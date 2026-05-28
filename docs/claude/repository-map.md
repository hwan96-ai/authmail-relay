# Repository Map

## When to use this

Use this document when locating files, deciding where an edit belongs, or
checking whether a requested change is documentation-only or product code.

## Top-level files

- `README.md`: main product, setup, security, Docker, configuration, and
  development overview.
- `README.ko.md`: Korean README.
- `pyproject.toml`: Python package metadata, setuptools configuration, and
  optional dependency groups.
- `SECURITY.md`: private vulnerability reporting and disclosure expectations.
- `CONTRIBUTING.md`: contributor setup, tests, commit conventions, and PR
  checklist.
- `CHANGELOG.md`: release history.
- `Dockerfile`, `docker-compose.yml`, `docker-compose.dev.yml`: container and
  local Mailpit development examples.

## Package code

- `authmail_relay/`: current import package and product code.
- `email_service/`: legacy compatibility shim for old imports.

Important modules:

- `authmail_relay/api.py`: FastAPI app factory and HTTP endpoints.
- `authmail_relay/sender.py`: SMTP send implementation.
- `authmail_relay/notifiers.py`: auth-email notifier helpers.
- `authmail_relay/client.py`: sync HTTP client SDK.
- `authmail_relay/async_client.py`: async HTTP client SDK.
- `authmail_relay/webhooks.py`: webhook delivery and signing.
- `authmail_relay/url_validation.py`: webhook URL validation.
- `authmail_relay/metrics.py`: optional Prometheus metrics.
- `authmail_relay/logging_config.py`: optional JSON logs and recipient hashing.
- `authmail_relay/__main__.py`: CLI entry point.

## Tests and examples

- `tests/`: pytest suite for API behavior, SMTP sender behavior, clients, CLI,
  observability, security fixes, idempotency, webhooks, retries, and the legacy
  shim.
- `examples/`: integration snippets for FastAPI, Django, Flask, and `.eml`
  capture-mode testing.

## Documentation

- `docs/api.md`: HTTP and library API reference.
- `docs/configuration.md`: environment variable reference.
- `docs/deployment.md`: production deployment guidance and release pipeline
  notes.
- `docs/operations.md`: metrics, logs, tracing, retries, and test capture mode.
- `docs/webhooks.md`: webhook payloads, signatures, retry behavior, and SSRF
  notes.
- `docs/supabase-auth.md`: Supabase Auth integration notes.
- `docs/providers.md`: auth-provider notes index.
- `docs/alternatives.md`: product positioning.
- `docs/runbooks/`: operational runbooks.
- `docs/claude/`: shared coding-agent harness instructions.

## Edit boundaries

For documentation-harness work, stay in `AGENTS.md`, `CLAUDE.md`,
`docs/claude/**`, or explicitly allowed documentation-gap files. Product code,
packaging metadata, deployment files, security policy files, GitHub workflows,
and environment files are outside that scope unless a task explicitly allows
them.
