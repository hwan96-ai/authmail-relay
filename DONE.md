# DONE — 2026-04-19 · 시도 1회차

## 모드
신규 구현

## 변경된 파일
- `email_service/api.py` — 신규. FastAPI 앱 팩토리, pydantic 요청 모델, Bearer 인증, 3개 엔드포인트(/send, /send/magic-link, /send/otp).
- `email_service/__main__.py` — 신규. `python -m email_service` 엔트리포인트. uvicorn으로 앱 기동.
- `pyproject.toml` — `[project.optional-dependencies]`에 `http = ["fastapi>=0.100", "uvicorn>=0.23"]` 추가. `dev`에 `httpx` 추가(TestClient용).
- `tests/test_api.py` — 신규. 16개 테스트(인증·검증·발송 경로·CRLF 차단·기동 검증).

## 추가된 의존성
- `fastapi>=0.100` — HTTP 서버 프레임워크. AC-1/2/3/4/5 구현의 핵심. Optional extra(`pip install email-service[http]`)로 분리하여 라이브러리로만 쓰는 기존 사용자에게 영향 없음.
- `uvicorn>=0.23` — ASGI 런타임. `python -m email_service` 실행에 필요.
- `httpx>=0.25` (dev) — `fastapi.testclient.TestClient`가 내부적으로 사용.

## 다룬 AC
- [x] **AC-1** — 일반 이메일 발송: `email_service/api.py:108-124` (POST /send). 테스트: `test_api.py::TestSendEmail::test_success`, `test_forwards_optional_fields`.
- [x] **AC-2** — 매직링크 발송: `email_service/api.py:126-137` (POST /send/magic-link). 내부에서 `MagicLinkNotifier`를 재사용. 테스트: `test_api.py::TestSendMagicLink::test_success`.
- [x] **AC-3** — OTP 발송: `email_service/api.py:139-149` (POST /send/otp). 내부에서 `OTPNotifier`를 재사용. 테스트: `test_api.py::TestSendOTP::test_success`.
- [x] **AC-4** — API 키 검증: `email_service/api.py:99-106` (verify_key 의존성). 누락/오류 모두 401 반환 + sender 미호출. 테스트: `test_missing_api_key_returns_401`, `test_wrong_api_key_returns_401`.
- [x] **AC-5** — 필수 필드 검증: pydantic `Field(min_length=1)` + FastAPI 기본 422. 테스트: `test_missing_required_field_returns_422`.
- [x] **AC-6** — 환경변수 누락 시 기동 실패: `email_service/api.py:20-23` (`_required_env`). `create_app()` 호출 시 `RuntimeError` 즉시 발생. 테스트: `test_missing_smtp_env_raises`, `test_missing_api_key_env_raises`.
- [x] **AC-E1** — SMTP 실패 시 502: `email_service/api.py:123-124, 136-137, 148-149`. 기존 `SmtpSender.send()`가 예외를 잡아 `False` 반환 → API에서 502로 변환. 테스트: `test_smtp_failure_returns_502`, `TestSendOTP::test_failure_returns_502`.
- [x] **AC-E2** — CRLF 헤더 인젝션 차단: `email_service/api.py:25-28` (`_no_crlf`) + pydantic `field_validator`. 요청 단계에서 422로 거부되어 sender까지 도달하지 않음(depth-in-defense: sender에도 동일 가드 이미 존재). 테스트: `test_crlf_in_to_rejected_before_sender`, `test_crlf_in_subject_rejected_before_sender`, `test_crlf_in_cc_rejected_before_sender`.

## 실행 방법

### 설치
```bash
pip install -e ".[http,dev]"
```

### 환경변수 설정
```bash
# 필수
export SMTP_HOST=smtp.gmail.com
export SMTP_USER=sender@gmail.com
export SMTP_PASSWORD=app-password
export API_KEY=<임의의-긴-비밀문자열>

# 선택
export SMTP_PORT=587                       # 기본 587
export SMTP_FROM=noreply@mycompany.com     # 기본은 SMTP_USER와 동일
export SMTP_USE_TLS=true                   # 기본 true
export MAGIC_LINK_BASE_URL=https://myapp.com  # /send/magic-link 사용 시만 필수
export HOST=127.0.0.1                      # 기본 127.0.0.1 (내부망 전제)
export PORT=8000                           # 기본 8000
```

### 기동
```bash
python -m email_service
```

### 호출 예시
```bash
# 일반 발송
curl -X POST http://127.0.0.1:8000/send \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to":"user@example.com","subject":"Hi","html_body":"<p>Hello</p>"}'

# 매직링크
curl -X POST http://127.0.0.1:8000/send/magic-link \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to":"user@example.com","user_name":"김땡땡","token":"abc123"}'

# OTP
curl -X POST http://127.0.0.1:8000/send/otp \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to":"user@example.com","user_name":"김땡땡","code":"123456"}'
```

### 테스트
```bash
python -m pytest tests/ -v
```

## 알려진 제약 / 주의사항
- **내부망 전제**: 기본 `HOST=127.0.0.1`. 외부 공개 시에는 앞단 TLS 종단/WAF가 별도로 필요하다(SPEC 범위 밖).
- **단일 API 키**: 모든 호출자가 같은 키를 공유. 호출자별 구분이 필요해지면 확장 필요.
- **MAGIC_LINK_BASE_URL 미설정**: 매직링크 엔드포인트만 503으로 실패. SMTP·API 키만 있으면 `/send`, `/send/otp`는 정상 동작.
- **TemplateNotifier 엔드포인트 없음**: SPEC Out of Scope에 따라 1차에서 제외.

## 다음 단계 제안
- 외부 SMTP로 실제 발송 수동 검증(사내 메일 1건).
- 배포 시: 환경변수 주입 방식 확정(.env / Secret Manager) 및 서비스 등록(systemd/Docker) 결정.
