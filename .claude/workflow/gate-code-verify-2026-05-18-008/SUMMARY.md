# Refactor Gate (Verify-only) — Post-NEW-V-4 검증 (flattening 확인)

세션: `gate-code-verify-2026-05-18-008`
타입: **Verification gate** (코드 / 테스트 수정 0건)
브랜치: `claude/cool-bouman-70eb80`
직전: `gate-code-fix-2026-05-18-007` (NEW-V-4 surgical resolution)

## 판정
🟢 **VERIFIED — 5 P0 + 4 P1 fix tier (1차/secondary/tertiary) 모두 STABLE. 0 신규 secondary 결함. code-L24 의 평탄화 예측 확정. 단일 사용자/단일 워커 환경 SHIP eligible. Release Gate (`/hwan-refactor-git`) 진입 가능.**

핵심 결과:
- 183/185 tests pass. 회귀 0건.
- **0 신규 finding** — code-L24 (fix→verify cycle 의 평탄화) 예측 적중. 4번째 verify pass 에서 처음으로 0-finding 달성.
- 사용자 질의 8 release blocker 후보 모두 P1/P2 — 단일 테넌트 환경 ship 차단 없음.
- Release Gate 진입 권장: docs 영역 P2 처리 + Linux 1회 실측만 남음.

## Subagent 사용 정당성

**Subagent 호출 0건**. [subagent-policy.md](../../../docs/process/subagent-policy.md) 조건 점검:
- (A) 다관점: 단일 보안/race 관점 충분 — ❌
- (B) 3+ 파일: api.py + 테스트 = 2 → ❌ (이번 fix 가 좁음)
- (C) Adversarial: fresh context, 직접 가능 — ❌
- (D) Synthesis: 단일 fix 대상 — ❌

→ **2 미만**. 정책상 단일 흐름이 default. 무엇보다 직전 fix 가 단순 line 제거 (새 추상화 0개) → subagent ROI 명백히 부족. 정책 정확히 적용.

---

## 1. P0 5건 재확인

```
P0-1 threadpool starvation       ✅ STABLE
P0-2 webhook_url SSRF             ✅ STABLE (parse + per-retry fetch-time)
P0-3 body/subject size limits     ✅ STABLE
P0-4 rate limit                   ✅ STABLE
P0-5 post-DATA disconnect         ✅ STABLE
```

회귀 0건. 31 P0 회귀 테스트 모두 통과.

## 2. P1 모든 tier 재확인

| Tier | 항목 | 상태 | 회귀 테스트 |
|------|------|------|------------|
| 1차 | SSRF parse-time validation | ✅ STABLE | TestP1A (5 tests, 1 skip) |
| 1차 | Idempotency cache (basic) | ✅ STABLE | TestP1B (8 tests) |
| 1차 | Webhook HMAC V2 timestamp | ✅ STABLE | TestP1C (5 tests) |
| Secondary | SSRF per-retry re-validation (code-L17) | ✅ STABLE | TestNewV1 (2 tests) |
| Secondary | Idempotency body fingerprint 409 (code-L18) | ✅ STABLE | TestNewV2 (3 tests) |
| Secondary | Idempotency per-key concurrency lock (code-L19) | ✅ STABLE | TestNewV3 (2 tests) |
| Tertiary | Lock/cache lifecycle 분리 (code-L23) | ✅ STABLE | TestNewV4 (4 tests) |

총 **29 P1 회귀 테스트** (1 skip), 모두 통과. 전체 baseline 124 + P0 31 + P1 29 = 184 신규 추가, +1 base skip 으로 183 pass 2 skip.

## 3. NEW-V-4 fix 의 secondary 영향 분석 (adversarial)

직전 fix 가 3 line `_key_locks.pop(...)` 제거 + 주석/TODO. 새 추상화 0개. 신규 race / memory / 보안 표면 점검:

| 영역 | 점검 | 결과 |
|------|------|------|
| 락 순서 (deadlock 위험) | `get_lock` (meta_lock only) → caller acquires per-key lock → `cache.get/put` (meta_lock briefly). 일관 순서. | ✅ 안전 |
| 메모리 누수 | lock dict 은 unique-key cardinality 로 bound (`code-L25` 기록). rate-limit 60/min × hostile caller 가 random key 매번 사용 시 최대 ~7MB/day. **이미 인지된 P2**. | ✅ 신규 X (code-L25 로 추적 중) |
| 재발 race | `get_lock` 항상 dict 존재 lock 반환 → in-flight holder 와 후속 caller 가 같은 lock 인스턴스. fix 정확. | ✅ 안전 |
| HTTPException 409 + lock | `_idempotency_guard` 의 finally 가 raise 시도 항상 release. | ✅ 안전 |
| 만료 entry + lock retain 흐름 | T1 A 잠금 → cache.get expired → store pop (lock 유지) → process → put new → release. T2 B 같은 lock 대기 → 끝나면 acquire → 새 entry hit. | ✅ 정확 동작 (테스트 확인) |
| Lock 객체 GC | `threading.Lock` 은 단순 primitive, refcycle 없음. dict 에 ref 유지 + 외부 ref (holder) → 정상. | ✅ 안전 |

**신규 secondary 결함 0건**. code-L24 의 평탄화 예측 확정.

## 4. 새 회귀 / 새 보안 문제

✅ **회귀**: 0건 (183 pass).
✅ **신규 보안 문제**: 0건.
✅ **신규 메모리/race 문제**: 0건 (code-L25 는 직전 세션 등록, 이번 verify 에서 신규 X).

## 5. 남은 리스크 재분류 (release blocker 분석)

| 항목 | 분류 | Single-tenant SHIP | Multi-tenant SHIP | PyPI 공개 |
|------|------|------------------|-------------------|-----------|
| SMTP sender sync sleep (L-SEED-02) | P1 | ✅ | 🟡 monitor | 🔴 Phase A |
| DNS rebinding sub-attempt ms (code-L12 잔여) | P2 | ✅ | ✅ | 🟡 IP pinning 검토 |
| AppDependencies dataclass (code-L11/L14) | P2 | ✅ | ✅ | 🟡 7번째 cross-cutting 전 |
| Linux exotic IP (code-L13) | P1 | ⚠️ verify | ⚠️ verify | 🔴 verify + fix |
| V1 webhook deprecation timeline (code-L16) | P2 | ✅ doc | ✅ doc | 🟡 timeline |
| In-memory rate limit / idempotency | P2 | ✅ | 🟡 doc | 🔴 Redis |
| Lock dict memory bound (code-L25) | P2 | ✅ | ✅ | 🟡 idle TTL eviction |
| smtp_disconnect_uncertain runbook | P2 | ✅ doc | ✅ doc | ✅ doc |

**현재 컨텍스트 (단일 사용자 / 단일 워커): 모두 SHIP eligible**. 가장 작은 추가 조치: Linux 1회 실측 (`python -c "import socket; print(socket.getaddrinfo('2130706433', None))"` 결과 확인).

## 6. Release Gate 진입 가능 여부

### 🟢 Release Gate `/hwan-refactor-git` 진입 가능 (단일 사용자/단일 워커 가정)

**근거**:
1. P0 5건 모두 resolved + 31 회귀 테스트
2. P1 1차/secondary/tertiary 모두 resolved + 29 회귀 테스트
3. 회귀 0건 (183 pass)
4. 신규 secondary 결함 0건 (code-L24 평탄화 확정 — 4번째 verify 에서 처음 달성)
5. 남은 리스크 모두 P1/P2 with deployment-context dependency, 본 컨텍스트 ship 차단 없음

**Release Gate 에서 처리 예상 영역**:
- ✅ docs: V1 deprecation timeline, smtp_disconnect_uncertain runbook, in-memory state docs, lock dict memory docs
- ✅ CHANGELOG: 모든 P0/P1 fix 요약
- ✅ README: deployment guidance (single vs multi worker, reverse proxy body cap)
- ⚠️ verify: Linux exotic IP 1회 실측 (code-L13)
- 📋 plan only: Phase A retry budget cap (L-SEED-02), AppDependencies refactor (code-L11/L14)

### 추가 가능 (선택, release 전):
- **Linux 실측 1회** (code-L13): `python -c "import socket; print(socket.getaddrinfo('2130706433', None))"` Linux 환경에서 실행. gaierror → safe, 127.0.0.1 → validator 추가 검증 필요.
- **Phase A retry budget cap** (L-SEED-02): 작은 surgical fix 가능. `SmtpSender(max_total_retry_sleep_seconds=10)` 옵션 추가. 본 verify 와 무관, release 전 1 fix pass 추가 권장.

---

## Active Learnings Applied

직전 priors 적용:
- **L-SEED-01** (테스트 통과 ≠ 안전): **5회차 재입증** 시도 → **0건 발견**. learning 의 영구 유효성 무력화 X (현재 코드가 충분히 보호됨 의미). 영구 active.
- **L-SEED-02** (BG + sync sleep): active deferred. 사용자 명시.
- **code-L09/L15** (validator + fixture 회귀): 본 verify 와 무관. applied 유효.
- **code-L11/L14** (create_app bloat): active deferred. 6 kwargs 도달.
- **code-L13** (exotic IP): active 미검증.
- **code-L16** (V1 deprecation): active. release-gate 영역.
- **code-L17/L18/L19** RESOLVED 유효.
- **code-L20/L21/L22** active (운영/docs 영역).
- **code-L23** (NEW-V-4): **RESOLVED-By: gate-code-fix-2026-05-18-007**. 본 verify 가 fix 의 정확성 + 신규 결함 없음 확정.
- **code-L24** (meta): **예측 적중 → 평탄화 확정**. 4번째 verify 에서 처음 0 finding. learning 자체의 효용 + 정당성 증명. status: **VALIDATED** (single occurrence, predictive value confirmed).
- **code-L25** (lock dict 메모리): active, release-gate 영역.

## New Learnings Captured

```yaml
ID: code-L26
Source: gate-code-verify-2026-05-18-008
Severity: P3
Mistake / Miss: Fix→verify cycle 의 평탄화가 4번째 verify 에서 처음 달성. 그 전 3 verify 모두 1-3 신규 finding 산출. 평탄화 시그널은 (a) fix pass 가 새 추상화 도입 X, (b) line 단순 제거 또는 1-line 추가, (c) 회귀 테스트가 4건 이상. 이 셋이 동시에 충족될 때 다음 verify 는 0 finding 예상.
Root Cause: 보안 fix 의 점진적 narrowing. 처음에는 큰 코드 (validate/idempotency cache) 도입 → 새 표면. 다음 fix 는 그 표면 안의 race/lifecycle 수정 → 더 작은 새 표면. 결국 line 단위 수정으로 수렴.
Recurrence Trigger: 다음 보안/안정성 fix 시리즈 시작 시.
Prevention Rule: 평탄화 시그널 3개 (위) 가 갖춰지면 release 단계 진입 안전. 갖춰지지 않으면 1-2 verify-fix 사이클 더 진행.
Next-Session Checklist Item: "이번 fix 가 새 추상화/dict/lock 을 도입하는가? 단순 line 제거/추가인가? 회귀 테스트 ≥4건인가? 모두 만족이면 다음 verify 평탄화 예상."
Applies To: 모든 보안/안정성 fix 시리즈
Owner Gate: code
Evidence: 본 프로젝트 fix→verify 사이클 4회, code-L24 예측 적중 (이 세션)
Status: active
```

```yaml
ID: code-L27
Source: gate-code-verify-2026-05-18-008
Severity: P2
Mistake / Miss: Lock 순서 (per-key lock → meta_lock) 가 일관되어 deadlock 위험 없음 — 그러나 이 invariant 가 docstring 에 명시되지 않음. 향후 다른 cross-cutting state (예: AppDependencies 도입) 가 새 lock 추가 시 ordering 깨질 위험.
Root Cause: 락 순서 invariant 가 implicit. 단일 dev 가 만든 코드라 의도된 순서 명확하지만, 다음 dev 가 인지 못하면 회귀 가능.
Recurrence Trigger: 새 lock / shared mutex 도입 시.
Prevention Rule: 락 순서 invariant 를 클래스 docstring 또는 docs/architecture.md 에 명시. 새 lock 추가 시 ordering 위치 검토 의무.
Next-Session Checklist Item: "새 lock/mutex 를 도입하는가? 기존 lock 들과의 acquisition order 가 문서화됐는가?"
Applies To: email_service/api.py (_IdempotencyCache, _SlidingWindowLimiter), 향후 lock-bearing 클래스
Owner Gate: code
Evidence: api.py 의 _meta_lock + per-key _key_locks + _SlidingWindowLimiter._lock — 3개 lock 의 ordering invariant 미문서화 (이 세션)
Status: active
```

## Recurrence Risks

| ID | 본 verify 결과 | 다음 gate 관찰 포인트 |
|----|---------------|---------------------|
| L-SEED-01 | 5회차 (0 finding) — 단순 평탄화 신호 | 영구 active, 평탄화 후에도 회귀 테스트 의무 |
| L-SEED-02 | active deferred | release-gate 영역 또는 small fix pass |
| code-L11/L14 | active deferred | 7번째 cross-cutting 전 |
| code-L13 | active 미검증 | release 전 Linux 실측 |
| code-L16 | active | release-gate docs |
| code-L17-L23 | resolved 유효 | — |
| code-L20/L21/L22 | active | release-gate docs |
| code-L24 (meta) | **VALIDATED** (예측 적중) | future fix 시리즈에 재적용 |
| code-L25 | active | release-gate (idle TTL) |
| **code-L26 (NEW P3)** | new | 미래 fix 시리즈 평탄화 시그널 추적 |
| **code-L27 (NEW P2)** | new | lock ordering 문서화 (release-gate docs 또는 다음 small fix pass) |

## Next Gate Prompt Addendum

> 다음 gate (release-gate `/hwan-refactor-git` 권장) prompt 에 그대로 붙일 텍스트:
>
> ```
> Active priors from gate-code-verify-2026-05-18-008:
>
> CODE STATE (release-ready for single-tenant single-worker):
> - 5 P0: resolved + 31 regression tests.
> - 4 P1 tiers (primary + secondary + tertiary): resolved + 29 regression tests.
> - 0 new findings this verify (code-L24 flattening prediction confirmed).
> - Total: 183 tests pass, 2 skipped, 0 regressions.
>
> STILL ACTIVE (release-gate scope):
> - L-SEED-02 SMTP sender sync sleep — small fix pass (Phase A budget cap)
>   recommended before release if multi-tenant.
> - code-L11 / code-L14 — create_app at 6 kwargs. AppDependencies refactor
>   recommended before adding 7th concern.
> - code-L13 Exotic IP — REQUIRED: 1× Linux verify before first Linux
>   deploy. Single command:
>     python -c "import socket; print(socket.getaddrinfo('2130706433', None))"
>   gaierror → safe. 127.0.0.1 → add IP-form normalization to validator.
> - code-L16 V1 webhook deprecation timeline — release-gate (docs).
> - code-L20/L21/L22/L25/L27 — docs/monitoring concerns. release-gate to
>   handle:
>   * V1 deprecation timeline in README + CHANGELOG
>   * smtp_disconnect_uncertain runbook in docs/runbooks/
>   * Single-vs-multi-worker deployment guide (in-memory state caveats)
>   * Lock dict memory bound documentation
>   * Lock ordering invariant in api.py docstring or docs/architecture.md
>
> Release-gate readiness checklist (single-tenant single-worker):
> 1. README sections: deployment guide, error codes table, known limitations
> 2. CHANGELOG: 5 P0 + 4 P1 tier resolutions, V1 deprecation announcement
> 3. docs/runbooks/: smtp-disconnect-uncertain, smtp-outage, webhook-outage
> 4. Linux exotic IP: 1× CI check or manual verify
> 5. Optional (multi-tenant path): Phase A retry budget cap small fix
>
> NO new code/test changes from this verify. Tree clean. Branch not main.
> 183 pass, 2 skip. Ready for /hwan-refactor-git.
> ```

## Closeout Checklist (per docs/process/gate-closeout-checklist.md)

- [x] A. SUMMARY 4 섹션 (Active / New / Recurrence / Next Addendum)
- [x] B. learnings.md 11-필드 schema (code-L26, code-L27)
- [x] C. index.md 세션 로그
- [x] D. Subagent 사용 정당성 명시 (이번엔 0건 + 명확한 사유)
- [x] E. 코드/테스트 수정 0건 (verify-only)
- [x] F. Hand-off — Next Gate Prompt Addendum 으로 release-gate 입력 완성
- [x] G. tree clean, branch ≠ master, destructive 명령 미사용
