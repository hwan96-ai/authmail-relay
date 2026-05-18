# Project-wide Learning Index — email-service

이 인덱스는 모든 `/hwan-refactor-*` gate 가 시작 시 읽어야 하는 cross-gate 누적 학습이다. 형식은 [docs/process/compound-learning-loop.md](../../docs/process/compound-learning-loop.md) §4.2 schema 준수.

---

## Seed Learnings (모든 gate 적용, status: active)

본 8개는 직전 두 세션 (`gate-code-2026-05-16-001`, `gate-release-2026-05-16-001`) 의 strong-convergence 발견을 정규화한 것. 어떤 gate 든 시작 시 priors 로 강제 적용.

### L-SEED-01

```yaml
ID: L-SEED-01
Source: gate-code-2026-05-16-001 (review + adversarial + edge-cases convergence)
Severity: P0
Mistake / Miss: 124 tests pass 인 상태를 "안전" 으로 판단했지만 외부 노출 (SSRF, OOM, rate-limit, threadpool starvation) 5건 미커버.
Root Cause: 단위/통합 테스트가 happy path 와 일부 negative path 만 커버하고, 외부 입력 검증/리소스 한계/공격 시나리오는 별도 reviewer 없이는 안 잡힘.
Recurrence Trigger: 모든 외부 노출 HTTP 엔드포인트가 추가될 때, "테스트 통과 = 안전" 판단을 다시 하려는 충동.
Prevention Rule: 외부 노출 (HTTP route, webhook, callback, file upload, external API) 변경 시 테스트 통과와 별개로 adversarial + edge-case reviewer 1회는 의무.
Next-Session Checklist Item: "이번 diff 가 외부 노출 surface 를 만들거나 확장하는가? 그렇다면 테스트 통과와 별개로 adversarial reviewer 1회 호출했는가?"
Applies To: email_service/api.py, email_service/webhooks.py, email_service/notifiers.py
Owner Gate: code, git
Evidence: gate-code-2026-05-16-001/SUMMARY.md P0-1 ~ P0-5
Status: active
```

### L-SEED-02

```yaml
ID: L-SEED-02
Source: gate-code-2026-05-16-001 (review + adversarial + edge-cases convergence)
Severity: P0
Mistake / Miss: BackgroundTasks.add_task(sync_fn) 패턴에 time.sleep 으로 retry 하는 코드가 들어가 threadpool starvation 위험을 만듦.
Root Cause: FastAPI BackgroundTasks 는 Starlette 의 bounded threadpool(~40) 위에서 동작하는데, sync IO + sleep 이 그 슬롯을 점유한다는 사실이 코드 작성 시점에는 추상화에 가려진다.
Recurrence Trigger: 새 endpoint 에서 webhook/notification/log push 같은 "비동기처럼 보이는 작업" 을 BackgroundTasks 로 등록할 때.
Prevention Rule: BackgroundTasks.add_task 대상 함수에 time.sleep / blocking IO / 동기 HTTP 클라이언트 사용 금지. 필요시 httpx.AsyncClient 또는 자체 ThreadPoolExecutor 로 격리.
Next-Session Checklist Item: "이번 diff 에 BackgroundTasks.add_task 호출이 추가됐는가? 그 대상 함수에 time.sleep 또는 requests/sync httpx 가 있는가?"
Applies To: email_service/api.py, email_service/webhooks.py, **/*background*.py
Owner Gate: code
Evidence: api.py:286 + webhooks.py:33-95 (gate-code-2026-05-16-001/reviews/adversarial.md F-03)
Status: active
```

### L-SEED-03

```yaml
ID: L-SEED-03
Source: gate-code-2026-05-16-001 + gate-release-2026-05-16-001 (review + cso + adversarial)
Severity: P0
Mistake / Miss: webhook_url 을 검증 없이 Pydantic str 또는 HttpUrl 로 받고 httpx 로 fetch — AWS metadata (169.254.169.254), 내부망, file:// 모두 통과.
Root Cause: "사용자가 자기 endpoint 주는데 뭐가 문제?" 라는 mental model. SSRF 위협은 multi-tenant 가정에서만 명백한데 코드 작성자는 단일 사용자 시점으로 봄.
Recurrence Trigger: 사용자가 URL 을 제공하고 서버가 그 URL 을 fetch 하는 모든 경로 (webhook, callback, image fetch, OAuth redirect 등).
Prevention Rule: 사용자 제공 URL fetch 전에 scheme allowlist + hostname resolve + loopback/link-local/private/IPv6-ULA 차단을 무조건 실행. WEBHOOK_ALLOWED_HOSTS env 도 권장.
Next-Session Checklist Item: "이번 diff 가 사용자 제공 URL 을 서버에서 fetch 하는 코드를 추가/수정하는가? scheme + private-IP 차단이 있는가?"
Applies To: email_service/webhooks.py, **/callbacks/**, **/oauth/**
Owner Gate: code, git
Evidence: api.py:51 (no validator) + webhooks.py:33-65 (gate-code-2026-05-16-001/SUMMARY.md P0-2)
Status: resolved
Resolved-By: gate-code-fix-2026-05-18-001 (email_service/url_validation.py + Pydantic field validators)
```

### L-SEED-04

```yaml
ID: L-SEED-04
Source: gate-code-2026-05-16-001 (review + edge-cases convergence)
Severity: P0
Mistake / Miss: Pydantic 필드에 min_length=1 만 있고 max_length 없음. 100MB html_body POST → msg.as_string() 2배 메모리 → OOM.
Root Cause: Pydantic "최소" 검증만 신경 쓰는 습관, FastAPI/uvicorn 가 본문을 메모리에 buffer 한다는 사실이 추상화에 가려짐.
Recurrence Trigger: 새 Pydantic Request 모델에 string/bytes 필드를 추가할 때.
Prevention Rule: 외부 입력 string/bytes 필드에 max_length 명시 의무. subject ≤ 998 (RFC 5322), body ≤ 10MB, list ≤ 100 개. 추가로 reverse-proxy body cap 필수.
Next-Session Checklist Item: "이번 diff 에 새 Pydantic 모델 (특히 Request) 의 str/bytes/list 필드가 추가됐는가? 각 필드에 max_length / max_items 가 있는가?"
Applies To: email_service/api.py, **/schemas/**, **/models/request*.py
Owner Gate: code
Evidence: api.py:51 SendEmailRequest (gate-code-2026-05-16-001/SUMMARY.md P0-3)
Status: resolved
Resolved-By: gate-code-fix-2026-05-18-001 (Pydantic max_length on all SendRequest models)
```

### L-SEED-05

```yaml
ID: L-SEED-05
Source: gate-code-2026-05-16-001 (edge-cases F-002)
Severity: P0
Mistake / Miss: SMTPServerDisconnected 를 phase 와 무관하게 ERR_SMTP_CONNECTION 으로 분류 → sendmail() 성공 후 disconnect 도 재시도 → 수신자 중복 발송.
Root Cause: 예외 타입만 보고 재시도 가능 여부 판정. SMTP 대화의 phase (pre-DATA / post-DATA) 가 의미를 가진다는 것을 retry 분류기가 모름.
Recurrence Trigger: 새로운 SMTP 예외/네트워크 예외를 분류기에 추가할 때, 또는 retry 로직 리팩토링 시.
Prevention Rule: 재시도 분류는 예외 타입 + send phase 양쪽을 본다. post-DATA 시점 이후의 disconnect 는 success 로 간주 (수신자 받았을 가능성 높음). 또는 SMTP Message-ID 기반 멱등성.
Next-Session Checklist Item: "재시도 로직을 추가/수정했는가? phase (pre-DATA / post-DATA) 를 구분하는가? 멱등성 키가 있는가?"
Applies To: email_service/sender.py
Owner Gate: code
Evidence: sender.py:225-291 (gate-code-2026-05-16-001/SUMMARY.md P0-5)
Status: resolved
Resolved-By: gate-code-fix-2026-05-18-001 (sendmail_returned flag + ERR_SMTP_DISCONNECT_UNCERTAIN)
```

### L-SEED-06

```yaml
ID: L-SEED-06
Source: gate-release-2026-05-16-001 (cso + adversarial)
Severity: P0
Mistake / Miss: .github/workflows/release.yml 이 `on: push: tags: ["v*"]` 만으로 PyPI publish. 빌드 검증/스모크/수동 승인 게이트 없음. 잘못된 0.3.1 → yank 만 가능, 버전명 영구 소진.
Root Cause: "tag 만 잘 달면 안전" 가정. PyPI publish 가 일방향이라는 운영 제약이 자동화 작성 시점에 보이지 않음.
Recurrence Trigger: 새 release pipeline 설계, semver bump 자동화 추가, hot-fix workflow 작성 시.
Prevention Rule: tag-trigger publish 는 반드시 (1) build → install → smoke test job, (2) `environment.required_reviewers` 또는 GitHub Release manual trigger 중 하나 이상 의무. 빠지면 release blocker.
Next-Session Checklist Item: ".github/workflows/ 에 publish job 이 있는가? smoke test + 수동 승인 게이트가 있는가?"
Applies To: .github/workflows/*.yml
Owner Gate: git
Evidence: .github/workflows/release.yml (gate-release-2026-05-16-001/SUMMARY.md CRIT-3)
Status: active
```

### L-SEED-07

```yaml
ID: L-SEED-07
Source: gate-release-2026-05-16-001 (cso)
Severity: P0
Mistake / Miss: Workflow 가 `actions/checkout@v4`, `pypa/gh-action-pypi-publish@release/v1` 등 mutable tag 참조 + `id-token: write` PyPI OIDC publish 권한.
Root Cause: Mutable tag 의 무게 (= upstream 침해 시 우리 PyPI 이름으로 악성 wheel) 가 작성 시점에 추상화에 가려짐.
Recurrence Trigger: 새 workflow 작성, action 버전 업데이트 PR, Dependabot 적용 시.
Prevention Rule: publish/배포 권한 (`id-token: write`, `contents: write`, `packages: write`) 을 가진 workflow 의 모든 action 은 commit SHA 핀. Dependabot 으로 SHA 갱신만 받기.
Next-Session Checklist Item: "이번 diff 의 workflow 가 publish 권한을 가지는가? 모든 action 이 commit SHA 로 핀되어 있는가?"
Applies To: .github/workflows/*.yml
Owner Gate: git
Evidence: .github/workflows/release.yml (gate-release-2026-05-16-001/audit/cso.md item-#1)
Status: active
```

### L-SEED-08

```yaml
ID: L-SEED-08
Source: gate-release-2026-05-16-001 (docs-ops)
Severity: P1
Mistake / Miss: SMTP/webhook outage, API_KEY 회전, PyPI yank/hotfix 같은 운영 절차 runbook 0건. "코드는 잘 동작하니까" 단계에서 멈춤.
Root Cause: 코드/테스트는 명시적으로 검토되지만, "사고 났을 때 운영자가 무엇을 누르는가" 는 작성자가 추상적으로만 인지.
Recurrence Trigger: 외부 서비스 의존 (SMTP, webhook, third-party API) 추가 시, 또는 새 인증 정보/시크릿 도입 시.
Prevention Rule: 외부 의존 추가 = runbook 1개 추가가 한 묶음. docs/runbooks/ 디렉토리에 최소 (장애 시나리오, 1차 대응 명령, 롤백 절차) 3 섹션.
Next-Session Checklist Item: "이번 diff 가 외부 의존 또는 시크릿을 추가/변경하는가? docs/runbooks/ 에 대응 절차가 있는가?"
Applies To: docs/runbooks/**, README.md
Owner Gate: git
Evidence: docs/ 부재 (gate-release-2026-05-16-001/audit/docs-ops.md F-001 ~ F-003)
Status: active
```

---

## Session Log

| Date | Gate | Session ID | applied | new | recurred | SUMMARY |
|------|------|-----------|---------|-----|----------|---------|
| 2026-05-16 | code | gate-code-2026-05-16-001 | 0 (seed 없던 시점) | 8 (initial) | — | [link](../workflow/gate-code-2026-05-16-001/SUMMARY.md) |
| 2026-05-16 | git | gate-release-2026-05-16-001 | 0 (seed 없던 시점) | 10 | — | [link](../workflow/gate-release-2026-05-16-001/SUMMARY.md) |
| 2026-05-18 | meta | workflow-improvement | — | 8 seed normalized | — | (이 변경) |
| 2026-05-18 | code | gate-code-fix-2026-05-18-001 | 5 (L-SEED-01,-02,-03,-04,-05) | 3 (code-L09,-L10,-L11) | 0 | [link](../workflow/gate-code-fix-2026-05-18-001/SUMMARY.md) — 4 P0 resolved, 1 partial (L-SEED-02) |
| 2026-05-18 | code | gate-code-verify-2026-05-18-002 | 8 (all priors) | 2 (code-L12,-L13) | 1 (L-SEED-01 재입증) | [link](../workflow/gate-code-verify-2026-05-18-002/SUMMARY.md) — verify-only, 5 P0 결과 확인, 2 신규 P1 (SSRF 잔여) |
| 2026-05-18 | code | gate-code-fix-2026-05-18-003 | 7 (active priors) | 3 (code-L14,-L15,-L16) | 1 (code-L09 generalized → code-L15) | [link](../workflow/gate-code-fix-2026-05-18-003/SUMMARY.md) — 3 P1 surgical, +17 tests, code-L12 resolved |
| 2026-05-18 | code | gate-code-verify-2026-05-18-004 | 10 (all active) | 3 (code-L17,-L18,-L19) | 2 (code-L11, L14 재발) | [link](../workflow/gate-code-verify-2026-05-18-004/SUMMARY.md) — verify-only post P1 fix, 5 P0 stable, 3 secondary gap, SHIP eligible single-tenant |
