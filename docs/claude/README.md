# Agent Instruction Index

## When to use this

Use this index at the start of any coding-agent session in this repository.
It routes agents to the durable project guidance without duplicating long
instructions in `AGENTS.md` or `CLAUDE.md`.

## Project instruction map

- [Project overview](project-overview.md): what this repository is, what it is
  not, and the main trust boundaries.
- [Repository map](repository-map.md): where the main package, tests, examples,
  docs, and deployment files live.
- [Development workflow](development-workflow.md): setup, dependency, branch,
  and edit-scope expectations.
- [Testing and validation](testing-and-validation.md): lightweight checks,
  pytest guidance, and documentation validation.
- [Security and secrets](security-and-secrets.md): secret-handling and
  sensitive-data rules for auth email infrastructure.
- [Portfolio showcase rules](portfolio-showcase-rules.md): how to handle any
  future public showcase work safely.
- [Release and git hygiene](release-and-git-hygiene.md): release evidence,
  branch hygiene, commits, and local-only files.

## Global agent rules

This repository is email/auth infrastructure. Agents must preserve privacy,
security, and portfolio readiness as first-class concerns.

Do not expose SMTP credentials, API keys, auth secrets, relay tokens,
production endpoints, private email addresses, logs, or message contents.

For public portfolio or showcase extraction, create a separate sanitized
repository. Do not make this original repository public.

Infer project behavior from repository evidence. Do not invent frameworks,
deployment platforms, credentials, environments, SLAs, or production topology.
