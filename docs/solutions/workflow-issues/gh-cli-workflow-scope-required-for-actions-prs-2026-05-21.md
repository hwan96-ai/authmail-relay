---
title: gh CLI needs `workflow` OAuth scope to merge PRs that touch .github/workflows/
date: 2026-05-21
problem_type: workflow_issue
category: workflow-issues
track: knowledge
module: github-actions
tags:
  - gh-cli
  - oauth
  - dependabot
  - github-actions
  - branch-protection
applies_when: Attempting to merge a PR via `gh pr merge` when the PR modifies any file under `.github/workflows/`
---

## Context

Dependabot routinely opens PRs that bump pinned action SHAs in `.github/workflows/*.yml`
(e.g. `actions/checkout`, `actions/setup-python`, `pypa/gh-action-pypi-publish`). These
PRs look identical in shape to a Python dep bump — small diff, green CI — so the
natural follow-up is `gh pr merge <N> --squash --delete-branch`.

If the local `gh` CLI was authenticated with an OAuth flow that did not request the
`workflow` scope, the merge fails late — only after diff/check inspection, branch
checkout, and any local validation. Master stays at the previous SHA and the PR
remains OPEN with no clear next action surfaced by the tool's error message.

## Guidance

Before running `gh pr merge` on a PR that touches `.github/workflows/`, confirm the
local `gh` token has the `workflow` scope. If it does not, either:

1. Merge via the GitHub web UI (the browser session has the scope), or
2. Re-authenticate the CLI with `gh auth refresh -h github.com -s workflow` and retry.

A useful preflight when the file list includes workflow files:

```bash
# Inspect what the PR touches
gh pr view <N> --json files --jq '.files[].path'

# Verify gh scopes include `workflow`
gh auth status 2>&1 | grep -i 'token scopes'
```

If `workflow` is not in the listed scopes, do not attempt `gh pr merge` — it will
fail with a non-obvious GraphQL error and leave the PR open.

## Why This Matters

The failure mode is:

```
GraphQL: refusing to allow an OAuth App to create or update workflow
`.github/workflows/ci.yml` without `workflow` scope (mergePullRequest)
```

It surfaces *after* the agent has already burned cycles on diff inspection, branch
checkout, and any local validation. Without a preflight check, every Dependabot
GitHub-Actions PR repeats this discovery. With one, the agent immediately picks the
right merge path (web UI vs. CLI) up front.

This is distinct from the `block-dangerous-git.py` master-commit block — that hook
fires on local git operations; this one fires on the GitHub API side when merging.

## When to Apply

- Any Dependabot PR with `ecosystem: github-actions`
- Any manual PR that adds, modifies, or deletes files under `.github/workflows/`
- Any composite PR that mixes workflow changes with other changes (the scope check
  applies to the merge as a whole, not just the workflow file)

Routine code-only or doc-only PRs do not need this preflight.

## Examples

**Failed merge (no `workflow` scope):**

```
$ gh pr merge 11 --squash --delete-branch
GraphQL: refusing to allow an OAuth App to create or update workflow
`.github/workflows/ci.yml` without `workflow` scope (mergePullRequest)
```

PR #11 in this repo (`actions/checkout` v4.2.2 → v6.0.2 SHA bump) hit exactly this
on 2026-05-21. Master remained at `99291df`; the PR stayed OPEN. Resolution was to
hand off the merge to the web UI rather than re-scoping the CLI in the middle of an
automated cycle.

**Preflight in an agent workflow:**

```bash
files=$(gh pr view "$PR" --json files --jq '.files[].path')
if echo "$files" | grep -q '^\.github/workflows/'; then
  scopes=$(gh auth status 2>&1 | grep -i 'token scopes' || true)
  if ! echo "$scopes" | grep -q 'workflow'; then
    echo "PR touches workflows but gh lacks 'workflow' scope — merge via web UI" >&2
    exit 2
  fi
fi
gh pr merge "$PR" --squash --delete-branch
```
