"""authmail-relay: self-hosted SMTP relay for auth emails."""
from authmail_relay.sender import SmtpSender
from authmail_relay.notifiers import MagicLinkNotifier, OTPNotifier, TemplateNotifier

# Single source of truth for the package version. pyproject.toml's `version`
# field is authoritative — this module re-reads it at runtime via
# importlib.metadata. Fallback covers the "running from source without
# install" case (e.g. pytest in CI before `pip install -e .`).
try:
    from importlib.metadata import version as _pkg_version, PackageNotFoundError

    try:
        __version__ = _pkg_version("authmail-relay")
    except PackageNotFoundError:
        try:
            # Migration fallback: pre-rename installs published the same code
            # as `hwan-email-service`. Honor that metadata if the new
            # distribution is not yet installed.
            __version__ = _pkg_version("hwan-email-service")
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
