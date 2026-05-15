# QA Report — email-service

## Metadata

- Date: 2026-05-15
- Branch: claude/sad-cannon-1131fe
- Repo: D:\email-service\.claude\worktrees\sad-cannon-1131fe
- Mode: static (Python lib + FastAPI HTTP service — no rendered UI to browse)
- Scope: sender.py, api.py, notifiers.py, client.py + tests/

## Health Score: 92 / 100

Breakdown (rubric: 100 - severity-weighted issues; critical -25, high -10, medium -5, low -2):

- Security posture: strong (CRLF defense in depth, constant-time auth, autoescape)
- Test coverage: strong (69 tests across 3 files, 979 LOC of tests for ~330 LOC of source)
- Boot safety: strong (fail-fast on missing env)
- Minor: 1 medium, 2 low findings (see below).

## Top 3 Things to Fix

1. **[MEDIUM] `from_addr` from env not CRLF-validated at boot** — `api.py:102` reads `SMTP_FROM` from env, passed into `SmtpConfig.from_addr`. `SmtpSender.send` checks it per-call (`sender.py:43`), but an operator-set CRLF in env would silently make every send return `False` with only a warning log, with no startup signal. Validate at `_build_sender_from_env`.
2. **[LOW] `TemplateNotifier` autoescape applies only to HTML, not subject** — `notifiers.py:122` formats `subject` with raw `context`, not `html_ctx`. Subject is a header so HTML escape isn't right anyway, but CRLF/injection in subject relies entirely on downstream `SmtpSender.send` rejection. Document or add explicit CRLF guard.
3. **[LOW] `SmtpSender.send` does not validate `from_addr` is set** — `sender.py:43` iterates `(from_addr, subject, to, ...)` but if `from_addr` is `""` (config default with empty user), the CRLF check passes and `sendmail` is called with empty sender. SMTP server will reject, but a config-time assertion would be more honest.

## Per-Dimension Verification

### 1. CRLF header injection — PASS

- **sender.py:43-46**: rejects `\r` / `\n` in `from_addr`, `subject`, `to`, `cc[*]`, `bcc[*]` before message construction. Returns `False` + warning log.
- **api.py:25-28, 39-51**: Pydantic `field_validator` on `to`, `subject`, `cc`, `bcc` raises `ValueError` (→ 422). Defense in depth: API rejects before sender even runs.
- **api.py:59-73**: Magic-link and OTP requests validate `to`.
- Test evidence: `tests/test_email_service.py:191` (`test_rejects_crlf_in_headers`), `tests/test_api.py:124,141,158` (CRLF in to/subject/cc — 422 before sender called).
- Gap: `user_name`, `token`, `code` not CRLF-validated at Pydantic layer — but these never become headers (notifiers HTML-escape them into body), so acceptable.
- Repro (static): N/A — verified via code path + existing tests.

### 2. HTML escape for user inputs in notifiers — PASS

- **notifiers.py:74**: `escape(user_name)` for MagicLink name.
- **notifiers.py:75**: `escape(link, quote=True)` for the href URL (quote=True is correct for attribute context).
- **notifiers.py:94-95**: `escape(user_name)`, `escape(payload)` for OTP.
- **notifiers.py:40-42, 121**: `TemplateNotifier` autoescape default True via `_escape_context`.
- Static analysis: no f-string interpolation of raw user input into HTML templates. Safe.

### 3. API_KEY constant-time compare — PASS

- **api.py:4, 133**: `import hmac` + `hmac.compare_digest(creds.credentials, api_key)`. Correct primitive.
- `HTTPBearer(auto_error=False)` (api.py:128) means missing creds path returns `creds is None` first (short-circuit), but timing diff between "missing" and "wrong" is acceptable (presence is not a secret).

### 4. `dry_run` is keyword-only — PASS (regression guard intact)

- **client.py:62, 83, 97**: all three methods (`send`, `send_magic_link`, `send_otp`) have `*` before `dry_run`. Matches commit a7a8c86 intent.
- Test evidence: `tests/test_client.py:142-165` — explicit `TestDryRunKeywordOnly` class with `test_send_rejects_positional_dry_run`, `test_send_magic_link_rejects_positional_dry_run`, `test_send_otp_rejects_positional_dry_run`, plus `test_keyword_dry_run_still_works`. Regression locked in.

### 5. Fail-fast boot on missing env — PASS

- **api.py:18-22**: `_required_env` raises `RuntimeError` with named variable.
- **api.py:98, 118**: `SMTP_HOST` and `API_KEY` required. App build fails loudly before serving.
- Optional with safe defaults: `SMTP_PORT` (587), `SMTP_USER`/`SMTP_PASSWORD` (empty — allows Mailpit), `SMTP_USE_TLS` (true), `SMTP_FROM` (falls back to user via `SmtpConfig.__post_init__` at sender.py:22-24).
- Magic-link endpoint correctly degrades to 503 if `MAGIC_LINK_BASE_URL` unset (api.py:121-123, 176-180) rather than crashing at boot — intentional.

### 6. SMTP STARTTLS + AUTH branching — PASS

- **sender.py:66-71**: `with smtplib.SMTP(...)` context manager, `if use_tls: server.starttls()`, `if user and password: server.login(...)`. Correct ordering (TLS before AUTH). Branching allows no-auth dev servers (Mailpit/MailHog).
- Test evidence: `tests/test_email_service.py:51` (`starttls.assert_called_once`), `:86` (`starttls.assert_not_called` when `use_tls=False`).
- Partial-delivery handling: `sender.py:74-81` inspects `sendmail` return dict (refused recipients) and returns `False` — prevents silent partial failure (good).

### 7. /docs OpenAPI presence — PASS (implicit)

- **api.py:127**: `FastAPI(title="email-service")`. No `docs_url=None` override → default `/docs` (Swagger UI) and `/openapi.json` are served.
- Note: `/docs` is unauthenticated by default. Acceptable for internal service-to-service deploy; if exposed publicly, consider gating.

### 8. Test coverage — STRONG

- Counts: 69 test functions across `test_api.py` (26), `test_client.py` (20), `test_email_service.py` (23).
- LOC ratio: 979 test lines vs ~330 source lines (~3x).
- Coverage observed:
  - Sender: STARTTLS on/off, AUTH on/off, CRLF rejection, partial-refusal failure, exception swallow.
  - API: auth (401), CRLF rejection at 422, dry-run on all 3 endpoints, dry-run still requires auth, dry-run still validates, dry-run accepts {true,1,yes}, magic-link 503 when unconfigured, response excludes None.
  - Client: bearer header, dry-run header translation, keyword-only enforcement, raise_for_status pass-through.

## Findings (Issues)

### M-01: SMTP_FROM env not validated at boot

- Severity: MEDIUM
- File: `email_service/api.py:102`
- Evidence: `from_addr=os.environ.get("SMTP_FROM", "")` — passed unvalidated into `SmtpConfig`. CRLF check happens per-send (sender.py:43) and silently returns False.
- Repro (static): Set `SMTP_FROM="ok@x.com\r\nBcc: attacker@evil"` → app boots fine → every `/send` returns 502 with no operator-visible cause beyond a per-request warning log.
- Fix direction: validate CRLF (and ideally email-shape) in `_build_sender_from_env`, raising `RuntimeError` at startup.

### L-01: TemplateNotifier subject uses unescaped context

- Severity: LOW
- File: `email_service/notifiers.py:122`
- Evidence: `subject = self._subject.format(**context)` — uses raw `context`, not `html_ctx`. Subject is a mail header, so HTML escape would be wrong, but CRLF safety depends entirely on `SmtpSender` downstream check.
- Repro: static — design is defensible (defense in depth at sender), but worth a comment.

### L-02: Empty `from_addr` not asserted in SmtpConfig

- Severity: LOW
- File: `email_service/sender.py:22-24`
- Evidence: `__post_init__` falls back `from_addr = self.user`, but both may be `""` (Mailpit no-auth case + no SMTP_FROM set). CRLF loop iterates `""` (passes), then `sendmail` called with empty sender → server-dependent error.
- Repro: static. SMTP server rejection masks config error.

## Baseline (machine-readable)

```json
{
  "date": "2026-05-15",
  "branch": "claude/sad-cannon-1131fe",
  "mode": "static",
  "health_score": 92,
  "dimensions": {
    "crlf_blocked": "pass",
    "html_escape": "pass",
    "constant_time_auth": "pass",
    "dry_run_keyword_only": "pass",
    "fail_fast_boot": "pass",
    "smtp_starttls_auth": "pass",
    "openapi_docs": "pass",
    "test_coverage": "strong"
  },
  "tests": {
    "count": 69,
    "files": {"test_api.py": 26, "test_client.py": 20, "test_email_service.py": 23},
    "total_loc": 979
  },
  "issues": {
    "critical": 0,
    "high": 0,
    "medium": 1,
    "low": 2
  },
  "top_fixes": [
    "Validate SMTP_FROM at boot (api.py:102)",
    "Document or guard TemplateNotifier subject CRLF (notifiers.py:122)",
    "Assert non-empty from_addr in SmtpConfig (sender.py:22)"
  ]
}
```
