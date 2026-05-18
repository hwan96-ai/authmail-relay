"""HTTP API wrapping email_service for service-to-service email sending."""
from __future__ import annotations

import hmac
import logging
import os
import threading
import time
import uuid
from collections import deque
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
) -> FastAPI:
    """Build the FastAPI app. Env vars are read only for arguments left as None."""
    if sender is None:
        sender = _build_sender_from_env()
    if api_key is None:
        api_key = _required_env("API_KEY")
    if rate_limiter is None:
        rate_limiter = _build_rate_limiter()

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
        _: None = Depends(verify_key),
    ) -> SendResult:
        if _is_dry_run(x_dry_run):
            return _DRY_RUN_RESULT
        rid = getattr(request.state, "request_id", None)
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
                _run_and_notify, _do_send, req.webhook_url, req.webhook_secret
            )
            return SendResult(
                sent=False, status="accepted", message=(
                    "Send queued; final result will be delivered via webhook"
                ),
            )
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
        return SendResult(
            sent=True,
            message_id=result.message_id,
            # Only surface status when it differs from default to preserve
            # backward-compatible response shape.
            status=status_val if status_val and status_val != "delivered" else None,
        )

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
        _: None = Depends(verify_key),
    ) -> SendResult:
        # Dry-run must succeed before the configuration check so that callers
        # can validate payloads even when MAGIC_LINK_BASE_URL is unset.
        if _is_dry_run(x_dry_run):
            return _DRY_RUN_RESULT
        if magic_link is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Magic link endpoint not configured (set MAGIC_LINK_BASE_URL)",
            )
        if req.webhook_url:
            def _do_send():
                return magic_link.send(req.to, req.user_name, req.token)
            background_tasks.add_task(
                _run_and_notify, _do_send, req.webhook_url, req.webhook_secret
            )
            return SendResult(sent=False, status="accepted")
        result = magic_link.send(req.to, req.user_name, req.token)
        if not result.sent:
            _fail(result)
        status_val = getattr(result, "status", None)
        return SendResult(
            sent=True,
            message_id=result.message_id,
            # Only surface status when it differs from default to preserve
            # backward-compatible response shape.
            status=status_val if status_val and status_val != "delivered" else None,
        )

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
        _: None = Depends(verify_key),
    ) -> SendResult:
        if _is_dry_run(x_dry_run):
            return _DRY_RUN_RESULT
        if req.webhook_url:
            def _do_send():
                return otp.send(req.to, req.user_name, req.code)
            background_tasks.add_task(
                _run_and_notify, _do_send, req.webhook_url, req.webhook_secret
            )
            return SendResult(sent=False, status="accepted")
        result = otp.send(req.to, req.user_name, req.code)
        if not result.sent:
            _fail(result)
        status_val = getattr(result, "status", None)
        return SendResult(
            sent=True,
            message_id=result.message_id,
            # Only surface status when it differs from default to preserve
            # backward-compatible response shape.
            status=status_val if status_val and status_val != "delivered" else None,
        )

    return app
