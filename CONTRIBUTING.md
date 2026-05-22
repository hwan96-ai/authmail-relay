# Contributing to authmail-relay

Thanks for your interest in contributing! This guide gets you from a fresh
clone to a passing test suite and a clean PR.

## Dev setup

```bash
git clone https://github.com/hwan96-ai/authmail-relay.git
cd authmail-relay
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev,http]"
```

Optional: run a local SMTP catcher (Mailpit / MailHog) for manual integration
testing.

```bash
docker compose -f docker-compose.dev.yml up -d
```

## Running tests

```bash
pytest tests/ -q
```

Run a single file or test:

```bash
pytest tests/test_authmail_relay.py::TestMagicLinkNotifier -q
```

All PRs must keep the full suite green. Add tests for new behavior; prefer
semantic assertions over exact-string HTML matches so cosmetic template
changes don't churn tests.

## Commit conventions

Follow Conventional Commits style:

- `feat: add async client`
- `fix: escape CRLF in subject header`
- `docs: clarify TemplateNotifier docstring`
- `test: cover dark-mode CSS in template`
- `refactor: extract _build_message helper`
- `chore: bump version to 0.3.0`

Keep commits small and focused. One logical change per commit.

## PR checklist

Before opening a PR:

- [ ] `pytest tests/ -q` is green locally
- [ ] New behavior has a test
- [ ] Public API changes are reflected in README + CHANGELOG
- [ ] No secrets, API keys, or real SMTP credentials in diffs or fixtures
- [ ] Docstrings updated for any new/changed function signatures
- [ ] If touching HTML templates: tests assert on semantics (href, escaped
      values, plain-text part), not exact-string equality

## Code style

- Python 3.10+ syntax (`str | None`, PEP 604 unions)
- Type hints on all public function signatures
- `html.escape` for all user-supplied data rendered into HTML
- No new runtime dependencies in the core library (`authmail_relay.sender`,
  `authmail_relay.notifiers`) — HTTP and metrics deps live behind the
  `[http]` extra

## Reporting bugs / requesting features

Use the GitHub issue templates in `.github/ISSUE_TEMPLATE/`. Include
reproducible steps and the expected vs. actual behavior.
