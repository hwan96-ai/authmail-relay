# Runbook: PyPI Yank & Hotfix Release

## 컨텍스트

PyPI 는 **deletion 불가, yank 만 가능**. 잘못된 버전 publish 시:
- `pip install hwan-email-service` (no version) → yanked 버전 제외
- `pip install hwan-email-service==X.Y.Z` (exact) → yanked 버전 그대로 설치 가능
- 버전 번호는 **영구 소진** — 같은 번호 재사용 절대 불가

따라서 잘못된 버전은 yank + 핫픽스 버전 publish 2-step.

## 시나리오

### A. publish 직후 발견 (T+0 ~ T+5min)

1. **즉시 yank**:
   - PyPI 웹 UI: 프로젝트 → "Manage" → "Releases" → 해당 버전 → "Yank"
   - 또는 `pypi-cli` (configured 시):
     ```
     pypi yank hwan-email-service X.Y.Z --reason "<reason>"
     ```

2. **caller 영향 평가**:
   - 메트릭: `pip install hwan-email-service==X.Y.Z` 시도 횟수 (PyPI Stats 통해)
   - caller 시스템들 / Slack 공지

3. **다음 핫픽스 버전 결정**:
   - 잘못된 게 `0.4.0` → `0.4.1` (혹은 BREAKING 다시 정상화 시 `0.5.0`)

### B. publish 후 시간 경과 (T+1h+)

1. yank + 위 절차 + **CHANGELOG 에 yanked 명시**:
   ```markdown
   ## [0.4.0] - YANKED 2026-MM-DD

   > **YANKED**: This version was yanked due to <reason>. Use 0.4.1 or
   > later. Reinstall: `pip install --upgrade hwan-email-service`.
   ```

2. 이미 설치된 caller 들에게 마이그레이션 가이드 발송.

## 핫픽스 publish 절차

### Sprint 0 — bugfix 작성

1. main 에서 hotfix 브랜치 분기:
   ```
   git checkout master
   git pull
   git checkout -b hotfix/yank-0.4.0
   ```

2. bugfix 적용. 코드 품질 검토(code quality review) 통과 확인.

3. version bump:
   - `pyproject.toml`: `version = "0.4.1"`
   - CHANGELOG: `## [0.4.1] - YYYY-MM-DD` 섹션 추가

4. PR + 머지 (master).

### Sprint 1 — Release

5. 릴리스 준비 검토(release readiness review) 통과 확인.

6. **새 tag push**:
   ```
   git checkout master
   git pull
   git tag v0.4.1
   git push origin v0.4.1
   ```

7. GitHub Actions `release` workflow 발동:
   - `build-and-smoke` job: build + install + version 검증 (tag ↔ pyproject 일치)
   - `publish` job: `pypi` environment 의 required reviewers 가 manual approve 후 publish

8. **manual approve**: 권한자가 GitHub Actions 페이지에서 "Approve" 클릭. 이게 CRIT-3 mitigation 의 핵심.

9. PyPI 페이지 확인: `https://pypi.org/project/hwan-email-service/0.4.1/`.

10. smoke install verify:
    ```
    pip install hwan-email-service==0.4.1
    python -c "import email_service; print(email_service.__version__)"
    ```

## 롤백 (핫픽스도 실패한 경우)

- 0.4.1 도 yank → 0.4.2 핫픽스 (위 절차 반복).
- caller 들은 0.3.x 등 안전한 이전 버전 핀 권장.

## 사후 분석 체크리스트

- [ ] 왜 publish 전 잡지 못했나? Code Gate / Release Gate 누락 항목?
- [ ] smoke gate (`build-and-smoke` job) 가 이 bug 를 잡을 수 있었나?
- [ ] required reviewers approve 가 너무 빨랐나? 체크리스트 강화?
- [ ] caller 시스템 영향 측정 (yank 후 며칠간 trace)
- [ ] CHANGELOG yanked 표기 확인

## 사전 예방 (가장 중요)

- **Code Gate VERIFIED 후만 release branch 진입**.
- **Release Gate BLOCK 시 무조건 tag push 금지**.
- `build-and-smoke` job 의 tag-vs-version 검증 통과 확인.
- `pypi` environment 의 required reviewers 가 설정되어 있는지 매 release 전 확인.

