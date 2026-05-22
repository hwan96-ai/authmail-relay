# Configuration

All HTTP-mode configuration is via environment variables. In library mode, most
of these are irrelevant — pass values directly to `SmtpConfig` / `SmtpSender`
instead.

`authmail-relay` fails fast at startup if a required variable is missing.

## Required

| Var | Description |
|---|---|
| `SMTP_HOST` | SMTP server hostname (e.g. `smtp.gmail.com`). |
| `API_KEY` | Shared Bearer token clients send as `Authorization: Bearer <value>`. Generate with `openssl rand -hex 32`. |

`SMTP_USER` / `SMTP_PASSWORD` are *optional* — leave blank to support
no-auth SMTP relays like Mailpit, MailHog, or an internal relay.

## SMTP

| Var | Default | Description |
|---|---|---|
| `SMTP_PORT` | `587` | SMTP port. |
| `SMTP_USER` | `""` | SMTP login. Blank for no-auth servers. |
| `SMTP_PASSWORD` | `""` | SMTP password / app password. Blank for no-auth servers. |
| `SMTP_FROM` | `SMTP_USER` | `From:` header address. |
| `SMTP_USE_TLS` | `true` | Use STARTTLS. If the server does not advertise STARTTLS, sending fails explicitly (no silent downgrade). |

## API behavior

| Var | Default | Description |
|---|---|---|
| `API_RATE_LIMIT_PER_MINUTE` | `60` | Per-bearer call cap on `/send*`. `0` disables. **In-memory, per worker.** |
| `API_IDEMPOTENCY_TTL_SECONDS` | `86400` | TTL for `Idempotency-Key` cache. `0` disables. **In-memory, per worker.** |
| `MAGIC_LINK_BASE_URL` | unset | Frontend URL prefix. `/send/magic-link` returns `503` until this is set. |
| `HOST` | `127.0.0.1` | uvicorn bind host. The bundled `Dockerfile` / `docker-compose.yml` already set `0.0.0.0` for container use. |
| `PORT` | `8000` | uvicorn bind port. |

## Webhooks

| Var | Default | Description |
|---|---|---|
| `WEBHOOK_ALLOW_HOSTS` | `""` | Comma-separated hostname allowlist for `webhook_url` SSRF validation. |
| `WEBHOOK_ALLOW_LOOPBACK` | `false` | `1` permits loopback / private IPs. **Test only — never set in production.** |

## Observability

| Var | Default | Description |
|---|---|---|
| `METRICS_ENABLED` | `false` | Enable `GET /metrics` (Prometheus). Requires the `[http]` extra (`prometheus-client`). |
| `METRICS_REQUIRE_AUTH` | `false` | Require `Authorization: Bearer $API_KEY` on `/metrics`. **Set to `true` in production.** |
| `EMAIL_SERVICE_LOG_FORMAT` | `text` | `json` enables structured JSON logs via `python-json-logger`. |
| `EMAIL_SERVICE_DEBUG` | `false` | `1` enables `smtplib.set_debuglevel(1)`. **Never in production** — leaks `AUTH PLAIN <base64>` (SMTP password) to stderr. |

## Testing

| Var | Default | Description |
|---|---|---|
| `EMAIL_TEST_CAPTURE_DIR` | unset | If set, skip SMTP and write each message to `<message_id>.eml` in that directory. Integration-test convenience. |

See [`examples/integration_test_with_capture.py`](../examples/integration_test_with_capture.py)
for an end-to-end usage example. This differs from `dry_run` / `X-Dry-Run`:
dry-run validates payload only (no MIME built), capture mode builds the full
MIME message and writes it to disk for header/body assertions.
