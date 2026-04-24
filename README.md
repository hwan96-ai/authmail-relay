# email-service

[![Python](https://img.shields.io/badge/python-%E2%89%A53.10-blue)](https://www.python.org/)

범용 SMTP 이메일 발송 패키지. Python 라이브러리로 직접 import해 쓰거나, FastAPI 기반 HTTP 서비스로 띄워 REST API로 호출할 수 있다.

---

## 소개

`email-service`는 SMTP로 HTML 이메일을 보내기 위한 재사용 가능한 파이썬 패키지이다. 다음 두 가지 사용 방식을 모두 지원한다.

- **라이브러리 모드** — 같은 Python 프로세스에서 `SmtpSender`, `MagicLinkNotifier` 등을 직접 import해 호출한다. 외부 의존성 없음 (표준 라이브러리의 `smtplib`, `email`만 사용).
- **HTTP 서비스 모드** — `python -m email_service` 로 FastAPI 서버를 기동하고, 다른 백엔드(언어 무관)가 REST로 메일 발송을 요청한다. SMTP 자격증명을 서버 측 환경변수에만 보관하고 호출자는 공유 `API_KEY` 로 인증한다.

비밀번호 설정 매직링크 / 일회용 인증코드(OTP) 같은 자주 쓰이는 템플릿은 기본 제공되며, 커스텀 템플릿도 쉽게 추가할 수 있다.

---

## 주요 기능

- **HTML + plain-text multipart 발송** — `text_body` 를 넘기면 HTML 미지원 클라이언트를 위한 대체본이 함께 첨부된다.
- **cc / bcc 지원** — 헤더/수신자 목록에 올바르게 반영. bcc 는 헤더에 노출되지 않는다.
- **CRLF 헤더 인젝션 차단** — `to`, `subject`, `from`, `cc`, `bcc` 에 `\r` / `\n` 이 포함되면 발송을 거부한다. HTTP API 에서는 sender 까지 가기 전 Pydantic 단계에서 `422` 로 차단.
- **HTML 자동 이스케이프** — `MagicLinkNotifier` / `OTPNotifier` / `TemplateNotifier` 의 사용자 입력 값 (user_name, token, code, context) 은 기본적으로 `html.escape` 처리된다.
- **플러그인 방식 Notifier** — `Notifier` 추상 클래스 상속으로 새로운 이메일 템플릿을 손쉽게 추가.
- **STARTTLS + SMTP AUTH** — `SmtpConfig.use_tls` / `user` / `password` 로 제어. 자격증명이 비면 AUTH 생략.
- **Fail-fast 기동** — HTTP 모드에서 필수 환경변수가 비어 있으면 `RuntimeError` 로 즉시 실패.
- **OpenAPI 문서 자동 제공** — 기본 활성화된 [`/docs`](http://127.0.0.1:8000/docs) (Swagger UI), `/openapi.json`.

---

## 사용 방식

| 모드 | 설치 | 실행 | 용도 |
|---|---|---|---|
| 라이브러리 | `pip install git+...` | Python 코드에서 `import` | 같은 프로세스 안에서 메일 발송 |
| HTTP 서비스 | `pip install "email-service[http] @ git+..."` | `python -m email_service` | 다른 서비스가 REST 로 호출 |

설치 명령 전체 예시:

```bash
# 라이브러리로만 사용
pip install git+https://github.com/hwan96-ai/email-service.git

# HTTP 서비스로 띄워서 사용
pip install "email-service[http] @ git+https://github.com/hwan96-ai/email-service.git"
```

요구 사항: Python **3.10+**.

---

## 빠른 시작

### HTTP 서비스로 띄워 curl 로 테스트

```bash
# 1) 설치
pip install "email-service[http] @ git+https://github.com/hwan96-ai/email-service.git"

# 2) 환경변수 설정 (최소)
export SMTP_HOST=smtp.gmail.com
export SMTP_USER=sender@gmail.com
export SMTP_PASSWORD=app-password
export API_KEY=$(openssl rand -hex 32)     # 임의의 긴 비밀문자열

# 3) 기동
python -m email_service
#   → INFO:     Uvicorn running on http://127.0.0.1:8000

# 4) 호출 (다른 터미널에서)
curl -X POST http://127.0.0.1:8000/send \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to":"user@example.com","subject":"Hi","html_body":"<p>Hello</p>"}'
#   → {"sent":true}
```

### Python 라이브러리로 한 줄 발송

```python
from email_service import SmtpSender
from email_service.sender import SmtpConfig

sender = SmtpSender(SmtpConfig(
    host="smtp.gmail.com", user="sender@gmail.com", password="app-password",
))
sender.send("user@example.com", "Hi", "<p>Hello</p>")
```

---

## Docker 로 실행

다른 서비스가 REST 로 호출하는 운영 시나리오라면 `Dockerfile` + `docker-compose.yml` + `.env.example` 이 함께 제공된다. Docker 이미지는 **Python 3.12 slim** 기반이며, 로컬 개발(Python 3.10+) 과 별개이다.

### 1) 환경변수 파일 준비

```bash
cp .env.example .env
# 에디터로 .env 열어 SMTP_HOST / SMTP_USER / SMTP_PASSWORD / API_KEY 채움
# API_KEY 생성: openssl rand -hex 32
```

`.env` 는 `.gitignore` 되어 있다. 절대 커밋하지 말 것.

### 2) 빌드 & 기동

```bash
docker compose up -d --build
```

- 이미지: `python:3.12-slim` 베이스, uid `10001` 의 non-root `app` 유저로 실행.
- 컨테이너 내부 `HOST=0.0.0.0`, `PORT=8000` (Dockerfile/compose 에 기본 설정).
- 호스트 `8000` ↔ 컨테이너 `8000` 포트 매핑 (`docker-compose.yml` 의 `ports:`).
- `docker-compose.yml` 에 `/health` 헬스체크 포함 — `docker compose ps` 에 `healthy` 상태가 뜨며, 기동 후 약 10 초 이내에 초록색으로 전환된다.

### 3) 호출

```bash
curl -X POST http://127.0.0.1:8000/send \
  -H "Authorization: Bearer $(grep ^API_KEY .env | cut -d= -f2-)" \
  -H "Content-Type: application/json" \
  -d '{"to":"user@example.com","subject":"Hi","html_body":"<p>Hello</p>"}'
```

### 4) 로그 / 중지

```bash
docker compose logs -f email-service    # 로그 추적
docker compose down                     # 정지 및 컨테이너 제거
```

### 운영 배포 참고

- `docker-compose.yml` 은 편의를 위해 `ports: "8000:8000"` 으로 호스트에 직접 공개한다. **공용 인터넷에는 노출 금지.** 내부망 / VPC / 방화벽 안에 두고 앞단에 Reverse Proxy (nginx, Traefik 등) + TLS 종단을 구성한다.
- 같은 Docker 네트워크 안의 다른 컨테이너만 호출하면 되는 경우 `ports:` 를 제거하고 `expose: ["8000"]` 로 바꾸면 호스트 포트가 열리지 않는다.

---

## HTTP API 사용법

### 엔드포인트

`POST` 요청은 모두 `Authorization: Bearer $API_KEY` 헤더가 필요하다. 성공 시 `200 {"sent": true}`. `GET /health` 는 인증이 필요 없다.

| 메서드 | 경로 | 요청 body | 인증 | 설명 |
|---|---|---|---|---|
| `GET` | `/health` | — | 불필요 | 헬스체크. `200 {"status": "ok"}` 반환. 로드밸런서/Docker healthcheck 용 |
| `POST` | `/send` | `to, subject, html_body, text_body?, cc?, bcc?` | 필요 | 일반 메일 |
| `POST` | `/send/magic-link` | `to, user_name, token` | 필요 | 매직링크 메일 (`MAGIC_LINK_BASE_URL` 필요) |
| `POST` | `/send/otp` | `to, user_name, code` | 필요 | OTP 메일 |

### 에러 코드

| 코드 | 의미 |
|---|---|
| `401` | API 키 누락/오류 |
| `422` | 필수 필드 누락, 또는 헤더 (`to`/`subject`/`cc`/`bcc`) 에 CRLF 포함 (헤더 인젝션 차단) |
| `502` | SMTP 연결 또는 발송 실패 |
| `503` | `/send/magic-link` 호출 시 `MAGIC_LINK_BASE_URL` 미설정 |

### curl 호출 예시

**일반 메일 (cc/bcc 포함):**
```bash
curl -X POST http://127.0.0.1:8000/send \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "to":"user@example.com",
        "subject":"Hi",
        "html_body":"<p>Hello</p>",
        "text_body":"Hello",
        "cc":["cc@example.com"],
        "bcc":["bcc@example.com"]
      }'
```

**매직링크 메일:**
```bash
curl -X POST http://127.0.0.1:8000/send/magic-link \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to":"user@example.com","user_name":"홍길동","token":"abc123"}'
```

**OTP 메일:**
```bash
curl -X POST http://127.0.0.1:8000/send/otp \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to":"user@example.com","user_name":"홍길동","code":"482901"}'
```

### Python 클라이언트 (httpx)

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

---

## Python 라이브러리로 사용하기

패키지의 공개 API:

```python
from email_service import SmtpSender, MagicLinkNotifier, OTPNotifier, TemplateNotifier
from email_service.sender import SmtpConfig
from email_service.notifiers import Notifier   # 커스텀 Notifier 만들 때
```

### `SmtpConfig`

SMTP 연결 설정. 단순 dataclass.

```python
from email_service.sender import SmtpConfig

config = SmtpConfig(
    host="smtp.gmail.com",   # 기본: smtp.gmail.com
    port=587,                # 기본: 587
    user="sender@gmail.com", # 로그인 계정
    password="app-password", # 앱 비밀번호
    from_addr="",            # 발신자 주소 (비우면 user 와 동일)
    use_tls=True,            # STARTTLS 사용 여부 (기본: True)
    timeout=10,              # 연결 타임아웃 초 (기본: 10)
)
```

### `SmtpSender`

HTML 이메일을 발송하는 저수준 sender.

```python
from email_service import SmtpSender
from email_service.sender import SmtpConfig

sender = SmtpSender(SmtpConfig(
    host="smtp.gmail.com",
    user="sender@gmail.com",
    password="app-password",
))

success = sender.send(
    to="recipient@example.com",
    subject="제목",
    html_body="<h1>본문</h1>",
    text_body="본문",              # 선택: plain-text 대체본 (multipart/alternative 의 fallback)
    cc=["cc@example.com"],         # 선택
    bcc=["bcc@example.com"],       # 선택
)
# 반환: True (성공) / False (실패, 로그에 에러 기록)
# 헤더 값(to/subject/from/cc/bcc)에 CR/LF가 포함되면 발송 거부 (CRLF 인젝션 차단)
```

### `MagicLinkNotifier`

비밀번호 설정 매직링크 이메일.

```python
from email_service import SmtpSender, MagicLinkNotifier
from email_service.sender import SmtpConfig

sender = SmtpSender(SmtpConfig(
    host="smtp.gmail.com", user="noreply@mycompany.com", password="app-password",
))

notifier = MagicLinkNotifier(
    sender,
    base_url="https://myapp.com",      # 필수: 프론트엔드 URL
    path="/set-password",              # 선택: 링크 경로 (기본)
    subject_prefix="[MyApp] ",         # 선택: 메일 제목 접두어
    expire_minutes=15,                 # 선택: 본문에 표시할 유효시간 (기본: 15)
)

# payload = 토큰 문자열. 토큰은 URL 인코딩되어 링크에 포함된다.
notifier.send("user@example.com", "홍길동", "abc123token")
# → 본문에 https://myapp.com/set-password?token=abc123token 링크 삽입
```

### `OTPNotifier`

일회용 인증코드 이메일.

```python
from email_service import SmtpSender, OTPNotifier
from email_service.sender import SmtpConfig

sender = SmtpSender(SmtpConfig(
    host="smtp.gmail.com", user="noreply@mycompany.com", password="app-password",
))

notifier = OTPNotifier(sender, subject_prefix="[MyApp] ", expire_minutes=5)

# payload = OTP 코드 문자열
notifier.send("user@example.com", "홍길동", "482901")
# → 본문에 482901 코드를 큰 글씨로 표시
```

### `TemplateNotifier`

임의의 제목/HTML 템플릿으로 메일을 렌더링해 발송. `(user_name, payload)` 고정 시그니처가 맞지 않는 케이스용.

```python
from email_service import SmtpSender, TemplateNotifier
from email_service.sender import SmtpConfig

sender = SmtpSender(SmtpConfig(host="smtp.gmail.com", user="noreply@x.com", password="..."))

notifier = TemplateNotifier(
    sender,
    subject="[MyApp] {order_id} 주문이 접수되었습니다",
    html_template="<p>{user_name}님, 주문 {order_id}번이 접수되었습니다. 금액: {amount}원</p>",
    text_template="{user_name}님, 주문 {order_id}번 접수. 금액: {amount}원",  # 선택
    autoescape=True,   # 기본 True — HTML 본문의 context 값만 html.escape 처리
)

notifier.send(
    "user@example.com",
    user_name="홍길동", order_id="A-1024", amount="45,000",
)
```

- 템플릿은 `str.format` 문법. 플레이스홀더 (`{key}`) 는 `send(**context)` 의 키워드와 매칭.
- `autoescape=True` 에서 **HTML 템플릿의 context 값만** 이스케이프된다. subject/text_template 은 HTML 컨텍스트가 아니므로 이스케이프하지 않음.

### 커스텀 Notifier

`Notifier` 를 상속하면 새 템플릿을 쉽게 추가할 수 있다.

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

---

## 환경변수

HTTP 서비스 모드 (`python -m email_service`) 에서 사용한다. 라이브러리 모드에서는 무관하다.

### 필수

| 이름 | 설명 |
|---|---|
| `SMTP_HOST` | SMTP 서버 호스트 (예: `smtp.gmail.com`) |
| `SMTP_USER` | SMTP 로그인 계정 |
| `SMTP_PASSWORD` | SMTP 비밀번호 / 앱 비밀번호 |
| `API_KEY` | 클라이언트가 `Authorization: Bearer` 로 보내는 공유 비밀 키 |

필수 환경변수가 비어 있으면 기동 즉시 `RuntimeError` 로 실패한다 (fail-fast).

### 선택

| 이름 | 기본값 | 설명 |
|---|---|---|
| `SMTP_PORT` | `587` | SMTP 포트 |
| `SMTP_FROM` | `SMTP_USER` 와 동일 | 발신자 주소 |
| `SMTP_USE_TLS` | `true` | STARTTLS 사용 여부 (`false` 로 설정 시 비활성) |
| `MAGIC_LINK_BASE_URL` | — | `/send/magic-link` 엔드포인트 활성화용 프론트엔드 URL. 미설정 시 해당 엔드포인트는 `503` 반환 |
| `HOST` | `127.0.0.1` | uvicorn 바인딩 호스트. 로컬 `python -m email_service` 기본값은 `127.0.0.1` (루프백). Docker 실행 시에는 컨테이너 밖에서 접근 가능해야 하므로 `0.0.0.0` 을 사용한다 (제공된 `Dockerfile` / `docker-compose.yml` 이 이미 `0.0.0.0` 으로 설정) |
| `PORT` | `8000` | uvicorn 바인딩 포트 |

---

## 보안 및 운영 주의사항

- **내부망 전제** — 로컬 `python -m email_service` 기본 `HOST=127.0.0.1`. 제공되는 `docker-compose.yml` 은 편의를 위해 `ports: "8000:8000"` 으로 호스트에 공개하지만, **운영에서 이 포트를 공용 인터넷에 직접 노출하지 말 것**. 내부망·VPC·방화벽 뒤에 두고 앞단에 Reverse Proxy / TLS 종단 / WAF 를 구성한다. 외부 완전 차단이 필요하면 `docker-compose.yml` 의 `ports:` 를 `expose:` 로 바꾸면 같은 compose 네트워크의 다른 컨테이너만 접근하게 된다.
- **단일 API 키** — 모든 호출자가 같은 키를 공유한다. 호출자별 구분이 필요하면 키를 분리하거나 리버스 프록시 레벨에서 인증을 추가한다.
- **CRLF 헤더 인젝션** — `SmtpSender` 와 HTTP API Pydantic 모델 양쪽에서 `to`/`subject`/`from`/`cc`/`bcc` 의 CR/LF 를 차단한다. 사용자 입력을 그대로 넘겨도 안전하다.
- **HTML 이스케이프** — 내장 Notifier 들은 user_name, token, code, context 를 기본적으로 `html.escape` 처리한다. HTML 구조 자체를 사용자 입력으로 만들지는 말 것.
- **자격증명 관리** — `SMTP_PASSWORD`, `API_KEY` 는 .env / secret store 등 외부에 보관하고 저장소에 커밋하지 않는다.
- **OpenAPI 스펙** — 기본 활성화된 `/docs` (Swagger UI), `/openapi.json` 에서 조회 가능. 운영에서 불필요하다면 외부 노출 전에 앞단에서 차단한다.

---

## 개발 및 테스트

```bash
git clone https://github.com/hwan96-ai/email-service.git
cd email-service

# 개발 의존성 설치 (pytest, httpx)
pip install -e ".[dev]"

# HTTP 모드 테스트까지 같이 돌리려면 http extras 도
pip install -e ".[dev,http]"

# 전체 테스트
python -m pytest tests/ -v

# 일부만
python -m pytest tests/test_email_service.py -v   # 코어 유닛 테스트
python -m pytest tests/test_api.py -v             # HTTP API 통합 테스트
```

테스트는 실제 SMTP 서버에 연결하지 않는다 (`smtplib.SMTP` 를 mock 처리).

---

## 프로젝트 구조

```
email-service/
├── email_service/
│   ├── __init__.py        # 공개 API re-export (SmtpSender, *Notifier)
│   ├── __main__.py        # `python -m email_service` 진입점 (uvicorn 기동)
│   ├── api.py             # FastAPI 앱 (create_app) + Pydantic 모델 + 인증
│   ├── sender.py          # SmtpConfig, SmtpSender — SMTP 발송 코어
│   └── notifiers.py       # Notifier(ABC), MagicLinkNotifier, OTPNotifier, TemplateNotifier
├── tests/
│   ├── test_email_service.py   # sender + notifier 유닛 테스트
│   └── test_api.py             # HTTP API 통합 테스트
├── pyproject.toml         # 패키지 메타 + optional extras (dev, http)
└── README.md
```
