# Code Fix Session — NEW-V-4 Lock-Eviction Race Surgical Resolution

세션: `gate-code-fix-2026-05-18-007`
타입: **Implementation pass** (NEW-V-4 만, 외 P1/P2 0건)
브랜치: `claude/cool-bouman-70eb80`
직전: `gate-code-verify-2026-05-18-006` (verify, NEW-V-4 = code-L23 발견)

## 판정
🟢 **NEW-V-4 lock-eviction race resolved. +4 회귀 테스트 (race + 2 unit + waiter), 0 regressions. 단일 사용자 / 단일 워커 환경 SHIP eligible.**

| Before | After |
|--------|-------|
| 179 pass, 2 skip | 183 pass, 2 skip (+4) |
| code-L23 active (NEW-V-4) | code-L23 resolved |

## 처리한 항목

### NEW-V-4 / code-L23 — Cache entry ↔ per-key lock lifecycle 분리
- **문제**: `_IdempotencyCache.get()` 가 expired entry 발견 시 `_store.pop` 과 함께 `_key_locks.pop` 도 호출. in-flight holder 가 hold 한 채로 lock 인스턴스가 dict 에서 사라짐 → 후속 caller 가 `get_lock()` 으로 새 lock 생성 → 같은 (bearer, key) 가 두 holder 에서 동시 처리 가능. NEW-V-3 의 직렬화 무력화.
- **수정 위치** (3개, 모두 `email_service/api.py`):
  1. `_IdempotencyCache.get()` line ~322: expired entry 발견 시 `_store.pop` 만, `_key_locks.pop` 제거
  2. `_IdempotencyCache._evict_expired_locked()` line ~301: 동일
  3. `_IdempotencyCache.put()` line ~349 (max-capacity oldest 제거): 동일
- **추가 변경**: class docstring 및 `__init__` 의 `_key_locks` 주석 갱신 — lifetime 이 decoupled 됨을 명시. `_evict_expired_locked` 에 TODO 추가 (lock dict 메모리 향후 별도 maintenance pass — 1h idle TTL eviction 검토).
- **외부 API / 응답 스키마 / env vars: 0 변경**.
- **Lock dict 메모리**: # unique (bearer, key) × ~80 bytes. 10k unique keys ≈ 800KB. 사용자 명시한 대로 TODO 주석으로만 표시, 이번 pass 미해결.

### 회귀 테스트 (`tests/test_p1_fixes.py` `TestNewV4_LockEvictionRace`)

4 신규 테스트:
1. **`test_idempotency_lock_dict_retains_lock_after_cache_expiry`** — unit 수준. `get_lock("b","k")` → put → expired 까지 시간 진행 → `get()` 가 None 반환 (expiry 경로) → `get_lock("b","k")` 가 동일 Lock 인스턴스 반환 (identity 검증). NEW-V-4 의 핵심 invariant.
2. **`test_idempotency_lock_retained_after_capacity_eviction`** — unit. max_entries=2, put 3개 → 가장 오래된 entry 가 _store 에서 evict 되지만 그 key 의 lock 은 dict 에 보존됨.
3. **`test_idempotency_lock_eviction_race`** — end-to-end. 짧은 TTL (0.05s) 로 pre-seed 한 expired entry + 10 동시 요청 + slow_send. fix 없으면 race → sender 2+ 회 호출. fix 적용 → **sender.send.call_count == 1**, 모든 응답 동일.
4. **`test_idempotency_long_first_blocks_waiter_eventually_returns_cached`** — 첫 요청 sender 가 release_first.wait() 로 block. 두 번째 요청은 lock 대기. 첫 sender 진입 후 두 번째가 lock 대기 중 시점에 `sender.send.call_count == 1` 단언 (두 번째가 sender 호출 안 함을 확인). release → 첫 완료, 두 번째 cached response 반환. 최종 sender.call_count == 1.

## 변경 파일

| File | LOC delta | 변경 |
|------|-----------|------|
| `email_service/api.py` | +12 / −5 | `_IdempotencyCache.get()` / `_evict_expired_locked` / `put()` 의 3개 `_key_locks.pop` 호출 제거. 주석 + TODO 추가. class docstring 갱신. |
| `tests/test_p1_fixes.py` | +185 (new class) | `TestNewV4_LockEvictionRace` 4 tests |

런타임 외부 인터페이스 미변경. env vars 미변경. SMTP sender 미변경. AppDependencies 리팩토링 미수행 (사용자 명시).

## 테스트 결과

```
Targeted (TestNewV4_LockEvictionRace): 4 passed
Full suite:                            183 passed, 2 skipped
Δ vs prior:                           +4 new, 0 regressions
```

## 남은 리스크 (이번 범위 밖, 동결)

1. **SMTP sender sync sleep** (L-SEED-02 partial): 31s budget 유지. 사용자 명시 deferred.
2. **DNS rebinding sub-attempt ms window** (code-L12 잔여 P2): IP pinning 필요. 본 pass 미수정.
3. **AppDependencies dataclass refactor** (code-L11/L14, 6 kwargs 도달): 사용자 명시 deferred.
4. **Linux exotic IP** (code-L13): 미검증.
5. **V1 webhook deprecation timeline** (code-L16): release-gate.
6. **In-memory state docs** (code-L21/L22 일부): docs 영역.
7. **smtp_disconnect_uncertain runbook**: docs.
8. **Lock dict 메모리 bound** (NEW: code-L22 일부 + 본 fix TODO): unique-key cardinality × 80 bytes. 10k = 800KB. release 전 README 에 인지 사항 추가 또는 idle TTL eviction (~1h) maintenance pass.

이번 pass 가 introduce 한 **신규 secondary 결함**: 없음 (예측됨 — code-L24 의 평탄화 cycle 시작). 다음 verify 가 0 finding 으로 평탄화될 가능성 높음.

---

## Active Learnings Applied

직전 priors 적용 결과:
- **L-SEED-01** (테스트 통과 ≠ 안전): 4 회귀 테스트로 NEW-V-4 contract 보호. 영구 active.
- **L-SEED-02** (BG + sync sleep): 인지, 사용자 명시 deferred.
- **code-L09/L15** (validator + fixture 회귀): 본 fix 는 cache 시그니처 변경 없음 (단순 lock pop 제거) → fixture 회귀 0건. applied 유효.
- **code-L11/L14** (create_app bloat): active 유지, 사용자 명시 deferred.
- **code-L13** (exotic IP), **code-L16** (V1 deprecation), **code-L17/L18/L19** (resolved), **code-L20/L21/L22** (active): 본 fix 와 무관, 유지.
- **code-L23** (lock-eviction race): **RESOLVED by gate-code-fix-2026-05-18-007** — get/evict_expired/put 의 3 `_key_locks.pop` 제거.
- **code-L24** (meta — fix pass 의 secondary 결함 패턴): 본 pass 가 신규 결함을 도입했는지 self-check. **단순 line 제거 + TODO 추가** 라 새 추상화 0개 → secondary 결함 발생 가능성 매우 낮음. code-L24 의 "1-2 cycle 후 평탄화" 예측과 일치.

## New Learnings Captured

```yaml
ID: code-L25
Source: gate-code-fix-2026-05-18-007 (NEW-V-4 surgical)
Severity: P2
Mistake / Miss: Per-key lock dict 와 cache entry dict 의 lifecycle 분리가 정답. 그러나 lock dict 메모리는 unique-key cardinality 로만 bound — 적대적 caller 가 매번 새 random Idempotency-Key 사용 시 무한 증가 가능.
Root Cause: lock 라이프사이클 단순화 (단일 dict, eviction 없음) 와 메모리 bound (idle TTL eviction) 의 trade-off. surgical 우선해서 단순화 선택, 메모리 bound 는 TODO 로 명시.
Recurrence Trigger: per-key lock 또는 per-key state 도입 시.
Prevention Rule: lock/state dict 에 별도 maintenance pass (idle TTL, e.g. 1h) 또는 LRU bound. release 전 (또는 적대적 caller 가능한 시나리오 전) 처리.
Next-Session Checklist Item: "Per-key state dict 에 메모리 bound 가 있는가? idle TTL 또는 LRU? release-gate 전 처리됐는가?"
Applies To: email_service/api.py (_IdempotencyCache._key_locks), 향후 per-key state
Owner Gate: code
Evidence: api.py _IdempotencyCache._evict_expired_locked TODO 주석 (이 세션)
Status: active
```

## Recurrence Risks

| ID | 본 fix 결과 | 다음 gate 관찰 포인트 |
|----|-------------|---------------------|
| L-SEED-01 | active (영구) | — |
| L-SEED-02 | active partial deferred | Phase A 권장 |
| code-L11/L14 | active deferred | 7번째 cross-cutting 전 |
| code-L13 | active 미검증 | Linux 검증 |
| code-L16 | active | release-gate |
| code-L17/L18/L19 | resolved 유효 | — |
| code-L20/L21/L22 | active | 운영 monitoring/docs |
| **code-L23** | **RESOLVED-By: gate-code-fix-2026-05-18-007** | 다음 verify 에서 retain 검증 |
| code-L24 (meta) | 본 pass 가 평탄화 cycle 시작 — 단순 line 제거 라 신규 결함 가능성 낮음 | 다음 verify 결과 0 finding 이면 평탄화 확정 |
| **code-L25 (NEW P2)** | new | lock dict 메모리 bound (release-gate 영역) |

## Next Gate Prompt Addendum

> 다음 gate prompt 에 그대로 붙일 텍스트:
>
> ```
> Active priors from gate-code-fix-2026-05-18-007:
>
> RESOLVED (this session):
> - code-L23 (NEW-V-4) Per-key lock dict lifecycle decoupled from cache
>   entry. Eviction paths (get/_evict_expired_locked/put) keep _key_locks
>   intact; an in-flight holder is no longer orphaned by store eviction.
>
> STILL ACTIVE:
> - L-SEED-02 SMTP sender sync sleep — Phase A retry budget cap.
> - code-L11 / code-L14 — create_app at 6 kwargs. AppDependencies before
>   7th cross-cutting.
> - code-L13 Exotic IP — UNVERIFIED on Linux.
> - code-L16 V1 webhook deprecation timeline — release-gate.
> - code-L20/L21/L22 — cache signature, failure amplification, lock memory.
> - code-L25 (NEW P2) — Lock dict memory bounded only by unique-key
>   cardinality. Hostile caller with random keys can grow ~80 bytes per
>   unique key. 10k unique keys ≈ 800KB. Add idle TTL eviction (e.g. 1h)
>   or LRU bound before exposing to untrusted callers / multi-tenant.
> - code-L24 (meta) — predicts THIS pass should NOT introduce a new
>   secondary finding (simple line removal, no new abstraction). Next
>   verify will confirm flattening.
>
> Pre-implementation checklist (carry forward):
> 1. Per-key state dict + bounded eviction policy (code-L23 + L25).
> 2. AppDependencies before 7th create_app kwarg (code-L11/L14).
> 3. Security re-validation inside retry loops (code-L17 lesson).
> 4. Cache flow: body fingerprint + per-key lock + decoupled lifecycle
>    (code-L18 + L19 + L23).
>
> Deployment context:
> - Single-tenant + single-worker: SHIP eligible TODAY.
> - Multi-tenant: handle code-L25 (memory bound) + L-SEED-02 (sync sleep)
>   + code-L13 (Linux verify).
> - PyPI public: above + AppDependencies + V1 deprecation timeline.
> ```
