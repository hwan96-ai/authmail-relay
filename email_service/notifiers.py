"""Pluggable notifier templates — magic-link, OTP, etc."""
from abc import ABC, abstractmethod

from email_service.sender import SmtpSender


class Notifier(ABC):
    """Base class for all email notifiers."""

    def __init__(self, sender: SmtpSender):
        self._sender = sender

    @abstractmethod
    def send(self, to_email: str, user_name: str, payload: str) -> bool:
        ...


class MagicLinkNotifier(Notifier):
    """Send a password-setup magic link."""

    def __init__(self, sender: SmtpSender, *,
                 base_url: str,
                 path: str = "/set-password",
                 subject_prefix: str = "",
                 expire_minutes: int = 15):
        super().__init__(sender)
        self._base_url = base_url.rstrip("/")
        self._path = path
        self._prefix = subject_prefix
        self._expire = expire_minutes

    def send(self, to_email: str, user_name: str, payload: str) -> bool:
        link = f"{self._base_url}{self._path}?token={payload}"
        subject = f"{self._prefix}비밀번호 설정 안내".strip()
        html = f"""\
<html><body style="font-family:sans-serif; color:#333;">
<h2>비밀번호 설정</h2>
<p>안녕하세요, <strong>{user_name}</strong>님.</p>
<p>아래 링크를 클릭하여 비밀번호를 설정해 주세요.<br>
링크는 <strong>{self._expire}분</strong> 동안 유효하며, 1회만 사용할 수 있습니다.</p>
<p style="margin:24px 0;">
  <a href="{link}"
     style="background:#1a73e8;color:#fff;padding:12px 28px;
            border-radius:6px;text-decoration:none;font-size:16px;">
    비밀번호 설정하기
  </a>
</p>
<p style="font-size:12px;color:#888;">
  이 메일을 요청하지 않으셨다면 무시하셔도 됩니다.
</p>
</body></html>"""
        return self._sender.send(to_email, subject, html)


class OTPNotifier(Notifier):
    """Send a one-time password code via email."""

    def __init__(self, sender: SmtpSender, *,
                 subject_prefix: str = "",
                 expire_minutes: int = 15):
        super().__init__(sender)
        self._prefix = subject_prefix
        self._expire = expire_minutes

    def send(self, to_email: str, user_name: str, payload: str) -> bool:
        subject = f"{self._prefix}비밀번호 설정 인증코드".strip()
        html = f"""\
<html><body style="font-family:sans-serif; color:#333;">
<h2>비밀번호 설정 인증코드</h2>
<p>안녕하세요, <strong>{user_name}</strong>님.</p>
<p>아래 인증코드를 입력하여 비밀번호를 설정해 주세요.</p>
<p style="font-size:32px;font-weight:bold;letter-spacing:8px;margin:24px 0;">
  {payload}
</p>
<p>인증코드는 <strong>{self._expire}분</strong> 동안 유효합니다.</p>
</body></html>"""
        return self._sender.send(to_email, subject, html)
