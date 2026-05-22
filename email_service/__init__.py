"""Backward-compatibility shim for the renamed ``authmail_relay`` package.

``email_service`` was the previous import name of this project (distributed on
PyPI as ``hwan-email-service``). It has been renamed to ``authmail_relay``
(distributed as ``authmail-relay``). This shim re-exports the new package so
existing ``from email_service ... import ...`` and ``import email_service``
statements keep working, while emitting a :class:`DeprecationWarning` to nudge
users toward the new name.

This module is intentionally thin: it forwards attribute access to
:mod:`authmail_relay` and registers submodule aliases (``email_service.api``
maps to ``authmail_relay.api``, etc.) so existing import paths continue to
resolve. Remove this shim in a future major release.
"""
from __future__ import annotations

import sys
import warnings

import authmail_relay as _authmail_relay

warnings.warn(
    "The `email_service` import package has been renamed to `authmail_relay` "
    "(PyPI: `authmail-relay`). Update your imports: "
    "`from email_service import X` -> `from authmail_relay import X`. "
    "This compatibility shim will be removed in a future major release.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export top-level attributes (SmtpSender, notifiers, __version__, ...).
__version__ = _authmail_relay.__version__
__all__ = list(getattr(_authmail_relay, "__all__", []))
for _name in __all__:
    globals()[_name] = getattr(_authmail_relay, _name)

# Register submodule aliases so `from email_service.api import X` works
# without forcing every consumer to immediately rewrite imports. Importing a
# submodule via the new name once is enough — Python caches it in sys.modules
# and we mirror it under the legacy ``email_service.<name>`` key.
_SUBMODULES = (
    "api",
    "async_client",
    "client",
    "logging_config",
    "metrics",
    "notifiers",
    "sender",
    "url_validation",
    "webhooks",
)
for _sub in _SUBMODULES:
    _full = f"authmail_relay.{_sub}"
    try:
        __import__(_full)
    except ImportError:
        # Optional dependencies (fastapi, httpx, ...) may be missing in some
        # environments; let the real ImportError surface when the consumer
        # actually touches that submodule.
        continue
    sys.modules[f"email_service.{_sub}"] = sys.modules[_full]

del _name, _sub, _full, _SUBMODULES
