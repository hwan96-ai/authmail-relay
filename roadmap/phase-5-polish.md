# Phase 5 — Polish & Community

**목표:** 이메일 a11y/i18n, Swagger UI 메타, examples/, async client. 표면 품질로 채택률 가속.

**소요 (CC):** ~2시간 | **위험:** 낮음 (additive) | **외부 의존:** 없음

## 진입 조건

- Phase 1 완료 (다른 단계와 병렬 가능)
- 별도 worktree 권장 — 충돌 위험 낮음

## 작업

### P0 — 이메일 템플릿 a11y/responsive (디자인 리뷰 P0 7건 중 핵심)

- [ ] **5.1 WCAG AA 색상 대비 수정**
  - 파일: [email_service/notifiers.py:22](../email_service/notifiers.py)
  - 변경: `color:#888` (3.54:1, fail) → `color:#595959` (7.04:1, AAA). CTA `#1a73e8` on white 는 OK (4.78:1).
  - 출처: [reports/09-design-review.md](../reports/09-design-review.md) Surface A P0

- [ ] **5.2 viewport meta + lang 속성**
  - 파일: [email_service/notifiers.py](../email_service/notifiers.py)
  - 변경: 각 템플릿에 `<html lang="ko">` (locale 도입 전), `<head><meta name="viewport" content="width=device-width, initial-scale=1"></head>` 추가
  - 출처: [reports/09-design-review.md](../reports/09-design-review.md) Surface A P0

- [ ] **5.3 600px 컨테이너 + 모바일 반응형**
  - 파일: [email_service/notifiers.py](../email_service/notifiers.py)
  - 변경: `<body>` 내부에 `<table role="presentation" style="max-width:600px;margin:0 auto;">` 래퍼 (Outlook 호환). `@media (max-width:600px)` 미디어쿼리.
  - 출처: [reports/09-design-review.md](../reports/09-design-review.md) Surface A P0

### P0 — Swagger UI 메타 (Surface B)

- [ ] **5.4 모든 라우트에 summary/description/tags/responses**
  - 파일: [email_service/api.py:138,142,166,188](../email_service/api.py)
  - 변경: `@app.post("/send", summary="Send a single HTML email", tags=["Email"], description="...", responses={401: {"model": ErrorResponse, "description": "Invalid or missing API key"}, 502: {"model": ErrorResponse, ...}})`
  - FastAPI 앱 자체 메타: `FastAPI(title="email-service", version=__version__, description="...", contact={...})`
  - 출처: [reports/09-design-review.md](../reports/09-design-review.md) Surface B P0
  - 테스트: `/openapi.json` 파싱 후 모든 operation 에 `summary` 키 존재 검증

### P1 — i18n + Dark Mode

- [ ] **5.5 템플릿 i18n hook**
  - 파일: [email_service/notifiers.py](../email_service/notifiers.py)
  - 변경: `MagicLinkNotifier(...)` 에 `subject: str | None = None`, `body_template: str | None = None` 파라미터 추가. None 이면 현재 한국어 기본값. caller 가 자기 locale 로 override 가능.
  - 출처: [reports/09-design-review.md](../reports/09-design-review.md) Surface A P1

- [ ] **5.6 dark mode 지원**
  - 파일: [email_service/notifiers.py](../email_service/notifiers.py)
  - 변경: `@media (prefers-color-scheme: dark) { body { background: #1a1a1a; color: #f0f0f0 } }` 추가. CTA 색상은 다크에서 살짝 밝게 조정.
  - 주의: Outlook 데스크탑은 prefers-color-scheme 미지원 → fallback 흰 배경 유지

- [ ] **5.7 plain-text 대체본 자동 생성**
  - 파일: [email_service/notifiers.py](../email_service/notifiers.py)
  - 변경: MagicLinkNotifier / OTPNotifier 가 `text_body=` 도 생성해 SmtpSender 에 전달. 현재 TemplateNotifier 만 지원 — 일관성 부재.
  - 출처: [reports/09-design-review.md](../reports/09-design-review.md) Surface A P1

### P1 — 비동기 클라이언트

- [ ] **5.8 `AsyncEmailServiceClient`**
  - 파일: [email_service/client.py](../email_service/client.py) — 또는 새 `async_client.py`
  - 변경: `httpx.AsyncClient` 기반 동일 시그니처. async/await 지원.
  - 게이트: `[async]` extras 또는 기본 포함? — httpx 가 이미 async 지원하므로 기본 포함
  - 테스트: pytest-asyncio 로 async 변형 테스트

### P1 — Community

- [ ] **5.9 examples/ 디렉토리**
  - 디렉토리: `examples/`
  - 신규 파일들:
    - `examples/flask_integration.py` — Flask 회원가입 → 매직링크 발송
    - `examples/fastapi_integration.py` — FastAPI 백엔드에서 사용
    - `examples/django_integration.py` — Django signals 기반
    - `examples/integration_test_with_capture.py` — EMAIL_TEST_CAPTURE_DIR 활용 (Phase 4 와 연결)
  - 각 예시는 runnable 하며 README 에서 링크
  - 출처: [reports/10-devex-review.md](../reports/10-devex-review.md) Pass 7

- [ ] **5.10 CONTRIBUTING.md + issue templates**
  - 파일: `CONTRIBUTING.md`, `.github/ISSUE_TEMPLATE/bug_report.md`, `.github/ISSUE_TEMPLATE/feature_request.md`
  - 변경: dev setup, pytest 실행, PR 가이드, code of conduct 링크
  - 출처: [reports/10-devex-review.md](../reports/10-devex-review.md) Pass 7

### P2 — TemplateNotifier 일관성

- [ ] **5.11 TemplateNotifier 가 Notifier ABC 를 상속하도록 정렬**
  - 파일: [email_service/notifiers.py:101](../email_service/notifiers.py)
  - 현재: `TemplateNotifier` 가 `Notifier` ABC 와 무관 — 시그니처도 다름 (`send(to, **context)` vs `send(to, user_name, payload)`)
  - 결정 필요: (a) TemplateNotifier 를 별도 클래스로 명시 — 현재 상태 유지, docstring 명문화 / (b) Notifier 시그니처를 `send(to, **kwargs)` 로 통일 (breaking)
  - 추천: (a) — docstring 에 "Notifier 와는 다른 시그니처를 의도적으로 가짐" 명시 + Notifier 가 fixed (user_name, payload) 인 이유 설명
  - 출처: [reports/08-eng-review-test-plan.md](../reports/08-eng-review-test-plan.md) Top 5

- [ ] **5.12 TemplateNotifier(autoescape=False) 테스트**
  - 파일: [tests/test_email_service.py](../tests/test_email_service.py)
  - 변경: `autoescape=False` 경로의 단위 테스트 추가 — 그 분기가 의도대로 raw context 를 사용하는지
  - 출처: [reports/08-eng-review-test-plan.md](../reports/08-eng-review-test-plan.md) 단일 gap

## 완료 정의

- [ ] P0 4건 완료
- [ ] P1 5건 완료
- [ ] P2 2건 완료
- [ ] [reports/09-design-review.md](../reports/09-design-review.md) 의 19개 TODO 중 P0/P1 13건 closed
- [ ] DX 점수 재측정 (devex-review skill 재실행) — 목표 7.5/10
- [ ] 커밋: `phase-5: polish — a11y, i18n, async client, examples`

## 출구 조건

- 이메일을 [Litmus](https://www.litmus.com/) 또는 수동으로 Gmail/Outlook/Apple Mail 에서 확인 (다크모드 포함)
- `/docs` Swagger UI 가 모든 endpoint 에 summary + example + response schema 표시
- examples/ 의 모든 예시가 `python examples/flask_integration.py` 로 실행됨
