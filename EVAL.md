# EVAL — 2026-04-19 · 시도 1회차

## 요약
- ✅ PASS: 8 / 8
- ❌ FAIL: 0 (회귀 0 건 포함)
- ⚠️ UNVERIFIABLE: 0

## 항목별 결과

### ✅ AC-1: 유효한 API 키로 일반 이메일 발송 요청 시 SMTP로 전송되고 성공 응답
- 검증 방법: Tier 1 — `pytest tests/test_api.py`
- 증거: `TestSendEmail::test_success` PASSED. 200 응답 + `{"sent": True}` + `sender.send()` 호출 확인. `test_forwards_optional_fields` 로 `text_body/cc/bcc` 패스스루까지 검증.
- 판정: PASS

### ✅ AC-2: 매직링크 이메일 발송 — 링크 포함 메일 전송
- 검증 방법: Tier 1 — `pytest tests/test_api.py::TestSendMagicLink`
- 증거: `test_success` PASSED. `MagicLinkNotifier.send("u@t.com", "Kim", "abc123")`가 정확한 인자로 호출됨. 링크 구성 로직은 `MagicLinkNotifier` 자체 기존 테스트(`TestMagicLinkNotifier::test_send_contains_link`, `test_token_url_encoded`)로 이미 커버됨.
- 판정: PASS

### ✅ AC-3: OTP 이메일 발송 — 코드 포함 메일 전송
- 검증 방법: Tier 1 — `pytest tests/test_api.py::TestSendOTP::test_success`
- 증거: PASSED. `OTPNotifier.send("u@t.com", "Kim", "123456")` 호출 확인. OTP 렌더링은 기존 `TestOTPNotifier::test_send_contains_code`로 이미 커버됨.
- 판정: PASS

### ✅ AC-4: API 키 누락/오류 → 401, SMTP 미호출
- 검증 방법: Tier 1 — `pytest tests/test_api.py`
- 증거: `test_missing_api_key_returns_401`, `test_wrong_api_key_returns_401` 모두 PASSED. 두 케이스 모두 401 + `sender.send.assert_not_called()` 확인. 매직링크 엔드포인트도 `TestSendMagicLink::test_auth_required`로 동일 확인.
- 판정: PASS

### ✅ AC-5: 필수 필드 누락 → 4xx
- 검증 방법: Tier 1 — `pytest tests/test_api.py::TestSendEmail::test_missing_required_field_returns_422`
- 증거: PASSED. `html_body` 누락 시 422 반환 확인. pydantic `Field(min_length=1)` 기본 동작.
- 판정: PASS

### ✅ AC-6: SMTP 환경변수 누락 시 기동 즉시 실패
- 검증 방법: Tier 1 — `pytest tests/test_api.py::TestStartupValidation`
- 증거: `test_missing_smtp_env_raises` PASSED — `create_app()` 호출 시 `RuntimeError(match="SMTP_HOST")`. `test_missing_api_key_env_raises` PASSED — `match="API_KEY"`. `_required_env` 구현이 빈 문자열/None 모두 거부.
- 판정: PASS

### ✅ AC-E1: SMTP 연결 실패 → 5xx (예외 터짐 없음)
- 검증 방법: Tier 1 — `pytest tests/test_api.py`
- 증거: `TestSendEmail::test_smtp_failure_returns_502` PASSED (sender.send → False → 502). `TestSendOTP::test_failure_returns_502` PASSED. 기존 `SmtpSender.send()`의 `except Exception: return False` 계약을 API가 502로 변환.
- 판정: PASS

### ✅ AC-E2: CRLF 주입 요청은 발송되지 않고 실패 응답
- 검증 방법: Tier 1 — `pytest tests/test_api.py`
- 증거: `test_crlf_in_to_rejected_before_sender`, `test_crlf_in_subject_rejected_before_sender`, `test_crlf_in_cc_rejected_before_sender` 모두 PASSED. 3케이스 모두 422 + `sender.send.assert_not_called()`. 다층 방어: pydantic validator가 1차 차단, 통과해도 `SmtpSender`가 동일 가드로 2차 차단(`test_email_service.py::test_rejects_crlf_in_headers` 통과).
- 판정: PASS

## 추가 발견

### Out of Scope 위반
- 없음. 점검 결과: MCP/CLI 파일 없음, 다중 SMTP 계정 로직 없음, 큐·재시도·레이트 리밋 없음, OAuth/JWT/RBAC 없음, 관리자 UI·웹훅·영속 로그 없음, 기본 `HOST=127.0.0.1`(내부망 전제), Docker/K8s 파일 없음, TemplateNotifier 엔드포인트 없음.

### 회귀
- 없음 (1회차).
- 기존 `tests/test_email_service.py` 20개 테스트도 모두 PASS 유지 (전체 36/36).

### 보안
- 없음. `api.py`/`__main__.py` 내 `password`/`api_key` 참조는 모두 환경변수 로드 또는 파라미터 비교. 하드코딩된 비밀값 없음. `tests/test_api.py`의 `API_KEY = "test-key"`는 테스트 fixture.

## 우선순위
- 없음 (모든 AC PASS).
