# Code Gate — Compound Learnings

> **2026-05-18 — Schema migration**: 이 파일의 항목들은 [docs/process/compound-learning-loop.md §4.2](../../../docs/process/compound-learning-loop.md) 의 11-필드 schema 로 정규화되어 [`.claude/learnings/index.md`](../index.md) 의 Seed Learnings (L-SEED-01 ~ 08) 에 통합되었다.
>
> 이 파일의 free-form 항목 (L1~L8) 은 historical 기록으로 보존. 다음 code gate 시작 시 priors 는 [index.md](../index.md) 의 `Owner Gate: code` 인 항목 (L-SEED-01, -02, -03, -04, -05) 에서 읽는다.
>
> 신규 learning 은 반드시 11-필드 schema 로 이 파일 하단에 append.

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
