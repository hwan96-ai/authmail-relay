# Code Gate — Compound Learnings

> **2026-05-18 — Schema migration**: 이 파일의 항목들은 [docs/process/compound-learning-loop.md §4.2](../../../docs/process/compound-learning-loop.md) 의 11-필드 schema 로 정규화되어 [`.claude/learnings/index.md`](../index.md) 의 Seed Learnings (L-SEED-01 ~ 08) 에 통합되었다.
>
> 이 파일의 free-form 항목 (L1~L8) 은 historical 기록으로 보존. 다음 code gate 시작 시 priors 는 [index.md](../index.md) 의 `Owner Gate: code` 인 항목 (L-SEED-01, -02, -03, -04, -05) 에서 읽는다.
>
> 신규 learning 은 반드시 11-필드 schema 로 이 파일 하단에 append.

## 2026-05-18 — gate-code-verify-2026-05-18-008 (verify-only, 평탄화 확정)

**0 신규 secondary 결함 발견.** code-L24 (fix→verify 사이클의 평탄화) 예측 적중 — 4번째 verify pass 에서 처음 0-finding 달성. 5 P0 + 4 P1 tier 모두 STABLE. Release Gate 진입 가능.

2 신규 learning (모두 P2/P3, 의미 기록 차원):
- **code-L26** [P3]: 평탄화 시그널 — fix pass 가 (a) 새 추상화 X, (b) line 단순 제거/추가, (c) 회귀 테스트 ≥4 동시 충족 시 다음 verify 0 finding 예상.
- **code-L27** [P2]: 락 순서 invariant (per-key lock → meta_lock) 가 implicit. 새 lock 도입 시 ordering 깨질 위험. docstring 명시 필요.

Priors 변경:
- **code-L24 (meta — 평탄화 예측)**: status **VALIDATED**. 본 verify 가 예측 정확성 입증.
- **L-SEED-01**: 5회차 invocation (0 finding) — learning 영구 유효성 유지, 평탄화 후에도 회귀 테스트 의무.

다음 단계: `/hwan-refactor-git` (Release Gate) 권장. docs P2 + Linux 1회 실측 + (선택) Phase A small fix pass.

## 2026-05-18 — gate-code-fix-2026-05-18-007 (NEW-V-4 surgical fix)

1 신규 learning + 1 prior RESOLVED. 전체 11-필드 schema 는 `../../workflow/gate-code-fix-2026-05-18-007/SUMMARY.md` "New Learnings Captured" 참조.

- **code-L25** [P2]: per-key lock dict 메모리 bound — unique-key cardinality 로만 bound. 적대적 caller 가능 시 idle TTL / LRU 필요. 이번 pass TODO 로만 명시.

Priors 변경:
- **code-L23 (lock-eviction race)**: **RESOLVED-By: gate-code-fix-2026-05-18-007** — `_IdempotencyCache` 의 3 `_key_locks.pop` 호출 제거. cache entry lifecycle 과 lock dict lifecycle 분리. 4 회귀 테스트 (unit 2 + integration 2) 추가.
- code-L24 (meta): 본 pass 가 단순 line 제거 + TODO 추가 (새 추상화 0개) → 신규 secondary 결함 가능성 매우 낮음. **평탄화 cycle 시작**. 다음 verify 에서 0 finding 이면 평탄화 확정.

P0 5건 + P1 1차/secondary/tertiary 모두 RESOLVED 또는 STABLE.

## 2026-05-18 — gate-code-verify-2026-05-18-006 (verify-only, post secondary P1 fix)

2 신규 learning. 전체 11-필드 schema 는 `../../workflow/gate-code-verify-2026-05-18-006/SUMMARY.md` "New Learnings Captured" 참조.

- **code-L23** [P1]: Per-key lock + TTL cache 의 lifecycle 결합. expired entry pop 시 lock 도 pop → in-flight holder 가 hold 한 채 dict 에서 사라짐 → 후속 caller 가 새 lock 생성 → 동시 처리 가능. **NEW-V-4 race**. surgical fix: lock pop 제거, 별도 lifecycle.
- **code-L24** [P2, meta]: Fix pass → verify pass 사이클이 평균 1 신규 secondary 결함 produce 한다는 패턴. 새 추상화 (캐시/락/CM) 자체의 edge case 가 다음 verify 의 발견 영역. 1-2 cycle 후 평탄화. — Compound Learning Loop 자체의 효용 + 정당성 재입증.

Priors 상태 변경:
- code-L17/L18/L19: resolved 유효성 확인. **단 code-L19 fix 가 code-L23 spawn** (1-step regression 패턴, code-L24 의 인스턴스).
- L-SEED-01: 4회차 재입증 (영구 active).
- 나머지 priors: 변경 없음 (active deferred).

P0 5건 + P1 1차/secondary: 모두 STABLE.

## 2026-05-18 — gate-code-fix-2026-05-18-005 (secondary P1 surgical fix)

3 신규 learning + 3 priors RESOLVED. 전체 11-필드 schema 는 `../../workflow/gate-code-fix-2026-05-18-005/SUMMARY.md` 의 "New Learnings Captured" 참조.

- **code-L20** [P2]: 캐시 시그니처 변경 시 단위 테스트 fixture 회귀 — keyword-only argument 권장.
- **code-L21** [P2]: 실패-미캐싱 정책의 트래픽 증폭 가능성 (rate limit 으로 차단되나 monitoring alert 필요).
- **code-L22** [P1]: per-key lock dict 메모리 — cache eviction 과 동기화로 자연 회수, max_entries 만큼 bounded.

Priors RESOLVED:
- **code-L17 (SSRF retry-loop 외부 재검증)**: validate_webhook_url 가 for-loop 내부로 이동. Resolved-By: gate-code-fix-2026-05-18-005.
- **code-L18 (캐시 body fingerprint 부재)**: SHA-256 canonical JSON fingerprint + 409 conflict. Resolved-By: gate-code-fix-2026-05-18-005.
- **code-L19 (lookup→process→store race)**: per-key threading.Lock + `_idempotency_guard` contextmanager. Resolved-By: gate-code-fix-2026-05-18-005.

Priors STILL ACTIVE (사용자 명시 미해결):
- L-SEED-02 (SMTP sync sleep): partial 유지 — Phase A 다음 pass.
- code-L11 / code-L14 (underscore Depends + create_app bloat): 6 kwargs 도달. AppDependencies refactor 다음 pass.

## 2026-05-18 — gate-code-verify-2026-05-18-004 (verify-only, post P1 fix)

3 신규 learning. 전체 11-필드 schema 는 `../../workflow/gate-code-verify-2026-05-18-004/SUMMARY.md` "New Learnings Captured" 참조.

- **code-L17** [P1]: SSRF 재검증이 retry loop 외부에 위치. retry 간 DNS rebinding 가능. 재검증을 loop 내부로 또는 IP pinning.
- **code-L18** [P1]: Idempotency cache key 에 body fingerprint 없음. 같은 key 다른 body → 잘못된 응답. body hash 포함 또는 mismatch 시 422.
- **code-L19** [P1]: Idempotency lookup→process→store 비원자적. 동시 요청 시 중복 발송. atomic set-if-empty 또는 key 별 lock.

Priors 상태 변화:
- L-SEED-01: 재입증 (영구 active)
- L-SEED-02: active 유지 (SMTP sender 측 partial 의도)
- code-L11: **재발** (3 라우트 underscore Depends 누적) — code-L14 와 묶어서 처리 필요
- code-L12: resolved 유효 (단 NEW retry-gap = code-L17 로 분기)
- code-L13: active (Linux 검증 미수행)
- code-L14: **재발** (create_app 6 kwargs 도달, 임계치 초과)
- code-L16: active (release-gate 영역)

P0 5건: 모두 STABLE 확인.
3 P1 fix: 구조적 OK, secondary gap 3건 (code-L17/L18/L19) — 모두 surgical fix 가능.

## 2026-05-18 — gate-code-fix-2026-05-18-003 (P1 surgical fix pass)

3개 신규 learning. 전체 11-필드 schema 는 `../../workflow/gate-code-fix-2026-05-18-003/SUMMARY.md` 의 "New Learnings Captured" 참조.

- **code-L14** [P2]: `create_app` 키워드 인자 5개 도달. 6번째 cross-cutting 추가 시 `AppDependencies` dataclass 로 묶기.
- **code-L15** [P1]: validator 새 호출 지점 추가는 기존 validator 추가와 동일한 fixture 회귀 위험. grep 사전 점검 필요. (code-L09 의 일반화)
- **code-L16** [P2]: V2 보안 헤더 도입 시 V1 deprecation timeline 동시 명시 필요. 호환성 유지가 보안 부채 영구화로 이어지지 않게.

Priors 상태 변경:
- **code-L12 (SSRF DNS rebinding)**: **RESOLVED-By: gate-code-fix-2026-05-18-003** — `deliver_webhook` 시작 시 재검증 추가. TOCTOU 윈도우 ms 단위로 축소. 완전 제거 (IP pinning) 는 후속.
- code-L09 (validator + 기존 fixture): 일반화하여 code-L15 로 진화. code-L09 도 active 유지 (구체적 시나리오 기록).
- L-SEED-02 (BG + sync sleep): active 유지, 의도된 partial fix. SMTP sender retry budget cap 은 다음 small fix pass 권장.

## 2026-05-18 — gate-code-verify-2026-05-18-002 (verify-only)

2개 신규 learning. 전체 11-필드 schema 는 `../../workflow/gate-code-verify-2026-05-18-002/SUMMARY.md` 의 "New Learnings Captured" 참조.

- **code-L12** [P1]: SSRF validator + DNS rebinding — validator 와 fetcher 사이 시간 갭에서 DNS 결과 변경 가능. transport-level IP binding 또는 re-resolve 필요.
- **code-L13** [P2]: SSRF validator 가 exotic IP 인코딩 (정수/16진/단축형) 못 잡음. ipaddress.ip_address() 는 RFC 표준만, getaddrinfo/httpx 는 historic 변형 수용. Linux glibc 확인 필요.

Verify 결과 priors 상태:
- L-SEED-01: ACTIVE (NEW-1 발견으로 재입증)
- L-SEED-02: ACTIVE (partial, 변경 없음)
- L-SEED-03,-04,-05: RESOLVED 유효 확인
- code-L09,-L10,-L11: applied OK, 유지

## 2026-05-18 — gate-code-fix-2026-05-18-001 (P0 fix implementation pass)

다음 3개 신규 learning 등록. 전체 11-필드 schema 는 `../../workflow/gate-code-fix-2026-05-18-001/SUMMARY.md` 의 "New Learnings Captured" 섹션 참조.

- **code-L09** [P1]: SSRF validator 추가 시 기존 test fixture (fake DNS hostname) 회귀 위험 — 환경변수 allowlist override 필수
- **code-L10** [P1]: SMTPServerDisconnected 는 sendmail() phase 에 따라 retriable 여부 다름 — sendmail_returned 플래그 필수
- **code-L11** [P2]: 라우트당 underscore Depends 3+ 누적 시 통합 Depends 함수 고려

직전 priors (L-SEED-01 ~ L-SEED-05) 적용 결과:
- L-SEED-01: ACTIVE (process learning, 영구 유효)
- L-SEED-02: ACTIVE 유지 (webhook 측만 부분 해결, SMTP retry sleep 미해결)
- L-SEED-03: RESOLVED (url_validation.py)
- L-SEED-04: RESOLVED (Pydantic max_length)
- L-SEED-05: RESOLVED (sendmail_returned + ERR_SMTP_DISCONNECT_UNCERTAIN)

## 2026-05-16 — gate-code-2026-05-16-001 (initial audit, no execution) [LEGACY FORMAT]

### L1 — BackgroundTasks + 동기 IO 패턴은 P0
- Category: true_positive
- Pattern: `BackgroundTasks.add_task(sync_func)` where sync_func contains `time.sleep` or blocking IO
- Action: 즉시 threadpool starvation 위험. async path로 통합하거나 자체 ThreadPoolExecutor로 격리
- Evidence: api.py:286, webhooks.py:33-95 (이 세션)
- Confidence: 9/10

### L2 — webhook_url / callback URL은 항상 SSRF 후보
- Category: true_positive
- Pattern: 외부 callback URL을 Pydantic `HttpUrl` 또는 `str`로만 받고 fetch
- Action: scheme allowlist + hostname resolve + private/loopback/link-local 차단
- Evidence: webhooks.py:33-65 (이 세션)
- Confidence: 10/10

### L3 — Pydantic `Field(min_length=1)`는 max_length 없으면 무방비
- Category: true_positive
- Pattern: HTTP body 필드에 `min_length`만 있고 `max_length` 없음
- Action: 모든 string body 필드에 명시적 `max_length` (특히 html_body/text_body는 10MB cap)
- Evidence: api.py:51 (이 세션)
- Confidence: 9/10

### L4 — 사이드카 retry는 클라이언트에 보이는 sleep budget이 됨
- Category: true_positive
- Pattern: sync route에서 `time.sleep` 기반 retry (`SmtpSender.send` style)
- Action: 합계 sleep budget cap (예: ≤10s). 더 길면 background로
- Evidence: sender.py:277, 392-412 (이 세션)
- Confidence: 9/10

### L5 — Python smtplib 예외 repr에 user/host 포함 → 502 body로 흘려보내지 말 것
- Category: project_context
- Pattern: `return JSONResponse(status_code=502, content={"error_message": str(exc)})` for SMTP errors
- Action: SMTP* 예외는 generic message; details는 server-side log only
- Evidence: sender.py:392-412 + api.py:305-352 (이 세션)
- Confidence: 8/10

### L6 — sync vs async client 99% 중복은 한쪽만 패치하는 드리프트 만든다
- Category: true_positive
- Pattern: client.py + async_client.py가 메서드 시그니처/로직이 거의 동일
- Action: 공통 transport 인터페이스 추출 또는 codegen. 둘 중 하나 수정 시 반드시 양쪽 동시
- Evidence: client.py:69-158 ↔ async_client.py:58-143 (이 세션)
- Confidence: 8/10

### L7 — SMTP `sendmail()` 완료 후 발생하는 disconnect는 재시도하면 안 됨
- Category: project_context
- Pattern: `_classify_smtp_error`가 예외 타입만 보고 phase 안 봄
- Action: send phase 추적 (`pre_data`, `post_data`) + post_data 이후는 retry 비활성
- Evidence: sender.py:225-291 (이 세션)
- Confidence: 9/10

### L8 — Prometheus counter는 멀티 워커에서 multiprocess 모드 필수
- Category: true_positive
- Pattern: `prometheus_client.Counter` global 인스턴스 + uvicorn workers > 1
- Action: `PROMETHEUS_MULTIPROC_DIR` 설정 + `MultiProcessCollector` 사용
- Evidence: metrics.py:33 (이 세션)
- Confidence: 8/10

---

## 누적 적용 (다음 세션부터)

위 8개 학습은 다음 Code Gate 실행 시 자동으로 priors로 적용됨. 특히 L1-L4는 이 프로젝트(FastAPI + 외부 호출 시스템)의 반복 위험 패턴.
