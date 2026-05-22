# API reference

## HTTP service mode

All `POST` endpoints require `Authorization: Bearer $API_KEY`. Success returns
`200 {"sent": true}`. `GET /health` is unauthenticated.

### Endpoints

| Method | Path | Body | Auth | Description |
|---|---|---|---|---|
| `GET` | `/health` | — | no | Healthcheck. `200 {"status":"ok"}`. For load balancers / Docker healthchecks. |
| `POST` | `/send` | `to, subject, html_body, text_body?, cc?, bcc?` | yes | Generic HTML mail. |
| `POST` | `/send/magic-link` | `to, user_name, token` | yes | Magic-link mail. Requires `MAGIC_LINK_BASE_URL`. |
| `POST` | `/send/otp` | `to, user_name, code` | yes | OTP mail. |

### Status codes

| Code | Meaning |
|---|---|
| `200` | Success (or `sent: false, status: accepted` for async webhook sends). |
| `401` | Missing / wrong API key. |
| `409` | `Idempotency-Key` collision — same key, different body fingerprint. |
| `422` | Validation error, or CRLF in `to` / `subject` / `cc` / `bcc` (header-injection guard). |
| `429` | Per-bearer rate limit exceeded. `Retry-After` header included. |
| `502` | SMTP connection or send failed. |
| `503` | `/send/magic-link` called without `MAGIC_LINK_BASE_URL` set. |

### curl examples

Generic mail:

```bash
curl -X POST http://127.0.0.1:8000/send \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "to":"user@example.com",
        "subject":"Hi",
        "html_body":"<p>Hello</p>",
        "text_body":"Hello",
        "cc":["cc@example.com"],
        "bcc":["bcc@example.com"]
      }'
```

Magic link:

```bash
curl -X POST http://127.0.0.1:8000/send/magic-link \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to":"user@example.com","user_name":"User","token":"abc123"}'
```

OTP:

```bash
curl -X POST http://127.0.0.1:8000/send/otp \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to":"user@example.com","user_name":"User","code":"482901"}'
```

### Dry-run

Validate payload without contacting SMTP. Add `X-Dry-Run: true` (`1` / `yes`
also accepted, case-insensitive). API-key auth and Pydantic validation still
run; SMTP does not.

```bash
curl -X POST http://127.0.0.1:8000/send/otp \
  -H "Authorization: Bearer $API_KEY" \
  -H "X-Dry-Run: true" \
  -H "Content-Type: application/json" \
  -d '{"to":"user@example.com","user_name":"User","code":"482901"}'
# → {"sent":false,"dry_run":true,"message":"Email payload is valid"}
```

The Python client SDK exposes this as `dry_run=True`.

### Request tracing

Every request echoes `X-Request-ID`. If the client omits it, the server
assigns a UUID. The ID propagates into the SMTP send log, so gateway →
email-service → SMTP can be grepped on a single ID.

```bash
curl -H "Authorization: Bearer $API_KEY" \
     -H "X-Request-ID: trace-abc-123" \
     -X POST http://127.0.0.1:8000/send \
     -d '{"to":"u@t.com","subject":"hi","html_body":"<p>x</p>"}'
# Response header: X-Request-ID: trace-abc-123
```

### Python client SDK

The `[http]` extra ships an `EmailServiceClient` based on `httpx`. It handles
Bearer auth, dry-run, and 4xx/5xx exceptions.

```python
import os
from email_service.client import EmailServiceClient

with EmailServiceClient(
    "http://email-service:8000",
    os.environ["EMAIL_SERVICE_API_KEY"],
) as client:
    client.health()
    client.send(
        to="user@example.com",
        subject="Hi",
        html_body="<p>Hello</p>",
        text_body="Hello",
        cc=["cc@example.com"],
        bcc=["bcc@example.com"],
    )
    client.send_magic_link("user@example.com", "User", "abc123")
    client.send_otp("user@example.com", "User", "482901")
```

Signature: `EmailServiceClient(base_url, api_key, timeout=10.0)`. Use as a
context manager, or call `close()` explicitly.

There is also an `AsyncEmailServiceClient` for `await`-based callers.

### Raw httpx

```python
import os, httpx

client = httpx.Client(
    base_url=os.environ["EMAIL_SERVICE_URL"],
    headers={"Authorization": f"Bearer {os.environ['EMAIL_API_KEY']}"},
    timeout=10,
)

resp = client.post("/send/otp", json={
    "to": "user@example.com",
    "user_name": "User",
    "code": "482901",
})
resp.raise_for_status()
```

### Node.js (fetch)

```javascript
const resp = await fetch("http://email-service:8000/send/otp", {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${process.env.EMAIL_API_KEY}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    to: "user@example.com",
    user_name: "User",
    code: "482901",
  }),
});

if (!resp.ok) throw new Error(`email-service failed: ${resp.status}`);
console.log(await resp.json());
```

---

## Library mode

Public API surface:

```python
from email_service import (
    SmtpSender,
    MagicLinkNotifier,
    OTPNotifier,
    TemplateNotifier,
)
from email_service.sender import SmtpConfig
from email_service.notifiers import Notifier   # base class for custom notifiers
```

### `SmtpConfig`

```python
from email_service.sender import SmtpConfig

config = SmtpConfig(
    host="smtp.gmail.com",
    port=587,
    user="sender@gmail.com",
    password="app-password",
    from_addr="",            # blank → same as user
    use_tls=True,            # STARTTLS
    timeout=10,
)
```

### `SmtpSender`

Low-level HTML/multipart sender.

```python
from email_service import SmtpSender
from email_service.sender import SmtpConfig

sender = SmtpSender(SmtpConfig(
    host="smtp.gmail.com",
    user="sender@gmail.com",
    password="app-password",
))

ok = sender.send(
    to="recipient@example.com",
    subject="Subject",
    html_body="<h1>Body</h1>",
    text_body="Body",                # optional plain-text alternative
    cc=["cc@example.com"],
    bcc=["bcc@example.com"],
)
# → True (sent) / False (failed, logged with error code)
# CR/LF in to/subject/from/cc/bcc → send refused (CRLF-injection guard).
```

### `MagicLinkNotifier`

```python
from email_service import SmtpSender, MagicLinkNotifier
from email_service.sender import SmtpConfig

sender = SmtpSender(SmtpConfig(
    host="smtp.gmail.com", user="noreply@mycompany.com", password="app-password",
))

notifier = MagicLinkNotifier(
    sender,
    base_url="https://myapp.com",
    path="/set-password",       # default
    subject_prefix="[MyApp] ",
    expire_minutes=15,
)

import secrets
token = secrets.token_urlsafe(32)  # caller-owned; or use a token issued by your auth provider
notifier.send("user@example.com", "User Name", token)
# Body links to https://myapp.com/set-password?token=<that token, URL-encoded>
```

The `token` argument is URL-encoded and embedded in the link. The package
does **not** generate, store, or verify the token — the caller is responsible
for entropy (`secrets.token_urlsafe(32)` minimum), expiry, and single-use
enforcement.

### `OTPNotifier`

```python
from email_service import SmtpSender, OTPNotifier
from email_service.sender import SmtpConfig

sender = SmtpSender(SmtpConfig(
    host="smtp.gmail.com", user="noreply@mycompany.com", password="app-password",
))

OTPNotifier(sender, subject_prefix="[MyApp] ", expire_minutes=5).send(
    "user@example.com", "User Name", "482901",
)
```

### `TemplateNotifier`

For arbitrary subject + HTML templates that don't fit `(user_name, payload)`.

```python
from email_service import SmtpSender, TemplateNotifier
from email_service.sender import SmtpConfig

sender = SmtpSender(SmtpConfig(host="smtp.gmail.com", user="noreply@x.com", password="..."))

notifier = TemplateNotifier(
    sender,
    subject="[MyApp] Order {order_id} received",
    html_template="<p>Hi {user_name}, order {order_id} received. Total: {amount}</p>",
    text_template="Hi {user_name}, order {order_id} received. Total: {amount}",
    autoescape=True,   # HTML-context values are html.escape()'d; subject/text are not
)

notifier.send(
    "user@example.com",
    user_name="User", order_id="A-1024", amount="45,000",
)
```

Templates use `str.format` placeholders. `autoescape=True` escapes values that
land in the HTML body only (subject and text body are not HTML contexts).

### Custom `Notifier`

```python
from html import escape
from email_service.notifiers import Notifier
from email_service.sender import SmtpSender

class WelcomeNotifier(Notifier):
    def __init__(self, sender: SmtpSender, *, company_name: str = ""):
        super().__init__(sender)
        self._company = company_name

    def send(self, to_email: str, user_name: str, payload: str) -> bool:
        safe_name = escape(user_name)
        safe_payload = escape(payload)
        safe_company = escape(self._company)
        subject = f"{self._company} — welcome"
        html = f"<h1>Welcome, {safe_name}!</h1><p>{safe_company}: {safe_payload}</p>"
        return self._sender.send(to_email, subject, html)
```

`TemplateNotifier(autoescape=True)` handles escaping for you, but **custom
`Notifier` subclasses must escape user-supplied values themselves** before
embedding them in HTML.
