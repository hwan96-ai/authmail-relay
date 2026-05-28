# AGENTS.md

Codex and other general-purpose coding agents should treat this file as the
router for repository-specific instructions.

Start with [docs/claude/README.md](docs/claude/README.md), then read the
specific child document that matches the task. Keep this file concise; durable
project guidance belongs under `docs/claude/`.

Core rules:

- This repository contains email/auth relay infrastructure. Treat credentials,
  logs, addresses, routing details, and message contents as highly sensitive.
- Do not expose SMTP credentials, API keys, auth secrets, relay tokens,
  production endpoints, private email addresses, logs, or message contents.
- Do not change product behavior unless the user explicitly asks for product
  code work and the change is verified.
- For portfolio or public showcase work, use a separate sanitized repository.
  Do not make this original repository public for showcase extraction.
- Do not commit local task files such as `.codex_task.md`.

Use these shared docs:

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
