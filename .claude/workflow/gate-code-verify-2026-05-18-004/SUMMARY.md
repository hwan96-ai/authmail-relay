# Refactor Gate (Verify-only) — Post-P1-Fix 검증

세션: `gate-code-verify-2026-05-18-004`
타입: **Verification gate** (코드 수정 0건)
브랜치: `claude/cool-bouman-70eb80`
직전: `gate-code-fix-2026-05-18-003` (P1 surgical fix — SSRF rebinding mitigation / idempotency / HMAC V2)

## 판정
🟡 **PARTIAL VERIFIED — 5 P0 안정 유지, 3 P1 fix 구조적으로는 sound 이나 secondary gap 3건 발견. 단일 사용자 / 단일 워커 / 단일 테넌트 환경에서는 SHIP 가능. 다중 사용자 / 멀티 워커 / PyPI 공개 환경은 새 발견 P1 처리 후 ship 권장.**

핵심:
- 172/174 tests pass (변화 없음, 회귀 0)
- 5 P0: structurally resolved 유지 ✅
- 3 P1 fixes: 모두 동작하나 secondary gap 3건 발견 — 모두 P1, P0 차단 없음
- 사용자 질의 5 release blocker 항목 분석: 0건 P0, 4건 P1, 1건 P2

## Subagent 사용 정당성

이번 verify gate **subagent 호출 0건**. [docs/process/subagent-policy.md](../../../docs/process/subagent-policy.md) §사용 조건:
- (A) 다관점? P1 fix 코드의 보안+동시성+release 관점 → 잠재적 가치 ✅
- (B) 3+ 파일? webhooks/api/url_validation/test_p1_fixes/test_p0_fixes = 5 ✅
- (C) Adversarial 필요? 신규 코드 (idempotency cache 등) 자체에 새 공격 표면 ✅
- (D) Synthesis 기준? P0/P1 1:1 + release blocker rubric ✅
- (E) Phase 병렬 요구? 아님 ❌

→ 4 of 5 충족. **하지만** 직전 fix pass 가 본인 작성 → fresh context. 직전 verify gate (2026-05-18-002) 도 단일 흐름에서 NEW-1, NEW-2 발견. 같은 패턴 일관성 유지 — **단일 흐름**.

---

## 1. 5 P0 재검증 (post-P1-fix)

| P0 | 상태 | 검증 |
|----|------|------|
| 1. threadpool starvation | ✅ STABLE | webhook 8s budget 유지, jitter 적용, 회귀 테스트 통과 |
| 2. webhook_url SSRF | ✅ STABLE (강화됨) | Pydantic + fetch-time 이중 검증 |
| 3. body/subject size limits | ✅ STABLE | max_length 변경 없음, 4 tests pass |
| 4. rate limit | ✅ STABLE | sliding window 변경 없음, 6 tests pass |
| 5. post-DATA disconnect | ✅ STABLE | sendmail_returned 플래그 변경 없음, 3 tests pass |

**모든 5 P0 회귀 0건. P1 fix 가 P0 contract 손상 없이 추가됨.**

## 2. 3 P1 fixes 충분성 검증

### P1-A. SSRF DNS rebinding mitigation — 🟡 **구조적 OK, 잔여 gap 1건**

**검증 항목**:
- ✅ `validate_webhook_url(url)` 가 `deliver_webhook` 시작 부에 호출됨 (webhooks.py:97)
- ✅ 검증 실패 시 HTTP 전송 안 함, `email_webhook_failed_total.inc()` 호출
- ✅ 5 회귀 테스트 모두 통과 (1 skip prometheus dep)
- ✅ DNS rebinding 시뮬레이션 테스트 (`test_dns_rebinding_simulation_blocks_second_resolution`) 통과

⚠️ **NEW-V-1 [P1] — per-retry 재검증 누락**:
- **위치**: webhooks.py:97 (validate) ↔ webhooks.py:127+ (for-loop with retries)
- **문제**: validate 가 **루프 시작 전 1회**만 호출. 3 retry 동안 DNS 가 rebind 되어도 재검증 0건. 즉 attempt 1 통과 후, attempt 2/3 가 private IP 로 connect 가능.
- **시나리오**: 1st attempt 503 응답 → 재시도 대기 (sleep 1-5s) → DNS rebound to 127.0.0.1 → attempt 2 가 127.0.0.1 hit.
- **현재 mitigation**: TOCTOU 윈도우가 "validate→첫 POST" ms 단위 → "첫 POST→마지막 POST" 8s 단위로 확대됨.
- **수정 방향** (surgical, 다음 fix pass): validate 를 for-loop **안**으로 이동, attempt 마다 재실행.

### P1-B. HTTP /send idempotency — 🟡 **구조적 OK, 잔여 gap 2건**

**검증 항목**:
- ✅ `_IdempotencyCache` 정확성: TTL, eviction, bearer 격리 (8 tests pass)
- ✅ 헤더 길이 검증 (≤128 → 400)
- ✅ 실패 응답 (502) 캐시 안 됨 — caller 재시도 시 sender 호출
- ✅ "accepted" status 도 캐시 (webhook async path)
- ✅ TTL=0 비활성화 동작

⚠️ **NEW-V-2 [P1] — body fingerprint 미검증**:
- **위치**: api.py `_idempotency_lookup` / `_idempotency_store`
- **문제**: 캐시 키 = `(bearer, idempotency_key)` 만. 요청 body 해시 미포함.
- **공격 시나리오**: caller 가 같은 키로 두 다른 body 전송 → 두 번째 호출이 첫 body 의 응답 반환. 의도된 멱등성 contract 위반.
- **표준 비교**: Stripe Idempotency-Key는 body fingerprint 도 검증 — 다르면 422.
- **현재 risk**: caller bug 시 잘못된 응답. 보안 영향 낮음 (auth-gated, 자기 충돌).
- **수정 방향**: cache key 에 `hashlib.sha256(body).hexdigest()` 추가. 또는 body 다를 시 422.

⚠️ **NEW-V-3 [P1] — process/store race condition**:
- **위치**: api.py send 라우트의 lookup → process → store 흐름
- **문제**: lookup, process, store 가 atomic 아님. 같은 key 의 2 동시 요청:
  - T0: req-A lookup → miss
  - T0+ε: req-B lookup → miss
  - T1: req-A process → sender.send (1st)
  - T2: req-B process → sender.send (2nd) ← **중복 발송**
  - T3: req-A store
  - T4: req-B store (overwrites or wins by timing)
- **현재 risk**: 같은 key 동시 호출 시 중복 발송. caller retry storm (네트워크 flapping) 에서 발생 가능.
- **수정 방향**: in-process lock per key (key별 lock map). 또는 store 가 set-if-empty 로 race 차단.

### P1-C. webhook HMAC V2 timestamp signature — 🟢 **구조적 OK, V1 vulnerability 잔여**

**검증 항목**:
- ✅ `TIMESTAMP_HEADER` 항상 송신
- ✅ V2 = HMAC over `"<ts>.<body>"`, 다른 timestamp → 다른 sig (replay 차단 핵심)
- ✅ V1 호환 (body-only sig) 유지 → 기존 수신자 영향 0
- ✅ secret 없을 시 두 sig 모두 없음, timestamp 만 송신
- ✅ Module docstring 에 receiver migration 4 단계 가이드

⚠️ **EXISTING [P1] — V1 receiver 는 여전히 replay 취약**:
- 이 fix 의 한계가 아닌 design choice. V1 deprecation timeline 명시되지 않음 → 사용자가 영영 V1 만 검증할 수 있음.
- **code-L16** (직전 세션 등록) 가 이 사항을 추적 중. release-gate 영역.

## 3. 새 회귀/보안 문제

✅ **회귀**: 0건. 172 pass (155+17 신규).

⚠️ **신규 공격 표면 / gap (모두 NEW P1)**:

1. **NEW-V-1**: SSRF re-validate 가 retry loop 외부에 위치 → retry 간 DNS rebinding 가능
2. **NEW-V-2**: Idempotency cache key 에 body fingerprint 없음 → 다른 body, 같은 key → 잘못된 응답
3. **NEW-V-3**: Idempotency lookup→process→store race → 동시 요청 시 중복 발송

이 3건 모두 새로 도입된 P1 코드 자체의 secondary gap. P0 차단 없음. surgical fix 가능.

🛡️ **개선된 보안 (P1 pass 결과)**:
- DNS rebinding TOCTOU 윈도우 수초 → ms 단위로 축소 (단, retry 간 갭은 NEW-V-1)
- /send 멱등성 1차 mitigation (race + body 검증 미흡)
- webhook V2 sig 로 replay 차단 (수신자 채택 시)

---

## 4. 사용자 질의 5개 release blocker 분석

### 4a. SMTP sender sync sleep
- **분류**: P1
- **Release blocker?** ❌ **NO** — 단, deployment context 의존
- **이유**: 31s max budget. `/send` route 동기 호출 시 threadpool 슬롯 점유. rate limit (60/분 default) + size cap 으로 cascading 위험 완화. 단일 워커 + 낮은 트래픽 (~1 req/s) 면 무해.
- **격상 조건**: 다중 워커 + 100+ req/s 환경에선 P0. 또는 SMTP outage 시 systemic 실패 위험.
- **권장**: 다음 small fix pass 에 Phase A (retry budget cap) 도입. v0.4.0 pre-work 로 Phase B (async path).

### 4b. V1 webhook signature deprecation
- **분류**: P1
- **Release blocker?** ❌ **NO**
- **이유**: V2 는 이미 송신 중. V1 수신자는 caller 의 시스템 (외부). caller 가 V2 채택 안 하면 그 caller 만 replay 취약. 우리 의무는 V2 제공 + 마이그레이션 path 문서화 (이미 docstring 에 있음).
- **권장**: README/CHANGELOG 에 V1 deprecation timeline 명시 (예: "v0.5.0 에서 V1 헤더 제거"). release-gate (`/hwan-refactor-git`) 영역.

### 4c. In-memory idempotency / rate limit
- **분류**: P2
- **Release blocker?** ❌ **NO**
- **이유**: 단일 워커 운영 시 의도된 동작. 단일 사용자/단일 테넌트면 cap 정확. 멀티 워커 → cap × workers (cap 이 N배 큰 것). 이 자체가 보안 사고는 아님, capacity planning 이슈.
- **격상 조건**: 정확한 quota 가 SLA 일부면 P1 → Redis-backed 구현 필요.
- **권장**: README `Deployment` 섹션에 multi-worker quota math 명시.

### 4d. Linux exotic IP encoding (code-L13)
- **분류**: P1
- **Release blocker?** ⚠️ **CONDITIONAL** — Linux 프로덕션 첫 배포 전 검증 필수
- **이유**: Windows getaddrinfo 는 exotic form (`2130706433`, `0x7f000001`) 거부 확인됨. Linux glibc 는 historically 정수 IP 수용. httpx canonicalization 동작 미실측. **validator 가 ValueError → DNS 분기 → glibc 가 127.0.0.1 로 해석 가능**.
- **검증 방법** (코드 수정 0건):
  ```bash
  # Linux 컨테이너에서:
  python -c "import socket; print(socket.getaddrinfo('2130706433', None))"
  # → 만약 ('127.0.0.1', 0) 반환 → bypass 확정 → P0 격상
  ```
- **권장**: CI matrix 에 Linux Python 3.10/3.11/3.12 매트릭스 추가. 또는 deployment 전 1회 검증 후 결과로 학습 fix.
- **임시 mitigation**: url_validation.py 의 hostname 정규식 더 엄격하게 (숫자만으로 시작하면 ip_address() 통과 못 한 모든 form 거부).

### 4e. smtp_disconnect_uncertain runbook
- **분류**: P2
- **Release blocker?** ❌ **NO**
- **이유**: 에러 발생 빈도 매우 낮음. 발생 시 운영자 reaction 명확화 필요지만 시스템 동작은 정상 (non-retriable + 명시적 코드).
- **권장**: `docs/runbooks/smtp-disconnect-uncertain.md` 신설. release-gate 영역.

### 종합 release blocker 판정

| 항목 | 분류 | Single-tenant SHIP | Multi-tenant SHIP | PyPI public 다수 사용자 |
|------|------|------------------|-------------------|------------------------|
| 4a. SMTP sync sleep | P1 | ✅ OK | 🟡 monitor | 🔴 Phase A 처리 후 |
| 4b. V1 deprecation | P1 | ✅ OK (doc) | ✅ OK (doc) | ✅ OK (doc) |
| 4c. In-memory state | P2 | ✅ OK | 🟡 doc + monitor | 🔴 Redis 필요 |
| 4d. Linux exotic IP | P1 | ⚠️ verify | ⚠️ verify | 🔴 verify + 수정 |
| 4e. runbook | P2 | ✅ OK (doc) | ✅ OK (doc) | ✅ OK (doc) |

**현재 컨텍스트 (단일 사용자/단일 워커 가정): 모두 SHIP eligible**. 단 4d 는 Linux 1회 검증 권장.

---

## 5. tests/test_p1_fixes.py 충분성

| 클래스 | tests | 충분도 | 누락 |
|--------|-------|--------|------|
| TestP1A_FetchTimeSSRFRevalidation | 5 (1 skip) | 🟡 | **per-retry re-validate (NEW-V-1)**, validator 재실행 latency |
| TestP1B_Idempotency | 8 | 🟡 | **동시 요청 race (NEW-V-3)**, **다른 body 같은 키 (NEW-V-2)**, dry_run + idempotency 상호작용 |
| TestP1C_WebhookReplayDefense | 5 | ✅ | (receiver-side validation 은 외부 영역) |

총 18 P1 regression tests. P1 contract 기본 검증 OK. 권장 추가 (NEW-V-1/2/3 처리 시 동시 추가):

1. `test_ssrf_revalidate_between_retries`: 첫 attempt 503 → mock resolver 가 2nd call 시 private IP → 2nd attempt 차단 확인
2. `test_idempotency_different_body_same_key`: 같은 key, 다른 body → 422 (이상적) 또는 적어도 잘못된 응답 캐시 안 함
3. `test_idempotency_concurrent_requests`: ThreadPoolExecutor 로 10 동시 호출 → sender.call_count == 1 (race 차단)

---

## Active Learnings Applied

직전 priors 적용 결과:
- **L-SEED-01** (테스트 통과 ≠ 안전): **재입증** — 172 pass 상태에서 NEW-V-1/2/3 3건 발견. learning 영구 유효성 재확인.
- **L-SEED-02** (BG + sync sleep): SMTP sender retry sync sleep 잔여 확인. status: active 유지.
- **code-L09** (validator + fixture 회귀): 본 verify 에서 추가 회귀 없음. resolved 유효.
- **code-L10** (SMTP phase): 본 verify 와 무관. resolved 유효.
- **code-L11** (underscore Depends): 3 라우트가 이번 P1 fix 로 5 underscore (creds, _, __ × 3 라우트) 다다름. 임계치 (3+) 초과 — **code-L14 (AppDependencies 권장)** 와 연관 watchlist 강화.
- **code-L12** (DNS rebinding parse-time): resolved 유효, 단 NEW-V-1 (retry 간 갭) 신규 노출.
- **code-L13** (exotic IP encoding): **여전히 미검증**. Linux 실측 release-gate 전 필수.
- **code-L14** (factory bloat 5+ kwargs): create_app 가 idempotency_cache 추가로 6 kwargs 도달 — **임계치 초과**. 다음 cross-cutting (예: audit log) 추가 전 dataclass 리팩토링 검토.
- **code-L15** (validator 새 호출 지점): applied 사전 fixture 검토. resolved 유효.
- **code-L16** (V1 deprecation timeline): **여전히 미명시**. release-gate 영역.

## New Learnings Captured

```yaml
ID: code-L17
Source: gate-code-verify-2026-05-18-004
Severity: P1
Mistake / Miss: SSRF 재검증을 retry loop 외부에 1회만 호출. retry 간 DNS rebinding 가능성을 닫지 못함. mitigation 의 의도와 실제 효과 사이 gap.
Root Cause: validate 비용 (DNS lookup) 을 retry 마다 반복하기 싫어서 luminous 위치 (loop 시작 전) 에 둠. 보안 vs 성능 trade-off 의 묵시적 선택.
Recurrence Trigger: TOCTOU 방어를 위한 재검증 패턴 도입 시.
Prevention Rule: 보안 재검증은 loop 안으로 이동 default. 비용이 부담스러우면 (a) validate 결과로 IP 핀, (b) per-retry validate + 캐시 hit (validator 자체 캐시), (c) 명시적으로 "loop 외 1회" 라고 docstring 에 trade-off 기록.
Next-Session Checklist Item: "보안 재검증 코드를 추가하는가? retry/loop 내부에서 호출되는가? trade-off 가 docstring 에 기록됐는가?"
Applies To: email_service/webhooks.py, **/url_validation.py
Owner Gate: code
Evidence: webhooks.py:97 validate before loop, webhooks.py:127+ for-loop without re-validate (이 세션)
Status: active
```

```yaml
ID: code-L18
Source: gate-code-verify-2026-05-18-004
Severity: P1
Mistake / Miss: Idempotency cache key 가 (bearer, key) 만 — body fingerprint 미포함. 같은 key 다른 body → 잘못된 응답 캐시. Stripe Idempotency-Key 표준과 불일치.
Root Cause: 캐시 도입 시 "key 가 unique 하면 그만" 가정. 호출자가 같은 key 로 다른 body 보낼 가능성을 고려 안 함.
Recurrence Trigger: 멱등성 캐시 / dedup 캐시 / rate limit 등 키 기반 상태 도입 시.
Prevention Rule: 외부 입력 키 + 내부 body fingerprint 동시 키화. 또는 body mismatch 시 422 반환 (Stripe 패턴).
Next-Session Checklist Item: "멱등성/캐시 키가 외부 입력만 사용하는가? body/payload fingerprint 가 포함됐거나 mismatch 검증이 있는가?"
Applies To: email_service/api.py (idempotency), 향후 cache layer
Owner Gate: code
Evidence: api.py _idempotency_lookup → cache.get(bearer, key) (이 세션)
Status: active
```

```yaml
ID: code-L19
Source: gate-code-verify-2026-05-18-004
Severity: P1
Mistake / Miss: Idempotency lookup → process → store 비원자적. 같은 key 의 동시 요청 시 둘 다 miss → 둘 다 process (= 중복 발송) → 둘 다 store.
Root Cause: 캐시 패턴 도입 시 single-threaded 가정. FastAPI 가 threadpool 위에서 sync route 를 병렬 실행한다는 사실 망각.
Recurrence Trigger: dedup / idempotency / "한 번만 실행" 보장 캐시 도입 시.
Prevention Rule: lookup-or-set-with-lock 패턴. key 별 lock map 또는 cache 자체에 atomic "get_or_compute" 인터페이스 추가. 또는 store 가 set-if-empty (atomic insert) 로 race 차단.
Next-Session Checklist Item: "캐시의 lookup/store 가 atomic 인가? 같은 키 동시 요청에서 중복 실행 가능한가?"
Applies To: email_service/api.py (_IdempotencyCache + helpers)
Owner Gate: code
Evidence: api.py send_email/send_magic_link/send_otp 의 cached check → process → _idempotency_store 흐름 (이 세션)
Status: active
```

## Recurrence Risks

| ID | 패턴 | 본 verify 결과 | 다음 gate 관찰 포인트 |
|----|------|---------------|---------------------|
| L-SEED-01 | 테스트 통과 ≠ 안전 | **재입증** (NEW-V-1/2/3 발견) | 영구 active |
| L-SEED-02 | BG + sync sleep | active (SMTP sender 측 미해결) | Phase A 도입 시 resolved 가능 |
| code-L11 | underscore Depends | **재발 (3 라우트 × ~2 each)** | code-L14 와 묶어서 처리 |
| code-L12 | DNS rebinding | resolved (parse-time) | NEW-V-1 (retry-time) 등장으로 부분 재발 |
| code-L13 | exotic IP | active | Linux 검증 결과로 resolution |
| code-L14 | factory bloat | **재발** (6 kwargs 도달) | 다음 cross-cutting 추가 전 처리 |
| code-L16 | V1 deprecation | active | release-gate 에서 |
| **code-L17 (NEW)** | retry loop 외 보안 재검증 | new | retry/loop 와 validator 조합 시 |
| **code-L18 (NEW)** | 캐시 키 body fingerprint | new | 캐시/dedup 도입 시 |
| **code-L19 (NEW)** | lookup→process→store race | new | 비원자적 캐시 도입 시 |

## Next Gate Prompt Addendum

> 다음 `/hwan-refactor-code` 또는 `/hwan-refactor-git` 시 prompt 에 붙일 텍스트:
>
> ```
> Active priors from gate-code-verify-2026-05-18-004:
>
> P0: All 5 (May-16) confirmed STABLE. 172/174 tests pass.
>
> NEW P1 (this verify pass, not yet fixed):
> - code-L17 SSRF re-validate is OUTSIDE retry loop — DNS rebinding still
>   possible across retries. Move validate inside the for-loop, or pin
>   resolved IP into httpx transport.
> - code-L18 Idempotency cache key lacks body fingerprint. Same key +
>   different body returns cached response. Add body hash to key, or
>   reject body mismatch with 422.
> - code-L19 Idempotency lookup→process→store is non-atomic. Concurrent
>   same-key requests can each miss, process, and double-send. Add
>   per-key lock or atomic set-if-empty.
>
> ACTIVE (carried forward):
> - L-SEED-02 SMTP sender sync sleep — Phase A (retry budget cap) is
>   surgical, recommend next small fix pass. Phase B/C async path is
>   v0.4.0 pre-work.
> - code-L13 Exotic IP encoding — UNVERIFIED on Linux. Must run before
>   first Linux deployment.
> - code-L14 create_app at 6 kwargs — refactor to AppDependencies before
>   adding a 7th cross-cutting concern.
> - code-L16 V1 webhook signature deprecation timeline missing — release
>   gate task (README/CHANGELOG).
>
> Pre-implementation checklist:
> 1. Adding security re-validation? Check inside retry loops, document
>    trade-off if outside (code-L17).
> 2. Adding cache/dedup? Include body fingerprint in key, atomic
>    lookup-or-set (code-L18, L19).
> 3. Adding 7th create_app kwarg? AppDependencies dataclass first
>    (code-L14).
> 4. Pre-deployment to Linux? Verify exotic IP literal handling
>    (code-L13).
>
> Deployment context judgment:
> - Single-tenant + single-worker + low traffic: SHIP eligible TODAY.
> - Multi-tenant or high-throughput: handle code-L17 + L18 + L19 +
>   L-SEED-02 Phase A first.
> - PyPI public + many integrators: above + Redis-backed state +
>   Phase B/C async.
> ```

## Closeout Checklist (per docs/process/gate-closeout-checklist.md)

- [x] A. SUMMARY.md 4 섹션 (Active / New / Recurrence / Next Addendum) — 본 문서
- [x] B. learnings.md 11-필드 schema — code-L17/L18/L19 schema 완비
- [x] C. index.md 한 줄 추가 예정
- [x] D. Subagent 사용 정당성 명시
- [x] E. 코드 수정 0건 (verify-only 준수)
- [x] F. Hand-off — Next Gate Prompt Addendum 으로 다음 입력 완성
- [x] G. tree clean, branch ≠ master, no destructive commands
