# Security Audit — email-service

**Mode:** Daily (8/10 confidence gate)
**Date:** 2026-05-15
**Scope:** D:\email-service\.claude\worktrees\sad-cannon-1131fe
**Branch:** claude/sad-cannon-1131fe @ a7a8c86

## Stack

- Python >=3.10, FastAPI (`fastapi>=0.100`), uvicorn, pydantic v2, stdlib smtplib
- Library + thin HTTP shim (`email_service.api:create_app`)
- 4 HTTP routes: `GET /health`, `POST /send`, `POST /send/magic-link`, `POST /send/otp`
- Deployment: Dockerfile (python:3.12-slim), docker-compose.yml (prod), docker-compose.dev.yml (mailpit)
- No CI workflows (`.github/` absent)

## Attack Surface

| Surface | Count / Notes |
|---|---|
| HTTP endpoints | 4 (1 unauthenticated `/health`, 3 bearer-gated) |
| External deps at runtime | fastapi, uvicorn, pydantic, starlette (transitive) |
| Secrets sources | env vars: `SMTP_PASSWORD`, `API_KEY` |
| Tracked secret files | none (`.env` is gitignored; `.env.example` contains only placeholders) |
| CI surface | none |

## Findings

### [MEDIUM] (confidence 9/10) [VERIFIED] Supply-chain | Unpinned dependencies, no lock file | pyproject.toml:13-14

Dependencies use floor-only specifiers and there is no `uv.lock` / `poetry.lock` / `requirements.txt`:

```
dev  = ["pytest>=7.0", "httpx>=0.25"]
http = ["fastapi>=0.100", "uvicorn>=0.23", "httpx>=0.25"]
```

**Exploit scenario:** A compromised upstream release of fastapi/uvicorn/starlette (or any transitive) lands in production on the next `docker build` because `pip install ".[http]"` resolves to latest. Recent supply-chain incidents (e.g. PyPI account takeovers) make this a realistic vector.

**Impact:** Container builds are not reproducible. A malicious version published between two builds is silently adopted.

**Recommendation:** Generate a lock file (`uv lock` or `pip-compile`) and copy/install it inside the Dockerfile. At minimum, pin upper bounds (`fastapi>=0.100,<1.0`) and add `--require-hashes` for the production install.

---

### [MEDIUM] (confidence 8/10) [VERIFIED] Documentation | Magic-link token entropy is caller responsibility, not documented as a security contract | email_service/api.py:54-57, email_service/notifiers.py:70-78

`SendMagicLinkRequest.token` is accepted from the caller and only validated for `min_length=1`. The service URL-encodes it into the magic-link and emails it. Token entropy, single-use enforcement, expiry binding, and storage all live with the caller.

**Exploit scenario:** A downstream integrator passes a short or predictable token (e.g. timestamp, sequential id). Attackers brute-force the magic-link endpoint of the caller's app and take over accounts. The email-service is not the breach point, but it is the channel and there is no warning.

**Impact:** Account takeover risk for any caller that does not generate cryptographically random tokens (>=128 bits, e.g. `secrets.token_urlsafe(32)`).

**Recommendation:** Add a "Security responsibilities of the caller" section to README.md explicitly stating: tokens must be `secrets.token_urlsafe(>=32)` or equivalent, single-use, server-side expiry-bound, never logged. Optionally enforce a minimum length (e.g. 32 chars) at the pydantic layer as a defensive backstop.

---

### [LOW] (confidence 8/10) [VERIFIED] Configuration | Hardcoded dev API key in tracked file | docker-compose.dev.yml:12

`API_KEY: <redacted-weak-token>` is checked in. This is a dev-only compose file targeting mailpit, so the blast radius is local-only. The risk is operator confusion (someone copies this into prod) and search-engine indexing surfacing the literal string.

**Recommendation:** Either rename the value to something obviously fake (`API_KEY: "REPLACE_ME_dev_only_do_not_use_in_prod"`) or move it into a gitignored `.env.dev` referenced via `env_file:`.

---

## Verified Negatives (intentionally not findings)

The following were checked and are correctly handled:

- **A01 Broken Access Control:** Every send endpoint depends on `verify_key`. `/health` is intentionally unauthenticated and returns only `{"status":"ok"}` (no info leak). — api.py:130-140
- **A02 Cryptographic / timing-attack on API key:** `hmac.compare_digest(creds.credentials, api_key)` — constant-time comparison present. — api.py:133
- **A03 Injection / CRLF header injection:** Defense in depth. Pydantic validators reject `\r`/`\n` in `to`, `subject`, `cc`, `bcc` at the API boundary (api.py:25-51), and `SmtpSender.send` re-checks the same fields before constructing the MIME message (sender.py:43-46). HTML bodies are escaped in notifier templates via `html.escape` (notifiers.py:40-42, 73-77, 94-96).
- **A05 Security Misconfiguration:**
  - No CORS middleware installed — correct for an internal service-to-service API (no browser callers expected).
  - No debug mode: `uvicorn.run(app, ...)` without `reload=True` / `debug=True`. — __main__.py:11-15
  - Dockerfile creates non-root `app` user (uid 10001) and `USER app` before CMD. — Dockerfile:17-19
  - Required env vars fail-fast at startup via `_required_env`. — api.py:18-22, 117-118
- **A07 Identification & Authentication Failures:** Single shared bearer token; appropriate for service-to-service. No password-based auth, no session management surface.
- **Secrets in git history:** Searched added-line history for `password`, `AKIA`, `sk-`, `API_KEY=`. Only hits are `.env.example` (placeholder `replace-with-long-random-secret`), README example (`<임의의-긴-비밀문자열>`), and the dev compose redacted weak token. No real credentials ever committed. `.env` is not tracked.
- **Dockerfile env-var exposure:** No secrets baked in as `ENV` or `ARG`. Only non-sensitive runtime defaults (`HOST`, `PORT`, `PYTHONUNBUFFERED`). Secrets enter via `env_file: .env` at runtime (compose-level, not image-level).
- **Webhooks / LLM integrations:** None present — confirmed.
- **CI/CD risks (`pull_request_target`, unpinned actions):** `.github/` directory does not exist — N/A.
- **Partial-delivery silent failure:** `sender.py:74-81` checks the `refused` dict from `smtplib.sendmail` and returns False on any refusal — good observability hygiene.

## Summary

| Severity | Count |
|---|---|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 2 |
| LOW | 1 |

The codebase is small, well-scoped, and shows clear security awareness (constant-time auth comparison, double-layer CRLF rejection, non-root container, fail-fast env validation). The two MEDIUM items are both about contracts at the edges (supply chain and caller responsibility) rather than exploitable bugs in the code itself.

## Disclaimer

This is an automated daily audit at the 8/10 confidence gate. It is not a substitute for manual penetration testing, dependency CVE scanning (e.g. `pip-audit`, `osv-scanner`), or formal threat modeling. Findings reflect only what was statically observable in the worktree at audit time; runtime behavior, deployment-environment misconfigurations, and downstream caller behavior are out of scope.
