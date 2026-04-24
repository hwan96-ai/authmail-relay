"""HTTP client SDK for email-service.

Thin wrapper around httpx that sets the Bearer auth header, translates
``dry_run=True`` into the ``X-Dry-Run: true`` header, and raises on 4xx/5xx
via ``Response.raise_for_status``.
"""
from __future__ import annotations

from typing import Any

import httpx


class EmailServiceClient:
    """Synchronous client for the email-service HTTP API.

    Example:
        with EmailServiceClient("http://email-service:8000", api_key) as c:
            c.send_otp("user@example.com", "홍길동", "482901")
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 10.0,
        *,
        transport: httpx.BaseTransport | None = None,
    ):
        kwargs: dict[str, Any] = {
            "base_url": base_url.rstrip("/"),
            "headers": {"Authorization": f"Bearer {api_key}"},
            "timeout": timeout,
        }
        if transport is not None:
            kwargs["transport"] = transport
        self._client = httpx.Client(**kwargs)

    def __enter__(self) -> "EmailServiceClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def health(self) -> dict[str, Any]:
        resp = self._client.get("/health")
        resp.raise_for_status()
        return resp.json()

    def send(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "to": to,
            "subject": subject,
            "html_body": html_body,
        }
        if text_body is not None:
            payload["text_body"] = text_body
        if cc is not None:
            payload["cc"] = cc
        if bcc is not None:
            payload["bcc"] = bcc
        return self._post("/send", payload, dry_run=dry_run)

    def send_magic_link(
        self,
        to: str,
        user_name: str,
        token: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self._post(
            "/send/magic-link",
            {"to": to, "user_name": user_name, "token": token},
            dry_run=dry_run,
        )

    def send_otp(
        self,
        to: str,
        user_name: str,
        code: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self._post(
            "/send/otp",
            {"to": to, "user_name": user_name, "code": code},
            dry_run=dry_run,
        )

    def _post(
        self, path: str, payload: dict[str, Any], *, dry_run: bool
    ) -> dict[str, Any]:
        headers = {"X-Dry-Run": "true"} if dry_run else None
        resp = self._client.post(path, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()
