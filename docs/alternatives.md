# Alternatives & positioning

`email-service` is small on purpose. Other categories of tool exist for
different problems — pick the one that matches your real constraint.

## Managed email providers

[Resend](https://resend.com), [Postmark](https://postmarkapp.com),
[SendGrid](https://sendgrid.com), [Mailgun](https://www.mailgun.com),
[Amazon SES](https://aws.amazon.com/ses/).

**Use these if you need:** managed deliverability, IP reputation, suppression
lists, bounce/complaint processing, analytics dashboards, vendor support, or
contractual SLAs.

`email-service` does **not** replace these. It is a thin self-hosted gateway
in front of an SMTP account — including, optionally, an SMTP relay provided
by one of these vendors.

## Self-hosted email platforms

[Postal](https://postalserver.io), [Plunk](https://www.useplunk.com),
[MailWhale](https://mailwhale.dev), [HYVOR Relay](https://hyvor.com/relay/),
[listmonk](https://listmonk.app) (newsletter-focused).

**Use these if you need:** to run your own outbound mail platform with
per-tenant API keys, queues, dashboards, deliverability tooling, or list
management.

`email-service` is much smaller. It targets the narrow "send a magic link /
OTP / password-reset" use case for an internal app.

## Full auth platforms

[Supabase Auth](https://supabase.com/auth),
[Ory Kratos](https://www.ory.sh/kratos/),
[Keycloak](https://www.keycloak.org),
[Authentik](https://goauthentik.io),
[Appwrite](https://appwrite.io).

**Use these if you need:** user records, sessions, social login, RBAC,
password hashing, account verification and recovery flows, MFA, or any
identity primitives.

`email-service` does **not** implement any of that. It sends the email; it
does not generate, store, verify, or expire tokens. The caller stays
responsible for entropy, lifecycle, and replay protection.

## Python / FastAPI libraries

[fastapi-mail](https://github.com/sabuhish/fastapi-mail).

**Use it if:** you just want an email-sending library inside one FastAPI app
and don't need a separate service.

`email-service` overlaps with this in library mode, but the value-add is the
HTTP service mode that lets multiple apps share one SMTP credential set.

## When `email-service` is the right tool

- You already have an SMTP account and want to keep using it.
- You have one or more internal apps that need to send transactional auth
  email (magic link, OTP, password reset, generic templates).
- You want SMTP credentials and email-template logic in one place, not copied
  into every app.
- You are comfortable running a small Python service behind a reverse proxy.
- You don't need analytics dashboards, suppression lists, or a contractual
  deliverability SLA.

If any of those don't fit, one of the alternatives above is probably the
better answer.
