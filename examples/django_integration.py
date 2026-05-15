"""Django integration example: send a welcome email via signal.

This example wires a post_save signal on the Django ``User`` model to
``SmtpSender`` directly (no HTTP service), suitable for monolith deployments
that import email_service as a library.

Drop this into one of your app's ``signals.py`` and ensure it is imported in
the AppConfig.ready() hook. Don't actually run this file standalone.
"""
from __future__ import annotations

import os

try:
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.db.models.signals import post_save
    from django.dispatch import receiver
except ImportError:  # pragma: no cover
    raise SystemExit(
        "Django is not installed. Install with `pip install django` to use this example."
    )

from email_service.notifiers import TemplateNotifier
from email_service.sender import SmtpConfig, SmtpSender


def _build_notifier() -> TemplateNotifier:
    sender = SmtpSender(SmtpConfig(
        host=os.environ.get("SMTP_HOST", "localhost"),
        port=int(os.environ.get("SMTP_PORT", "1025")),
        user=os.environ.get("SMTP_USER", ""),
        password=os.environ.get("SMTP_PASSWORD", ""),
        use_tls=os.environ.get("SMTP_USE_TLS", "false").lower() == "true",
        from_addr=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
    ))
    return TemplateNotifier(
        sender,
        subject="Welcome, {name}!",
        html_template="<h1>Welcome {name}</h1><p>Thanks for joining.</p>",
        text_template="Welcome {name}\n\nThanks for joining.",
    )


_notifier = _build_notifier()
User = get_user_model()


@receiver(post_save, sender=User)
def send_welcome_email(sender, instance, created, **kwargs):
    if not created:
        return
    if not instance.email:
        return
    # In production, push this to a Celery/RQ worker so save() stays fast.
    _notifier.send(
        instance.email,
        name=instance.get_full_name() or instance.username,
    )
