"""Tests for the legacy ``email_service`` backward-compatibility shim.

``email_service`` is a thin re-export of :mod:`authmail_relay` that exists
only to keep pre-rename imports working. These tests verify it emits a
:class:`DeprecationWarning` and that the public top-level names and
submodule aliases still resolve to the new package.
"""
from __future__ import annotations

import importlib
import sys
import warnings


def _drop_cached_shim() -> None:
    """Clear ``email_service*`` from ``sys.modules`` so reimport runs fresh."""
    for key in list(sys.modules):
        if key == "email_service" or key.startswith("email_service."):
            del sys.modules[key]


def test_legacy_import_emits_deprecation_warning():
    _drop_cached_shim()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        import email_service  # noqa: F401  (import-for-side-effect is the test)

    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deprecations, "expected at least one DeprecationWarning on legacy import"
    assert any("authmail_relay" in str(w.message) for w in deprecations)


def test_legacy_top_level_names_match_new_package():
    _drop_cached_shim()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        import authmail_relay
        import email_service

    assert email_service.__version__ == authmail_relay.__version__
    assert email_service.SmtpSender is authmail_relay.SmtpSender
    assert email_service.MagicLinkNotifier is authmail_relay.MagicLinkNotifier
    assert email_service.OTPNotifier is authmail_relay.OTPNotifier
    assert email_service.TemplateNotifier is authmail_relay.TemplateNotifier


def test_legacy_submodule_imports_resolve_to_new_package():
    _drop_cached_shim()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        importlib.import_module("email_service")
        legacy_sender = importlib.import_module("email_service.sender")
        new_sender = importlib.import_module("authmail_relay.sender")

    assert legacy_sender is new_sender
