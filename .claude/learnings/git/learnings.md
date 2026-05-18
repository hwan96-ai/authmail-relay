# Release Gate — Compound Learnings

> **2026-05-18 — Schema migration**: 이 파일의 항목들은 [docs/process/compound-learning-loop.md §4.2](../../../docs/process/compound-learning-loop.md) 의 11-필드 schema 로 정규화되어 [`.claude/learnings/index.md`](../index.md) 의 Seed Learnings 에 통합되었다.
>
> 다음 release gate 시작 시 priors 는 [index.md](../index.md) 의 `Owner Gate: git` 인 항목 (L-SEED-01, -03, -06, -07, -08) 에서 읽는다.
>
> 신규 learning 은 반드시 11-필드 schema 로 이 파일 하단에 append.

## 2026-05-18 — gate-release-verify-2026-05-18-004 (final SHIP verify)

1 신규 learning. 전체 11-필드 schema 는 `../../workflow/gate-release-verify-2026-05-18-004/SUMMARY.md` 의 "New Learnings Captured" 참조.

- **git-L08** [P2]: 보안/안정성 fix 시리즈는 평균 5-6 verify-fix cycle 필요. fix → secondary surface → 평탄화 패턴. 일정 추정에 cycle 수 반영 필요.

Priors 변경:
- **code-L24 (평탄화 예측)**: **fully VALIDATED** — 2회 적중 (gate-code-verify-2026-05-18-008 + 본 verify). 미래 fix 시리즈에 신뢰 가능 메타 패턴.
- **git-L01 (Code Gate GREEN ≠ Release ready)**: VALIDATED 재확인. 4 항목 점검이 본 verify 에서 그대로 GREEN.
- **git-L06**: RESOLVED 유효 (10× stress 통과).
- L-SEED-01: 8회차 invocation. 영구.

판정: 🟢 **SHIP** for single-tenant single-worker. P0=0. PR description 3 항목 (maintainer setup + squash merge + Linux verify) 포함 시 PR 머지 + tag push 안전.

**본 프로젝트의 Compound Learning Loop end-to-end 검증 완료**: 6 cycle 만에 5 P0 (code) + 4 P1 tier + 3 release-side P0 + 1 test infra → all resolved. 회귀 0.

다음 단계: PR 직접 생성 (gh pr create) — 본 워크플로 범위 밖.

## 2026-05-18 — gate-release-verify-2026-05-18-003 (verify-only, SHIP WITH WATCHLIST)

2 신규 learning. 전체 11-필드 schema 는 `../../workflow/gate-release-verify-2026-05-18-003/SUMMARY.md` "New Learnings Captured" 참조.

- **git-L06** [P1]: `test_idempotency_lock_eviction_race` 가 5회 중 2회 실패 (40% flaky). TestClient thread-safety 한계로 추정, 본 fix code 의 race 가 아님 (unit 테스트 100% 통과). 향후 concurrent 테스트는 unit-level 또는 per-thread TestClient 권장.
- **git-L07** [P2]: GitHub `environment` Required reviewers 같은 외부 설정 의존은 yml 만으로 검증 불가. PR description 에 maintainer setup checklist 명시 필요.

Priors 변경:
- L-SEED-06/-07/-08: **RESOLVED 유효성 확정** (본 verify 가 fix 의 정확성 8 항목 모두 GREEN 확인)
- **git-L01**: **VALIDATED** — Code Gate GREEN ≠ Release ready 4 항목 (release.yml/runbooks/CHANGELOG/version-sync) 자동 점검 패턴이 본 verify 에서 그대로 적용됨. actionability 입증.
- code-L24 (평탄화 예측): 부분 적중. fix 의 새 추상화 0개 → code 측 race 0건. 그러나 TestClient 한계로 인한 test infra 1건 발견. 향후 "code race 0 ≠ test infra 0" 분리.
- L-SEED-01: 6회차 재입증.

판정: 🟡 SHIP WITH WATCHLIST. 단일테넌트/단일워커 PR 가능. tag push 도 manual approval 차단으로 안전 (단 maintainer 가 pypi Environment Required reviewers 1회 설정 필수).

다음 단계: PR 생성 + flaky test follow-up small PR + (옵션) Linux exotic IP Docker 실측 + (옵션) Phase A retry budget cap.

## 2026-05-18 — gate-release-fix-2026-05-18-002 (CRIT-2/3/4 surgical resolution)

2 신규 learning + 3 priors RESOLVED. 전체 11-필드 schema 는 `../../workflow/gate-release-fix-2026-05-18-002/SUMMARY.md` "New Learnings Captured" 참조.

- **git-L04** [P1]: GitHub Actions SHA 핀의 stale 위험. Dependabot 자동 갱신 또는 분기별 audit 필요.
- **git-L05** [P2]: `importlib.metadata` 기반 `__version__` 이 dev stale install 환경에서 잘못된 버전 반환. dev 가이드 보강 필요.

Priors RESOLVED:
- **L-SEED-06** (tag push 자동 publish): RESOLVED-By: gate-release-fix-2026-05-18-002 (smoke gate + manual approval gate)
- **L-SEED-07** (mutable refs + OIDC publish): RESOLVED-By 동일 (5 액션 SHA pin + id-token 격리)
- **L-SEED-08** (runbook 부재): RESOLVED-By 동일 (5 runbook 작성)
- **git-L01** (Code Gate GREEN ≠ Release ready): **VALIDATED** — 본 fix 가 정확히 4 항목 처리하여 learning 의 actionability 입증.

Priors 일부 진화:
- code-L16 (V1 deprecation): 부분 resolved (CHANGELOG/README 명시). 명확한 major version timeline 미정.
- code-L25 (lock dict 메모리): 부분 resolved (README 한계 명시). 코드 측 idle TTL 미구현.

다음 단계: release-gate verify (`/hwan-refactor-git`) 재실행 권장 → SHIP WITH WATCHLIST 또는 SHIP 예상. PR 생성 + maintainer 가 pypi environment Required reviewers 설정 후 tag push.

## 2026-05-18 — gate-release-2026-05-18-001 (verify-only, BLOCK 유지)

3 신규 learning. 전체 11-필드 schema 는 `../../workflow/gate-release-2026-05-18-001/SUMMARY.md` 의 "New Learnings Captured" 참조.

- **git-L01** [P0]: Code Gate 통과 ≠ Release ready. release.yml + docs/runbooks + CHANGELOG + version-sync 는 별도 점검 필수. **본 워크플로의 핵심 invariant**.
- **git-L02** [P1]: PR 머지 가능 ≠ tag push 가능. tag push 자동 publish 구조에서 두 단계 분리 명시 필요.
- **git-L03** [P2]: autosave hook 의 90 commits → squash merge 권장. PR description 이 의미 단위 변경 요약 역할.

Priors 변경:
- **L-SEED-06 (tag push 자동 publish)**: **재발** — 1차 release gate (2026-05-16) 발견 후 미수정. severity P0 유지.
- **L-SEED-07 (mutable refs + OIDC)**: **재발** 동일.
- **L-SEED-08 (runbook 부재)**: **재발** 동일.
- 기존 R-1 ~ R-15 (직전 release gate): 모두 미수정 status 그대로. Sprint 1-3 으로 분류.

판정: 🔴 BLOCK (publish 측). 🟡 단일테넌트 PR 생성은 코드 안전 (description 에 release-yml 하드닝 미완 명시 시).

다음 단계: Sprint 1 (release.yml SHA pin + smoke gate + __version__) → Sprint 2 (runbooks + CHANGELOG + README) → Sprint 3 (Linux verify + 선택 Phase A) → re-run `/hwan-refactor-git`.

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
