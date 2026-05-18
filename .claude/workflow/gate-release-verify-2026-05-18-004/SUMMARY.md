# Release Gate (Verify-only) — Final SHIP Verification

세션: `gate-release-verify-2026-05-18-004`
타입: **Release Gate final verify-only** (코드 / 테스트 / 문서 / 인프라 수정 0건)
브랜치: `claude/cool-bouman-70eb80`
직전: `gate-test-fix-2026-05-18-001` (flaky test 해결)

## 배포 판정

🟢 **SHIP — 단일 사용자 / 단일 워커 환경 PR 생성 및 머지 안전.**

- P0 release blocker: **0건**
- 모든 8 invariant GREEN (release.yml + runbooks + CHANGELOG + README + version + flaky test)
- 0 회귀, 0 새 finding (**code-L24 평탄화 예측 완전 적중** — 본 cycle 의 최종 확인)
- tag push 가능 조건 명확화: maintainer 1회 setup 후 안전

## Subagent 사용 정당성

**0건**. 정책 (B) 3+ 파일 / (D) 명확한 synthesis 기준만 충족 (2 of 5). 본 verify 는 **객관 검증 가능한 8 invariant grep + 10× stress + full pytest** — subagent ROI 없음. single-flow 일관성 유지.

---

## 1. 모든 release invariant 재확인

### `.github/workflows/release.yml`

```
jobs: ['build-and-smoke', 'publish']           ✅ 2-job split
publish.needs: build-and-smoke                  ✅ 의존성 강제
publish.environment: pypi                       ✅ environment gate
build-and-smoke.permissions: {contents: read}   ✅ id-token 격리
publish.permissions: {id-token: write, ...}     ✅ OIDC publish 만 격리
action_count: 5
all_pinned: True                                ✅ 모두 40-char hex SHA
  actions/checkout              SHA 11bd71901bbe
  actions/setup-python          SHA 0b93645e9fea
  actions/upload-artifact       SHA b4b15b8c7c6a
  actions/download-artifact     SHA fa0a91b85d4f
  pypa/gh-action-pypi-publish   SHA 7f25271a4aa4
```

CRIT-2 (mutable refs) + CRIT-3 (smoke/gate) 모두 RESOLVED 유효.

### Runbooks

```
docs/runbooks/ 파일 수: 5
  api-key-rotation.md
  pypi-yank-hotfix.md
  smtp-disconnect-uncertain.md
  smtp-outage.md
  webhook-outage.md
```

CRIT-4 RESOLVED 유효.

### Docs

```
CHANGELOG.md '## [Unreleased]' 섹션: 1 occurrence    ✅
README.md '## Deployment' 섹션:    1 occurrence    ✅
```

### Version single source

```
api.py line 439: version=__version__              ✅
email_service/__init__.py importlib.metadata:     ✅
runtime: app.version == email_service.__version__ ✅ (직접 호출 확인)
```

### Flaky test (직전 fix 의 검증)

```
10× targeted: pass=10 fail=0 / 10                  ✅ 0% flaky
tests/test_p1_fixes.py 전체: 28 passed, 1 skipped  ✅
Full pytest: 183 passed, 2 skipped                 ✅ 0 regressions
```

git-L06 RESOLVED-By 가 verify 단에서 stress 후에도 안정 유지 확인.

---

## 2. Linux exotic IP 재시도

명령: `docker run --rm python:3.12-slim python -c "import socket; print(socket.getaddrinfo('2130706433', None))"`
환경: Docker Desktop daemon **세 번째 시도에도 미실행**
결과: NOT VERIFIED — code-L13 active 유지

### Release blocker 여부 (최종 판정)

| 배포 컨텍스트 | code-L13 차단 여부 | 근거 |
|--------------|------------------|------|
| **단일테넌트 / 단일워커 / 본 host (Windows)** | ❌ NOT blocker | Windows host getaddrinfo 가 거부 확인됨. validator 통과 후 fetch 도 거부. |
| **Linux production (Docker/Kubernetes)** | ⚠️ CONDITIONAL — 1회 실측 권장 | Linux glibc historically 정수 IP 수용. CI/runner 에서 1회 실행 후 결과 문서화 권장. README/CHANGELOG 에 미검증 명시 완료 — 운영자가 인지 가능. |
| **PyPI 공개 + Linux 사용자 다수** | 🔴 fix 권장 | hostname 정규식 강화로 정수/16진/단축형 차단. 별도 PR. |

**현 컨텍스트 결론**: **단일 테넌트 / 단일 워커 PR 차단 아님**. Linux 첫 배포 전 Docker 환경에서 1회 실측 권장 — 운영자 책임으로 위임 가능 (docs 에 명시되어 있음).

---

## 3. 통합 이슈 — 최종 P0/P1/P2

### P0 (배포 차단)

**0건**. CRIT-2/3/4 + git-L06 모두 RESOLVED.

### P1 (배포 가능, 추적 필요 — 모두 PR 차단 아님)

| ID | 항목 | 처리 권장 시점 |
|----|------|--------------|
| L-SEED-02 | SMTP sender sync sleep (31s budget) | Phase A small fix or v0.4.0 (Phase B async) |
| code-L13 | Linux exotic IP 미검증 | Linux production 첫 배포 전 1회 |
| code-L16 | V1 webhook deprecation 명확 timeline (v1.0?) | docs update 또는 v0.4.0 |
| git-L04 | `.github/dependabot.yml` Actions ecosystem | 별도 docs PR |

### P2 (배포 후 처리)

| ID | 항목 |
|----|------|
| code-L11/L14 | AppDependencies dataclass — 7번째 cross-cutting 도입 전 |
| code-L25 | Lock dict idle TTL eviction |
| code-L27 | Lock ordering invariant 명시 (ARCHITECTURE.md) |
| git-L05 | dev install reinstall 가이드 |
| git-L07 | external setup checklist (PR description) |
| test-L01 | unit-level concurrency 테스트 패턴 (이미 본 fix 가 적용) |
| test-L02 | `_idempotency_guard` emulator drift (code-L11/L14 refactor 시 자동 무력화) |
| - | `.github/workflows/test.yml` PR-time 자동 lint/test |
| - | `requirements.lock` + pip-audit CI step |

### P3 (참고)

- 90 autosave commits → squash merge 권장 (git-L03)
- pre-Pydantic body buffer 메모리 (nginx 권장 명시됨)

---

## 4. PR 생성 가능 여부 + tag push 가능 조건

### 🟢 PR 생성: 가능 (단일테넌트 / 단일워커)

**PR description 필수 포함** (3가지):

1. **Maintainer 1회 setup 요청** (git-L07):
   ```markdown
   ### Maintainer setup required before first tag push
   1. Repo Settings → Environments → Create `pypi`
   2. Add at least one Required reviewer on `pypi` environment
   3. Configure PyPI Trusted Publisher mapping at
      https://pypi.org/manage/account/publishing/
      (Project: email-service, Workflow: release.yml, Environment: pypi)
   ```

2. **Squash merge 권장** (git-L03):
   ```markdown
   ### Merge strategy
   This branch has ~90 autosave commits. Squash merge recommended.
   PR description serves as the canonical change summary.
   ```

3. **Linux exotic IP 미검증 안내** (code-L13):
   ```markdown
   ### Pre-Linux-deploy verification (recommended, not blocking)
   ```bash
   docker run --rm python:3.12-slim python -c \
     "import socket; print(socket.getaddrinfo('2130706433', None))"
   ```
   - `gaierror` → safe (no action)
   - `127.0.0.1` → file follow-up issue for validator hardening
   ```

### Tag push 가능 조건

1. ✅ PR 머지 완료 (squash 권장)
2. ✅ `pypi` Environment Required reviewers 설정 1회 (maintainer)
3. ✅ pyproject.toml version 과 tag 일치 (`build-and-smoke` 가 mismatch 자동 차단)
4. ⚠️ Linux exotic IP 1회 실측 (단일테넌트 면 optional)
5. ✅ flaky test 0건 (본 verify 가 10/10 확정)

→ **모든 조건 충족 시 tag push 안전**. publish 가 build-and-smoke 통과 + Required reviewers manual approval 후만 진행.

---

## 5. code-L24 평탄화 cycle 완료 확인

본 프로젝트의 fix → verify 사이클:

| Cycle | Fix | Verify | 신규 finding |
|-------|-----|--------|------------|
| 1 | P0 ×5 (code) | gate-code-verify-2026-05-18-002 | 2 P1 (NEW-V-1 + 후속 노트) |
| 2 | P1 secondary ×3 | gate-code-verify-2026-05-18-004 | 3 P1 (NEW-V-1/2/3 secondary gap) |
| 3 | secondary P1 ×3 | gate-code-verify-2026-05-18-006 | 1 P1 (NEW-V-4 lock-eviction race) |
| 4 | NEW-V-4 surgical | gate-code-verify-2026-05-18-008 | **0** (code-L24 평탄화 첫 적중) |
| 5 | Release-side CRIT-2/3/4 | gate-release-verify-2026-05-18-003 | 1 P1 (git-L06 test infra flaky) |
| 6 | Test infra (git-L06) | **본 verify** | **0** |

**code-L24 (메타 패턴) 완전 검증**: 평탄화 시그널 3 조건 (새 추상화 X / line 단순 변경 / 회귀 테스트 ≥4) 충족 시 다음 verify 0 finding 예상 → 직전 fix (test rewrite + 4 NEW-V-4 tests) 가 정확히 해당 → 본 verify 0 finding 확정.

**Compound Learning Loop 본 프로젝트 첫 end-to-end 검증 완료**: 6 cycle 만에 5 P0 + 4 P1 tier + 3 release-side P0 + 1 test infra → 모두 resolved, 회귀 0.

---

## Active Learnings Applied

- **L-SEED-01** (테스트 통과 ≠ 안전): 8회차 invocation, 0 finding. 영구 active 유지 (평탄화 후에도 회귀 테스트 의무).
- **git-L01** (Code Gate GREEN ≠ Release ready): VALIDATED 재확인. 본 verify 가 4 항목 (release.yml + runbooks + CHANGELOG + version) 모두 GREEN 확정.
- **git-L06** (TestClient flakiness): RESOLVED 유효 (10/10 stress 통과).
- **code-L24** (평탄화 예측): **fully VALIDATED**. 2회 적중 (gate-code-verify-2026-05-18-008 + 본 verify). 미래 fix 시리즈에 신뢰 가능한 메타 패턴.
- **test-L01/L02**: applied (직전 fix 가 patterns 적용함). 유지.
- **code-L13**: active (Docker 환경 미가용). 운영자 책임 docs 명시 완료.
- **L-SEED-02 / code-L11/L14/L16/L25/L27 / git-L02/L03/L04/L05/L07**: 모두 deferred priors, 변경 없음.

## New Learnings Captured

```yaml
ID: git-L08
Source: gate-release-verify-2026-05-18-004
Severity: P2
Mistake / Miss: 본 프로젝트 end-to-end 처리에 6 verify-fix cycle (Code Gate 4 + Release Gate 2) 소요. Compound Learning Loop 의 평탄화 패턴은 cycle 1-2 에서 거의 명백 (새 추상화 도입 = 새 secondary surface), cycle 3-4 부터 단순 line 변경 + 새 finding 0 으로 수렴.
Root Cause: 보안/안정성 fix 는 새 추상화 (cache / lock / validator) 를 평균 1-2 layer 도입. 각 layer 가 자체 edge case 생성. 결국 단위 수정으로 수렴할 때까지 평탄화 안 됨.
Recurrence Trigger: 보안/안정성 fix 시리즈 신규 개시 시.
Prevention Rule: 첫 P0 발견 시 즉시 cycle 수 견적 — "5 P0 면 약 5 verify-fix cycle 예상". 일정/리소스 추정에 반영. 단일 fix pass 로 끝낼 수 없는 사실 명시.
Next-Session Checklist Item: "fix 시리즈 시작 시 cycle 수 견적 했는가? 일정에 평탄화까지 포함됐는가?"
Applies To: 모든 보안/안정성 fix 시리즈 일정 추정
Owner Gate: git (release planning)
Evidence: 본 프로젝트 6 cycle 완료 — 5 P0 (Code) + 3 P0 (Release) → resolved, 회귀 0. 평탄화 2회 적중.
Status: active
```

## Recurrence Risks

| ID | 본 verify 결과 | 다음 gate / 다음 프로젝트 |
|----|---------------|-------------------------|
| code-L24 | **fully VALIDATED** (2회 적중) | 미래 fix 시리즈에 메타 패턴 재사용 |
| git-L01 | VALIDATED 재확인 | 미래 release gate 의 4 항목 자동 점검 invariant |
| L-SEED-01 | 8회차 active | 영구 |
| **git-L08 (NEW P2)** | new | 미래 보안 fix 시리즈 cycle 수 견적 |

## Next Gate Prompt Addendum (PR 생성용)

> 다음 단계 — `/hwan-refactor-git` 추가 verify 불필요. **PR 직접 생성** prompt 권장:
>
> ```
> Final state (gate-release-verify-2026-05-18-004 SHIP):
> - 183 tests pass, 2 skipped, 0 regressions, 0 flaky
> - 5 P0 + 4 P1 tier (code) + 3 release-side P0 + 1 test infra: all resolved
> - 6 verify-fix cycles complete, code-L24 flattening validated (2× hit)
>
> PR creation steps (do NOT auto-execute — user must approve each):
>
> 1. gh pr create --base master --head claude/cool-bouman-70eb80 \
>    --title "Security & reliability hardening: 5 P0 + 4 P1 fixes" \
>    --body "$(see PR template below)"
> 2. Use squash merge (90 autosave commits → 1)
>
> PR body template (copy-paste from
> .claude/workflow/gate-release-fix-2026-05-18-002/SUMMARY.md §9):
>
> ## Summary
> Codebase hardening across 5 critical (P0) and 4 high (P1) vulnerabilities.
> Test suite expanded 124 → 183 (+60 regression tests, 0 flaky).
>
> ## Resolved (code-level)
> - SSRF on webhook_url (parse-time + per-retry re-validate)
> - Body/subject size caps (RFC 5322 + 10MB)
> - Per-bearer rate limit on /send*
> - BackgroundTasks bounded backoff (71s → 8s + jitter)
> - SMTP post-DATA disconnect phase-aware retry (no double-send)
> - HTTP idempotency via Idempotency-Key with body fingerprint
> - Webhook HMAC V2 timestamp signature (replay defense)
> - Per-key idempotency lock with decoupled lifecycle
>
> ## Resolved (release pipeline)
> - All GitHub Actions pinned to commit SHA (was mutable @v4/@v5)
> - build-and-smoke job + tag-vs-pyproject version check
> - publish job gated on pypi GitHub Environment
> - Version single source via importlib.metadata
> - 5 operational runbooks in docs/runbooks/
> - CHANGELOG ## [Unreleased] + README ## Deployment section
>
> ## Maintainer setup required before first tag push
> 1. Repo Settings → Environments → Create `pypi`
> 2. Set Required reviewers (at least 1)
> 3. Configure PyPI Trusted Publisher mapping
>
> ## Pre-Linux-deploy (recommended, not blocking)
> docker run --rm python:3.12-slim python -c \
>   "import socket; print(socket.getaddrinfo('2130706433', None))"
> - gaierror → safe. 127.0.0.1 → file follow-up issue for validator.
>
> ## Test plan
> - [x] 183 tests pass (60 new regression tests)
> - [x] flaky test resolved (10/10 stress runs)
> - [ ] Linux exotic IP verified (maintainer action before first Linux deploy)
> - [ ] pypi Environment Required reviewers configured (maintainer action)
>
> ## Follow-up issues (separate PRs)
> - SMTP sender sync sleep retry budget cap (L-SEED-02)
> - V1 webhook signature deprecation timeline (code-L16)
> - AppDependencies dataclass refactor (code-L11/L14)
> - .github/dependabot.yml for Actions SHA updates (git-L04)
>
> See .claude/workflow/ for full audit trail across 6 verify-fix cycles.
> ```

---

## Closeout Checklist

- [x] A. SUMMARY 4 섹션 (Active / New / Recurrence / Next Addendum)
- [x] B. learnings.md 11-필드 schema (git-L08)
- [x] C. index.md 세션 로그
- [x] D. Subagent 사용 정당성 명시 (0 호출, 객관 검증)
- [x] E. 코드 / 테스트 / 문서 / release.yml 수정 0건
- [x] F. Hand-off — PR 생성용 prompt + body 템플릿 완성
- [x] G. tree clean, branch ≠ master, destructive 명령 미사용
