---
title: Review checklist for major-version Dependabot bumps of pinned-SHA GitHub Actions
date: 2026-05-21
problem_type: workflow_issue
category: workflow-issues
track: knowledge
module: github-actions
tags:
  - dependabot
  - github-actions
  - upload-artifact
  - download-artifact
  - pinned-sha
  - release-workflow
applies_when: Reviewing a Dependabot PR that bumps a `.github/workflows/*.yml` action across one or more major versions when the action is pinned by commit SHA
---

## Context

This repo pins every third-party Action by commit SHA with a human-readable version
comment above the `uses:` line (`# actions/upload-artifact v4.4.3`). Dependabot
updates the SHA but does not rewrite the comment, so after a few merges the comment
no longer matches the pinned version. That looks like a regression on inspection
(`grep` for `v4.4.3` still finds matches in the file) but is purely cosmetic.

On top of that, major-version bumps of artifact actions (`upload-artifact`,
`download-artifact`) carry breaking default changes that the one-line SHA diff does
not surface. Examples observed while clearing the Dependabot backlog on 2026-05-21:

- `actions/upload-artifact` v4 → v5 changed hidden-file inclusion defaults
- `actions/upload-artifact` v6 → v7 moved the runtime to Node 24
- `actions/download-artifact` v7 → v8 defaulted `digest-mismatch` to `error` and
  stopped unzipping non-zipped downloads
- `actions/download-artifact` v6 → v7 moved the runtime to Node 24

Reading only the diff is not enough; the reviewer also has to confirm the workflow
does not depend on the removed/changed defaults, and that the new
`upload-artifact` and `download-artifact` versions are still compatible with each
other.

## Guidance

For a Dependabot PR that bumps a pinned-SHA workflow action across one or more
major versions, run this fixed checklist before merging:

1. **PR state.** `gh pr view <N> --json state,mergeStateStatus,statusCheckRollup,files,headRefOid`.
   Require `state: OPEN`, `mergeStateStatus: CLEAN`, all checks `SUCCESS`.
2. **Diff scope.** `gh pr diff <N>`. Require exactly one `uses:` SHA line changed
   per affected job. Any extra lines (permissions, triggers, env, secrets) escalate
   to a manual review — Dependabot should not be editing those.
3. **Comment drift.** The `# action vX.Y.Z` comment above the `uses:` line is
   advisory and Dependabot does not update it. Do not treat a stale comment as a
   defect. Cross-check the SHA against the upstream release notes instead of
   trusting the comment.
4. **Major-version release notes.** For every major version crossed, read the
   release notes for breaking changes. Focus on defaults that the workflow relies
   on implicitly: artifact name, download path, `merge-multiple`, `overwrite`,
   `include-hidden-files`, `digest-mismatch`, decompression behavior, Node runtime
   version, and minimum runner version.
5. **Cross-action compatibility.** `upload-artifact` and `download-artifact` ship
   on independent major-version tracks but share the artifact API contract. After
   either is bumped, confirm the other still works against the new contract.
   `upload-artifact` v4+ and `download-artifact` v4+ all use the new API; mixing
   v4-v8 across the pair is supported. Mixing a v3-or-earlier with a v4-or-later
   is not.
6. **Release gates intact.** For PRs touching `release.yml`, re-verify the gates
   are unchanged: `on: workflow_dispatch`, publish job
   `if: github.event_name == 'workflow_dispatch'`, `environment: pypi`,
   `id-token: write` isolated to the publish job, build/test jobs `contents: read`
   only. The diff scope check in step 2 catches most regressions here; this step
   is the explicit re-read.
7. **Merge routing.** See
   [gh-cli-workflow-scope-required-for-actions-prs-2026-05-21.md](gh-cli-workflow-scope-required-for-actions-prs-2026-05-21.md) — `gh pr merge` requires the
   `workflow` OAuth scope; if missing, route to the web UI.

Do not run the release workflow, trigger `workflow_dispatch`, or push a tag as
part of merging the bump. The build-and-smoke job already runs on the PR via
`ci.yml`; that is the validation signal.

## Why This Matters

Major-version bumps of artifact actions look mechanically identical to patch
bumps — one SHA changes, CI is green — but the upstream defaults that change
between majors can silently break a release the next time it runs. The release
workflow on this repo is manually dispatched, so a regression introduced today
will not surface until the next publish attempt, possibly weeks later, with the
maintainer trying to ship and no recent context on what changed.

A fixed checklist makes the review repeatable and bounded: the reviewer does not
have to re-derive what to look at from scratch each time a Dependabot PR for a
workflow action lands, and does not have to remember which defaults shifted in
which major version.

The checklist also encodes two non-obvious facts that cost cycles the first time
through:

- The `# action vX.Y.Z` comment drifts from the SHA and should be ignored as a
  source of truth.
- `upload-artifact` and `download-artifact` are versioned independently; the
  reviewer must confirm the pair after either side moves.

## When to Apply

- Any Dependabot PR with `ecosystem: github-actions` where the bump crosses a
  major-version boundary
- Any manual SHA bump of `actions/upload-artifact`, `actions/download-artifact`,
  or other pinned third-party actions in `.github/workflows/`
- Any audit of `.github/workflows/release.yml` after a workflow-action SHA
  changes

Routine patch- or minor-version Dependabot bumps still need steps 1, 2, 3, and 7
but can skip the breaking-change reading in steps 4-6.

## Examples

**PR #9 (`actions/download-artifact` 4.1.8 → 8.0.1) on 2026-05-21:**

- Step 1: `state: OPEN`, `mergeStateStatus: CLEAN`, `Test` and
  `GitGuardian Security Checks` both `SUCCESS`.
- Step 2: Diff was a single SHA change at `release.yml:146` in the `publish` job
  (`fa0a91b…` → `3e5f45b…`). No other lines touched.
- Step 3: The comment `# actions/download-artifact v4.1.8` above the line is now
  stale. Ignored as expected; confirmed `3e5f45b…` against the v8.0.1 release on
  GitHub.
- Step 4: v5-v8 release notes reviewed. Workflow uses only `name: dist` and
  `path: dist` with no `merge-multiple`, `pattern`, `overwrite`, or
  `include-hidden-files` flags, so the changed defaults (Node 24 in v7,
  ESM/`digest-mismatch: error`/content-type-aware unzip in v8) do not affect the
  single-named-artifact download path.
- Step 5: Master already holds `upload-artifact` at SHA `043fb46d…` (v7.0.1 via
  PR #8). Upload v7 + download v8 both use the new artifact API → compatible.
- Step 6: Gates unchanged — diff did not touch lines 36, 51, 133, 135-137, or
  142 of `release.yml`.
- Step 7: `gh auth status` reported scopes `'gist', 'read:org', 'repo'`. No
  `workflow` scope, so CLI merge was not attempted; routed to web UI per the
  existing scope rule.

**Comment-drift cosmetic example after PR #8 merged:**

```yaml
# actions/upload-artifact v4.4.3                              # stale comment
- uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a  # actually v7.0.1
```

The comment looks like a regression on `grep v4.4.3` but is purely cosmetic —
the SHA is the source of truth.
