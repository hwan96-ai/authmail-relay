---
title: Public release docs must match runtime config
date: 2026-05-21
category: docs/solutions/documentation-gaps
module: public-release-documentation
problem_type: documentation_gap
component: documentation
severity: medium
applies_when:
  - "Preparing a repo for public GitHub release or public deployed URL sharing"
  - "Updating README quickstarts that depend on Docker Compose or environment variables"
  - "Documenting security-sensitive examples such as API keys, webhooks, metrics, or HTML templates"
tags: [public-release, readme, docker-compose, security-docs, verification]
---

# Public release docs must match runtime config

## Context

The public-release review found that the README still taught an old Mailpit quickstart using a hardcoded weak development token, while `docker-compose.dev.yml` had already been hardened to require `API_KEY` from `.env`. That mismatch made first-time onboarding fail and also left a weak-key pattern in public-facing docs.

The same review surfaced adjacent public-readiness gaps: a custom notifier example interpolated untrusted HTML directly, webhook receiver docs prioritized replayable V1 signatures, metrics docs allowed unauthenticated public exposure by example, package trust files were missing, and package metadata was too thin for a public Python package.

## Guidance

Treat public-release documentation as executable configuration, not prose. For each quickstart or security example:

- Read the runtime config first (`docker-compose*.yml`, `.env.example`, `pyproject.toml`, and the implementation).
- Remove active weak-secret examples instead of labeling them "dev only".
- Keep onboarding commands copy-pasteable for the project’s real target shells.
- Prefer documentation guardrails over runtime behavior changes when compatibility risk is higher than the doc gap.
- Run targeted searches after editing, especially for weak keys and legacy security patterns.

Concrete checks used here:

```powershell
rg -n "weak development token" README.md .env.example docker-compose.dev.yml SECURITY.md pyproject.toml -S
rg -n "1s, 10s, 60s|Bearer secret" README.md -S
python -m pytest tests/ -v
git diff --check
git status --short --untracked-files=all
```

## Why This Matters

A public README is often the first production runbook users copy from. If it drifts from runtime config, users either fail during setup or cargo-cult unsafe defaults into deployments. Security examples are especially sticky: a weak API key, replayable webhook verifier, or unescaped HTML snippet can survive long after the implementation has been fixed.

## When to Apply

- Before moving a repository from private/internal use to public GitHub.
- After hardening runtime config, especially when docs previously showed permissive defaults.
- When release reviews identify docs that contradict code behavior.
- When adding examples for auth, webhooks, metrics, SMTP credentials, HTML templates, or deployment.

## Examples

Before:

```bash
# README claimed this worked, but compose no longer set it.
curl -H "Authorization: Bearer <redacted-weak-token>" http://127.0.0.1:8000/send/otp
```

After:

```bash
API_KEY=$(openssl rand -hex 32)
printf "API_KEY=%s\n" "$API_KEY" > .env
docker compose -f docker-compose.dev.yml up -d --build
curl -H "Authorization: Bearer $API_KEY" http://127.0.0.1:8000/send/otp
```

Before:

```python
html = f"<h1>{user_name}</h1><p>{payload}</p>"
```

After:

```python
from html import escape

html = f"<h1>{escape(user_name)}</h1><p>{escape(payload)}</p>"
```

## Mistakes And Wrong Assumptions

- Assuming a prior compose hardening was fully reflected in README. It was not: the active Mailpit section still documented a weak development token.
- Treating webhook docs as already migrated because implementation emitted V2 signatures. The practical receiver example still taught V1-only verification.
- Letting an SDK example use `"secret"` as a placeholder API key after adding stronger production guidance.
- Trying to run `python -m build` late in verification without accounting for sandbox subprocess restrictions; pytest passed, but build verification remained blocked by the environment.

## Final Fixes

- README Mailpit quickstart now creates `.env` with a generated `API_KEY` and includes PowerShell-friendly commands.
- Public docs now recommend V2 timestamped webhook signature verification first and label V1 as legacy.
- Custom notifier example escapes user-controlled values with `html.escape`.
- Production guidance now calls out strong API keys, TLS/proxy placement, body limits, failed-auth rate limiting, authenticated metrics, safe SMTP credential handling, and dependency constraints/lock recommendations.
- Trust files and metadata were added: `LICENSE`, `SECURITY.md`, PR CI, Dependabot, and fuller `pyproject.toml` metadata.

## Prevention Rules

- Every README quickstart that uses Docker Compose must be checked against the compose file before release.
- Public docs must not contain active weak API key examples; use generated values or environment variables.
- Receiver examples for signed callbacks must include freshness checks, not just HMAC comparison.
- Custom HTML examples must escape untrusted values at the point of interpolation.
- Public-release verification should include both tests and text searches for old insecure examples.

## Related

- README Mailpit/dev quickstart
- `docker-compose.dev.yml`
- `.env.example`
- `email_service/webhooks.py`
- `email_service/api.py`
