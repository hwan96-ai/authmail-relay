# CLAUDE.md

Claude Code should treat this file as the project router. Keep long-lived
instructions in `docs/claude/` so Claude, Codex, and other agents share one
source of truth.

Read [docs/claude/README.md](docs/claude/README.md) first, then load the
document relevant to the task.

Non-negotiables:

- This is email/auth infrastructure. Handle secrets, endpoints, logs, private
  addresses, and message content as sensitive data.
- Never expose SMTP credentials, API keys, auth secrets, relay tokens,
  production endpoints, private email addresses, logs, or message contents.
- Do not change product behavior during documentation or harness work.
- Public portfolio extraction must happen in a separate sanitized repository,
  not by making this original repository public.
- Do not commit `.codex_task.md` or other local-only task files.

Shared instruction index:

- [Project overview](docs/claude/project-overview.md)
- [Repository map](docs/claude/repository-map.md)
- [Development workflow](docs/claude/development-workflow.md)
- [Testing and validation](docs/claude/testing-and-validation.md)
- [Security and secrets](docs/claude/security-and-secrets.md)
- [Portfolio showcase rules](docs/claude/portfolio-showcase-rules.md)
- [Release and git hygiene](docs/claude/release-and-git-hygiene.md)

Documented solutions live in `docs/solutions/`, organized by category with
YAML frontmatter such as `module`, `tags`, and `problem_type`. They are useful
when implementing, debugging, or documenting in already-covered areas.
