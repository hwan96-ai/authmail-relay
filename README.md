# email-service

범용 SMTP 이메일 발송 패키지. 매직링크, OTP 등 플러그인 방식의 notifier를 제공한다.

## 설치

```bash
# 라이브러리로만 사용 (Python 코드에서 import)
pip install git+https://github.com/hwan96-ai/email-service.git

# HTTP 서비스로 띄워서 사용 (다른 서비스가 REST로 호출)
pip install "email-service[http] @ git+https://github.com/hwan96-ai/email-service.git"
```

## 사용 모드

1. **라이브러리** — 같은 Python 프로세스에서 직접 `SmtpSender`, `MagicLinkNotifier` 등을 import해 호출. 아래 [API](#api) 참고.
2. **HTTP 서비스** — 별도 프로세스로 띄우고 다른 백엔드가 REST로 호출. 아래 [HTTP 서비스로 사용](#http-서비스로-사용-rest-api) 참고.

## HTTP 서비스로 사용 (REST API)

다른 서비스(Node/Go/Python 무관)가 HTTP로 메일 발송을 요청하는 방식. 자격증명은 서버 측 환경변수로만 보관하고, 클라이언트는 공유 `API_KEY`로 인증한다.

### 기동

```bash
pip install -e ".[http]"

# 필수
export SMTP_HOST=smtp.gmail.com
export SMTP_USER=sender@gmail.com
export SMTP_PASSWORD=app-password
export API_KEY=<임의의-긴-비밀문자열>

# 선택
export SMTP_PORT=587                       # 기본 587
export SMTP_FROM=noreply@mycompany.com     # 기본은 SMTP_USER와 동일
export SMTP_USE_TLS=true                   # 기본 true
export MAGIC_LINK_BASE_URL=https://myapp.com  # /send/magic-link 쓸 때만 필수
export HOST=127.0.0.1                      # 기본 127.0.0.1 (내부망 전제)
export PORT=8000                           # 기본 8000

python -m email_service
```

필수 환경변수가 비어 있으면 기동 즉시 `RuntimeError`로 실패한다 (fail-fast).

### 엔드포인트

모든 요청은 `Authorization: Bearer $API_KEY` 헤더 필요. 성공 시 `200 {"sent": true}`.

| 메서드 | 경로 | body 필드 | 설명 |
|---|---|---|---|
| POST | `/send` | `to, subject, html_body, text_body?, cc?, bcc?` | 일반 메일 |
| POST | `/send/magic-link` | `to, user_name, token` | 매직링크 메일 (`MAGIC_LINK_BASE_URL` 필요) |
| POST | `/send/otp` | `to, user_name, code` | OTP 메일 |

에러 코드:
- `401` — API 키 누락/오류
- `422` — 필수 필드 누락 또는 헤더(`to`/`subject`/`cc`/`bcc`)에 CRLF 포함 (헤더 인젝션 차단)
- `502` — SMTP 연결/발송 실패
- `503` — 매직링크 엔드포인트인데 `MAGIC_LINK_BASE_URL` 미설정

### 호출 예시

**curl**
```bash
curl -X POST http://127.0.0.1:8000/send \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to":"user@example.com","subject":"Hi","html_body":"<p>Hello</p>"}'

curl -X POST http://127.0.0.1:8000/send/magic-link \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to":"user@example.com","user_name":"홍길동","token":"abc123"}'

curl -X POST http://127.0.0.1:8000/send/otp \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to":"user@example.com","user_name":"홍길동","code":"482901"}'
```

**Python 클라이언트**
```python
import os, httpx

client = httpx.Client(
    base_url=os.environ["EMAIL_SERVICE_URL"],           # 예: http://email-service:8000
    headers={"Authorization": f"Bearer {os.environ['EMAIL_API_KEY']}"},
    timeout=10,
)

resp = client.post("/send/otp", json={
    "to": "user@example.com",
    "user_name": "홍길동",
    "code": "482901",
})
resp.raise_for_status()   # 401/422/502/503 → 예외
```

### 운영 주의사항

- **내부망 전제**: 기본 `HOST=127.0.0.1`. 외부에 노출할 경우 앞단 TLS 종단·WAF 별도 필요.
- **단일 API 키**: 모든 호출자가 같은 키 공유. 호출자별 구분이 필요하면 키 분리나 리버스 프록시 레벨 인증을 추가.
- **프로그램적 통합**: OpenAPI 문서는 기본 활성화된 `/docs` (Swagger UI), `/openapi.json`에서 조회.

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
    text_body="본문",              # 선택: plain-text 대체본
    cc=["cc@example.com"],         # 선택
    bcc=["bcc@example.com"],       # 선택
)
# 반환: True (성공) / False (실패, 로그에 에러 기록)
# 헤더 값(to/subject/from/cc/bcc)에 CR/LF가 포함되면 발송 거부 (CRLF 인젝션 차단)
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

### TemplateNotifier

임의의 제목/HTML 템플릿으로 이메일을 렌더링해 발송. 매직링크/OTP처럼 `(user_name, payload)` 고정 시그니처가 맞지 않는 케이스용.

```python
from email_service import SmtpSender, TemplateNotifier
from email_service.sender import SmtpConfig

sender = SmtpSender(SmtpConfig(host="smtp.gmail.com", user="noreply@x.com", password="..."))

notifier = TemplateNotifier(
    sender,
    subject="[MyApp] {order_id} 주문이 접수되었습니다",
    html_template="<p>{user_name}님, 주문 {order_id}번이 접수되었습니다. 금액: {amount}원</p>",
    text_template="{user_name}님, 주문 {order_id}번 접수. 금액: {amount}원",  # 선택
    autoescape=True,   # 기본 True — context 값의 HTML 특수문자를 이스케이프
)

notifier.send(
    "user@example.com",
    user_name="홍길동",
    order_id="A-1024",
    amount="45,000",
)
```

- 템플릿은 `str.format` 문법. 플레이스홀더(`{key}`)는 `send(**context)`의 키워드와 매칭.
- `autoescape=True`(기본)에서 HTML 템플릿의 context 값은 `html.escape`로 이스케이프됨. subject/text_template은 이스케이프하지 않음.

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
