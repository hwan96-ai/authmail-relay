---
title: Bootstrap agent harness docs without product changes
date: 2026-05-28
category: documentation-gaps
module: agent-harness-documentation
problem_type: documentation_gap
component: documentation
severity: low
applies_when:
  - "A private or portfolio-sensitive repository needs agent instructions"
  - "A harness task requires routers plus shared durable docs"
  - "A required file is intentionally ignored but must be committed"
tags: [agent-harness, documentation, privacy, git-hygiene]
---

# Bootstrap agent harness docs without product changes

## Context

This task created a coding-agent harness for a private, email/auth-sensitive
repository. The explicit requirement was documentation-only work: root routers
for Codex/general agents and Claude Code, shared durable instruction documents
under `docs/claude/`, and a compound lesson under the allowed
`docs/solutions/documentation-gaps/` path.

The main risk was accidentally broadening the task into product behavior,
public-release cleanup, or unrelated repository changes.

## Mistakes

- `git diff --name-only` did not show newly created untracked files until
  intent-to-add entries were created.
- `CLAUDE.md` was ignored by `.gitignore`, so it required an explicit forced
  add path even though the task required it.
- Some PowerShell and Node helper attempts failed with sandbox spawn-refresh
  errors, so validation had to rely on simpler successful commands.

## Wrong Assumptions

- New files are not visible in `git diff` by default. Use `git status --short`
  and, when a pre-stage diff is required, `git add -N` for new files.
- Required task files can be ignored by repository policy. Check `.gitignore`
  before assuming absence from status means absence from disk.

## Failed Attempts

- Creating directories with `New-Item` failed under the sandbox, but
  `apply_patch` successfully created nested files.
- A Node-based markdown link validation helper failed under the same sandbox
  condition, so link validation used `rg` and direct file discovery instead.
- The ce-compound frontmatter validator script could not run in the sandbox,
  and the escalated retry was rejected by the approval system, so the
  frontmatter was inspected manually against the schema.

## Review Findings

- The repo is a Python 3.10+ package using setuptools with FastAPI HTTP mode,
  SMTP library mode, sync and async `httpx` clients, Docker examples, and
  pytest coverage.
- Existing docs already emphasize internal deployment, SMTP/API secret
  handling, protected metrics/docs, webhook signing, PII-safe logging, and no
  real SMTP usage in tests.
- The root routers should stay concise, with detailed instructions in
  `docs/claude/`.
- Future public portfolio work must happen in a separate sanitized repository,
  not by making the original repository public.

## Final Solutions

- Added `AGENTS.md` and `CLAUDE.md` as concise routers.
- Added shared durable instruction docs under `docs/claude/`.
- Added a discoverability note for `docs/solutions/` in both root routers.
- Kept changes within the allowed documentation scope.
- Used intent-to-add plus `git diff` to review new-file content before final
  staging.
- Manually checked the compound note frontmatter after the validator command
  was blocked.

## Prevention Rules

- For documentation-only harness tasks, inspect repository evidence before
  writing guidance and do not infer unsupported frameworks or deployment facts.
- Use `git status --short --untracked-files=all` alongside `git diff
  --name-only` so ignored and untracked paths do not hide scope issues.
- If a required file is ignored, force-add only that exact allowed file and call
  it out in the final report.
- Keep root agent files as routers and put durable details in shared docs to
  avoid drift between agent harnesses.
- For private email/auth infrastructure, never include live secrets,
  production endpoints, private email addresses, logs, or message contents in
  docs, commits, or final summaries.

## Related

- `AGENTS.md`
- `CLAUDE.md`
- `docs/claude/README.md`
