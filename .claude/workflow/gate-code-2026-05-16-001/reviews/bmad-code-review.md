# BMAD Architectural Code Review — email-service

**Date:** 2026-05-16
**Scope:** `email_service/` package, 10 files, 1868 LOC
**Focus:** Architectural soundness — module boundaries, separation of concerns, abstraction quality, testability, maintainability

---

## Executive Summary

This is a **well-factored small library** with mostly clean module boundaries. The architecture is healthy enough to extend, but suffers from three structural problems that compound as the codebase grows:

1. **`SmtpSender.send` is a god-method** mixing validation, framing, capture mode, retry loop, metrics, and logging in one ~170-line block.
2. **`api.py` is doing too much** — env-var loading, DI wiring, request models, route definitions, background-task plumbing, and webhook payload shaping all live in one file.
3. **Sync/async client duplication is verbatim** — every payload shape and 502-translation branch exists twice with zero shared core.

No critical layering violations, no circular dependencies, no hidden state. Public API surface is appropriately minimal. Error codes are well-structured as string constants (though not as an exception hierarchy).

---

## Findings

### F1. `SmtpSender.send` is a god-method
- **file:line:** `email_service/sender.py:126-291`
- **severity:** P1
- **architectural issue:** A single ~170-line method performs CRLF validation, MIME assembly, EMAIL_TEST_CAPTURE_DIR side-channel, retry orchestration, per-attempt result rewriting (lines 238-247, 250-259, 280-288 each manually copy fields onto a new `SendResult` because `attempts` needs adjustment), metric emission, and structured logging. The "rewrite the dataclass to fix one field" pattern repeats 3x and signals a missing abstraction (`SendResult.with_attempts(n)` or a mutable builder).
- **smell category:** god-class / missing-abstraction
- **fix direction:** Extract (a) `_build_message()` returning `MIMEMultipart`, (b) `_validate_headers()` returning early `SendResult | None`, (c) `_capture_to_disk()` as a separate strategy, (d) keep retry loop in `send()` calling a pure `_send_once()`. Give `SendResult` a `replace(attempts=...)` helper (it's `frozen=True`, so use `dataclasses.replace`).

### F2. Capture-mode is a hidden side channel inside the sender
- **file:line:** `email_service/sender.py:172-216`
- **severity:** P2
- **architectural issue:** `EMAIL_TEST_CAPTURE_DIR` reading is buried inside `send()`. This is an **environment variable read from a library class that takes its config via `SmtpConfig`** — a leaky abstraction. Tests that don't set the var get real SMTP behavior; tests that set it get filesystem behavior. The branching belongs in a `Transport` interface (`SmtpTransport`, `FileCaptureTransport`, `NullTransport`).
- **smell category:** leaky-abstraction / hidden-coupling
- **fix direction:** Introduce a `Transport` protocol with `deliver(msg, recipients) -> TransportResult`. Inject via `SmtpSender(config, transport=...)`. Keep env-var resolution at the construction boundary (`api.py` / `__main__.py`), not inside the send path.

### F3. `api.py` mixes 5 unrelated responsibilities
- **file:line:** `email_service/api.py:1-443`
- **severity:** P1
- **architectural issue:** This single 443-line file owns: (1) env-var resolution + CRLF guard (`_build_sender_from_env`, `_required_env`, `_no_crlf`), (2) Pydantic request/response models, (3) dry-run helpers, (4) FastAPI app factory and DI wiring, (5) route handlers, (6) background-task webhook plumbing (`_run_and_notify`, `_result_to_payload`). When the project adds a 4th endpoint, this file crosses 600 LOC.
- **smell category:** god-class / shotgun-surgery (adding an endpoint touches schemas, helpers, route, and background plumbing all here)
- **fix direction:** Split into `api/schemas.py` (Pydantic models), `api/config.py` (env→SmtpConfig + DI), `api/routes.py` (handlers), `api/background.py` (`_run_and_notify`, `_result_to_payload`). Keep `api/__init__.py` as the assembly point with `create_app()`.

### F4. Background webhook plumbing duplicates response shaping inline
- **file:line:** `email_service/api.py:271-289` and `api.py:260-269`
- **severity:** P2
- **architectural issue:** `_result_to_payload` produces a dict-shape that is **the webhook contract** but is defined as an inner helper of `create_app`. The shape (`message_id`, `status`, `error_code`, `refused`, `sent_at`, `attempts`) is duplicated structurally in the synchronous response path (lines 343-352, 390-400, 431-440). The webhook payload schema has no formal definition — it's implicit in dict construction. Webhook receivers cannot generate clients from OpenAPI.
- **smell category:** anemic-domain / missing-abstraction
- **fix direction:** Promote to a `WebhookPayload` Pydantic model in `schemas.py`. Build it once via `WebhookPayload.from_send_result(result, message_id)`. Use it for both sync responses and async webhook bodies.

### F5. Sync/async client code is duplicated verbatim
- **file:line:** `email_service/client.py:69-135` vs `email_service/async_client.py:58-122`
- **severity:** P1
- **architectural issue:** `send()`, `send_magic_link()`, `send_otp()`, and `_post()` are duplicated word-for-word between the two clients. Only `await` and `httpx.AsyncClient` differ. Every new endpoint or field requires changing both files (shotgun-surgery). The 502→`EmailServiceError` translation block (`_post` body) is duplicated. Payload-building logic ("if not None, add to dict") is duplicated 6x.
- **smell category:** shotgun-surgery / missing-abstraction
- **fix direction:** Extract a `_build_send_payload(...)`, `_build_magic_link_payload(...)`, `_build_otp_payload(...)` set of pure functions in a `_payloads.py` module. Extract `_parse_502(resp) -> EmailServiceError | None` as a pure function. Sync and async `_post` then become 4-line shells. Optionally generate one from the other via a shared base + transport, but the pure-function extraction alone removes ~70% of the duplication.

### F6. No typed exception hierarchy for the library layer
- **file:line:** `email_service/sender.py:27-35` (error codes as strings) and `client.py:14-27` (single `EmailServiceError`)
- **severity:** P2
- **architectural issue:** Errors travel as **string error codes inside a `SendResult`** rather than as a typed exception hierarchy. This is a deliberate design (callers branch on `error_code`), but it means: (a) static type checkers cannot enforce exhaustive handling, (b) the `client.EmailServiceError` collapses 8 distinct server-side conditions into one client-side exception, (c) there is no `EmailServiceError` subclass per failure mode (e.g. `SmtpAuthFailedError`, `SmtpTimeoutError`). Callers wanting to "retry on timeout, alert on auth" must `if err.error_code == "smtp_timeout"`.
- **smell category:** primitive-obsession / anemic-domain
- **fix direction:** Either (a) keep the current `SendResult` model but add a typed `enum` for error codes (currently strings — typo-prone), or (b) introduce a small client-side hierarchy: `EmailServiceError` → `TransientSmtpError`, `AuthError`, `RecipientRefusedError`, etc. Map `error_code` → exception class in one place.

### F7. `__main__.py` reaches into `api.py` private function
- **file:line:** `email_service/__main__.py:37` (`from email_service.api import _build_sender_from_env`)
- **severity:** P2
- **architectural issue:** The CLI imports a **leading-underscore private** function from `api.py`. The `_build_sender_from_env` belongs in a config module (see F3) where both CLI and API can depend on it without the underscore-violation. This is a broken-layering signal: the CLI conceptually sits **above** the HTTP layer but is dipping into HTTP-layer internals to get sender construction.
- **smell category:** broken-layering / leaky-abstraction
- **fix direction:** Move `_build_sender_from_env` to `email_service/config.py` (or `email_service/_config.py`) and have both `api.py` and `__main__.py` import it as a public function `build_sender_from_env`.

### F8. Configuration sources are scattered across 5 modules
- **file:line:**
  - `api.py:131-147` (SMTP_HOST/PORT/USER/PASSWORD/FROM/USE_TLS)
  - `api.py:202` (METRICS_REQUIRE_AUTH)
  - `sender.py:44-48` (EMAIL_SERVICE_DEBUG)
  - `sender.py:173` (EMAIL_TEST_CAPTURE_DIR)
  - `metrics.py:33` (METRICS_ENABLED)
  - `logging_config.py:15` (EMAIL_SERVICE_LOG_FORMAT)
  - `__main__.py:30-31` (HOST, PORT)
- **severity:** P2
- **architectural issue:** No single source of truth for the env-var contract. Each module reads its own `os.environ.get(...)` ad hoc with inconsistent truthy parsing (`_truthy` is redefined in `api.py` and `metrics.py`; `_debug_enabled` is a third copy). Onboarding a new env var requires deciding which file owns it; there is no test that enumerates all env vars. A typo (`SMPT_HOST`) fails silently for optional vars.
- **smell category:** shotgun-surgery / primitive-obsession
- **fix direction:** Create `email_service/config.py` exposing a single `Settings` dataclass (or pydantic `BaseSettings`) that reads all env vars in one place. Inject it into `SmtpSender`, `create_app`, `configure_logging`. Keeps env reads at the edge; library code becomes pure-input. Centralize `_truthy` there.

### F9. `notifiers.py` mixes templates, escaping, and dispatch
- **file:line:** `email_service/notifiers.py:9-106` (HTML/text template constants) vs `113-238` (notifier classes)
- **severity:** P3
- **architectural issue:** Hard-coded Korean HTML templates live as module-level string constants in the same file as the abstract `Notifier` class. The templates are presentation; the class is dispatch. They mix in one file. The class supports override via `html_template=`, so the bundled templates are essentially default presets — they belong in `email_service/templates/` (one per file, easier i18n).
- **smell category:** missing-abstraction (presentation vs dispatch)
- **fix direction:** Move templates to `email_service/templates/magic_link.html`, `magic_link.txt`, `otp.html`, `otp.txt`, loaded via `importlib.resources`. Keeps `notifiers.py` focused on the notifier protocol.

### F10. `TemplateNotifier` does not inherit from `Notifier` ABC
- **file:line:** `email_service/notifiers.py:209-238`
- **severity:** P3
- **architectural issue:** The docstring openly says "Does not inherit from Notifier ABC". This is honest, but signals that **the `Notifier` ABC was the wrong abstraction** — it forces the `(to, user_name, payload)` signature, which doesn't generalize. The ABC abstracts over 2 concrete classes that share 90% of their structure (subject/template/expire fields, `.send()` formatting), while the more general `TemplateNotifier` had to bail out.
- **smell category:** premature-abstraction
- **fix direction:** Either (a) delete the `Notifier` ABC and let the three notifiers be duck-typed (Python idiom), or (b) make `Notifier` a `Protocol` with just `send(to_email: str, **kwargs) -> SendResult` so `TemplateNotifier` conforms naturally.

### F11. `SendResult` has no `__bool__` symmetry with status field
- **file:line:** `email_service/sender.py:51-67`
- **severity:** P3
- **architectural issue:** `SendResult.status` is a string (`"delivered"`, `"failed"`, `"partial"`, `"captured"`) — primitive obsession. There's a discrepancy: `sent=True` with `status="captured"` (capture mode) is fine, but `sent=False` with `status="partial"` is semantically odd (some recipients succeeded). Callers reading `result.sent` for partial-success scenarios get the wrong answer.
- **smell category:** primitive-obsession
- **fix direction:** Promote `status` to an `Enum` (`SendStatus.DELIVERED | FAILED | PARTIAL | CAPTURED`). Clarify the `sent` vs `status` contract in the docstring: `sent` = "all recipients accepted", `status` = "outcome category".

### F12. Webhook payload contract is implicit
- **file:line:** `email_service/api.py:260-289` vs `email_service/webhooks.py` (no schema)
- **severity:** P2
- **architectural issue:** `webhooks.py` accepts `payload: dict[str, Any]` and signs/sends it. The payload structure is defined inline in `api.py:_result_to_payload`. There is **no place a webhook consumer can look** to learn the schema. Compare to OpenAPI for sync responses, which is fully typed.
- **smell category:** missing-abstraction
- **fix direction:** Pair with F4. Define `WebhookPayload(BaseModel)` in `schemas.py`. Make `deliver_webhook(url, payload: WebhookPayload, ...)` typed. Auto-generate webhook schema docs from the model.

### F13. `api.py` background task swallows exceptions silently
- **file:line:** `email_service/api.py:275` (`except Exception as exc:  # pragma: no cover - defensive`)
- **severity:** P2 (architectural, not just a code smell)
- **architectural issue:** The `# pragma: no cover` on a broad `except Exception` is an admission that this path is **untested but load-bearing for production reliability**. A failure here only emits a log + a "failed" webhook; if the webhook itself fails, the caller has no way to learn the result. There is no dead-letter queue, no in-memory tracking of in-flight background tasks. For an async-by-webhook system, this is the critical reliability seam, and it has no observable seam for tests.
- **smell category:** hidden-coupling (failure mode coupled to log infrastructure)
- **fix direction:** Extract `_run_and_notify` to a class `WebhookDispatcher` with testable seams. Add a metric `email_background_send_exceptions_total`. Consider returning a 202-with-receipt-id so callers can poll if the webhook never arrives. At minimum, remove the `pragma: no cover` and write the test.

### F14. `SmtpSender.send` accepts `Sequence` shapes inconsistently
- **file:line:** `email_service/sender.py:137` (`*(cc or ()), *(bcc or ())`)
- **severity:** P3
- **architectural issue:** The signature says `cc: list[str] | None` but the code spreads it as a tuple. Minor, but typical of primitive-obsession around recipient lists. A `Recipients` value object (`to`, `cc`, `bcc`, with validation) would centralize CRLF checking, deduplication, and the "all addresses" concatenation that appears at line 218.
- **smell category:** primitive-obsession
- **fix direction:** Optional refactor. `@dataclass(frozen=True) class Recipients` with `.all() -> list[str]` and `.validate_headers() -> SendResult | None`.

### F15. Public surface is correctly minimal — positive note
- **file:line:** `email_service/__init__.py:1-5`
- **severity:** N/A (commendation)
- **architectural observation:** `__all__` exports only `SmtpSender`, `MagicLinkNotifier`, `OTPNotifier`, `TemplateNotifier`. `SendResult`, `SmtpConfig`, `EmailServiceClient` are reachable via submodule import but not re-exported — this is the right call (they're either supporting types or have separate import lines documented). Keep this discipline as the package grows.

### F16. Dependency direction is clean — positive note
- **architectural observation:** Library code (`sender.py`, `notifiers.py`, `logging_config.py`, `metrics.py`) does not import from HTTP code (`api.py`, `webhooks.py`, `client.py`, `async_client.py`). The HTTP layer depends down into the library; the library never reaches up. This is exactly right.

### F17. `metrics.py` no-op pattern is well done — positive note
- **file:line:** `email_service/metrics.py:36-66`
- **architectural observation:** The `_NoOpMetric` stub that mirrors the prometheus_client API lets call sites stay free of `if metrics_enabled:` branches. Clean, idiomatic, testable.

---

## Categorical Assessment

| Category | Grade | Notes |
|---|---|---|
| Module cohesion | C+ | `sender.py` and `api.py` are doing too much; others are focused. |
| Layering | A- | Library/HTTP separation is clean; `__main__` reaches into `api._build_sender_from_env` (F7). |
| Configuration handling | C | Env reads scattered across 7 sites with redundant `_truthy` helpers (F8). |
| Error type hierarchy | C | Error codes are stringly-typed constants, not enums; client has only one exception class (F6). |
| Testability | B- | Pure `SmtpConfig` and notifier construction is testable; capture-mode-via-env undermines clean DI (F2); background task is untested (F13). |
| Public API surface | A | `__init__.py` is appropriately minimal (F15). |
| Sync/async duplication | D | Verbatim duplication, every endpoint change touches both files (F5). |
| Dependency direction | A | Library never imports HTTP layer (F16). |

---

## Overall Grade: **B−**

The codebase is **structurally healthy enough to extend safely today**, but three accumulating debts (sender god-method, api.py overload, sync/async duplication) will turn each new endpoint into a 4-file change. Address F1, F3, F5 before adding a 4th endpoint or the 2nd notifier type.

---

## Top 5 Structural Issues

1. **Sync/async client verbatim duplication** — `email_service/client.py:69-158` vs `email_service/async_client.py:58-143`. Every endpoint addition is a 2-file shotgun edit. (F5, P1)
2. **`SmtpSender.send` god-method** — `email_service/sender.py:126-291`. ~170 lines mixing 6 concerns; capture-mode buried inside (F1+F2, P1).
3. **`api.py` mixes 5 responsibilities** — `email_service/api.py:1-443`. Schemas, env loading, DI, routes, and background plumbing in one file (F3, P1).
4. **Configuration scattered across 7 modules** — `api.py:131-147`, `api.py:202`, `sender.py:44-48,173`, `metrics.py:33`, `logging_config.py:15`, `__main__.py:30-31`. No `Settings` aggregate (F8, P2).
5. **Webhook payload contract is implicit** — `email_service/api.py:260-289` defines the wire format inline; `webhooks.py` takes `dict[str, Any]`. Consumers have nothing to import (F4+F12, P2).
