---
title: Sweep stale `# action vX.Y.Z` comments as a separate chore PR, not inside the Dependabot merge
date: 2026-05-21
problem_type: workflow_issue
category: workflow-issues
track: knowledge
module: github-actions
tags:
  - dependabot
  - github-actions
  - pinned-sha
  - chore
  - release-workflow
applies_when: After merging one or more Dependabot PRs that bump pinned-SHA GitHub Actions in `.github/workflows/*.yml`, when the human-readable `# action vX.Y.Z` comments above the `uses:` lines no longer match the merged SHAs
---

## Context

Actions in `.github/workflows/*.yml` are pinned by commit SHA with a human-readable
version comment immediately above:

```yaml
# actions/upload-artifact v4.4.3
- uses: actions/upload-artifact@b4b15b8c7c6ac21ea08fcf65892d2ee8f75cf882
```

Dependabot rewrites the SHA but does not rewrite the comment. After a few merges
the comment is no longer the version actually pinned. PR #8 (upload-artifact
v4.4.3 → v7.0.1) and PR #9 (download-artifact v4.1.8 → v8.0.1) on 2026-05-21
both left their comments at the pre-bump version.

The temptation is to fix the comment inside the Dependabot PR before merging.
Don't — it expands the diff scope of an automated PR, breaks the "single SHA
line" review heuristic that other agents and humans use to greenlight Dependabot
bumps quickly, and re-runs CI for a comment edit.

## Guidance

After the Dependabot merge lands on master, open a separate chore PR that
edits only the stale comment lines:

1. Branch off `master`: `git checkout -b chore/update-<action>-comments`
2. Edit `.github/workflows/*.yml` to align each `# action vX.Y.Z` comment with
   the actual pinned SHA. Use the SHA's upstream release tag as the source of
   truth (look up the SHA on the action's GitHub releases page or via
   `gh api repos/<owner>/<repo>/git/refs/tags/<tag>`).
3. Verify the diff is comment-only with `git diff master -- .github/workflows/`
   and `git diff --check`. The diff should be exactly N lines changed where N
   is the number of stale comments.
4. Commit message: `chore: update <action> version comments`
5. Open the PR with a body that explicitly states: comment-only cleanup, no SHA
   changes, no workflow behavior changes. This lets reviewers (and the
   workflow-scope merge rule in
   [gh-cli-workflow-scope-required-for-actions-prs-2026-05-21.md](gh-cli-workflow-scope-required-for-actions-prs-2026-05-21.md))
   apply the same "diff scope is one line per action" check from
   [major-version-dependabot-actions-bump-review-checklist-2026-05-21.md](major-version-dependabot-actions-bump-review-checklist-2026-05-21.md).

Because the file lives under `.github/workflows/`, the chore PR is still
subject to the `workflow` OAuth scope rule for `gh pr merge` — route to the
web UI if the CLI lacks the scope.

## Why This Matters

The comment is decorative, not load-bearing — the SHA is the source of truth —
so the cost of letting it drift is small. But cumulative drift across many
Dependabot merges makes the file misleading on inspection: `grep v4.4.3` finds
a match that is not actually pinned, and a casual reader sees a "v4 pin" that
is actually v7. The fix is cheap (a one-line `sed`-equivalent edit per action)
but only if it stays out of the Dependabot PR itself.

Folding the comment edit into the Dependabot PR is worse than letting it drift:

- It expands the diff beyond the single `uses:` SHA line, defeating the fast
  "one line per action" review heuristic.
- It changes the commit author on the merged commit from `dependabot[bot]` to
  whoever amended it, which breaks the audit trail of "this commit is exactly
  what Dependabot proposed."
- It triggers a CI re-run for a comment-only edit, wasting minutes.

Doing the sweep as a separate chore PR keeps each PR's scope honest: the
Dependabot PR is "the SHA bump, exactly as Dependabot proposed it," and the
chore PR is "the cosmetic comment sync, no behavior change." Each can be
reviewed by its own heuristic.

## When to Apply

- After merging any Dependabot PR that updated a pinned SHA in
  `.github/workflows/*.yml`. Batch multiple stale comments into one chore PR if
  several Dependabot PRs landed in the same window.
- After a manual SHA bump where the editor forgot to update the comment.
- During a routine workflow-file audit when `grep` for an old version still
  matches the comment line.

Not needed when the comment was updated in the same commit as the SHA bump
(e.g. a manual upgrade that touched both lines).

## Examples

**Workflow on 2026-05-21:** PR #8 and PR #9 merged within the same morning,
both with stale comments. The cleanup landed as a separate chore PR
([#24](https://github.com/hwan96-ai/email-service/pull/24)) batching both:

```diff
-      # actions/upload-artifact v4.4.3
+      # actions/upload-artifact v7.0.1
       - name: Upload built artifacts for publish job
         uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
```

```diff
-      # actions/download-artifact v4.1.8
+      # actions/download-artifact v8.0.1
       - uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c
```

Diff scope: 4 lines changed, 0 SHA bytes touched. CI on the chore branch
re-ran the same `Test` workflow as before — no behavior change to validate
because no behavior changed.

**Autosave-hook interaction:** the local autosave hook in this repo creates a
commit per file save. Two separate `Edit` calls produced two
`autosave: claude changes …` commits on the chore branch. Squash-merge
collapses them in the final PR commit. The autosave commits are noisy but
harmless on a short-lived chore branch — they are not worth the friction of
trying to `--amend`, which the `block-dangerous-git.py` hook blocks anyway
(see [autosave-hook-creates-noisy-commits-2026-05-21.md](autosave-hook-creates-noisy-commits-2026-05-21.md)).
