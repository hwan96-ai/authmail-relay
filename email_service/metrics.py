"""Optional Prometheus metrics. Loaded only when METRICS_ENABLED=true.

The package must remain importable without ``prometheus-client`` installed,
so we always provide a no-op fallback when the dependency or the env-var
opt-in is missing.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

try:
    from prometheus_client import (  # type: ignore[import-not-found]
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )
    _AVAILABLE = True
except ImportError:  # pragma: no cover - depends on optional dep
    _AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

    def generate_latest() -> bytes:  # type: ignore[misc]
        return b""


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"true", "1", "yes"}


METRICS_ENABLED = _truthy(os.environ.get("METRICS_ENABLED"))


class _NoOpMetric:
    """No-op stub so call sites never have to branch on availability."""

    def labels(self, **_kwargs):  # noqa: D401 - signature matches prom client
        return self

    def inc(self, *_args, **_kwargs):
        return None

    def dec(self, *_args, **_kwargs):
        return None

    def set(self, *_args, **_kwargs):
        return None

    def observe(self, *_args, **_kwargs):
        return None

    @contextmanager
    def time(self):
        yield

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def track_inprogress(self):
        return self


if _AVAILABLE and METRICS_ENABLED:
    email_send_total = Counter(
        "email_send_total",
        "Total email send attempts",
        ["result", "error_code"],
    )
    email_send_duration_seconds = Histogram(
        "email_send_duration_seconds",
        "SMTP send duration in seconds",
    )
    email_send_active = Gauge(
        "email_send_active",
        "Emails currently being sent",
    )
    email_retry_attempts_total = Counter(
        "email_retry_attempts_total",
        "Total SMTP send retry attempts",
        ["reason"],
    )
    email_webhook_failed_total = Counter(
        "email_webhook_failed_total",
        "Total webhook deliveries that exhausted retries",
    )
else:
    email_send_total = _NoOpMetric()  # type: ignore[assignment]
    email_send_duration_seconds = _NoOpMetric()  # type: ignore[assignment]
    email_send_active = _NoOpMetric()  # type: ignore[assignment]
    email_retry_attempts_total = _NoOpMetric()  # type: ignore[assignment]
    email_webhook_failed_total = _NoOpMetric()  # type: ignore[assignment]


def metrics_available() -> bool:
    """Whether prometheus-client is importable AND METRICS_ENABLED=true."""
    return _AVAILABLE and METRICS_ENABLED


def render_latest() -> tuple[bytes, str]:
    """Return ``(body, content_type)`` suitable for an HTTP response."""
    return generate_latest(), CONTENT_TYPE_LATEST
