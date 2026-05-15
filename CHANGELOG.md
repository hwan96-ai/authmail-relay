# Changelog

All notable changes documented here. Format: [Keep a Changelog](https://keepachangelog.com/). Versioning: [SemVer](https://semver.org/).

## [0.2.0] - 2026-05-15

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

### Migration (0.1.x → 0.2.0)

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
