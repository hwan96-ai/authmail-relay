# Project Overview

## When to use this

Use this document when an agent needs a quick understanding of the product,
its boundaries, and the risk model before changing code or documentation.

## What this repository is

`authmail-relay` is a Python package and optional HTTP service for sending
auth-related email through an existing SMTP provider. The README describes it
as a self-hosted SMTP relay for magic-link, OTP, password-reset, and templated
transactional email.

The project supports two usage modes:

- Library mode through `authmail_relay.SmtpSender` and notifier classes.
- HTTP service mode through FastAPI, started with `python -m authmail_relay`.

The package name, PyPI distribution, and import package are aligned as:

- Repository/service: `authmail-relay`
- Distribution: `authmail-relay`
- Import package: `authmail_relay`

A legacy `email_service` compatibility shim remains for older imports and emits
a deprecation warning according to the README and tests.

## What this repository is not

Repository docs explicitly state that this project is not a mail server, not a
full auth platform, not a marketing or bulk-email platform, and not a managed
email-provider replacement. The caller or upstream auth provider owns token
generation, storage, expiration, replay protection, sessions, and user state.

## Core architecture

The main package is `authmail_relay/`.

- `api.py` builds the FastAPI application, request models, authentication,
  rate limiting, idempotency, health, metrics, and send endpoints.
- `sender.py` builds MIME messages and sends them through SMTP, including
  structured send results and retry behavior.
- `notifiers.py` contains magic-link, OTP, template, and custom notifier
  helpers.
- `client.py` and `async_client.py` provide sync and async HTTP client SDKs
  using `httpx`.
- `webhooks.py` delivers async send-result callbacks and signs webhook payloads.
- `url_validation.py` protects webhook destinations.
- `logging_config.py` configures optional JSON logging and hashes recipients.
- `metrics.py` exposes optional Prometheus metrics.
- `__main__.py` provides the CLI entry point for `serve` and `test`.

## Operational stance

The service is designed as an internal gateway. Existing deployment docs say
it should sit behind a reverse proxy or API gateway on a private network or
VPC, with TLS termination, edge rate limiting, body-size limits, protected
metrics/docs, and secret-manager or environment-based secrets.

Agents must preserve that internal-service assumption unless repository
evidence and an explicit user request say otherwise.
