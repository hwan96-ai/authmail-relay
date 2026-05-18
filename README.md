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

## 보안 모델 / Security Model

- **매직링크 토큰 엔트로피는 호출자 책임이다.** 본 패키지는 `MagicLinkNotifier` 로 전달된 `token` 문자열을 그대로 URL 쿼리에 인코딩만 할 뿐, 생성·검증·저장하지 않는다. 호출자는 최소 `secrets.token_urlsafe(32)` 수준의 엔트로피로 토큰을 생성하고, 만료·1회용 사용 등 라이프사이클을 별도로 관리해야 한다.
- **`API_KEY` 는 공유 비밀** 이며 `Authorization: Bearer` 헤더로 전달된다. `openssl rand -hex 32` 등으로 충분히 길고 무작위인 값을 사용하고, 절대 저장소에 커밋하지 않는다.
- **CRLF 헤더 인젝션** 은 sender 단계와 Pydantic 단계 모두에서 차단된다. `SMTP_FROM` 도 부팅 시 검증된다.
- **STARTTLS** 가 서버에서 광고되지 않는 경우 `use_tls=True` 발송은 명시적으로 실패한다 (다운그레이드 / STRIPTLS 방어).

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

## Deployment

운영 환경 배포 전 반드시 확인할 사항들. 이 섹션을 건너뛰면 본 서비스가 의도한 보안/안정성 보장이 무너질 수 있다.

### 워커 수 (single vs multi)

본 서비스의 다음 상태는 **in-memory, per-process**이다:

- **Rate limit** (`API_RATE_LIMIT_PER_MINUTE`): 워커당 cap. uvicorn workers=N 이면 실제 처리량 = N × cap.
- **Idempotency cache** (`API_IDEMPOTENCY_TTL_SECONDS`): 워커당 dedup. 같은 `Idempotency-Key` 가 다른 워커에 분산되면 dedup 깨짐.
- **Per-key concurrency lock**: 워커당 직렬화. 워커 N개면 같은 키가 최대 N회 동시 처리 가능.

권장:

- **단일 워커 + sticky LB**: 가장 단순. `uvicorn email_service --workers 1` 또는 같은 워커로 라우팅하는 LB. 본 서비스가 의도한 정확한 동작.
- **멀티 워커**: rate-limit / idempotency 정확성이 SLA 일부면 외부 store (Redis 등) 로 교체 필요 — 현재 미지원, P1 향후 항목.

### 본문 크기 제한

Pydantic 의 `max_length` 가 422 거부를 보장하지만, FastAPI 가 요청 본문을 **메모리에 전체 buffer 한 후** Pydantic 을 실행한다. 따라서 100 MB 요청이 들어오면 거부는 되어도 메모리는 일시 점유.

**필수**: 리버스 프록시에서 body cap 설정.

```nginx
# /etc/nginx/sites-available/email-service
location / {
    client_max_body_size 12m;   # 10 MB body cap + 2 MB headers/overhead
    proxy_pass http://email-service:8000;
}
```

uvicorn 자체에는 명시적 body cap 옵션이 없음 — proxy 단에서 차단.

### 환경변수 reference

| 변수 | 필수 | 기본 | 설명 |
|------|------|------|------|
| `SMTP_HOST` | ✅ | — | SMTP 호스트 |
| `SMTP_PORT` | | `587` | SMTP 포트 |
| `SMTP_USER` | | `""` | SMTP 사용자 (옵션) |
| `SMTP_PASSWORD` | | `""` | SMTP 비밀번호 (옵션) |
| `SMTP_FROM` | | `SMTP_USER` | From 헤더 주소 |
| `SMTP_USE_TLS` | | `true` | STARTTLS 사용 |
| `API_KEY` | ✅ | — | Bearer 인증 토큰. `openssl rand -hex 32` 권장 |
| `API_RATE_LIMIT_PER_MINUTE` | | `60` | `/send*` 의 per-bearer 분당 호출 cap. `0` 이면 비활성. |
| `API_IDEMPOTENCY_TTL_SECONDS` | | `86400` | `Idempotency-Key` 캐시 TTL (초). `0` 이면 비활성. |
| `WEBHOOK_ALLOW_HOSTS` | | `""` | `webhook_url` SSRF 검증의 hostname allowlist (콤마 구분). 내부 콜백용. |
| `WEBHOOK_ALLOW_LOOPBACK` | | `false` | `1` 이면 loopback/private IP 허용. **테스트 전용 — production 금지** |
| `EMAIL_SERVICE_DEBUG` | | `false` | `1` 이면 smtplib 디버그 출력 (**SMTP 비밀번호가 stderr 에 base64 로 출력됨 — production 절대 금지**) |
| `MAGIC_LINK_BASE_URL` | | unset | 설정 시 `/send/magic-link` 활성화 |
| `METRICS_ENABLED` | | `false` | `/metrics` 엔드포인트 활성화 |
| `METRICS_REQUIRE_AUTH` | | `false` | `/metrics` 에 Bearer 인증 강제 |
| `EMAIL_SERVICE_LOG_FORMAT` | | `text` | `json` 시 구조화 로그 |
| `EMAIL_TEST_CAPTURE_DIR` | | unset | 설정 시 SMTP 미접속, `.eml` 파일 저장 (테스트용) |

### Webhook signature: V1 → V2 migration

본 서비스는 webhook payload 에 두 가지 서명 헤더를 동시 전송한다:

- `X-Email-Service-Signature` (V1): HMAC-SHA256(secret, body) — **replay 공격에 취약**.
- `X-Email-Service-Signature-V2`: HMAC-SHA256(secret, `"<timestamp>.<body>"`)
- `X-Email-Service-Timestamp`: Unix epoch seconds

**V2 채택 권장 (수신자 측 마이그레이션 절차)**:

1. `X-Email-Service-Timestamp` 읽기.
2. `abs(now - timestamp) > 300` (5분) 이면 거부 — replay window 차단.
3. `hmac_sha256(secret, f"{timestamp}.{body}")` 를 V2 헤더와 constant-time 비교.

V1 헤더는 **향후 major version 에서 제거 예정**. CHANGELOG 참조.

### Release 자동화 (PyPI)

`release.yml` 은 **2-step manual gate** 모델이다. tag push 만으로는 PyPI 에 publish 되지 않는다.

1. **tag push** → `build-and-smoke` job 만 실행. wheel 빌드 + smoke import + tag/version 일치 검증까지만 수행. PyPI 는 건드리지 않는다.
2. **Actions → `release` → "Run workflow"** (workflow_dispatch) 에서 publish 할 tag (예: `v0.4.0`) 를 입력하고 수동 실행. 이 dispatch 자체가 사람 승인 게이트다. `build-and-smoke` 가 다시 검증된 뒤 `publish` job 이 PyPI 로 업로드한다.

왜 분리: private repo 에서는 GitHub Environment "Required reviewers" UI 가 플랜에 따라 노출되지 않을 수 있어 `environment: pypi` 게이트만으로는 manual approval 을 보장하기 어렵다. workflow_dispatch 트리거 자체를 사람 행동으로 만들어 이 빈틈을 막는다. Environment Required reviewers 가 활성화돼 있다면 그 위에 추가로 얹히는 defense-in-depth.

- 모든 GitHub Actions 는 commit SHA 로 핀 (mutable tag 금지).
- 잘못된 publish 는 yank 만 가능, 버전명 영구 소진. [`docs/runbooks/pypi-yank-hotfix.md`](docs/runbooks/pypi-yank-hotfix.md) 참조.

### 운영 runbook

장애 / 회전 / 핫픽스 절차:

- [`docs/runbooks/smtp-outage.md`](docs/runbooks/smtp-outage.md)
- [`docs/runbooks/webhook-outage.md`](docs/runbooks/webhook-outage.md)
- [`docs/runbooks/api-key-rotation.md`](docs/runbooks/api-key-rotation.md)
- [`docs/runbooks/pypi-yank-hotfix.md`](docs/runbooks/pypi-yank-hotfix.md)
- [`docs/runbooks/smtp-disconnect-uncertain.md`](docs/runbooks/smtp-disconnect-uncertain.md)

## Operations

운영 환경에서 발송 성공률·실패 사유·지연을 관측하기 위한 옵트인 기능들이다. 모두 환경변수로 켤 수 있으며, 기본값은 모두 off — 기존 동작과 100% 호환된다.

### Prometheus 메트릭 (`/metrics`)

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `METRICS_ENABLED` | `false` | `true` 일 때 `GET /metrics` 활성화. `prometheus-client` 설치 필요. |
| `METRICS_REQUIRE_AUTH` | `false` | `true` 일 때 `/metrics` 호출에도 `Authorization: Bearer $API_KEY` 강제. |

활성화:

```bash
pip install "email-service[http]"   # prometheus-client 포함
METRICS_ENABLED=true python -m email_service
curl http://127.0.0.1:8000/metrics
```

노출되는 시리즈:

- `email_send_total{result, error_code}` — Counter. `result` 는 `success` / `failure`, `error_code` 는 `crlf_in_header` / `smtp_auth_failed` / `smtp_connection` / `smtp_timeout` / `smtp_transient` / `recipient_refused` / `starttls_unsupported` / `unknown` (`success` 시 빈 문자열).
- `email_send_duration_seconds` — Histogram. SMTP 호출 한 건의 종단 지연 (초).
- `email_send_active` — Gauge. 현재 처리 중인 발송 건수.
- `email_retry_attempts_total{reason}` — Counter. 재시도 시도 횟수 (Phase 4 `max_retries > 0` 일 때).
- `email_webhook_failed_total` — Counter. webhook 콜백 전달이 최종 실패한 건수.

샘플 출력:

```
# HELP email_send_total Total email send attempts
# TYPE email_send_total counter
email_send_total{result="success",error_code=""} 42.0
email_send_total{result="failure",error_code="smtp_connection"} 3.0
email_send_duration_seconds_bucket{le="0.5"} 41.0
```

권장 알람 (Prometheus):

```yaml
- alert: EmailFailureRateHigh
  expr: rate(email_send_total{result="failure"}[5m]) > 0.05
  for: 10m
  annotations:
    summary: "email-service failure rate above 5% for 10 minutes"
```

### 구조화 로그 (JSON)

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `EMAIL_SERVICE_LOG_FORMAT` | `text` | `json` 일 때 `python-json-logger` 로 JSON 한 줄 로그 출력. |
| `EMAIL_SERVICE_DEBUG` | `0` | `1` 일 때 `smtplib.set_debuglevel(1)` 활성화 (개발 전용). |

PII 안전성: 수신자 이메일 주소는 절대 평문으로 로그에 남지 않는다. 모든 발송 로그는 SHA-256 해시 앞 8자(`to_hash`) 로 표기되며, `error_code`·`duration_ms`·`message_id`·`request_id` 가 함께 기록된다.

> ⚠️ **보안 주의**: `EMAIL_SERVICE_DEBUG=1` 은 `smtplib` 의 디버그 출력을 stderr 로 보내며, 여기에는 `AUTH PLAIN <base64>` 라인이 포함된다 (즉, 비밀번호가 base64 로 노출). 절대 운영 환경에서는 켜지 말 것. 표준 라이브러리 한계상 이 라인을 안전하게 마스킹할 수 없다.

### 분산 트레이싱 (`X-Request-ID`)

모든 요청은 `X-Request-ID` 헤더를 echo 하며, 헤더가 없으면 UUID 가 자동 발급된다. 이 ID 는 SMTP 발송 로그까지 그대로 전파되어, 게이트웨이 → email-service → SMTP 의 풀 트레이스를 단일 ID 로 grep 할 수 있다.

```bash
curl -H "Authorization: Bearer $API_KEY" \
     -H "X-Request-ID: trace-abc-123" \
     -X POST http://127.0.0.1:8000/send \
     -d '{"to":"u@t.com","subject":"hi","html_body":"<p>x</p>"}'
# Response includes: X-Request-ID: trace-abc-123
```

### SMTP 재시도 (`max_retries`)

라이브러리 모드에서만 사용. 기본값 `0` 으로 기존 동작과 호환된다.

```python
from email_service import SmtpSender, SmtpConfig

sender = SmtpSender(
    SmtpConfig(host="smtp.gmail.com", port=587, user="u", password="p"),
    max_retries=2,                  # 1 회 시도 + 2 회 재시도 = 최대 3 회
    backoff_seconds=(1, 5, 25),     # 지수 백오프; 마지막 값으로 클램프
)
```

재시도 대상: `SMTPServerDisconnected`, `SMTPConnectError`, `socket.timeout`, SMTP 4xx 응답. 5xx 영구 실패와 부분 거부(partial refusal) 는 즉시 반환되어 같은 수신자에게 중복 발송되지 않는다. `Message-ID` 는 재시도 전체에서 동일하게 유지된다 (MTA dedup).

각 재시도는 `email_retry_attempts_total{reason}` 카운터를 증가시킨다.

### Test mode — .eml 캡처 (`EMAIL_TEST_CAPTURE_DIR`)

환경변수 `EMAIL_TEST_CAPTURE_DIR` 가 set 되면 SMTP 호출을 건너뛰고 메시지를 `<message_id>.eml` 파일로 디렉토리에 저장한다. 통합 테스트에서 SMTP 없이 메일 내용을 검증할 때 사용.

```bash
EMAIL_TEST_CAPTURE_DIR=/tmp/outbox pytest tests/
```

전체 예시는 [examples/integration_test_with_capture.py](examples/integration_test_with_capture.py) 참고.

`dry_run` (HTTP `X-Dry-Run: true`) 과 다름: dry-run 은 페이로드 검증 only (메시지 빌드 안 함), capture mode 는 실제 MIME 메시지를 생성하여 디스크에 저장 (헤더·바디 검증 가능).

### Webhook 콜백 (비동기 발송 통지)

`webhook_url` 을 `POST /send` (또는 `/send/magic-link`, `/send/otp`) 의 body 에 포함하면 발송이 백그라운드로 처리되고 응답은 즉시 `{"sent": false, "status": "accepted"}` 로 반환된다. 최종 결과는 다음 페이로드로 webhook URL 에 POST 된다:

```json
{
  "message_id": "<...@host>",
  "status": "delivered",
  "error_code": null,
  "refused": [],
  "sent_at": "2026-05-15T10:00:00+00:00",
  "attempts": 1
}
```

`webhook_secret` 도 함께 보내면 body 전체에 대한 HMAC-SHA256 서명이 `X-Email-Service-Signature: sha256=<hex>` 헤더로 포함된다.

수신자 측 검증 (Python):

```python
import hmac, hashlib
sig = request.headers["X-Email-Service-Signature"]
expected = "sha256=" + hmac.new(SECRET.encode(), request.body, hashlib.sha256).hexdigest()
assert hmac.compare_digest(sig, expected)
```

Webhook 전달 자체는 `(1s, 10s, 60s)` 백오프로 최대 3 회 재시도된다. 최종 실패 시 `email_webhook_failed_total` 메트릭이 증가하며 발송 자체에는 영향을 주지 않는다 (이미 발송 완료).

#### 로컬 webhook 테스트

`docker-compose.dev.yml` 에 포함된 `webhook-sink` (httpbin) 서비스로 페이로드를 즉시 확인할 수 있다:

```bash
docker compose -f docker-compose.dev.yml up -d
curl -H "Authorization: Bearer $API_KEY" \
     -X POST http://127.0.0.1:8000/send \
     -H "Content-Type: application/json" \
     -d '{"to":"u@t.com","subject":"hi","html_body":"<p>x</p>",
          "webhook_url":"http://webhook-sink/post","webhook_secret":"shh"}'
# httpbin echoes the received POST at http://127.0.0.1:8080/post
docker compose -f docker-compose.dev.yml logs webhook-sink
```

---

## 사용 방식

| 모드 | 설치 | 실행 | 용도 |
|---|---|---|---|
| 라이브러리 | `pip install email-service` | Python 코드에서 `import` | 같은 프로세스 안에서 메일 발송 |
| HTTP 서비스 | `pip install "email-service[http]"` | `python -m email_service` | 다른 서비스가 REST 로 호출 |

설치 명령 전체 예시:

```bash
# 라이브러리로만 사용 (PyPI)
pip install email-service

# HTTP 서비스로 띄워서 사용 (PyPI)
pip install "email-service[http]"

# 아직 PyPI 에 게시 안 된 버전을 미리 받고 싶을 때 (git 직접 설치)
pip install git+https://github.com/hwan96-ai/email-service.git
pip install "email-service[http] @ git+https://github.com/hwan96-ai/email-service.git"
```

요구 사항: Python **3.10+**.

---

## 30초 안에 첫 메일 보내기

`python -m email_service test` 서브커맨드가 환경변수만으로 SMTP 설정을 검증하고 테스트 메일 한 통을 즉시 발송한다. 발송 결과가 `SendResult` 형태로 stdout 에 떨어진다.

```bash
# 1) 설치
pip install email-service

# 2) 환경변수 (Gmail 예시 — 앱 비밀번호 권장)
export SMTP_HOST=smtp.gmail.com
export SMTP_USER=sender@gmail.com
export SMTP_PASSWORD=app-password
# API_KEY 는 test 서브커맨드에서는 필요 없음 (HTTP 서버 모드 전용)

# 3) 발송
python -m email_service test --to me@example.com
#   → SendResult(sent=True, error_code=None, ..., message_id='<...@host>')
#   exit 0 on success, exit 1 on failure (with error_code printed)
```

자세한 옵션: `python -m email_service test --help`.

---

## 빠른 시작

### HTTP 서비스로 띄워 curl 로 테스트

```bash
# 1) 설치
pip install "email-service[http]"

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

## 로컬 메일 테스트 (Mailpit)

실제 메일을 발송하지 않고 로컬에서 발송 결과를 눈으로 확인하려면 `docker-compose.dev.yml` 을 쓴다. [Mailpit](https://mailpit.axllent.org/) 이 SMTP 서버 + 웹 UI 를 같이 제공한다.

```bash
# 빌드 & 기동 (email-service + mailpit)
docker compose -f docker-compose.dev.yml up -d --build

# 헬스체크
curl http://127.0.0.1:8000/health
# → {"status":"ok"}

# 메일 발송 (API_KEY 는 dev-secret 으로 하드코딩)
curl -X POST http://127.0.0.1:8000/send/otp \
  -H "Authorization: Bearer dev-secret" \
  -H "Content-Type: application/json" \
  -d '{"to":"user@example.com","user_name":"홍길동","code":"482901"}'
```

발송된 메일은 Mailpit 웹 UI 에서 확인한다:

- Mailpit UI: http://127.0.0.1:8025
- Mailpit SMTP: `mailpit:1025` (컨테이너 내부), `127.0.0.1:1025` (호스트)

개발용 compose 의 환경변수는 다음과 같이 기본값이 들어 있어 `.env` 파일이 필요 없다.

| 변수 | 값 | 비고 |
|---|---|---|
| `SMTP_HOST` | `mailpit` | |
| `SMTP_PORT` | `1025` | |
| `SMTP_USER` / `SMTP_PASSWORD` | 빈 값 | Mailpit 은 SMTP AUTH 가 필요 없다 |
| `SMTP_USE_TLS` | `false` | |
| `API_KEY` | `dev-secret` | |
| `MAGIC_LINK_BASE_URL` | `http://localhost:3000` | |

정지:

```bash
docker compose -f docker-compose.dev.yml down
```

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

### Python 클라이언트 SDK

`email-service[http]` 로 설치하면 `EmailServiceClient` 를 import 해서 바로 쓸 수 있다. Bearer 헤더 자동 부착, dry-run 헤더 자동 전환, 4xx/5xx 시 예외 발생까지 담당한다.

```python
from email_service.client import EmailServiceClient

with EmailServiceClient("http://email-service:8000", "secret") as client:
    client.health()
    # 일반 메일
    client.send(
        to="user@example.com",
        subject="Hi",
        html_body="<p>Hello</p>",
        text_body="Hello",
        cc=["cc@example.com"],
        bcc=["bcc@example.com"],
    )
    # 매직링크 / OTP
    client.send_magic_link("user@example.com", "홍길동", "abc123")
    client.send_otp("user@example.com", "홍길동", "482901")
```

생성자: `EmailServiceClient(base_url, api_key, timeout=10.0)`. context manager 를 지원하며, 직접 `close()` 를 호출해도 된다. 내부적으로 `httpx.Client` 를 사용하므로 `http` extras 가 필요하다.

### Dry-run

메일을 실제로 발송하지 않고 payload 가 유효한지만 확인하고 싶을 때 `X-Dry-Run` 헤더를 쓴다.

- 헤더 값: `true` / `1` / `yes` (대소문자 무시) 는 dry-run 으로 처리된다.
- 적용 대상: `/send`, `/send/magic-link`, `/send/otp`
- 동작: API Key 인증과 Pydantic validation 은 그대로 수행되지만, SMTP 는 호출되지 않는다.
- 응답: `200 {"sent": false, "dry_run": true, "message": "Email payload is valid"}`

```bash
curl -X POST http://127.0.0.1:8000/send/otp \
  -H "Authorization: Bearer $API_KEY" \
  -H "X-Dry-Run: true" \
  -H "Content-Type: application/json" \
  -d '{"to":"user@example.com","user_name":"홍길동","code":"482901"}'
# → {"sent":false,"dry_run":true,"message":"Email payload is valid"}
```

SDK 에서는 `dry_run=True` 만 넘기면 된다.

```python
client.send_otp("user@example.com", "홍길동", "482901", dry_run=True)
```

### 직접 httpx 로 호출

SDK 를 쓰지 않고 raw 로 호출하는 예시.

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

### Node.js (fetch)

언어 무관하게 REST 로 호출 가능. Node 18+ 기본 내장 `fetch` 예시.

```javascript
const resp = await fetch("http://email-service:8000/send/otp", {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${process.env.EMAIL_API_KEY}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    to: "user@example.com",
    user_name: "홍길동",
    code: "482901",
  }),
});

if (!resp.ok) {
  throw new Error(`email-service failed: ${resp.status}`);
}

console.log(await resp.json());   // { sent: true }
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
│   ├── api.py             # FastAPI 앱 (create_app) + Pydantic 모델 + 인증 + dry-run
│   ├── client.py          # EmailServiceClient — HTTP SDK (httpx 기반)
│   ├── sender.py          # SmtpConfig, SmtpSender — SMTP 발송 코어
│   └── notifiers.py       # Notifier(ABC), MagicLinkNotifier, OTPNotifier, TemplateNotifier
├── tests/
│   ├── test_email_service.py   # sender + notifier 유닛 테스트
│   ├── test_api.py             # HTTP API 통합 테스트
│   └── test_client.py          # EmailServiceClient SDK 테스트
├── docker-compose.yml         # 운영용 compose
├── docker-compose.dev.yml     # 개발용 compose (Mailpit 포함)
├── pyproject.toml             # 패키지 메타 + optional extras (dev, http)
└── README.md
```
