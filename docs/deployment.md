# Deployment

Production deployment guide for `authmail-relay`. Read [SECURITY.md](../SECURITY.md)
and the README "Security" section first.

## Production checklist

Before exposing `authmail-relay` to any production traffic:

- [ ] `API_KEY` generated with `openssl rand -hex 32` (or equivalent ≥256-bit
      randomness). No example/short strings.
- [ ] Service is **not** directly reachable from the public internet. It sits
      behind a reverse proxy or API gateway on a private network / VPC.
- [ ] TLS terminates at the edge proxy or gateway, not in uvicorn.
- [ ] Edge enforces a body-size limit (e.g. nginx `client_max_body_size 12m`).
- [ ] Edge / WAF rate-limits failed authentication attempts. The app's built-in
      per-bearer rate limit only protects *authenticated* `/send*` calls — it
      does not stop blind Bearer-token guessing.
- [ ] `/metrics` is either disabled at the edge or served with
      `METRICS_REQUIRE_AUTH=true`, and ideally scraped only from an internal
      network.
- [ ] `/docs` and `/openapi.json` are blocked at the edge if not needed in
      production.
- [ ] `SMTP_PASSWORD`, `API_KEY`, and `WEBHOOK_SECRET` come from a secret
      manager or out-of-band env injection — never committed.
- [ ] `EMAIL_SERVICE_DEBUG` is **off** in production. It enables `smtplib`
      debug output, which prints `AUTH PLAIN <base64>` (SMTP password in
      base64) to stderr.
- [ ] `WEBHOOK_ALLOW_LOOPBACK` is **off** in production (loopback/private
      destinations are a test-only convenience).
- [ ] Webhook receivers validate the `X-Email-Service-Signature-V2` header with
      a fresh timestamp window (≤5 min). The legacy V1 header is
      replay-vulnerable — see [webhooks.md](webhooks.md).

## Workers: single vs multi

Several pieces of state in `authmail-relay` are **in-memory, per-process**:

| State | Env var | Scope |
|---|---|---|
| Rate limit | `API_RATE_LIMIT_PER_MINUTE` | Per worker — total = N × cap |
| Idempotency cache | `API_IDEMPOTENCY_TTL_SECONDS` | Per worker — dedup breaks across workers |
| Per-key concurrency lock | (built-in) | Per worker — same key may run N-times concurrent across N workers |

Recommended patterns:

- **Single worker + sticky LB** — the simplest correct setup. Run
  `python -m authmail_relay` (workers=1) or pin all calls to one worker via a
  sticky load balancer. This is the design target.
- **Multi-worker** — only if exact rate-limit and idempotency semantics are
  *not* part of your SLA. A shared external store (Redis, etc.) is not
  currently supported.

## Body-size limit at the edge

Pydantic's `max_length` will return `422` for oversize bodies, but FastAPI
buffers the entire request body into memory before Pydantic runs. A 100 MB
request will be rejected, but only after memory is briefly consumed.

Enforce a hard cap at the proxy. nginx example:

```nginx
# /etc/nginx/sites-available/authmail-relay
location / {
    client_max_body_size 12m;   # 10 MB body + 2 MB headers/overhead
    proxy_pass http://authmail-relay:8000;
}
```

uvicorn has no equivalent flag — cap at the proxy.

## Docker

The provided `docker-compose.yml` publishes `8000:8000` on the host for
convenience. **Do not expose that port to the public internet.** Run on a
private network / VPC, behind a reverse proxy with TLS termination.

If only same-network containers should reach it, drop `ports:` and use
`expose: ["8000"]` so the host port stays closed.

The image runs as non-root uid `10001` (`app` user) on `python:3.12-slim`.

The provided Dockerfile is a simple example that does `pip install ".[http]"`.
For production, build with a pinned constraints / lockfile (`uv lock`,
`pip-compile`) so transitive dependencies cannot drift between builds.

## Release pipeline (PyPI)

`.github/workflows/release.yml` uses a **2-step manual gate**. A tag push alone
does not publish to PyPI:

1. **Tag push** → only the `build-and-smoke` job runs. It builds the wheel,
   does a smoke import, and verifies the tag matches `pyproject.toml` version.
   PyPI is not touched.
2. **Actions → `release` → "Run workflow"** (`workflow_dispatch`) with the tag
   (e.g. `v0.4.1`) as input. The dispatch itself is the human approval gate.
   `build-and-smoke` runs again, then `publish` uploads to PyPI.

Why the dispatch gate: on private repos, GitHub Environment "Required
reviewers" UI may not be available depending on plan, so the `environment: pypi`
gate alone cannot guarantee manual approval. Making `workflow_dispatch` the
trigger forces a human action. Required reviewers, where available, layer on
top.

- All GitHub Actions are pinned by commit SHA. Mutable tags are not used.
- A bad publish can only be yanked; the version number is permanently spent.
  See [`docs/runbooks/pypi-yank-hotfix.md`](runbooks/pypi-yank-hotfix.md).

## Runbooks

Operational procedures for common incidents:

- [public-deploy-readiness.md](runbooks/public-deploy-readiness.md)
- [smtp-outage.md](runbooks/smtp-outage.md)
- [smtp-disconnect-uncertain.md](runbooks/smtp-disconnect-uncertain.md)
- [webhook-outage.md](runbooks/webhook-outage.md)
- [api-key-rotation.md](runbooks/api-key-rotation.md)
- [pypi-yank-hotfix.md](runbooks/pypi-yank-hotfix.md)
