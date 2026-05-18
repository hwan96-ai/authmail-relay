# Adversarial Release Audit — email-service v0.3.0

Date: 2026-05-16
Auditor role: Senior SRE + Security
Scope: post-deploy operational risk (in addition to Code Gate P0 findings, which are not re-listed).

---

## Findings

### F-01 — OpenAPI version drift (semver lie)
- **category**: 8 (ops guide / release hygiene)
- **location**: `email_service/api.py:172` — `version="0.2.0"`; `pyproject.toml:7` — `version = "0.3.0"`
- **production_scenario**: Client introspects `/openapi.json` to gate compatibility ("require >=0.3"). Service reports `0.2.0`, client refuses to call, or worse: client trusts the version and skips a workaround that's only needed on real 0.2.0.
- **blast_radius**: All HTTP clients that pin against OpenAPI version. Silent contract bug.
- **severity**: P2
- **evidence**: `version="0.2.0"` literal in `create_app` vs CHANGELOG `[0.3.0] - 2026-05-15` and `pyproject.toml`.
- **mitigation**:
  - Immediate: replace with `importlib.metadata.version("email-service")`.
  - Long-term: CI check that fails when pyproject version ≠ OpenAPI version ≠ git tag.

---

### F-02 — Single static API_KEY, no rotation primitive
- **category**: 1 (auth/권한)
- **location**: `email_service/api.py:161` (`api_key = _required_env("API_KEY")`), `api.py:231` (`hmac.compare_digest(creds.credentials, api_key)`)
- **production_scenario**: Key leaks to a downstream service log. To rotate, ops must (a) generate new key, (b) restart the service (key is read once at boot), (c) update every caller atomically. There is no overlap window — any caller not updated in lockstep gets 401.
- **blast_radius**: Forced downtime for every caller during rotation; in a multi-tenant deploy, all tenants share one key so any leak compromises all tenants.
- **severity**: P1
- **evidence**: Single `_required_env("API_KEY")` call, no plural form, no JWT/HMAC kid pattern, no `API_KEYS` (list) support.
- **mitigation**:
  - Immediate: document a "key rotation procedure" runbook (planned outage window, blast-radius).
  - Long-term: accept `API_KEYS` comma-list, iterate `compare_digest` against all; OR move to per-caller HMAC with key-id header.

---

### F-03 — uvicorn single-worker default + sync SMTP in event loop
- **category**: 3 (성능 절벽)
- **location**: `email_service/__main__.py:28` — `uvicorn.run(app, host=..., port=...)` (no `workers=`); `email_service/api.py:305` `def send_email(...)` is a **sync** def, so FastAPI runs it in the threadpool. `email_service/sender.py:225` `time.sleep(delay)` inside retry loop.
- **production_scenario**: Default uvicorn single worker, FastAPI's threadpool defaults to 40 threads. Sync `/send` endpoint occupies one threadpool slot for the duration of an SMTP handshake (10s timeout × up to 4 attempts = 40s worst case). 40 concurrent slow SMTP calls and the entire service stops accepting requests — including `/health`, which causes the docker `healthcheck` to mark the container unhealthy and `restart: unless-stopped` to kill it mid-send.
- **blast_radius**: Cascading restart loop during SMTP provider degradation. All in-flight sends lost. Background tasks (webhook async) are killed on SIGTERM with no drain.
- **severity**: P0
- **evidence**: No `workers=` in `uvicorn.run`; sync route handlers; `time.sleep` inside threadpool.
- **mitigation**:
  - Immediate: document recommended `gunicorn -k uvicorn.workers.UvicornWorker -w N` deploy; add `--timeout-graceful-shutdown` to drain BackgroundTasks; add separate readiness probe distinct from `/health` that does not depend on threadpool capacity.
  - Long-term: switch hot path to `aiosmtplib` so event loop is the unit of concurrency, not threadpool slots.

---

### F-04 — Prometheus multiprocess mode unconfigured → metrics-per-worker drift
- **category**: 3 + 6 (성능 / 모니터링)
- **location**: `email_service/metrics.py` — uses default `prometheus_client` registry; `email_service/api.py:225` calls `metrics_module.render_latest()` directly.
- **production_scenario**: As soon as ops follow the F-03 fix and run multiple uvicorn workers, each worker has its own in-process counter. `/metrics` returns whichever worker the LB happens to land on — Prometheus scrape sees a counter that randomly drops by 1/N. Alert thresholds based on rate become noise.
- **blast_radius**: All observability signals become unreliable in production. Silent — you only notice when an incident's metrics don't add up.
- **severity**: P1
- **evidence**: No `PROMETHEUS_MULTIPROC_DIR` handling, no `MultiProcessCollector`. Default Counter/Histogram/Gauge are process-local.
- **mitigation**:
  - Immediate: pin deploy to `workers=1` until fixed (sacrifices F-03 fix).
  - Long-term: add `prometheus_client.multiprocess.MultiProcessCollector` path, mount tmpfs at `PROMETHEUS_MULTIPROC_DIR`, document in deploy guide.

---

### F-05 — `EMAIL_SERVICE_DEBUG=1` writes SMTP AUTH (base64 password) to stderr
- **category**: 7 (시크릿 노출)
- **location**: `email_service/sender.py:311-312` — `if _debug_enabled(): server.set_debuglevel(1)`
- **production_scenario**: An incident responder sets `EMAIL_SERVICE_DEBUG=1` in production to investigate SMTP timeouts. Docker logs ship to a central log aggregator (Datadog/Loki/CloudWatch). Base64-decoded password is now in the log index, retained for the platform's default retention (often 30+ days), visible to anyone with log-read access. SMTP provider rotation required, plus possibly disclosure depending on jurisdiction.
- **blast_radius**: Full SMTP credential compromise. Catastrophic if the SMTP account can send from the company domain (DKIM-signed phishing potential).
- **severity**: P1
- **evidence**: Code comment at line 308-310 explicitly acknowledges the danger but ships the flag anyway with only a README warning gate.
- **mitigation**:
  - Immediate: refuse to enable when `ENV=production` (check `EMAIL_SERVICE_ENV` or block when not on localhost).
  - Long-term: replace with structured debug logging that redacts AUTH lines (write a thin wrapper that intercepts smtplib's `_print_debug` to strip lines matching `AUTH\s+`).

---

### F-06 — `/metrics` opt-in auth (METRICS_REQUIRE_AUTH default off) leaks send volumes
- **category**: 6 (모니터링 사각지대) + 1 (auth)
- **location**: `email_service/api.py:202` — `if not _truthy(os.environ.get("METRICS_REQUIRE_AUTH")): return`
- **production_scenario**: Service deployed behind a public LB. `/metrics` enabled (per CHANGELOG "Optional `/metrics`"). Anyone on the internet can scrape `email_send_total`, `email_retry_attempts_total`, `email_webhook_failed_total` and derive send volume, failure rate, customer activity windows. Competitive intel / DDoS targeting signal.
- **blast_radius**: Information disclosure; depending on labels, may reveal error_code distribution that indicates which SMTP provider is in use.
- **severity**: P2
- **evidence**: Default `METRICS_REQUIRE_AUTH` unset → `_metrics_auth` returns immediately.
- **mitigation**:
  - Immediate: flip default — auth required unless explicitly `METRICS_REQUIRE_AUTH=false`.
  - Long-term: separate `/metrics` to a private port (uvicorn admin app pattern), never expose on the public listener.

---

### F-07 — Webhook BackgroundTasks lost on container restart, no drain
- **category**: 3 + 9 (성능 / SPOF)
- **location**: `email_service/api.py:326-328` — `background_tasks.add_task(...)` + `email_service/__main__.py:28` no signal handlers; docker-compose `restart: unless-stopped`.
- **production_scenario**: 50 in-flight `/send` requests with `webhook_url` are queued as BackgroundTasks. Ops triggers a deploy. uvicorn receives SIGTERM. FastAPI's BackgroundTasks have **no built-in drain** — the asyncio loop is cancelled, pending tasks (which include `time.sleep(60)` between webhook retries) get `CancelledError` and disappear. Caller never receives the webhook for those 50 emails — but the emails were sent. Caller's accounting now has 50 phantom in-flight requests until their own timeout fires (if any).
- **blast_radius**: Per-deploy: any caller relying on webhook for state machine progression stalls. Magic-link / OTP flows show "sending..." indefinitely.
- **severity**: P1
- **evidence**: No `lifespan`/`shutdown` handler in `create_app`; no task drain; webhook backoff `(1, 10, 60)` sleeps occupy threadpool past graceful shutdown timeouts.
- **mitigation**:
  - Immediate: document that `webhook_url` is best-effort and **not durable** in the API docstring; tell callers to also poll.
  - Long-term: replace BackgroundTasks with a real queue (Redis + RQ, or SQS) so webhook delivery survives restarts.

---

### F-08 — No dependency lockfile → reproducibility / supply chain
- **category**: 4 (의존성 취약점)
- **location**: `pyproject.toml:12-13` — explicit `# TODO: generate a requirements.lock`; Dockerfile `RUN pip install ".[http]"` resolves at build time.
- **production_scenario**: A transitive dep ships a malicious or broken release between two image builds of the same git SHA. Two CI runs of the same commit produce different images. Post-incident "what changed?" answer is "we don't know — pip resolved differently." Also: PyPI dependency confusion attack via similar-named packages becomes harder to detect without a lockfile audit trail.
- **blast_radius**: Indeterminate. Worst case: silent malicious code execution in the build container, leak via build secrets.
- **severity**: P1
- **evidence**: TODO comment in pyproject.toml; no `uv.lock` / `requirements.lock` / `poetry.lock` in repo root.
- **mitigation**:
  - Immediate: `pip freeze > requirements.lock` from a known-good build, commit, `Dockerfile` uses `pip install -r requirements.lock`.
  - Long-term: `uv lock` + Dependabot + `pip-audit` in CI.

---

### F-09 — PyPI release: no manual approval, irreversible, no checksum verification before publish
- **category**: 5 (롤백 불가)
- **location**: `.github/workflows/release.yml` — fires on `push` of any `v*` tag with no `environment` approval gate beyond the named environment.
- **production_scenario**: Maintainer pushes a tag from a dirty workspace or wrong branch. Workflow auto-builds and publishes to PyPI. PyPI permits **yank** but not delete — version number is burned forever. Worse: the bad 0.3.1 sits on PyPI for the 30s it takes a CDN to propagate before yank is effective; downstream `pip install email-service` during that window pulls the bad release and pins it via lockfile.
- **blast_radius**: Bad release uncorrectable; only path is `0.3.2`. Downstream lockfiles can keep the bad version alive indefinitely.
- **severity**: P1
- **evidence**: `on: push: tags: ["v*"]` — no `workflow_dispatch` requirement, no manual approval reviewer, no smoke test on built artifacts before publish.
- **mitigation**:
  - Immediate: add `environment: pypi` reviewers (the `environment` is declared but unclear if reviewer rule is enforced; verify in repo settings).
  - Immediate: insert smoke test step between `build` and `publish` — install the built wheel in a fresh venv, import, run `python -m email_service test --help`.
  - Long-term: separate `release-rc` (TestPyPI) and `release` (PyPI) workflows; promote only after RC dwell time.

---

### F-10 — Webhook HMAC: timing attack on signature header, no replay protection
- **category**: 1 (auth)
- **location**: `email_service/webhooks.py:28-31` — `_sign` uses `hexdigest()`; caller-side verification is the caller's problem but no timestamp/nonce is in the signed payload.
- **production_scenario**: Attacker captures one webhook delivery (e.g., by being on the same VPC mesh and reading raw HTTP). Replays it indefinitely; caller has no way to detect (no `sent_at` is in the signed envelope at the header level, only in the body which can be forged-then-resigned only with the secret — so this is actually OK for forgery, but replay is open).
- **blast_radius**: A delivered webhook for OTP=482901 can be replayed; if caller treats webhook as the trigger for "user verified", attacker locks the account out of step.
- **severity**: P2
- **evidence**: No timestamp header in `headers` dict in `deliver_webhook`; signature covers body only.
- **mitigation**:
  - Immediate: add `X-Email-Service-Timestamp` header, include in signed prefix (`sha256=HMAC(secret, timestamp + "." + body)`); document caller must reject timestamps >5 min old.
  - Long-term: idempotency key (`message_id`) caller-side dedupe documented.

---

### F-11 — `BackgroundTasks` swallow all exceptions silently to webhook only
- **category**: 6 (모니터링)
- **location**: `email_service/api.py:275` — `except Exception as exc: # pragma: no cover - defensive` → logs `exception` then POSTs to webhook.
- **production_scenario**: If `webhook_url` is the dead-letter destination AND it's down, the exception is logged but no metric increments (the `email_send_total{result="failure"}` counter is only incremented inside `sender.send`, but if `send_fn()` itself raises an unexpected exception before the counter increments — e.g., OOM in template rendering — the failure is invisible in Prometheus). No alert can fire.
- **blast_radius**: Silent error class. Hard to detect without log-based alerts that compete with metric-based alerts.
- **severity**: P2
- **evidence**: `_run_and_notify` only emits webhook + log on exception, no metric counter.
- **mitigation**:
  - Immediate: add `email_background_task_failed_total` counter increment in the except branch.
  - Long-term: structured error budget tracking covering background path.

---

### F-12 — No request body size limit / no rate limit (re-confirmed, ops view)
- **category**: 3 + 9
- **location**: `email_service/api.py` — no `Limit-*` middleware, no `slowapi`/`limits`, no max body size; uvicorn default is unbounded.
- **production_scenario**: Authenticated caller (compromised key per F-02) sends a 100 MB `html_body`. The Pydantic model accepts. The SMTP server might or might not accept; the threadpool slot is occupied for the duration; memory spikes. With 40 threadpool slots × 100 MB = 4 GB resident, OOM-kill.
- **blast_radius**: Single bad caller can take down all-tenants service. Combined with F-03 means easy DOS.
- **severity**: P0 (already known from Code Gate but ops-confirming the deploy impact)
- **evidence**: No `MAX_REQUEST_BODY_BYTES` env, no middleware enforcing length.
- **mitigation**:
  - Immediate: deploy-side mitigation — set `client_max_body_size 1m;` at the upstream proxy (nginx/Caddy/ALB), refuse to deploy without it.
  - Long-term: in-app `Content-Length` check middleware so the service is safe even without a proxy.

---

### F-13 — `restart: unless-stopped` masks crash loops
- **category**: 6 (모니터링)
- **location**: `docker-compose.yml:14` — `restart: unless-stopped`
- **production_scenario**: Bad config (`SMTP_HOST` typo) → boot fails with `RuntimeError`. Docker restarts immediately. Restarts every ~5s indefinitely. Nothing surfaces unless someone watches docker events; healthcheck only runs once container is up.
- **blast_radius**: Hidden outages. Container appears "running" briefly between crashes.
- **severity**: P2
- **evidence**: No `on-failure:N` cap, no orchestrator backoff config.
- **mitigation**:
  - Immediate: switch to `restart: on-failure:5` for crash bounding; add log-based alert on "Required environment variable missing" message.
  - Long-term: explicit liveness vs readiness probes; orchestrator-level CrashLoopBackOff visibility (k8s) or compose-level healthcheck on boot.

---

### F-14 — Dockerfile not multi-stage, ships pip + build cache
- **category**: 4 + 7 (dep / 노출 표면)
- **location**: `Dockerfile` — single stage, `python:3.12-slim` base, `pip install ".[http]"` runs in final image.
- **production_scenario**: Final image carries `pip`, setuptools, wheel cache, ~100MB of bloat. Larger image = slower pulls during rollback (longer time to recover). Also: any CVE in `pip`/`setuptools` is present in production even though they're not needed at runtime.
- **blast_radius**: Slower MTTR; larger attack surface.
- **severity**: P3
- **evidence**: Single `FROM` in Dockerfile.
- **mitigation**:
  - Immediate: accept for v0.3.0.
  - Long-term: builder + runtime multi-stage; copy only `email_service/` and installed site-packages to a `python:3.12-slim` runtime stage.

---

### F-15 — No HEALTHCHECK in Dockerfile (only compose-level)
- **category**: 6
- **location**: `Dockerfile` — no `HEALTHCHECK` instruction; `docker-compose.yml:15-20` defines one.
- **production_scenario**: Deploy outside docker-compose (k8s, ECS, plain `docker run`) loses the healthcheck. Operator copy-pastes `docker run` from README and there's no built-in liveness signal.
- **blast_radius**: Per-platform: silent unhealthy containers.
- **severity**: P3
- **evidence**: Dockerfile ends at `CMD` without HEALTHCHECK.
- **mitigation**: Add `HEALTHCHECK CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else 1)"` to Dockerfile so it's portable.

---

### F-16 — No SMTP circuit breaker / no fallback provider
- **category**: 9 (외부 의존 SPOF)
- **location**: `email_service/sender.py` retry loop hits the same `SMTP_HOST` forever.
- **production_scenario**: Primary SMTP provider (e.g., SES) outage. Every `/send` retries 3× with `(1, 5, 25)` backoff = ~31s per request occupying a threadpool slot. Combined with F-03: provider down ⇒ service down within seconds.
- **blast_radius**: Full outage during SMTP provider degradation. No half-open probes; no automatic failover.
- **severity**: P1
- **evidence**: Single `SMTP_HOST` env, no `SMTP_FALLBACK_HOST`, no circuit-breaker state.
- **mitigation**:
  - Immediate: lower `max_retries` to 0 on the hot path; let caller retry; document this trade-off.
  - Long-term: pybreaker or hand-rolled circuit breaker; secondary provider config (SES → SendGrid fallback).

---

### F-17 — Webhook target SSRF (cross-reference, ops impact)
- **category**: 2 + 9
- **location**: `email_service/api.py:51` `webhook_url: str | None = None` — no scheme/host validation; `webhook_url=http://169.254.169.254/...` (cloud metadata) or `http://internal-admin:8080/...` will be POSTed to by the service.
- **production_scenario**: Authenticated caller (or attacker with stolen API_KEY) uses the service as an SSRF proxy. In AWS, IMDSv1 metadata endpoint returns IAM role credentials. With IMDSv2 the impact is reduced but internal RFC1918 reachability is still abused.
- **blast_radius**: IAM role compromise → full cloud account if instance role is overprivileged.
- **severity**: P0 (already known from Code Gate but ops blast-radius is severe)
- **evidence**: No allowlist, no scheme check, no DNS-rebinding-safe resolution in `deliver_webhook`.
- **mitigation**:
  - Immediate: deploy-side — block egress from the service container to RFC1918 / link-local at the network layer (security group / NetworkPolicy).
  - Immediate: enforce IMDSv2 + hop-limit=1 on the host.
  - Long-term: in-app allowlist (`WEBHOOK_ALLOWLIST_HOSTS` env), resolve-then-pin the IP before connecting, reject private IPs.

---

### F-18 — Logs ship PII risk if app reconfigures logging
- **category**: 7 + 8
- **location**: `email_service/logging_config.py` (not read but referenced); `email_service/sender.py:101` uses `hash_recipient(to)`; *but* tracebacks from any unhandled exception inside templates can dump the rendered HTML body (which may contain user data) to stderr.
- **production_scenario**: Template raises during rendering; `logger.exception` emits the formatted traceback including local variables in some configurations (e.g., when `LOG_FORMAT=json` + `python-json-logger` + custom processor that adds `exc_info` with vars).
- **blast_radius**: Inconsistent PII redaction guarantees.
- **severity**: P3
- **evidence**: Exception handlers don't sanitize; relies on logging config discipline.
- **mitigation**: Document log-pipeline review as part of deploy checklist; add a test that asserts no plaintext recipient leaks under `logger.exception`.

---

## Summary

- **ship_recommendation**: BLOCK
- **block_reason**: Three P0s in combination create a high-probability post-deploy outage path:
  1. F-03 (single-worker sync threadpool exhaustion) — service becomes unavailable under any SMTP slowdown.
  2. F-12 (no body-size limit) — single authenticated bad caller can OOM the container.
  3. F-17 (webhook SSRF blast radius) — any API_KEY leak escalates to cloud-account compromise.

  Plus F-09 (irreversible PyPI release with no smoke gate) means a bad fix-forward will burn the version number with no clean recovery path. At minimum, F-09 and F-17 must be mitigated **before** the first `v0.3.0` tag is pushed.

- **watchlist_items** (must be monitored within first 7 days post-deploy, even if shipped):
  1. uvicorn threadpool saturation — alert at >80% of 40 default slots in use for >60s.
  2. SMTP send P99 latency — alert at >5s sustained for 5min (early signal of F-03 cascade).
  3. `email_webhook_failed_total` rate — alert at >1% of `email_send_total`.
  4. `email_send_total{error_code="smtp_auth_failed"}` — any nonzero in 5min = key compromise or rotation needed.
  5. Container restart count — alert at >2 restarts/hour (F-13 crashloop detection).
  6. Log line containing `set_debuglevel` or `AUTH` — must be zero in production logs.
  7. `/metrics` HTTP 200 from any source outside known Prometheus scraper IP — F-06 information disclosure.
  8. Image pull duration during deploy — proxy for F-14 / MTTR.
  9. Pending BackgroundTasks at SIGTERM — instrument and alert (F-07).

- **rollback_plan_completeness**: 2 / 10
  - No documented rollback procedure in README.
  - PyPI release is irreversible (yank only, no delete) — F-09.
  - Docker image rollback not pinned to a tag — `image: email-service:latest` in compose makes "rollback to previous image" non-trivial.
  - No state-migration concerns (stateless), which is the only thing keeping this from 1/10.

- **recommended_runbook_additions**:
  1. "Rolling back a bad PyPI release (yank + 0.3.x+1 hotfix workflow)"
  2. "API_KEY rotation procedure (with caller coordination steps)"
  3. "SMTP provider outage response (circuit-breaker manual toggle, fallback config swap)"
  4. "Deploy SIGTERM drain procedure — confirming BackgroundTasks completed before kill -9"
  5. "Enabling EMAIL_SERVICE_DEBUG safely (dev/stg only, log-pipeline isolation checklist)"
  6. "Image rollback: pinning email-service:vX.Y.Z tags, never :latest"
  7. "Prometheus multiprocess setup for multi-worker deploys"
  8. "Healthcheck false-positive triage (threadpool-saturated /health still returns 200)"
  9. "Webhook delivery debugging — checking BackgroundTasks queue depth"
  10. "Container crashloop diagnosis — log signatures for missing env vars (F-13)"
  11. "Cloud-egress allowlist verification for webhook target IPs (F-17 SSRF mitigation)"
  12. "OpenAPI version drift CI check (F-01)"
