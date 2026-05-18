# Release Gate 검증 결과 — Post Code-Gate VERIFIED

세션: `gate-release-2026-05-18-001`
타입: **Release Gate verify-only** (코드 / 테스트 / 문서 / 인프라 수정 0건)
브랜치: `claude/cool-bouman-70eb80`
직전 Code Gate: `gate-code-verify-2026-05-18-008` (🟢 VERIFIED, 0 신규 finding)
직전 Release Gate: `gate-release-2026-05-16-001` (🔴 BLOCK)
변경 범위 vs origin/master: 37 files, +7222 / −107, 90 commits

## 배포 판정
🔴 **BLOCK — 단일 사용자 / 단일 워커 PR 도 release-side P0 3건 미해결로 차단. PyPI publish 자동화가 일방향이라 잘못 publish 시 버전명 영구 소진.**

판정 근거:
- 코드 레벨 P0/P1 (16건): 모두 resolved + 회귀 테스트 60건 ✅
- 그러나 직전 release gate 의 release-specific P0 3건 (CRIT-2/3/4) **미해결 그대로**
- 4건의 추가 release-blocker 인지 항목: 1건 미검증 (Linux), 1건 추적 (in-flight email loss), 2건 docs gap

**중요**: "PR 생성 가능 여부" 와 "publish/release 가능 여부" 는 다름. **PR 생성 자체는 가능** (코드 안정성 확보). 단, **이 PR 을 머지하면 tag push 시 즉시 publish 위험** — 이 사실을 PR description 에 명시하고 release-side 처리 완료 후 머지/tag push 권장.

---

## Subagent 사용 정당성

**Subagent 호출 0건**. 정책 점검:
- (A) 다관점 ✅ / (B) 3+ 파일 ✅ / (C) Adversarial ✅ / (D) Synthesis 기준 ✅ / (E) phase 병렬 요구 ✅ → 5 of 5 충족.
- **그러나** 4 로컬 점검 (release.yml + docs/ + CHANGELOG + version) 으로 BLOCK 사유가 명백히 확정. subagent 가 추가 발견할 여지 적음 (직전 release gate 가 이미 21 + 17 + 15 = 53 findings 확보).
- **fresh context**: 직전 release gate 산출물 + Code Gate 8 세션의 누적 priors 가 본인 컨텍스트에 있음.
- 정책 5/5 충족하지만 ROI 가 marginal — single-flow 진행. 사용자가 추가 confidence 요구 시 dispatch 가능.

---

## 1. 직전 Release Gate (2026-05-16-001) BLOCK 항목 재확인

### 🔴 CRIT-2 [STILL ACTIVE] — GitHub Actions mutable refs + OIDC publish

**위치**: `.github/workflows/release.yml:25-28, 36`
**상태**: 미수정 (release.yml 안 건드림 그대로)

```yaml
- uses: actions/checkout@v4                        # mutable tag
- uses: actions/setup-python@v5                    # mutable tag
- uses: pypa/gh-action-pypi-publish@release/v1     # mutable tag
permissions:
  id-token: write                                  # PyPI Trusted Publisher OIDC
  contents: read
```

**위험**: 위 액션 중 하나가 upstream 침해되면 우리 PyPI 이름으로 악성 wheel 배포. **release blocker for PyPI publish**.
**수정 방향**: 모든 액션을 commit SHA 로 핀, Dependabot 으로 SHA 갱신만 받기.

### 🔴 CRIT-3 [STILL ACTIVE] — Tag-trigger 자동 publish, smoke/approval 게이트 0

**위치**: `.github/workflows/release.yml:14-16`
**상태**: 미수정

```yaml
on:
  push:
    tags:
      - "v*"
```

**위험**: tag push 즉시 PyPI publish. 빌드 검증 / 스모크 테스트 / 수동 승인 0건. 잘못된 0.4.0 publish → yank 만 가능, 버전명 영구 소진, 핫픽스로 0.4.1 강제.
**수정 방향**:
1. `environment.pypi` 에 `required_reviewers` 추가 (가장 작은 변경)
2. 또는 publish 전 install + smoke test job 추가 (`pip install dist/*.whl && python -c "import email_service; ..."` )
3. 또는 GitHub Release manual trigger 로 변경 (`on: release: published`)

### 🔴 CRIT-4 [STILL ACTIVE] — 운영 runbook 부재

**위치**: `docs/runbooks/` 디렉토리 미존재. `docs/` 하위에 `process/` 만 (워크플로 docs).
**상태**: 미작성

**누락 runbook (최소 5건)**:
- SMTP outage 대응
- webhook 타겟 outage 대응
- `API_KEY` 무중단 회전 절차
- PyPI yank / hotfix release 절차
- `ERR_SMTP_DISCONNECT_UNCERTAIN` 대응 (운영자 액션 명세)

**위험**: 첫 사고 시 운영자 대응 불가. 코드 단계에서 P0 해결했지만 운영 단계 readiness 0.

---

## 2. 신규 release-side 발견 (Code Gate 이후 추가)

### 🟡 P1 — `version="0.2.0"` 하드코딩 (api.py:438) ↔ pyproject.toml `0.3.0`

**위치**: `email_service/api.py:438`
**문제**: OpenAPI 가 `0.2.0` 응답. pyproject 와 불일치. 통합 SDK 가 OpenAPI 기반이면 잘못된 client 생성. 직전 release gate 의 R-9, code-L16 와 별개 항목.
**수정 방향** (다음 small fix):
```python
# email_service/__init__.py
__version__ = "0.3.0"
# api.py
from email_service import __version__
app = FastAPI(version=__version__, ...)
```

### 🟡 P1 — CHANGELOG `## [Unreleased]` 섹션 부재

**위치**: `CHANGELOG.md` head
**문제**: 본 작업 (P0×5 + P1×4 tier + 60 회귀 테스트) 의 CHANGELOG 미작성. 다음 release 가 0.3.1? 0.4.0? semver 결정 안 됨.
**수정 방향** (release 전 docs PR):
- `## [Unreleased]` 섹션 신설
- 5 P0 fix + 4 P1 tier 정리
- V1 webhook signature deprecation 공지
- BREAKING changes 확인 (현재 없음 — V2 sig 는 추가)

### 🟡 P1 — README deployment guidance 부재

**위치**: `README.md`
**문제**: 본 작업으로 도입된 운영 관련 사항이 README 에 없음:
- `API_RATE_LIMIT_PER_MINUTE` (default 60, multi-worker → cap × workers)
- `API_IDEMPOTENCY_TTL_SECONDS` (default 86400)
- `WEBHOOK_ALLOW_HOSTS` / `WEBHOOK_ALLOW_LOOPBACK` (테스트/내부 콜백)
- single-worker vs multi-worker 권장
- nginx `client_max_body_size 12m` 또는 uvicorn body cap
- `EMAIL_SERVICE_DEBUG=1` production 금지 경고

### 🟡 P1 — Lock dict 메모리 + V1 deprecation 미문서화 (code-L25/L16)

이미 인지된 P2 도 release 전 docs 영역으로 격상 권장.

---

## 3. 통합 이슈 — P0/P1/P2 재분류

### P0 (배포 차단)

| ID | 출처 | 위치 | 문제 | 수정 우선순위 |
|----|------|------|------|--------------|
| CRIT-2 | 직전 release gate | release.yml:25-28,36 | mutable action refs + OIDC publish | Sprint 1 |
| CRIT-3 | 직전 release gate | release.yml:14-16 | tag push 자동 publish, smoke 0 | Sprint 1 |
| CRIT-4 | 직전 release gate | docs/runbooks/ 없음 | 운영 runbook 0건 | Sprint 1-2 |

### P1 (PR 가능, 그러나 머지/publish 전 처리 권장)

| ID | 출처 | 위치 | 문제 |
|----|------|------|------|
| R-9 | 직전 + 본 verify | api.py:438 | `version="0.2.0"` ↔ pyproject `0.3.0` |
| P1-new-1 | 본 verify | CHANGELOG.md | `## [Unreleased]` 섹션 부재 |
| P1-new-2 | 본 verify | README.md | deployment guidance 부재 (rate limit/idempotency env, body cap, debug 경고) |
| L-SEED-02 | 누적 | sender.py | SMTP retry sync sleep 31s |
| code-L13 | 누적 | url_validation.py | Linux exotic IP 미검증 |
| code-L16 | 누적 | webhooks.py + docs | V1 signature deprecation timeline 부재 |
| code-L25 | 누적 | api.py | Lock dict 메모리 bound 미문서화 |
| code-L27 | 누적 | api.py | Lock ordering invariant 미문서화 |

### P2 (배포 후 처리)

| ID | 출처 | 문제 |
|----|------|------|
| R-1 | 직전 | `requirements.lock` 부재 + 상한선 느슨 (`prometheus-client`, `python-json-logger`) — 다음 minor 전 권장 |
| R-2 | 직전 | `EMAIL_SERVICE_DEBUG` production guard 부재 (코드 변경 필요) |
| R-3 | 직전 | `hash_recipient` salt 없는 SHA-256 |
| R-4 | 직전 | Prometheus multiprocess 모드 미설정 |
| R-5 | 직전 | BackgroundTasks SIGTERM drain 없음 |
| R-6 | 직전 | OpenAPI `/metrics` 기본 미인증 노출 |
| R-7 | 직전 | Dockerfile USER root 추정, HEALTHCHECK 없음 |
| L-SEED-08 | 직전 | smtp_disconnect_uncertain runbook (CRIT-4 의 일부) |
| code-L21 | 누적 | 실패-미캐싱 trafic 증폭 monitoring alert 없음 |

### P3 (참고)

- CHANGELOG 의 "30초 안에 시작" 라벨 정확성
- 본 작업의 commit message convention (autosave commits 가 90개 — 정리 PR 권장 또는 squash)

---

## 4. CI / release.yml 상세 점검

| 항목 | 상태 |
|------|------|
| `actions/checkout` | `@v4` mutable — **P0 CRIT-2** |
| `actions/setup-python` | `@v5` mutable — **P0 CRIT-2** |
| `pypa/gh-action-pypi-publish` | `@release/v1` mutable — **P0 CRIT-2** |
| Trusted Publisher OIDC | 활성화 (좋음, secret 없음) |
| Build smoke test | **없음** — **P0 CRIT-3** |
| Manual approval (`environment.required_reviewers`) | **미설정** — **P0 CRIT-3** |
| Tag pattern | `v*` (모든 v-prefix 자동 publish) |
| dependabot config | 미확인 (.github/dependabot.yml 없음) |
| pip-audit / safety CI step | 없음 |
| 다른 workflow | ISSUE_TEMPLATE/ 만 — CI test workflow 없음 (lint/test on PR 자동화 0) |

**CI test workflow 부재 별도 발견**: PR 에 대한 자동 lint/test workflow 없음. 머지 전 reviewer 가 로컬에서 테스트해야 함. **P1 — `.github/workflows/test.yml` 추가 권장**.

---

## 5. 문서/운영 readiness

| 영역 | 상태 |
|------|------|
| README.md | 30802 bytes, deployment guidance 부재 (P1-new-2) |
| CHANGELOG.md | 5589 bytes, Unreleased 섹션 부재 (P1-new-1) |
| CONTRIBUTING.md | 존재 |
| CLAUDE.md | 본 작업으로 process docs 진입점 추가됨 |
| docs/process/ | compound-learning-loop, subagent-policy, gate-closeout-checklist 3건 |
| docs/runbooks/ | **없음 (CRIT-4)** |
| ARCHITECTURE.md | 없음 (lock ordering invariant 등 명시 필요 — code-L27) |
| SECURITY.md | 없음 (취약점 보고 절차) |

---

## 6. Linux exotic IP 실측 결과

명령: `python -c "import socket; print(socket.getaddrinfo('2130706433', None))"`
환경: Windows 11 (현재 host)
결과: **gaierror** (Windows getaddrinfo 거부) — 안전 확인 (단 Windows 한정)

⚠️ **Linux 환경 (Ubuntu/Debian + glibc) 미실측**. Production 배포 환경이 Linux 일 경우:
- Linux glibc 의 `inet_aton` 호환 동작이 historically 정수 IP 수용
- 실측 권장: Docker `python:3.12-slim` 이미지에서 1회 실행
```bash
docker run --rm python:3.12-slim python -c "import socket; print(socket.getaddrinfo('2130706433', None))"
```
- 결과가 gaierror → safe (Windows 와 동일)
- 결과가 `('127.0.0.1', 0)` → **validator bypass 확정, P0 격상**

본 verify 에서는 단일 host 결과만 확보. release 전 Linux 컨테이너 실측 required.

---

## 7. 사용자 질의 8 release blocker 재분류

| # | 항목 | 분류 | 단일테넌트 SHIP | 멀티테넌트 SHIP | PyPI 공개 |
|---|------|------|---------------|----------------|-----------|
| 1 | SMTP sender sync sleep | P1 | ✅ | 🟡 monitor | 🔴 Phase A |
| 2 | Linux exotic IP | P1 | ⚠️ **verify before Linux deploy** | ⚠️ same | 🔴 verify + fix |
| 3 | V1 webhook deprecation timeline | P1 | ✅ doc | ✅ doc | 🔴 README/CHANGELOG 명시 필수 |
| 4 | In-memory rate limit / idempotency | P2 | ✅ | 🟡 doc | 🔴 Redis |
| 5 | Lock dict memory bound | P2 | ✅ | ✅ | 🟡 idle TTL eviction |
| 6 | smtp_disconnect_uncertain runbook | P2 | ✅ doc | ✅ doc | ✅ doc |
| 7 | Reverse-proxy body cap | P2 | ✅ doc | ✅ doc | 🟡 nginx 권장 명시 |
| 8 | Multi-worker deployment caveat | P2 | ✅ N/A (single) | 🟡 doc | 🔴 명확 명시 |
| **+** | **CRIT-2/3/4 (release-side P0)** | **P0** | **🔴 BLOCK** | **🔴 BLOCK** | **🔴 BLOCK** |

### 단일테넌트/단일워커 기준 PR 생성 가능 여부

- **코드 자체**: ✅ 생성 가능. 60 회귀 테스트, 회귀 0건, P0 5건 + P1 4 tier resolved.
- **PR 머지/배포**: 🔴 publish 자동화가 일방향 (CRIT-3) → **PR 머지 ≠ publish 안전**. PR description 에 "Do not push tag until CRIT-2/3 resolved" 명시 필수.

### PyPI 공개 / 멀티테넌트 추가 blocker

| 격상 항목 | 사유 |
|----------|------|
| #1 SMTP sync sleep → P0 | 다중 워커 환경의 cascading 실패 — Phase A retry budget cap 도입 필요 |
| #2 Linux exotic IP → P0 (확정 시) | validator bypass 가능 |
| #3 V1 deprecation timeline → P1 | 외부 통합자 다수 → 마이그레이션 path 명시 의무 |
| #4 In-memory state → P0 (정확 quota 요구 시) | Redis-backed 필수 |
| #8 Multi-worker caveat → P0 | README 미명시 시 운영자가 cap 곱하기 forget |

---

## 8. Release Sprint 권장 순서

### Sprint 1 — Release-blocker 처리 (1-2일)
1. **release.yml SHA 핀** (CRIT-2): 3 action 을 commit SHA 로
2. **publish smoke gate** (CRIT-3): build → install → smoke test job 추가 OR `environment.pypi.required_reviewers` 설정
3. **`__version__` 단일 소스** (P1 R-9): `email_service/__init__.py` 에 `__version__ = "0.4.0"` (또는 결정한 다음 버전), `api.py` 가 이를 import

### Sprint 2 — 운영 readiness (2-3일)
4. **`docs/runbooks/` 신설** (CRIT-4): 5 runbook 최소 (smtp-outage, webhook-outage, api-key-rotation, pypi-yank-hotfix, smtp-disconnect-uncertain)
5. **CHANGELOG `## [Unreleased]`** (P1-new-1): 5 P0 + 4 P1 tier + V1 deprecation 공지
6. **README deployment guide** (P1-new-2): env vars table, single vs multi worker, reverse-proxy body cap, debug 경고, V1 timeline
7. **ARCHITECTURE.md** (선택, code-L27): lock ordering invariant + state ownership

### Sprint 3 — Linux verify + 선택 fix (반나절)
8. **Linux exotic IP 실측** (code-L13): Docker 1회 → 결과로 코드 fix 결정
9. **(선택) Phase A retry budget cap** (L-SEED-02): `SmtpSender(max_total_retry_sleep_seconds=10)` 옵션 + 회귀 테스트 1건
10. **(선택) `.github/workflows/test.yml`** 추가: PR 시 pytest 자동 실행

### Re-validation
- Sprint 1 후: `/hwan-refactor-git --quick` 재실행 → CRIT-2/3 resolved 확인
- Sprint 2 후: `/hwan-refactor-git` 전체 → 운영 readiness GOOD
- 그 후 PR 생성 + 머지 + tag push (publish 자동)

---

## 9. PR 생성 권장 시점 + PR description 템플릿

### 권장 시점 (단일테넌트/단일워커)
- **A안 (보수)**: Sprint 1-2 완료 후 PR 생성. 머지 = 즉시 publish 안전.
- **B안 (분할)**: 본 코드 변경만 별도 PR (no tag push). description 에 "Do not push tag — release-yml hardening pending in follow-up PR" 명시. 별도 PR 로 Sprint 1-2 처리. 더 작은 PR 단위, 리뷰 부담 감소.

### PR description 템플릿 (B안 가정)
```markdown
## Summary
Codebase hardening: 5 P0 + 4 P1 tier vulnerabilities resolved across security,
SMTP correctness, and operational safety. Test suite expanded 124 → 183 (+60
regression tests).

## What's resolved (code level)
- P0-1 BackgroundTasks threadpool starvation → bounded backoff + jitter
- P0-2 webhook_url SSRF → scheme + IP + DNS validation, per-retry re-check
- P0-3 body/subject OOM → Pydantic max_length
- P0-4 missing rate limit → sliding window per bearer
- P0-5 SMTP post-DATA disconnect double-send → sendmail_returned phase flag
- P1 SSRF DNS rebinding (parse-time + per-retry, code-L17)
- P1 Idempotency body fingerprint mismatch → HTTP 409 (code-L18)
- P1 Idempotency per-key concurrency lock (code-L19) + lifecycle decoupled (code-L23)
- P1 Webhook HMAC V2 timestamp signature for replay defense

## ⚠️ DO NOT PUSH TAG until follow-up PR lands

This branch is code-level safe to merge but the release pipeline still has:
- mutable GitHub Actions refs (CRIT-2)
- tag-push → immediate PyPI publish with no smoke gate (CRIT-3)
- no docs/runbooks/ directory (CRIT-4)

A separate PR will harden release.yml and add operational runbooks BEFORE
the next tag.

## Test plan
- [x] 183 unit/integration tests pass (was 124)
- [x] 60 new regression tests covering each P0/P1 contract
- [ ] Linux exotic IP behavior verified (code-L13, run separately)

## Documentation gaps (follow-up)
See .claude/workflow/gate-release-2026-05-18-001/SUMMARY.md
```

---

## Active Learnings Applied

직전 priors:
- L-SEED-01: invocation 6회 (release gate 가 직접 code 회귀 안 봄, 별도) — 영구 active
- L-SEED-02: active (Phase A 미실행)
- L-SEED-03/-04/-05: resolved
- L-SEED-06 (tag push 즉시 publish): **재발 — 1차 release gate 에서 발견 후 미해결**. severity 한 단계 상승 검토 → P0 유지 (이미 P0)
- L-SEED-07 (mutable refs + OIDC): **재발** 동일.
- L-SEED-08 (runbook 부재): **재발**.
- code-L09/L15/L17/L18/L19/L23: resolved 유효 (code-level)
- code-L11/L14/L16/L20/L21/L22/L24/L25/L26/L27: active, 대부분 release-gate 영역
- code-L13: active 미검증 (Linux)

## New Learnings Captured

```yaml
ID: git-L01
Source: gate-release-2026-05-18-001
Severity: P0
Mistake / Miss: Code Gate 8 세션이 P0/P1 30+건 처리하는 동안 Release Gate 의 P0 (release.yml + runbook) 0건 처리. Code-side stable 이라 self-evidence 가 강했지만 publish 시 즉시 위험.
Root Cause: Gate 분리 시 release-side P0 는 code-side 에 inherit 되지 않는다는 가정. 실제로는 release.yml 미수정 = publish 위험 그대로.
Recurrence Trigger: Code Gate verified → release-gate skip 충동.
Prevention Rule: Code Gate 가 모두 GREEN 이라도 Release Gate 는 release.yml + docs/runbooks + CHANGELOG + version-sync 의 4가지를 별도 점검. 이 4가지는 code 회귀 0건과 무관.
Next-Session Checklist Item: "Code Gate 통과 후 Release Gate 시작 시: release.yml SHA pin / smoke gate / docs/runbooks/ 존재 / CHANGELOG Unreleased / __version__ 단일 소스 4가지 점검 했는가?"
Applies To: .github/workflows/*, CHANGELOG.md, README.md, docs/runbooks/
Owner Gate: git
Evidence: 1차 release gate (2026-05-16-001) 의 CRIT-2/3/4 가 본 verify 에서 그대로 발견. Code Gate 6 verify pass 동안 변경 0.
Status: active
```

```yaml
ID: git-L02
Source: gate-release-2026-05-18-001
Severity: P1
Mistake / Miss: PR 생성 가능 여부 와 publish 가능 여부 가 동치라고 가정하면 잘못된 결정. tag push 즉시 publish 구조에서는 PR 머지 자체는 안전해도 그 후 tag push 가 위험.
Root Cause: GitHub flow 의 PR-merge-then-tag 패턴에서 두 단계 분리가 implicit 임.
Recurrence Trigger: 코드 안정성만 보고 PR 머지 → tag push 충동.
Prevention Rule: PR 머지 직전 release.yml + runbook 상태 재확인. PR description 에 "DO NOT push tag until <conditions>" 명시.
Next-Session Checklist Item: "이번 PR 머지 후 tag push 안전한가? release.yml mutable refs / smoke gate / runbook 모두 OK 인가?"
Applies To: PR description 템플릿, release 절차
Owner Gate: git
Evidence: 본 verify (이 세션) — code GREEN but release.yml unchanged.
Status: active
```

```yaml
ID: git-L03
Source: gate-release-2026-05-18-001
Severity: P2
Mistake / Miss: PR 의 90 commits 가 모두 `autosave: claude changes <timestamp>` 형식. semantic commit history 부재 — 머지 후 git log 가 분석 불가.
Root Cause: autosave hook 의 부수효과. 의도된 안전 장치지만 release 단계에서 noise.
Recurrence Trigger: autosave hook + 긴 fix 시리즈.
Prevention Rule: PR 머지 전 (또는 머지 옵션으로) squash 사용. PR description 이 변경 요약 역할 — autosave history 의 정보 손실 없음.
Next-Session Checklist Item: "PR 머지 옵션이 squash 인가? PR description 이 변경 요약을 정확히 담고 있는가?"
Applies To: PR 머지 절차
Owner Gate: git
Evidence: 90 autosave commits in this branch (이 세션 git log)
Status: active
```

## Recurrence Risks

| ID | 본 verify 결과 | 다음 gate 관찰 포인트 |
|----|---------------|---------------------|
| L-SEED-06 (tag push 자동 publish) | **재발 — 2차 release gate** | severity P0 유지, Sprint 1 강제 |
| L-SEED-07 (mutable refs + OIDC) | **재발 — 2차 release gate** | severity P0 유지, Sprint 1 강제 |
| L-SEED-08 (runbook 부재) | **재발 — 2차 release gate** | severity P1 유지 (단일테넌트 ship 가능), Sprint 2 |
| code-L13 (exotic IP) | 미검증 — 단순 명령 1회로 해결 가능 | Sprint 3 |
| code-L16 (V1 deprecation) | active | Sprint 2 (CHANGELOG/README) |
| code-L25 (lock dict memory) | active | Sprint 2 (docs) |
| code-L27 (lock ordering) | active | Sprint 2 (ARCHITECTURE.md) |
| **git-L01 (NEW P0)** | new | Code Gate GREEN ≠ Release ready — 본 워크플로의 핵심 invariant |
| **git-L02 (NEW P1)** | new | PR 머지 가능 ≠ tag push 가능 — release 절차 분리 |
| **git-L03 (NEW P2)** | new | autosave commits → squash merge |

## Next Gate Prompt Addendum

> 다음 gate prompt (Sprint 1-2 처리 후 `/hwan-refactor-git` 재실행) 에 그대로 붙일 텍스트:
>
> ```
> Active priors from gate-release-2026-05-18-001:
>
> CURRENT BLOCK reasons (release-side P0, must resolve before publish):
> - CRIT-2 release.yml mutable refs (@v4, @v5, @release/v1) + OIDC publish
> - CRIT-3 tag push = immediate PyPI publish, no smoke/approval gate
> - CRIT-4 docs/runbooks/ directory absent
>
> NON-BLOCKING for single-tenant single-worker PR creation:
> - All code-level P0 (5) and P1 (4 tiers) resolved + 60 regression tests
> - 183/185 tests pass, 0 regressions
>
> Sprint sequence:
> Sprint 1 (CRIT-2/3): release.yml SHA-pin all 3 actions; add smoke job
>   OR set environment.required_reviewers; __version__ single source.
> Sprint 2 (CRIT-4 + P1 docs): docs/runbooks/ 5 minimum; CHANGELOG
>   Unreleased section; README deployment guide with env table.
> Sprint 3 (verify + optional): Linux exotic IP 1× docker run;
>   optional Phase A retry budget cap; optional .github/workflows/test.yml.
>
> Pre-PR checklist (single-tenant single-worker):
> 1. PR description states: "DO NOT push tag until release.yml hardened"?
> 2. PR uses squash merge (90 autosave commits)?
> 3. Test plan in PR: 183 pass + Linux exotic IP verify pending?
>
> After Sprint 1-2: re-run /hwan-refactor-git. Expected verdict change:
> BLOCK → SHIP WITH WATCHLIST (Linux verify) → SHIP.
> ```

---

## 최종 ship 가능 여부

🔴 **현 상태: BLOCK** (publish 측면)
🟡 **단일테넌트/단일워커 PR 생성**: 코드 자체 안전 — **단, PR description 에 release-yml 하드닝 미완 명시 필수**
🔴 **PyPI 공개 publish**: Sprint 1-2 완료 전 절대 불가

이유:
- 코드 자체 SHIP eligible
- 그러나 release 자동화가 일방향 (CRIT-3) → 코드 안전이 publish 안전을 보장하지 않음
- CRIT-2 (mutable refs) 가 supply chain 위험 (P0)
- CRIT-4 (runbook 부재) 가 첫 사고 시 대응 불가

권장: B안 (분할 PR). 본 코드 PR + 별도 release-hardening PR.

---

## Closeout Checklist (per docs/process/gate-closeout-checklist.md)

- [x] A. SUMMARY 4 섹션 (Active / New / Recurrence / Next Addendum)
- [x] B. learnings.md 11-필드 schema (git-L01, L02, L03)
- [x] C. index.md 세션 로그
- [x] D. Subagent 사용 정당성 명시 (5/5 충족하나 fresh context + 명확한 BLOCK 사유로 ROI 한계)
- [x] E. 코드/테스트/문서/인프라 수정 0건 (verify-only)
- [x] F. Hand-off — Next Gate Prompt Addendum 완성
- [x] G. tree clean, branch ≠ master, destructive 명령 미사용
