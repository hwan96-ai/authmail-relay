# Release and Git Hygiene

## When to use this

Use this document before creating branches, commits, tags, release notes,
deployment changes, or PR descriptions.

## Branch and commit hygiene

Start by checking the current branch and worktree status. Preserve user changes
you did not make. Do not reset, overwrite, or discard unrelated work.

For scoped tasks, stage only the files allowed by the task. Use
`git diff --name-only` before staging and after staging to confirm scope.

Do not commit local-only task files such as `.codex_task.md`.

## Release evidence in this repository

`pyproject.toml` is the package metadata source for the distribution name,
version, Python requirement, dependencies, optional dependency groups, and
project URLs.

`CHANGELOG.md` records release history. `docs/deployment.md` describes the
PyPI release pipeline as a manual two-step flow: tag push for build and smoke
checks, then workflow dispatch with the tag to publish.

The deployment docs also state that release automation pins GitHub Actions by
commit SHA and that a bad PyPI publish can only be yanked, not reused.

## Deployment file caution

`Dockerfile`, `docker-compose.yml`, `docker-compose.dev.yml`, and GitHub
workflow files affect runtime or release behavior. Do not edit them during
agent-harness or docs-only tasks unless explicitly allowed.

## Final verification pattern

Before handing back work:

```bash
git diff --check
git diff --name-only
git status --short
```

If committing, review the diff first, stage only intended files, commit with
the requested message, push the requested branch, and show final status.
