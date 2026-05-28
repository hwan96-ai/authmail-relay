# Development Workflow

## When to use this

Use this document before changing files, installing dependencies, running local
commands, or choosing validation for a change.

## Setup

The project is a Python package using setuptools and `pyproject.toml`.
Repository docs show this development setup:

```bash
pip install -e ".[dev,http]"
python -m pytest tests/ -v
```

Python 3.10 or newer is required. HTTP service mode depends on the optional
`http` extra, which includes FastAPI, uvicorn, httpx, Prometheus client support,
and JSON logging support.

## Running the service

The CLI entry point is:

```bash
python -m authmail_relay
```

That starts the FastAPI service through uvicorn. The default host is
`127.0.0.1`; the Dockerfile sets `HOST=0.0.0.0` and `PORT=8000` for container
use.

For a one-shot SMTP credential smoke test, repository docs use:

```bash
python -m authmail_relay test --to me@example.com
```

Do not run a real SMTP smoke test unless the user explicitly provides approval
and confirms the target address and environment are safe.

## Editing rules

Prefer narrow, evidence-based edits. Preserve the current public API, CLI,
environment variable names, and security behavior unless the user explicitly
asks for product behavior changes.

For documentation-only tasks:

- Do not edit product code.
- Do not edit packaging, deployment, CI, or environment files unless the task
  explicitly includes them.
- Keep agent router files concise and move durable details into
  `docs/claude/`.
- Keep relative links working from the file where the link appears.

## Sensitive project context

This repository handles auth email delivery. While developing, avoid printing,
storing, or committing real SMTP credentials, API keys, relay tokens,
production endpoints, private email addresses, logs, or message contents.

Use examples such as `user@example.com` and placeholder secret names instead
of live values.
