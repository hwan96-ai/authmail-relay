"""Optional JSON logging. Activated when EMAIL_SERVICE_LOG_FORMAT=json.

Always safe to call ``configure_logging()`` — if ``python-json-logger`` is
not installed, the configuration silently falls back to the default text
format (a warning is emitted to the root logger).
"""
from __future__ import annotations

import hashlib
import logging
import os


def configure_logging() -> None:
    fmt = os.environ.get("EMAIL_SERVICE_LOG_FORMAT", "text").lower()
    if fmt != "json":
        return
    try:
        # pythonjsonlogger >= 3.x exposes the formatter under `.json`.
        from pythonjsonlogger.json import JsonFormatter  # type: ignore[import-not-found]
    except ImportError:
        try:
            from pythonjsonlogger import jsonlogger  # type: ignore[import-not-found]
            JsonFormatter = jsonlogger.JsonFormatter
        except ImportError:
            logging.getLogger(__name__).warning(
                "EMAIL_SERVICE_LOG_FORMAT=json but python-json-logger is not "
                "installed; falling back to text logging."
            )
            return
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


def hash_recipient(addr: str) -> str:
    """PII-safe recipient identifier for logs/metrics (8-char SHA-256 prefix)."""
    return hashlib.sha256(addr.encode("utf-8")).hexdigest()[:8]
