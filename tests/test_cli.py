"""Tests for the `python -m authmail_relay` CLI."""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(*args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    import os
    env = os.environ.copy()
    # Force module discovery from this checkout.
    env["PYTHONPATH"] = str(REPO_ROOT)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "authmail_relay", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestCLIHelp:
    def test_test_help_exits_zero(self):
        result = _run("test", "--help")
        assert result.returncode == 0, result.stderr
        assert "--to" in result.stdout
        # Usage text should reference the test subcommand.
        assert "test" in result.stdout.lower()

    def test_top_level_help_exits_zero(self):
        result = _run("--help")
        assert result.returncode == 0, result.stderr
        # Should advertise both subcommands.
        assert "serve" in result.stdout
        assert "test" in result.stdout

    def test_test_missing_to_errors(self):
        # argparse exits 2 on missing required arg.
        result = _run("test")
        assert result.returncode == 2
        assert "--to" in result.stderr


class TestCLITestCommand:
    def test_failing_send_exits_1(self, tmp_path):
        # Point at a bogus SMTP host so the send fails fast; exit code should
        # be 1 and the printed SendResult should carry an error_code.
        env_extra = {
            "SMTP_HOST": "127.0.0.1",
            "SMTP_PORT": "1",  # nothing listens here
            "SMTP_USER": "",
            "SMTP_PASSWORD": "",
            "SMTP_USE_TLS": "false",
            "SMTP_FROM": "from@example.com",
            # API_KEY is not required for the `test` subcommand path.
        }
        result = _run("test", "--to", "to@example.com", env_extra=env_extra)
        assert result.returncode == 1
        # The SendResult repr must mention sent=False and an error code.
        assert "sent=False" in result.stdout
        assert "error_code=" in result.stdout
