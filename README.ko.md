# email-service

[![PyPI](https://img.shields.io/pypi/v/hwan-email-service.svg)](https://pypi.org/project/hwan-email-service/)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.10-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> 자체 SMTP를 사용하는 Python/FastAPI 팀을 위한 작은 셀프호스팅 인증 메일 서비스.

언어: [English](README.md) · **한국어** · [HTML Usage Guide](https://hwan96-ai.github.io/email-service/usage.html) · [한국어 사용 가이드](https://hwan96-ai.github.io/email-service/usage.ko.html)

<sub>HTML 가이드는 GitHub Pages에서 웹페이지로 열립니다.</sub>

`email-service` 는 팀이 보유한 SMTP 계정을 통해 **매직 링크(magic link)**, **OTP**,
**비밀번호 재설정(password reset)** 메일을 보내는 작고 셀프호스팅 가능한 서비스다.
SMTP 자격증명과 메일 템플릿 로직을 인증 메일이 필요한 모든 앱에서 분리해, 각 앱은
Bearer API 키로 내부 HTTP 엔드포인트 하나만 호출하거나, Python 라이브러리로 임포트해
사용한다.

```text
앱 / 인증 서버
      │  Bearer API key
      ▼
  email-service     ← SMTP 자격증명은 여기에만 존재
      │
      ▼
 SMTP 제공자  ──►  사용자 메일함
```

### 이 서비스가 하는 것

- 이미 SMTP를 보유한 팀을 위한 작은 내부 **인증 메일 게이트웨이**.
- 매직 링크, OTP 코드, 비밀번호 재설정 등 트랜잭션 인증 메일과 일반 템플릿 메일을 발송.
- Python/FastAPI 팀을 위해 만들어졌지만, HTTP API는 언어 중립적이다.

### 이 서비스가 *아닌* 것

- **메일 서버가 아니다** — 기존 SMTP 제공자(Gmail, SES SMTP, 사내 릴레이 등)에 연결할
  뿐이며, 수신 메일이나 MX 처리는 하지 않는다.
- **완전한 인증 플랫폼이 아니다** — 인증 메일을 보내는 데 집중하며, 로그인 토큰을
  생성/저장/검증/만료하거나 세션 또는 사용자 정보를 관리하지 않는다.
- **마케팅/벌크 메일 플랫폼이 아니다** — 바운스 처리, 수신거부 목록, 분석 대시보드,
  딜리버러빌리티 도구는 제공하지 않는다.
- Resend, Postmark, SendGrid, Mailgun, SES 같은 **관리형 메일 서비스의 대체재가
  아니다** — 그들이 제공하는 딜리버러빌리티, 도메인 평판, SLA는 작은 셀프호스팅
  게이트웨이가 따라갈 수 없다. [docs/alternatives.md](docs/alternatives.md) 참고.

---

## 패키지 이름

저장소 이름, PyPI 배포 이름, Python 임포트 패키지 이름이 모두 다르다.

| | 이름 |
|---|---|
| Repository / service | `email-service` |
| PyPI distribution | `hwan-email-service` |
| Python import | `email_service` |

```bash
pip install hwan-email-service
```

```python
import email_service
```

---

## 설치

```bash
# 라이브러리 모드 (추가 의존성 없음)
pip install hwan-email-service

# HTTP 서비스 모드 (FastAPI + uvicorn)
pip install "hwan-email-service[http]"
```

요구 버전: **Python 3.10+**.

아직 릴리스되지 않은 최신 커밋을 git에서 바로 설치:

```bash
pip install "hwan-email-service[http] @ git+https://github.com/hwan96-ai/email-service.git"
```

---

## Quickstart — HTTP 서비스 모드

`email-service` 를 독립 서비스로 실행한다. 다른 앱은 Bearer API 키와 함께 HTTP로
호출한다. SMTP 자격증명은 이 서비스의 환경 변수에만 존재한다.

```bash
pip install "hwan-email-service[http]"

export SMTP_HOST=smtp.gmail.com
export SMTP_USER=sender@gmail.com
export SMTP_PASSWORD=app-password
export API_KEY=$(openssl rand -hex 32)

python -m email_service
# → Uvicorn running on http://127.0.0.1:8000
```

다른 터미널에서:

```bash
curl -X POST http://127.0.0.1:8000/send \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to":"user@example.com","subject":"Hi","html_body":"<p>Hello</p>"}'
# → {"sent":true}
```

> `$API_KEY` 는 export한 셸 안에만 존재한다. `curl` 을 다른 터미널에서 실행한다면
> 그 터미널에서 `API_KEY` 를 다시 export하거나 `.env` 에서 먼저 불러와야 한다.

OpenAPI 문서: <http://127.0.0.1:8000/docs>.

전체 HTTP 엔드포인트 레퍼런스, dry-run 모드, 멱등성(idempotency), Python 클라이언트
SDK: [docs/api.md](docs/api.md).

### 30초 SMTP 스모크 테스트

SMTP 자격증명만 빠르게 검증하고 싶다면 HTTP 서버 없이 바로:

```bash
export SMTP_HOST=smtp.gmail.com
export SMTP_USER=sender@gmail.com
export SMTP_PASSWORD=app-password

python -m email_service test --to me@example.com
#   → SendResult(sent=True, error_code=None, ..., message_id='<...@host>')
```

성공 시 종료 코드 `0`, 실패 시 `1` 과 함께 `error_code` 가 출력된다.

---

## Quickstart — 라이브러리 모드

`email_service` 를 하나의 Python/FastAPI 앱 안에서 직접 임포트한다. 별도의 내부
HTTP 게이트웨이가 필요하지 않을 때 적합하다.

```python
from email_service import SmtpSender, MagicLinkNotifier, OTPNotifier
from email_service.sender import SmtpConfig

sender = SmtpSender(SmtpConfig(
    host="smtp.gmail.com",
    user="sender@gmail.com",
    password="app-password",
))

# 단일 HTML 메일
sender.send("user@example.com", "Hi", "<p>Hello</p>")

# 매직 링크
MagicLinkNotifier(sender, base_url="https://myapp.com").send(
    "user@example.com", "User Name", "<인증 제공자가 만든 불투명한 값 — 자체 인증을 쓴다면 최소 secrets.token_urlsafe(32) 이상>",
)

# OTP
OTPNotifier(sender).send("user@example.com", "User Name", "482901")
```

전체 라이브러리 API(`SmtpSender`, `MagicLinkNotifier`, `OTPNotifier`,
`TemplateNotifier`, 커스텀 notifier, 재시도): [docs/api.md](docs/api.md#library-mode).

HTTP 클라이언트 SDK(`EmailServiceClient`)는 [docs/api.md#library-mode](docs/api.md#library-mode) 참고.

---

## 보안 — 배포 전에 반드시 읽을 것

`email-service` 는 **내부** 서비스로 설계되었다. 셀프호스팅 인증 메일 서비스는 잘못
노출되면 악용될 수 있다. 운영 배포 전 다음 항목을 필수 요구사항으로 다룰 것:

- **공용 인터넷에 직접 노출하지 말 것.** 프라이빗 네트워크/VPC 내부의 리버스 프록시
  또는 API 게이트웨이 뒤에 둘 것.
- **TLS는 엣지에서 종료**(nginx, Traefik, 게이트웨이)할 것.
- **인증 실패 트래픽은 엣지에서 레이트 리밋**할 것. 앱에 내장된 bearer 단위
  레이트 리밋은 *인증된* 요청에만 적용되며, Bearer 토큰 추측 공격을 막아주지 않는다.
- **`/docs` 와 `/metrics` 보호** — 엣지에서 비활성화하거나 인증을 요구할 것.
  `/metrics` 는 `METRICS_REQUIRE_AUTH=true` 설정 권장.
- **`API_KEY`, `WEBHOOK_SECRET`, SMTP 자격증명은 환경 변수 또는 시크릿 매니저에
  저장**할 것. `API_KEY` 는 `openssl rand -hex 32` 로 생성한다. 절대 커밋하지 말 것.

**신뢰 경계:** 이 서비스는 인증 메일을 *발송*만 한다. 로그인 토큰의 생성, 저장,
검증, 만료는 하지 **않는다**. 토큰 엔트로피(`secrets.token_urlsafe(32)` 이상),
만료, 일회성 사용 강제, 재생 방지, 계정 상태 확인은 호출자의 책임이다.

email-service 앞단에 Supabase Auth 또는 다른 인증 제공자를 둔다면, 토큰의 생성과
검증은 email-service가 아니라 그 제공자가 담당한다.
[docs/supabase-auth.md](docs/supabase-auth.md) 참고.

운영 체크리스트 전문: [docs/deployment.md](docs/deployment.md).
취약점 신고: [SECURITY.md](SECURITY.md).

---

## Docker

```bash
cp .env.example .env
# .env 편집: SMTP_HOST / SMTP_USER / SMTP_PASSWORD / API_KEY 설정
#   API_KEY=$(openssl rand -hex 32)

docker compose up -d --build
curl http://127.0.0.1:8000/health   # → {"status":"ok"}
```

제공되는 `docker-compose.yml` 은 편의를 위해 호스트의 `8000:8000` 을 노출한다.
**이 포트를 공용 인터넷에 노출하지 말 것** — 운영 강화 사항은 배포 가이드 참고.

[Mailpit](https://mailpit.axllent.org/) 을 사용한 로컬 개발(실제 SMTP 없이):

```bash
docker compose -f docker-compose.dev.yml up -d --build
# Mailpit UI: http://127.0.0.1:8025
```

---

## 설정

필수 환경 변수: `SMTP_HOST`, `API_KEY`.

필수 변수가 빠지면 서비스는 시작 시점에 즉시 실패한다.

전체 환경 변수 레퍼런스(레이트 리밋, 멱등성, webhook SSRF 허용목록, metrics 인증,
구조화 로그, 재시도 튜닝): [docs/configuration.md](docs/configuration.md).

저장소 루트에 동작 가능한 `.env.example` 이 포함되어 있다.

---

## 웹훅 (비동기 발송)

`/send*` 요청 본문에 `webhook_url` 을 포함하면 발송 결과를 비동기로 받는다.
서비스는 레거시 V1 헤더와 타임스탬프 바인딩된 V2 헤더 양쪽으로 페이로드에 서명한다.
새로 추가하는 수신기는 V2를 검증해야 한다.

웹훅 페이로드 포맷, 서명 검증, V1 → V2 마이그레이션, `docker-compose.dev.yml` 을
사용한 로컬 테스트: [docs/webhooks.md](docs/webhooks.md).

---

## 관측성(Observability)

옵트인 기능이며 기본값은 모두 비활성화:

- **Prometheus metrics** `/metrics` (`METRICS_ENABLED=true`,
  `METRICS_REQUIRE_AUTH=true` 권장).
- **구조화된 JSON 로그**(`EMAIL_SERVICE_LOG_FORMAT=json`). 수신자 주소는 해시
  처리(SHA-256, 앞 8자)되며 평문으로 기록되지 않는다.
- **`X-Request-ID` 전파** — gateway → email-service → SMTP 발송 로그까지 일관 전달.
- **SMTP 재시도** — 라이브러리 모드에서 제한된 지수 백오프(`max_retries=N`).

운영 가이드 전문: [docs/operations.md](docs/operations.md).

---

## 예시

자주 쓰이는 Python 프레임워크용 통합 스니펫:

- [examples/fastapi_integration.py](examples/fastapi_integration.py)
- [examples/django_integration.py](examples/django_integration.py)
- [examples/flask_integration.py](examples/flask_integration.py)
- [examples/integration_test_with_capture.py](examples/integration_test_with_capture.py)
  — 실제 SMTP 서버 없이 `.eml` 캡처 모드로 통합 테스트.

---

## 무엇을 언제 쓸 것인가

| 필요한 것 | 선택지 |
|---|---|
| 관리형 딜리버러빌리티, 바운스, SLA, 대시보드 | Resend / Postmark / SendGrid / Mailgun / Amazon SES |
| 완전한 사용자/세션/RBAC/비밀번호 플로우 | Supabase Auth, Ory Kratos, Keycloak, Authentik, Appwrite |
| 하나의 FastAPI 앱 안에서 쓰는 메일 라이브러리 | [fastapi-mail](https://github.com/sabuhish/fastapi-mail) |
| 기존 SMTP 자격증명을 모든 앱에서 분리하는 내부 HTTP 게이트웨이 | **email-service** |

자체 호스팅 메일 플랫폼 포함 상세 비교: [docs/alternatives.md](docs/alternatives.md).

Supabase Auth와 함께 쓰는 경우:
[Supabase Auth 연동 가이드](docs/supabase-auth.md) 참고 — email-service는 이메일
전송만 담당하고, 토큰/세션/`auth.uid()` 신원은 Supabase Auth가 계속 소유한다.
프로바이더별 인덱스: [docs/providers.md](docs/providers.md).

---

## 개발

```bash
git clone https://github.com/hwan96-ai/email-service.git
cd email-service

pip install -e ".[dev,http]"
python -m pytest tests/ -v
```

테스트는 실제 SMTP 서버에 연결하지 않는다(`smtplib.SMTP` 가 mocking된다).

---

## 라이선스

[MIT](LICENSE).
