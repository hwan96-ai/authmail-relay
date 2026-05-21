# Webhooks

Async delivery notifications. When you pass `webhook_url` in a `/send*`
request body, the send is handled in the background and the HTTP call returns
immediately with `{"sent": false, "status": "accepted"}`. The final result is
POSTed to the webhook URL.

## Payload

```json
{
  "message_id": "<...@host>",
  "status": "delivered",
  "error_code": null,
  "refused": [],
  "sent_at": "2026-05-15T10:00:00+00:00",
  "attempts": 1
}
```

## Signature headers

If `webhook_secret` is included alongside `webhook_url`, the webhook POST
carries both a V2 timestamp-bound signature and a legacy V1 signature:

| Header | Format | Notes |
|---|---|---|
| `X-Email-Service-Signature-V2` | `sha256=<hex>` of `HMAC-SHA256(secret, "<timestamp>.<body>")` | **Recommended.** Replay-resistant when paired with a timestamp window check. |
| `X-Email-Service-Timestamp` | Unix epoch seconds | Pair with V2. |
| `X-Email-Service-Signature` (V1) | `HMAC-SHA256(secret, body)` | Legacy. Has no timestamp binding — vulnerable to indefinite replay of captured requests. |

`webhook_secret` should be treated like `API_KEY`: long random value
(`openssl rand -hex 32`), stored in a secret manager or env var, never
committed.

## Receiver verification (Python, V2)

```python
import hashlib
import hmac
import time

body = await request.body()
timestamp = request.headers["X-Email-Service-Timestamp"]
signature = request.headers["X-Email-Service-Signature-V2"]

now = int(time.time())
if abs(now - int(timestamp)) > 300:           # 5-minute window
    raise ValueError("stale webhook timestamp")

signed = timestamp.encode("ascii") + b"." + body
expected = "sha256=" + hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()
if not hmac.compare_digest(signature, expected):
    raise ValueError("bad webhook signature")
```

## V1 → V2 migration

V1 is kept only for receivers that have not yet been updated. **New
receivers should validate V2.** V1 will be removed in a future major release —
see [CHANGELOG.md](../CHANGELOG.md).

To migrate a receiver:

1. Start reading `X-Email-Service-Timestamp`.
2. Reject if `abs(now - timestamp) > 300`.
3. Compute `HMAC-SHA256(secret, f"{timestamp}.{body}")` and compare to
   `X-Email-Service-Signature-V2` using `hmac.compare_digest`.

## Retry behavior

The webhook delivery itself retries with `(1s, 2s, 5s)` backoff for a total of
3 attempts. If all attempts fail, `email_webhook_failed_total` increments. The
underlying email is already sent — webhook failure does not affect delivery.

## SSRF defense

`webhook_url` is validated to block IP literals (loopback, link-local,
private, multicast, reserved, unspecified) and hostnames that resolve to
those addresses. DNS re-resolution happens on every retry attempt, defeating
inter-retry DNS rebinding.

Bypass knobs (test only):

- `WEBHOOK_ALLOW_HOSTS` — comma-separated hostname allowlist (case-insensitive
  match against the URL hostname). Listed hostnames skip both IP-literal and
  DNS-resolution checks.
- `WEBHOOK_ALLOW_LOOPBACK=1` — allow loopback / private IPs without an
  explicit hostname. **Never set in production.**

## Local testing

`docker-compose.dev.yml` ships an httpbin-based `webhook-sink` service:

```bash
docker compose -f docker-compose.dev.yml up -d
export WEBHOOK_SECRET="$(openssl rand -hex 32)"
curl -H "Authorization: Bearer $API_KEY" \
     -X POST http://127.0.0.1:8000/send \
     -H "Content-Type: application/json" \
     -d "{\"to\":\"u@t.com\",\"subject\":\"hi\",\"html_body\":\"<p>x</p>\",
          \"webhook_url\":\"http://webhook-sink/post\",\"webhook_secret\":\"$WEBHOOK_SECRET\"}"
docker compose -f docker-compose.dev.yml logs webhook-sink
```

PowerShell generates the secret like so:

```powershell
$env:WEBHOOK_SECRET = -join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Minimum 0 -Maximum 256) })
```
