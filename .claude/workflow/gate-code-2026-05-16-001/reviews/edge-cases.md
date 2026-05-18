# Edge Case Review — email_service/

**Reviewer**: QA Engineer + SRE
**Date**: 2026-05-16
**Scope**: `email_service/` (10 files, 1868 LOC)
**Test baseline**: 124 pass, 1 skip

---

## Findings

### F-001 — Idempotency: webhook async path can deliver duplicate emails

- **category**: 4 (재시도/멱등성)
- **location**: `api.py:315-333`, `api.py:383-389`, `api.py:424-430`
- **missing_handling**: `/send` accepts no idempotency key. Caller retrying after a timeout (e.g. 30s TCP RST after SMTP `DATA` already accepted) → second BackgroundTask sends a second copy. Same applies to magic-link/OTP.
- **trigger_input**: Client posts `/send {to:"a@x", subject:"S", html_body:"H", webhook_url:"…"}`, gets 504 from intermediate proxy after server already queued the BackgroundTask, retries the request.
- **what_happens**: Two emails sent. No dedup. `message_id` is generated server-side per call, so caller cannot distinguish.
- **severity**: **P1**
- **suggested_fix**:
  ```python
  # api.py SendEmailRequest
  idempotency_key: str | None = Field(default=None, max_length=128)
  # in send_email: maintain TTL cache keyed by (api_key, idempotency_key) → cached SendResult
  ```
- **suggested_test**: `test_send_with_same_idempotency_key_returns_cached_result()` — call twice with same key, assert sender invoked once.

---

### F-002 — Retry produces duplicate sends on partial-accept SMTP failures

- **category**: 4
- **location**: `sender.py:225-291`, `sender.py:345-347`
- **missing_handling**: `smtplib.sendmail` may raise `SMTPServerDisconnected` AFTER the server has accepted `DATA` (relays often drop after 250 OK). Sender treats this as connection error → retriable → resends same message → recipient receives 2+ copies.
- **trigger_input**: SMTP server: accept HELO/MAIL FROM/RCPT TO/DATA → return 250 → close TCP. Library raises `SMTPServerDisconnected` during QUIT or response read.
- **what_happens**: `ERR_SMTP_CONNECTION` returned, `_is_retriable` → True, retry; recipient gets duplicate.
- **severity**: **P1**
- **suggested_fix**: Make connection errors retriable only when raised before `sendmail()` completes. Wrap `server.sendmail(...)` separately:
  ```python
  try:
      refused = server.sendmail(...)
  except smtplib.SMTPServerDisconnected:
      # Post-DATA disconnect: treat as delivered-uncertain, not retriable
      return SendResult(sent=False, error_code="smtp_disconnect_post_data", status=STATUS_FAILED)
  ```
- **suggested_test**: Mock SMTP that raises `SMTPServerDisconnected` after `sendmail` returns; assert no retry.

---

### F-003 — `_is_retriable(None)` for non-exception path returns False, but partial-refusal retries are not even attempted

- **category**: 4
- **location**: `sender.py:250`, `sender.py:366-374`, `sender.py:532-533`
- **missing_handling**: When `server.sendmail` returns refused dict (partial delivery), `ERR_RECIPIENT_REFUSED` is non-retriable. Fine — but for `STATUS_PARTIAL`, the To recipient may have succeeded while only Cc was refused. The fix is correctly non-retriable, but the API layer reports `_fail(result)` → 502 to caller, who cannot distinguish "all failed" from "1 of 3 succeeded".
- **trigger_input**: `to="ok@x", cc=["bad@invalid"]` → `sendmail` returns `{"bad@invalid": (550, ...)}`.
- **what_happens**: API returns 502, caller thinks email failed entirely, may retry → primary recipient gets duplicate.
- **severity**: **P1**
- **suggested_fix**: In `api.py:343` distinguish `result.status == STATUS_PARTIAL` and return 207-style success with `refused` list:
  ```python
  if not result.sent:
      if result.status == STATUS_PARTIAL:
          return SendResult(sent=True, message_id=..., status="partial", refused=result.refused)
      _fail(result)
  ```
- **suggested_test**: `test_partial_refusal_returns_2xx_with_refused_list()`.

---

### F-004 — `time.sleep` in retry loop blocks FastAPI event loop / BackgroundTask worker

- **category**: 5 (취소/타임아웃) + 6 (동시성)
- **location**: `sender.py:277`
- **missing_handling**: `sender.send()` is called from sync `def send_email(...)` route handler → FastAPI runs it in a threadpool, so the event loop is fine. BUT default backoff is `(1, 5, 25)` = up to 31s blocking; with `max_retries=3` and 50 concurrent sends, the threadpool (default 40) saturates → all subsequent requests queue.
- **trigger_input**: 100 concurrent `/send` calls when SMTP is throwing `4xx transient`; max_retries=3.
- **what_happens**: Health endpoint stays responsive (separate task) but `/send` requests queue indefinitely. No queue depth limit.
- **severity**: **P2**
- **suggested_fix**: Document max threadpool. Add `--limit-concurrency` to uvicorn invocation in `__main__.py:28`. Consider async sender with `aiosmtplib`.
- **suggested_test**: Load test 100 concurrent sends against mock that returns 421 transient; assert p99 latency bounded.

---

### F-005 — No upper bound on `html_body` / `text_body` size

- **category**: 7 (극단값)
- **location**: `api.py:44-66`
- **missing_handling**: `html_body: str = Field(min_length=1)` — no `max_length`. A 100MB POST body is accepted, parsed by Pydantic, copied into `MIMEText`, base64-encoded, sent.
- **trigger_input**: `POST /send` with `html_body` = 100MB string.
- **what_happens**: Memory exhaustion; uvicorn worker OOM-killed; depending on SMTP server, also exceeds RFC 5321 line/message size limits silently → server-side rejection or truncation.
- **severity**: **P1**
- **suggested_fix**:
  ```python
  html_body: str = Field(min_length=1, max_length=5_000_000)  # 5MB
  text_body: str | None = Field(default=None, max_length=5_000_000)
  ```
  Plus uvicorn `--limit-max-requests` and reverse-proxy body-size limit.
- **suggested_test**: `test_send_rejects_oversize_body()` — assert 422 for 10MB body.

---

### F-006 — `cc` / `bcc` lists have no length cap; no per-element email validation

- **category**: 7
- **location**: `api.py:49-50`, `api.py:59-66`
- **missing_handling**: `cc: list[str] | None = None` — no max items, no email format check. 10000 recipients → enormous RCPT TO conversation, likely rate-limited or banned by SMTP.
- **trigger_input**: `cc=["a@x"] * 10000`.
- **what_happens**: Single sendmail call with 10001 recipients. Server may close connection mid-conversation; resource consumption spike; possible IP blacklisting.
- **severity**: **P1**
- **suggested_fix**:
  ```python
  cc: list[str] | None = Field(default=None, max_length=50)
  bcc: list[str] | None = Field(default=None, max_length=50)
  # And validate each: EmailStr from pydantic[email]
  ```
- **suggested_test**: `test_send_rejects_too_many_recipients()`.

---

### F-007 — `to` accepts any non-empty string including invalid emails

- **category**: 7
- **location**: `api.py:45`, `sender.py:137-153`
- **missing_handling**: No syntactic email validation. `to=" "` (single space) passes `min_length=1`, no CRLF, gets stuffed into `msg["To"]`. SMTP RCPT TO will reject, but lots of wasted work + potentially confusing error path.
- **trigger_input**: `to=" "`, `to="not-an-email"`, `to="<script>alert(1)</script>"`.
- **what_happens**: SMTP refuses; returns `ERR_RECIPIENT_REFUSED` → 502 — but no early rejection.
- **severity**: **P2**
- **suggested_fix**: Use `pydantic.EmailStr` (requires `email-validator` extra). Stricter validation pre-SMTP.
- **suggested_test**: `test_send_rejects_malformed_email_pre_smtp()`.

---

### F-008 — `webhook_url` accepts arbitrary URL → SSRF

- **category**: 3 (실패 처리) + Security
- **location**: `api.py:51`, `webhooks.py:65`
- **missing_handling**: No scheme/host allowlist. `webhook_url="http://169.254.169.254/latest/meta-data/"` (AWS metadata) or `http://localhost:6379/` (internal Redis).
- **trigger_input**: `webhook_url="http://localhost:8000/admin"` — server makes authenticated-looking POST to its own admin.
- **what_happens**: httpx POSTs to internal address with full payload (which contains `message_id`, etc.) → SSRF; also a side channel to exfiltrate metadata.
- **severity**: **P0**
- **suggested_fix**:
  ```python
  ALLOWED_WEBHOOK_SCHEMES = {"https"}
  def _validate_webhook_url(url: str) -> str:
      p = urlparse(url)
      if p.scheme not in ALLOWED_WEBHOOK_SCHEMES: raise ValueError(...)
      if _is_private_ip(p.hostname): raise ValueError(...)
      return url
  ```
  Enforce HTTPS, block RFC1918/loopback/link-local, optional allowlist via env.
- **suggested_test**: `test_webhook_url_rejects_private_ip()`, `test_webhook_url_requires_https()`.

---

### F-009 — Webhook delivery has no overall timeout budget, can hang BackgroundTask 200+ seconds

- **category**: 5
- **location**: `webhooks.py:33-103`
- **missing_handling**: `timeout=10` per request, but with `max_retries=3` and backoffs `(1, 10, 60)`, worst case = (10 + 1) + (10 + 10) + (10 + 60) = 101s, and if the user passes custom backoffs there's no upper bound. BackgroundTask blocks Starlette's task group; on shutdown, no cancellation handling.
- **trigger_input**: Webhook endpoint hangs (accepts TCP but never responds). max_retries=3 default.
- **what_happens**: Worker blocked 90+s on webhook delivery. On uvicorn shutdown (SIGTERM), in-flight tasks may be killed mid-delivery without graceful drain.
- **severity**: **P2**
- **suggested_fix**: Add overall `deadline` parameter. Use `httpx.AsyncClient` from the async route handler instead of sync `client.post`. Wire `signal.SIGTERM` to set a cancel event.
- **suggested_test**: `test_webhook_total_deadline_bounded()` using slow mock.

---

### F-010 — Webhook payload not signed when secret is None; no replay protection even when signed

- **category**: 6 + Security
- **location**: `webhooks.py:51-54`
- **missing_handling**: Signature includes only body, no timestamp. Attacker who captures one valid signed webhook can replay indefinitely. No nonce.
- **trigger_input**: Attacker on path captures signed webhook, replays 1 hour later.
- **what_happens**: Receiver cannot detect replay; may double-process notification.
- **severity**: **P2**
- **suggested_fix**: Include `X-Email-Service-Timestamp` header in signed material: `_sign(timestamp + b"." + body, secret)`. Receiver rejects > 5min skew.
- **suggested_test**: `test_signature_includes_timestamp_for_replay_protection()`.

---

### F-011 — `_run_and_notify` exception path produces inconsistent error_code value

- **category**: 1 (분기 누락)
- **location**: `api.py:271-289`
- **missing_handling**: Defensive fallback sets `error_code: "unknown"` (string), but `sender.py` uses `ERR_UNKNOWN = "unknown"` — same constant, OK. However when `send_fn` raises, `message_id` is `None`, but if exception happens AFTER message constructed in sender (e.g. socket error post-handoff), the caller has no idea whether email landed. Same idempotency issue as F-002 but routed through webhook channel.
- **trigger_input**: Force `sender.send` to raise (e.g. mock raising `MemoryError`).
- **what_happens**: Webhook receives `status:"failed"`, but actual delivery status is indeterminate.
- **severity**: **P2**
- **suggested_fix**: Surface `status: "uncertain"` and document. Already `pragma: no cover` — write a real test.
- **suggested_test**: `test_background_send_exception_delivers_failure_webhook()`.

---

### F-012 — `_build_sender_from_env` parses SMTP_PORT without try/except

- **category**: 3
- **location**: `api.py:142`
- **missing_handling**: `int(os.environ.get("SMTP_PORT", "587"))` — `SMTP_PORT="abc"` → ValueError at app-startup, but message is unfriendly (`invalid literal for int() with base 10: 'abc'`).
- **trigger_input**: `SMTP_PORT=foo python -m email_service`.
- **what_happens**: Crash, no actionable error.
- **severity**: **P3**
- **suggested_fix**: Wrap in try/except, raise `RuntimeError("SMTP_PORT must be an integer")`.
- **suggested_test**: `test_build_sender_invalid_port_message()`.

---

### F-013 — STARTTLS check uses raw string `"starttls"` — case sensitivity vs server response

- **category**: 1
- **location**: `sender.py:317`
- **missing_handling**: `server.has_extn("starttls")` — smtplib lowercases extensions, so this works. But `use_tls=True` with port 465 (implicit SSL) → server never advertises STARTTLS → refused. There's no support for implicit SMTPS (smtplib.SMTP_SSL).
- **trigger_input**: `SMTP_HOST=smtp.example.com SMTP_PORT=465 SMTP_USE_TLS=true`.
- **what_happens**: `ERR_STARTTLS_UNSUPPORTED`, no email sent. User cannot use 465.
- **severity**: **P2**
- **suggested_fix**: Add `smtp_mode: Literal["plain","starttls","ssl"]` in SmtpConfig; use `smtplib.SMTP_SSL` when `ssl` mode selected.
- **suggested_test**: `test_smtp_ssl_mode_uses_smtp_ssl()`.

---

### F-014 — Subject with non-ASCII (Korean/Japanese) not RFC 2047 encoded

- **category**: 8 (국제화)
- **location**: `sender.py:156`
- **missing_handling**: `msg["Subject"] = subject` — when subject contains non-ASCII (e.g. "비밀번호 설정 안내"), Python's `email.message.Message` auto-encodes via `MIMEMultipart` default Header handling, but with no explicit charset declaration. In some SMTP servers / older clients, the raw UTF-8 bytes leak as `=?utf-8?b?...?=` correctly; but if subject contains both `\r\n`-style line wrap requirements (very long Korean subject), the wrap may break. Also `From` with non-ASCII display name e.g. `from_addr="홍길동 <a@x>"` will not be properly encoded — Python serializes it as raw UTF-8 in the header, which violates RFC 5322.
- **trigger_input**: `SMTP_FROM="홍길동 <a@x>"`, `subject="안녕하세요 " * 20`.
- **what_happens**: Header may be sent with raw UTF-8 bytes → some MTAs reject (`501 syntax error`), or display as mojibake in Outlook.
- **severity**: **P2**
- **suggested_fix**:
  ```python
  from email.header import Header
  from email.utils import formataddr
  msg["Subject"] = Header(subject, "utf-8")
  # parse from_addr into (name, email), re-encode name as RFC 2047:
  msg["From"] = formataddr((name, addr), charset="utf-8")
  ```
- **suggested_test**: `test_subject_korean_rfc2047_encoded()`, `test_from_display_name_non_ascii()`.

---

### F-015 — `MagicLinkNotifier.send` does not URL-encode `base_url` path joining edge cases

- **category**: 7
- **location**: `notifiers.py:156`
- **missing_handling**: `f"{self._base_url}{self._path}?{urlencode({'token': payload})}"` — if `path` is missing leading `/`, URL becomes malformed. If `payload` contains `\r\n`, `urlencode` will encode it (safe), but does not check overall URL length (some clients truncate at 2048).
- **trigger_input**: `path="set-password"` (no leading slash) → `"https://x.com" + "set-password"` = `"https://x.comset-password"`.
- **what_happens**: Broken link, user cannot reset password. No validation.
- **severity**: **P3**
- **suggested_fix**: Enforce `path` starts with `/` in `__init__`.
- **suggested_test**: `test_magic_link_path_must_start_with_slash()`.

---

### F-016 — `TemplateNotifier.send` raises KeyError on missing context variable

- **category**: 1
- **location**: `notifiers.py:233-238`
- **missing_handling**: `self._template.format(**html_ctx)` — if template has `{missing}` placeholder, raises `KeyError("missing")` with no friendly handling. Propagates to API → 500 (not 502, not validation error).
- **trigger_input**: `TemplateNotifier(subject="S", html_template="Hi {user}")`. Call `send("a@x")` with no `user=`.
- **what_happens**: `KeyError: 'user'` uncaught → FastAPI returns 500.
- **severity**: **P3**
- **suggested_fix**: Wrap `.format()` in try/except `KeyError`, return `SendResult(sent=False, error_code=ERR_TEMPLATE_NOT_CONFIGURED, ...)` or raise specific exception.
- **suggested_test**: `test_template_notifier_missing_placeholder_raises_typed_error()`.

---

### F-017 — Async/sync clients silently swallow JSON decode failure on 502, lose error context

- **category**: 1
- **location**: `client.py:145-156`, `async_client.py:130-141`
- **missing_handling**: `try: body = resp.json(); except Exception: body = {}` — bare except, any exception type, no logging. If server returns 502 with HTML error page (proxy injecting), `error_code` becomes `None`, masking root cause.
- **trigger_input**: nginx upstream timeout returns 502 with `text/html` body.
- **what_happens**: `EmailServiceError(error_code=None, message=None)`, useless for caller.
- **severity**: **P3**
- **suggested_fix**: Catch `json.JSONDecodeError`/`ValueError` specifically; include `resp.text[:200]` in error message; log warning.
- **suggested_test**: `test_client_502_with_non_json_body_preserves_text()`.

---

### F-018 — Capture-mode path traversal partially mitigated but `..` in Message-ID not blocked

- **category**: 7 + Security
- **location**: `sender.py:177-180`
- **missing_handling**: `mid_clean = message_id.strip("<>").replace("@", "_at_").replace("/", "_").replace("\\", "_")` — does not strip `..` or NUL bytes. `make_msgid()` is server-generated, so untrusted input doesn't reach here directly, BUT if a custom Message-ID is ever passed in, `..\\..\\etc\\passwd` could escape — partial mitigation only.
- **trigger_input**: Future refactor allowing caller-supplied Message-ID.
- **what_happens**: Write outside `EMAIL_TEST_CAPTURE_DIR`.
- **severity**: **P3** (latent, currently safe)
- **suggested_fix**: Use `os.path.basename(mid_clean)` or sanitize with regex `[^A-Za-z0-9_.-]`.
- **suggested_test**: `test_capture_path_sanitized_against_traversal()`.

---

### F-019 — Trace ID middleware does not sanitize incoming `X-Request-ID`

- **category**: 7 + Security
- **location**: `api.py:192-199`
- **missing_handling**: `tid = request.headers.get("X-Request-ID") or uuid.uuid4().hex` — caller can inject `X-Request-ID: foo\r\nSet-Cookie: bar` (HTTP response splitting). Starlette generally strips `\r\n` from header values at write-time, but defense in depth wants explicit validation.
- **trigger_input**: `curl -H "X-Request-ID: bad\r\nX-Injected: yes" /health`.
- **what_happens**: Modern Starlette rejects, but no validation here — relies on stack.
- **severity**: **P3**
- **suggested_fix**: Validate `^[A-Za-z0-9_-]{1,64}$`; fall back to UUID otherwise.
- **suggested_test**: `test_request_id_with_crlf_is_replaced()`.

---

### F-020 — `email_send_active` gauge race on exception in `_send_once` before `try` body

- **category**: 6
- **location**: `sender.py:303-522`
- **missing_handling**: `email_send_active.inc()` before `try:`. If a future modification inserts code between `inc()` and `try:` that raises, `dec()` in finally never runs → gauge leaks. Currently safe but fragile.
- **trigger_input**: N/A (latent).
- **what_happens**: Currently OK because `email_send_active.inc()` is line 304, `try:` is 305. Refactoring hazard.
- **severity**: **P3**
- **suggested_fix**: Move `inc()` inside `try:` first line, or use `with email_send_active.track_inprogress():` context manager (already provided by NoOpMetric stub).
- **suggested_test**: `test_active_gauge_decrements_on_immediate_failure()`.

---

### F-021 — `if value:` for falsy "0" / "" treated as no-value in env parsing

- **category**: 1
- **location**: `api.py:32-34`, `api.py:146`
- **missing_handling**: `if not val:` rejects empty string. But `SMTP_PASSWORD=""` is sometimes intentional (e.g. local Mailpit). `_required_env("SMTP_HOST")` with value `"0"` would succeed (`"0"` is truthy as non-empty string), good. But `SMTP_USE_TLS` parsing: `os.environ.get("SMTP_USE_TLS", "true").lower() != "false"` — so `SMTP_USE_TLS=0` → True (TLS on), `SMTP_USE_TLS=no` → True. Asymmetric with `_truthy` elsewhere.
- **trigger_input**: `SMTP_USE_TLS=0` expecting TLS off.
- **what_happens**: TLS remains on. Silent misconfiguration.
- **severity**: **P2**
- **suggested_fix**: Use unified `_truthy`/`_falsy` parser. Reject unknown values explicitly.
- **suggested_test**: `test_smtp_use_tls_recognized_values()`.

---

### F-022 — `OTPNotifier`/`MagicLinkNotifier` re-fail subject when prefix has trailing whitespace stripped

- **category**: 1
- **location**: `notifiers.py:157`, `notifiers.py:197`
- **missing_handling**: `f"{self._prefix}{self._subject}".strip()` — strips both sides. If `subject_prefix="[DEV] "` and `subject="알림"`, result is `"[DEV] 알림"` → strip → `"[DEV] 알림"` (OK). If prefix is empty and subject has leading/trailing whitespace intentionally, it's stripped. Minor.
- **trigger_input**: `subject="  spaced  "`, prefix `""`.
- **what_happens**: Subject becomes `"spaced"`. Possibly unexpected.
- **severity**: **P3**
- **suggested_fix**: Document, or only `.strip()` the prefix concatenation gap.
- **suggested_test**: N/A.

---

### F-023 — Retry attempt count metric inflated under partial-then-retry scenarios

- **category**: 6
- **location**: `sender.py:264-266`
- **missing_handling**: `email_retry_attempts_total.labels(reason=...).inc()` is called once per retry. But if `STATUS_PARTIAL` becomes retriable in a future change, retries could resend successful recipients, inflating both metric AND duplicate emails (compounds F-002).
- **trigger_input**: Latent.
- **severity**: **P3**
- **suggested_fix**: Add explicit assertion `assert result.status != STATUS_PARTIAL` before retry loop entry.
- **suggested_test**: N/A.

---

## Summary

### coverage_score: **6/10**

Strong on basic SMTP error taxonomy, CRLF injection, capture mode, structured results. Weak on idempotency, body-size limits, SSRF, post-DATA disconnect semantics, RFC 2047 internationalization, and recipient validation.

### top_5_critical_gaps

1. **F-008 (P0) SSRF via webhook_url** — no allowlist, can hit AWS metadata / localhost.
2. **F-002 (P1) Duplicate email on post-DATA disconnect retry** — silent double-send.
3. **F-001 (P1) No idempotency key** — retry-on-timeout produces duplicates.
4. **F-005 (P1) No body size limit** — trivial OOM DoS.
5. **F-006 (P1) No recipient count cap** — IP reputation / DoS risk.

### pattern_observations

- **Retry semantics naive**: classification of "retriable" is by exception type only, not by *phase* of the SMTP conversation. The single biggest gap.
- **Input validation deferred to SMTP**: `to`, `cc`, `bcc`, `html_body`, `webhook_url` are all loosely typed strings. The system relies on downstream SMTP for "validation by rejection". Cheap upfront validation (EmailStr, max_length, URL allowlist) would prevent multiple classes of issues.
- **Background tasks lack a cancellation/deadline story**: webhook delivery can block 100+s; SIGTERM handling not wired. Acceptable for current scale but risky if traffic grows.
- **Internationalization assumed via UTF-8 in body, not headers**: subject/From rely on implicit encoding. RFC 2047 not explicit.
- **No structured idempotency layer anywhere**: neither in HTTP API nor in SmtpSender. Acceptable for fire-and-forget transactional mail, dangerous for OTP (user may receive 2+ codes, only one valid).

### recommended_test_files

- `tests/test_idempotency.py` — F-001, F-002.
- `tests/test_smtp_partial_failure.py` — F-002, F-003, F-023.
- `tests/test_webhook_security.py` — F-008, F-009, F-010.
- `tests/test_input_limits.py` — F-005, F-006, F-007.
- `tests/test_i18n_headers.py` — F-014, F-015.
- `tests/test_smtp_ssl_mode.py` — F-013.
- `tests/test_env_parsing.py` — F-012, F-021.
- `tests/test_client_error_paths.py` — F-017.
