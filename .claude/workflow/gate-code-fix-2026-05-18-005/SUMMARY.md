# Code Fix Session — Secondary P1 Surgical Resolution

세션: `gate-code-fix-2026-05-18-005`
타입: **Implementation pass** (NEW-V-1, NEW-V-2, NEW-V-3 만)
브랜치: `claude/cool-bouman-70eb80`
직전: `gate-code-verify-2026-05-18-004` (verify, 3 secondary P1 발견)

## 판정
🟢 **3 secondary P1 모두 surgical 해결. +7 회귀 테스트, 0 regressions. SMTP sync sleep + AppDependencies refactor 는 명시적으로 미수행 (사용자 지시).**

| Before | After |
|--------|-------|
| 172 pass, 2 skip | 179 pass, 2 skip (+7) |
| 3 active secondary P1 (NEW-V-1/2/3) | 0 active secondary P1 |
| `code-L17/L18/L19` active | `code-L17/L18/L19` resolved |

## 처리한 secondary P1

### NEW-V-1 — SSRF per-retry re-validation
- **위치**: `email_service/webhooks.py:deliver_webhook`
- **변경**: `validate_webhook_url(url)` 호출을 retry **for-loop 외부 → 내부**로 이동. 각 attempt 직전 재실행.
- **효과**: 1차 검증 후 retry 사이 DNS rebind 가 발생해도 다음 attempt 가 다시 resolve → private IP 감지 시 `email_webhook_failed_total.inc()` 후 즉시 return False.
- **TOCTOU 잔여**: validate ↔ `client.post(url)` 의 ms 단위 sub-attempt 윈도우만 남음. 완전 제거는 httpx transport hook (IP pinning) 필요 — 본 pass 범위 외.
- **회귀 테스트**: `TestNewV1_PerRetrySSRFRevalidation` (2 tests)
  - `test_ssrf_revalidate_between_retries`: 1st resolve public IP / 2nd resolve 127.0.0.1 mock. 503 → retry → 2nd validate blocks. httpx call_count == 1 단언.
  - `test_repeated_failures_revalidate_each_time`: validator counting wrapper 로 max_retries=3 시 validator 정확히 3회 호출 확인.

### NEW-V-2 — Idempotency body fingerprint
- **위치**: `email_service/api.py` (`_IdempotencyCache` 시그니처 + `_body_fingerprint` 헬퍼 + 3 라우트 wiring)
- **변경**:
  - `_body_fingerprint(req)` = SHA-256(canonical JSON dump, sort_keys=True). 모든 필드 포함 (`webhook_secret` 도 — 다르면 다른 요청).
  - `_IdempotencyCache.put(bearer, key, fingerprint, response)` 시그니처 변경, 저장 값은 `{expires, fingerprint, response}` envelope.
  - `_IdempotencyCache.get()` 가 envelope 반환 (caller 가 fingerprint 비교).
  - `_idempotency_guard` 안에서 fingerprint mismatch → `HTTPException(409, "Idempotency-Key was previously used with a different request body")`.
  - 비교는 `hmac.compare_digest` (timing-safe).
- **회귀 테스트**: `TestNewV2_IdempotencyBodyFingerprint` (3 tests) + 기존 2 캐시 단위 테스트 시그니처 업데이트
  - `test_idempotency_same_body_same_key_cached`: 같은 body 2 번 → 같은 응답, sender.call_count == 1
  - `test_idempotency_different_body_same_key_rejected`: 다른 body 같은 key → 409, sender.call_count == 1 (첫 요청만)
  - `test_idempotency_different_key_different_body_both_process`: 독립

### NEW-V-3 — Idempotency per-key lock (concurrency)
- **위치**: `email_service/api.py` (`_IdempotencyCache.get_lock` + `_idempotency_guard` contextmanager)
- **변경**:
  - `_IdempotencyCache._key_locks: dict[(bearer, key), threading.Lock]`
  - `_meta_lock` 가 `_key_locks` 와 `_store` 동시 보호 (get-or-create 원자성).
  - `get_lock(bearer, key)` — 락 인스턴스 반환 (없으면 생성).
  - eviction 시 lock 도 같이 pop (메모리 자연 회수).
  - `_idempotency_guard` 가 lock acquire → lookup → yield → release. 캐시 miss 시 lock 을 held 한 상태로 yield, 호출 측 process + `_idempotency_remember` 완료 후 release.
- **격리 보장**: 다른 key 는 자기만의 lock → 병렬 처리. 같은 key 만 직렬화.
- **회귀 테스트**: `TestNewV3_IdempotencyConcurrency` (2 tests)
  - `test_idempotency_concurrent_requests_single_execution`: ThreadPoolExecutor(10), 같은 key+body 10 동시 호출. slow_send 가 send_started.set() 후 proceed.wait() 로 race window 강제. 결과: `sender.send.call_count == 1`, 모든 응답 body 동일.
  - `test_different_keys_run_in_parallel`: 2 다른 key. semaphore 로 두 send 가 parallel 진입 확인 (한 쪽이 직렬화되면 acquire timeout). 결과: 둘 다 sender 진입, 직렬화 아님.

## 변경 파일 요약

| File | LOC delta | 변경 |
|------|-----------|------|
| `email_service/webhooks.py` | +13 / −10 | validate_webhook_url 호출을 retry loop 내부로 이동 |
| `email_service/api.py` | +85 / −51 | `_body_fingerprint` 헬퍼, `_IdempotencyCache` envelope+lock 추가, `_idempotency_guard` contextmanager, 3 라우트 with-block restructure |
| `tests/test_p1_fixes.py` | +220 (additions) | 7 신규 + 2 기존 캐시 테스트 시그니처 업데이트 |

워크플로/process docs 미변경. 런타임 외부 인터페이스 (응답 스키마, env vars) 미변경. 새 env var 0개 (TTL/max 환경 변수 기존 유지).

## 테스트 결과

```
Before: 172 passed, 2 skipped
After:  179 passed, 2 skipped (+7 new, 0 regressions)

Per-block:
  TestNewV1 (per-retry SSRF re-validation): 2 pass
  TestNewV2 (body fingerprint):              3 pass
  TestNewV3 (concurrency):                   2 pass
  (캐시 단위 테스트 2개 시그니처 업데이트, 동작 보존)
```

## 미처리 (사용자 명시 요청)

- **SMTP sender sync sleep (L-SEED-02 partial)**: 본 pass 미수정. Phase A (retry budget cap) 다음 small fix pass 권장.
- **AppDependencies dataclass (code-L14)**: `create_app` 가 6 kwargs 도달. 본 pass 미리팩토링. **계획만** 제시:
  - 새 dataclass `email_service.app_config.AppDependencies` 추가, fields: `sender`, `api_key`, `magic_link`, `otp`, `rate_limiter`, `idempotency_cache`.
  - `create_app(deps: AppDependencies | None = None, **legacy_kwargs)` — legacy kwargs 들어오면 deps 로 변환 (백워드 호환).
  - 테스트가 직접 키워드 전달하는 패턴은 유지.
  - 다음 cross-cutting (7번째 — audit log, tracing 등) 도입 *전*에 처리 권장.
- **P2 항목들** (Linux exotic IP 검증, V1 deprecation timeline, in-memory state docs, runbook): 본 pass 미수정. release-gate (`/hwan-refactor-git`) 영역.

## 남은 리스크

1. **SMTP sync sleep** (L-SEED-02 partial): 31s budget 유지. 다음 pass Phase A 권장.
2. **DNS rebinding sub-attempt window (~ms)**: validate ↔ httpx connect 사이. IP pinning 으로만 완전 제거 가능. 본 pass 의 per-retry re-validate 로 inter-retry 갭 (~8s) 은 해결.
3. **code-L14** (create_app 6 kwargs): 7번째 추가 전 dataclass 리팩토링.
4. **Linux exotic IP** (code-L13): 미검증. release 전 확인 권장.
5. **V1 webhook deprecation timeline** (code-L16): release-gate 에서.

---

## Active Learnings Applied

직전 priors:
- L-SEED-01 (테스트 통과 ≠ 안전): 7 회귀 테스트로 NEW-V 컨트랙트 영구 보호.
- L-SEED-02 (BG + sync sleep): 인지, 의도된 partial 유지.
- code-L09, L15 (validator + 기존 fixture 회귀): 본 pass 의 cache signature 변경 시 동일 패턴. `test_cache_evicts_at_capacity` + `test_cache_isolates_bearers` 2개 fixture 사전 식별 → surgical 업데이트 → 베이스라인 즉시 복구.
- code-L10 (SMTP phase): 무관, 유지.
- code-L11, L14 (underscore Depends + create_app bloat): **재발 유지**. 본 pass 미해결 (사용자 명시). 다음 cross-cutting 도입 전 처리 필수.
- code-L12 (DNS rebinding parse-time): resolved 유효.
- code-L13 (exotic IP): active.
- code-L16 (V1 deprecation): active.
- **code-L17** (loop 외 보안 재검증): **RESOLVED by NEW-V-1 fix** — validate 가 retry loop 내부로 이동.
- **code-L18** (캐시 key body fingerprint): **RESOLVED by NEW-V-2 fix** — fingerprint 포함, mismatch 409.
- **code-L19** (lookup→process→store race): **RESOLVED by NEW-V-3 fix** — per-key lock + contextmanager.

## New Learnings Captured

```yaml
ID: code-L20
Source: gate-code-fix-2026-05-18-005 (secondary P1 impl pass)
Severity: P2
Mistake / Miss: 캐시 시그니처 (`put(bearer, key, value)` → `put(bearer, key, fingerprint, response)`) 변경 시 직접 호출하는 단위 테스트 2개가 깨졌다. fingerprint 추가는 학습 (code-L18) 의 직접 결과지만, 테스트 시그니처 회귀는 매번 동반.
Root Cause: 캐시/저장소 인터페이스가 단위 테스트로 직접 호출되는 패턴 + 시그니처 진화 가능성.
Recurrence Trigger: 캐시/store 의 시그니처에 새 필드 추가 시 (fingerprint, version 등).
Prevention Rule: 새 필드를 cache.put 에 추가할 때, 단위 테스트 호출 지점을 동시에 grep + 업데이트. 가능하면 keyword-only argument 로 default 제공하여 백워드 호환.
Next-Session Checklist Item: "cache.put / store.insert 시그니처를 수정하는가? 단위 테스트의 직접 호출 grep 했는가? default 가능하면 keyword-only 로 전환했는가?"
Applies To: email_service/api.py (_IdempotencyCache), 향후 cache layer
Owner Gate: code
Evidence: tests/test_p1_fixes.py test_cache_evicts_at_capacity / test_cache_isolates_bearers (이 세션)
Status: active
```

```yaml
ID: code-L21
Source: gate-code-fix-2026-05-18-005 (secondary P1 impl pass)
Severity: P2
Mistake / Miss: contextmanager (`_idempotency_guard`) 가 lock 을 yield 동안 hold. caller 가 yield 안에서 raise 시 finally 가 정확히 release 한다. 다만 yield 안에서 `_fail(result)` (HTTPException) 가 발생하면 lock 도 함께 release 됨 — 다음 동일 키 요청은 cache miss → 다시 처리 → 또 실패. 무한 실패 루프는 아니지만 caller bug 시 sender 가 매 요청 호출됨 (의도된 동작: 실패는 캐시 안 함).
Root Cause: contextmanager + 실패-미캐싱 정책의 자연스러운 상호작용. 명시적 의도지만 운영자가 트래픽 증폭 가능성을 인지해야 함.
Recurrence Trigger: idempotency 캐시 + 실패-미캐싱 정책 운영.
Prevention Rule: 실패 시 sender 호출 증폭을 rate limit 가 차단함 (이미 적용). 단, monitoring 에서 "같은 idem_key 로 실패 반복" 패턴이 있을 시 alert 필요. docs/runbooks 에 명시.
Next-Session Checklist Item: "실패-미캐싱 정책의 트래픽 증폭이 rate limit 으로 차단되는가? monitoring alert 정의되어 있는가?"
Applies To: email_service/api.py, docs/runbooks
Owner Gate: git
Evidence: api.py `_idempotency_remember` 의 if-condition (이 세션)
Status: active
```

```yaml
ID: code-L22
Source: gate-code-fix-2026-05-18-005 (secondary P1 impl pass)
Severity: P1
Mistake / Miss: per-key lock 도입 시 lock dict 메모리 누수 가능성. 본 fix 는 cache eviction 시 lock 도 함께 pop. 단 cache hit/miss 패턴이 비정상적이거나 (예: 매번 새 key) max_entries 도달까지 lock 누적 = 최대 10k locks (~80KB). 운영상 문제 없으나 unbounded growth 인지 필요.
Root Cause: lock 라이프사이클을 cache entry 와 묶었는데, cache 가 max_entries 까지 늘어나는 동안 lock dict 도 동일 페이스로 증가.
Recurrence Trigger: per-key lock 도입 (지금) 또는 향후 다른 dict-based state.
Prevention Rule: lock dict 메모리 cap 명시 (max_entries 와 같이). eviction policy 통합. monitoring 으로 lock count 노출.
Next-Session Checklist Item: "Per-key lock 도입 시 cache eviction 과 lock 정리가 동기화되어 있는가? 메모리 cap 이 문서화됐는가?"
Applies To: email_service/api.py (_IdempotencyCache._key_locks)
Owner Gate: code
Evidence: api.py _IdempotencyCache.put/get 의 eviction 분기 (이 세션)
Status: active
```

## Recurrence Risks

| ID | 본 세션 결과 | 다음 gate 관찰 포인트 |
|----|--------------|----------------------|
| L-SEED-01 | active (영구) | — |
| L-SEED-02 | active partial | Phase A 도입 권장 |
| code-L09 / L15 | applied (사전 grep 으로 fixture 회귀 surgical 처리) | 시그니처 변경 패턴 시 |
| code-L11 / L14 | active 재발 (본 pass 미해결, 사용자 명시) | 7번째 cross-cutting 전 dataclass |
| code-L12 | resolved 유효 | — |
| code-L13 | active (Linux 미검증) | release 전 |
| code-L16 | active | release-gate |
| **code-L17 (RESOLVED)** | Resolved-By: gate-code-fix-2026-05-18-005 | — |
| **code-L18 (RESOLVED)** | Resolved-By: gate-code-fix-2026-05-18-005 | — |
| **code-L19 (RESOLVED)** | Resolved-By: gate-code-fix-2026-05-18-005 | — |
| code-L20 (NEW P2) | new | 캐시 시그니처 변경 시 |
| code-L21 (NEW P2) | new | 실패-미캐싱 정책 운영 시 monitoring |
| code-L22 (NEW P1) | new | per-key lock dict 메모리 |

## Next Gate Prompt Addendum

> 다음 gate prompt 에 그대로 붙일 텍스트:
>
> ```
> Active priors from gate-code-fix-2026-05-18-005:
>
> RESOLVED (this session):
> - code-L17 SSRF per-retry re-validation — validate now runs inside the
>   retry loop. Inter-retry DNS rebinding closed. Sub-attempt window
>   (~ms) remains; full elimination needs IP pinning.
> - code-L18 Idempotency body fingerprint — SHA-256 of canonical JSON.
>   Mismatch → 409. Same body + same key → cached response.
> - code-L19 Idempotency concurrency — per-key lock via `get_lock()` +
>   `_idempotency_guard` contextmanager. Different keys parallel.
>
> STILL ACTIVE (carry forward):
> - L-SEED-02 SMTP sender sync sleep — 31s budget unchanged.
>   Next priority: Phase A retry budget cap. Phase B/C async path is
>   v0.4.0 pre-work.
> - code-L11 / code-L14 — create_app at 6 kwargs + underscore Depends
>   accumulation. Refactor to AppDependencies BEFORE adding a 7th
>   cross-cutting concern.
> - code-L13 Exotic IP encoding — UNVERIFIED on Linux. Run before first
>   Linux deployment.
> - code-L16 V1 webhook signature deprecation — release-gate (docs).
> - code-L20 Cache signature change ↔ unit test fixtures — grep call
>   sites when adding fields.
> - code-L21 Failure not cached → sender amplification potential —
>   rate limit blocks, but add monitoring alert pattern.
> - code-L22 Per-key lock dict memory — bounded by cache max_entries
>   via shared eviction; document cap.
>
> Pre-implementation checklist:
> 1. Adding a cache/store with mutation? Include fingerprint or
>    versioning if external input determines lookup key (code-L18).
> 2. Adding cache lookup→process→store flow? Per-key lock or atomic
>    set-if-empty (code-L19).
> 3. Adding security re-validation? Inside retry loop (code-L17).
> 4. Adding 7th create_app kwarg? AppDependencies first (code-L11/L14).
> 5. Pre-deployment to Linux? Verify exotic IP handling (code-L13).
>
> Deployment context judgment:
> - Single-tenant + single-worker: SHIP eligible TODAY (all P0/P1
>   findings either resolved or accepted as P2 docs).
> - Multi-tenant or high-throughput: handle L-SEED-02 Phase A,
>   code-L13 Linux verify, code-L16 V1 deprecation timeline first.
> - PyPI public + many integrators: above + Phase B/C async,
>   Redis-backed state, AppDependencies refactor.
> ```
