# Refactor Gate 검증 결과 — email-service

세션: `gate-code-2026-05-16-001`
스코프: 전체 (`email_service/` 10 files, 1868 LOC)
브랜치: `claude/cool-bouman-70eb80` (master 기준)
테스트 baseline: 124 pass, 1 skip

## 판정
🟡 **REFACTOR NEEDED** — 코드는 동작하지만, **5개의 P0 프로덕션 위험**과 구조적 부채가 누적되어 다음 기능 추가 전에 처리 권장.

판정 근거:
- 4개 리뷰어 중 3+가 동시에 지적한 P0: 5건 (threadpool 고갈, SSRF, 사이즈 제한, 레이트 리밋, 동기 sleep)
- 회귀를 만든 변경은 없음 → BLOCKING 아님
- 다만 외부 노출 HTTP 서비스 특성상 P0는 무시 못 함

---

## 통합 이슈 리스트

### P0 (수정 안 하면 프로덕션 장애/사고)

#### P0-1. [review, adversarial, edge-cases] BackgroundTasks + 동기 webhook 재시도 → threadpool starvation
- **위치**: `api.py:286,289`, `webhooks.py:33-95`, `sender.py:277`
- **문제**: `_run_and_notify`가 sync로 BackgroundTasks에 등록됨. webhook 재시도가 `time.sleep(1, 10, 60)` = 최대 71초, SMTP 재시도가 추가 31초. Starlette 기본 threadpool ~40 → 40 동시 webhook 호출만으로 모든 sync 라우트(`/health` 포함) 굶주림 → k8s liveness fail → pod restart.
- **수정안**: 
  1. webhook 백오프 단축 `(1, 2, 5)` + jitter
  2. `httpx.AsyncClient`로 전환하여 async path로 통합, 또는
  3. 자체 소유 `ThreadPoolExecutor(max_workers=N)` 분리

#### P0-2. [review, adversarial, edge-cases] webhook_url SSRF
- **위치**: `api.py:51`, `webhooks.py:33-65`
- **문제**: `SendEmailRequest.webhook_url`에 validator 없음. `http://169.254.169.254/...` (AWS metadata), `http://localhost:8500/...` (Consul), file://, RFC1918 모두 통과. API_KEY 유출 시 내부 망 정찰 가능.
- **수정안**: 
  - https/http allowlist scheme만 허용
  - hostname resolve 후 loopback/link-local/private/IPv6 ULA 차단
  - 환경변수 `WEBHOOK_ALLOWED_HOSTS` allowlist 지원

#### P0-3. [review, adversarial, edge-cases] 본문/제목 사이즈 제한 없음 → OOM
- **위치**: `api.py:51` (SendEmailRequest)
- **문제**: `Field(min_length=1)`만 있고 `max_length` 없음. 100MB body × 10 동시 → ~2GB resident → OOMKill. `msg.as_string()` (sender.py:347)가 메모리 2배.
- **수정안**: 
  - `html_body`/`text_body`: `max_length=10_000_000` (10MB)
  - `subject`: `max_length=998` (RFC 5322)
  - `to`/`cc`/`bcc`: `max_length=100` (개수)
  - uvicorn `--limit-max-requests`, nginx `client_max_body_size`

#### P0-4. [review, adversarial] `/send*` 레이트 리밋 없음 + 동기 retry sleep
- **위치**: `api.py:158-161, 305-352`, `sender.py:277, 392-412`
- **문제**: 단일 공유 bearer token. per-key throttle, per-recipient cooldown, daily cap 없음. 키 유출 시 SMTP reputation 분 단위로 파괴 (SES suspension). 또한 sync 라우트에서 SMTPSender.send()가 `time.sleep` 최대 31초 → threadpool 추가 압박.
- **수정안**: 
  - `slowapi` 토큰 버킷 (per bearer + per recipient)
  - 재시도 총 sleep budget 캡 (예: 합계 ≤10s)
  - SMTPAuth 에러는 502 body에 상세 노출 금지 (smtplib repr가 user/host 포함)

#### P0-5. [edge-cases] SMTP 부분 실패 시 재시도 → 중복 발송
- **위치**: `sender.py:225-291`
- **문제**: `SMTPServerDisconnected`가 `sendmail()` *완료 후* 발생해도 `ERR_SMTP_CONNECTION`으로 분류돼 재시도. 수신자는 메일을 받았는데 재시도가 또 발송. 가장 위험한 silent failure.
- **수정안**: 
  - `sendmail()` 성공 플래그를 시점 기준으로 분리
  - 또는 idempotency key를 SMTP Message-ID로 강제 → 같은 ID 재전송 시 SMTP 서버단 중복 제거 의존
  - 적어도 `_safe_send_after_data` 같은 phase 추적

---

### P1 (강력 권장 — 리팩토링 + 보안)

#### P1-1. [bmad, adversarial] `sender.py` god-method (`SmtpSender.send` 170 LOC, 6 책임)
- **위치**: `sender.py:126-291`
- **문제**: validation + MIME 빌드 + capture-mode + retry + metrics + logging 한 함수. capture-mode가 hardcoded env-var 사이드 채널.
- **수정안**: `_build_message()`, `_send_with_retry()`, `_record_send_metrics()`로 분리. capture는 `MessageWriter` 인터페이스로 추출.

#### P1-2. [bmad, adversarial] `client.py` vs `async_client.py` 99% 중복
- **위치**: `client.py:69-158` ↔ `async_client.py:58-143`
- **문제**: 동기/비동기 클라이언트가 거의 동일. 한쪽 버그 수정이 자동으로 다른 쪽에 안 옴.
- **수정안**: 공통 transport 인터페이스 추출 또는 codegen.

#### P1-3. [bmad] `api.py`가 5가지 책임 혼재 (443 LOC)
- **위치**: `api.py:1-443`
- **문제**: schemas + env loading + DI + routes + background plumbing 한 파일.
- **수정안**: `schemas.py`, `settings.py`, `dependencies.py`, `routes.py`로 분리.

#### P1-4. [review, adversarial] 멱등성 키 없음
- **위치**: `api.py:51` (SendEmailRequest)
- **문제**: 504 후 재시도하면 이중 발송. OTP에서 특히 위험.
- **수정안**: `idempotency_key: Optional[str]` 필드 + 짧은 TTL 캐시 (Redis or in-memory).

#### P1-5. [review] retry 백오프에 jitter 없음
- **위치**: `sender.py:120`, `webhooks.py:94`
- **문제**: 결정적 backoff → SMTP/webhook 동시 회복 시 thundering herd.
- **수정안**: `delay * (0.5 + random())` 적용.

#### P1-6. [review, adversarial] webhook HMAC이 직렬화된 JSON 위 → 검증 깨짐
- **위치**: `webhooks.py:51`
- **문제**: 수신자가 JSON re-serialize 하면 서명 깨짐. 결국 검증을 끄게 됨.
- **수정안**: "raw bytes 검증" 문서화 + timestamp 헤더 + replay protection.

#### P1-7. [review] `request_id` 가 notifier 경로에 전파 안 됨
- **위치**: `notifiers.py:166,206`, `api.py:385,426`
- **문제**: magic-link/OTP 경로 trace correlation 끊김.
- **수정안**: `request_id` kwarg 전체 경로 통과.

#### P1-8. [review] `EMAIL_SERVICE_DEBUG`가 stderr에 base64 password 출력
- **위치**: `sender.py:311-312`
- **문제**: 프로덕션에서 debug=1 사고 → journald에 자격증명.
- **수정안**: prod 환경 감지 시 거부 + 시작 시 loud warning + AUTH 라인 redacting 로그 필터.

#### P1-9. [adversarial] `/send`의 `sent` 필드 의미 혼동
- **위치**: `api.py:329-333`
- **문제**: `sent=False`가 "큐잉됨"과 "전송 실패"를 동시에 의미.
- **수정안**: `status: "sent" | "queued" | "failed"` enum 도입.

#### P1-10. [adversarial] Prometheus counter multiprocess-unsafe + SIGTERM drain 없음
- **위치**: `metrics.py:33`, `api.py:271-289`
- **문제**: 멀티 워커에서 카운터 한 워커 분만 노출됨. 배포 시 in-flight email 손실.
- **수정안**: `prometheus_client.multiprocess` 모드 + graceful shutdown handler.

---

### P2 (코드 품질)

- **api.py:194**: `X-Request-ID` 검증 없음 (길이 ≤64, charset)
- **api.py:201-209**: `METRICS_REQUIRE_AUTH` 요청마다 env 재읽기 — boot 시 1회로
- **api.py:142**: `int(SMTP_PORT)` 크래시 메시지 불친절
- **api.py:45,49**: `pydantic.EmailStr` 미사용 → RFC 검증 없음
- **api.py:346-352, 394-400, 435-441**: 응답 shimming 3중 중복
- **sender.py:175-181**: capture filename에 `:` 포함 시 Windows에서 OSError
- **sender.py:500**: `except Exception` → ERR_UNKNOWN. 5xx permanent와 구분 못 함
- **sender.py:413-436**: SMTP permanent error code 분류 누락 (`ERR_SMTP_PERMANENT`)
- **webhooks.py:59,65**: 매 호출마다 `httpx.Client()`; pool 재사용 X; 응답 body 크기 캡 X
- **webhooks.py**: 비-2xx response body 폐기 → 디버깅 불가
- **client.py:147 / async_client.py:131**: bare `except Exception`이 JSON-decode 에러 삼킴
- **`_truthy`/`_is_dry_run` 3곳 중복**: 한 곳으로 통합
- **`Notifier` ABC**: TemplateNotifier가 따르지 않음 → 추상화 깨짐
- **`_NoOpMetric`**: 사용 안 되는 API 표면(`time()`, `__enter__`)

### P3 (참고)

- `sender.py:124`: 빈 tuple 입력 시 silent `(1,)` 전환 → raise
- `notifiers.py:163-165`: text-body link URL escape 안 됨 (HTML branch만 escape)
- `__main__.py:30`: `HOST=127.0.0.1` 기본값이 컨테이너 사용자 놀라게 함
- `notifiers.py`: 한국어/일본어 subject RFC 2047 인코딩 명시 처리 없음
- `logging_config.py`: `hash_recipient` salt 상수면 PII 식별 가능 — 미확인

---

## 테스트 갭

### 추가 필요한 시나리오 (우선순위)
1. **`test_smtp_partial_failure.py`** — `sendmail()` 직후 disconnect, 중복 발송 회귀 방지 (P0-5 잡힘)
2. **`test_webhook_security.py`** — SSRF 거부 (loopback, link-local, RFC1918) (P0-2)
3. **`test_input_limits.py`** — 10MB body, 100명 recipients 거부 (P0-3)
4. **`test_idempotency.py`** — 같은 키로 2번 호출 → 1번만 발송 (P1-4)
5. **`test_retry_backoff.py`** — `time.sleep` 호출 시퀀스 + jitter 분포 (P1-5 보호)
6. **`test_env_parsing.py`** — `SMTP_USE_TLS=yes/1/TRUE` 모호값 거부
7. **`test_i18n_headers.py`** — 한국어 subject, non-ASCII display name
8. **`test_client_error_paths.py`** — 비-JSON 502 응답에서 sync/async client 동작

---

## 회귀 위험 영역

P0-1 (threadpool) 와 P0-4 (rate limit) 수정은 **API 동작 변경**이므로 회귀 테스트 보강 필수:
- 기존 `sent=False` 응답 클라이언트가 어떻게 해석하는지 확인 (P1-9 의존)
- BackgroundTasks → AsyncTask 전환 시 webhook 순서/배달 보장 변동 가능
- 레이트 리밋 추가 시 기존 통합 테스트가 429 받을 수 있음 → test fixture에 bypass 키 필요

---

## 다음 단계 권장

이 audit은 **수정을 실행하지 않음**. P0 5건은 모두 외부 노출 행동 변경을 동반하므로 사용자 검토 후 단계적 처리 권장:

### 권장 처리 순서
1. **Sprint 1 (보안 긴급)**: P0-2 SSRF + P0-3 사이즈 제한 + P0-4 레이트 리밋
2. **Sprint 2 (안정성)**: P0-1 threadpool + P0-5 중복 발송
3. **Sprint 3 (구조)**: P1-1 ~ P1-3 분해 + P1-2 클라이언트 중복 제거
4. **Sprint 4 (관측/회복)**: P1-5 jitter + P1-7 request_id + P1-10 multiprocess metrics

각 sprint 후 본 Gate 재실행하여 회귀 검증.
