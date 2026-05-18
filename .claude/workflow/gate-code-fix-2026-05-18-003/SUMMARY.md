# Code Fix Session — P1 Surgical Resolution

세션: `gate-code-fix-2026-05-18-003`
타입: **Implementation pass** (P1 only, P2 미수정)
브랜치: `claude/cool-bouman-70eb80`
직전 세션: `gate-code-verify-2026-05-18-002` (verify, 2 신규 P1 발견)

## 판정
🟢 **3 P1 surgical fix 완료, +17 회귀 테스트, 0 regressions. 1 P1 (SMTP sync sleep) 큰 리팩토링으로 계획만 제시.**

| Before | After |
|--------|-------|
| 155 pass, 1 skip | 172 pass, 2 skip (+17 new) |
| 5 active P1 (사용자 질의 1-5) | 1 active P1 (SMTP sync sleep) + 1 active P2 (in-memory rate limit) |

## 처리한 P1

### P1-A. SSRF DNS rebinding mitigation
- **변경**: `email_service/webhooks.py` `deliver_webhook` 시작 부에 `validate_webhook_url(url)` 재실행 추가.
- **효과**: TOCTOU 윈도우를 "Pydantic parse → BackgroundTask 실행" (수초) → "validate → 첫 POST" (~ms) 로 단축.
- **완전 제거 안 함**: validate ↔ httpx connect 사이 사소한 TOCTOU 잔여. 완전 제거하려면 httpx Transport 후킹 통해 resolve 된 IP 를 강제 사용해야 함 — 큰 변경, 미실행.
- **회귀 테스트**: `TestP1A_FetchTimeSSRFRevalidation` (5 tests, 1 skip)
  - 직접 private IP 거부, loopback 거부, AWS metadata 거부
  - DNS rebinding 시뮬레이션: validator 가 2번째 resolve 결과로 127.0.0.1 반환 시 HTTP 전송 0건
  - 차단 시 failure counter 증가 (prometheus 환경에서만 동작 → skip)

### P1-B. HTTP /send idempotency
- **변경**: `email_service/api.py`
  - 신규 `_IdempotencyCache` (TTL + bounded LRU-ish + thread-safe)
  - `_check_idempotency_key`, `_idempotency_lookup`, `_idempotency_store` 헬퍼
  - 3개 send 라우트에 `Idempotency-Key` 헤더 인자 + lookup/store 흐름
  - 환경변수 `API_IDEMPOTENCY_TTL_SECONDS` (default 86400 = 24h), max entries 10_000
- **정책**:
  - 헤더 부재 → 정상 처리 (기존 호환)
  - 헤더 있고 캐시 HIT → sender/notifier 호출 없이 캐시된 응답 반환
  - 캐시는 **성공한 send (sent=True) + 큐잉된 send (status="accepted")** 만 저장. **502 실패는 캐시 안 함** (호출자가 수정 후 재시도 시 실제 실행 보장).
  - 키 길이 ≤ 128 (초과 시 400)
  - 베어러별 격리 (다른 베어러는 다른 캐시 키)
- **회귀 테스트**: `TestP1B_Idempotency` (8 tests)
  - 같은 키 → 캐시 hit, sender call_count=1
  - 다른 키 → 독립 처리, sender call_count=2
  - 키 없음 → dedup 없음
  - 실패 응답 캐시 안 됨
  - 키 너무 김 → 400
  - 비활성화 (ttl=0) 동작
  - 용량 초과 시 eviction
  - 베어러 격리

### P1-C. webhook HMAC replay defense (V2 signature)
- **변경**: `email_service/webhooks.py`
  - 신규 `SIGNATURE_HEADER_V2`, `TIMESTAMP_HEADER` 상수
  - `_sign_v2(timestamp, body, secret)`: HMAC-SHA256(`"<ts>.<body>"`)
  - 모든 deliver_webhook 호출에 `X-Email-Service-Timestamp` (Unix epoch) 헤더 추가
  - secret 있을 시 V1 (`X-Email-Service-Signature`, body only) + V2 (timestamp+body) 둘 다 전송
- **호환성**: V1 헤더/포맷 변경 없음. 기존 수신자 영향 0. V2 수신자는 신규 헤더 + 신선도 검증 (±5분) 로 replay 차단.
- **문서화**: `webhooks.py` module docstring 에 수신자 마이그레이션 가이드 4 단계 추가.
- **회귀 테스트**: `TestP1C_WebhookReplayDefense` (5 tests)
  - timestamp 헤더 present + 유효한 epoch
  - V2 서명 = HMAC over `"<ts>.<body>"`, constant-time 검증
  - V1 헤더 보존 (백워드 호환)
  - 다른 timestamp → 다른 서명 (replay 차단 핵심)
  - secret 없을 시 두 서명 모두 없음, timestamp 만 송신

## 미처리 P1 (계획만)

### P1-D. SMTP sender sync sleep (사용자 질의 #1) — 계획만, 본 pass 미수정
**현 상태**: `email_service/sender.py` 의 retry 루프 (line 277) 가 `time.sleep(backoff_seconds[i])` 사용. 최대 (1+5+25) = 31s threadpool 슬롯 점유.

**왜 surgical 안 되는가**:
1. `SmtpSender.send()` 는 라이브러리 사용자가 직접 호출 (CLI / Python lib). async 전환 시 라이브러리 사용자 인터페이스 변경 — breaking change.
2. FastAPI 라우트 (`/send`) 는 sync handler 로 호출 → async 로 바꾸면 라우트 signature + dependency 도 변경.
3. smtplib 자체가 sync IO. `aiosmtplib` 같은 외부 의존성 추가 필요.

**제안 단계적 계획** (별도 PR):
1. **Phase A** (안전 부분 fix): retry 총 sleep budget 캡 (e.g. `max_total_retry_sleep_seconds=10` 옵션). max_retries × backoff 합산 시 cap 초과면 즉시 fail. 사용자별 sender 인스턴스 옵션 추가, default 무제한 유지 (백워드 호환).
   - 본 pass 에서도 small surgical fix 가능했음. 다만 사용자가 "큰 리팩토링이면 계획만" 명시 → 본 pass 미실행.
2. **Phase B** (async 도입): `aiosmtplib` 추가, `AsyncSmtpSender` 신설 (`SmtpSender` 유지). `/send` 라우트를 `async def` + `AsyncSmtpSender.send()`. 라이브러리 사용자는 기존 `SmtpSender` 유지.
3. **Phase C** (정리): SDK clients (`client.py` / `async_client.py`) 이미 sync/async 둘 다 있음 → backend 도 정합.

**권장 우선순위**: Phase A 는 다음 small fix pass 에 포함. Phase B/C 는 v0.4.0 release pre-work.

## 처리하지 않은 P2 (문서화 권장만)

| 항목 | 권장 조치 |
|------|----------|
| In-memory rate limit (per-worker) | README `Deployment` 섹션에 "single-worker 또는 sticky LB 권장, multi-worker quota 는 worker 수 × API_RATE_LIMIT_PER_MINUTE" 명시 |
| smtp_disconnect_uncertain runbook | `docs/runbooks/smtp-disconnect-uncertain.md` 신설 (대응 절차: "메일은 발송됐을 수 있음. 수신자에게 확인 후 수동 재발송 결정") |
| FastAPI pre-Pydantic body buffer | README 에 nginx `client_max_body_size 12m` / uvicorn `--limit-max-requests` 권장 |
| Pydantic max_length char vs byte | 비고 추가, P3 |

본 pass 미수정 — 문서 변경은 별도 docs PR 권장.

## 변경 파일 요약

| File | LOC delta | 변경 |
|------|-----------|------|
| `email_service/webhooks.py` | +47 / −2 | fetch-time SSRF re-validation, V2 signature, timestamp header, module docstring 갱신 |
| `email_service/api.py` | +183 / −18 | `_IdempotencyCache`, 헬퍼 3개, 3개 send 라우트 wiring |
| `tests/test_p1_fixes.py` | +325 (new) | 18 regression tests (1 skip on prometheus) |
| `tests/test_phase4.py` | +6 / −3 | 3 deliver_webhook 테스트에 `WEBHOOK_ALLOW_HOSTS=hook` monkeypatch |

런타임/설정/워크플로 docs 미변경 (사용자 명시).

## 테스트 결과

```
Before: 155 passed, 1 skipped
After:  172 passed, 2 skipped (+17 new tests, 0 regressions)

Per-block:
  P1-A (SSRF rebinding):    5 pass + 1 skip (prometheus dependency)
  P1-B (idempotency):       8 pass
  P1-C (HMAC replay V2):    4 pass
  Compatibility:            3 phase4 tests updated to new contract
```

## 남은 리스크 (이번 범위 밖)

1. **P1-D SMTP sync sleep** (계획만): retry budget cap (Phase A) 은 다음 small fix pass 권장. async 전환 (Phase B/C) 은 v0.4.0 pre-work.
2. **P2 in-memory rate limit**: 단일 워커면 OK. 멀티 워커 시 cap 곱하기 워커 수.
3. **P2 idempotency in-memory**: 본 세션에서 rate limit 와 같은 한계. multi-worker 시 같은 key 가 워커 N개에서 모두 처리될 수 있음. **문서화 필요**.
4. **DNS rebinding 잔여 TOCTOU**: validate ↔ httpx connect 사이 ms 단위 윈도우. 완전 제거는 httpx transport hook 필요.
5. **V1 webhook signature 사용 시 replay 가능**: V2 채택 안 한 수신자는 여전히 취약. README/CHANGELOG 에 V2 마이그레이션 경로 명시 필요.

---

## Active Learnings Applied

직전 세션 priors 적용 결과:

- **L-SEED-01** (테스트 통과 ≠ 안전): 적용. 본 fix 도 18 regression tests 추가하여 P1 contract 영구 보호.
- **L-SEED-02** (BG + sync sleep): 인지함. SMTP sender 측은 계획만 — 의도된 미해결, 다음 pass.
- **code-L09** (validator + 기존 fixture 회귀): 적용 — fetch-time validator 가 test_phase4 3개 깨지는 것 예상, 사전 monkeypatch 패치.
- **code-L10** (SMTP phase 식별): 본 fix 와 무관, 유지.
- **code-L11** (underscore Depends 누적): **재발** — 본 fix 가 3 라우트 각각에 `creds`, `_`, `__` 위치 인자 사용. 임계치 미만이지만 watchlist.
- **code-L12** (DNS rebinding): **이 세션이 처리한 P1-A**. learning resolved (partial — IP pinning 완전 해결은 후속).
- **code-L13** (exotic IP literal): 본 pass 미해결. Linux glibc 실측 검증 필요.

## New Learnings Captured

```yaml
ID: code-L14
Source: gate-code-fix-2026-05-18-003 (P1 impl pass)
Severity: P2
Mistake / Miss: 캐시 (idempotency, rate limit) 와 같은 cross-cutting 상태가 늘면서 `create_app(...)` 시그니처가 키워드 인자 5개로 팽창. 미래 cross-cutting (audit log, feature flag, tracing) 추가 시 같은 패턴 반복 → factory bloat.
Root Cause: Cross-cutting state 를 라우트 closures 가 캡처하는 구조라 전부 `create_app` 파라미터로 노출.
Recurrence Trigger: 새 cross-cutting concern (3rd 추가) 도입 시.
Prevention Rule: cross-cutting state 가 3개 (rate_limiter, idempotency_cache, +1) 이상이면 `AppDependencies` 같은 컨테이너 dataclass 로 묶기. 작은 리팩토링으로 가능.
Next-Session Checklist Item: "create_app 키워드 인자가 5개 이상인가? AppDependencies dataclass 도입 검토."
Applies To: email_service/api.py
Owner Gate: code
Evidence: create_app(sender, api_key, magic_link, otp, rate_limiter, idempotency_cache) — 본 세션
Status: active
```

```yaml
ID: code-L15
Source: gate-code-fix-2026-05-18-003 (P1 impl pass)
Severity: P1
Mistake / Miss: 새 검증 (fetch-time SSRF re-validate) 추가하면서 기존 test_phase4 의 `http://hook/x` fixture 3개가 또 깨졌다. 이전에 1번 깨진 적 있는데 같은 패턴 재발.
Root Cause: code-L09 의 알람을 "validator 추가 시 fixture" 로만 좁게 해석. 같은 validator 가 다른 호출 지점에서 활성화되는 경우도 같은 영향.
Recurrence Trigger: 검증 코드를 새 호출 지점에 적용 (validator 자체는 기존이지만 호출 위치가 새로움).
Prevention Rule: validator 함수를 새 위치에서 호출하기 전에 grep 으로 기존 모든 호출 지점의 테스트 fixture 영향 사전 점검. monkeypatch 패턴 일관화.
Next-Session Checklist Item: "기존 validator 함수의 새 호출 지점을 추가하는가? 그 호출이 기존 테스트 fixture 와 충돌하는가?"
Applies To: email_service/**, tests/**
Owner Gate: code
Evidence: tests/test_phase4.py:test_deliver_webhook_* 3건 (이번 세션 fix 후 깨짐 → monkeypatch 추가)
Status: active
```

```yaml
ID: code-L16
Source: gate-code-fix-2026-05-18-003 (P1 impl pass)
Severity: P2
Mistake / Miss: V2 signature 도입 시 V1 헤더를 보존했지만 V1 수신자는 여전히 replay 취약. "구 클라이언트도 동작" 과 "구 클라이언트 보안" 은 다른 문제.
Root Cause: 호환성을 위해 구 동작 유지 → 보안 부채 영구화 가능.
Recurrence Trigger: 보안 관련 헤더/프로토콜 버저닝 (auth, signing, encoding) 시.
Prevention Rule: V1 deprecation timeline 명시 (e.g. v0.5.0 제거). README/CHANGELOG 에 "V1 receivers are vulnerable to replay until migration to V2" 명시.
Next-Session Checklist Item: "보안 헤더의 새 버전을 도입했는가? deprecation timeline 이 명시됐는가?"
Applies To: email_service/webhooks.py
Owner Gate: git
Evidence: webhooks.py SIGNATURE_HEADER 와 SIGNATURE_HEADER_V2 동시 존재 (이 세션)
Status: active
```

## Recurrence Risks

| ID | 본 세션 결과 | 다음 gate 관찰 포인트 |
|----|--------------|----------------------|
| L-SEED-01 | active (영구) | — |
| L-SEED-02 | active (partial 유지 — SMTP sender 측 미해결) | 다음 fix 세션에서 sender retry budget cap 도입 권장 |
| code-L09 | **RECURRED** as code-L15 (validator 새 호출 지점) | severity 자동 상승 규칙 적용 안 함 — 일반화하여 code-L15 로 진화시킴 |
| code-L12 | **RESOLVED** (P1-A 처리, partial — IP pinning 후속) | Resolved-By: gate-code-fix-2026-05-18-003 |
| code-L13 | active (Linux 실측 미수행) | 다음 verify 세션에서 |
| code-L14 (NEW) | new | create_app 인자 5개 → 다음 cross-cutting 추가 시 dataclass 검토 |
| code-L15 (NEW) | new | 모든 validator 새 호출 지점 추가 시 fixture 사전 점검 |
| code-L16 (NEW) | new | V1 deprecation timeline 문서화 필요 (release gate 영역) |

## Next Gate Prompt Addendum

> ```
> Active priors from gate-code-fix-2026-05-18-003:
>
> RESOLVED (since last gate):
> - code-L12 (SSRF DNS rebinding fetch-time gap): mitigated via re-validation
>   in deliver_webhook entry. TOCTOU window now ~ms. Full elimination via
>   IP pinning still pending.
>
> ACTIVE (carry forward):
> - L-SEED-02 (BG + sync sleep): SMTP sender retry time.sleep still
>   unbounded. Next priority: add max_total_retry_sleep_seconds option to
>   SmtpSender (Phase A from this session's SUMMARY). Phase B/C async path
>   is v0.4.0 pre-work.
> - code-L13 (exotic IP encoding): unverified on Linux. Add CI matrix run
>   or one-off Linux test.
> - code-L14 (factory bloat): create_app has 5 cross-cutting kwargs. If
>   adding a 6th, introduce AppDependencies dataclass first.
> - code-L15 (validator new call-site fixtures): when adding a new call site
>   for any existing validator, grep tests for fixtures that may break.
> - code-L16 (V1 signature deprecation): document V1 webhook signature
>   deprecation timeline in README + CHANGELOG (release-gate task).
>
> Pre-implementation checklist:
> 1. Adding a new BackgroundTasks.add_task? Confirm callable has no
>    blocking IO and total time bounded.
> 2. Adding a new validator call site? Grep tests for fixtures that
>    relied on the old non-validated path.
> 3. Bumping create_app kwargs to 6? Refactor to AppDependencies first.
> 4. Modifying SMTP retry classifier? Preserve sendmail_returned phase
>    flag (code-L10).
> 5. Introducing V3+ of any header? Plan V1 deprecation in same PR.
>
> Deployment notes (current state):
> - Single-worker uvicorn: SHIP eligible. Multi-worker: P2 idempotency +
>   rate-limit cap multiply by worker count — document or use Redis.
> - V1 webhook receivers still vulnerable to replay — must migrate to V2
>   (per code-L16) before claiming "anti-replay protected".
> ```
