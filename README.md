# email-service

범용 SMTP 이메일 발송 패키지. 매직링크, OTP 등 플러그인 방식의 notifier를 제공한다.

## 설치

```bash
pip install git+https://github.com/hwan96-ai/email-service.git
```

## 구조

```
email_service/
  sender.py       # SmtpConfig, SmtpSender — SMTP 발송 코어
  notifiers.py    # Notifier(ABC), MagicLinkNotifier, OTPNotifier
  __init__.py      # 공개 API re-export
```

## API

### SmtpConfig

SMTP 연결 설정. dataclass.

```python
from email_service.sender import SmtpConfig

config = SmtpConfig(
    host="smtp.gmail.com",   # SMTP 서버 (기본: smtp.gmail.com)
    port=587,                # 포트 (기본: 587)
    user="sender@gmail.com", # 로그인 계정
    password="app-password", # 앱 비밀번호
    from_addr="",            # 발신자 주소 (비우면 user와 동일)
    use_tls=True,            # STARTTLS 사용 여부 (기본: True)
    timeout=10,              # 연결 타임아웃 초 (기본: 10)
)
```

### SmtpSender

HTML 이메일을 발송하는 저수준 sender.

```python
from email_service import SmtpSender
from email_service.sender import SmtpConfig

sender = SmtpSender(SmtpConfig(
    host="smtp.gmail.com",
    user="sender@gmail.com",
    password="app-password",
))

# 직접 발송
success = sender.send(
    to="recipient@example.com",
    subject="제목",
    html_body="<h1>본문</h1>",
)
# 반환: True (성공) / False (실패, 로그에 에러 기록)
```

### MagicLinkNotifier

비밀번호 설정 매직링크 이메일을 보내는 notifier.

```python
from email_service import SmtpSender, MagicLinkNotifier
from email_service.sender import SmtpConfig

sender = SmtpSender(SmtpConfig(
    host="smtp.gmail.com",
    user="noreply@mycompany.com",
    password="app-password",
))

notifier = MagicLinkNotifier(
    sender,
    base_url="https://myapp.com",      # 필수: 프론트엔드 URL
    path="/set-password",               # 선택: 링크 경로 (기본: /set-password)
    subject_prefix="[MyApp] ",          # 선택: 메일 제목 접두어
    expire_minutes=15,                  # 선택: 링크 유효시간 표시 (기본: 15)
)

# payload = 토큰 문자열
notifier.send("user@example.com", "홍길동", "abc123token")
# → 이메일 본문에 https://myapp.com/set-password?token=abc123token 링크 포함
```

### OTPNotifier

일회용 인증코드 이메일을 보내는 notifier.

```python
from email_service import SmtpSender, OTPNotifier
from email_service.sender import SmtpConfig

sender = SmtpSender(SmtpConfig(
    host="smtp.gmail.com",
    user="noreply@mycompany.com",
    password="app-password",
))

notifier = OTPNotifier(
    sender,
    subject_prefix="[MyApp] ",
    expire_minutes=5,
)

# payload = OTP 코드 문자열
notifier.send("user@example.com", "홍길동", "482901")
# → 이메일 본문에 482901 코드 표시
```

### 커스텀 Notifier 만들기

`Notifier` 추상 클래스를 상속해서 새로운 이메일 템플릿을 추가할 수 있다.

```python
from email_service.notifiers import Notifier
from email_service.sender import SmtpSender

class WelcomeNotifier(Notifier):
    def __init__(self, sender: SmtpSender, *, company_name: str = ""):
        super().__init__(sender)
        self._company = company_name

    def send(self, to_email: str, user_name: str, payload: str) -> bool:
        subject = f"{self._company} 가입을 환영합니다"
        html = f"<h1>{user_name}님, 환영합니다!</h1><p>{payload}</p>"
        return self._sender.send(to_email, subject, html)
```

## 프로젝트에서 사용하는 예시 (인바운드콜 auth)

```python
# auth/email_service.py
from email_service import SmtpSender, MagicLinkNotifier, OTPNotifier
from email_service.sender import SmtpConfig
from email_service.notifiers import Notifier

_sender = SmtpSender(SmtpConfig(
    host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
    port=int(os.getenv("SMTP_PORT", "587")),
    user=os.getenv("SMTP_USER"),
    password=os.getenv("SMTP_PASSWORD"),
))

def get_notifier(method: str = "email_magic_link") -> Notifier:
    if method == "email_otp":
        return OTPNotifier(_sender, subject_prefix="[Saltware] ")
    return MagicLinkNotifier(
        _sender,
        base_url=os.getenv("FRONTEND_BASE_URL", "http://localhost:3000"),
        subject_prefix="[Saltware] ",
    )
```

## 테스트

```bash
git clone https://github.com/hwan96-ai/email-service.git
cd email-service
pip install -e ".[dev]"
python -m pytest tests/ -v
```

## 의존성

외부 의존성 없음. Python 표준 라이브러리(smtplib, email)만 사용.
