# Security and Secrets

## When to use this

Use this document for any work touching configuration, deployment,
observability, webhooks, auth-email flows, examples, logs, or public-facing
documentation.

## Data that must not be exposed

Agents must not expose:

- SMTP credentials.
- API keys.
- Auth secrets.
- Relay tokens.
- Production endpoints.
- Private email addresses.
- Logs.
- Message contents.

This applies to code comments, docs, examples, shell output, commits, issue
text, PR descriptions, screenshots, and final responses.

## Repository security model

Repository docs describe `authmail-relay` as an internal service. It should not
be directly exposed to the public internet. Deployments should use a reverse
proxy or API gateway, private network placement, TLS termination, failed-auth
rate limits at the edge, body-size limits at the edge, and protected `/docs`,
`/openapi.json`, and `/metrics` access.

The service sends auth emails but does not generate, store, verify, or expire
login tokens. Callers or auth providers own token entropy, expiration,
single-use enforcement, replay protection, sessions, and account-state checks.

## Secret handling

Required HTTP-mode environment variables include `SMTP_HOST` and `API_KEY`.
SMTP credentials can be provided with `SMTP_USER`, `SMTP_PASSWORD`, and
`SMTP_FROM`. Webhooks can use `WEBHOOK_SECRET`.

Do not commit `.env` files or secret values. Use placeholders in documentation.
Generate examples with fake values only.

The existing docs warn that `EMAIL_SERVICE_DEBUG` enables `smtplib` debug
output that can print SMTP authentication material to stderr. Never enable it
in production and never include that output in public artifacts.

## Logs and observability

The logging code hashes recipient addresses before adding them to structured
log metadata. Preserve PII-safe logging behavior. Do not replace hashed
recipient identifiers with plaintext addresses in logs or docs.

Metrics and health checks should not reveal message content, private recipient
addresses, credentials, or production topology.

## Webhook safety

Webhook handling includes URL validation, SSRF defenses, retries, and HMAC
signatures. Preserve replay-resistant V2 signature guidance and timestamp
validation when editing webhook docs or code.
