---
title: Verify current PR state before acting on instructions
date: 2026-05-21
problem_type: workflow_issue
category: workflow-issues
track: knowledge
module: pr-management
tags:
  - github
  - pr-workflow
  - autosave
  - state-verification
applies_when: A user instruction names a specific PR/branch to act on across sessions
---

# Verify current PR state before acting on instructions

## Context

A multi-session task handed instructions like "merge PR #19 if mergeable, then handle Dependabot PR #13 first". By the time the new session ran, both PR #19 and PR #13 were already merged by prior automation/sessions. Without checking state first, an agent could waste a turn trying to merge an already-merged PR, or worse, recreate the work.

Related: the repo's autosave hook can produce commits between sessions (see [[autosave-hook-creates-noisy-commits-2026-05-21]]), so the "world" may have changed since the instructions were written.

## Guidance

Before acting on any cross-session instruction that names a specific PR, branch, or commit:

1. `gh pr view <N> --json state,mergeable,mergeStateStatus` — confirm PR is still open and mergeable
2. `git log --oneline -10 origin/master` — confirm referenced commits/PRs are not already on the default branch
3. Re-read `gh pr list --state open` against the priority list — items may have been merged or closed

Treat user instructions as a snapshot from when they were written, not a live source of truth.

## Why This Matters

- Saves a wasted turn attempting actions on already-completed work
- Prevents accidentally re-doing or reverting merged changes
- Surfaces drift early so the agent can adapt the plan rather than blindly execute

## When to Apply

- Any `/goal`-style multi-step task that names PRs/branches/issues by number
- Resuming work after autosave hooks, scheduled jobs, or other agents may have acted
- Dependabot priority lists where items get merged out from under the instruction

## Examples

Before (blindly follows instruction):
```
# Instruction: "merge PR #19"
gh pr merge 19 --squash   # fails: already merged
```

After (verifies first):
```
gh pr view 19 --json state,mergeStateStatus
# state=MERGED → skip, move to next priority item
git log --oneline -5      # confirm #19's commit is on master
```
