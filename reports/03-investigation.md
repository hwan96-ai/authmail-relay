# Investigation Report — Pre-emptive Bug Hunt

Repo: `email-service` @ `claude/sad-cannon-1131fe`
Scope: 5 hypotheses across `email_service/sender.py`, `email_service/api.py`, `tests/test_api.py`.

---

## H1. SMTP connection failure cleanup

**Status:** VERIFIED SAFE

**Evidence:** `sender.py:66-67` uses `with smtplib.SMTP(...) as server:`. Python's `smtplib.SMTP` implements `__enter__`/`__exit__`. If the constructor itself raises (e.g. DNS failure, refused connect, timeout), the `with` block is never entered, so there is no half-open socket to leak — the constructor's own cleanup (`_get_socket` → close on failure) handles it. If `starttls()`, `login()`, or `sendmail()` raise, `__exit__` runs `quit()`/`close()`. The outer `try/except Exception` at `sender.py:84` catches all and logs via `logger.exception`, returning `False`. No resource leak, no silent failure.

**Note:** `smtplib.SMTP.__exit__` calls `quit()`, which itself can raise on a broken connection; CPython swallows that and calls `close()`. Safe.

---

## H2. STARTTLS downgrade attack defense

**Status:** VULNERABLE (latent — depends on threat model & deploy posture)

**Evidence:** `sender.py:66-71`:
```python
with smtplib.SMTP(self._cfg.host, self._cfg.port, timeout=self._cfg.timeout) as server:
    if self._cfg.use_tls:
        server.starttls()
    if self._cfg.user and self._cfg.password:
        server.login(self._cfg.user, self._cfg.password)
```

Three concrete weaknesses:

1. **No explicit `ssl.SSLContext`.** `server.starttls()` is called with no `context=` argument, so `smtplib` builds a default context via `ssl._create_stdlib_context()`. In modern Python this validates the cert chain and hostname, but it does not pin, does not enforce TLS ≥ 1.2 explicitly, and silently accepts whatever the runtime default is. Best practice: pass `context=ssl.create_default_context()` explicitly so the intent is auditable and the behavior is stable across Python versions.

2. **No `ehlo()` + STARTTLS-capability check.** `smtplib.starttls()` itself raises `SMTPNotSupportedError` if the server's EHLO response lacks `STARTTLS` — that's caught by the outer `except`, so the message will not be sent in plaintext. This is fine. However:

3. **STRIPTLS / MITM stripping the STARTTLS capability from EHLO.** An on-path attacker can strip `STARTTLS` from the server's `EHLO` response. Result: `server.has_extn('starttls')` is `False` → `starttls()` raises `SMTPNotSupportedError` → caught → return `False`. So the email is *not* sent in cleartext (good), but the failure is silent from the caller's perspective and indistinguishable from a transient network error. The credentials in `login()` would also never be sent (good, because `login()` runs *after* `starttls()`). Net: **no credential leak, no plaintext send.** This is correct behavior, but it relies on the implicit ordering. There is no defense-in-depth assertion like `assert server.has_extn("starttls")` before `login()`.

**Verdict:** Not exploitable for credential theft today. But the code would be more robust with: (a) explicit `ssl.create_default_context()`, (b) an explicit capability assertion. Recommended hardening, not a P0.

**Proposed fix (`sender.py:66-71`):**
```python
import ssl
ctx = ssl.create_default_context()
with smtplib.SMTP(self._cfg.host, self._cfg.port, timeout=self._cfg.timeout) as server:
    server.ehlo()
    if self._cfg.use_tls:
        if not server.has_extn("starttls"):
            logger.error("SMTP server %s does not advertise STARTTLS; refusing to send", self._cfg.host)
            return False
        server.starttls(context=ctx)
        server.ehlo()
    if self._cfg.user and self._cfg.password:
        server.login(self._cfg.user, self._cfg.password)
```

**Proposed regression test:** Mock `smtplib.SMTP` so that `has_extn("starttls")` returns `False`; assert `send()` returns `False` *and* `login()` was never called.

---

## H3. Header injection / MIMEMultipart bypass

**Status:** VERIFIED SAFE

**Evidence:** `sender.py:43-46` rejects any CRLF in `from_addr`, `subject`, `to`, `cc`, `bcc` before constructing the message. All header assignments at `sender.py:49-55` use the validated values. Body content goes through `MIMEText(..., "html", "utf-8")` / `MIMEText(..., "plain", "utf-8")` which encode bodies properly — header injection from body content is not possible. No alternative send path bypasses `MIMEMultipart`. The API layer (`api.py`) also validates input via Pydantic models before reaching `sender.send()` (confirmed by `test_dry_run_still_runs_validation` at `tests/test_api.py:248-262` which yields 422 for CRLF in `to`).

One minor gap: `text_body` and `html_body` are not CRLF-checked, but they are bodies, not headers — MIME encoding handles them. Safe.

---

## H4. FastAPI /send exception info leakage

**Status:** VERIFIED SAFE

**Evidence:** `api.py:154-164`. On `sender.send(...) → False`, the handler raises `HTTPException(502, "Email send failed")` with a fixed string. The actual exception (SMTP error, auth failure, host unreachable) is caught inside `SmtpSender.send` at `sender.py:84-86` and logged via `logger.exception(...)` — it never escapes back to the FastAPI layer. The client receives only `{"detail": "Email send failed"}`. No host, port, traceback, or credential material is leaked. Same pattern for `/send/magic-link` (`api.py:185`) and `/send/otp` (`api.py:202`).

---

## H5. dry_run test coverage proves SMTP is not called

**Status:** VERIFIED SAFE

**Evidence:** `tests/test_api.py:194-207` — `test_send_dry_run_skips_sender` injects a `MagicMock()` sender, hits `/send` with `X-Dry-Run: true`, asserts response is `{"sent": False, "dry_run": True, "message": "..."}`, and **explicitly asserts `sender.send.assert_not_called()`**. Parallel coverage exists for magic-link (`:209-221`, `magic.send.assert_not_called()`) and OTP (`:223-234`, `otp.send.assert_not_called()`). Truthy variants `1/yes/TRUE/Yes` also covered (`:264-275`). Auth precedence verified (`:236-246`). Validation precedence verified (`:248-262`). Coverage is thorough.

---

## DEBUG REPORT — Most Critical Finding (H2)

| Field | Value |
|---|---|
| **SYMPTOM** | `SmtpSender.send()` calls `server.starttls()` with no explicit `ssl.SSLContext` and no pre-check that the server advertises STARTTLS. Under an active STRIPTLS MITM, behavior is correct-by-accident (login fails closed because `starttls()` raises before `login()`), but the design has no explicit defense-in-depth assertion and silently returns `False` indistinguishable from a transient network failure. |
| **ROOT CAUSE** | `smtplib.SMTP.starttls()` invoked without `context=` argument and without prior `server.has_extn("starttls")` capability check. Relies on implicit ordering (starttls before login) for credential safety. No explicit TLS policy. |
| **FIX (file:line)** | `email_service/sender.py:66-71` — import `ssl`, build `ctx = ssl.create_default_context()`, call `server.ehlo()`, assert `server.has_extn("starttls")` when `use_tls` is True, then `server.starttls(context=ctx)`, then `server.ehlo()` again before `login()`. See proposed patch in H2 above. |
| **EVIDENCE** | `sender.py:66-71` shows bare `server.starttls()` with no context arg and no capability check. No test exercises the STARTTLS-stripped scenario. `tests/test_email_service.py` was not found to contain a STRIPTLS regression test (grep target: `has_extn`, `starttls`, `SMTPNotSupportedError` — none in tests). |
| **REGRESSION TEST** | New test in `tests/test_email_service.py`: monkeypatch `smtplib.SMTP` with a fake whose `has_extn("starttls")` returns `False`. Construct `SmtpSender(SmtpConfig(use_tls=True, user="u", password="p", ...))`. Call `.send(...)`. Assert: (1) return value is `False`, (2) the fake's `login` method was never called, (3) the fake's `sendmail` method was never called. Second test: assert `starttls` is called with a non-None `context` of type `ssl.SSLContext`. |
| **STATUS** | OPEN — hardening recommended. Not P0 (no credential leak today), but P2 maintainability/auditability fix. Two new tests would lock the contract. |

---

## Summary

| # | Hypothesis | Status |
|---|---|---|
| 1 | SMTP cleanup on exception | VERIFIED SAFE |
| 2 | STARTTLS downgrade defense | VULNERABLE (latent, P2) |
| 3 | Header injection bypass | VERIFIED SAFE |
| 4 | /send 502 info leakage | VERIFIED SAFE |
| 5 | dry_run skips SMTP test | VERIFIED SAFE |

Only H2 warrants action. Code is otherwise tight: CRLF validation, fixed 502 message, exception swallowing isolated to sender, comprehensive dry-run test coverage including auth & validation precedence.
