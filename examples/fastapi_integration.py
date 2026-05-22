"""FastAPI integration example: call the authmail-relay HTTP API.

Use the async client when calling authmail-relay from a FastAPI endpoint so the
event loop is never blocked on SMTP.

Run:
    pip install fastapi uvicorn "authmail-relay[http]"
    EMAIL_SERVICE_URL=http://localhost:8000 EMAIL_SERVICE_API_KEY=key \\
        uvicorn examples.fastapi_integration:app --reload
"""
from __future__ import annotations

import os

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
except ImportError:  # pragma: no cover
    raise SystemExit(
        "FastAPI is not installed. Install with `pip install fastapi uvicorn`."
    )

from authmail_relay.async_client import AsyncEmailServiceClient
from authmail_relay.client import EmailServiceError


EMAIL_SERVICE_URL = os.environ.get("EMAIL_SERVICE_URL", "http://localhost:8000")
EMAIL_SERVICE_API_KEY = os.environ.get("EMAIL_SERVICE_API_KEY", "")


class SignupRequest(BaseModel):
    email: str
    name: str
    token: str


app = FastAPI()
# Shared client across requests — reuses the underlying httpx connection pool.
client = AsyncEmailServiceClient(EMAIL_SERVICE_URL, EMAIL_SERVICE_API_KEY)


@app.on_event("shutdown")
async def _shutdown():
    await client.aclose()


@app.post("/signup")
async def signup(req: SignupRequest):
    try:
        result = await client.send_magic_link(req.email, req.name, req.token)
    except EmailServiceError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error_code": exc.error_code, "message": exc.message},
        )
    return {"status": "queued", "message_id": result.get("message_id")}
