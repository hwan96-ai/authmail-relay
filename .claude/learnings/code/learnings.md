# Code Gate — Compound Learnings

## 2026-05-16 — gate-code-2026-05-16-001 (initial audit, no execution)

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
