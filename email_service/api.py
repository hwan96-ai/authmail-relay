"""HTTP API wrapping email_service for service-to-service email sending."""
from __future__ import annotations

import hashlib
import hmac
import json as _json
import logging
import os
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator

from email_service import metrics as metrics_module
from email_service.notifiers import MagicLinkNotifier, OTPNotifier
from email_service.sender import SmtpConfig, SmtpSender
from email_service.url_validation import validate_webhook_url
from email_service.webhooks import deliver_webhook


# P0-3 (body size limits): caps for external input fields. Goal is to prevent
# OOM from a single oversized request (FastAPI buffers the whole body before
# Pydantic runs, and msg.as_string() doubles memory inside the SMTP path).
MAX_SUBJECT_LEN = 998       # RFC 5322 line-length cap
MAX_BODY_LEN = 10_000_000   # 10 MB per HTML/text body
MAX_RECIPIENTS = 100        # per-list cap on To/Cc/Bcc (1 + 100 + 100 worst)
MAX_USER_NAME_LEN = 256
MAX_TOKEN_LEN = 4096
MAX_CODE_LEN = 64
MAX_URL_LEN = 2048
MAX_SECRET_LEN = 256

logger = logging.getLogger(__name__)


def _required_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Required environment variable missing: {name}")
    return val


def _no_crlf(value: str) -> str:
    if "\r" in value or "\n" in value:
        raise ValueError("CRLF characters are not allowed")
    return value


def _validate_webhook_field(v: str | None) -> str | None:
    """P0-2: SSRF defense. Run only when a URL is provided."""
    if v is None:
        return v
    try:
        return validate_webhook_url(v)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


class SendEmailRequest(BaseModel):
    to: str = Field(min_length=1, max_length=320)  # RFC 5321 max email length
    subject: str = Field(min_length=1, max_length=MAX_SUBJECT_LEN)
    html_body: str = Field(min_length=1, max_length=MAX_BODY_LEN)
    text_body: str | None = Field(default=None, max_length=MAX_BODY_LEN)
    cc: list[str] | None = Field(default=None, max_length=MAX_RECIPIENTS)
    bcc: list[str] | None = Field(default=None, max_length=MAX_RECIPIENTS)
    webhook_url: str | None = Field(default=None, max_length=MAX_URL_LEN)
    webhook_secret: str | None = Field(default=None, max_length=MAX_SECRET_LEN)

    @field_validator("to", "subject")
    @classmethod
    def _reject_crlf(cls, v: str) -> str:
        return _no_crlf(v)

    @field_validator("cc", "bcc")
    @classmethod
    def _reject_crlf_list(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        for item in v:
            _no_crlf(item)
        return v

    @field_validator("webhook_url")
    @classmethod
    def _validate_webhook_url_safe(cls, v: str | None) -> str | None:
        return _validate_webhook_field(v)


class SendMagicLinkRequest(BaseModel):
    to: str = Field(min_length=1, max_length=320)
    user_name: str = Field(min_length=1, max_length=MAX_USER_NAME_LEN)
    token: str = Field(min_length=1, max_length=MAX_TOKEN_LEN)
    webhook_url: str | None = Field(default=None, max_length=MAX_URL_LEN)
    webhook_secret: str | None = Field(default=None, max_length=MAX_SECRET_LEN)

    @field_validator("to")
    @classmethod
    def _reject_crlf(cls, v: str) -> str:
        return _no_crlf(v)

    @field_validator("webhook_url")
    @classmethod
    def _validate_webhook_url_safe(cls, v: str | None) -> str | None:
        return _validate_webhook_field(v)


class SendOTPRequest(BaseModel):
    to: str = Field(min_length=1, max_length=320)
    user_name: str = Field(min_length=1, max_length=MAX_USER_NAME_LEN)
    code: str = Field(min_length=1, max_length=MAX_CODE_LEN)
    webhook_url: str | None = Field(default=None, max_length=MAX_URL_LEN)
    webhook_secret: str | None = Field(default=None, max_length=MAX_SECRET_LEN)

    @field_validator("to")
    @classmethod
    def _reject_crlf(cls, v: str) -> str:
        return _no_crlf(v)

    @field_validator("webhook_url")
    @classmethod
    def _validate_webhook_url_safe(cls, v: str | None) -> str | None:
        return _validate_webhook_field(v)


class SendResult(BaseModel):
    sent: bool
    dry_run: bool | None = None
    message: str | None = None
    message_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    refused: list[str] | None = None
    status: str | None = None


class ErrorResponse(BaseModel):
    """Body of 502 responses when SMTP delivery fails."""
    error_code: str
    message: str | None = None


_DRY_RUN_TRUE = {"true", "1", "yes"}


def _is_dry_run(value: str | None) -> bool:
    return value is not None and value.strip().lower() in _DRY_RUN_TRUE


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _DRY_RUN_TRUE


_DRY_RUN_RESULT = SendResult(
    sent=False, dry_run=True, message="Email payload is valid"
)


class _SlidingWindowLimiter:
    """Per-key sliding window. P0-4: protect SMTP reputation if API_KEY leaks.

    In-memory and per-process (multi-worker deployments use this as a
    per-worker cap, which is the intended behavior — a leaked key cannot
    burn out the SMTP provider even if it hits every worker). Bounded
    memory: at most ``max_requests`` timestamps per key.
    """

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max = max(0, int(max_requests))
        self._window = float(window_seconds)
        self._buckets: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._max > 0

    def check(self, key: str, *, now: float | None = None) -> tuple[bool, float]:
        """Return ``(allowed, retry_after_seconds)``.

        ``retry_after_seconds`` is the seconds until the oldest bucket entry
        ages out. 0.0 when allowed.
        """
        if not self.enabled:
            return True, 0.0
        t = now if now is not None else time.monotonic()
        cutoff = t - self._window
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = deque()
                self._buckets[key] = bucket
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self._max:
                # Reject. Retry-After = window - (now - oldest).
                retry_after = max(1.0, self._window - (t - bucket[0]))
                return False, retry_after
            bucket.append(t)
            return True, 0.0


def _build_rate_limiter() -> _SlidingWindowLimiter:
    raw = os.environ.get("API_RATE_LIMIT_PER_MINUTE", "60")
    try:
        limit = int(raw)
    except ValueError:
        limit = 60
    return _SlidingWindowLimiter(max_requests=limit, window_seconds=60.0)


# P1 idempotency: cap and TTL for the in-memory dedup cache.
MAX_IDEMPOTENCY_KEY_LEN = 128
_IDEMPOTENCY_MAX_ENTRIES = 10_000


def _body_fingerprint(req: BaseModel) -> str:
    """SHA-256 of the canonical JSON dump of a Pydantic request model.

    Used by the idempotency layer to detect that a caller reused an
    ``Idempotency-Key`` with a different request body (NEW-V-2). Excludes no
    fields: every field is part of the request's identity (different
    ``webhook_secret`` or ``webhook_url`` is a different request).
    """
    payload = req.model_dump(exclude_none=False, mode="json")
    canonical = _json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class _IdempotencyCache:
    """Per-bearer dedup of ``Idempotency-Key`` -> cached response.

    Bounded in size (oldest entries evicted) and TTL'd. In-memory, per-process.
    Multi-worker deployments use this as a per-worker cap; same key may be
    processed at most once per worker. For strong cross-worker dedup, replace
    with a Redis-backed store.

    Entries are cached only on **2xx** responses (and queued "accepted" async
    sends) to avoid re-serving an error.

    # Concurrency (P1 NEW-V-3)

    ``get_lock(bearer, key)`` returns a ``threading.Lock`` instance that callers
    hold across the lookup → process → store critical section. Per-key
    locking serializes only requests with the *same* key; requests with
    different keys run in parallel.

    # Body fingerprint (P1 NEW-V-2)

    Each entry stores a ``fingerprint`` (SHA-256 of the canonical request body).
    Callers MUST verify the fingerprint matches before returning a cached
    response, and reject mismatches with HTTP 409 — same key + different body
    is a contract violation, not a cache hit.
    """

    def __init__(self, *, ttl_seconds: float, max_entries: int) -> None:
        self._ttl = float(ttl_seconds)
        self._max = max(0, int(max_entries))
        # key = (bearer_token, idempotency_key)
        # value = {"expires": float, "fingerprint": str, "response": dict}
        self._store: dict[tuple[str, str], dict] = {}
        # Per-key processing lock (NEW-V-3). Lifetime tied to the cache entry —
        # evicted alongside the store entry.
        self._key_locks: dict[tuple[str, str], threading.Lock] = {}
        self._meta_lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._max > 0 and self._ttl > 0

    def get_lock(self, bearer: str, key: str) -> threading.Lock:
        """Return the per-key lock (creates one if absent).

        Holding this lock serializes only requests with the same
        ``(bearer, key)`` — different keys remain parallel.
        """
        composite = (bearer, key)
        with self._meta_lock:
            lock = self._key_locks.get(composite)
            if lock is None:
                lock = threading.Lock()
                self._key_locks[composite] = lock
            return lock

    def _evict_expired_locked(self, now: float) -> None:
        # Cheap pass: scan and drop expired. Bounded by _max so worst-case
        # cost is O(_max). Also drops the matching key lock.
        expired = [k for k, e in self._store.items() if e["expires"] <= now]
        for k in expired:
            self._store.pop(k, None)
            self._key_locks.pop(k, None)

    def get(
        self, bearer: str, key: str, *, now: float | None = None
    ) -> dict | None:
        """Return the cached entry dict ``{"fingerprint": ..., "response": ...}``
        or ``None`` when absent / expired.
        """
        if not self.enabled:
            return None
        t = now if now is not None else time.monotonic()
        with self._meta_lock:
            entry = self._store.get((bearer, key))
            if entry is None:
                return None
            if entry["expires"] <= t:
                self._store.pop((bearer, key), None)
                self._key_locks.pop((bearer, key), None)
                return None
            # Return the entry (caller reads fingerprint + response).
            return {
                "fingerprint": entry["fingerprint"],
                "response": entry["response"],
            }

    def put(
        self,
        bearer: str,
        key: str,
        fingerprint: str,
        response: dict,
        *,
        now: float | None = None,
    ) -> None:
        if not self.enabled:
            return
        t = now if now is not None else time.monotonic()
        with self._meta_lock:
            if len(self._store) >= self._max:
                self._evict_expired_locked(t)
                # Still full? Drop the oldest by expiry to make room.
                if len(self._store) >= self._max:
                    oldest_key = min(
                        self._store, key=lambda k: self._store[k]["expires"]
                    )
                    self._store.pop(oldest_key, None)
                    self._key_locks.pop(oldest_key, None)
            self._store[(bearer, key)] = {
                "expires": t + self._ttl,
                "fingerprint": fingerprint,
                "response": response,
            }


def _build_idempotency_cache() -> _IdempotencyCache:
    raw_ttl = os.environ.get("API_IDEMPOTENCY_TTL_SECONDS", "86400")
    try:
        ttl = float(raw_ttl)
    except ValueError:
        ttl = 86400.0
    return _IdempotencyCache(
        ttl_seconds=ttl, max_entries=_IDEMPOTENCY_MAX_ENTRIES
    )


def _build_sender_from_env() -> SmtpSender:
    # SMTP_USER/PASSWORD are optional so that no-auth SMTP servers
    # (Mailpit, MailHog, ...) can be used via docker-compose.dev.yml.
    from_addr = os.environ.get("SMTP_FROM", "")
    if from_addr:
        try:
            _no_crlf(from_addr)
        except ValueError as exc:
            raise RuntimeError(
                "SMTP_FROM contains CRLF characters and would enable header "
                "injection"
            ) from exc
    return SmtpSender(SmtpConfig(
        host=_required_env("SMTP_HOST"),
        port=int(os.environ.get("SMTP_PORT", "587")),
        user=os.environ.get("SMTP_USER", ""),
        password=os.environ.get("SMTP_PASSWORD", ""),
        from_addr=from_addr,
        use_tls=os.environ.get("SMTP_USE_TLS", "true").lower() != "false",
    ))


def create_app(
    *,
    sender: SmtpSender | None = None,
    api_key: str | None = None,
    magic_link: MagicLinkNotifier | None = None,
    otp: OTPNotifier | None = None,
    rate_limiter: _SlidingWindowLimiter | None = None,
    idempotency_cache: _IdempotencyCache | None = None,
) -> FastAPI:
    """Build the FastAPI app. Env vars are read only for arguments left as None."""
    if sender is None:
        sender = _build_sender_from_env()
    if api_key is None:
        api_key = _required_env("API_KEY")
    if rate_limiter is None:
        rate_limiter = _build_rate_limiter()
    if idempotency_cache is None:
        idempotency_cache = _build_idempotency_cache()

    if magic_link is None:
        base_url = os.environ.get("MAGIC_LINK_BASE_URL")
        if base_url:
            magic_link = MagicLinkNotifier(sender, base_url=base_url)
    if otp is None:
        otp = OTPNotifier(sender)

    app = FastAPI(
        title="email-service",
        version="0.2.0",
        description=(
            "SMTP-based HTML email service with magic-link and OTP notifiers. "
            "All write endpoints require Bearer authentication and support "
            "`X-Dry-Run: true` for payload validation without sending. "
            "Async delivery is available by including a `webhook_url` in the "
            "request body."
        ),
        contact={
            "name": "email-service",
            "url": "https://github.com/hwan96-ai/email-service",
        },
        openapi_tags=[
            {"name": "Email", "description": "Email send endpoints."},
            {"name": "Health", "description": "Liveness / readiness probes."},
            {"name": "Metrics", "description": "Prometheus metrics endpoint."},
        ],
    )
    bearer = HTTPBearer(auto_error=False)

    @app.middleware("http")
    async def trace_id_middleware(request: Request, call_next):
        tid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        # Make trace id available to route handlers via request.state.
        request.state.request_id = tid
        response = await call_next(request)
        response.headers["X-Request-ID"] = tid
        return response

    def _metrics_auth(request: Request) -> None:
        if not _truthy(os.environ.get("METRICS_REQUIRE_AUTH")):
            return
        auth = request.headers.get("authorization", "")
        token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
        if not token or not hmac.compare_digest(token, api_key):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key"
            )

    @app.get(
        "/metrics",
        summary="Prometheus metrics",
        tags=["Metrics"],
        description=(
            "Prometheus exposition format. Returns 404 when prometheus-client "
            "is not installed. Optionally protected by `METRICS_REQUIRE_AUTH=true`."
        ),
        response_description="Plain-text Prometheus exposition.",
    )
    def metrics(request: Request) -> Response:
        if not metrics_module.metrics_available():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "metrics disabled")
        _metrics_auth(request)
        body, content_type = metrics_module.render_latest()
        return Response(content=body, media_type=content_type)

    def verify_key(
        creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> None:
        if creds is None or not hmac.compare_digest(creds.credentials, api_key):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key"
            )

    def rate_limit(
        creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> None:
        """P0-4: cap requests per API key to protect SMTP reputation."""
        if not rate_limiter.enabled:
            return
        # Bucket by bearer token (single shared key today, but works correctly
        # when multi-key support is added later).
        key = creds.credentials if creds is not None else "_anon"
        allowed, retry_after = rate_limiter.check(key)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(int(retry_after) or 1)},
            )

    def _check_idempotency_key(value: str | None) -> str | None:
        """Validate header shape only. Returns the key when valid."""
        if value is None:
            return None
        v = value.strip()
        if not v:
            return None
        if len(v) > MAX_IDEMPOTENCY_KEY_LEN:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Idempotency-Key length exceeds "
                    f"{MAX_IDEMPOTENCY_KEY_LEN} characters"
                ),
            )
        return v

    def _bearer_of(creds: HTTPAuthorizationCredentials | None) -> str:
        return creds.credentials if creds is not None else "_anon"

    @contextmanager
    def _idempotency_guard(
        creds: HTTPAuthorizationCredentials | None,
        idem_key: str | None,
        fingerprint: str,
    ):
        """Critical section for idempotent send.

        - ``idem_key is None`` or cache disabled: yields ``None``, no locking.
        - Cache hit with matching fingerprint: yields the cached response dict.
        - Cache hit with different fingerprint: raises HTTP 409.
        - Cache miss: yields ``None`` while holding a per-key lock so that any
          concurrent caller with the same key waits until this handler stores
          its result (NEW-V-3).

        Caller is expected to call ``_idempotency_remember`` inside the with
        block on cache-miss so that storage happens while the lock is held.
        """
        if idem_key is None or not idempotency_cache.enabled:
            yield None
            return
        bearer_tok = _bearer_of(creds)
        lock = idempotency_cache.get_lock(bearer_tok, idem_key)
        lock.acquire()
        try:
            existing = idempotency_cache.get(bearer_tok, idem_key)
            if existing is not None:
                if not hmac.compare_digest(
                    existing["fingerprint"], fingerprint
                ):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            "Idempotency-Key was previously used with a "
                            "different request body"
                        ),
                    )
                yield existing["response"]
            else:
                yield None
        finally:
            lock.release()

    def _idempotency_remember(
        creds: HTTPAuthorizationCredentials | None,
        idem_key: str | None,
        fingerprint: str,
        result: SendResult,
    ) -> None:
        """Cache a successful or queued result. Failures are NOT cached so
        the caller can retry after fixing the upstream cause."""
        if idem_key is None or not idempotency_cache.enabled:
            return
        if not (result.sent or result.status == "accepted"):
            return
        idempotency_cache.put(
            _bearer_of(creds),
            idem_key,
            fingerprint,
            result.model_dump(exclude_none=True),
        )

    @app.get(
        "/health",
        summary="Health check",
        tags=["Health"],
        description="Liveness probe. Always returns `{\"status\": \"ok\"}` when the process is running.",
        response_description="Always `{\"status\": \"ok\"}`.",
    )
    def health() -> dict[str, str]:
        return {"status": "ok"}

    _failure_responses = {
        401: {"description": "Invalid or missing API key"},
        502: {"model": ErrorResponse, "description": "Email send failed"},
    }

    def _fail(result) -> None:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail={
                "error_code": result.error_code,
                "message": result.error_message,
            },
        )

    def _result_to_payload(result, message_id: str | None) -> dict:
        return {
            "message_id": message_id or result.message_id,
            "status": getattr(result, "status", None)
                or ("delivered" if result.sent else "failed"),
            "error_code": result.error_code,
            "refused": list(result.refused) if result.refused else [],
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "attempts": getattr(result, "attempts", 1),
        }

    def _run_and_notify(send_fn, webhook_url: str, webhook_secret: str | None):
        """Background task: invoke ``send_fn``, then POST result to webhook."""
        try:
            result = send_fn()
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Background send raised")
            payload = {
                "message_id": None,
                "status": "failed",
                "error_code": "unknown",
                "refused": [],
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "attempts": 1,
                "error_message": str(exc),
            }
            deliver_webhook(webhook_url, payload, webhook_secret)
            return
        payload = _result_to_payload(result, getattr(result, "message_id", None))
        deliver_webhook(webhook_url, payload, webhook_secret)

    @app.post(
        "/send",
        response_model=SendResult,
        response_model_exclude_none=True,
        responses=_failure_responses,
        summary="Send raw HTML email",
        tags=["Email"],
        description=(
            "Send an arbitrary HTML email. Use `X-Dry-Run: true` to validate "
            "the payload without contacting SMTP. Include `webhook_url` in the "
            "body to deliver asynchronously and receive the result by webhook."
        ),
        response_description="Send result with message id and delivery status.",
    )
    def send_email(
        req: SendEmailRequest,
        request: Request,
        background_tasks: BackgroundTasks,
        x_dry_run: str | None = Header(default=None, alias="X-Dry-Run"),
        idempotency_key: str | None = Header(
            default=None, alias="Idempotency-Key"
        ),
        creds: HTTPAuthorizationCredentials | None = Depends(bearer),
        _: None = Depends(verify_key),
        __: None = Depends(rate_limit),
    ) -> SendResult:
        if _is_dry_run(x_dry_run):
            return _DRY_RUN_RESULT
        idem_key = _check_idempotency_key(idempotency_key)
        fingerprint = _body_fingerprint(req) if idem_key else ""
        rid = getattr(request.state, "request_id", None)
        with _idempotency_guard(creds, idem_key, fingerprint) as cached:
            if cached is not None:
                return SendResult(**cached)
            if req.webhook_url:
                def _do_send():
                    return sender.send(
                        to=req.to,
                        subject=req.subject,
                        html_body=req.html_body,
                        text_body=req.text_body,
                        cc=req.cc,
                        bcc=req.bcc,
                        request_id=rid,
                    )
                background_tasks.add_task(
                    _run_and_notify, _do_send,
                    req.webhook_url, req.webhook_secret,
                )
                queued = SendResult(
                    sent=False, status="accepted", message=(
                        "Send queued; final result will be delivered "
                        "via webhook"
                    ),
                )
                _idempotency_remember(creds, idem_key, fingerprint, queued)
                return queued
            result = sender.send(
                to=req.to,
                subject=req.subject,
                html_body=req.html_body,
                text_body=req.text_body,
                cc=req.cc,
                bcc=req.bcc,
                request_id=rid,
            )
            if not result.sent:
                _fail(result)
            status_val = getattr(result, "status", None)
            response = SendResult(
                sent=True,
                message_id=result.message_id,
                # Only surface status when it differs from default to preserve
                # backward-compatible response shape.
                status=(
                    status_val
                    if status_val and status_val != "delivered"
                    else None
                ),
            )
            _idempotency_remember(creds, idem_key, fingerprint, response)
            return response

    @app.post(
        "/send/magic-link",
        response_model=SendResult,
        response_model_exclude_none=True,
        responses=_failure_responses,
        summary="Send password-setup magic link",
        tags=["Email"],
        description=(
            "Send a password-setup magic link to the user. Requires "
            "`MAGIC_LINK_BASE_URL` to be configured at startup. The token is "
            "URL-encoded automatically."
        ),
        response_description="Send result with message id and delivery status.",
    )
    def send_magic_link(
        req: SendMagicLinkRequest,
        background_tasks: BackgroundTasks,
        x_dry_run: str | None = Header(default=None, alias="X-Dry-Run"),
        idempotency_key: str | None = Header(
            default=None, alias="Idempotency-Key"
        ),
        creds: HTTPAuthorizationCredentials | None = Depends(bearer),
        _: None = Depends(verify_key),
        __: None = Depends(rate_limit),
    ) -> SendResult:
        # Dry-run must succeed before the configuration check so that callers
        # can validate payloads even when MAGIC_LINK_BASE_URL is unset.
        if _is_dry_run(x_dry_run):
            return _DRY_RUN_RESULT
        idem_key = _check_idempotency_key(idempotency_key)
        fingerprint = _body_fingerprint(req) if idem_key else ""
        with _idempotency_guard(creds, idem_key, fingerprint) as cached:
            if cached is not None:
                return SendResult(**cached)
            if magic_link is None:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "Magic link endpoint not configured "
                    "(set MAGIC_LINK_BASE_URL)",
                )
            if req.webhook_url:
                def _do_send():
                    return magic_link.send(req.to, req.user_name, req.token)
                background_tasks.add_task(
                    _run_and_notify, _do_send,
                    req.webhook_url, req.webhook_secret,
                )
                queued = SendResult(sent=False, status="accepted")
                _idempotency_remember(creds, idem_key, fingerprint, queued)
                return queued
            result = magic_link.send(req.to, req.user_name, req.token)
            if not result.sent:
                _fail(result)
            status_val = getattr(result, "status", None)
            response = SendResult(
                sent=True,
                message_id=result.message_id,
                status=(
                    status_val
                    if status_val and status_val != "delivered"
                    else None
                ),
            )
            _idempotency_remember(creds, idem_key, fingerprint, response)
            return response

    @app.post(
        "/send/otp",
        response_model=SendResult,
        response_model_exclude_none=True,
        responses=_failure_responses,
        summary="Send one-time password (OTP)",
        tags=["Email"],
        description=(
            "Send a one-time password code via email. The `code` field is "
            "rendered verbatim into the email body — generate it on the caller "
            "side."
        ),
        response_description="Send result with message id and delivery status.",
    )
    def send_otp(
        req: SendOTPRequest,
        background_tasks: BackgroundTasks,
        x_dry_run: str | None = Header(default=None, alias="X-Dry-Run"),
        idempotency_key: str | None = Header(
            default=None, alias="Idempotency-Key"
        ),
        creds: HTTPAuthorizationCredentials | None = Depends(bearer),
        _: None = Depends(verify_key),
        __: None = Depends(rate_limit),
    ) -> SendResult:
        if _is_dry_run(x_dry_run):
            return _DRY_RUN_RESULT
        idem_key = _check_idempotency_key(idempotency_key)
        fingerprint = _body_fingerprint(req) if idem_key else ""
        with _idempotency_guard(creds, idem_key, fingerprint) as cached:
            if cached is not None:
                return SendResult(**cached)
            if req.webhook_url:
                def _do_send():
                    return otp.send(req.to, req.user_name, req.code)
                background_tasks.add_task(
                    _run_and_notify, _do_send,
                    req.webhook_url, req.webhook_secret,
                )
                queued = SendResult(sent=False, status="accepted")
                _idempotency_remember(creds, idem_key, fingerprint, queued)
                return queued
            result = otp.send(req.to, req.user_name, req.code)
            if not result.sent:
                _fail(result)
            status_val = getattr(result, "status", None)
            response = SendResult(
                sent=True,
                message_id=result.message_id,
                status=(
                    status_val
                    if status_val and status_val != "delivered"
                    else None
                ),
            )
            _idempotency_remember(creds, idem_key, fingerprint, response)
            return response

    return app
