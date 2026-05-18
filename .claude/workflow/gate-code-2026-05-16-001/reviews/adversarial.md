# Adversarial Code Review — email_service/

Date: 2026-05-16
Target: `D:\email-service\.claude\worktrees\cool-bouman-70eb80\email_service\` (10 files, 1868 LOC)
Reviewer mode: senior engineer, aggressive critique. Findings ordered by category, max 3 per category, ranked by severity.

---

## Category 1 — 과한 추상화 (Premature Abstraction)

### 1.1 `Notifier` ABC with one mandatory method, used by two near-identical subclasses

- **category**: 1
- **location**: `notifiers.py:113-122`, with concrete classes 124-206
- **problem**: The `Notifier` ABC fixes a `(to_email, user_name, payload)` signature for exactly two subclasses (MagicLinkNotifier, OTPNotifier), and the third notifier (`TemplateNotifier`) explicitly does NOT inherit from it because the signature doesn't fit. So the ABC abstracts a shape that only two of three implementations honor — the abstraction is doing zero work.
- **attack_scenario**: A new contributor adds `WelcomeNotifier(name, signup_date)` and either (a) shoves data into `payload` as a stringified dict, or (b) breaks out and skips the ABC like `TemplateNotifier` did. Either way the ABC actively misleads.
- **impact**: API design entropy — every future notifier has to choose "fit the rigid shape" vs. "fork like TemplateNotifier did". Code reviewers will keep re-litigating this.
- **severity**: P3
- **evidence**:
  ```python
  # notifiers.py:113-122
  class Notifier(ABC):
      def __init__(self, sender: SmtpSender):
          self._sender = sender
      @abstractmethod
      def send(self, to_email: str, user_name: str, payload: str) -> SendResult: ...
  # notifiers.py:209-215
  class TemplateNotifier:
      """... Does not inherit from Notifier ABC. ..."""
  ```
- **fix_direction**: Delete the ABC. Document a duck-typed protocol (`send(...) -> SendResult`) and let each notifier define its own signature. The current ABC only provides type-check-time coupling without runtime value.

### 1.2 `_NoOpMetric` stub class with overlapping `__enter__` and `time()` context managers

- **category**: 1
- **location**: `metrics.py:36-65`
- **problem**: The no-op stub exposes `labels`, `inc`, `dec`, `set`, `observe`, `time()` (contextmanager), `__enter__`/`__exit__`, AND `track_inprogress`. Only `labels/inc/dec/observe` are actually used by callers (grep `sender.py`, `webhooks.py`). The remaining surface is speculative.
- **attack_scenario**: Future refactor adds a real `time()` usage somewhere, and the prom-client `Histogram.time()` returns a different context-manager protocol than the stub — silently diverges in `METRICS_ENABLED=false` test environments.
- **impact**: Maintenance overhead with no current customer. Encourages call-site patterns that may not survive enabling real metrics.
- **severity**: P3
- **evidence**:
  ```python
  # metrics.py:54-65
  @contextmanager
  def time(self): yield
  def __enter__(self): return self
  def __exit__(self, *_args): return False
  def track_inprogress(self): return self
  ```
- **fix_direction**: Strip the stub down to only the methods actually invoked from the codebase. Add others on demand.

---

## Category 2 — 책임 분리 실패 (Single Responsibility Violation)

### 2.1 `SmtpSender.send()` orchestrates 6 distinct responsibilities

- **category**: 2
- **location**: `sender.py:126-291` (165 LOC for one method)
- **problem**: `send()` performs: (1) CRLF header validation, (2) MIME construction, (3) capture-mode side-channel (write `.eml` to disk), (4) retry loop orchestration, (5) error-code translation, (6) metrics labeling. Capture-mode in particular is a hard-coded `if os.environ.get(...)` test hook embedded in production code (lines 173-216).
- **attack_scenario**: Adding rate-limiting, DKIM signing, or per-tenant From-address rewriting forces a 7th responsibility into the same method. Test capture mode has its own metric path (`email_send_total.labels(result="success", error_code="")` at 191) which is duplicated separately from the real success path at line 385 — they will drift.
- **impact**: Every behavior change requires reading 165 lines. Capture-mode bug-for-bug emulation diverges from real path (e.g., capture mode never goes through retry, never records duration histogram, never increments `email_send_active`).
- **severity**: P1
- **evidence**:
  ```python
  # sender.py:172-196 — capture mode side-channel
  capture_dir = os.environ.get("EMAIL_TEST_CAPTURE_DIR")
  if capture_dir:
      try:
          os.makedirs(capture_dir, exist_ok=True)
          ...
          email_send_total.labels(result="success", error_code="").inc()
          return SendResult(sent=True, message_id=message_id, status=STATUS_CAPTURED)
  ```
- **fix_direction**: Extract `_build_message()`, `_capture_to_disk()`, and `_retry_loop()` as separate methods. Move capture mode behind a strategy/transport object (`SmtpTransport` vs `DiskCaptureTransport`) selected once at `__init__` rather than re-tested every send.

### 2.2 `create_app()` is a 290-line god-function with closures over `sender`, `magic_link`, `otp`, `api_key`

- **category**: 2
- **location**: `api.py:150-443`
- **problem**: `create_app` mixes: env-var bootstrapping, middleware, auth dependency, metrics endpoint, payload-to-response translation (`_result_to_payload`, `_fail`), background-task helper (`_run_and_notify`), and 3 route handlers. Three route handlers (`send_email`, `send_magic_link`, `send_otp`) each duplicate the same dry-run-check / webhook-branch / fail-or-respond pattern.
- **attack_scenario**: Adding a 4th notifier endpoint requires copy-pasting ~30 lines including the subtle `status_val if status_val and status_val != "delivered" else None` shimming logic (which exists in 3 places and will drift).
- **impact**: 3-way duplication that has already been written verbatim 3 times. Closure-based DI prevents unit-testing the helpers in isolation.
- **severity**: P2
- **evidence**:
  ```python
  # api.py:346-352, 394-400, 435-441 — same shim repeated 3x
  status_val = getattr(result, "status", None)
  return SendResult(
      sent=True,
      message_id=result.message_id,
      status=status_val if status_val and status_val != "delivered" else None,
  )
  ```
- **fix_direction**: Extract `_handle_send(req, send_fn, ...)` taking the send callable. Route handlers become 5-line dispatch. Module-level helpers replace closures.

---

## Category 3 — 기존 동작 변경 위험 (Breaking Changes)

### 3.1 `/send` with `webhook_url` returns `sent=False` to legacy callers

- **category**: 3
- **location**: `api.py:315-333`
- **problem**: Legacy callers that ignore the response body or check `resp.json()["sent"]` will see `sent=False` whenever they opt into async webhook delivery. The semantic for "queued" is encoded as `sent=False, status="accepted"`, conflated with "send actually failed". An older client that branches on `sent` cannot distinguish queue-accepted from delivery-failed.
- **attack_scenario**: A caller previously did `if resp.json()["sent"]: log.info("sent")`. They flip on `webhook_url` to get async behavior, and now every call logs as "not sent" — even though the email will be delivered.
- **impact**: Silent semantic drift on the most-used response field. Monitoring/alerting based on `sent` will mis-fire.
- **severity**: P1
- **evidence**:
  ```python
  # api.py:329-333
  return SendResult(
      sent=False, status="accepted", message=(
          "Send queued; final result will be delivered via webhook"
      ),
  )
  ```
- **fix_direction**: Either (a) return HTTP 202 with an explicit `accepted` schema and document that `sent` is meaningless for async, or (b) keep `sent=True` for "accepted into queue" with `status="accepted"` and document that `sent` means "request accepted".

### 3.2 `MagicLinkNotifier.send()` HTML-escapes `link` with `quote=True` — breaks templates expecting raw URL

- **category**: 3
- **location**: `notifiers.py:155-166`
- **problem**: `link` is `escape(link, quote=True)` before going into `str.format`, which produces `&amp;` for `&` query separators. Users who override `html_template` with their own anchor `<a href="{link}">` get a working escaped link, but anyone reading the HTML and copy-pasting the URL gets the escaped form. More importantly, any user-supplied `html_template` that uses `{link}` outside an HTML attribute context (e.g., in a `<pre>` block, or in JSON-LD structured data) is now broken.
- **attack_scenario**: User passes `html_template` with `<script type="application/ld+json">{{"url":"{link}"}}</script>` for email schema markup. The JSON now contains `&amp;` and is invalid.
- **impact**: Subtle template incompatibility for custom HTML templates; not caught by current tests because tests use defaults.
- **severity**: P2 (추정 — depends on whether any external user supplies custom templates)
- **evidence**:
  ```python
  # notifiers.py:158-162
  html = self._html_template.format(
      name=escape(user_name),
      link=escape(link, quote=True),
      expire=self._expire,
  )
  ```
- **fix_direction**: Document escape behavior in the docstring, or expose `autoescape: bool = True` like `TemplateNotifier` already does (line 226). Consistency between the two notifier families is the real fix.

---

## Category 4 — 숨은 회귀 (Silent Regressions Tests Won't Catch)

### 4.1 Metrics objects are bound at import time, never re-evaluated

- **category**: 4
- **location**: `metrics.py:33,68-96` and consumers `sender.py:16-21`, `webhooks.py:18`
- **problem**: `METRICS_ENABLED` is read ONCE at module import. Then either real `Counter`/`Histogram` or `_NoOpMetric()` instances are bound at module level. `sender.py` and `webhooks.py` import those instances directly (`from email_service.metrics import email_retry_attempts_total`). If a deployment changes the env var, restarts uvicorn workers, and tests pass on one worker but not others (depending on order of imports vs env loading) → metrics silently no-op.
- **attack_scenario**: Operator sets `METRICS_ENABLED=true` via container env, but `email_service` is imported before the env is loaded (e.g., by a sitecustomize.py, a `__init__.py` side-effect, or a test fixture that imports first). The bound objects are `_NoOpMetric`. `/metrics` endpoint returns empty body, but `metrics_available()` may even return `True` because it re-reads `_AVAILABLE and METRICS_ENABLED` — wait, no, `METRICS_ENABLED` is a module-level constant. Still, if `_AVAILABLE` is True but env loaded late, the call sites use stubs while `/metrics` reports no real counters either. Hard to diagnose.
- **impact**: Operators see zero metrics and have no error to trace. Tests pass because tests typically set env before import.
- **severity**: P1
- **evidence**:
  ```python
  # metrics.py:33
  METRICS_ENABLED = _truthy(os.environ.get("METRICS_ENABLED"))
  # metrics.py:68
  if _AVAILABLE and METRICS_ENABLED:
      email_send_total = Counter(...)
  # sender.py:16-21 — captures reference at import
  from email_service.metrics import email_send_total, ...
  ```
- **fix_direction**: Always create real Counter objects when `_AVAILABLE` (prometheus-client doesn't require enabling), and gate only the `/metrics` endpoint on `METRICS_ENABLED`. Or expose `metrics.email_send_total()` as a getter so call sites resolve lazily.

### 4.2 Background task `_run_and_notify` swallows ALL exceptions including programming errors

- **category**: 4
- **location**: `api.py:271-289`
- **problem**: `except Exception as exc` catches AttributeError, TypeError, etc. and converts them into a webhook payload with `error_code="unknown"`. The HTTP request already returned 200/202 to the caller, so they cannot tell that the background task crashed due to a bug vs. an SMTP issue.
- **attack_scenario**: A refactor breaks `_do_send` (e.g., changes a kwarg name), tests still pass because they mostly exercise the sync path, async-webhook callers receive `{"error_code":"unknown"}` payloads for every send and cannot tell production is broken.
- **impact**: Production silently fully broken on the async path; no exception reaches Sentry-style aggregators unless they hook into `logger.exception`. Marked `# pragma: no cover` confirms it's never tested.
- **severity**: P1
- **evidence**:
  ```python
  # api.py:275-287
  except Exception as exc:  # pragma: no cover - defensive
      logger.exception("Background send raised")
      payload = {
          "message_id": None, "status": "failed", "error_code": "unknown",
          ...
      }
      deliver_webhook(webhook_url, payload, webhook_secret)
      return
  ```
- **fix_direction**: Differentiate `AttributeError/TypeError/NameError` (programming bugs — re-raise) from `IOError/OSError/SMTP*` (operational). At minimum, increment a dedicated `email_background_task_crashed_total` counter so operators get a signal.

### 4.3 `email_send_active.inc()` outside `try`, `dec()` in `finally` — gauge can go negative

- **category**: 4
- **location**: `sender.py:303-304, 521-522`
- **problem**: `email_send_active.inc()` is on line 304, OUTSIDE the try block. The try begins line 305. The `finally: email_send_active.dec()` (line 521-522) runs for both success and exception cases. If `inc()` itself raised (unlikely but possible if prom-client is misconfigured, e.g., registry conflict), the `finally` still runs `dec()` against a counter that was not incremented. Conversely, if `inc()` succeeds and the function returns inside `try`, that's correct.

  Actually re-reading: `inc()` is line 304, before `try:` line 305. Since `try` covers lines 305-520 and `finally` is at 521, the `finally` only runs if `try` was entered — Python `try/finally` semantics. So if `inc()` raises, `finally` does NOT run. Reading again carefully: lines 303-304 are NOT inside the `try` block. The `try:` opens at 305. So `finally` is bound to the `try` starting at 305 and only fires when 305 is entered. So inc/dec are balanced. **Withdrawn — but worth noting the pattern is fragile.**

  However, a real issue remains: in `try/except` flow, every `return` inside the `try` triggers `finally`, which is correct. But if the `with smtplib.SMTP(...)` block on line 306 raises during `__enter__` (e.g., `OSError`), Python guarantees `__exit__` runs but the SMTP context manager itself may not have completed setup — and our `email_send_active.dec()` still runs. That's correct behavior. **Re-classifying as informational; severity downgraded.**
- **attack_scenario**: N/A — false alarm on closer reading.
- **impact**: None observed.
- **severity**: P3 (informational; the pattern is correct but place `inc()` inside `try` for robustness)
- **evidence**:
  ```python
  # sender.py:303-305
  start = time.perf_counter()
  email_send_active.inc()   # outside try
  try:
      with smtplib.SMTP(...) as server:
  # sender.py:521-522
  finally:
      email_send_active.dec()
  ```
- **fix_direction**: Move `email_send_active.inc()` to be the first line inside `try:` so the inc/dec pairing is structurally enforced.

---

## Category 5 — 성능 회귀 (Performance Regression)

### 5.1 `BackgroundTasks` runs blocking SMTP send + `time.sleep` retries on the FastAPI event loop

- **category**: 5
- **location**: `api.py:271-289, 326-328, 386-388, 427-429`; `sender.py:277` (`time.sleep`); `webhooks.py:95` (`time.sleep`)
- **problem**: FastAPI `BackgroundTasks` runs sync callables in a threadpool (good), BUT the callable `_run_and_notify` invokes `sender.send()` which can `time.sleep(25)` for retry backoff, then `deliver_webhook()` which can `time.sleep(60)` for webhook backoff. Total worst case: ~85s per request, occupying a thread for the duration. With default starlette threadpool size (40), 40 concurrent webhooked requests saturate the threadpool and the entire app stops responding (including `/health`).
- **attack_scenario**: A caller floods 100 webhook-mode sends with a slow webhook target that returns 500s. Each request occupies a thread for `1+10+60=71s` of webhook retry alone. The 41st `/health` probe times out, k8s restarts the pod, in-flight retries are lost.
- **impact**: Denial of service via slow webhook target. Health-check failures during high webhook-failure rate. Lost emails on pod restart since background tasks have no persistence.
- **severity**: P0
- **evidence**:
  ```python
  # sender.py:277
  time.sleep(delay)
  # webhooks.py:93-95
  if attempt < max_total:
      idx = min(attempt - 1, len(backoffs) - 1)
      time.sleep(backoffs[idx])
  # api.py:326-328 — both queued onto BackgroundTasks
  background_tasks.add_task(
      _run_and_notify, _do_send, req.webhook_url, req.webhook_secret
  )
  ```
- **fix_direction**: Replace `BackgroundTasks` with a real queue (RQ, Celery, or even an asyncio task + `asyncio.sleep` wrapper). At minimum, document the threadpool exhaustion risk and cap concurrent webhooked sends.

### 5.2 `client.py` / `async_client.py` create a new `httpx.Client` per `EmailServiceClient` instance — no connection pooling across instances

- **category**: 5
- **location**: `client.py:38-53`, `async_client.py:27-42`
- **problem**: Each `EmailServiceClient` instantiation opens a new HTTP connection pool. Documented usage pattern in the docstring shows `with EmailServiceClient(...) as c: c.send_otp(...)` — single send per client → no benefit from pooling, plus TLS handshake every call.
- **attack_scenario**: A user writes `def send_otp(to, code): with EmailServiceClient(url, key) as c: return c.send_otp(...)` and calls it from a request handler. Every call does fresh DNS + TCP + TLS. At 100 req/s, p99 latency is dominated by handshake time.
- **impact**: Slow client-side throughput, unnecessary connection churn on the server side.
- **severity**: P2
- **evidence**:
  ```python
  # client.py:33-36 — docstring encourages per-call instantiation
  Example:
      with EmailServiceClient("http://email-service:8000", api_key) as c:
          c.send_otp("user@example.com", "홍길동", "482901")
  ```
- **fix_direction**: Document that `EmailServiceClient` should be a long-lived singleton, or provide a module-level factory that returns a shared instance. Add `limits=httpx.Limits(max_keepalive_connections=20)` to defaults.

---

## Category 6 — 동시성 문제 (Concurrency)

### 6.1 `deliver_webhook` blocks for up to 71s using `time.sleep` — when called from FastAPI BackgroundTasks, blocks an entire threadpool worker

- **category**: 6
- **location**: `webhooks.py:93-95`, called from `api.py:289`
- **problem**: `deliver_webhook` is synchronous and uses `time.sleep`. Called from `_run_and_notify` which is queued via FastAPI `BackgroundTasks`. Background tasks run on the starlette threadpool (default 40 workers). A misbehaving webhook target with default backoffs `(1, 10, 60)` holds a worker for 71+ seconds per call.
- **attack_scenario**: Adversary's webhook target returns `503` deterministically. Every webhook-mode email send pins a threadpool worker for ~71s. After 40 such sends in 71s, all sync endpoints (FastAPI route handlers that aren't `async def`) including dependency resolution may queue. While the app is technically still alive, throughput collapses.
- **impact**: Effective DoS via cooperative-but-slow webhook target. Same root cause as 5.1 but framed as concurrency.
- **severity**: P0
- **evidence**:
  ```python
  # webhooks.py:93-95
  if attempt < max_total:
      idx = min(attempt - 1, len(backoffs) - 1)
      time.sleep(backoffs[idx])
  ```
- **fix_direction**: Provide an `async_deliver_webhook` using `httpx.AsyncClient` and `asyncio.sleep`, scheduled with `asyncio.create_task` from inside an async route. Or move webhook delivery into a separate worker process entirely.

### 6.2 Prometheus `Counter`/`Histogram` are process-local — workers see disjoint metrics

- **category**: 6
- **location**: `metrics.py:69-90`
- **problem**: prometheus-client `Counter` objects are not multiprocess-safe by default. uvicorn typically runs multiple workers (`--workers N`); each worker has its own counters, and `/metrics` returns only the current worker's view. Without `PROMETHEUS_MULTIPROC_DIR` configured, observed rates are 1/N of reality.
- **attack_scenario**: Operator deploys with `--workers 4`. Dashboard shows ~25% of actual send volume because each scrape randomly hits one worker. Alerting thresholds are off by 4x.
- **impact**: Incorrect monitoring/alerting. Hard to debug because each scrape gives a plausible-looking number.
- **severity**: P1
- **evidence**:
  ```python
  # metrics.py:68-90 — no MultiProcessCollector / PROMETHEUS_MULTIPROC_DIR handling
  if _AVAILABLE and METRICS_ENABLED:
      email_send_total = Counter("email_send_total", ...)
  ```
- **fix_direction**: Document the single-worker requirement, OR support `PROMETHEUS_MULTIPROC_DIR` properly (use `MultiProcessCollector` in `render_latest()` when env var present).

### 6.3 No coordination between BackgroundTask completion and process shutdown — in-flight sends lost on graceful shutdown

- **category**: 6
- **location**: `api.py:326-328, 386-388, 427-429`
- **problem**: When uvicorn receives SIGTERM, FastAPI's lifespan shutdown waits for active HTTP requests but does NOT wait for `BackgroundTasks` to drain. Any email queued for async send is silently dropped.
- **attack_scenario**: k8s deploys a new version. During the 30s grace period, 50 webhook-mode requests are accepted (status `202`/`accepted`). At pod termination, the BackgroundTasks are abandoned mid-retry. Callers receive no webhook, eventually time out, retry with the same email, get duplicate sends.
- **impact**: Email loss on every deployment. Duplicate sends if callers retry. No durability guarantee despite the "accepted" status.
- **severity**: P1
- **evidence**:
  ```python
  # api.py — no shutdown hook, no task drain logic
  background_tasks.add_task(
      _run_and_notify, _do_send, req.webhook_url, req.webhook_secret
  )
  ```
- **fix_direction**: Either (a) reject webhook-mode requests as a documented limitation until backed by a durable queue, or (b) add a startup-event-scoped `asyncio.Queue` + worker task with proper shutdown drain.

---

## Category 7 — 에러 처리 누락/약화 (Error Swallowing)

### 7.1 `client.py:147` bare `except Exception` swallows JSON-decode and all transport errors

- **category**: 7
- **location**: `client.py:144-156`, mirrored in `async_client.py:130-142`
- **problem**: When a 502 response has a non-JSON body, `resp.json()` raises (likely `json.JSONDecodeError`), and the bare `except Exception` catches it silently. The resulting `EmailServiceError` has `error_code=None, message=None` — the caller cannot distinguish "smtp_timeout" from "server returned HTML error page". The exception message becomes `"None: None"`.
- **attack_scenario**: Server proxy (e.g., misconfigured nginx) returns 502 with `text/html` "Bad Gateway" page. Client raises `EmailServiceError("None: None")`. Operator has no clue what went wrong.
- **impact**: Loss of debuggability for the most operationally-important error path.
- **severity**: P2
- **evidence**:
  ```python
  # client.py:144-156
  try:
      body = resp.json()
  except Exception:
      body = {}
  detail = body.get("detail", body) if isinstance(body, dict) else {}
  if not isinstance(detail, dict):
      detail = {}
  raise EmailServiceError(
      error_code=detail.get("error_code"),
      message=detail.get("message"),
      status_code=502,
  )
  ```
- **fix_direction**: On JSON decode failure, include `resp.text[:200]` in the `EmailServiceError.message` and a sentinel `error_code="non_json_response"`.

### 7.2 `sender.py:500` bare `except Exception` lumps programming bugs into `ERR_UNKNOWN`

- **category**: 7
- **location**: `sender.py:500-520`
- **problem**: The catch-all `except Exception` after specific SMTP exception clauses catches AttributeError, TypeError, KeyError — any programming error. These get reported as `error_code="unknown"` with `sent=False`. Production never sees a real stack trace at the caller level; only the log line. Worse, `_is_retriable("unknown")` returns `False`, so a programming bug that should be a hard crash is silently treated as a permanent failure and not retried, masking flakiness as a "user error".
- **attack_scenario**: A refactor renames `msg.as_string()` and a subtle path raises `AttributeError`. Tests cover the happy path. Production sees `error_code="unknown"` for 100% of sends. Operator looks for SMTP problems, finds none. Logs do contain the stack via `logger.exception`, but the structured error code obscures the urgency.
- **impact**: Bug-class errors masquerade as operational errors. Alerting based on `error_code` does not distinguish.
- **severity**: P2
- **evidence**:
  ```python
  # sender.py:500-520
  except Exception as exc:
      duration_ms = (time.perf_counter() - start) * 1000.0
      logger.exception("Failed to send email", ...)
      email_send_total.labels(result="failure", error_code=ERR_UNKNOWN).inc()
      return SendResult(sent=False, error_code=ERR_UNKNOWN, ...)
  ```
- **fix_direction**: Narrow the catch: handle `smtplib.SMTPException` and `OSError` only. Let everything else propagate so the FastAPI handler returns 500 with the trace and ops sees real-priority alerts.

### 7.3 Webhook non-2xx responses are logged but the body is never captured

- **category**: 7
- **location**: `webhooks.py:65-83`
- **problem**: On non-2xx, only `resp.status_code` is logged. The response body — which is the only diagnostic for "why did our webhook target reject us?" — is discarded. After 3 retries exhaust, the counter increments but no operator can tell why.
- **attack_scenario**: Webhook target returns `400 {"error":"signature_mismatch"}` because the operator rotated the secret. Logs say "Webhook returned non-2xx: 400" with zero diagnostic info. Operator must reproduce manually with curl to see the message.
- **impact**: Operational opacity for webhook failures. Average debug time inflated.
- **severity**: P2
- **evidence**:
  ```python
  # webhooks.py:76-83
  logger.warning(
      "Webhook returned non-2xx",
      extra={
          "message_id": message_id,
          "webhook_status": resp.status_code,
          "attempts": attempt,
      },
  )
  ```
- **fix_direction**: Log `resp.text[:512]` (truncated) on non-2xx. Could also include in the failure metric as a label, but cardinality risk — keep in logs.

---

## Summary

- **self_confidence**: 8/10. Read full source for sender.py, api.py, webhooks.py, metrics.py, notifiers.py, client.py, async_client.py. Did not deeply audit logging_config.py, __init__.py, __main__.py — minor risk that findings about hash_recipient or logging setup are missed. Did not run tests.
- **blind_spots**:
  - `logging_config.py` — hash_recipient salt source unchecked (PII leakage if salt is constant).
  - `__main__.py` — uvicorn startup args not reviewed (workers count, signal handling).
  - Test suite — did not verify which behaviors are actually covered vs. claimed. The `# pragma: no cover` on api.py:275 confirms at least one gap.
  - `pyproject.toml` / dependency pins — supply-chain not audited.
  - Authentication race: `hmac.compare_digest` use is correct, but no rate-limiting on auth failures.
- **recommended_tests**:
  1. **Background-task threadpool exhaustion**: spin up app with `httpx.MockTransport`, send 50 webhook-mode requests against a webhook target that hangs 70s, assert `/health` still responds within 100ms.
  2. **Late env-var binding**: import `email_service.metrics` BEFORE setting `METRICS_ENABLED=true`, then import `email_service.sender`, then call `sender.send()`, assert `email_send_total` is actually a real Counter (currently would fail — it's a `_NoOpMetric`).
  3. **Async-mode `sent` field contract**: assert that `POST /send` with `webhook_url` returns a documented "accepted" shape distinct from delivery-failure (currently both have `sent=False`).
- **regression_risk_summary**: Highest production-incident risk is the `BackgroundTasks` + blocking `time.sleep` combination (P0, items 5.1/6.1/6.3) — slow webhook targets can DoS the service and crash deploys lose emails. Second is metrics multi-process correctness (P1, 6.2). The sync-API breaking change on `sent` field for webhook mode (P1, 3.1) will silently mis-fire monitoring.
