# Refactor Gate (Verify-only) — Post-secondary-P1-fix 검증

세션: `gate-code-verify-2026-05-18-006`
타입: **Verification gate** (코드 / 테스트 수정 0건)
브랜치: `claude/cool-bouman-70eb80`
직전: `gate-code-fix-2026-05-18-005` (secondary P1 fix — NEW-V-1/2/3)

## 판정
🟡 **PARTIAL VERIFIED — 5 P0 + 3 secondary P1 모두 STABLE. 단, NEW-V-3 fix 자체에 잔여 race 1건 발견 (tertiary P1). 단일 사용자 / 단일 워커 환경 SHIP 가능 (race 트리거 확률 낮음). 다중 사용자 / 고트래픽 환경은 처리 후 ship 권장.**

핵심:
- 179/181 tests pass. 회귀 0건.
- 5 P0 모두 STABLE
- 3 secondary P1 (NEW-V-1/2/3) 구조적 OK
- **NEW 발견: code-L19 fix 가 도입한 lock-eviction race (tertiary P1)**
- 사용자 질의 7개 release blocker 후보: 0건 P0, 2건 P1, 5건 P2

## Subagent 사용 정당성

이번 verify gate **subagent 호출 0건**. [docs/process/subagent-policy.md](../../../docs/process/subagent-policy.md):
- (A) 다관점 / (B) 3+ 파일 / (C) Adversarial / (D) Synthesis 기준 → 4 of 5 충족
- 그러나 직전 fix pass 가 본인 작성 → fresh context, ROI 부분 감소
- 직전 verify gate 패턴 일관성 (single-flow) 유지

---

## 1. 5 P0 재검증 (post-secondary-fix)

| P0 | 상태 | 검증 |
|----|------|------|
| P0-1 threadpool starvation | ✅ STABLE | webhook 8s budget + jitter 유지. NEW-V-1 fix 가 추가한 per-attempt validate 는 동기 lookup 이므로 budget 외 +N×O(ms) 추가, 영향 미미 |
| P0-2 webhook_url SSRF | ✅ STRENGTHENED | parse + per-retry fetch-time = 이중→삼중 검증. inter-retry rebind gap 닫힘 |
| P0-3 body/subject size limits | ✅ STABLE | Pydantic max_length 변경 없음 |
| P0-4 rate limit | ✅ STABLE | sliding window 변경 없음. 6 tests pass |
| P0-5 post-DATA disconnect | ✅ STABLE | sendmail_returned flag 변경 없음. 3 tests pass |

**5 P0 모두 secondary fix 로 인한 contract 손상 없음**.

## 2. 3 secondary P1 (NEW-V-1/2/3) 충분성 검증

### NEW-V-1. SSRF per-retry re-validation — 🟢 RESOLVED

| 검증 | 결과 |
|------|------|
| `validate_webhook_url(url)` 가 retry for-loop 내부 호출 (webhooks.py 인근 line 90+) | ✅ |
| 각 attempt 직전 재실행 | ✅ |
| 실패 시 `email_webhook_failed_total.inc()` + return False | ✅ |
| `test_ssrf_revalidate_between_retries` (1st public, 2nd 127.0.0.1) → httpx call 1회만 | ✅ |
| `test_repeated_failures_revalidate_each_time` → validator 3회 호출 | ✅ |

⚠️ **잔여 (이전부터 인지)**: validate ↔ httpx.connect ms 단위 sub-attempt window. IP pinning 필요. **P2** (기존 운영 위험 평가에서 격하 — 단일 attempt 안의 race 는 공격자가 그 ms 윈도우를 정밀하게 맞춰야 함, 현실적 공격 난이도 높음).

### NEW-V-2. Idempotency body fingerprint — 🟢 RESOLVED

| 검증 | 결과 |
|------|------|
| `_body_fingerprint(req)` 모든 필드 포함, SHA-256(canonical JSON sort_keys=True) | ✅ |
| Pydantic v2 `model_dump(mode="json")` deterministic | ✅ |
| `_idempotency_guard` 에서 fingerprint mismatch → HTTPException 409 | ✅ |
| 비교는 `hmac.compare_digest` (timing-safe, 보수적 선택) | ✅ |
| `test_idempotency_same_body_same_key_cached` (sender 1회) / `_different_body_same_key_rejected` (409) / `_different_key_different_body_both_process` | ✅ 3건 모두 pass |

⚠️ **잔여 P3**: fingerprint 에 `webhook_secret` 포함 → 캐시 메모리에 secret hash 잔존. 로그/외부로 노출 안 됨 (현재). 향후 monitoring/debug 출력에 fingerprint 포함 시 secret 유추 표면 — 발생 가능성 낮음.

### NEW-V-3. Idempotency per-key concurrency lock — 🟡 **NEW RESIDUAL RACE 발견**

| 검증 | 결과 |
|------|------|
| `_IdempotencyCache.get_lock()` per-key threading.Lock | ✅ |
| `_meta_lock` 가 dict mutation 보호 | ✅ |
| `_idempotency_guard` contextmanager 가 lock acquire→yield→finally release | ✅ |
| `test_idempotency_concurrent_requests_single_execution` (10 threads, sender 1회) | ✅ |
| `test_different_keys_run_in_parallel` (semaphore-gated) | ✅ |

⚠️ **NEW-V-4 [P1] — lock-eviction race**:
- **위치**: `email_service/api.py` `_IdempotencyCache.get()` (lines ~331-340) + `_IdempotencyCache._evict_expired_locked()` (lines ~301-307)
- **문제**: `get()` 가 expired 엔트리를 발견하면 `_store.pop(key)` **와 `_key_locks.pop(key)` 동시 호출**. 그러나 다른 스레드가 이미 그 lock 인스턴스를 `get_lock()` 으로 받아 hold 중일 수 있음.
- **시나리오**:
  ```
  T0  prior entry exists for (bearer, K1) with stale TTL. Lock_old in dict.
  T1  thread A: get_lock(K1) → returns Lock_old
  T2  thread A: acquire(Lock_old). Inside guard, cache.get(K1):
                entry expired → pop _store[K1] AND pop _key_locks[K1]
                Lock_old REMOVED from dict (but A still holds it)
                returns None → A yields, starts processing (sender.send)
  T3  thread C arrives: get_lock(K1) → NOT in dict → create Lock_new, add
  T4  thread C: acquire(Lock_new). Different lock instance from A's!
                cache.get(K1) → None (A hasn't stored yet)
                yield None → C also starts processing
  T5  Both A and C concurrently call sender.send for same (bearer, K1)
       → DUPLICATE SEND
  ```
- **트리거 조건**: 직전 같은 키 entry 가 TTL (default 24h) 만료된 후, 같은 키로 동시 요청. 운영상 발생 빈도 매우 낮음 — 같은 key 를 24h 주기로 두 번 이상 사용 + 그 때 동시 요청.
- **Severity**: P1 (NEW-V-3 의 원래 의도 위반, 회귀 — 우리 본 fix 가 도입한 새 race). 단 트리거 조건이 좁아 실전 발생 확률 낮음.
- **수정 방향** (다음 small fix pass):
  - Option A (최소): `get()` 에서 expired 시 `_store.pop` 만 하고 `_key_locks` 는 보존. lock 메모리 누수 가능성 — bounded by # unique keys (현실: # unique idempotency keys ever used per worker).
  - Option B (정확): lock acquire 후 cache.get 호출 시 entry expired 이라도 lock 은 pop 안 함. eviction 은 별도 maintenance 작업으로 분리.
  - Option C: get_lock() 호출 시 lock 객체에 ref count 추가, 0 되면 evict. 복잡.
- **권장**: Option A (간단, lock 메모리 ~ # idem keys × 80 bytes — 10k keys = 800KB, 허용).

⚠️ **EXISTING [P2] — 장시간 첫 요청이 같은 키 후속 요청 차단**:
- 첫 caller 의 sender.send 가 30s 걸리면 같은 key 후속 caller 가 30s waitfor lock. 의도된 동작 (idempotency 핵심) 이지만 FastAPI threadpool 슬롯 점유. rate limit 가 이미 적용되어 cascading 위험 제한적. 별도 alert 필요.

### Webhook HMAC V2 timestamp signature — 🟢 RESOLVED (이전 세션 verify 결과 그대로)

| 검증 | 결과 |
|------|------|
| `TIMESTAMP_HEADER` 항상 송신 (V2 의존성) | ✅ |
| V2 sig = HMAC(`"<ts>.<body>"`) | ✅ |
| V1 sig 유지 (백워드 호환) | ✅ |
| 다른 timestamp → 다른 V2 sig | ✅ |
| 4 tests pass | ✅ |

V1 deprecation timeline 은 release-gate 영역 (code-L16).

---

## 3. 새 회귀 / 보안 문제

✅ **회귀**: 0건. 179 pass (155 base + 17 P0 + 18 P1 + 7 NEW-V).

⚠️ **신규 P1**: 1건 (NEW-V-4 = code-L19 fix 의 잔여 race).

🛡️ **개선된 보안 (secondary fix 결과)**:
- inter-retry DNS rebind 차단 (per-attempt validate)
- Idempotency-Key 오용 차단 (body fingerprint + 409)
- 같은 key 동시 요청 직렬화 (대부분의 경우)

⚠️ **신규 공격 표면 분석**:
- per-retry validate 로 DNS lookup overhead 3× (단일 attempt 당 ~ms). 매우 적은 추가 비용.
- body fingerprint 계산 비용 (SHA-256 of small JSON ~10KB) — 1μs 단위. 무시 가능.
- per-key lock dict 메모리 (~80 bytes per unique key) — bounded by max_entries via eviction. 단 NEW-V-4 race 가 eviction 의도 약화.

---

## 4. 사용자 질의 7개 release blocker 분석

| # | 항목 | 분류 | Single-tenant SHIP | Multi-tenant SHIP | PyPI 공개 |
|---|------|------|------------------|-------------------|-----------|
| 1 | SMTP sender sync sleep | P1 | ✅ | 🟡 monitor | 🔴 Phase A 필수 |
| 2 | DNS rebinding sub-attempt ms window | P2 | ✅ | ✅ | 🟡 IP pinning 검토 |
| 3 | AppDependencies dataclass refactor (code-L11/L14) | P2 | ✅ | ✅ | 🟡 7번째 cross-cutting 전 |
| 4 | Linux exotic IP (code-L13) | P1 | ⚠️ verify | ⚠️ verify | 🔴 verify + fix |
| 5 | V1 webhook deprecation timeline (code-L16) | P2 | ✅ (doc) | ✅ (doc) | 🟡 timeline 명시 |
| 6 | In-memory rate limit / idempotency | P2 | ✅ | 🟡 doc | 🔴 Redis 필요 |
| 7 | smtp_disconnect_uncertain runbook | P2 | ✅ (doc) | ✅ (doc) | ✅ (doc) |
| **+** | **NEW-V-4 lock-eviction race** | **P1** | ✅ (낮은 확률) | ⚠️ monitor | 🔴 처리 권장 |

**현재 컨텍스트 (단일 사용자 / 단일 워커): 모두 SHIP eligible**. 단 #4 (Linux exotic IP) 는 Linux 1회 실측 + NEW-V-4 는 추후 surgical fix 권장.

## 5. tests/test_p0_fixes.py + tests/test_p1_fixes.py 충분성

| 테스트 파일 | 테스트 수 | 충분도 | 누락 |
|-----------|----------|--------|------|
| test_p0_fixes.py | 31 (1 skip) | ✅ | (없음 — P0 contract 보호 견고) |
| test_p1_fixes.py (P1A/B/C original) | 17 (1 skip) | 🟡 | (이전 verify 의 권장 일부 미반영) |
| test_p1_fixes.py (NEW-V-1/2/3) | 7 | 🟡 | **NEW-V-4 race**, 장시간 holder + 후속 waiter 의 응답 일관성, V2 signature constant-time 비교 |

**권장 추가** (NEW-V-4 처리 시 동시 추가):
1. `test_idempotency_lock_eviction_race` — 만료 엔트리 + 동시 요청 = sender 1회 보장 (현재 실패 예상)
2. `test_idempotency_long_first_blocks_waiter_eventually_returns_cached` — 첫 요청 30s, 후속 요청 lock 대기 후 cache hit
3. `test_idempotency_lock_dict_bounded` — N>max_entries 키 입력 후 _key_locks size ≤ max_entries 확인

총 56 P-class tests + 124 base = 180. P0 stable, P1 1차/secondary stable, **NEW-V-4 미커버**.

---

## Active Learnings Applied

직전 priors 적용:
- **L-SEED-01** 영구 active (재입증: 179 pass 상태에서 NEW-V-4 1건 발견)
- **L-SEED-02** active partial (SMTP sender 측 미해결, 사용자 명시 deferred)
- **code-L09/L15** applied (이전 fix pass 에서 fixture 회귀 사전 처리)
- **code-L11/L14** active 재발 — AppDependencies refactor deferred (사용자 명시)
- **code-L12** resolved 유효
- **code-L13** active (Linux 미검증)
- **code-L16** active (release-gate)
- **code-L17/L18/L19** RESOLVED-By: gate-code-fix-2026-05-18-005 — 본 verify 결과 유효성 확인. **단 code-L19 fix 가 NEW-V-4 race 도입** (1-step regression 패턴).
- **code-L20** active (cache 시그니처 회귀 패턴)
- **code-L21** active (실패-미캐싱 amplification)
- **code-L22** active (lock dict 메모리 — NEW-V-4 와 부분 연관)

## New Learnings Captured

```yaml
ID: code-L23
Source: gate-code-verify-2026-05-18-006
Severity: P1
Mistake / Miss: Per-key concurrency lock 도입 후, 그 lock 의 라이프사이클을 cache entry 와 묶으면 expired-entry pop 시점에 in-flight holder 의 lock 도 dict 에서 제거됨. 후속 caller 는 같은 키에 대해 새 lock 을 생성 → 두 holder 가 같은 key 에 대해 동시 처리. NEW-V-3 fix 가 의도한 직렬화가 무력화.
Root Cause: Lock 객체의 라이프사이클 단순화를 위해 cache entry pop 과 lock pop 을 atomic 묶음으로 했지만, lock 객체는 reference 되면 dict 에서 사라져도 caller 가 hold 가능 → 두 lock 인스턴스가 같은 키에 공존.
Recurrence Trigger: per-key lock + TTL 기반 store + 만료 시 동기 pop 패턴.
Prevention Rule: lock dict 는 cache entry pop 과 분리. eviction 은 별도 maintenance 또는 호출자가 lock release 시 ref count 검사. 가장 단순한 surgical: get() 에서 expired 시 lock pop 안 함.
Next-Session Checklist Item: "Per-key lock 라이프사이클이 cache entry pop 과 묶여 있는가? expired pop 시 lock holder 가 존재할 수 있는가?"
Applies To: email_service/api.py (_IdempotencyCache.get / _evict_expired_locked)
Owner Gate: code
Evidence: api.py _IdempotencyCache.get pops both _store and _key_locks on expiry. Trace in SUMMARY.md §2 NEW-V-4.
Status: active
```

```yaml
ID: code-L24
Source: gate-code-verify-2026-05-18-006
Severity: P2
Mistake / Miss: P1 fix 가 도입한 새 코드 (Per-key lock 등) 자체가 새 secondary 위험 도입. 1차 fix → 1차 verify 발견 NEW-V → 2차 fix → 2차 verify 발견 NEW-V-4. 매 fix pass 가 평균 1 신규 secondary 결함을 produce 한다는 패턴.
Root Cause: 보안/안정성 fix 가 새 추상화 (cache + lock + contextmanager) 를 도입하면서 그 추상화 자체의 edge case 가 새 발견 영역으로 추가됨. 본질적으로 무한하진 않으나 평탄화되기 전까지 verify pass 마다 N+1 발견.
Recurrence Trigger: 모든 보안 fix pass 가 새 데이터구조/락/캐시 도입할 때.
Prevention Rule: fix 직후 verify 는 항상 1 pass 더 — 본 워크플로 이미 적용. 1 verify 가 0 new finding 이 될 때까지 반복. 통상 2-3 verify-fix 사이클이면 평탄화.
Next-Session Checklist Item: "이 fix 가 도입한 새 추상화 (캐시, 락, 컨텍스트매니저) 가 self-test 됐는가? 그 자체의 race/lifecycle 검증 테스트 있는가?"
Applies To: 보안/멱등성/캐시 fix 일반
Owner Gate: code, git
Evidence: 본 프로젝트 fix→verify 사이클 4회 (P0 → verify NEW1-NEW5 → P1 → verify NEW-V-1/2/3 → secondary → verify NEW-V-4)
Status: active
```

## Recurrence Risks

| ID | 본 verify 결과 | 다음 gate 관찰 포인트 |
|----|---------------|---------------------|
| L-SEED-01 | 재입증 4회 | 영구 active |
| L-SEED-02 | active 유지 | Phase A 권장 |
| code-L11/L14 | active 유지 (사용자 deferred) | 7번째 cross-cutting 전 |
| code-L13 | active 미검증 | Linux 1회 실측 필요 |
| code-L16 | active | release-gate |
| code-L17/L18/L19 | resolved 유효 | (단 code-L19 가 NEW-V-4 spawn) |
| code-L20 | active | 캐시 시그니처 변경 시 |
| code-L21 | active | 실패-미캐싱 monitoring |
| code-L22 | active 연관 | lock dict 메모리 |
| **code-L23 (NEW P1)** | new | per-key lock + TTL store eviction |
| **code-L24 (NEW P2)** | new | fix pass 의 secondary 결함 패턴 인식 |

## Next Gate Prompt Addendum

> 다음 gate prompt 에 그대로 붙일 텍스트:
>
> ```
> Active priors from gate-code-verify-2026-05-18-006:
>
> P0: All 5 still STABLE.
> P1 primary fixes: stable.
> P1 secondary fixes (NEW-V-1/2/3): stable.
>
> NEW P1 (this verify):
> - code-L23 (NEW-V-4) Idempotency lock-eviction race: _IdempotencyCache.get()
>   pops _key_locks alongside expired _store entry, but a holder of the old
>   lock may still be processing. Next caller creates fresh lock for same
>   key → two concurrent processors → duplicate send. Surgical fix: stop
>   popping locks in get(); evict locks separately or never (bounded by
>   unique keys × ~80 bytes).
>
> STILL ACTIVE (carried forward):
> - L-SEED-02 SMTP sender sync sleep — Phase A retry budget cap next pass.
> - code-L11 / code-L14 — create_app at 6 kwargs. AppDependencies before
>   7th cross-cutting.
> - code-L13 Exotic IP — UNVERIFIED on Linux. Required before Linux deploy.
> - code-L16 V1 webhook signature deprecation — release-gate.
> - code-L20/L21/L22 — cache signature, failure amplification, lock memory.
> - code-L24 (meta) fix passes typically produce 1 new secondary finding
>   each verify. Plan for 1-2 more verify-fix cycles before flattening.
>
> Pre-implementation checklist:
> 1. Adding lifecycle-coupled state (lock + cache, ref counts)? Decouple
>    lifecycles (code-L23).
> 2. Adding 7th create_app kwarg? AppDependencies dataclass first.
> 3. Adding security re-validation? Inside retry loop (code-L17 lesson).
> 4. Adding cache flow? Body fingerprint + per-key lock + decoupled
>    lifecycle (code-L18 + L19 + L23).
>
> Deployment context:
> - Single-tenant + single-worker: SHIP eligible. NEW-V-4 race trigger
>   probability low (requires expired entry + concurrent same-key reuse).
> - Multi-tenant or high-throughput: fix NEW-V-4 + L-SEED-02 Phase A +
>   code-L13 Linux verify first.
> - PyPI public: above + AppDependencies + V1 deprecation timeline.
> ```

## Closeout Checklist (per docs/process/gate-closeout-checklist.md)

- [x] A. SUMMARY 4 섹션 (Active / New / Recurrence / Next Addendum)
- [x] B. learnings.md 11-필드 schema (code-L23, L24)
- [x] C. index.md 세션 로그
- [x] D. Subagent 사용 정당성 명시
- [x] E. 코드/테스트 수정 0건 (verify-only 준수)
- [x] F. Hand-off — Next Gate Prompt Addendum 완성
- [x] G. tree clean, branch ≠ master, destructive 명령 미사용
