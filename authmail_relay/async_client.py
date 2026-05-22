"""Async HTTP client SDK for authmail-relay.

Mirrors the sync API in ``authmail_relay.client.EmailServiceClient`` but uses
``httpx.AsyncClient``. Use this from FastAPI / asyncio code paths.

Example:
    async with AsyncEmailServiceClient("http://authmail-relay:8000", api_key) as c:
        await c.send_otp("user@example.com", "홍길동", "482901")
"""
from __future__ import annotations

from typing import Any

import httpx

from authmail_relay.client import EmailServiceError


class AsyncEmailServiceClient:
    """Asynchronous client for the authmail-relay HTTP API.

    Re-raises :class:`EmailServiceError` on 502 responses, identical to the
    sync :class:`~authmail_relay.client.EmailServiceClient`. All other 4xx/5xx
    responses raise :class:`httpx.HTTPStatusError`.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 10.0,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        kwargs: dict[str, Any] = {
            "base_url": base_url.rstrip("/"),
            "headers": {"Authorization": f"Bearer {api_key}"},
            "timeout": timeout,
        }
        if transport is not None:
            kwargs["transport"] = transport
        self._client = httpx.AsyncClient(**kwargs)

    async def __aenter__(self) -> "AsyncEmailServiceClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        resp = await self._client.get("/health")
        resp.raise_for_status()
        return resp.json()

    async def send(
        self,
        to: str,
        subject: str,
        html_body: str,
        *,
        text_body: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        dry_run: bool = False,
        webhook_url: str | None = None,
        webhook_secret: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "to": to, "subject": subject, "html_body": html_body,
        }
        if text_body is not None:
            payload["text_body"] = text_body
        if cc is not None:
            payload["cc"] = cc
        if bcc is not None:
            payload["bcc"] = bcc
        if webhook_url is not None:
            payload["webhook_url"] = webhook_url
        if webhook_secret is not None:
            payload["webhook_secret"] = webhook_secret
        return await self._post("/send", payload, dry_run=dry_run)

    async def send_magic_link(
        self,
        to: str,
        user_name: str,
        token: str,
        *,
        dry_run: bool = False,
        webhook_url: str | None = None,
        webhook_secret: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "to": to, "user_name": user_name, "token": token,
        }
        if webhook_url is not None:
            payload["webhook_url"] = webhook_url
        if webhook_secret is not None:
            payload["webhook_secret"] = webhook_secret
        return await self._post("/send/magic-link", payload, dry_run=dry_run)

    async def send_otp(
        self,
        to: str,
        user_name: str,
        code: str,
        *,
        dry_run: bool = False,
        webhook_url: str | None = None,
        webhook_secret: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "to": to, "user_name": user_name, "code": code,
        }
        if webhook_url is not None:
            payload["webhook_url"] = webhook_url
        if webhook_secret is not None:
            payload["webhook_secret"] = webhook_secret
        return await self._post("/send/otp", payload, dry_run=dry_run)

    async def _post(
        self, path: str, payload: dict[str, Any], *, dry_run: bool
    ) -> dict[str, Any]:
        headers = {"X-Dry-Run": "true"} if dry_run else None
        resp = await self._client.post(path, json=payload, headers=headers)
        if resp.status_code == 502:
            try:
                body = resp.json()
            except Exception:
                body = {}
            detail = body.get("detail", body) if isinstance(body, dict) else {}
            if not isinstance(detail, dict):
                detail = {}
            raise EmailServiceError(
                error_code=detail.get("error_code"),
                message=detail.get("message"),
                status_code=502,
            )
        resp.raise_for_status()
        return resp.json()
