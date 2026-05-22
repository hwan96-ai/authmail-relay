# Auth-provider integration notes

`authmail-relay` is provider-agnostic: it sends auth emails through
your SMTP, but the auth provider (Supabase Auth, Auth.js, Keycloak,
etc.) remains the source of truth for users, tokens, sessions, and
identity. This page is an index of per-provider integration notes.

> authmail-relay is not an auth platform. It does not generate, store,
> verify, expire, or exchange OTP/session tokens, and it cannot
> satisfy `auth.uid()`-style RLS by itself. See each provider's notes
> for where the boundary lives.

## Provider notes

- **[Supabase Auth](supabase-auth.md)** — integration guidance for
  Supabase Auth (Send Email Hook / SMTP relay shapes, payload
  mapping, sample requests, and the responsibility boundary).

## Future / not yet documented

The following providers do not yet have dedicated integration notes
in this repo. Adding authmail-relay in front of them is typically a
matter of pointing their email delivery (SMTP relay or send-email
webhook) at authmail-relay. The same boundary rules apply:
authmail-relay only delivers the email — token generation,
verification, expiration, and session creation stay with the
provider.

- **Custom FastAPI auth** — applications that roll their own auth on
  top of FastAPI can call authmail-relay directly for magic-link, OTP,
  and password-reset delivery. The app owns the token lifecycle.
- **Auth.js (NextAuth)** — Auth.js exposes an email provider that
  invokes a `sendVerificationRequest` callback. That callback is the
  natural place to call authmail-relay. Auth.js still owns the
  verification token.
- **Keycloak** — Keycloak can be configured with an SMTP server. The
  SMTP host can point at a relay that forwards to authmail-relay, or
  at authmail-relay's SMTP-compatible front-end if one is configured
  in your deployment.
- **Ory (Kratos)** — Kratos uses Courier for email delivery and can
  be configured with SMTP. The same SMTP-relay pattern applies.
- **Auth0** — Auth0 supports a custom email provider hook. The hook
  is the integration point; Auth0 keeps owning the tokens.

These placeholders intentionally do not claim shipped integrations,
example code, or templates. They mark where future per-provider
documentation can land. Treat the descriptions above as the general
shape of an integration, not as a tested recipe.

See also [docs/alternatives.md](alternatives.md) for when to choose a
different tool entirely.
