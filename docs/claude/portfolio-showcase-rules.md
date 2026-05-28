# Portfolio Showcase Rules

## When to use this

Use this document for any request involving public release, portfolio display,
demo extraction, screenshots, code samples, blog posts, case studies, or
showcase repositories.

## Required approach

Future public portfolio or showcase extraction must happen in a separate
sanitized repository. Do not make this original repository public as the
showcase path.

The sanitized repository should contain only reviewed, intentionally public
material. It must not include real secrets, private operational history,
production endpoints, private email addresses, logs, message contents, or
deployment details that reveal sensitive infrastructure.

## What not to do

Do not perform public-release cleanup in this original repository unless the
user gives an explicit task for that exact scope. Do not broaden a harness,
documentation, or internal-maintenance task into public-release work.

Do not create a public showcase repository unless the user explicitly asks for
that task. If asked, treat it as a separate project with a sanitization review.

## Safe showcase material

Use placeholders and high-level architecture where possible. Prefer describing
the project as a self-hosted auth-email SMTP relay without showing private
deployment details, logs, real email addresses, or live infrastructure.

Any sample requests should use reserved examples such as `user@example.com`,
`https://example.com`, and placeholder tokens rather than real values.
