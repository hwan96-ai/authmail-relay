"""Reusable SMTP email service with pluggable notifiers."""
from email_service.sender import SmtpSender
from email_service.notifiers import MagicLinkNotifier, OTPNotifier, TemplateNotifier

# Single source of truth for the package version. pyproject.toml's `version`
# field is authoritative — this module re-reads it at runtime via
# importlib.metadata. Fallback covers the "running from source without
# install" case (e.g. pytest in CI before `pip install -e .`).
try:
    from importlib.metadata import version as _pkg_version, PackageNotFoundError

    try:
        __version__ = _pkg_version("email-service")
    except PackageNotFoundError:
        __version__ = "0.0.0+dev"
except ImportError:  # pragma: no cover — Python < 3.8 never supported
    __version__ = "0.0.0+dev"

__all__ = [
    "SmtpSender",
    "MagicLinkNotifier",
    "OTPNotifier",
    "TemplateNotifier",
    "__version__",
]
