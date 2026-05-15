"""HTTP API wrapping email_service for service-to-service email sending."""
from __future__ import annotations

import hmac
import logging
import os

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator

from email_service.notifiers import MagicLinkNotifier, OTPNotifier
from email_service.sender import SmtpConfig, SmtpSender

logger = logging.getLogger(__name__)


def _required_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Required environment variable missing: {name}")
    return val


def _no_crlf(value: str) -> str:
    if "\r" in value or "\n" in value:
        raise ValueError("CRLF characters are not allowed")
    return value


class SendEmailRequest(BaseModel):
    to: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    html_body: str = Field(min_length=1)
    text_body: str | None = None
    cc: list[str] | None = None
    bcc: list[str] | None = None

    @field_validator("to", "subject")
    @classmethod
    def _reject_crlf(cls, v: str) -> str:
        return _no_crlf(v)

    @field_validator("cc", "bcc")
    @classmethod
    def _reject_crlf_list(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        for item in v:
            _no_crlf(item)
        return v


class SendMagicLinkRequest(BaseModel):
    to: str = Field(min_length=1)
    user_name: str = Field(min_length=1)
    token: str = Field(min_length=1)

    @field_validator("to")
    @classmethod
    def _reject_crlf(cls, v: str) -> str:
        return _no_crlf(v)


class SendOTPRequest(BaseModel):
    to: str = Field(min_length=1)
    user_name: str = Field(min_length=1)
    code: str = Field(min_length=1)

    @field_validator("to")
    @classmethod
    def _reject_crlf(cls, v: str) -> str:
        return _no_crlf(v)


class SendResult(BaseModel):
    sent: bool
    dry_run: bool | None = None
    message: str | None = None


_DRY_RUN_TRUE = {"true", "1", "yes"}


def _is_dry_run(value: str | None) -> bool:
    return value is not None and value.strip().lower() in _DRY_RUN_TRUE


_DRY_RUN_RESULT = SendResult(
    sent=False, dry_run=True, message="Email payload is valid"
)


def _build_sender_from_env() -> SmtpSender:
    # SMTP_USER/PASSWORD are optional so that no-auth SMTP servers
    # (Mailpit, MailHog, ...) can be used via docker-compose.dev.yml.
    from_addr = os.environ.get("SMTP_FROM", "")
    if from_addr:
        try:
            _no_crlf(from_addr)
        except ValueError as exc:
            raise RuntimeError(
                "SMTP_FROM contains CRLF characters and would enable header "
                "injection"
            ) from exc
    return SmtpSender(SmtpConfig(
        host=_required_env("SMTP_HOST"),
        port=int(os.environ.get("SMTP_PORT", "587")),
        user=os.environ.get("SMTP_USER", ""),
        password=os.environ.get("SMTP_PASSWORD", ""),
        from_addr=from_addr,
        use_tls=os.environ.get("SMTP_USE_TLS", "true").lower() != "false",
    ))


def create_app(
    *,
    sender: SmtpSender | None = None,
    api_key: str | None = None,
    magic_link: MagicLinkNotifier | None = None,
    otp: OTPNotifier | None = None,
) -> FastAPI:
    """Build the FastAPI app. Env vars are read only for arguments left as None."""
    if sender is None:
        sender = _build_sender_from_env()
    if api_key is None:
        api_key = _required_env("API_KEY")

    if magic_link is None:
        base_url = os.environ.get("MAGIC_LINK_BASE_URL")
        if base_url:
            magic_link = MagicLinkNotifier(sender, base_url=base_url)
    if otp is None:
        otp = OTPNotifier(sender)

    app = FastAPI(title="email-service")
    bearer = HTTPBearer(auto_error=False)

    def verify_key(
        creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> None:
        if creds is None or not hmac.compare_digest(creds.credentials, api_key):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key"
            )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/send",
        response_model=SendResult,
        response_model_exclude_none=True,
    )
    def send_email(
        req: SendEmailRequest,
        x_dry_run: str | None = Header(default=None, alias="X-Dry-Run"),
        _: None = Depends(verify_key),
    ) -> SendResult:
        if _is_dry_run(x_dry_run):
            return _DRY_RUN_RESULT
        ok = sender.send(
            to=req.to,
            subject=req.subject,
            html_body=req.html_body,
            text_body=req.text_body,
            cc=req.cc,
            bcc=req.bcc,
        )
        if not ok:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Email send failed")
        return SendResult(sent=True)

    @app.post(
        "/send/magic-link",
        response_model=SendResult,
        response_model_exclude_none=True,
    )
    def send_magic_link(
        req: SendMagicLinkRequest,
        x_dry_run: str | None = Header(default=None, alias="X-Dry-Run"),
        _: None = Depends(verify_key),
    ) -> SendResult:
        # Dry-run must succeed before the configuration check so that callers
        # can validate payloads even when MAGIC_LINK_BASE_URL is unset.
        if _is_dry_run(x_dry_run):
            return _DRY_RUN_RESULT
        if magic_link is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Magic link endpoint not configured (set MAGIC_LINK_BASE_URL)",
            )
        ok = magic_link.send(req.to, req.user_name, req.token)
        if not ok:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Email send failed")
        return SendResult(sent=True)

    @app.post(
        "/send/otp",
        response_model=SendResult,
        response_model_exclude_none=True,
    )
    def send_otp(
        req: SendOTPRequest,
        x_dry_run: str | None = Header(default=None, alias="X-Dry-Run"),
        _: None = Depends(verify_key),
    ) -> SendResult:
        if _is_dry_run(x_dry_run):
            return _DRY_RUN_RESULT
        ok = otp.send(req.to, req.user_name, req.code)
        if not ok:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Email send failed")
        return SendResult(sent=True)

    return app
