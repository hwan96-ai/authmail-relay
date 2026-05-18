# Production-Readiness Code Review — email-service

Scope: `email_service/` (~1868 LOC, Phase 1-5 polish merged, 124 tests pass). Focus: bugs that fire in prod.

---

## P0 — Will fail in prod

### 1. `api.py:286,289` — Webhook callback executes blocking HTTP inside FastAPI BackgroundTasks (async event loop)
- **severity**: P0
- **issue**: `_run_and_notify` is a sync function passed to `BackgroundTasks.add_task`. FastAPI runs sync background tasks **inside the event loop's threadpool**, but `deliver_webhook` uses `httpx.Client` (sync) and `time.sleep` with backoffs `(1, 10, 60)`. A single failing webhook holds a threadpool worker for **up to 71 seconds** plus the `_do_send` SMTP call (default 10s timeout × 1 attempt). With the default Starlette threadpool size (~40), ~40 stuck webhook deliveries will starve every other sync route, including `/health`, `/metrics`, and all `/send*` calls.
- **why it fires**: One slow/dead webhook endpoint (network partition, customer dashboard down). `time.sleep(60)` blocks a worker thread, queue depth grows, k8s liveness probe (`/health`) eventually times out and the pod restarts mid-send.
- **fix direction**: Cap `deliver_webhook` backoffs much lower (e.g. `(1, 2, 5)`) and/or run webhook+SMTP in a bounded `concurrent.futures.ThreadPoolExecutor` you own (e.g. `max_workers=8`), then fail-fast when full. Alternatively switch to `httpx.AsyncClient` and make the route async.

### 2. `webhooks.py:33-65` — SSRF: webhook URL is unvalidated, accepts `http://169.254.169.254/...`, `file://`, internal IPs
- **severity**: P0
- **issue**: `deliver_webhook(url, ...)` calls `client.post(url, ...)` with no scheme/host validation. The URL comes straight from `SendEmailRequest.webhook_url` (api.py:51) which has no validator at all. Any authenticated caller (or anyone who steals the API key from logs/env) can pivot the email-service into making requests to AWS/GCP metadata services, internal admin panels, Redis, etc., and read the response body indirectly via logs.
- **why it fires**: Attacker with valid `API_KEY` (or insider) sends `{"webhook_url": "http://169.254.169.254/latest/meta-data/iam/security-credentials/"}`. The service POSTs the email-result JSON there; even if the response isn't returned, status codes leak via `webhook_status` log field and a metadata-service `200` confirms reachability.
- **fix direction**: Validate `webhook_url` in `SendEmailRequest`: require `https://` (or http only in dev), block hostnames that resolve to RFC1918, loopback, link-local, `0.0.0.0/8`, IPv6 ULA/link-local. Resolve once and pass the IP to httpx, or use an allowlist of webhook domains via env (`WEBHOOK_ALLOWED_HOSTS`).

### 3. `api.py:51, async_client.py:80, client.py:93` — No size limits on `html_body`/`text_body`; unbounded memory
- **severity**: P0
- **issue**: `SendEmailRequest.html_body` has only `min_length=1`. FastAPI/Starlette by default reads the entire request body into memory before pydantic validation. A 500 MB HTML payload is happily accepted, MIME-encoded (`msg.as_string()` at sender.py:347 makes another full copy as a `str`), then handed to SMTP. Two large copies of the body sit in RAM per concurrent request.
- **why it fires**: Hostile caller posts a 100 MB body; ten concurrent requests = ~2 GB resident, OOMKill. Also any Gmail/SES SMTP relay will reject anything >25-40 MB, but only after you've eaten the memory.
- **fix direction**: Add `max_length` to all body/subject fields (e.g. `html_body: str = Field(min_length=1, max_length=10_000_000)`). Add a reverse-proxy/uvicorn `--limit-max-request-size` and a Starlette middleware that 413s oversized bodies before pydantic.

### 4. `api.py:158-161, 305-352` — No rate limit / no abuse protection on `/send*`
- **severity**: P0
- **issue**: Only auth control is a single shared bearer token (`API_KEY`). One compromised key = unbounded outgoing email = your SMTP relay (Gmail, SES) blacklists your sending domain within minutes. There is no per-key rate limit, no per-recipient throttle, no daily cap.
- **why it fires**: Key leaks in client logs / git / CI output. Attacker scripts 10k OTP sends to attacker-controlled inbox to mine your reputation; SES suspends the account, legitimate password-reset emails stop working.
- **fix direction**: At minimum add a global token-bucket (e.g. `slowapi`) keyed on the bearer token, plus a per-recipient `to` cooldown. Better: multiple API keys with per-key quotas. Even a hard `MAX_SENDS_PER_MINUTE` env-var ceiling is far better than nothing.

### 5. `sender.py:277, 137-153` — `time.sleep()` inside SMTP retry blocks event loop when called from async path
- **severity**: P0
- **issue**: `SmtpSender.send()` is sync and calls `time.sleep(delay)` (sender.py:277) with default backoffs `(1, 5, 25)`. The API routes `send_email`/`send_magic_link`/`send_otp` (api.py:305, 368, 416) are **defined as sync functions**, so FastAPI runs them in the threadpool — which is bounded (~40). A single SMTP outage with `max_retries>=2` parks each in-flight request for up to **31 seconds** holding a threadpool slot. The whole API stalls.
- **why it fires**: SMTP relay momentary outage during a daily traffic spike. 40+ concurrent password resets arrive; all 40 threadpool workers each sleep 1+5+25s; `/health` is also a sync route on the same pool → k8s liveness fails → pod restart → in-flight messages queued in `BackgroundTasks` are lost.
- **fix direction**: Either (a) keep `max_retries=0` default (which it already is — but document loudly) and let an external queue retry, or (b) bound the worst-case total backoff (e.g. cap sum to 10s) and add a hard wall-clock budget inside `send()`. Long-term: make routes `async def` and run SMTP in a bounded `ThreadPoolExecutor` with a queue-full backpressure response (503).

---

## P1 — Likely to fail

### 6. `sender.py:392-412` — `SMTPAuthenticationError`'s `str(exc)` is included in `error_message`, often leaks credentials hint
- **severity**: P1
- **issue**: `error_message=str(exc)` for `SMTPAuthenticationError` is returned via `_fail` (api.py:251-258) in the **502 response body**. `smtplib`'s `SMTPAuthenticationError.__str__` typically includes the server's response containing the username (e.g. `(535, b'5.7.8 Username and Password not accepted ... user=ops@company.com')`). That body is then surfaced to the HTTP caller and logged by anyone who logs response bodies.
- **why it fires**: Misconfigured SMTP password in staging. The HTTP 502 detail contains the SMTP user identity; that propagates to the calling service's error log / Sentry / customer support tickets.
- **fix direction**: For `SMTPAuthenticationError`, return a generic `error_message="SMTP authentication failed"` to the client; keep the detailed `str(exc)` only in the server-side `logger.exception` call.

### 7. `sender.py:311-312` — `set_debuglevel(1)` prints AUTH base64 password to stderr; gated only by env var with no audit
- **severity**: P1
- **issue**: When `EMAIL_SERVICE_DEBUG` is truthy, smtplib writes raw protocol to stderr **including the base64-encoded password**. Comment acknowledges this. The env var is silently honored — no startup log, no warning, no production-mode block.
- **why it fires**: Operator sets `EMAIL_SERVICE_DEBUG=1` in a staging compose file to debug, then forgets and copies to prod. Password ends up in stdout/journald/log aggregator. Discovery: months later via routine log search.
- **fix direction**: Refuse to enable debug when a `PRODUCTION=true` / `ENV=production` style flag is set. Log a loud `WARNING` line at app startup whenever debug is active. Better: redact AUTH lines via a logging filter.

### 8. `api.py:163-168` — Magic-link / OTP notifiers are constructed once at app boot but with mutable shared `sender`; `OTPNotifier` always wired
- **severity**: P1
- **issue**: `magic_link` is only created when `MAGIC_LINK_BASE_URL` is set, but `otp = OTPNotifier(sender)` is always constructed, even when never used. More importantly, all three endpoints share one `SmtpSender` instance which has no internal concurrency control. `smtplib.SMTP` is **not reentrant** — each call constructs its own `SMTP` connection (good), but the `SmtpConfig` is read-only so that's fine. The actual bug: `magic_link.send` and `otp.send` ignore `request_id` (notifiers.py:166, 206 — no `request_id` kwarg passed through). Webhook results and logs lose trace correlation for these endpoints.
- **why it fires**: Production incident: traces show `/send` requests but not the corresponding `magic-link` paths; debugging an OTP delivery delay can't be correlated end-to-end.
- **fix direction**: Add `request_id` parameter to `MagicLinkNotifier.send`/`OTPNotifier.send` and forward to `self._sender.send(..., request_id=request_id)`. Update api.py:385/426 to pass `rid`.

### 9. `webhooks.py:65, 84` — `httpx.Client` constructed per call (no connection pool reuse) and no max body size
- **severity**: P1
- **issue**: `deliver_webhook` creates a fresh `httpx.Client` per call when `client is None` (default). Each webhook delivery does TCP+TLS handshake fresh. Also `client.post(url, content=body, ...)` does not limit the **response** body — a malicious webhook returns a 10 GB streaming response that httpx will buffer (default has no max).
- **why it fires**: High send volume → CPU spent in TLS handshakes; or hostile webhook target returns large body → memory blow-up while we just wanted the status code.
- **fix direction**: Use a module-level `httpx.Client` configured with `limits=httpx.Limits(max_connections=20)` and read response with `client.stream` discarding body, OR set `max_redirects=0` and explicitly only inspect `resp.status_code` without touching `.text`. Better, pass `limits` and a small `read` timeout (`timeout=httpx.Timeout(connect=5, read=10, write=10, pool=5)`).

### 10. `webhooks.py:63-95` — Webhook retry has no jitter; thundering herd on shared downstream
- **severity**: P1
- **issue**: Backoffs `(1, 10, 60)` are deterministic. If 1000 emails go through at the same time and the webhook target dies, all 1000 retry at exactly `t+1`, `t+11`, `t+71`. Same for `sender.py:120` `(1, 5, 25)`.
- **why it fires**: SMTP relay or webhook target has a brief 30s outage. All in-flight retries hit it simultaneously the moment it recovers, knocking it down again.
- **fix direction**: Add `random.uniform(0, 0.5) * delay` jitter to both retry loops.

### 11. `api.py:271-289` — Background task swallows `_do_send` exceptions silently when webhook also fails
- **severity**: P1
- **issue**: If `send_fn()` raises (e.g. memory error, SMTP library bug not caught by `_send_once`), the `except Exception` builds an `error_message=str(exc)` and POSTs to the webhook. If `deliver_webhook` then fails after retries, **the only record is `email_webhook_failed_total` counter + log line**. The caller got `202 accepted` and will never know the email failed. There is no DLQ, no persistence.
- **why it fires**: Webhook URL typo by caller. Email send fails for an unrelated reason. Caller's user never gets password reset, caller's system shows "queued" forever.
- **fix direction**: Document in API docs that async mode requires a working webhook. Add a `email_async_orphaned_total` metric specifically for this case. Long-term: persist queued sends + final status in Redis/DB.

### 12. `api.py:146` — `use_tls` default reversed: env `SMTP_USE_TLS=anything-but-false` → True
- **severity**: P1
- **issue**: `os.environ.get("SMTP_USE_TLS", "true").lower() != "false"` means typos (`SMTP_USE_TLS=disabled`, `SMTP_USE_TLS=no`, `SMTP_USE_TLS=0`) all silently keep TLS enabled — that's actually safe — BUT it also means `SMTP_USE_TLS=False` (Python-style capital F) → `"false"` lowercase → disabled. Combined with `sender.py:317` STARTTLS-not-advertised → 503 with a generic message, an operator that *intentionally* wants to test against a no-TLS mailpit instance might be confused. The opposite is the bigger risk: `SMTP_USE_TLS=False` from `.env` does disable TLS. Verify default safe.
- **why it fires**: Operator copies `.env.example` with `SMTP_USE_TLS=False`, gets plaintext SMTP creds over the wire if STARTTLS check passes (rare but possible misconfig). More commonly: confusing UX.
- **fix direction**: Use a strict `_truthy()` helper and default to True; reject ambiguous values with a clear startup error.

### 13. `sender.py:413-436` — Non-transient 5xx SMTP responses (e.g. 550 mailbox full) classed as `ERR_UNKNOWN`, not retried but indistinguishable in metrics from real bugs
- **severity**: P1
- **issue**: `SMTPResponseException` with `code >= 500` is bucketed as `ERR_UNKNOWN`. Operationally `550 mailbox unavailable` is very different from an unhandled `KeyError`. Both go in the same metric label.
- **why it fires**: Alerting on `error_code="unknown"` spikes during a wave of bounced addresses → noisy false positive on the on-call dashboard.
- **fix direction**: Add `ERR_SMTP_PERMANENT` for `5xx` and keep `ERR_UNKNOWN` for actual exceptions.

### 14. `webhooks.py:51` — Webhook signature is over compact JSON; receivers easily reject it because they re-serialize
- **severity**: P1
- **issue**: HMAC is computed over `json.dumps(payload, separators=(",", ":"))` — receiver must use the **exact same byte sequence**. If the receiver's framework re-parses and re-serializes (typical with Express body-parser or `await req.json()` then `JSON.stringify`), key order or whitespace differs and the HMAC will not validate.
- **why it fires**: Customer integrates webhook with Node/Express following naïve docs; signatures always fail; they disable verification → silent loss of integrity.
- **fix direction**: Document explicitly "verify against the raw request body bytes, do not re-serialize". Also include a timestamp in the signed payload + header (`X-Email-Service-Timestamp`) to prevent replay.

---

## P2 — Quality

### 15. `api.py:194` — `uuid.uuid4().hex` for request_id but accepts user-supplied `X-Request-ID` verbatim, no validation
- **severity**: P2
- **issue**: Header value is echoed back in response header and logged. Hostile caller can inject huge / control-character / CRLF strings to corrupt log lines (especially with JSON logger this is mostly safe, but with text it is not).
- **fix direction**: Validate length (≤64) and charset (`[A-Za-z0-9_-]`).

### 16. `api.py:142` — `int(os.environ.get("SMTP_PORT", "587"))` crashes app boot on garbage port
- **severity**: P2
- **issue**: A misconfigured `SMTP_PORT=587 # comment` raises `ValueError` deep in `create_app`, no friendly error.
- **fix direction**: Wrap with a `_required_int` helper that reports the env var name.

### 17. `sender.py:175-181` — Capture-mode filename uses untrusted `Message-ID` for path; `make_msgid()` is safe but still uses local hostname
- **severity**: P2
- **issue**: `mid_clean` strips `<>`, `@`, `/`, `\`, but on Windows leaves `:` from IPv6 hostnames in `make_msgid()` which is illegal in NTFS filenames. Will crash with `OSError` only on Windows when test capture is enabled.
- **fix direction**: Strip any character not in `[A-Za-z0-9._-]`.

### 18. `api.py:51` — Email RFC validation absent. `to: str = Field(min_length=1)` accepts `"not-an-email"`, `";"`, `"<script>"`
- **severity**: P2
- **issue**: SMTP server will reject, surfacing as `recipient_refused` 502. Better caught at API boundary with a clear 422.
- **fix direction**: Use `pydantic.EmailStr` (requires `email-validator` extra) for `to`, `cc[*]`, `bcc[*]`.

### 19. `api.py:201-209` — `METRICS_REQUIRE_AUTH` reads env on every request
- **severity**: P2
- **issue**: Tiny perf cost + means changing env at runtime takes effect, which is surprising and inconsistent with other settings read once at boot.
- **fix direction**: Resolve at `create_app` time.

### 20. Test gaps in retry path — only counted via metrics, no test asserts `time.sleep` is actually called with correct backoff sequence
- **severity**: P2
- **issue**: From metadata "124 tests pass" — but the bounded-backoff retry contract (sender.py:260-278) is exactly the kind of thing that needs a deterministic test with a mocked `time.sleep` capturing arguments. If someone changes `_backoff_seconds` defaults, tests pass silently.
- **fix direction**: Add `test_retry_backoff_sequence` mocking `time.sleep` and `_send_once` to return transient errors.

---

## P3 — Style / nit

### 21. `api.py:112,119` — Two near-identical truthy parsers (`_is_dry_run`, `_truthy`) read same set
- **severity**: P3
- **fix**: Consolidate to one.

### 22. `sender.py:124` — `backoff_seconds or (1,)` lets `()` silently become `(1,)`; surprising
- **severity**: P3
- **fix**: Raise on empty tuple.

### 23. `notifiers.py:163-165` — text version is **not** URL-escaped while HTML is; mismatch with HTML branch using `escape(link, quote=True)`
- **severity**: P3
- **issue**: Text body might contain raw `<>` if `base_url` is weird. Low risk.

### 24. `__main__.py:30` — `HOST=127.0.0.1` default. Containerized deployments will fail to receive external traffic.
- **severity**: P3
- **fix**: Keep loopback default but document loudly in README. (Many ops will set `HOST=0.0.0.0` anyway.)

---

## top_5_must_fix

1. **api.py:286-289 / webhooks.py** — Sync background webhook delivery with `time.sleep` up to 71s starves FastAPI threadpool; cap backoffs and/or move to bounded executor.
2. **webhooks.py:33-65** — SSRF on `webhook_url`: validate scheme, block private/loopback/link-local IPs.
3. **api.py:51** — Add `max_length` to `html_body`, `text_body`, `subject` (e.g. 10 MB / 256 KB / 998 chars) plus reverse-proxy body size cap.
4. **api.py:158-161** — No rate limit on `/send*` with a single shared bearer token; one leaked key = SMTP reputation kill. Add per-key quota.
5. **sender.py:277 + 392-412** — Sync `time.sleep` retry in sync routes blocks threadpool under SMTP outage; also `SMTPAuthenticationError` `str(exc)` leaks SMTP user in 502 body.

## self_confidence

**7/10** — Read all 10 source files; findings cite exact lines and concrete failure modes. Confidence is not 9-10 because I did not execute tests, did not read the test suite to confirm gaps (estimated from metadata), and Phase-1-5 polish may already address some items in ways not visible in source (e.g. an env-var I missed, a reverse-proxy assumed). The P0 items (threadpool starvation, SSRF, no size limits, no rate-limit, sync sleep in retry) are confident.
