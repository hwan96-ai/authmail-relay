# Design Review — email-service

Scope: two design surfaces only.
- **A.** Outbound HTML emails — `email_service/notifiers.py` (MagicLink, OTP, Template)
- **B.** FastAPI Swagger UI at `/docs` — `email_service/api.py` (auto-generated from operation metadata)

No DESIGN.md exists. This is a backend service; design surface is intentionally narrow.

## Initial overall score: **4.8 / 10**

Functional but missing the basics for production-quality email rendering and API docs. The biggest gaps are WCAG contrast on fine-print, no responsive container, no dark mode, hardcoded Korean copy, and zero Swagger operation metadata (no summaries, tags, response schemas, or examples).

---

## Surface A — HTML Emails

| Dimension | Score | Evidence | What 10 looks like |
|---|---|---|---|
| Typography | 4 | `notifiers.py:10,29` — only `font-family:sans-serif` | Full system stack: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`. Set `line-height:1.5`, base `font-size:16px`. |
| Hierarchy | 6 | `notifiers.py:11-22` h2 → p → CTA → fine-print, single rhythm | Consistent vertical spacing scale (8/16/24/32px). h2 has explicit `margin:0 0 16px`. CTA block has breathing room above and below. |
| Color (contrast) | 3 | `notifiers.py:22` `#888` on white = **3.54:1** — fails WCAG AA (4.5:1 for body text) | `#666` (5.74:1) or `#595959` (7:1). Body `#333` is fine (12.6:1). CTA `#1a73e8` on white = 4.56:1 — passes AA at 14px+. |
| Interaction states | N/A | Static email | — |
| Accessibility | 3 | No `lang` attr on `<html>`, no `role`, no `aria-label`, no preheader, no plain-text alternative passed by these notifiers | `<html lang="ko">`, `<a role="link" aria-label="비밀번호 설정하기">`, hidden preheader `<div style="display:none">` for inbox preview, plain-text body via `text_body=` |
| Responsive | 2 | `notifiers.py:10` no `max-width`, no viewport meta, no media query | 600px centered container, `<meta name="viewport">`, CTA `display:block` on `max-width:480px` |
| Dark mode | 0 | No `prefers-color-scheme` | `@media (prefers-color-scheme: dark)` overrides body to dark surface (`#1a1a1a`), text to `#e8e8e8`, keep CTA distinguishable |
| Locale (i18n) | 2 | `notifiers.py:11,19,23,30,32,36` — Korean hardcoded in template constants. `subject_prefix` is the only hook. | Template strings injectable per-instance (constructor kwarg) or i18n catalog. Subject + body + CTA label all overridable. |
| Email client compat | 3 | `notifiers.py:16-20` CSS-only rounded button, no Outlook VML, no table-based layout | Outlook-conditional VML `<v:roundrect>` fallback, table-based layout for Outlook 2007-2019, MSO-safe inline styles |

**Surface A average: 2.9/10** (excluding N/A)

---

## Surface B — Swagger UI at `/docs`

| Dimension | Score | Evidence | What 10 looks like |
|---|---|---|---|
| Operation summaries | 2 | `api.py:142,166,188` — `@app.post("/send", ...)` lacks `summary=`/`description=`. Function docstrings absent. | `summary="Send raw email"`, `description=` with usage notes, `X-Dry-Run` header documented |
| Response schemas | 3 | `api.py:163,177,185,202` — HTTPException for 401/502/503 with no documented schema | `responses={401: {"model": ErrorOut, "description": "Invalid API key"}, 502: ..., 503: ...}` |
| Tags | 0 | None | `tags=["Email"]` on send endpoints, `tags=["Health"]` on `/health` |
| Examples | 0 | None | `Field(..., example="user@example.com")` on every request model field; `openapi_examples=` on body params |
| ReDoc fallback | 8 | FastAPI auto-mounts `/redoc` | OK by default |
| App metadata | 3 | `api.py:127` only `title="email-service"` | `version=`, `description=`, `contact=`, `license_info=`, OpenAPI `servers=` |

**Surface B average: 2.7/10**

---

## 7-Pass Review

| Pass | Focus | Score | Note |
|---|---|---|---|
| 1 | Information architecture | 6 | Email flow h2 → body → CTA → fine-print is correct; Swagger has no grouping (no tags). |
| 2 | Interaction states | 6 | Emails static (N/A). Swagger try-it-out works but lacks example payloads, so first-time users hit validation walls. |
| 3 | User journey | 7 | Email → CTA → 15min expiry is clear. Subject prefix configurable. Plain-text alternative not wired in MagicLink/OTP notifiers (only TemplateNotifier supports it). |
| 4 | AI slop risk | 7 | Left-aligned, restrained palette, no gradients or emoji. Honest, not generated-looking. |
| 5 | Design system | 0 | No DESIGN.md, no shared tokens between MagicLink and OTP templates (colors, spacing, font duplicated). Acceptable for backend lib but worth a single `_BASE_STYLES` constant. |
| 6 | Responsive + a11y | 3 | No viewport, no max-width, no lang attr, contrast failure on fine-print, no dark mode. |
| 7 | Unresolved decisions | — | See TODOs below. |

---

## Approved improvements (TODO)

Prioritized. P0 = ship-blocker for "production-quality"; P1 = should-have; P2 = polish.

### P0 — Correctness / Accessibility

- [ ] **Fix WCAG AA contrast.** `notifiers.py:22` change `color:#888` → `color:#595959` (passes 7:1). Same review for any future fine-print.
- [ ] **Add `lang="ko"`** to `<html>` tag in both templates so screen readers pick the right voice.
- [ ] **Add viewport meta** `<meta name="viewport" content="width=device-width,initial-scale=1">` in `<head>` (and add a `<head>` — currently jumps straight to `<body>`).
- [ ] **Wrap body in 600px centered container** with `max-width:600px;margin:0 auto;padding:24px` so Gmail/Apple Mail don't render full-bleed on desktop.

### P0 — API discoverability

- [ ] **Tag operations**: `tags=["Email"]` on `/send`, `/send/magic-link`, `/send/otp`; `tags=["Health"]` on `/health`.
- [ ] **Add summary + description** to each `@app.post(...)`. Document the `X-Dry-Run` header behavior in the description (currently invisible in Swagger).
- [ ] **Document error responses**: declare `responses={401, 502, 503}` with a shared `ErrorOut` model so Swagger shows the failure shape.

### P1 — Polish

- [ ] **i18n hook for MagicLink/OTP**: accept `subject`, `heading`, `cta_label`, `fine_print` as constructor kwargs with current Korean as defaults. Removes hardcoded copy without breaking callers.
- [ ] **Dark mode** `@media (prefers-color-scheme: dark)` block: body bg `#1a1a1a`, text `#e8e8e8`, fine-print `#9a9a9a`, CTA bg unchanged (still legible on dark).
- [ ] **Plain-text alternative for MagicLink/OTP**: pass `text_body=` to `_sender.send()`. TemplateNotifier already supports this — propagate the pattern.
- [ ] **Hidden preheader** `<div style="display:none;max-height:0;overflow:hidden">…</div>` after `<body>` so inbox preview text isn't "안녕하세요, …".
- [ ] **Pydantic `Field(example=…)`** on every field in `SendEmailRequest`, `SendMagicLinkRequest`, `SendOTPRequest`. Makes Swagger try-it-out usable on first click.
- [ ] **App metadata**: `FastAPI(title=, version=, description=, contact=)` in `api.py:127`.

### P2 — Nice-to-have

- [ ] **Shared `_BASE_STYLES`** constant in `notifiers.py` to dedupe the body wrapper styles between MagicLink and OTP.
- [ ] **Full system font stack** instead of bare `sans-serif`.
- [ ] **Outlook VML fallback** for the CTA button (conditional comments). Only if Outlook desktop is a real user segment — likely yes for Korean enterprise.
- [ ] **`role="link"` + `aria-label`** on CTA anchor (low impact since anchor text is already descriptive).
- [ ] **OpenAPI `servers=`** entry so Swagger try-it-out targets the right base URL in non-localhost environments.

---

## Estimated post-fix overall score: **8.0 / 10**

After P0 + P1: emails meet WCAG AA, render correctly on mobile, support i18n + dark mode, and have a plain-text fallback. Swagger gains tags, summaries, response schemas, and request examples — enough that an integrator can wire it up without reading source. P2 items push toward 9 but aren't required for "production quality."

---

## Completion summary

Two design surfaces reviewed: HTML email templates (notifiers.py) and FastAPI Swagger UI (api.py).

**Initial:** 4.8/10. The emails are honest and not slop, but fail WCAG AA on fine-print contrast, lack any responsive container or dark mode, and hardcode Korean copy. The Swagger UI is bare auto-generated output with no tags, summaries, response schemas, or examples.

**Approved improvements:** 19 TODOs across P0 (4 emails + 3 API = 7), P1 (6), P2 (6). All are concrete edits to two files, no architecture changes.

**Estimated post-fix:** 8.0/10. None of the P0 items require new dependencies or rewrites; they are inline style tweaks, FastAPI decorator kwargs, and Pydantic Field examples.

No AskUserQuestion raised. All decisions made inline per instruction.
