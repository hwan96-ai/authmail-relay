---
title: Validate build-system.requires bumps with build + twine, not just pytest
date: 2026-05-21
problem_type: convention
category: conventions
track: knowledge
module: packaging
tags:
  - dependabot
  - packaging
  - setuptools
  - pyproject
  - validation
applies_when: A Dependabot PR (or manual bump) changes pyproject.toml's [build-system] requires
---

# Validate build-system.requires bumps with build + twine, not just pytest

## Context

Dependabot opens PRs that bump `pyproject.toml`'s `[build-system] requires` (e.g., `setuptools>=68.0` → `setuptools>=82.0.1`). These dependencies do not run at import time, so `pytest` passing tells you nothing about whether the wheel/sdist still builds cleanly or stays PyPI-uploadable. A green test suite has historically been treated as the merge signal, which is insufficient for this class of bump.

Related: [[verify-pr-state-before-acting-2026-05-21]] for cross-session PR state hygiene; PR #15 (setuptools >=82.0.1) was the trigger for codifying this.

## Guidance

For any PR that modifies `[build-system] requires` in `pyproject.toml`, run the full packaging chain locally on the PR branch before merging:

1. `gh pr checkout <N>`
2. `python -m pytest tests/ -q` — sanity check that nothing imports-time regressed
3. `rm -rf dist/ build/ *.egg-info` — clean to avoid contamination from stale artifacts
4. `python -m build` — exercise the new build backend version against the actual project metadata
5. `python -m twine check dist/*` — verify the wheel and sdist are PyPI-uploadable (METADATA, README rendering)
6. `rm -rf dist/ build/ *.egg-info` — clean again before switching back to master so artifacts never leak into a merge

Only merge after all four steps pass.

## Why This Matters

- `setuptools`, `wheel`, `build`, `hatchling`, `poetry-core` and similar live in `[build-system] requires`. They do not appear in `sys.modules` at runtime, so pytest cannot detect regressions in them
- Real failure modes for build-system bumps: deprecated config keys that the new version drops, metadata format changes (`License-Expression` vs `License`), changed default behavior for `packages`/`package_data` discovery, README/long-description rendering errors caught by twine
- Skipping the build step means the regression surfaces in the release workflow (or worse, on PyPI upload), where the cost to recover is much higher than 30 seconds locally
- Cleaning `dist/` matters: a stale wheel from a previous build can be picked up by twine check and mask a real failure in the new build

## When to Apply

- Any Dependabot PR labeled `python` whose diff touches `pyproject.toml` `[build-system]` block
- Manual bumps of build-time deps (`setuptools`, `wheel`, `build`, `hatchling`, `poetry-core`, `flit-core`, `pdm-backend`, etc.)
- PRs that change `build-backend` or backend configuration even if the version is unchanged

Does NOT apply to runtime dep bumps in `[project.dependencies]` or `[project.optional-dependencies]` — those are exercised by pytest.

## Examples

PR #15 — `setuptools>=68.0` → `setuptools>=82.0.1`:

```bash
gh pr checkout 15
python -m pytest tests/ -q           # 183 passed, 2 skipped
rm -rf dist/ build/ *.egg-info
python -m build                       # Successfully built email_service-0.4.0.tar.gz and .whl
python -m twine check dist/*          # PASSED on both wheel and sdist
rm -rf dist/ build/ *.egg-info
git checkout master
gh pr merge 15 --squash --delete-branch
```

Anti-pattern (insufficient):

```bash
gh pr checkout 15
python -m pytest                      # passes
gh pr merge 15                        # merged — but build regression undetected
```
