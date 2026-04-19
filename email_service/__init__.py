"""Reusable SMTP email service with pluggable notifiers."""
from email_service.sender import SmtpSender
from email_service.notifiers import MagicLinkNotifier, OTPNotifier, TemplateNotifier

__all__ = ["SmtpSender", "MagicLinkNotifier", "OTPNotifier", "TemplateNotifier"]
