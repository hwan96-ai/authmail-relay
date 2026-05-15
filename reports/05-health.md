# CODE HEALTH DASHBOARD

**Project:** email-service
**Branch:** claude/sad-cannon-1131fe
**Date:** 2026-05-15
**Run:** First run (no trend data)

## Results

| Category   | Tool       | Score | Status   | Duration | Details                                    |
|------------|------------|-------|----------|----------|--------------------------------------------|
| Type check | mypy       | —     | SKIPPED  | —        | mypy not installed; not in dev extras      |
| Lint       | ruff       | —     | SKIPPED  | —        | ruff not installed; no [tool.ruff] config  |
| Tests      | pytest     | 10/10 | PASS     | 1.43s    | 69 passed, 0 failed                        |
| Dead code  | vulture    | —     | SKIPPED  | —        | vulture not installed                      |
| Shell lint | shellcheck | —     | SKIPPED  | —        | no .sh files in repo                       |
| GBrain     | —          | —     | SKIPPED  | —        | not configured                             |

## Composite Score

Only `pytest` ran; all other categories skipped. Weight collapses to 100% on tests.

**COMPOSITE SCORE: 10.0 / 10**

Caveat: this score reflects test health only. Five of six rubric dimensions could not be measured, so the composite is not representative of overall code health. Treat as "tests-green" rather than "fully healthy."

## Recommendations (sorted by impact = weight × deficit)

Impact here is the *missing-signal* impact — installing each tool would reveal hidden deficits worth this much of the composite weight.

1. **[28% signal recovery] Install mypy** — Add `mypy` to `[project.optional-dependencies].dev` in `pyproject.toml`. Run `python -m mypy email_service/`. Highest-weight category currently dark.
   - Suggested: `dev = ["pytest>=7.0", "httpx>=0.25", "mypy>=1.8"]`

2. **[18% signal recovery] Install ruff + configure** — Add `ruff` to dev extras and a `[tool.ruff]` block. Replaces flake8/black/isort. Run `python -m ruff check email_service/ tests/`.
   - Suggested: `dev = [..., "ruff>=0.4"]`
   - Suggested config: `[tool.ruff] line-length = 100` + `[tool.ruff.lint] select = ["E","F","I","UP","B"]`

3. **[13% signal recovery] Install vulture** — Catches dead code that lint won't. `dev = [..., "vulture>=2.10"]` then `python -m vulture email_service/ --min-confidence 80`.

4. **[low priority] Shell lint & GBrain** — No `.sh` files exist; shellcheck not applicable. GBrain integration is optional and unrelated to baseline health.

## Next Run

Once mypy/ruff/vulture are added, re-run `/health` to populate the dashboard and establish a trend baseline. Target: keep composite ≥8.0 across all six dimensions before merging significant changes.
