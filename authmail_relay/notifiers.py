"""Pluggable notifier templates — magic-link, OTP, etc."""
from abc import ABC, abstractmethod
from html import escape
from urllib.parse import urlencode

from authmail_relay.sender import SendResult, SmtpSender


# Email templates use accessible markup:
# - <html lang="ko"> for screen readers
# - <meta viewport> for mobile rendering
# - 600px max-width container (Outlook-safe <table>)
# - WCAG AA color contrast (#595959 on white = 7.04:1)
# - @media (prefers-color-scheme: dark) for dark mode
# - @media (max-width:600px) for responsive collapse
_BASE_STYLE = """\
<style>
  @media (max-width:600px) {{
    .container {{ width: 100% !important; }}
    .cta {{ display: block !important; text-align: center; }}
  }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #1a1a1a !important; color: #f0f0f0 !important; }}
    .fine-print {{ color: #aaa !important; }}
    .cta {{ background: #4a8eff !important; }}
  }}
</style>"""


_MAGIC_LINK_HTML = """\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
""" + _BASE_STYLE + """
</head>
<body style="font-family:sans-serif; color:#333; margin:0; padding:0;">
<table role="presentation" align="center" class="container" style="max-width:600px;width:100%;margin:0 auto;border-collapse:collapse;">
  <tr><td style="padding:24px;">
    <h2>비밀번호 설정</h2>
    <p>안녕하세요, <strong>{name}</strong>님.</p>
    <p>아래 링크를 클릭하여 비밀번호를 설정해 주세요.<br>
    링크는 <strong>{expire}분</strong> 동안 유효하며, 1회만 사용할 수 있습니다.</p>
    <p style="margin:24px 0;">
      <a href="{link}" class="cta"
         style="background:#1a73e8;color:#fff;padding:12px 28px;
                border-radius:6px;text-decoration:none;font-size:16px;">
        비밀번호 설정하기
      </a>
    </p>
    <p class="fine-print" style="font-size:12px;color:#595959;">
      이 메일을 요청하지 않으셨다면 무시하셔도 됩니다.
    </p>
  </td></tr>
</table>
</body></html>"""


_MAGIC_LINK_TEXT = """\
안녕하세요, {name}님.

비밀번호를 설정하려면 다음 링크를 여세요:
{link}

링크는 {expire}분 동안 유효하며, 1회만 사용할 수 있습니다.
"""


_OTP_HTML = """\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
""" + _BASE_STYLE + """
</head>
<body style="font-family:sans-serif; color:#333; margin:0; padding:0;">
<table role="presentation" align="center" class="container" style="max-width:600px;width:100%;margin:0 auto;border-collapse:collapse;">
  <tr><td style="padding:24px;">
    <h2>비밀번호 설정 인증코드</h2>
    <p>안녕하세요, <strong>{name}</strong>님.</p>
    <p>아래 인증코드를 입력하여 비밀번호를 설정해 주세요.</p>
    <p style="font-size:32px;font-weight:bold;letter-spacing:8px;margin:24px 0;">
      {payload}
    </p>
    <p class="fine-print" style="color:#595959;">인증코드는 <strong>{expire}분</strong> 동안 유효합니다.</p>
  </td></tr>
</table>
</body></html>"""


_OTP_TEXT = """\
안녕하세요, {name}님.

비밀번호를 설정하려면 다음 인증코드를 입력하세요:

  {payload}

인증코드는 {expire}분 동안 유효합니다.
"""


_MAGIC_LINK_SUBJECT = "비밀번호 설정 안내"
_OTP_SUBJECT = "비밀번호 설정 인증코드"


def _escape_context(context: dict) -> dict:
    return {k: escape(str(v)) if isinstance(v, str) else v
            for k, v in context.items()}


class Notifier(ABC):
    """Base class for all email notifiers."""

    def __init__(self, sender: SmtpSender):
        self._sender = sender

    @abstractmethod
    def send(self, to_email: str, user_name: str, payload: str) -> SendResult:
        ...


class MagicLinkNotifier(Notifier):
    """Send a password-setup magic link.

    i18n / customization:
        Override the Korean defaults by passing ``subject=`` and
        ``html_template=``. The HTML template must use ``{name}``, ``{link}``,
        and ``{expire}`` placeholders (str.format syntax). Optionally pass
        ``text_template=`` to override the plain-text alternative.
    """

    def __init__(self, sender: SmtpSender, *,
                 base_url: str,
                 path: str = "/set-password",
                 subject_prefix: str = "",
                 expire_minutes: int = 15,
                 subject: str | None = None,
                 html_template: str | None = None,
                 text_template: str | None = None):
        super().__init__(sender)
        self._base_url = base_url.rstrip("/")
        self._path = path
        self._prefix = subject_prefix
        self._expire = expire_minutes
        self._subject = subject if subject is not None else _MAGIC_LINK_SUBJECT
        self._html_template = (
            html_template if html_template is not None else _MAGIC_LINK_HTML
        )
        self._text_template = (
            text_template if text_template is not None else _MAGIC_LINK_TEXT
        )

    def send(self, to_email: str, user_name: str, payload: str) -> SendResult:
        link = f"{self._base_url}{self._path}?{urlencode({'token': payload})}"
        subject = f"{self._prefix}{self._subject}".strip()
        html = self._html_template.format(
            name=escape(user_name),
            link=escape(link, quote=True),
            expire=self._expire,
        )
        text = self._text_template.format(
            name=user_name, link=link, expire=self._expire,
        )
        return self._sender.send(to_email, subject, html, text_body=text)


class OTPNotifier(Notifier):
    """Send a one-time password code via email.

    i18n / customization:
        Override the Korean defaults by passing ``subject=`` and
        ``html_template=``. The HTML template must use ``{name}``,
        ``{payload}``, and ``{expire}`` placeholders. Optionally pass
        ``text_template=`` to override the plain-text alternative.
    """

    def __init__(self, sender: SmtpSender, *,
                 subject_prefix: str = "",
                 expire_minutes: int = 15,
                 subject: str | None = None,
                 html_template: str | None = None,
                 text_template: str | None = None):
        super().__init__(sender)
        self._prefix = subject_prefix
        self._expire = expire_minutes
        self._subject = subject if subject is not None else _OTP_SUBJECT
        self._html_template = (
            html_template if html_template is not None else _OTP_HTML
        )
        self._text_template = (
            text_template if text_template is not None else _OTP_TEXT
        )

    def send(self, to_email: str, user_name: str, payload: str) -> SendResult:
        subject = f"{self._prefix}{self._subject}".strip()
        html = self._html_template.format(
            name=escape(user_name),
            payload=escape(payload),
            expire=self._expire,
        )
        text = self._text_template.format(
            name=user_name, payload=payload, expire=self._expire,
        )
        return self._sender.send(to_email, subject, html, text_body=text)


class TemplateNotifier:
    """Send an email rendered from subject + HTML templates with arbitrary context.

    Does not inherit from Notifier ABC. Notifier has a fixed
    ``(to, user_name, payload)`` signature for magic-link/OTP-style use cases.
    TemplateNotifier supports arbitrary context via ``**kwargs`` and is
    intentionally separate.

    Placeholders use ``str.format`` syntax. Pass values as keyword arguments
    to ``send()``. Suited for reuse cases that don't fit the fixed
    (user_name, payload) shape of MagicLinkNotifier / OTPNotifier.
    """

    def __init__(self, sender: SmtpSender, *,
                 subject: str,
                 html_template: str,
                 text_template: str | None = None,
                 autoescape: bool = True):
        self._sender = sender
        self._subject = subject
        self._template = html_template
        self._text_template = text_template
        self._autoescape = autoescape

    def send(self, to_email: str, **context) -> SendResult:
        html_ctx = _escape_context(context) if self._autoescape else context
        subject = self._subject.format(**context)
        html_body = self._template.format(**html_ctx)
        text = self._text_template.format(**context) if self._text_template else None
        return self._sender.send(to_email, subject, html_body, text_body=text)
