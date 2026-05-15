"""CLI entrypoint: `python -m email_service [serve|test]`.

Two subcommands:

* ``serve`` (default if no subcommand) — boots the FastAPI app under uvicorn.
* ``test --to <addr>`` — uses ``_build_sender_from_env`` to construct an
  ``SmtpSender`` from environment variables and dispatches a one-shot test
  email. Prints the resulting :class:`SendResult` and exits 0 on success,
  1 otherwise. Useful for verifying SMTP credentials end-to-end before
  starting the server in front of a real workload.
"""
from __future__ import annotations

import argparse
import os
import sys


def _cmd_serve(_args: argparse.Namespace) -> int:
    # Import lazily so `test` does not require uvicorn/fastapi installed.
    import uvicorn

    from email_service.api import create_app

    app = create_app()
    uvicorn.run(
        app,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )
    return 0


def _cmd_test(args: argparse.Namespace) -> int:
    from email_service.api import _build_sender_from_env

    sender = _build_sender_from_env()
    result = sender.send(args.to, args.subject, args.html)
    print(result)
    return 0 if result.sent else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m email_service",
        description=(
            "Run the email-service HTTP API (`serve`, default) or fire a "
            "one-shot test email from environment variables (`test`)."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser(
        "serve",
        help="Run the FastAPI HTTP service via uvicorn (default).",
    )

    test = sub.add_parser(
        "test",
        help="Send a single test email using environment-configured SMTP.",
    )
    test.add_argument(
        "--to", required=True,
        help="Recipient email address.",
    )
    test.add_argument(
        "--subject",
        default="email-service test",
        help="Subject line (default: 'email-service test').",
    )
    test.add_argument(
        "--html",
        default="<p>Hello from <code>email-service</code>.</p>",
        help="HTML body (default: a short hello world).",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command in (None, "serve"):
        return _cmd_serve(args)
    if args.command == "test":
        return _cmd_test(args)
    parser.error(f"unknown command: {args.command}")
    return 2  # unreachable; parser.error exits


if __name__ == "__main__":
    sys.exit(main())
