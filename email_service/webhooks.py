"""Webhook delivery for async send-result notifications.

Uses ``httpx`` (already required by the SDK extras) so we do not add a new
dependency. Retries with bounded backoff. HMAC-SHA256 signs the body when
a secret is provided so recipients can verify authenticity.

# Replay-attack defense (V2 signature)

In addition to the legacy ``X-Email-Service-Signature`` header (sha256 of the
body bytes only), this module emits ``X-Email-Service-Signature-V2`` which
covers ``"<timestamp>.<body>"`` and an ``X-Email-Service-Timestamp`` header
(integer Unix-epoch seconds).

**Recipients SHOULD migrate to V2:**

1. Read the ``X-Email-Service-Timestamp`` header.
2. Reject if abs(now - timestamp) > 5 minutes (anti-replay window).
3. Compute ``hmac_sha256(secret, f"{timestamp}.{body}")`` and compare
   constant-time with the V2 header digest.

V1 (body-only) remains for backward compatibility but is vulnerable to
indefinite replay if captured. Plan to remove V1 in a future major version.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import random
import time
from typing import Any

import httpx

from email_service.metrics import email_webhook_failed_total
from email_service.url_validation import validate_webhook_url

logger = logging.getLogger(__name__)


SIGNATURE_HEADER = "X-Email-Service-Signature"
SIGNATURE_HEADER_V2 = "X-Email-Service-Signature-V2"
TIMESTAMP_HEADER = "X-Email-Service-Timestamp"
# P0-1 (threadpool starvation): bounded total sleep budget. Previous
# (1, 10, 60) summed to 71s while running on a sync BackgroundTask, which
# pinned a starlette threadpool worker per retry. Sum now ≤ 8s before jitter.
DEFAULT_BACKOFFS: tuple[float, ...] = (1.0, 2.0, 5.0)
DEFAULT_MAX_RETRIES = 3
# ±25% jitter to avoid thundering herd against a shared webhook target.
_JITTER_RATIO = 0.25


def _jittered(delay: float) -> float:
    if delay <= 0:
        return 0.0
    spread = delay * _JITTER_RATIO
    return max(0.0, delay + random.uniform(-spread, spread))


def _sign(body: bytes, secret: str) -> str:
    """V1: signature over body only. Vulnerable to replay if captured."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _sign_v2(timestamp: str, body: bytes, secret: str) -> str:
    """V2: signature over ``"<timestamp>.<body>"`` bytes — anti-replay."""
    payload = timestamp.encode("ascii") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def deliver_webhook(
    url: str,
    payload: dict[str, Any],
    secret: str | None,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoffs: tuple[float, ...] = DEFAULT_BACKOFFS,
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
    # P1 webhook HMAC replay: emit a server-side timestamp and a V2 signature
    # covering "<timestamp>.<body>" so receivers can enforce a freshness
    # window and reject replays.
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        TIMESTAMP_HEADER: timestamp,
    }
    if secret:
        headers[SIGNATURE_HEADER] = _sign(body, secret)
        headers[SIGNATURE_HEADER_V2] = _sign_v2(timestamp, body, secret)

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
                time.sleep(_jittered(float(backoffs[idx])))
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
