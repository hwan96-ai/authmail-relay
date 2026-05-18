# CSO Release Audit — email-service v0.3.0
Date: 2026-05-16
Auditor: CSO (release gate)
Scope: extends Code Gate (does not re-discover SSRF, length caps, /send rate limit, BackgroundTasks sync sleep, SMTP double-send — these remain P0 inherited).

---

## Findings

### 1. Loose dependency floors with no lock file
- **category**: supply-chain / OWASP-A08
- **location**: `pyproject.toml:19-26`
- **severity**: P1
- **finding**: All HTTP-extra pins are floor-only with a major-version ceiling (`fastapi>=0.115,<1`, `uvicorn>=0.30,<1`, `httpx>=0.27,<1`, `prometheus-client>=0.20` with no upper bound, `python-json-logger>=2.0` with no upper bound). No `requirements.lock` exists (line 12-13 has a TODO). A future malicious 0.9999 of any of these would be auto-pulled by downstream users.
- **exploit_scenario**: Account compromise of an upstream maintainer (cf. `colors.js`, `ua-parser-js`) leads to a malicious patch release. Any user who `pip install email-service[http]` after the compromise picks it up. `python-json-logger` has an unbounded upper, so a 3.x release with new transitive deps is silently accepted.
- **mitigation**: Immediate — add upper bounds for `prometheus-client<1` and `python-json-logger<4` (current major). Long-term — generate `requirements.lock` via `uv pip compile` or `pip-compile`, commit it, install via `pip install -r requirements.lock` in Docker. Add `pip-audit` to CI.

### 2. No CVE scanning in CI
- **category**: CVE / supply-chain
- **location**: `.github/workflows/` (no scan workflow present alongside release.yml)
- **severity**: P2
- **finding**: There is no `pip-audit`, `safety`, or `osv-scanner` job. Known CVEs in transitive deps (e.g. historical `starlette` `MultiPartParser` DoS, `h11` request smuggling fixes) would not be caught before release.
- **exploit_scenario**: A starlette CVE published the week before tag-push is shipped to PyPI because nothing checks. Downstream users inherit it.
- **mitigation**: Immediate — add a `pip-audit` step gated on the tag-push job before `python -m build`. Long-term — Dependabot or Renovate on the repo plus weekly scheduled scan.

### 3. Unpinned GitHub Actions (mutable tags)
- **category**: supply-chain / OWASP-A08 / release-process
- **location**: `.github/workflows/release.yml:29,31,42`
- **severity**: P1
- **finding**: `actions/checkout@v4`, `actions/setup-python@v5`, `pypa/gh-action-pypi-publish@release/v1` are all mutable refs. A repo compromise of any of these (cf. `tj-actions/changed-files` March 2025 incident) would let the attacker run arbitrary code with `id-token: write`, minting a PyPI publish token and publishing a malicious wheel under our project name.
- **exploit_scenario**: Compromise of `pypa/gh-action-pypi-publish` repo or its release tag. Attacker’s code runs in the `pypi` environment with OIDC write, publishes a backdoored `email-service==0.3.1`. Every downstream user is affected.
- **mitigation**: Immediate — pin every action to a full commit SHA with a comment for the human-readable version, e.g. `uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11 # v4.1.1`. Long-term — enable Dependabot for `github-actions` ecosystem so SHA bumps come as PRs.

### 4. SMTP debug leaks AUTH password to stderr in production-capable environment
- **category**: secrets / OWASP-A09
- **location**: `email_service/sender.py:311-312` (`server.set_debuglevel(1)` when `EMAIL_SERVICE_DEBUG=1`); documented in CHANGELOG line 30
- **severity**: P1
- **finding**: When `EMAIL_SERVICE_DEBUG=1`, `smtplib.set_debuglevel(1)` dumps the full SMTP wire conversation — including `AUTH PLAIN <base64(user\0user\0password)>` — to stderr. There is no environment gate (no `if env == "production": refuse`). README comment is the only guardrail. In a containerized prod where stderr is shipped to a log aggregator, an operator flipping the flag for a "quick check" exfiltrates the SMTP password into Splunk/Datadog/CloudWatch indefinitely.
- **exploit_scenario**: SRE debugging a prod incident sets `EMAIL_SERVICE_DEBUG=1`, restarts the container. SMTP password lands in centralized logs, retained 90+ days, queryable by anyone with log read access. The base64 is trivially reversed.
- **mitigation**: Immediate — refuse to enable `set_debuglevel` unless `EMAIL_SERVICE_ENV in {"dev","test"}` OR add a startup banner `WARNING: SMTP debug enabled — credentials WILL be logged`. Long-term — write a custom debug routing that masks AUTH lines (regex-replace base64 payload after `AUTH PLAIN `/`AUTH LOGIN `).

### 5. PII hashing is unsalted — recipients are enumerable
- **category**: PII / OWASP-A02
- **location**: `email_service/logging_config.py:40-42`
- **severity**: P2
- **finding**: `hash_recipient` is `sha256(addr)[:8]` with no salt. Eight hex chars = 32 bits of namespace. (a) An attacker with log access can confirm whether a specific address received mail by hashing candidates (`sha256("alice@corp.com")[:8]`) and grepping. (b) Across services that import this package, the same address hashes identically — cross-service correlation. (c) 32-bit truncation also produces collisions but doesn’t prevent confirmation attacks.
- **exploit_scenario**: Attacker with read access to centralized logs (or a leaked log dump) wants to know if `ceo@target.com` uses this service. Computes hash, greps. Confirmed presence + timing = de-anonymized.
- **mitigation**: Immediate — add a per-deployment salt via `EMAIL_SERVICE_LOG_SALT` env var, mix into the hash (`hashlib.sha256(salt + addr).hexdigest()[:12]`). Long-term — use HMAC-SHA256 with a rotated key kept out of the image; document in README that the hash is a per-deployment opaque token, not a global identifier.

### 6. Constant-time API key compare is correct, but no auth throttling
- **category**: OWASP-A07 / OWASP-A04
- **location**: `email_service/api.py:206, 231` (uses `hmac.compare_digest` ✅) + absent rate-limiter on 401 paths
- **severity**: P1
- **finding**: Token compare itself is constant-time — good. But there is no per-IP throttle on auth failures. Combined with the known absent /send rate limit, an attacker can brute-force the bearer token at line-rate. Even with a 32-byte hex token (recommended in `.env.example`), unbounded attempts produce a slow but real risk on weaker-than-recommended keys (operators who used `openssl rand -hex 8`).
- **exploit_scenario**: Operator picks a short key for convenience. Attacker fires 10k req/s of bogus Bearer tokens at /send. No throttle, no lockout, no alert.
- **mitigation**: Immediate — document in README that API_KEY MUST be ≥32 bytes (already advises `-hex 32` ✅, but not enforced at boot). Add a boot-time `len(api_key) < 32: raise RuntimeError`. Long-term — add SlowAPI/limits middleware with separate buckets for 401 vs 2xx; alert on >50 401s/min from one IP.

### 7. webhook_secret echoed back to attacker on misrouted webhooks (info leak in logs)
- **category**: OWASP-A09 / secrets
- **location**: `email_service/webhooks.py:51-65` and `api.py:286`
- **severity**: P2
- **finding**: When an attacker supplies a `webhook_url` they control (the inherited SSRF P0), they receive the request body which includes hash signatures computed with caller-supplied `webhook_secret`. If a downstream legit caller uses the same `webhook_secret` for multiple targets, the attacker now has signed payloads usable as oracle for HMAC verification probing. More directly: an attacker who can POST `/send` with `webhook_url=http://attacker/sink&webhook_secret=<guess>` receives an `X-Email-Service-Signature` over a known body, letting them brute-force short secrets offline.
- **exploit_scenario**: Attacker hits `/send` 10 times each with a 6-char `webhook_secret` guess, observes signature returned to their controlled sink. Confirms via offline HMAC computation. Pivots to forging callbacks against the same secret used by legit caller (if reused).
- **mitigation**: Immediate — minimum length check on `webhook_secret` (>=32 chars) and reject in pydantic validator. Long-term — couple webhook_secret to a server-issued per-tenant key, not caller-supplied. (Also blocked by SSRF fix from Code Gate.)

### 8. Default bind 0.0.0.0 documented as “use this in Docker”
- **category**: OWASP-A05
- **location**: `.env.example:33-36` + (assumed) module main
- **severity**: P2
- **finding**: The example tells users to bind `0.0.0.0` for Docker without an accompanying reminder that the service exposes /send and /metrics. If a user runs Docker on a host with public IP and no firewall, /send is internet-reachable. With METRICS_REQUIRE_AUTH defaulting to off (line 217 of api.py), /metrics is world-readable and leaks `email_send_total{}` cardinality — including labels like `error_code` which expose volume and failure modes to a passing attacker.
- **exploit_scenario**: Solo dev runs `docker compose up` on a $5 VPS, port 8000 is published. Anyone hits `/metrics` to learn deployment exists + traffic shape, then hits `/send` to brute force the key. README says “bind 0.0.0.0” — looks normal.
- **mitigation**: Immediate — change `.env.example` comment to “only bind 0.0.0.0 behind a reverse proxy / firewall”; default `METRICS_REQUIRE_AUTH=true` in production guidance. Long-term — refuse to start with `HOST=0.0.0.0` AND `METRICS_REQUIRE_AUTH` unset, unless `EMAIL_SERVICE_ALLOW_PUBLIC_BIND=1`.

### 9. STARTTLS handled correctly, but no certificate hostname pinning option
- **category**: TLS / OWASP-A02
- **location**: `sender.py:317-340`
- **severity**: P3
- **finding**: `starttls(context=ssl.create_default_context())` is the right default — verifies cert chain + hostname. No issue today. However, there is no escape hatch documented for self-signed internal SMTP (and no opt-in for `check_hostname=False` either, which is good). Risk is purely operational: a user with a self-signed corporate relay may be tempted to monkey-patch the context insecurely. Worth a README note.
- **exploit_scenario**: N/A under default config. MITM-resistant via stdlib defaults.
- **mitigation**: Immediate — none required. Long-term — document an `SmtpConfig(tls_context=...)` injection point so users don’t reach for `ssl._create_unverified_context()`.

### 10. httpx webhook delivery uses default verify=True ✅ but no SSRF guard (inherited)
- **category**: TLS / OWASP-A10 (inherited)
- **location**: `webhooks.py:59` (`httpx.Client(timeout=timeout)`)
- **severity**: P0 (already flagged by Code Gate — re-confirmed)
- **finding**: TLS verification defaults are correct (`httpx.Client` defaults to `verify=True`). However the SSRF still allows internal hosts; combined with `verify=False` not being settable, TLS is OK but private-IP / metadata-service POSTs (169.254.169.254) are unblocked. Re-listing for completeness against the P0 inheritance.
- **mitigation**: see Code Gate.

### 11. CHANGELOG promises “0.2.0” FastAPI app version but bumped pyproject to 0.3.0
- **category**: release-process
- **location**: `email_service/api.py:172` (`version="0.2.0"`) vs `pyproject.toml:7` (`0.3.0`) vs `CHANGELOG.md:5`
- **severity**: P2
- **finding**: FastAPI OpenAPI advertises version 0.2.0; package version is 0.3.0. OpenAPI consumers / SDK generators will produce a mismatched artifact.
- **exploit_scenario**: Not a direct exploit — but a release-readiness blocker for any consumer that uses OpenAPI version for cache-busting or compat checks. Indicates the version bump was mechanical (pyproject + CHANGELOG) without a grep for other version strings.
- **mitigation**: Immediate — read version from `email_service.__version__` or `importlib.metadata.version("email-service")` in `create_app()`. Long-term — single source of truth for version, enforced by a `release` check.

### 12. Single shared API_KEY — no multi-tenant doc
- **category**: OWASP-A01 / release-process
- **location**: `.env.example:12-16`, `api.py:161,231`
- **severity**: P2
- **finding**: One bearer token grants full send rights to all endpoints. There is no per-caller identity, no scopes, no audit trail of who sent what. CHANGELOG and README do not call this out as a constraint. A downstream consumer plugging this in as a “shared microservice” for 5 teams gives every team full ability to send as anyone.
- **exploit_scenario**: Team A’s key is leaked in a misconfigured CI log; attacker now sends phishing magic-links to Team B’s users from a legitimate domain.
- **mitigation**: Immediate — add a “Security Model — Single Tenant” section to README stating: this service trusts every caller with API_KEY equally; deploy one instance per tenant or front it with an authenticating proxy that adds caller identity. Long-term — multi-key support keyed by header (`X-Caller`) with per-key rate limits.

### 13. Webhook payload contains `error_message` with raw exception text
- **category**: OWASP-A09 / info-leak
- **location**: `api.py:284` (`"error_message": str(exc)`)
- **severity**: P3
- **finding**: On background-task failure the webhook payload includes `str(exc)`. If exception carries SMTP server hostname, internal path, or credential fragment from a misconfigured auth, this exfiltrates to the (attacker-controlled, given SSRF) webhook URL.
- **exploit_scenario**: Combined with SSRF, attacker `webhook_url=http://attacker`, triggers a configured-wrong send path, receives e.g. `str(exc) = "[Errno -2] Name or service not known: 'internal-smtp.corp.local'"`. Now they know an internal hostname.
- **mitigation**: Immediate — whitelist exception fields that flow to webhook payload; do not include `str(exc)`. Long-term — error code only; details in server logs.

### 14. CRLF guard is applied to subject/to/cc/bcc but `user_name` is NOT validated
- **category**: OWASP-A03 / SMTP-injection
- **location**: `api.py:69-92` (`SendMagicLinkRequest`, `SendOTPRequest`) — only `to` has `_reject_crlf`; `user_name` flows into HTML/text body
- **severity**: P3
- **finding**: `user_name` is HTML-escaped by notifiers (`escape(user_name)` in `notifiers.py:159,199`), so HTML injection is closed. But for the **plain-text** part, `notifiers.py:163-164,203-204` formats `text_template.format(name=user_name, ...)` with no escape — and the text alternative is part of the MIME body, not a header, so CRLF cannot inject SMTP headers. So the impact is bounded to the text-part body content. Still worth a defensive `_no_crlf` on user_name to keep guarantees uniform.
- **exploit_scenario**: An attacker who controls user_name (e.g., via signup form) inserts characters that disrupt plain-text rendering in some MUAs. Low impact.
- **mitigation**: Immediate — add `_reject_crlf` validator to `user_name` on both notifier request models. Long-term — central pydantic StrictStr type bound for all string fields with CRLF + length cap.

### 15. No request body size limit at uvicorn / FastAPI layer
- **category**: OWASP-A04 / DoS
- **location**: module main (uvicorn launch) + api.py (no `MAX_BODY_SIZE`)
- **severity**: P1
- **finding**: Code Gate already flagged absent `max_length` on `html_body/subject`. Even with those, `cc`/`bcc` list lengths and overall request bytes are unbounded. An attacker uploads a 100MB `cc=["a@b", ...]` list, consuming worker memory and tying up a `BackgroundTasks` slot (per the inherited sync-sleep P0).
- **exploit_scenario**: 4 concurrent 100MB POSTs to /send saturate the FastAPI process; combined with sync BackgroundTasks (inherited P0), entire service is unresponsive.
- **mitigation**: Immediate — uvicorn `--limit-request-line`/middleware-level `Content-Length` cap (e.g. 1MB). Pydantic `Field(max_length=...)` for html_body (already in Code Gate), plus `max_items` on cc/bcc lists. Long-term — async send queue + per-request budget.

---

## Summary

### ship_recommendation
**BLOCK**

### block_reason
Inherited from Code Gate (still open):
- P0: webhook_url SSRF (api.py:51 / webhooks.py:33-65)
- P0: html_body/subject no max_length DoS (api.py:51)
- P0: /send rate limit absent (api.py:158-161)
- P0: BackgroundTasks runs sync time.sleep on event loop (api.py:286 / webhooks.py:33-95)
- P0: SMTP post-DATA disconnect retry → double-send (sender.py:225-291)

New from CSO that must be fixed before SHIP:
- P1 unpinned GitHub Actions in `release.yml` (Trusted Publisher OIDC is wasted if action ref is mutable)
- P1 `EMAIL_SERVICE_DEBUG` leaks SMTP password to stderr with no env guard
- P1 No body-size / list-length caps (compounds DoS P0s)
- P1 Loose deps + no lock file + no pip-audit in CI
- P1 No auth-failure throttle / no boot-time min-length check on API_KEY

### top_5_new_security_issues (not previously flagged by Code Gate)
1. **Unpinned GitHub Actions in `release.yml`** — `@v4`/`@v5`/`@release/v1` mutable refs combined with `id-token: write` is a one-CVE-away supply-chain compromise of every downstream `pip install`.
2. **`EMAIL_SERVICE_DEBUG=1` dumps base64 SMTP password to stderr unconditionally** — no env gate, no redaction; CHANGELOG even advertises it.
3. **`hash_recipient` is unsalted 32-bit SHA-256 prefix** — recipient enumeration + cross-deployment correlation attack on logs.
4. **No upper bound on `prometheus-client` / `python-json-logger`, no lock file, no CVE scan** — supply-chain timebomb.
5. **OpenAPI version 0.2.0 ≠ package 0.3.0** + single shared API_KEY with no multi-tenant doc — release process hygiene gap that bites integrators.

### supply_chain_risk_score
**8 / 10**

Justification: Trusted Publisher OIDC is set up correctly (good), but every action in the publish workflow uses a mutable ref while holding `id-token: write` (bad). No lock file, no pip-audit, no Dependabot for actions, no upper bound on two deps. One upstream compromise = malicious wheel on PyPI under our name. The mitigation is well-understood and cheap (SHA-pin the four lines in release.yml + add pip-audit step) — but it isn't done, so the risk is real today.
