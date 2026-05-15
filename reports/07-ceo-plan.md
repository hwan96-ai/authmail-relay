# CEO Plan: email-service expansion
status: ACTIVE
Branch: claude/sad-cannon-1131fe
Mode: SELECTIVE EXPANSION
Date: 2026-05-15

## Vision

### 10x Check
Today the package is a thin, polite wrapper around `smtplib`: send one HTML email, hope it lands, log on failure. That's a 1x library. A 10x email-service is the *trustworthy fire-and-forget primitive* an entire org reaches for — calls survive transient SMTP flaps via retry, callers learn the outcome via signed webhooks instead of polling logs, and integration tests in caller apps work offline because the service captures emails to disk on demand. The ceiling above that (outbox, multi-tenant keys, provider abstraction, template registry) is real but pulls scope into platform territory and forces a database. We hold the line at "best single-tenant SMTP primitive in Python," not "Postmark clone."

### Platonic Ideal
A caller writes `client.send_otp(...)` once and never thinks about it again. Transient SMTP errors retry behind the scenes with exponential backoff. The terminal result (sent / bounced / refused / gave-up) arrives as a signed HMAC webhook to a caller-registered URL — the loop closes asynchronously without the caller polling. In tests, the caller flips `EMAIL_TEST_CAPTURE_DIR=/tmp/eml` and assertions read `.eml` files instead of mocking smtplib. The service stays a single binary, no DB, no message broker, no per-tenant config.

## Scope Decisions

| # | Proposal | Effort | Decision | Reasoning |
|---|----------|--------|----------|-----------|
| 1 | Outbox pattern built-in | M-L | DEFERRED | Forces DB coupling — belongs in caller's persistence layer or a separate `email-outbox` library. Out of single-tenant SMTP primitive's scope. |
| 2 | Webhook callback for send result | S | ACCEPTED | Closes the async loop. Highest leverage per LOC. HMAC-signed, optional. |
| 3 | Template registry with versioning | M | DEFERRED | Adds storage + admin UI surface. `TemplateNotifier` already covers 90% of cases. Revisit if 3+ users ask. |
| 4 | Multi-tenant API_KEY + rate limits | M | DEFERRED | Reverse proxy / API gateway solves this better. README already documents the pattern. Avoid reinventing nginx. |
| 5 | Provider abstraction (SendGrid/SES) | M | DEFERRED but design-aware | Notifier already abstracts at the right layer. Add when a second provider is actually needed; do not pre-build. |
| 6 | Test-mode (capture to .eml) | S | ACCEPTED | Eliminates `mock.patch('smtplib.SMTP')` boilerplate in every caller. Env-var only, zero API surface. |
| 7 | Retry with exponential backoff | S | ACCEPTED | Currently zero retries — a single TCP blip drops the email. Industry-baseline reliability. Idempotent via `Message-ID`. |

## Accepted Scope

- **Webhook callback for send result** — POST signed payload to `WEBHOOK_URL` after terminal outcome.
- **Retry with exponential backoff** — `[1s, 5s, 25s]` default, capped at 3 attempts, configurable per call.
- **Test-mode (env var captures emails)** — `EMAIL_TEST_CAPTURE_DIR` writes `.eml` files instead of opening an SMTP socket.

## NOT in scope

- **Outbox / transactional consistency** — caller responsibility; separate library if ever needed.
- **Template registry, admin UI** — `TemplateNotifier` is enough.
- **Multi-tenant key management** — solved at reverse proxy.
- **Provider plugins beyond SMTP** — Notifier shape is forward-compatible; ship when demanded, not before.
- **Bounce/complaint parsing** — SMTP-level data is too thin; needs provider API. Out.

## Architecture (ASCII diagram)

```
                       POST /send  (+ optional webhook_url, max_attempts)
caller ─────────────────────────────────────────────►  FastAPI
                                                         │
                                                         ▼
                                              ┌─ test-mode? ─┐
                                              │ yes          │ no
                                              ▼              ▼
                                     write .eml         RetryingSender
                                     to CAPTURE_DIR     │
                                     return sent=true   │ attempt 1
                                                        ▼
                                                   SmtpSender.send()
                                                        │
                                              ┌─ transient? ─┐
                                              │ yes (4xx-tmp │  permanent / success
                                              │  / timeout)  │
                                              ▼              ▼
                                          sleep(backoff)   terminal result
                                          retry (≤max)        │
                                                              ▼
                                                   webhook_url set?
                                                       │       │
                                                       no      yes
                                                       │       ▼
                                                       │   POST signed JSON
                                                       │   X-Email-Signature:
                                                       │     sha256=hmac(secret,body)
                                                       │   (best-effort, 3 tries,
                                                       │    then dead-letter log)
                                                       ▼
                                                   return 200 to caller
```

Key invariant: the synchronous HTTP response reflects *send attempt initiation* (or terminal result if no retry needed). The webhook reflects the *terminal outcome* after all retries.

## Error & Rescue Registry

| Path | Exception / Condition | Classification | Rescue Action |
|---|---|---|---|
| RetryingSender | `smtplib.SMTPServerDisconnected`, `socket.timeout`, `ConnectionRefusedError` | TRANSIENT | sleep backoff, retry up to `max_attempts` |
| RetryingSender | `smtplib.SMTPResponseException` code 4xx | TRANSIENT | retry |
| RetryingSender | `smtplib.SMTPResponseException` code 5xx | PERMANENT | stop, mark `failed_permanent`, fire webhook |
| RetryingSender | `smtplib.SMTPRecipientsRefused` (all recipients refused) | PERMANENT | stop, mark `refused`, fire webhook with refused list |
| RetryingSender | partial refusal (some recipients accepted) | PARTIAL | DO NOT retry (already delivered to others); mark `partial`, include refused list in webhook |
| RetryingSender | retries exhausted | TERMINAL | mark `gave_up`, fire webhook with last_error |
| WebhookDispatcher | `httpx.HTTPError`, non-2xx response | TRANSIENT | retry 3× (1s, 5s, 25s); after that log `dead_letter` at ERROR with full payload |
| WebhookDispatcher | invalid `WEBHOOK_URL` scheme (not https in prod) | CONFIG | fail-fast at startup if `WEBHOOK_REQUIRE_HTTPS=true` |
| TestCapture | `EMAIL_TEST_CAPTURE_DIR` not writable | CONFIG | fail-fast at startup with clear path + perms error |
| TestCapture | disk full while writing .eml | OPERATIONAL | return `502`, log; do not silently fall through to real SMTP |

## Failure Modes

| Failure | Detection | Impact | Mitigation |
|---|---|---|---|
| Caller's webhook endpoint down | non-2xx from POST | terminal result not delivered | 3 retries → dead-letter log (operator can replay from log) |
| Retry storm during SMTP outage | `retry_attempt_count` metric spikes | service threads blocked on `sleep` | retries run in `BackgroundTasks`; sync response returns immediately when `webhook_url` set |
| Partial recipient refusal interpreted as full failure | refused-dict non-empty | caller resends, duplicate to good recipients | classify partial separately; webhook says `partial` not `failed`; do not retry |
| Test-mode accidentally enabled in prod | startup log says `TEST_CAPTURE_DIR=...` | zero real emails sent | emit `WARNING` on every send when test-mode active; healthcheck includes `test_mode: true` |
| HMAC secret leaks | — | attacker forges webhook payloads | secret rotation via env var swap + restart; document in security section |
| Message-ID changes between retries | duplicate emails if receiving MTA dedups loosely | recipient sees 2 emails | generate Message-ID once per *logical send*, reuse across retry attempts |

## Diagrams

### State machine — single send lifecycle

```
        ┌─────────┐
        │ ACCEPTED│ (HTTP 200 returned to caller if webhook_url set)
        └────┬────┘
             │ attempt
             ▼
        ┌─────────┐ transient err   ┌──────────┐
        │SENDING  │────────────────►│RETRY_WAIT│
        └────┬────┘                 └────┬─────┘
             │ success                   │ backoff elapsed
             │                           └─► (back to SENDING)
             │ permanent err / refused   │
             │ max_attempts hit ─────────┤
             ▼                           ▼
        ┌─────────┐               ┌──────────┐
        │  SENT   │               │  FAILED  │ (permanent | refused | gave_up)
        └────┬────┘               └────┬─────┘
             │                         │
             └──────────┬──────────────┘
                        ▼
                ┌───────────────┐
                │ WEBHOOK (opt) │ HMAC-signed POST
                └───────────────┘
```

### Webhook payload schema

```
POST <webhook_url>
Headers:
  Content-Type: application/json
  X-Email-Signature: sha256=<hex_hmac(secret, body)>
  X-Email-Event: send.terminal
Body:
  {
    "message_id": "<random@host>",
    "to": "user@example.com",
    "status": "sent" | "failed_permanent" | "refused" | "partial" | "gave_up",
    "attempts": 2,
    "refused": ["bad@example.com"],         // present if partial/refused
    "last_error": "SMTPServerDisconnected: ...",  // present if not sent
    "timestamp": "2026-05-15T12:34:56Z"
  }
```

## Section 3 — Security

- **HMAC signing**: `WEBHOOK_SECRET` env var (≥32 bytes). Signature = `sha256=` + hex HMAC of raw request body. Caller MUST `hmac.compare_digest` — README will show the verify snippet.
- **HTTPS-only webhook in prod**: `WEBHOOK_REQUIRE_HTTPS=true` (default) rejects `http://` URLs at startup; allow override for local dev.
- **Replay protection**: include `timestamp` in payload + signed; caller rejects payloads older than 5 minutes (documented).
- **No secret in logs**: webhook secret is never logged, even at DEBUG. Add a smoke test that greps logs for the secret.
- **Test-mode safety**: capture dir mode 0700; warn loudly if running with `EMAIL_TEST_CAPTURE_DIR` set in a non-test environment (heuristic: `ENV=production`).

## Section 4 — Data flow & UX edge cases

- **Partial recipient refusal**: do not retry. Already delivered to accepted recipients; retrying would duplicate. Surface as `status: "partial"` in webhook with refused list. Sync response still returns `sent=false` for backward compat? **Decision: return `sent=true, partial=true, refused=[...]`** — new field, additive, no break.
- **Caller did not supply `webhook_url`**: behavior is exactly today's, plus retry. Sync response carries terminal result.
- **Caller supplied `webhook_url` AND retry needed**: sync response returns `accepted=true` immediately; retries + final webhook happen in `BackgroundTasks`. New response shape gated on presence of `webhook_url`.
- **Dry-run + webhook**: dry-run never fires webhook (documented). Returns existing dry-run shape.
- **Test-mode + webhook**: test-mode fires the webhook with `status: "sent"` and a synthetic `message_id`, so caller webhook handlers are exercised in tests. Toggle via `EMAIL_TEST_FIRE_WEBHOOKS=true`.

## Section 6 — Tests

| Feature | Unit | Integration |
|---|---|---|
| RetryingSender | mock `SmtpSender.send` to fail N then succeed; assert attempt count, backoff sleep called with right args (monkeypatch `time.sleep`) | full FastAPI test client + mock SMTP that 421s twice then accepts; assert 200 + correct attempts metric |
| Webhook dispatcher | mock httpx; assert signature header, payload schema, retry on 5xx, dead-letter log on exhaustion | spin up a tiny `aiohttp` receiver in test, verify signed payload arrives within 100ms |
| Test-mode | env var set → assert `.eml` written, SMTP never called; disk-full → 502 | full request → file appears in tempdir → parsed by `email.parser` matches headers |
| Partial refusal | sendmail returns refused dict → status=partial, no retry | API returns `sent=true, partial=true, refused=[...]` |
| HMAC verification | known-vector test (RFC 4231-style fixture) | round-trip: dispatcher signs, receiver verifies, mismatch rejected |

Coverage gate: new modules ≥90% line coverage. Existing modules untouched ≥ current %.

## Section 8 — Observability

Emit Prometheus-style counters (text endpoint `/metrics` if `METRICS_ENABLED=true`, default off to avoid scope creep):

- `email_send_success_total{template="generic|magic_link|otp"}`
- `email_send_failure_total{reason="transient|permanent|refused|gave_up", template="..."}`
- `email_retry_attempt_count{template="..."}` (histogram or counter)
- `email_webhook_dispatch_total{outcome="success|retry|dead_letter"}`
- `email_test_mode_capture_total` (so prod alerts can fire if this is non-zero in prod)

Structured logs (already `logger.exception`-based): add `extra={"message_id": ..., "attempt": ..., "status": ...}` on every retry + terminal log.

## Section 9 — Deploy

Each new feature ships behind an env-var feature flag:

| Flag | Default | Effect |
|---|---|---|
| `EMAIL_RETRY_MAX_ATTEMPTS` | `1` (off) | Retries disabled by default; opt-in by setting to 3 |
| `EMAIL_RETRY_BACKOFF_SECONDS` | `1,5,25` | Comma-separated backoff schedule |
| `WEBHOOK_URL` | unset | If unset, dispatcher is fully bypassed |
| `WEBHOOK_SECRET` | unset | Required when `WEBHOOK_URL` set; fail-fast otherwise |
| `WEBHOOK_REQUIRE_HTTPS` | `true` | Reject non-HTTPS webhook URLs |
| `EMAIL_TEST_CAPTURE_DIR` | unset | When set, capture to disk; never open SMTP |
| `EMAIL_TEST_FIRE_WEBHOOKS` | `false` | Whether test-mode also exercises webhooks |
| `METRICS_ENABLED` | `false` | Expose `/metrics` |

Rollout order: (1) retry behind flag, (2) test-mode, (3) webhooks. Each is independently shippable in its own PR.

## Section 11 — Design

No UI scope. Swagger `/docs` automatically reflects new request fields (`webhook_url`, `max_attempts`) and new response fields (`partial`, `refused`, `accepted`). Add a dedicated `## Webhook payload` section to README with the schema above and a 10-line Python verifier example.

## Completion Summary

| Item | Status | Effort | Files touched (est.) |
|---|---|---|---|
| Retry with exponential backoff | ACCEPTED | S | `sender.py`, `api.py`, tests, README |
| Webhook callback (HMAC-signed) | ACCEPTED | S-M | new `webhooks.py`, `api.py`, tests, README |
| Test-mode (.eml capture) | ACCEPTED | S | `sender.py`, `api.py`, tests, README, `.env.example` |
| Outbox pattern | DEFERRED | M-L | — |
| Template registry | DEFERRED | M | — |
| Multi-tenant API keys | DEFERRED | M | — |
| Provider abstraction | DEFERRED | M | — |

Net effect: closes the async reliability loop (retry + webhook) and removes caller-side test friction (.eml capture), without dragging the package into platform/DB territory. Single binary, single tenant, much harder to misuse.
