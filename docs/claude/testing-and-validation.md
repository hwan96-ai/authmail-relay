# Testing and Validation

## When to use this

Use this document when selecting checks before handing work back, especially
when deciding whether docs-only validation is enough or product tests are
required.

## Product test suite

Repository docs identify pytest as the test runner:

```bash
python -m pytest tests/ -v
```

The README says tests do not connect to a real SMTP server because `smtplib.SMTP`
is mocked. The suite covers:

- FastAPI endpoint behavior and OpenAPI metadata.
- SMTP sender behavior and structured error codes.
- Sync and async `httpx` client SDK behavior.
- CLI behavior.
- Observability, metrics, request IDs, logging, and PII-safe recipient hashes.
- Webhook signing, retry behavior, and URL validation.
- Idempotency, rate limiting, size limits, and security fixes.
- Legacy `email_service` shim compatibility.

Run the product test suite when product code, API behavior, package metadata,
or test fixtures change.

## Lightweight documentation validation

For documentation-only harness changes, run at minimum:

```bash
git diff --check
git diff --name-only
```

Then verify changed paths are within the allowed documentation scope for the
task. Review the diff before staging.

Useful docs checks:

```bash
rg "\]\([^)]+\)" AGENTS.md CLAUDE.md docs/claude
rg "When to use this" docs/claude
```

The first command helps inspect relative links. The second confirms every
`docs/claude` child document includes the required section.

## Secrets-aware validation

Do not paste real secrets, private email addresses, production URLs, logs, or
message bodies into test commands, docs, commits, PR descriptions, or final
status reports.

If validation requires environment variables, use placeholders in written
instructions and ask the user before executing commands against any real SMTP
provider or production endpoint.
