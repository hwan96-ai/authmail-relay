---
title: Autosave hook in email-service creates noisy commits before manual commit
date: 2026-05-21
category: docs/solutions/workflow-issues
module: repo-workflow
problem_type: workflow_issue
component: git-hooks
severity: low
applies_when:
  - "Working in the email-service repo where a SessionStart/autosave hook auto-creates a working branch and auto-commits intermediate changes"
  - "Preparing a single clean docs or feature commit for a PR-based workflow"
  - "Running /ce-compound or any flow that expects a tidy `git log` for one logical change"
tags: [git, hooks, autosave, branch-management, commit-hygiene, workflow]
---

# Autosave hook in email-service creates noisy commits before manual commit

## Context

The `email-service` repo runs a SessionStart hook that, when the session starts on `master`, automatically creates a new branch named `claude/session-<timestamp>` to protect `master`. A separate autosave hook then periodically commits in-flight edits with messages like `autosave: claude changes <timestamp>`.

When the goal is a single, reviewable docs/feature commit (e.g., for a PR titled `docs: add public deploy readiness runbook`), the autosave commits land between `git checkout -b <real-branch>` and the eventual manual `git commit`. The branch ends up with 2–3 `autosave: ...` commits on top of the intended commit, and `git status` shows a clean working tree at the very moment you expect to stage a diff — because the hook already committed it.

The first signal of this is "working tree clean" right after writing files, plus extra `autosave: ...` entries in `git log --oneline`.

## Guidance

Do not fight the autosave hook by trying to suppress it mid-session. Instead, plan for it in the commit step:

1. After all file edits are done, run `git log --oneline -5` and identify the last upstream commit (e.g., `45cf6bf` on `origin/master`).
2. `git reset --soft <last-upstream-sha>` to collapse all autosave commits back into the staging area while keeping the working tree intact.
3. Inspect the staged diff: `git diff --cached --stat` and `git diff --cached --check`.
4. Create one clean commit with the real message, using a HEREDOC for multiline bodies.
5. Push and create the PR as usual. The autosave commits never reach `origin`.

When you create your own branch (e.g., `docs/public-deploy-readiness-runbook`) off the auto-created session branch, the autosave hook still runs there too — so apply the same soft-reset step on whatever branch you finally push.

## Why This Matters

- A PR with two `autosave: claude changes <timestamp>` commits plus one real commit looks careless and obscures the diff in code review.
- Reviewers can no longer trust the commit subject as a description of the change.
- Bisect and revert workflows downstream become harder because the meaningful change is split across arbitrary autosave boundaries.
- Believing the working tree is clean when it isn't can cause a second wave of edits to silently land in a follow-up autosave commit with a misleading message.

The soft-reset workaround is cheap (one command) and keeps `origin/<branch>` history clean without disabling a hook that exists for safety reasons.

## When to Apply

- Any session in this repo where the SessionStart hook reports `🌿 main 브랜치 감지 → 새 브랜치 자동 생성` or similar.
- Any time `git log` shows commits prefixed with `autosave: claude changes`.
- Before `git push` and `gh pr create`, especially for docs PRs where commit hygiene is part of the deliverable.
- Not applicable when the autosave commits *are* the intended history (e.g., the existing merged PR #18 uses that style by design).

## Examples

Detect-and-fix pattern used in the public-deploy-readiness runbook PR:

```bash
# After writing docs and expecting to commit
git status                       # "nothing to commit, working tree clean" — surprise
git log --oneline -5
# c4518a0 ... (not yet — only autosaves so far)
# f419370 autosave: claude changes 2026-05-21 18:53:53
# 9e148dd autosave: claude changes 2026-05-21 18:53:43
# 45cf6bf autosave: claude changes 2026-05-21 18:04:48 (#18)   <- last upstream

git reset --soft 45cf6bf
git diff --cached --stat         # confirm the real change is staged
git commit -m "$(cat <<'EOF'
docs: add public deploy readiness runbook

<body...>
EOF
)"
git push -u origin docs/public-deploy-readiness-runbook
```

Preventive rule, in one line: **In `email-service`, treat a clean working tree after edits as evidence the autosave hook ran — always `git log` and soft-reset to the last upstream SHA before the final commit.**
