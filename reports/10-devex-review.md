# DX Review — email-service

**Mode**: DX EXPANSION
**Product**: Python library + FastAPI HTTP service
**Date**: 2026-05-15
**Overall DX**: 4.5/10 — Competitive tier (~3 min TTHW), missing magical moment

---

## Personas

- **A — Internal Python backend engineer**: `pip install`, imports `SmtpSender`, sends in-process.
- **B — Polyglot backend (Node/Go/Ruby)**: `pip install [http]`, runs server, calls via curl/HTTP.

Both used for journey tracing below.

---

## Empathy Narratives

### Persona A (Library mode, ~3 min)
Opens README, finds `pip install git+https://github.com/hwan96-ai/email-service.git` — pauses: not on PyPI? Wonders if this is production-ready. Imports `from email_service import SmtpSender` and `from email_service.sender import SmtpConfig` — two imports for one thing feels split. Constructs `SmtpConfig` with `host`, `user`, `password` — clean dataclass. Calls `sender.send(to, subject, html)` → returns `True`. Wait — only `True`? Tries with bad password: returns `False`. **No reason.** No exception. Has to grep logs for `smtplib.SMTPAuthenticationError`. The bool throws away every bit of diagnostic info SMTP gave us. Adds `logging.basicConfig(level=DEBUG)` and re-runs to dig it out. Writes a wrapper to retry on failure but can't distinguish auth-fail from network-down from invalid-recipient. Concludes: works, but the return shape forces every caller to re-implement error handling against log strings.

### Persona B (HTTP mode, ~3 min)
Reads README quickstart. Sets 4 env vars (SMTP_HOST, USER, PASSWORD, API_KEY), runs `python -m email_service`. Uvicorn boots cleanly, `/docs` Swagger shows up — pleasant surprise. Copies curl from README, swaps in `$API_KEY`, fires: `{"sent":true}`. Tries with wrong SMTP password: `502 {"detail":"Email send failed"}`. **That's it.** No error code, no doc URL, no machine-parseable hint. Now writes Node code that has to string-match `detail` to know whether to retry, alert, or 5xx upstream. Looks at `/docs` for help — operation summaries are empty (FastAPI default route names only). Searches for changelog to know if upgrade is safe — there is none. Version is `0.1.0`. Ships it anyway because deadline.

---

## Competitive Benchmark

| Tool | TTHW | Notable DX | Source |
|---|---|---|---|
| Resend | ~30s | `npx resend send` 1-cmd | resend.com |
| SendGrid | ~2min | SDK + API key | sendgrid.com |
| Mailgun | ~3min | curl docs prominent | mailgun.com |
| AWS SES | ~10min | IAM hell | aws.amazon.com |
| **email-service (current)** | **~3min** | Self-hosted, env-driven | this repo |

**Target tier**: Competitive (achieved). **Champion (<2min)** requires 1-shot CLI test command.

---

## Magical Moment (proposed)

`python -m email_service test --to me@example.com` — uses configured env vars, sends one real email, prints result with timing. Single command from install to "email landed in inbox." Estimated effort: ~30 min.

---

## Journey Trace

| Stage | Friction | Resolution |
|---|---|---|
| Discover | Not on PyPI — only `git+` install | Publish to PyPI. P1. |
| Install | `[http]` extras name not obvious | README comparison table sharper |
| Hello World | 3 min, 5 env vars manually | `email-service init` CLI prompts |
| Real Usage | `bool` return loses error context | `SendResult` dataclass with reason |
| Debug | Logs only — no debug mode | `EMAIL_SERVICE_DEBUG=1` env flag |
| Upgrade | No CHANGELOG, version frozen at 0.1.0 | Adopt semver + CHANGELOG.md |

---

## 8-Pass Scorecard

### Pass 1 — Getting Started: **6/10**
TTHW ~3 min. No PyPI, no quickstart script, no 1-shot test command.
**To reach 10**: `pipx run email-service test --to me@example.com` works in 30s from zero.

### Pass 2 — API/CLI/SDK: **7/10**
`EmailServiceClient` is clean — context manager, typed kwargs, `dry_run` keyword-only is a nice touch (recent fix). Missing: async variant (`AsyncEmailServiceClient`), no CLI subcommands beyond bare server boot.
**To reach 10**: async client + `python -m email_service test|init|send` subcommands.

### Pass 3 — Error Messages: **4/10**
`api.py:163,185,201` all return `"Email send failed"` with bare 502. No `error_code`, no `doc_url`, no actionable hint. Library `SmtpSender.send` returns `bool` — total diagnostic loss.
**To reach 10**: structured `{"error":{"code":"smtp_auth_failed","message":"...","doc_url":"https://.../errors#smtp_auth_failed"}}` and `SendResult` dataclass replacing `bool`.

### Pass 4 — Documentation: **6/10**
README is comprehensive (Korean, thorough, with security notes). No standalone docs site, no `examples/` directory, FastAPI operation summaries empty (Swagger `/docs` shows function names not descriptions).
**To reach 10**: examples/ with Flask/Django/FastAPI integrations + populated OpenAPI `summary` + `description` on every route.

### Pass 5 — Upgrade Path: **3/10**
No CHANGELOG.md. Version pinned at `0.1.0` since project start. No deprecation policy. Users have no way to know what changed between git pulls.
**To reach 10**: semver discipline + CHANGELOG.md + GitHub releases with notes.

### Pass 6 — Dev Environment: **7/10**
`docker-compose.dev.yml` with Mailpit is **excellent** — local-only end-to-end test with web UI. Inline type hints throughout. Missing: `examples/` dir, `.devcontainer` config.
**To reach 10**: examples/ + devcontainer + `make dev` Makefile.

### Pass 7 — Community: **2/10**
No CONTRIBUTING.md, no issue templates, no PR template, no Code of Conduct, no examples/. Single-author repo with no contributor on-ramp.
**To reach 10**: CONTRIBUTING.md + .github/ISSUE_TEMPLATE/ + examples/ + first-issue labels.

### Pass 8 — Measurement: **1/10**
Zero telemetry. No `/metrics` Prometheus endpoint. No send statistics. Operators flying blind on send-rate, failure-rate, SMTP latency.
**To reach 10**: `/metrics` Prometheus endpoint exposing `emails_sent_total{result="ok|fail",template="otp|magic_link|generic"}`, `smtp_send_duration_seconds`, build/version info.

---

## DX Scorecard

| Dimension | Score | Prior | Trend |
|---|---|---|---|
| Getting Started | 6/10 | — | baseline |
| API/CLI/SDK | 7/10 | — | baseline |
| Errors | 4/10 | — | baseline |
| Docs | 6/10 | — | baseline |
| Upgrade | 3/10 | — | baseline |
| Dev Env | 7/10 | — | baseline |
| Community | 2/10 | — | baseline |
| Measurement | 1/10 | — | baseline |
| **Overall** | **4.5/10** | — | baseline |

**TTHW**: ~3 min (Competitive)
**Magical moment**: missing
**Champion ceiling**: <2 min via `pipx run email-service test`

---

## Implementation Checklist (Top 10)

1. **Publish to PyPI** — eliminates `git+` friction (Pass 1, 4)
2. **`python -m email_service test --to <addr>` 1-shot CLI** — magical moment (Pass 1)
3. **`SendResult` dataclass with `error_code`** — replace bool return + bare 502 (Pass 3)
4. **CHANGELOG.md + semver discipline** — restore upgrade trust (Pass 5)
5. **`examples/` directory** — Flask, Django, FastAPI integration recipes (Pass 4, 7)
6. **`/metrics` Prometheus endpoint** — operator observability (Pass 8)
7. **CONTRIBUTING.md + issue templates** — community on-ramp (Pass 7)
8. **OpenAPI `summary`/`description` on each route** — `/docs` becomes self-serve (Pass 2, 4)
9. **`AsyncEmailServiceClient`** — async-native callers (Pass 2)
10. **`EMAIL_SERVICE_DEBUG=1` verbose mode** — structured debug logs on demand (Pass 3)

---

## Files Referenced

- `D:\email-service\.claude\worktrees\sad-cannon-1131fe\README.md`
- `D:\email-service\.claude\worktrees\sad-cannon-1131fe\email_service\__main__.py`
- `D:\email-service\.claude\worktrees\sad-cannon-1131fe\email_service\client.py`
- `D:\email-service\.claude\worktrees\sad-cannon-1131fe\email_service\api.py` (lines 163, 185, 201 — bare 502s)
- `D:\email-service\.claude\worktrees\sad-cannon-1131fe\pyproject.toml` (version 0.1.0, no PyPI metadata)
