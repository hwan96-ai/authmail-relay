# Code Fix Session — P0 ×5 Resolution

세션: `gate-code-fix-2026-05-18-001`
타입: **Implementation pass** (audit 아님, 실제 코드 수정)
브랜치: `claude/cool-bouman-70eb80`
직전 inherit: `gate-code-2026-05-16-001` 의 P0-1 ~ P0-5

## 판정
🟢 **All 5 P0 resolved, 155 tests pass (was 124), no regressions**

| Before | After |
|--------|-------|
| 124 pass, 1 skip | 155 pass, 1 skip |
| 5 open P0 | 0 open P0 (모두 회귀 테스트 포함 fix) |

## 해결한 P0

### P0-1. BackgroundTasks + sync sleep → threadpool starvation
- **변경**: `email_service/webhooks.py`
  - `DEFAULT_BACKOFFS` (1, 10, 60) → (1, 2, 5) — 최대 sleep 71s → 8s
  - `_jittered()` ±25% jitter 적용 (thundering herd 방지)
- **회귀 테스트**: `tests/test_p0_fixes.py::TestP0_1_BoundedWebhookBackoff` (5 tests)
  - 누적 sleep ≤ 10s 강제 단언 (real retry loop 포함)
  - jitter 분포 범위 검증
- **남은 위험**: 동기 BackgroundTask 구조 자체는 유지 (large refactor 회피). 8s 슬립도 threadpool 슬롯 점유하나 시스템적 starvation 위험 대폭 감소. P1 후속으로 `httpx.AsyncClient` 전환 권장.

### P0-2. webhook_url SSRF
- **변경**: 신규 `email_service/url_validation.py` + `api.py` Pydantic field_validator
  - scheme http/https 강제
  - IP literal 검사 (loopback/link-local/private/multicast/reserved/unspecified)
  - 호스트네임 DNS 해석 후 IP 검증
  - 환경변수 override: `WEBHOOK_ALLOW_HOSTS` (allowlist), `WEBHOOK_ALLOW_LOOPBACK=1` (테스트)
- **회귀 테스트**: `TestP0_2_SSRFDefense` (10 tests)
  - 169.254.169.254 (AWS metadata), 127.0.0.1, ::1, RFC1918, ftp://, file://, link-local DNS 모두 거부
  - 공개 IP 통과, allowlist hostname 통과, NXDOMAIN 거부
  - API end-to-end: AWS metadata URL → 422 응답
- **기존 테스트 호환**: `test_phase4` 의 `http://hook/x` 픽스처는 `WEBHOOK_ALLOW_HOSTS=hook` monkeypatch 로 통과 유지

### P0-3. subject / body / recipient 사이즈 제한
- **변경**: `api.py` Pydantic 모델 모두에 `max_length` / `max_items`
  - `to`: 320 (RFC 5321), `subject`: 998 (RFC 5322), `html_body`/`text_body`: 10MB
  - `cc`/`bcc`: 100 개, `user_name`: 256, `token`: 4096, `code`: 64
  - `webhook_url`: 2048, `webhook_secret`: 256
- **회귀 테스트**: `TestP0_3_SizeLimits` (4 tests)
  - subject 998+1 → 422, body 10MB+1 → 422, cc 101 → 422

### P0-4. shared bearer + rate limit 없음
- **변경**: `api.py` 신규 `_SlidingWindowLimiter` + `rate_limit` dependency
  - 환경변수 `API_RATE_LIMIT_PER_MINUTE` (default 60)
  - 토큰별 sliding window (현재 단일 키지만 multi-key 시도 자동 동작)
  - 적용 라우트: `/send`, `/send/magic-link`, `/send/otp` (헬스/메트릭 제외)
  - 429 응답 + `Retry-After` 헤더
  - In-memory, per-process. 멀티 워커는 per-worker cap → 의도된 동작
- **회귀 테스트**: `TestP0_4_RateLimit` (6 tests)
  - N 초과 시 429 + Retry-After, window 후 회복, 키별 격리, 비활성화 (max=0), 헬스 미적용

### P0-5. SMTP post-DATA disconnect 중복 발송
- **변경**: `email_service/sender.py`
  - `_send_once` 에 `sendmail_returned` 플래그 + `sendmail_refused` 캐싱
  - `SMTPServerDisconnected` 처리 분기:
    - sendmail 후 disconnect → `STATUS_DELIVERED` (또는 refused 있으면 PARTIAL)
    - sendmail 전/중 disconnect → 신규 `ERR_SMTP_DISCONNECT_UNCERTAIN` (non-retriable)
  - `_RETRIABLE_ERROR_CODES` 에 신규 코드 미포함 → retry 자동 차단
- **회귀 테스트**: `TestP0_5_DisconnectDuringSendmail` (3 tests)
  - mid-sendmail disconnect → attempts=1, no retry, sleep=0
  - post-sendmail disconnect → sent=True, delivered
  - post-sendmail disconnect + partial refusal → refused 보존, status=partial

## 테스트 결과

```
$ pytest tests/ --tb=line -q
...........................................................................
155 passed, 1 skipped in 9.07s
```

- 신규 test: `tests/test_p0_fixes.py` (31 tests across 5 classes)
- 수정 test: `tests/test_phase4.py`
  - `test_retry_succeeds_after_transient_disconnect` → `test_retry_succeeds_after_transient_timeout` (TimeoutError 사용. SMTPServerDisconnected mid-flow 는 새 규약에 따라 non-retriable)
  - `test_message_id_stable_across_retries` → 421 transient response 사용
  - `test_api_send_with_webhook_returns_accepted` → `WEBHOOK_ALLOW_HOSTS=hook` 환경 설정

## 변경 파일 요약

| File | LOC delta | 변경 |
|------|-----------|------|
| `email_service/api.py` | +143 / −13 | Pydantic 크기 제한, SSRF wiring, rate limiter |
| `email_service/sender.py` | +57 / −0 | sendmail_returned 플래그, post-DATA 성공 분기, ERR_SMTP_DISCONNECT_UNCERTAIN |
| `email_service/webhooks.py` | +14 / −3 | bounded backoffs (1,2,5), jitter |
| `email_service/url_validation.py` | +120 (new) | SSRF validator |
| `tests/test_p0_fixes.py` | +390 (new) | 31 regression tests |
| `tests/test_phase4.py` | +15 / −9 | 새 contract 반영 |

## 범위 준수 확인
- ✅ email_service/* 만 수정 (런타임 코드)
- ✅ tests/* 만 수정 (테스트)
- ✅ `.claude/` `docs/process/` `pyproject.toml` `Dockerfile` `.github/` 미변경
- ✅ 대규모 리팩토링 없음: 새 모듈 1개 (url_validation), 새 dataclass 0개, 기존 시그니처/응답 스키마 유지
- ✅ PR/머지/배포 자동 실행 없음
- ✅ 실제 이메일 발송 없음 (capture/mock only)

## 남은 리스크 (이번 범위 밖, P1 으로 이관 권장)

1. **BackgroundTasks 구조 자체**: 8s sleep 도 threadpool 슬롯 점유. 진정한 해결은 `httpx.AsyncClient` + async route 전환. (gate-code SUMMARY P0-1 의 "fix direction (1)/(2)" 중 (2) 만 적용)
2. **SMTP retry 도 동기 sleep**: `sender.send()` 의 retry sleep 은 그대로. webhook 측만 단축. sync `/send` 라우트는 여전히 SMTP 응답 시간만큼 점유.
3. **Rate limit in-memory**: 멀티 워커 환경에서 per-worker. 키 1개일 때 효과 충분, 다중 키 시 Redis-backed 필요.
4. **Webhook HMAC replay**: `gate-release` P1-15. 본 작업 범위 밖.
5. **Idempotency key**: `gate-code` P1-4. POST /send 재시도 중복은 P0-5 만 해결, HTTP 레이어 멱등키는 미해결.

---

## Active Learnings Applied

이번 fix 작업에서 다음 seed learning 이 priors 로 사용됨:

- **L-SEED-01** (테스트 통과 ≠ 외부 노출 안전): 124 pass 였던 코드를 실제로 P0 5건 수정. learning 검증됨.
- **L-SEED-02** (BackgroundTasks + sync sleep): webhooks.py 의 DEFAULT_BACKOFFS 단축으로 부분 mitigation. learning 의 Prevention Rule 정확함.
- **L-SEED-03** (webhook_url SSRF): url_validation.py 가 본 learning 의 Prevention Rule (scheme allowlist + hostname resolve + private-IP 차단) 그대로 구현.
- **L-SEED-04** (max_length 의무): Pydantic 모델 전체에 max_length / max_items 추가.
- **L-SEED-05** (post-DATA disconnect): sendmail_returned 플래그 도입. learning 의 Prevention Rule "phase (pre-DATA / post-DATA) 양쪽을 본다" 그대로 적용.

## New Learnings Captured

```yaml
ID: code-L09
Source: gate-code-fix-2026-05-18-001 (impl pass)
Severity: P1
Mistake / Miss: SSRF validator 를 Pydantic field_validator 에 직접 넣으면 기존 test fixtures (http://hook/x 같은 fake hostname) 가 422 로 깨진다.
Root Cause: 외부 노출 검증을 추가할 때 기존 테스트가 fake DNS hostname 을 쓰는지 사전 조사 안 함.
Recurrence Trigger: URL/주소/외부 식별자 검증 추가 시.
Prevention Rule: 새 validator 도입 전에 grep 으로 기존 fixture 패턴 식별, 환경변수 allowlist override 또는 conftest 세팅 동시 추가.
Next-Session Checklist Item: "이번 diff 가 입력 validator 를 추가하는가? 기존 테스트 fixture 가 깨질 패턴이 있는가? allowlist override 가 제공되는가?"
Applies To: email_service/api.py, tests/**
Owner Gate: code
Evidence: tests/test_phase4.py:357 (수정 전 422, 수정 후 monkeypatch WEBHOOK_ALLOW_HOSTS=hook)
Status: active
```

```yaml
ID: code-L10
Source: gate-code-fix-2026-05-18-001 (impl pass)
Severity: P1
Mistake / Miss: SMTPServerDisconnected 를 retriable 로 분류하면 sendmail() 직후 disconnect 케이스에서 중복 발송. 예외 타입 단독으론 phase 식별 불가.
Root Cause: smtplib 의 예외가 phase 정보를 제공하지 않음. 호출자가 명시적으로 phase 플래그를 들고 있어야 함.
Recurrence Trigger: SMTP retry classifier 확장, 새 SMTP 예외 추가, retry 로직 리팩토링 시.
Prevention Rule: with SMTP() 컨텍스트 안의 sendmail() 호출 직후 sendmail_returned 같은 플래그 set. 예외 핸들러에서 이 플래그로 분기.
Next-Session Checklist Item: "이번 diff 가 SMTP retry/예외 처리를 수정하는가? sendmail_returned 같은 phase 플래그를 보존하는가?"
Applies To: email_service/sender.py
Owner Gate: code
Evidence: email_service/sender.py:_send_once (이 세션)
Status: active
```

```yaml
ID: code-L11
Source: gate-code-fix-2026-05-18-001 (impl pass)
Severity: P2
Mistake / Miss: FastAPI Depends 를 위치 인자 없이 추가하면 라우트 시그니처에 의미 없는 underscore 파라미터 (_, __) 가 누적된다.
Root Cause: 인증/제한 검사를 의도적으로 side-effect-only Depends 로 묶는 구조에서 발생.
Recurrence Trigger: 새 cross-cutting 검사 (감사, 한도, A/B flag) 추가 시.
Prevention Rule: 2개 이상이면 라우트별 `depends_chain` 같은 묶음 Depends 함수로 통합 고려. 단발성이면 underscore 유지.
Next-Session Checklist Item: "라우트당 underscore Depends 가 3개 이상이면 통합 Depends 함수로 리팩토링 검토."
Applies To: email_service/api.py
Owner Gate: code
Evidence: send_email/send_magic_link/send_otp 시그니처 (이 세션)
Status: active
```

## Recurrence Risks

| ID | Pattern | 본 세션 결과 | 다음 gate 관찰 포인트 |
|----|---------|--------------|-----------------------|
| L-SEED-01 | 테스트 통과만으로 안전 판단 | Applied — 5 P0 모두 fix | 다음 외부 노출 변경 시 회귀 테스트 의무 |
| L-SEED-02 | BackgroundTasks + sync sleep | **Partial** — webhook 측만 단축. sender retry sleep 은 그대로. SMTP 측은 다음 gate 에서 |
| L-SEED-03 | webhook_url SSRF | Resolved-By: gate-code-fix-2026-05-18-001 |
| L-SEED-04 | max_length 누락 | Resolved-By: gate-code-fix-2026-05-18-001 |
| L-SEED-05 | post-DATA disconnect | Resolved-By: gate-code-fix-2026-05-18-001 |

L-SEED-02 는 부분 해결 — 다음 gate 시작 시 재발 감지 시 severity 유지 (상승 X, 의도된 부분 fix).

## Next Gate Prompt Addendum

> 다음 `/hwan-refactor-code` 또는 `/hwan-refactor-git` 실행 시 prompt 에 붙일 텍스트:
>
> ```
> Active priors from gate-code-fix-2026-05-18-001:
> - L-SEED-01, -03, -04, -05: resolved. Test coverage exists in tests/test_p0_fixes.py.
> - L-SEED-02 (BackgroundTasks + sync sleep): PARTIAL resolution. Webhook side
>   bounded to ≤8s. SMTP retry side (sender.py:277 time.sleep) still unbounded.
>   Re-flag if any new endpoint adds BackgroundTasks.add_task with sync IO.
> - code-L09: when adding new input validators, audit existing test fixtures
>   for fake DNS hostnames and provide an env allowlist override.
> - code-L10: SMTP retry classifier must distinguish pre-DATA vs post-DATA
>   disconnect. Preserve sendmail_returned flag pattern.
> - code-L11: routes with 3+ underscore Depends should consolidate.
>
> Pre-implementation checklist:
> 1. Does this diff add a route or modify request validation?
>    → Verify field max_length is set per L-SEED-04.
> 2. Does it accept a user-provided URL fetched server-side?
>    → Must route through email_service.url_validation.
> 3. Does it add BackgroundTasks.add_task(sync_fn)?
>    → sync_fn must not call time.sleep or blocking IO. If retry needed,
>      bound total sleep ≤ 10s with jitter (see webhooks.DEFAULT_BACKOFFS).
> 4. Does it modify SMTP retry/exception logic?
>    → Preserve sendmail_returned flag. New exception types must be
>      classified pre-DATA (retriable) vs post-DATA (success/uncertain).
> ```
