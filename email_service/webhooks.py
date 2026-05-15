"""Webhook delivery for async send-result notifications.

Uses ``httpx`` (already required by the SDK extras) so we do not add a new
dependency. Retries with bounded backoff. HMAC-SHA256 signs the body when
a secret is provided so recipients can verify authenticity.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx

from email_service.metrics import email_webhook_failed_total

logger = logging.getLogger(__name__)


SIGNATURE_HEADER = "X-Email-Service-Signature"
DEFAULT_BACKOFFS: tuple[int, ...] = (1, 10, 60)
DEFAULT_MAX_RETRIES = 3


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def deliver_webhook(
    url: str,
    payload: dict[str, Any],
    secret: str | None,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoffs: tuple[int, ...] = DEFAULT_BACKOFFS,
    timeout: float = 10.0,
    client: httpx.Client | None = None,
) -> bool:
    """POST ``payload`` (JSON) to ``url`` with optional HMAC-SHA256 signature.

    Retries on non-2xx, timeout, and connection errors. Returns True on first
    successful 2xx response, False if all attempts exhaust.

    Webhook failures DO NOT affect the email send result — the email has
    already been sent by the time this is called.
    """
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if secret:
        headers[SIGNATURE_HEADER] = _sign(body, secret)

    message_id = payload.get("message_id")
    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=timeout)
    assert client is not None
    try:
        max_total = max(1, int(max_retries))
        for attempt in range(1, max_total + 1):
            try:
                resp = client.post(url, content=body, headers=headers)
                if 200 <= resp.status_code < 300:
                    logger.info(
                        "Webhook delivered",
                        extra={
                            "message_id": message_id,
                            "webhook_status": resp.status_code,
                            "attempts": attempt,
                        },
                    )
                    return True
                logger.warning(
                    "Webhook returned non-2xx",
                    extra={
                        "message_id": message_id,
                        "webhook_status": resp.status_code,
                        "attempts": attempt,
                    },
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                logger.warning(
                    "Webhook delivery error: %s",
                    type(exc).__name__,
                    extra={
                        "message_id": message_id,
                        "attempts": attempt,
                    },
                )
            if attempt < max_total:
                idx = min(attempt - 1, len(backoffs) - 1)
                time.sleep(backoffs[idx])
        # All attempts failed.
        email_webhook_failed_total.inc()
        logger.error(
            "Webhook delivery failed after %d attempts",
            max_total,
            extra={"message_id": message_id},
        )
        return False
    finally:
        if own_client:
            client.close()
