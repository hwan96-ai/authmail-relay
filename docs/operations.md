# Operations

Observability and resilience features. All opt-in. Defaults are unchanged.

## Prometheus metrics

| Var | Default | Description |
|---|---|---|
| `METRICS_ENABLED` | `false` | Enable `GET /metrics`. Requires `prometheus-client` (ships with `[http]` extra). |
| `METRICS_REQUIRE_AUTH` | `false` | Require `Authorization: Bearer $API_KEY` on `/metrics`. **Set to `true` in production.** |

```bash
pip install "authmail-relay[http]"
export API_KEY=$(openssl rand -hex 32)
METRICS_ENABLED=true METRICS_REQUIRE_AUTH=true python -m authmail_relay
curl -H "Authorization: Bearer $API_KEY" http://127.0.0.1:8000/metrics
```

If `METRICS_ENABLED=false` or `prometheus-client` is missing, `/metrics`
appears in OpenAPI but returns `404 metrics disabled`.

### Exposed series

- `email_send_total{result, error_code}` — counter. `result` is
  `success` / `failure`; `error_code` is one of `crlf_in_header`,
  `smtp_auth_failed`, `smtp_connection`, `smtp_timeout`, `smtp_transient`,
  `recipient_refused`, `starttls_unsupported`, `unknown` (empty on success).
- `email_send_duration_seconds` — histogram of SMTP send latency.
- `email_send_active` — gauge of in-flight sends.
- `email_retry_attempts_total{reason}` — counter, incremented per retry
  attempt (library mode, `max_retries > 0`).
- `email_webhook_failed_total` — counter of webhook deliveries that
  exhausted retries.

Sample:

```
# HELP email_send_total Total email send attempts
# TYPE email_send_total counter
email_send_total{result="success",error_code=""} 42.0
email_send_total{result="failure",error_code="smtp_connection"} 3.0
email_send_duration_seconds_bucket{le="0.5"} 41.0
```

Sample alert rule:

```yaml
- alert: EmailFailureRateHigh
  expr: rate(email_send_total{result="failure"}[5m]) > 0.05
  for: 10m
  annotations:
    summary: "authmail-relay failure rate above 5% for 10 minutes"
```

## Structured logs

| Var | Default | Description |
|---|---|---|
| `EMAIL_SERVICE_LOG_FORMAT` | `text` | `json` emits one JSON object per log line via `python-json-logger`. |
| `EMAIL_SERVICE_DEBUG` | `0` | `1` enables `smtplib.set_debuglevel(1)`. **Never in production.** |

**PII safety.** Recipient addresses are never logged in plaintext. Send logs
include only `to_hash` (SHA-256, first 8 chars), `error_code`, `duration_ms`,
`message_id`, and `request_id`.

> **`EMAIL_SERVICE_DEBUG=1` is unsafe in production.** It sends `smtplib`
> debug output to stderr, including `AUTH PLAIN <base64>` lines (the SMTP
> password in base64). There is no way to mask this safely within the standard
> library; treat the flag as developer-only.

## Request tracing (`X-Request-ID`)

Every request echoes `X-Request-ID`; if the client omits it, the server
assigns a UUID. The ID propagates into SMTP send logs, so gateway →
authmail-relay → SMTP can be grepped on a single ID.

## SMTP retries (library mode)

```python
from authmail_relay import SmtpSender, SmtpConfig

sender = SmtpSender(
    SmtpConfig(host="smtp.gmail.com", port=587, user="u", password="p"),
    max_retries=2,                  # 1 attempt + 2 retries = 3 max
    backoff_seconds=(1, 5, 25),     # last value is the clamp
)
```

Retried on: `SMTPServerDisconnected`, `SMTPConnectError`, `socket.timeout`,
and SMTP 4xx responses. Permanent 5xx errors and partial recipient refusals
return immediately so the same recipient is never re-sent. `Message-ID` is
preserved across retries so receiving MTAs can dedup.

Each retry increments `email_retry_attempts_total{reason}`.

## Test mode — `.eml` capture

Setting `EMAIL_TEST_CAPTURE_DIR=<path>` skips SMTP entirely and writes each
message as `<message_id>.eml` to that directory. Useful for integration tests
that need to assert against actual MIME headers/bodies.

```bash
EMAIL_TEST_CAPTURE_DIR=/tmp/outbox pytest tests/
```

End-to-end example: [`examples/integration_test_with_capture.py`](../examples/integration_test_with_capture.py).

Distinct from `dry_run` / `X-Dry-Run`: dry-run validates the request payload
only (no MIME built), capture mode builds the full MIME message and persists it.
