# Release-side Fix Session — CRIT-2/3/4 + Version Single Source + Docs

세션: `gate-release-fix-2026-05-18-002`
타입: **Release-blocker surgical fix** (런타임 로직 미변경)
브랜치: `claude/cool-bouman-70eb80`
직전: `gate-release-2026-05-18-001` (verify, 🔴 BLOCK)

## 판정
🟢 **release-side P0 3건 (CRIT-2/3/4) 모두 resolved. Version single source 도입. CHANGELOG Unreleased + README Deployment 섹션 추가. 다음 verify 에서 SHIP eligible 예상.**

| Before | After |
|--------|-------|
| 🔴 BLOCK — release.yml + runbooks + version 모두 미해결 | 🟢 모든 CRIT-2/3/4 resolved, 런타임 회귀 0건 |
| 183 pass, 2 skip | 183 pass, 2 skip (test 1건 시그니처 업데이트 surgical, 회귀 0) |

## 처리한 항목

### CRIT-2 — release.yml mutable refs → commit SHA pin

**위치**: `.github/workflows/release.yml`

5 액션 모두 `gh api` 로 검증한 SHA 로 pin:

| Action | Version | SHA |
|--------|---------|-----|
| `actions/checkout` | v4.2.2 | `11bd71901bbe5b1630ceea73d27597364c9af683` |
| `actions/setup-python` | v5.3.0 | `0b93645e9fea7318ecaed2b359559ac225c90a2b` |
| `actions/upload-artifact` | v4.4.3 | `b4b15b8c7c6ac21ea08fcf65892d2ee8f75cf882` |
| `actions/download-artifact` | v4.1.8 | `fa0a91b85d4f404e444e00e005971372dc801d16` |
| `pypa/gh-action-pypi-publish` | v1.12.4 | `7f25271a4aa483500f742f9492b2ab5648d61011` |

상단 주석에 SHA 갱신 절차 + Dependabot 권장 명시. mutable tag 사용 금지 경고.

### CRIT-3 — Tag push 자동 publish → smoke gate + environment approval

**위치**: `.github/workflows/release.yml`

`build-and-publish` 단일 job → **`build-and-smoke` + `publish` 두 job 분리**.

**`build-and-smoke` job** (`permissions: contents: read`, **id-token 없음**):
1. checkout (SHA-pinned)
2. Python 3.12 setup
3. `python -m build` (sdist + wheel)
4. 별도 venv 에 wheel install
5. Smoke import: `email_service`, `SmtpSender`, `MagicLinkNotifier`, `OTPNotifier`, `__version__` 존재 확인
6. **Tag-vs-pyproject 버전 매칭 검증**: `v0.4.1` tag → pyproject 도 `0.4.1` 이어야 fail 안 함
7. dist/ 를 artifact 로 upload (1일 retention)

**`publish` job** (`needs: build-and-smoke`, `environment: pypi`):
1. dist artifact download
2. PyPI publish via Trusted Publisher OIDC (`id-token: write` — 이 job 으로 격리)

**Manual approval**: `pypi` GitHub Environment 의 "Required reviewers" 설정 필수 (repo Settings → Environments → pypi). 본 PR 머지 후 maintainer 가 1회 설정. release.yml 상단 주석에 명시.

YAML 검증: `python yaml.safe_load` 통과. `publish.needs == "build-and-smoke"` 확인.

### CRIT-4 — `docs/runbooks/` 5건 작성

신규 디렉토리 `docs/runbooks/` + 5 runbook:

| File | 내용 |
|------|------|
| `smtp-outage.md` | SMTP provider 다운 대응. provider 상태 확인, rate limit 조정, backup SMTP 전환, 사후 분석 체크리스트, 알람 임계값 권장. |
| `webhook-outage.md` | webhook target 다운. "메일은 발송됨" 명시, message_id 식별 절차, DLQ 없음 사실 명시, SSRF false positive 처리. |
| `api-key-rotation.md` | 단일 키 한계 명시 + 다운타임 허용 옵션 A 절차 (5분), 듀얼키 옵션 B 는 multi-key 지원 후. 사전 준비 / smoke test / 롤백. |
| `pypi-yank-hotfix.md` | yank 절차 (publish 직후 vs 시간 경과). 핫픽스 publish Sprint 0-1 분리. 본 fix 의 build-and-smoke + manual approval 참조. |
| `smtp-disconnect-uncertain.md` | 신규 에러 코드 운영자 해석. 빈도별 결정 트리, caller 측 권장 (idempotency-key). 의도된 동작 — 버그 아님 명시. |

### Version single source

**위치**: `email_service/__init__.py` + `email_service/api.py:438`

**`__init__.py`** — `importlib.metadata` 기반 + fallback:
```python
try:
    from importlib.metadata import version as _pkg_version, PackageNotFoundError
    try:
        __version__ = _pkg_version("email-service")
    except PackageNotFoundError:
        __version__ = "0.0.0+dev"
except ImportError:
    __version__ = "0.0.0+dev"
```

**`api.py`** — 하드코딩 `"0.2.0"` 제거, `from email_service import __version__` + `FastAPI(version=__version__, ...)`.

**테스트 surgical update** (`tests/test_api.py:test_every_path_has_summary_and_tags`):
- 기존: `assert spec["info"]["version"] == "0.2.0"` (하드코딩)
- 신규: `assert spec["info"]["version"] == email_service.__version__` (동적 추적)
- 이유: `__version__` 이 install 환경 의존. CI 에서는 build 후 pyproject 의 `0.3.0` 매칭. 로컬 dev 에서 stale install (`0.1.0`) 이어도 둘이 일치하면 OK.

**release.yml 의 tag-vs-version 검증** 이 publish 시점에 pyproject ↔ tag 일치 강제 → 잘못된 version 으로 publish 차단.

### CHANGELOG `## [Unreleased]`

**위치**: `CHANGELOG.md` head

추가된 섹션 구조:
- Security (P0): 5건 (SSRF, size caps, rate limit, bounded backoff, post-DATA disconnect)
- Security (P1): 2건 (HTTP idempotency, HMAC V2 signature)
- Release pipeline: SHA pin + smoke gate + version single source
- Operational documentation: runbooks + README Deployment
- Known limitations (tracked): SMTP sync sleep, in-memory state, sub-attempt DNS window, Linux exotic IP 미검증

**Breaking changes 없음** 명시 — SDK caller 코드 변경 불요.

### README Deployment 섹션

**위치**: `README.md` `## Operations` 직전에 `## Deployment` 신규.

내용:
- **워커 수 (single vs multi)**: in-memory 상태 (rate limit / idempotency / per-key lock) 모두 per-process. 단일 워커 + sticky LB 권장. 멀티워커 시 Redis-backed 필요.
- **본문 크기 제한**: nginx `client_max_body_size 12m` 예시. FastAPI buffer 우선 동작 설명.
- **환경변수 reference 테이블**: 14 환경변수 전체. 본 release 의 신규 (`API_RATE_LIMIT_PER_MINUTE`, `API_IDEMPOTENCY_TTL_SECONDS`, `WEBHOOK_ALLOW_HOSTS`, `WEBHOOK_ALLOW_LOOPBACK`) 포함. `EMAIL_SERVICE_DEBUG` production 금지 경고.
- **Webhook V1 → V2 마이그레이션**: 수신자 측 3 step 가이드 + "V1 향후 major version 제거 예정" 공지.
- **Release 자동화**: tag push 자동 publish + **manual approval 필수** 명시 + 모든 액션 SHA pin + yank 영구 소진 경고. pypi-yank-hotfix runbook 링크.
- **운영 runbook 링크**: 5 runbook 직접 링크.

### Linux exotic IP 실측

명령: `docker run --rm python:3.12-slim python -c "import socket; print(socket.getaddrinfo('2130706433', None))"`
환경: Docker Desktop daemon **미실행** (이 세션의 host 환경 한계)
결과: **NOT VERIFIED** in this session.

CHANGELOG / README 에 미검증 사실 명시. Linux production 배포 전 1회 실측 권장. code-L13 active 유지.

## 변경 파일 요약

| File | 변경 |
|------|------|
| `.github/workflows/release.yml` | 단일 job → 2-job split (build-and-smoke + publish). 5 액션 SHA pin. 상단 주석 갱신. |
| `email_service/__init__.py` | `__version__` importlib.metadata 기반 + fallback. `__all__` 갱신. |
| `email_service/api.py` | `from email_service import __version__` import 추가. `FastAPI(version=__version__, ...)`. 하드코딩 `"0.2.0"` 제거. |
| `tests/test_api.py` | OpenAPI version assertion 동적 추적으로 surgical update. |
| `CHANGELOG.md` | `## [Unreleased]` 섹션 신규. |
| `README.md` | `## Deployment` 섹션 신규 (Operations 직전). |
| `docs/runbooks/smtp-outage.md` | 신규 |
| `docs/runbooks/webhook-outage.md` | 신규 |
| `docs/runbooks/api-key-rotation.md` | 신규 |
| `docs/runbooks/pypi-yank-hotfix.md` | 신규 |
| `docs/runbooks/smtp-disconnect-uncertain.md` | 신규 |

런타임 로직 변경 (`sender.py`, `webhooks.py`, `url_validation.py`, notifiers/metrics/logging): **0건**.

## 테스트 결과

```
Full suite: 183 passed, 2 skipped
Regression: 0건
release.yml YAML: syntax valid, jobs=[build-and-smoke, publish], publish.needs=build-and-smoke
__version__ resolution: importlib.metadata 동작 확인 (이 환경 stale install 로 0.1.0 반환, CI 에서는 pyproject 의 0.3.0)
```

## 남은 리스크 (release-gate 이후, 의도된 deferred)

| ID | 항목 | 분류 | 처리 시점 |
|----|------|------|----------|
| L-SEED-02 | SMTP sender sync sleep (31s budget) | P1 | 다음 small fix (Phase A retry cap) or v0.4.0 (Phase B async) |
| code-L13 | Linux exotic IP 미검증 | P1 | release 전 1회 Docker 실측 |
| code-L11/L14 | create_app 6 kwargs / AppDependencies refactor | P2 | 7번째 cross-cutting 도입 전 |
| code-L25/L27 | Lock dict 메모리 (idle TTL eviction) / Lock ordering 명시 | P2 | 별도 docs PR or v0.4.x |
| - | `requirements.lock` + pip-audit CI | P2 | 향후 minor 전 |

## 단일테넌트/단일워커 PR 가능 여부 — 변동

**Before this fix**: 🟡 코드 자체 안전, but PR description 에 "DO NOT push tag" 경고 필수.
**After this fix**: 🟢 PR 가능 + tag push 도 manual approval gate 가 차단 → safe. 단, **maintainer 가 `pypi` environment 의 Required reviewers 설정 후** publish 가능.

PR description 에 추가할 사항 (1줄):
> "Before first tag push: configure `pypi` GitHub Environment with Required reviewers (Settings → Environments → pypi)."

---

## Active Learnings Applied

직전 priors:
- **L-SEED-06/-07 (tag publish/mutable refs)**: **RESOLVED-By: gate-release-fix-2026-05-18-002** — smoke gate + 5 SHA pin.
- **L-SEED-08 (runbook 부재)**: **RESOLVED** — 5 runbook 작성.
- **code-L16 (V1 deprecation timeline)**: **부분 resolved** — CHANGELOG + README 에 명시. 정확한 major version 제거 timeline (v1.0?) 은 별도 미정. status: still active for explicit timeline.
- **code-L25 (lock dict 메모리)**: 부분 resolved — README 에 "in-memory state" 한계 명시. 코드 측 idle TTL 미구현, 별도 fix 대기.
- **code-L13 (Linux exotic IP)**: active (docker 환경 미가용). CHANGELOG/README 에 미검증 명시.
- **git-L01 (Code Gate GREEN ≠ Release ready)**: **VALIDATED** — 본 fix 가 정확히 git-L01 의 4 항목 (release.yml + runbooks + CHANGELOG + version-sync) 처리. learning 의 actionability 입증.
- **git-L02 (PR 머지 ≠ tag push)**: 부분 무력화 — manual approval gate 덕에 tag push 가 안전해짐. learning 의 적용 범위 좁아짐.
- **git-L03 (autosave commits)**: active — 본 PR 머지 시 squash 권장 (런타임에서 적용 어려움, PR 워크플로).
- **code-L09/L15 (validator + fixture 회귀)**: applied — test_api.py 의 version assertion 1건 surgical update 로 baseline 즉시 복구.

## New Learnings Captured

```yaml
ID: git-L04
Source: gate-release-fix-2026-05-18-002
Severity: P1
Mistake / Miss: GitHub Actions SHA 핀이 보안적으로 옳지만, 사람이 SHA 갱신을 수동 추적하면 누락된 보안 패치를 놓치기 쉽다. mutable tag 의 위험 (CRIT-2) 과 stale SHA 의 위험 (CVE 미적용) 사이 trade-off.
Root Cause: SHA 핀의 자체 동결성. 자동화 (Dependabot SHA-based update) 없으면 stale 진행.
Recurrence Trigger: workflow 의 다른 action 추가 시, 또는 6개월+ SHA 미갱신 시.
Prevention Rule: Dependabot config (`.github/dependabot.yml`) 에 GitHub Actions ecosystem 등록. SHA pin 자동 PR 받기. 또는 분기별 manual audit.
Next-Session Checklist Item: ".github/dependabot.yml 에 actions 등록되어 있는가? 6개월 이상 갱신 안 된 SHA 가 있는가?"
Applies To: .github/workflows/*.yml, .github/dependabot.yml
Owner Gate: git
Evidence: release.yml SHA pin 5건 도입 (이 세션) — 미래 갱신 메커니즘 없음.
Status: active
```

```yaml
ID: git-L05
Source: gate-release-fix-2026-05-18-002
Severity: P2
Mistake / Miss: `__version__` 을 importlib.metadata 로 단일화하니 dev 환경 (stale `pip install -e .`) 에서 잘못된 버전 반환. CI/build 에서는 정확히 동작하지만 로컬 dev 가 혼란.
Root Cause: importlib.metadata 가 install distribution 의 dist-info 를 읽음. editable install 후 pyproject version bump 하면 dist-info 안 갱신.
Recurrence Trigger: dev 머신 stale install, 또는 `pip install -e .` 후 pyproject version 변경.
Prevention Rule: dev 가이드에 "pyproject version 변경 후 `pip install -e . --force-reinstall` 또는 `pip install -e . --upgrade`" 명시. CI 는 fresh build 이므로 영향 없음.
Next-Session Checklist Item: "dev 환경에서 `__version__` 이 pyproject 와 일치하지 않으면 reinstall 실행."
Applies To: README dev 가이드, CONTRIBUTING
Owner Gate: git
Evidence: 이 세션 host 가 `0.1.0` 반환 (stale install) vs pyproject `0.3.0`.
Status: active
```

## Recurrence Risks

| ID | 본 fix 결과 | 다음 gate 관찰 포인트 |
|----|-------------|---------------------|
| L-SEED-06/-07/-08 | **RESOLVED** | 다음 release-gate 에서 retain 검증 |
| code-L16 (V1 deprecation) | 부분 resolved | 명확한 major version 제거 timeline 결정 시 fully resolved |
| code-L13 (Linux exotic IP) | active | docker 가용 환경에서 1회 실측 |
| code-L11/L14/L25/L27 | active deferred | 별도 docs PR 또는 v0.4.x |
| git-L01 | **VALIDATED** | 본 fix 의 actionability 입증, 미래 release-gate 재적용 |
| git-L02 | 부분 무력화 | manual approval 도입으로 위험 축소 |
| git-L03 | active | PR 머지 시 squash |
| **git-L04 (NEW P1)** | new | Dependabot config 추가 권장 (별도 docs PR) |
| **git-L05 (NEW P2)** | new | dev 가이드 보강 |

## Next Gate Prompt Addendum

> 다음 gate (release-gate verify 또는 PR 생성) prompt 에 그대로:
>
> ```
> RELEASE-SIDE STATE (post-fix):
> - CRIT-2 RESOLVED: all 5 GitHub Actions pinned to verified commit SHAs
> - CRIT-3 RESOLVED: build-and-smoke + tag-vs-version verify + publish
>   gated on pypi GitHub Environment (configure Required reviewers in
>   repo Settings → Environments → pypi BEFORE first publish)
> - CRIT-4 RESOLVED: 5 runbooks in docs/runbooks/
> - Version single source: importlib.metadata, FastAPI(version=__version__)
> - CHANGELOG: ## [Unreleased] with full P0/P1 + known limitations
> - README: ## Deployment with env vars table + V1 migration guide
>
> NOT YET DONE (deferred, not release blockers for single-tenant):
> - L-SEED-02 SMTP sender sync sleep — Phase A retry budget cap optional
> - code-L13 Linux exotic IP — run `docker run --rm python:3.12-slim
>   python -c "import socket; print(socket.getaddrinfo('2130706433', None))"`
>   before first Linux deploy
> - code-L25 lock dict idle TTL eviction — optional v0.4.x feature
> - git-L04 .github/dependabot.yml for SHA auto-updates — recommended
>
> Pre-PR maintainer checklist (one-time setup):
> 1. Repo Settings → Environments → Create `pypi`
> 2. Set Required reviewers (at least 1 person)
> 3. Configure PyPI Trusted Publisher (release workflow + pypi env)
> 4. (Optional) Add .github/dependabot.yml with github-actions ecosystem
>
> Per-release checklist (when ready to publish):
> 1. Bump pyproject version → commit → merge PR
> 2. git tag vX.Y.Z (must match pyproject)
> 3. git push origin vX.Y.Z
> 4. GitHub Actions: build-and-smoke runs first
>    - tag-vs-version check will fail if mismatch
> 5. After build-and-smoke passes, publish job pauses for manual approval
> 6. Required reviewer approves → publish proceeds
> ```

---

## Closeout Checklist

- [x] A. SUMMARY 4 섹션 (Active / New / Recurrence / Next Addendum)
- [x] B. learnings.md 11-필드 schema (git-L04, L05)
- [x] C. index.md 세션 로그
- [x] D. Subagent 사용 정당성 — 0건 호출. 이번 fix 는 명확한 surgical change 목록 (CRIT-2/3/4 + version + docs), single-flow 가 직접 가장 효율적. 정책 §a/b/c "단일 파일 작은 수정 / 명확한 P0 핫픽스 / 단순 정리" 에 해당 (5건 surgical fix).
- [x] E. 런타임 코드 미변경 (`sender.py` / `webhooks.py` / `url_validation.py` / notifiers / metrics / logging 0건). API 모듈만 version import 1줄 추가.
- [x] F. Hand-off — Next Gate Prompt Addendum + Per-release checklist 완성
- [x] G. tree clean (autosave), branch ≠ master, destructive 명령 미사용
