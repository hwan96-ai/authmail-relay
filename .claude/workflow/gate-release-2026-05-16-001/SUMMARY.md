# Release Gate 검증 결과 — email-service

세션: `gate-release-2026-05-16-001`
대상: 현재 `master` 상태 (v0.3.0), 다음 릴리스 준비도 검증
브랜치 상태: `claude/cool-bouman-70eb80` == `origin/master` (배포할 신규 커밋 0개)
연계 세션: 직전 Code Gate `gate-code-2026-05-16-001` (P0×5 미해결)

## 배포 판정
🔴 **BLOCK — 다음 릴리스 (v0.3.1/v0.4.0) 배포 불가**

3개 audit 모두 BLOCK 권장. 차단 요인 카테고리:
- **보안**: Code Gate P0 5건 미해결 + 새로운 P0 1건 (CI 액션 mutable refs)
- **운영**: 롤백 절차 부재 (PyPI는 yank만 가능, 재배포 1회 한정)
- **문서**: SMTP/webhook 장애 runbook 0건, error code 레퍼런스 부재

---

## 🔴 배포 차단 항목 (Critical)

### CRIT-1. [Code Gate P0 누적] 5건 미해결
프로덕션 보안/안정성 P0 5건이 v0.3.0에 그대로 존재. 다음 릴리스 전 모두 해결 필수:
- webhook_url SSRF (api.py:51, webhooks.py:33-65)
- html_body/subject `max_length` 없음 → OOM (api.py:51)
- `/send*` 레이트 리밋 없음 (api.py:158-161)
- BackgroundTasks + 동기 `time.sleep` → threadpool 고갈 (api.py:286, webhooks.py:33-95)
- SMTP post-DATA disconnect 재시도 → 수신자 중복 발송 (sender.py:225-291)

### CRIT-2. [cso, adversarial] CI 액션 mutable refs + `id-token: write`
- **위치**: `.github/workflows/release.yml`
- **취약점**: `actions/checkout@v4`, `pypa/gh-action-pypi-publish@release/v1` 모두 mutable tag. Trusted Publisher OIDC가 정확히 설정되어 있어 한 액션의 upstream 침해 = 우리 PyPI 이름으로 악성 wheel 배포.
- **수정**: 모든 액션을 commit SHA로 핀 (`actions/checkout@b4ffde6...`), Dependabot으로 SHA 핀 업데이트만 받기.

### CRIT-3. [adversarial] PyPI 배포 = 일방향, 스모크 게이트 없음
- **위치**: `.github/workflows/release.yml` (`on: push: tags`)
- **문제**: 태그 push 즉시 PyPI publish. 빌드 후 스모크 테스트/수동 승인 없음. 잘못된 0.3.1 → yank만 가능, 0.3.1 이름은 영구 소진. 핫픽스로 0.3.2 강제.
- **수정**: 
  - `environment: pypi`에 `required_reviewers` 추가
  - publish 전 install + smoke test job 추가
  - 또는 GitHub Release 생성을 트리거로 변경 (tag만으론 발행 안 됨)

### CRIT-4. [docs-ops] 장애 runbook 0건
- **위치**: README / docs/
- **누락**: SMTP 다운 대응, webhook 타겟 다운 대응, API_KEY 무중단 회전, PyPI yank/hotfix 절차, in-flight email 손실 대응.
- **수정**: 최소 `docs/runbooks/` 디렉토리 + 5개 runbook (각 시나리오별 명령어 수준).

---

## 통합 이슈 리스트 (신규 발견, Code Gate 외)

### P0 — 차단

| ID | 출처 | 위치 | 문제 | 수정 방향 |
|----|------|------|------|----------|
| R-1 | cso, adv | release.yml | mutable action refs + OIDC publish 권한 | SHA 핀 |
| R-2 | adv | release.yml | tag push = 즉시 PyPI publish, 스모크 X | review gate 추가 |
| R-3 | docs-ops | README/docs | SMTP outage / webhook outage runbook 부재 | 5 runbook 작성 |
| R-4 | docs-ops | README/docs | in-flight email 손실 보장 미명시 | "Known Limitations" 섹션 |
| R-5 | docs-ops | README/docs | webhook 미배달 시 데이터 손실 — DLQ 0 | 아키텍처 한계 명시 + 향후 DLQ 약속 |

### P1 — 출시 후 24h 내 사고 가능

| ID | 출처 | 위치 | 문제 | 수정 방향 |
|----|------|------|------|----------|
| R-6 | cso | sender.py:311-312 | `EMAIL_SERVICE_DEBUG=1`이 base64 SMTP password를 stderr 출력 | prod 환경 감지 시 거부 + 시작 시 loud warning + redact filter |
| R-7 | cso | logging_config.py:40-42 | `hash_recipient` salt 없는 SHA-256 32-bit prefix → 수신자 식별 가능 | per-deployment random salt 환경변수 + bcrypt/hmac-based |
| R-8 | cso | pyproject.toml | `requirements.lock` 없음 + 상한선 느슨 (`prometheus-client`, `python-json-logger` no upper) | `uv lock` or `pip-compile` + CI에 `pip-audit` 잡 |
| R-9 | cso | api.py:172 | OpenAPI version `"0.2.0"`, pyproject `0.3.0` — semver 거짓말 | `__version__` 단일 소스 |
| R-10 | cso | api.py:161 | 단일 공유 API_KEY — 회전 시 무중단 불가, 다중 통합 시 모두 같은 키 | 다중 키 + per-key quota (향후) — 우선 회전 절차 문서화 |
| R-11 | adv | metrics.py | uvicorn workers ≥2 시 Prometheus 단일 워커 데이터만 노출 | `PROMETHEUS_MULTIPROC_DIR` 설정 + multiprocess collector |
| R-12 | adv | api.py:271-289 | BackgroundTasks SIGTERM drain 없음 → 배포마다 webhook 손실 | lifespan + grace period |
| R-13 | docs-ops | README | API_KEY 회전 절차 부재 (R-10과 짝) | 단계별 runbook (dual-auth 기간) |
| R-14 | docs-ops | README | error code 의미·재시도 정책 단일 표 부재 | `ERR_SMTP_AUTH` 등 표 추가 |
| R-15 | cso, adv | webhooks.py:51 | HMAC에 timestamp 없음 → replay attack 가능 (OTP에 치명) | `X-Webhook-Timestamp` 헤더 + 5분 window |

### P2 — 일주일 내 발견될 운영 이슈

- R-16 [adv] `/metrics`가 기본 미인증 노출 — 발송 볼륨 유출 가능 (api.py:201-209)
- R-17 [adv] Dockerfile 미상의 USER (root 추정), HEALTHCHECK 없음, 단일 stage
- R-18 [adv] docker-compose `restart: unless-stopped` + on-failure 캡 없음 → boot crashloop 마스킹
- R-19 [docs-ops] 환경변수 4곳 산재, 통합 reference table 없음
- R-20 [docs-ops] alarm 임계값 가이드 (예: `email_send_failed_total` rate >1/min) 없음
- R-21 [docs-ops] async client 사용 예 부족
- R-22 [docs-ops] i18n 안내 부재 (영어 README 또는 한국어 README 위치 명시)
- R-23 [cso] SMTP CRLF 차단 확인됨 (subject/to/cc/bcc 모두 OK) — 단 `user_name`/from display 미확인 → P3로 강등
- R-24 [adv] SMTP 서킷 브레이커 없음 → provider outage 시 전체 cascade

### P3 — 참고

- R-25 [docs-ops] CHANGELOG `## [Unreleased]` 섹션 부재 (운영 관습)
- R-26 [docs-ops] README "30초 안에 시작" 라벨 과장 (실제 .env 작성 포함 시 3-5분)
- R-27 [cso] `user_name` 필드 CRLF 검증 미확인

---

## 영역별 결과 요약

### 🔒 보안 (`/cso` 대체 cso audit)
- **새 발견**: 5건 (CI 액션 mutable, debug password leak, hash_recipient 식별 가능, lockfile 부재, semver 불일치)
- **OWASP 매핑 확인**: A02 (HMAC replay), A05 (default misconfig 일부), A08 (supply chain), A09 (PII redaction), A10 (SSRF) — A03 SMTP injection은 차단됨 (good)
- **TLS**: `httpx` `verify=True` default OK, `ssl.create_default_context()` OK
- **인증**: `hmac.compare_digest` 사용 — constant-time OK
- **supply_chain_risk_score**: **8/10** (높음)
- **ship_recommendation**: **BLOCK**

### ⚔️ Adversarial (배포 후 운영)
- **새 P0**: 3건 (CI mutable refs, PyPI 일방향, in-flight email 손실 정책 없음)
- **새 P1**: 6건 (API_KEY 회전, Prometheus multiprocess, debug leak, SIGTERM drain, lockfile, SMTP 서킷)
- **rollback_plan_completeness**: **2/10**
- **runbook 부재**: 12개 (PyPI rollback, API_KEY rotation, SMTP outage 등)
- **ship_recommendation**: **BLOCK**

### 📝 문서/운영
- **operational_readiness_score**: **4/10**
- **P0 doc 부재**: 3건 (SMTP outage runbook, webhook 미배달 정책, in-flight 손실 명시)
- **외부 도입 차단 갭 top 5**:
  1. Error code 레퍼런스 표 부재
  2. Known Limitations 섹션 부재
  3. 장애 runbook 부재
  4. API_KEY 회전 / PyPI rollback 절차 부재
  5. 환경변수 통합 표 부재

### 🧪 테스트/성능
- 본 Gate에서는 별도 실행 안 함 (Code Gate에서 baseline 124 pass 확인)
- 추가 권장: `bmad-qa-generate-e2e-tests` 후속 세션에서 R-3/R-5 시나리오 (SMTP outage chaos test)

---

## 다음 단계 (해결 순서)

### Sprint 1 — 보안/배포 인프라 (1주)
1. **CRIT-1 / Code Gate P0 5건 해결** → Code Gate 재실행하여 GREEN 확인
2. **CRIT-2 / R-1** release.yml 액션 SHA 핀
3. **CRIT-3 / R-2** PyPI publish 스모크 게이트 + 수동 승인 게이트
4. **R-6** EMAIL_SERVICE_DEBUG 프로덕션 가드
5. **R-8** `requirements.lock` 생성 + CI `pip-audit`
6. **R-9** `__version__` 단일 소스

### Sprint 2 — 운영 문서 (3-5일)
7. **CRIT-4 / R-3, R-4, R-5, R-13, R-14** 5 runbook + Known Limitations + Error Code 표 작성
8. **R-25, R-26** CHANGELOG Unreleased 섹션 + README 라벨 정직화

### Sprint 3 — 운영 안정성 (1주)
9. **R-7** hash_recipient salt
10. **R-11** Prometheus multiprocess
11. **R-12** BackgroundTasks SIGTERM drain
12. **R-15** webhook HMAC timestamp + replay 방어
13. **R-24** SMTP 서킷 브레이커 (단순 구현)

### 재검증
- Sprint 1 후: `/hwan-refactor-code` 재실행 → P0 0건 확인
- Sprint 2 후: `/hwan-refactor-git --quick` → docs 갭 해소 확인
- Sprint 3 후: `/hwan-refactor-git` 전체 → SHIP 판정 받기
- 그 후에만 tag push.

---

## 산출물

- [audit/cso.md](audit/cso.md) — CSO 보안 감사 (15 findings)
- [audit/adversarial.md](audit/adversarial.md) — SRE 공격 시나리오 (17 findings)
- [audit/docs-ops.md](audit/docs-ops.md) — 문서/운영 준비도 (21 findings)
- [SUMMARY.md](SUMMARY.md) — 본 문서
- Code Gate 산출물: `../gate-code-2026-05-16-001/SUMMARY.md` (P0×5 미해결)

## PR/배포 가이드

⛔ **현재 상태에서 tag push 금지.** 배포 자동화가 일방향이며, Sprint 1 미완 상태로 publish 시 0.3.1 이름이 영구 소진됨.

권장 워크플로:
1. 본 SUMMARY를 GitHub Issue 또는 Linear ticket으로 변환
2. Sprint 1 → feature branch → PR (Code Gate 재실행) → merge
3. Sprint 2/3도 동일 패턴
4. 모든 Sprint 완료 + 본 Release Gate 재실행 SHIP 판정 후 `v0.4.0` tag push
