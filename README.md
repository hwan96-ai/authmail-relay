# email-service

[![PyPI](https://img.shields.io/pypi/v/hwan-email-service.svg)](https://pypi.org/project/hwan-email-service/)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.10-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> Small self-hosted auth-email service for Python/FastAPI teams using their own SMTP.

[한국어 README](README.ko.md) · [HTML Usage Guide](docs/usage.html) · [한국어 사용 가이드](docs/usage.ko.html)

`email-service` is a small, self-hosted service that sends **magic-link**, **OTP**,
and **password-reset** emails through your own SMTP account. It keeps SMTP
credentials and email-template logic out of every app that needs to send auth
mail — your apps call one internal HTTP endpoint with a Bearer API key, or
import it as a Python library.

```text
App / Auth server
      │  Bearer API key
      ▼
  email-service     ← SMTP credentials live here
      │
      ▼
 SMTP provider  ──►  User inbox
```

### What it is

- A small internal **auth-email gateway** for teams that already have SMTP.
- Sends transactional auth emails: magic links, OTP codes, password resets,
  plus arbitrary templated mail.
- Built for Python/FastAPI teams, but the HTTP API is language-agnostic.

### What it is *not*

- **Not a mail server** — it talks to your existing SMTP provider (Gmail, SES
  SMTP, an internal relay, etc.). It does not accept inbound mail or handle MX.
- **Not a full auth platform** — it sends auth emails; it does not generate,
  store, verify, or expire login tokens, manage sessions, or store users.
- **Not a marketing/bulk-email platform** — no bounce processing, suppression
  lists, analytics dashboards, or deliverability tooling.
- **Not a managed-email replacement** for Resend, Postmark, SendGrid, Mailgun,
  or SES — those bring deliverability, reputation, and SLAs that a small
  self-hosted gateway cannot match. See [alternatives](docs/alternatives.md).

---

## Package names

The repo name, PyPI distribution name, and Python import package differ.

| | Name |
|---|---|
| Repository / service | `email-service` |
| PyPI distribution | `hwan-email-service` |
| Python import | `email_service` |

```bash
pip install hwan-email-service
```

```python
import email_service
```

---

## Install

```bash
# Library mode (no extra deps)
pip install hwan-email-service

# HTTP service mode (FastAPI + uvicorn)
pip install "hwan-email-service[http]"
```

Requirements: **Python 3.10+**.

Install the latest unreleased commit straight from git:

```bash
pip install "hwan-email-service[http] @ git+https://github.com/hwan96-ai/email-service.git"
```

---

## Quickstart — HTTP service mode

Run `email-service` as a standalone service. Other apps call it over HTTP with
a Bearer API key. SMTP credentials live in this service's environment only.

```bash
pip install "hwan-email-service[http]"

export SMTP_HOST=smtp.gmail.com
export SMTP_USER=sender@gmail.com
export SMTP_PASSWORD=app-password
export API_KEY=$(openssl rand -hex 32)

python -m email_service
# → Uvicorn running on http://127.0.0.1:8000
```

In another terminal:

```bash
curl -X POST http://127.0.0.1:8000/send \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to":"user@example.com","subject":"Hi","html_body":"<p>Hello</p>"}'
# → {"sent":true}
```

OpenAPI docs: <http://127.0.0.1:8000/docs>.

Full HTTP endpoint reference, dry-run mode, idempotency, and the Python client
SDK: [docs/api.md](docs/api.md).

### 30-second SMTP smoke test

If you just want to verify SMTP credentials, skip the HTTP server entirely:

```bash
export SMTP_HOST=smtp.gmail.com
export SMTP_USER=sender@gmail.com
export SMTP_PASSWORD=app-password

python -m email_service test --to me@example.com
#   → SendResult(sent=True, error_code=None, ..., message_id='<...@host>')
```

Exits `0` on success, `1` on failure with `error_code` printed.

---

## Quickstart — library mode

Import `email_service` directly inside one Python/FastAPI app. Useful when you
don't need a separate internal HTTP gateway.

```python
from email_service import SmtpSender, MagicLinkNotifier, OTPNotifier
from email_service.sender import SmtpConfig

sender = SmtpSender(SmtpConfig(
    host="smtp.gmail.com",
    user="sender@gmail.com",
    password="app-password",
))

# One-off HTML mail
sender.send("user@example.com", "Hi", "<p>Hello</p>")

# Magic link
MagicLinkNotifier(sender, base_url="https://myapp.com").send(
    "user@example.com", "User Name", "abc123token",
)

# OTP
OTPNotifier(sender).send("user@example.com", "User Name", "482901")
```

Full library API (`SmtpSender`, `MagicLinkNotifier`, `OTPNotifier`,
`TemplateNotifier`, custom notifiers, retries): [docs/api.md](docs/api.md#library-mode).

---

## Security — read before deploying

`email-service` is designed as an **internal** service. A self-hosted auth
email service can be abused if exposed incorrectly. Treat the following as
hard requirements before any production deploy:

- **Do not expose directly to the public internet.** Put it behind a reverse
  proxy or API gateway on a private network / VPC.
- **Terminate TLS at the edge** (nginx, Traefik, your gateway).
- **Rate-limit failed auth attempts at the edge.** The app's built-in
  per-bearer rate limit applies to *authenticated* requests; it does not
  protect against blind Bearer-token guessing.
- **Protect `/docs` and `/metrics`** — either disable at the edge or require
  auth. Set `METRICS_REQUIRE_AUTH=true` for `/metrics`.
- **Store `API_KEY`, `WEBHOOK_SECRET`, and SMTP credentials in environment
  variables or a secret manager.** Generate `API_KEY` with
  `openssl rand -hex 32`. Never commit them.

**Trust boundary:** this service sends auth emails. It does **not** generate,
store, verify, or expire login tokens. The caller is responsible for token
entropy (at least `secrets.token_urlsafe(32)`), expiration, single-use
enforcement, replay protection, and account-state checks.

For the full production checklist, see [docs/deployment.md](docs/deployment.md).
Vulnerability reporting: [SECURITY.md](SECURITY.md).

---

## Docker

```bash
cp .env.example .env
# Edit .env: set SMTP_HOST / SMTP_USER / SMTP_PASSWORD / API_KEY
#   API_KEY=$(openssl rand -hex 32)

docker compose up -d --build
curl http://127.0.0.1:8000/health   # → {"status":"ok"}
```

The provided `docker-compose.yml` publishes `8000:8000` on the host for
convenience. **Do not expose this port to the public internet** — see the
deployment guide for production hardening.

Local development with [Mailpit](https://mailpit.axllent.org/) (no real SMTP
needed):

```bash
docker compose -f docker-compose.dev.yml up -d --build
# Mailpit UI: http://127.0.0.1:8025
```

---

## Configuration

Required env vars: `SMTP_HOST`, `API_KEY`.

The service fails fast at startup if required vars are missing.

Full env-var reference (rate limits, idempotency, webhook SSRF allowlist,
metrics auth, structured logs, retry tuning): [docs/configuration.md](docs/configuration.md).

A working `.env.example` is included in the repo root.

---

## Webhooks (async send)

Pass `webhook_url` in a `/send*` request body to receive the delivery result
asynchronously. The service signs the payload with both a legacy V1 header and
a V2 timestamp-bound header; new receivers should validate V2.

Webhook payload format, signature verification, the V1 → V2 migration, and
local testing with `docker-compose.dev.yml`: [docs/webhooks.md](docs/webhooks.md).

---

## Observability

Opt-in features, all off by default:

- **Prometheus metrics** at `/metrics` (`METRICS_ENABLED=true`,
  `METRICS_REQUIRE_AUTH=true` recommended).
- **Structured JSON logs** (`EMAIL_SERVICE_LOG_FORMAT=json`). Recipient
  addresses are hashed (SHA-256, first 8 chars) — never logged in plaintext.
- **`X-Request-ID` propagation** end-to-end from gateway → email-service →
  SMTP send logs.
- **SMTP retries** with bounded exponential backoff (library mode,
  `max_retries=N`).

Full operations guide: [docs/operations.md](docs/operations.md).

---

## Examples

End-to-end integration snippets for common Python frameworks:

- [examples/fastapi_integration.py](examples/fastapi_integration.py)
- [examples/django_integration.py](examples/django_integration.py)
- [examples/flask_integration.py](examples/flask_integration.py)
- [examples/integration_test_with_capture.py](examples/integration_test_with_capture.py)
  — `.eml` capture mode for integration tests without a real SMTP server.

---

## When to use what

| If you need… | Use |
|---|---|
| Managed deliverability, bounces, SLA, dashboards | Resend / Postmark / SendGrid / Mailgun / Amazon SES |
| Full user/session/RBAC/password flows | Supabase Auth, Ory Kratos, Keycloak, Authentik, Appwrite |
| A mail library inside one FastAPI app | [fastapi-mail](https://github.com/sabuhish/fastapi-mail) |
| An internal HTTP gateway that keeps your existing SMTP credentials out of every app | **email-service** |

A longer comparison, including self-hosted email platforms, lives in
[docs/alternatives.md](docs/alternatives.md).

---

## Development

```bash
git clone https://github.com/hwan96-ai/email-service.git
cd email-service

pip install -e ".[dev,http]"
python -m pytest tests/ -v
```

Tests do not connect to a real SMTP server (`smtplib.SMTP` is mocked).

---

## License

[MIT](LICENSE).
