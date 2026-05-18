# Changelog

All notable changes documented here. Format: [Keep a Changelog](https://keepachangelog.com/). Versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Release pipeline

- `release.yml`: split into a 2-step manual gate. Tag push now runs `build-and-smoke` only — it no longer triggers PyPI publish. Publishing requires explicit `workflow_dispatch` from the Actions UI with the target tag as input. Rationale: private repos may not expose Environment "Required reviewers", so the `environment: pypi` gate alone could not guarantee manual approval. The workflow_dispatch invocation IS the human approval gate. Required reviewers, if available, layers on top.

## [0.4.0] - 2026-05-18

Security and reliability hardening. **No breaking changes to the existing response schema** — additive only. SDK callers do NOT need code changes.

### Security (P0)

- **SSRF defense on `webhook_url`** (CVE-class). Pydantic field validation rejects non-http(s) schemes, IP literals (loopback/link-local/private/multicast/reserved), and hostnames that resolve to those addresses. Re-validates on every retry attempt (defeats inter-retry DNS rebinding). New env vars: `WEBHOOK_ALLOW_HOSTS` (allowlist), `WEBHOOK_ALLOW_LOOPBACK` (test-only).
- **Request size caps** on `subject` (≤998 chars, RFC 5322), `html_body`/`text_body` (≤10 MB each), `cc`/`bcc` (≤100 each), `Idempotency-Key` (≤128). Returns 422 on overflow.
- **Per-bearer rate limit** on `/send*` endpoints. New env var `API_RATE_LIMIT_PER_MINUTE` (default 60). Returns 429 with `Retry-After` header. **In-memory, per-process** — see Deployment notes for multi-worker caveat.
- **Bounded retry backoff** on webhook delivery. Was `(1, 10, 60)` = 71 s max; now `(1, 2, 5)` with ±25% jitter = ≤8 s. Prevents threadpool starvation from background tasks.
- **`SMTPServerDisconnected` phase-aware retry**. Post-`sendmail()` disconnect is treated as delivered (no retry → no duplicate send). Mid-`sendmail()` disconnect returns new non-retriable error `ERR_SMTP_DISCONNECT_UNCERTAIN`. See `docs/runbooks/smtp-disconnect-uncertain.md`.

### Security (P1)

- **HTTP idempotency** via `Idempotency-Key` header. Body fingerprint (SHA-256 of canonical request JSON) prevents same-key + different-body collisions — returns 409 on mismatch. Per-key locking prevents concurrent duplicate execution. In-memory TTL cache. New env var `API_IDEMPOTENCY_TTL_SECONDS` (default 86400).
- **Webhook HMAC V2 signature** for replay defense. New headers `X-Email-Service-Signature-V2` (HMAC over `"<timestamp>.<body>"`) and `X-Email-Service-Timestamp` (Unix epoch). V1 (`X-Email-Service-Signature`, body only) preserved for backward compat. **V1 receivers remain vulnerable to indefinite replay** — migrate to V2 (verify timestamp within ±5 min + V2 signature). V1 will be removed in a future major version.

### Release pipeline

- `release.yml`: all third-party actions pinned to commit SHA (was mutable tags). New `build-and-smoke` job builds the wheel, installs into a clean venv, verifies imports + version, and confirms the pushed tag matches `pyproject.toml`. `publish` job depends on `build-and-smoke` and uses the `pypi` GitHub Environment (configure **Required reviewers** in repo settings for manual approval).
- `email_service.__version__` is now sourced from `importlib.metadata` (single source of truth = `pyproject.toml`). `FastAPI(version=...)` and the OpenAPI document follow.

### Operational documentation

- `docs/runbooks/`: 5 runbooks for SMTP outage, webhook outage, `API_KEY` rotation, PyPI yank/hotfix, and `smtp_disconnect_uncertain` triage.
- README: new Deployment section (single vs multi worker, reverse-proxy body cap, env-var table, V1 deprecation notice).

### Known limitations (tracked, not release blockers for single-tenant)

- `SmtpSender` retry uses synchronous `time.sleep` (max 31 s budget). Acceptable for single-worker / low-throughput deployments; consider `aiosmtplib` migration for high concurrency.
- In-memory rate limit + idempotency cache + per-key locks → per-process state. Multi-worker uvicorn → caps multiply by worker count. Use single worker or replace with Redis-backed store for strict cross-worker semantics.
- `webhook_url` validator runs in the BackgroundTask; sub-attempt DNS-rebinding window (~ms between validate and httpx connect) is still theoretically open. Full elimination requires IP pinning via httpx transport.
- Linux glibc `inet_aton`-compatible numeric host forms (e.g., `http://2130706433/`) were not verified in this release window. Behaviour on Windows getaddrinfo: rejected. Linux production deployment should run a one-time check (`docker run --rm python:3.12-slim python -c "import socket; print(socket.getaddrinfo('2130706433', None))"`).

## [0.3.0] - 2026-05-15

> Renamed from the pre-allocated `0.2.0` tag (which already pointed at an unreleased commit). Content unchanged from the 5-phase refactor work — this is the first published release after that work.

### Changed (BREAKING)

- `SmtpSender.send` now returns `SendResult` instead of `bool`. Use `result.sent` or rely on `__bool__`.
- 502 responses now include `{"error_code", "message"}` detail.
- `EmailServiceClient` raises `EmailServiceError` on send failure with `.error_code`.

### Added

- `SendResult` dataclass with structured error reporting (`error_code`, `error_message`, `refused`, `message_id`).
- Error code module constants in `email_service.sender`: `ERR_CRLF_IN_HEADER`, `ERR_SMTP_AUTH_FAILED`, `ERR_SMTP_CONNECTION`, `ERR_SMTP_TIMEOUT`, `ERR_RECIPIENT_REFUSED`, `ERR_STARTTLS_UNSUPPORTED`, `ERR_TEMPLATE_NOT_CONFIGURED`, `ERR_UNKNOWN`.
- `python -m email_service test --to <addr>` 1-shot CLI for testing SMTP config.
- `EmailServiceError` exception in `email_service.client` carrying `.error_code`, `.message`, `.status_code`.
- API responses now include `message_id` (from RFC 5322 Message-ID header) on success.
- OpenAPI `responses` schema now documents 401 and 502 shapes via `ErrorResponse`.

### Added (observability — phase 3)

- Optional `/metrics` Prometheus endpoint (`METRICS_ENABLED=true`, with `prometheus-client` installed).
- Optional JSON logging (`EMAIL_SERVICE_LOG_FORMAT=json`).
- `X-Request-ID` middleware — echoes incoming header, generates UUID if absent, propagates to sender logs.
- PII-safe recipient hashing (`hash_recipient`) — recipients never logged in plaintext.
- `EMAIL_SERVICE_DEBUG=1` enables `smtplib.set_debuglevel(1)` (dev-only — exposes AUTH lines, see README warning).

### Added (reliability — phase 4)

- Retry with exponential backoff: `SmtpSender(max_retries=3, backoff_seconds=(1, 5, 25))`. Retries `SMTPServerDisconnected`, `SMTPConnectError`, `socket.timeout`, SMTP 4xx. 5xx and partial refusal do not retry. Message-ID stable across retries.
- Test-capture mode: `EMAIL_TEST_CAPTURE_DIR=/path` writes each message as `.eml` file and skips SMTP. Distinct from `dry_run` (which only validates payload).
- Webhook callback: per-request `webhook_url` + `webhook_secret` fields. Final result POSTed asynchronously via FastAPI `BackgroundTasks` with HMAC-SHA256 signature header. Self-retries `(1s, 10s, 60s)`.
- New `email_service/webhooks.py` module + `email_webhook_failed_total` metric.
- dev compose webhook-sink (`kennethreitz/httpbin`) for local testing.

### Added (polish — phase 5)

- Email templates: WCAG AA color contrast (`#595959` fine print), `<html lang>`, viewport meta, 600px responsive container, `prefers-color-scheme: dark` support.
- i18n: `MagicLinkNotifier(subject=..., html_template=..., text_template=...)` and same for `OTPNotifier` — caller can override Korean defaults.
- Plain-text alternative now auto-generated by MagicLink/OTP notifiers (consistent with `TemplateNotifier`).
- `AsyncEmailServiceClient` (in `email_service.async_client`) — async/await variant of the sync SDK.
- FastAPI OpenAPI: every route now has `summary`, `tags`, `description`, `response_description`. App-level `version`, `description`, `contact`, `openapi_tags`.
- Example integrations: `examples/{flask,fastapi,django}_integration.py` + `integration_test_with_capture.py`.
- `CONTRIBUTING.md` + GitHub issue templates.

### Security (phase 1)

- STARTTLS now uses `ssl.create_default_context()` and aborts (returns `False`) when the server does not advertise STARTTLS.
- `SMTP_FROM` env var is validated for CRLF characters at boot — fail-fast with `RuntimeError`.
- `docker-compose.dev.yml` requires `API_KEY` via `${API_KEY:?Set API_KEY in .env}` — no more hardcoded `dev-secret`.
- Dependency floors pinned: `fastapi>=0.115,<1`, `uvicorn>=0.30,<1`, `httpx>=0.27,<1`.
- README adds "Security Model" section noting caller responsibility for magic-link token entropy.

### Fixed

- `/send/magic-link` now honors `X-Dry-Run` before the `MAGIC_LINK_BASE_URL` config check, matching `/send` and `/send/otp` semantics.

### Migration (0.1.x → 0.3.0)

Before:

```python
if sender.send(to, subj, html):
    ...
```

After (option A — backward-compat via `__bool__`): same code works unchanged.

After (option B — recommended): branch on structured error code.

```python
result = sender.send(to, subj, html)
if not result.sent:
    log.error("send failed: %s — %s", result.error_code, result.error_message)
```

For the HTTP client, catch `EmailServiceError`:

```python
from email_service.client import EmailServiceClient, EmailServiceError

with EmailServiceClient(url, key) as c:
    try:
        c.send_otp("user@example.com", "홍길동", "482901")
    except EmailServiceError as e:
        if e.error_code == "smtp_timeout":
            retry(...)
        else:
            raise
```

## [0.1.0] - 2026-05-01

### Added

- Initial release. SMTP sender, magic-link / OTP notifiers, FastAPI HTTP service.
- CRLF header injection guards (sender + Pydantic).
- STARTTLS-required mode that aborts when the server does not advertise STARTTLS.
- `HTTP_DRY_RUN` support via `X-Dry-Run` header for payload validation in CI.
- `EmailServiceClient` sync SDK wrapping `httpx`.
- Docker / docker-compose deployment artifacts.
