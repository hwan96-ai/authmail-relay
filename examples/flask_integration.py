"""Flask integration example: send a magic-link on signup.

Run:
    pip install flask email-service
    SMTP_HOST=localhost SMTP_PORT=1025 python examples/flask_integration.py

The MagicLinkNotifier is constructed once at app startup and reused per request.
"""
from __future__ import annotations

import os
import secrets

try:
    from flask import Flask, jsonify, request
except ImportError:  # pragma: no cover
    raise SystemExit(
        "Flask is not installed. Install it with `pip install flask` to run this example."
    )

from email_service.notifiers import MagicLinkNotifier
from email_service.sender import SmtpConfig, SmtpSender


def build_notifier() -> MagicLinkNotifier:
    sender = SmtpSender(SmtpConfig(
        host=os.environ.get("SMTP_HOST", "localhost"),
        port=int(os.environ.get("SMTP_PORT", "1025")),
        user=os.environ.get("SMTP_USER", ""),
        password=os.environ.get("SMTP_PASSWORD", ""),
        use_tls=os.environ.get("SMTP_USE_TLS", "false").lower() == "true",
    ))
    return MagicLinkNotifier(
        sender,
        base_url=os.environ.get("APP_BASE_URL", "http://localhost:5000"),
        subject_prefix="[MyApp] ",
    )


app = Flask(__name__)
notifier = build_notifier()


@app.post("/signup")
def signup():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    name = data.get("name", "사용자")
    if not email:
        return jsonify({"error": "email required"}), 400

    # In production, persist the token alongside the user with an expiry.
    token = secrets.token_urlsafe(32)
    result = notifier.send(email, name, token)
    if not result.sent:
        return jsonify({
            "error": "email_failed",
            "error_code": result.error_code,
        }), 502
    return jsonify({"status": "magic_link_sent"})


if __name__ == "__main__":
    app.run(debug=True)
