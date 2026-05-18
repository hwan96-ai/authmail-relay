# Release Gate — Compound Learnings

> **2026-05-18 — Schema migration**: 이 파일의 항목들은 [docs/process/compound-learning-loop.md §4.2](../../../docs/process/compound-learning-loop.md) 의 11-필드 schema 로 정규화되어 [`.claude/learnings/index.md`](../index.md) 의 Seed Learnings 에 통합되었다.
>
> 다음 release gate 시작 시 priors 는 [index.md](../index.md) 의 `Owner Gate: git` 인 항목 (L-SEED-01, -03, -06, -07, -08) 에서 읽는다.
>
> 신규 learning 은 반드시 11-필드 schema 로 이 파일 하단에 append.

## 2026-05-16 — gate-release-2026-05-16-001 (audit-only, BLOCK verdict) [LEGACY FORMAT]

### L1 — GitHub Actions `@v4` 같은 mutable tag + OIDC publish = 단일 침해점
- Category: true_positive
- Pattern: `.github/workflows/*.yml`이 `id-token: write`와 PyPI/registry publish 권한을 가지면서 액션을 mutable tag로 참조 (`@v4`, `@main`, `@release/v1`)
- Action: 모든 publish 워크플로의 액션은 commit SHA로 핀, Dependabot으로 SHA 갱신
- Evidence: `.github/workflows/release.yml` (이 세션)
- Confidence: 10/10

### L2 — PyPI tag-push 자동 배포는 일방향
- Category: project_context
- Pattern: `on: push: tags: ["v*"]` 만으로 publish, 스모크/수동 승인 게이트 없음
- Action: 최소 install + smoke test job + `environment.required_reviewers` 또는 GitHub Release 트리거로 변경
- Evidence: `.github/workflows/release.yml` (이 세션)
- Confidence: 9/10

### L3 — `requirements.lock` 부재 + 상한선 없는 의존성은 supply chain 사고 대기
- Category: true_positive
- Pattern: `pyproject.toml`에 `>=` 하한선만, `<X` 상한 일부 없음, lock file 없음
- Action: `uv lock` 또는 `pip-compile`로 lockfile + CI에 `pip-audit` 잡 추가
- Evidence: pyproject.toml + 주석 처리된 TODO (이 세션)
- Confidence: 9/10

### L4 — 디버그 플래그가 시크릿을 stderr로 흘리는 패턴은 항상 prod-가드 필요
- Category: true_positive
- Pattern: `DEBUG=1` 같은 env var가 base64 password / 토큰을 컨테이너 stderr에 출력
- Action: prod 환경 자동 감지 + 거부, 또는 startup 시 loud warning, redact log filter
- Evidence: sender.py:311-312 (이 세션) — 후속 세션에서도 다시 확인
- Confidence: 10/10

### L5 — `hash_recipient` 같은 PII redaction은 salt 없으면 식별 가능
- Category: true_positive
- Pattern: 로그 PII 마스킹에 `hashlib.sha256(value)` 직접 사용
- Action: per-deployment random salt 환경변수 + bcrypt 또는 hmac-based hash
- Evidence: logging_config.py:40-42 (이 세션)
- Confidence: 9/10

### L6 — OpenAPI version과 pyproject version 불일치 = 신뢰 손상 시그널
- Category: true_positive
- Pattern: `FastAPI(version="0.2.0")` 하드코딩, pyproject `version = "0.3.0"`
- Action: `email_service/__init__.py`에 `__version__` 단일 소스, 양쪽 모두 참조
- Evidence: api.py:172 vs pyproject.toml (이 세션)
- Confidence: 10/10

### L7 — 외부 서비스 코드 작성 후에는 항상 runbook 0건이 큰 갭
- Category: project_context
- Pattern: SMTP/webhook/외부 호출 코드는 있는데 `docs/runbooks/` 디렉토리 자체가 없음
- Action: 코드 작성과 동시에 최소 SMTP-outage, webhook-outage, API_KEY-rotation runbook 작성
- Evidence: README + docs/ 전체 (이 세션)
- Confidence: 9/10

### L8 — `BackgroundTasks` 기반 비동기 작업은 SIGTERM drain 패턴 필수
- Category: true_positive
- Pattern: FastAPI `BackgroundTasks` + uvicorn 종료 시 drain 코드 없음
- Action: lifespan handler에 in-flight 작업 추적 + grace period
- Evidence: api.py:271-289 (이 세션)
- Confidence: 8/10

### L9 — Single shared API_KEY는 다중 통합 + 회전 요구 즉시 막힘
- Category: project_context
- Pattern: 환경변수로 받는 단일 `API_KEY`로 인증 (예: bearer)
- Action: dual-auth 기간 지원 (2개 키 동시 valid) 또는 다중 키 + per-key quota
- Evidence: api.py:161 (이 세션)
- Confidence: 8/10

### L10 — Prometheus default registry는 uvicorn workers≥2 시 침묵 손상
- Category: true_positive
- Pattern: `from prometheus_client import Counter` global + 멀티 워커
- Action: `PROMETHEUS_MULTIPROC_DIR` env + `MultiProcessCollector`, 워커 가이드 README에
- Evidence: metrics.py:33 (이 세션)
- Confidence: 8/10

---

## 누적 적용

L1-L4는 모든 Python+CI+PyPI 프로젝트의 반복 위험. L5-L10은 본 프로젝트 특화. 다음 Release Gate 실행 시 자동 priors.
