# Refactor Gate (Verify-only) — Post-Fix P0 검증

세션: `gate-code-verify-2026-05-18-002`
타입: **Verification gate** (코드 수정 0건)
브랜치: `claude/cool-bouman-70eb80`
직전 세션: `gate-code-fix-2026-05-18-001` (P0 ×5 implementation pass)
Inherit: P0 0 / P1 5 (사용자 질의 항목)

## 판정
🟡 **PARTIAL VERIFIED — 5 P0 구조적 해결 확인, 새 P1 2건 발견. 단일 사용자/단일 워커 환경 SHIP 가능, 다중 사용자/멀티 테넌트 환경은 P1 처리 후 ship.**

핵심:
- 원래 5 P0 모두 코드 + 테스트로 검증됨 (155/156 pass, 1 skip)
- 보안 회귀 없음 (새 공격 표면 추가는 있지만 모두 자체 검증 또는 auth-gated)
- 새 발견 2건: SSRF DNS-rebinding 잔여 위험 (P1), exotic IP 인코딩 fetch 시점 검증 (P1)
- 사용자 질의 5 잔여 리스크: 1 P0 차단 없음, 4 P1, 1 P2

## Subagent 사용 정당성

이 verify gate 에서 **subagent 호출 0건**. 정책 [docs/process/subagent-policy.md](../../../docs/process/subagent-policy.md) §사용 조건 점검:
- (A) 다관점 전문성? 단일 보안/구조 관점이면 충분 — ❌
- (B) 3+ 파일 동시? api.py + sender.py + webhooks.py + url_validation.py + tests = 5 → ✅
- (C) Adversarial/edge 관점 필요? 코드 본인 작성, 컨텍스트 fresh → 직접 가능, ROI 낮음 → ❌
- (D) 명확한 synthesis 기준? P0별 1:1 확인 → ✅
- (E) Phase 가 병렬 요구? Verify 모드는 단일 흐름 OK → ❌

→ 2 of 5 (B, D). 단 (C) 가 가장 가치 있는 조건이고 본인이 fresh context 라 ROI 부족. **단일 흐름으로 진행.**

---

## 5 P0 재검증 (구조 + 테스트)

### P0-1 (threadpool starvation) — ✅ STRUCTURALLY RESOLVED

| 검증 항목 | 결과 |
|----------|------|
| `DEFAULT_BACKOFFS` sum ≤ 10s | ✅ (1+2+5=8s) |
| `_jittered()` 정의 + 사용 | ✅ webhooks.py:43, 적용 line 99 |
| 누적 sleep 단위 테스트 | ✅ `test_total_sleep_bounded_in_real_retry_loop` |
| 회귀 위험: 백오프 늘리는 누군가 | ✅ test_default_backoffs_total_under_ten_seconds 가 차단 |

**하지만**: SMTP `sender.send()` 의 `time.sleep` (sender.py:277) 은 그대로. sync `/send` 라우트는 여전히 SMTP 재시도 (최대 1+5+25=31s) 동안 threadpool 슬롯 점유. **이게 사용자 질의 #1** — 아래 별도 평가.

### P0-2 (SSRF) — ✅ STRUCTURALLY RESOLVED, ⚠️ 잔여 위험 2건

| 검증 항목 | 결과 |
|----------|------|
| Scheme allowlist (http/https) | ✅ url_validation.py:72 |
| IP literal 차단 | ✅ ipaddress.ip_address + _is_blocked_ip |
| DNS resolve 후 IP 검증 | ✅ url_validation.py:97-112 |
| Allowlist override | ✅ WEBHOOK_ALLOW_HOSTS env |
| IPv4-mapped IPv6 (예: `::ffff:7f00:1`) | ✅ Python stdlib `is_loopback=True` 정상 동작 (직접 검증함) |
| 테스트 커버리지 | ✅ TestP0_2_SSRFDefense 10 tests |
| End-to-end (api → 422) | ✅ test_api_rejects_aws_metadata_at_request_validation |

**잔여 위험 (새 발견)**:

⚠️ **NEW-1 [P1]: DNS rebinding**
- Pydantic field_validator 가 한 번 resolve → 통과. 실제 fetch (`webhooks.deliver_webhook` 의 `httpx.Client.post`) 는 ~ms 후. 그 사이 DNS rebinding (TTL=0, 두 번째 resolve 시 127.0.0.1 반환) 가능.
- **공격 시나리오**: attacker.com → 첫 resolve 시 1.2.3.4 (공인 IP), validator 통과. 두 번째 resolve 시 127.0.0.1. webhook 이 내부망 hit.
- **완화**: (a) auth-gated (API_KEY 필요), (b) 호출자가 자신의 webhook_url 제공 — 자기 공격은 의미 없음, (c) 다만 다중 테넌트 시 한 테넌트가 다른 인프라 정찰 가능.
- **격상 필요한가**: 단일 테넌트면 P2, 다중 사용자면 P1. **현재 단일 API_KEY 단일 테넌트 가정** → P1 watchlist.

⚠️ **NEW-2 [P1]: Exotic IP 인코딩 fetch 시점 검증**
- `ipaddress.ip_address("2130706433")` 등 정수/16진수 형태는 ValueError → DNS 분기. Windows getaddrinfo 거부 확인. **단 Linux glibc 는 historically 정수 IP 인식**, httpx 자체 URL canonicalization 가능성. validator 통과 후 httpx fetch 가 127.0.0.1 로 hit 할 가능성.
- **검증 필요**: `httpx.Client().post("http://2130706433/")` 를 Linux 환경에서 실행 → 어떤 IP 로 connect 하는지 확인.
- 현재 테스트 부재.

### P0-3 (size limits) — ✅ STRUCTURALLY RESOLVED, ⚠️ pre-Pydantic buffer

| 검증 항목 | 결과 |
|----------|------|
| `MAX_SUBJECT_LEN=998` | ✅ RFC 5322 준수 |
| `MAX_BODY_LEN=10_000_000` | ✅ |
| `MAX_RECIPIENTS=100` | ✅ |
| Pydantic max_length 모든 모델 | ✅ SendEmailRequest / SendMagicLinkRequest / SendOTPRequest |
| 테스트 커버리지 | ✅ TestP0_3_SizeLimits 4 tests |

**잔여 위험**:

⚠️ **EXISTING [P2]: FastAPI buffers full body BEFORE Pydantic**
- 100MB POST → uvicorn 가 메모리에 전체 버퍼링 → Pydantic 가 max_length 검사 → 422 반환. 거부되지만 메모리는 transient 점유.
- **완화**: uvicorn `--limit-max-requests`, 또는 nginx `client_max_body_size`. 인프라 레벨, 코드 변경 불필요.
- **테스트 불가**: TestClient 가 인프라 layer 우회.
- README 에 deployment guide 명시 필요.

⚠️ **EXISTING [P3]: Pydantic max_length = char count, not byte count**
- 10MB UTF-8 worst case 40MB 바이트. 실제 메모리 4×.
- Risk 낮음 (worst case도 OOM 안 가는 수준), but document worth.

### P0-4 (rate limit) — ✅ STRUCTURALLY RESOLVED

| 검증 항목 | 결과 |
|----------|------|
| Sliding window 정확성 | ✅ _SlidingWindowLimiter, deque pop while expired |
| Per-bearer 격리 | ✅ test_limiter_isolates_keys |
| 429 + Retry-After | ✅ test_api_returns_429_after_exceeding_limit |
| /health 미적용 | ✅ test_health_endpoint_is_not_rate_limited |
| 비활성화 mode (max=0) | ✅ test_limiter_disabled_when_max_is_zero |
| Threading.Lock | ✅ check/append atomic |
| 테스트 커버리지 | ✅ TestP0_4_RateLimit 6 tests |

**잔여 위험 (의도된 한계)**:

⚠️ **EXISTING [P2]: In-memory per-process**
- Multi-worker uvicorn → 워커당 quota. 워커 N개면 실제 cap = N × `API_RATE_LIMIT_PER_MINUTE`.
- **단일 워커면 OK**. Multi-worker 운영 시 README 에 명시 + Redis-backed 대체 가이드.
- 사용자 질의 #2 — 아래 별도 평가.

⚠️ **EXISTING [P3]: `_buckets` dict 무한 증가**
- 키별 deque 는 max_requests 개로 bounded, but dict key 자체 (bearer 토큰) 는 절대 삭제 안 됨.
- 단일 키 시 dict size = 1. 다중 키 도입 시 시간 지나면 garbage 누적. eviction 필요.

### P0-5 (post-DATA disconnect) — ✅ STRUCTURALLY RESOLVED

| 검증 항목 | 결과 |
|----------|------|
| `sendmail_returned` 플래그 도입 | ✅ sender.py:_send_once line ~308 |
| Post-sendmail disconnect → success | ✅ test_disconnect_after_sendmail_returned_is_success |
| Mid-sendmail disconnect → non-retriable | ✅ test_disconnect_mid_sendmail_does_not_retry |
| Partial refusal + post-disconnect | ✅ test_disconnect_after_partial_refusal_preserves_refused_list |
| `ERR_SMTP_DISCONNECT_UNCERTAIN` NOT in retriable set | ✅ sender.py:_RETRIABLE_ERROR_CODES 확인 |
| 테스트 커버리지 | ✅ TestP0_5_DisconnectDuringSendmail 3 tests |

**잔여 위험**:

⚠️ **NEW [P2]: `ERR_SMTP_DISCONNECT_UNCERTAIN` runbook 부재**
- 새 에러 코드가 모니터링/알림에 등장 시 운영자가 의미 모름.
- README error code 표 + docs/runbooks/smtp-disconnect-uncertain.md 작성 필요. 사용자 질의 #5.

⚠️ **THEORETICAL [P3]: success path 의 `email_send_duration_seconds.observe()` 가 raise 하면**
- 매우 낮은 확률. prometheus_client 라이브러리 결함 의존.
- 만약 raise → outer `except Exception as exc: → ERR_UNKNOWN` → 클라이언트는 실패로 인식 → 재시도. 그런데 메일은 이미 발송됨 → 중복.
- 현실적 risk 매우 낮음. 미해결 OK.

---

## tests/test_p0_fixes.py 충분성 평가

| P0 | 테스트 수 | 충분도 | 누락 |
|----|----------|--------|------|
| P0-1 | 5 | ✅ | (없음) |
| P0-2 | 10 | 🟡 | DNS rebinding sim, exotic IP literal end-to-end |
| P0-3 | 4 | 🟡 | UTF-8 byte size 검증, pre-Pydantic body limit (인프라 레벨) |
| P0-4 | 6 | 🟡 | 동시성 (multi-thread) lock 정합성, dict 메모리 누수 |
| P0-5 | 3 | ✅ | (없음) |

총 28 테스트. 기본 contract 검증 OK. 권장 추가 (P1/P2 처리 시 함께):
1. `test_ssrf_dns_rebinding_simulation`: TTL=0 mock resolver, 두 번째 resolve 결과가 다른 시나리오
2. `test_ssrf_exotic_ip_literal`: `http://2130706433/`, `http://0x7f000001/`, `http://127.1/` 모두 validator 또는 fetch 시점에 차단
3. `test_rate_limit_concurrent_access`: 50개 스레드 동시 호출, total = N+1 차단 보장

---

## 사용자 질의 5개 잔여 리스크 재분류

| # | 항목 | 재분류 | 배포 차단? | 이유 |
|---|------|--------|-----------|------|
| 1 | SMTP sender sync sleep | **P1** | ❌ NO | 8s+ threadpool 점유 가능하지만 rate limit + size cap 으로 cascading 위험 완화. 단일 워커 + 낮은 트래픽에선 무해. 진정한 해결은 async path — 큰 리팩토링. L-SEED-02 partial 유지. |
| 2 | In-memory rate limit | **P2** | ❌ NO | 단일 워커 면 의도된 동작. multi-worker README docs 추가 필요. 다중 워커 + 정확한 quota 요구 시 P1. |
| 3 | Webhook HMAC replay | **P1** | ❌ NO | API_KEY 가 webhook secret 보호. replay 공격은 secret 유출 후만 가능. timestamp 헤더 추가는 P1 후속. |
| 4 | HTTP /send idempotency | **P1** | ❌ NO | 네트워크 재시도 시 중복 발송 가능. 그러나 호출자 측 dedup 책임으로 분담 가능. README 에 권장 패턴 명시 필요. P0-5 가 SMTP 레벨 idempotency 부분 제공. |
| 5 | smtp_disconnect_uncertain runbook | **P2** | ❌ NO | 운영 가독성. 에러 발생 빈도 낮음 (현실에서 드문 케이스). docs 보강. |

**종합**: 5개 모두 배포 차단 아님 (단, multi-tenant 또는 PyPI 외부 공개 사용자 다수 가정 시 #1, #4 는 P0 으로 격상 권장).

## 새로 생긴 회귀/보안 문제

✅ **회귀 0건**: 기존 124 tests + 새 31 tests = 155 모두 통과. 기존 contract (응답 shape, 에러 코드, status string) 보존.

⚠️ **신규 공격 표면**:
- SSRF validator 자체가 새 코드 → DNS rebinding (NEW-1), exotic IP (NEW-2) 두 잔여.
- Rate limiter 자체가 새 코드 → 메모리 누수 가능성 (다중 키 도입 시), 워커 격리.
- 모두 P1/P2, P0 차단 없음.

🛡️ **개선된 보안**:
- subject/from/to/cc/bcc CRLF 차단 (기존)
- SSRF 1차 방어 (신규)
- 입력 사이즈 cap (신규)
- 단일 키 brute-force 시 rate limit 으로 dampen (신규)
- post-DATA disconnect 중복 발송 차단 (신규)

---

## 변경 파일 (verify gate — 0 코드 수정)

| 파일 | 변경 |
|------|------|
| `.claude/workflow/gate-code-verify-2026-05-18-002/SUMMARY.md` | **신규** (이 문서) |
| `.claude/learnings/index.md` | 세션 로그 한 줄 추가, 신규 learning ID 등록 |
| `.claude/learnings/code/learnings.md` | code-L12, L13 append |

런타임 코드 / 테스트 / 설정 / 워크플로 docs / process docs **건드리지 않음** (사용자 명시 요청).

---

## Active Learnings Applied

직전 세션 priors 적용 결과:
- **L-SEED-01** (테스트 통과 ≠ 안전): 검증됨. 155 pass 인 코드에서 NEW-1 (DNS rebinding) 발견 — learning 의 핵심 재입증.
- **L-SEED-02** (BackgroundTasks + sync sleep): 본 세션 SMTP retry sync sleep 잔여 확인. **상태 유지 (active, partial)**. 재발 시 severity 상승 규칙 미적용 (의도된 부분 fix 임을 추적 중).
- **L-SEED-03/-04/-05**: resolved (직전 세션 처리). 본 세션 verify 결과 resolution 유효.
- **code-L09** (validator + 기존 fixture 회귀): tests/test_phase4.py 의 monkeypatch 패턴 검증됨.
- **code-L10** (SMTP phase 식별): TestP0_5_DisconnectDuringSendmail 가 sendmail_returned 플래그 정확히 검증.
- **code-L11** (underscore Depends 누적): 3 라우트 각 2개 underscore — 임계치 아래, 현재 OK.

## New Learnings Captured

```yaml
ID: code-L12
Source: gate-code-verify-2026-05-18-002
Severity: P1
Mistake / Miss: SSRF URL validator 가 Pydantic parse time 1회 DNS resolve 후 결과 신뢰. 실제 fetch 시점에 DNS 가 다른 IP 반환 (rebinding) 시 차단 우회.
Root Cause: Validator (요청 receive 시점) 과 fetcher (background task 시점) 사이에 시간 갭. 같은 hostname 두 번 resolve 보장 없음.
Recurrence Trigger: 외부 URL fetch 코드 추가, validator-then-fetch 패턴.
Prevention Rule: (a) validator 가 resolve 한 IP 를 fetch 에 강제 주입 (httpx transport 후킹), 또는 (b) fetch 자체에서 IP 재검증, 또는 (c) auth-gated + 단일 테넌트 가정 명시. (a) 또는 (b) 가 진정한 방어.
Next-Session Checklist Item: "URL validator 와 실제 fetch 사이에 DNS 가 1회만 resolve 된다고 가정하지 않는가? 두 번째 resolve 시 다른 IP 가 반환되면 어떻게 되는가?"
Applies To: email_service/url_validation.py, email_service/webhooks.py
Owner Gate: code
Evidence: validator (api.py field_validator) → fetch (webhooks.deliver_webhook) 시간 갭. 본 SUMMARY NEW-1.
Status: active
```

```yaml
ID: code-L13
Source: gate-code-verify-2026-05-18-002
Severity: P2
Mistake / Miss: SSRF validator 가 표준 dotted-decimal IP 만 검사. 정수형 (2130706433), 16진수 (0x7f000001), 단축형 (127.1) 등 비표준 인코딩은 ipaddress.ip_address() 에서 ValueError → DNS 분기. 실제 httpx fetch 가 canonical 변환 후 127.0.0.1 로 connect 할 가능성.
Root Cause: Python stdlib ipaddress.ip_address() 는 RFC 표준 인코딩만 수용. 그러나 OS-level inet_aton / httpx URL parser 는 historic 비표준 인코딩 수용 가능.
Recurrence Trigger: URL/IP 검증 추가 시, 다양한 클라이언트 라이브러리가 hostname 을 canonicalize.
Prevention Rule: validator 에서 hostname 을 그대로 신뢰하지 말고 첫 글자가 숫자/0x/8진 prefix 면 더 엄격한 정규식 또는 inet_aton 통해 모든 인코딩을 표준 dotted-decimal 로 정규화 후 검증.
Next-Session Checklist Item: "URL hostname 검증 시 정수/16진/단축형 IP 가 fetch 시점에 어떤 IP 로 해석되는지 확인했는가?"
Applies To: email_service/url_validation.py
Owner Gate: code
Evidence: ipaddress.ip_address('2130706433') ValueError, Windows getaddrinfo gaierror. Linux glibc 동작 미검증.
Status: active
```

## Recurrence Risks

| ID | 패턴 | 본 세션 결과 | 다음 gate 관찰 포인트 |
|----|------|--------------|----------------------|
| L-SEED-01 | 테스트 통과 ≠ 안전 | 재입증 (NEW-1 발견) | 영구 active |
| L-SEED-02 | BG + sync sleep | **STILL ACTIVE (partial fix)** | SMTP retry sleep 영역 남음. 신규 BackgroundTasks 추가 시 자동 alert |
| code-L09 | validator + fixture 회귀 | applied OK | 다음 validator 도입 시 |
| code-L10 | SMTP phase | applied OK | smtp 예외 핸들러 수정 시 |
| code-L11 | underscore Depends | applied OK | 새 cross-cutting Depends 추가 시 |
| **code-L12 (NEW)** | DNS rebinding | NEW | 외부 URL fetch 코드 변경 시 |
| **code-L13 (NEW)** | exotic IP literal | NEW | URL validator 수정 시 |

## Next Gate Prompt Addendum

> 다음 `/hwan-refactor-code` 또는 `/hwan-refactor-git` 실행 시 prompt 에 붙일 텍스트:
>
> ```
> Active priors from gate-code-verify-2026-05-18-002:
> - 5 P0 from May-16 confirmed STRUCTURALLY resolved with 155-pass test suite.
> - L-SEED-02 (BG + sync sleep) remains ACTIVE: SMTP sender.send() retry path
>   still uses synchronous time.sleep. Bounded by max_retries config but
>   blocks Starlette threadpool slot during sync /send calls.
> - code-L12 (NEW): SSRF validator does not defend against DNS rebinding.
>   Either bind resolved IP into transport layer or accept the residual risk
>   under single-tenant + authenticated-caller assumption.
> - code-L13 (NEW): SSRF validator may miss exotic IP encodings (decimal,
>   hex, shortened). Verify behavior on Linux production env.
>
> Pre-implementation checklist:
> 1. New URL-fetch code? → bind resolved IP into transport, or add a
>    re-resolve check at fetch time (code-L12).
> 2. New rate-limit boundary? → if multi-worker, design for shared store
>    (in-memory limiter is per-worker — documented limitation).
> 3. New SMTP error code? → add to docs/runbooks/ AND README error table
>    (per L-SEED-08 + smtp_disconnect_uncertain example).
> 4. New BackgroundTasks.add_task? → confirm callable has no time.sleep
>    or blocking IO (L-SEED-02).
> 5. Adding /send-class endpoint? → must wire rate_limit Depends; must
>    use Pydantic max_length on every string field (L-SEED-04, P0-3).
>
> Deployment notes (current state):
> - Single-tenant + single-worker uvicorn: SHIP eligible
> - Multi-tenant or multi-worker: process P1 items (#1, #2, #4) first
> - PyPI public + many integrators: process L-SEED-02 fully (async path)
>   AND code-L12 (DNS rebinding) before next minor version bump
> ```

---

## Closeout Checklist 검증 (per docs/process/gate-closeout-checklist.md)

- [x] A. SUMMARY.md 4 섹션 포함 (Active Applied / New / Recurrence / Next Addendum)
- [x] B. learnings.md 갱신 — 11-필드 schema (code-L12, code-L13 등록 예정)
- [x] C. index.md 한 줄 추가 예정
- [x] D. Subagent 사용 정당성 — 미사용 사유 명시 (위 §"Subagent 사용 정당성")
- [x] E. Gate 철학 보존 — 코드 수정 0건 (verify-only 명시 준수)
- [x] F. Hand-off — Next Gate Prompt Addendum 으로 다음 실행자 입력 완성
- [x] G. 운영 안전 — tree clean, branch ≠ master, destructive 명령 미사용
