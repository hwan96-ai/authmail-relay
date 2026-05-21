# Security Policy

## Supported versions

Security fixes target the latest released version of `hwan-email-service` on PyPI
and the corresponding `master` branch. Older versions are not patched.

## Reporting a vulnerability

Please **do not open a public GitHub issue** for security-sensitive findings.

Report vulnerabilities privately via GitHub's
[Private Vulnerability Reporting](https://github.com/hwan96-ai/email-service/security/advisories/new)
for this repository. This routes the report directly to the maintainers and
keeps exploit details out of public view until a fix is ready.

If for any reason private reporting is unavailable, open a minimal public issue
that asks for a private maintainer contact channel — but do **not** include
exploit details, secrets, proof-of-concept payloads, production URLs, or
affected deployment specifics in that issue.

### What to include in a private report

- Affected version or commit SHA
- Deployment mode (library, HTTP service, Docker)
- Impact and any attack preconditions (network position, prior auth, etc.)
- Minimal reproduction steps or proof-of-concept
- Whether SMTP credentials, API keys, or webhook receivers could be exposed

## Disclosure expectations

- Maintainers aim to acknowledge valid private reports within **7 days**.
- We coordinate a fix or mitigation with the reporter before public disclosure.
- We ask reporters to give us a reasonable window (typically 30–90 days
  depending on severity) before publishing details.

Out-of-scope: theoretical issues without a reproducible impact, social
engineering of maintainers, and findings against deployments you do not own.
