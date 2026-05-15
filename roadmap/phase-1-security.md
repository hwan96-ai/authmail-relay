# Phase 1 — Security & Correctness

**목표:** 보안·신뢰성 결함을 즉시 차단. 공개 API 시그니처 변경 없음 → 호출자 영향 0.

**소요 (CC):** ~1시간 | **위험:** 낮음 | **외부 의존:** 없음

## 진입 조건
- 현재 브랜치에서 `python -m pytest tests/ -q` 통과 확인.
- master 와 동기 (rebase 또는 별도 worktree).

## 작업 (P0 → P1 → P2 순)

### P0 — 즉시 수정 (보안 직접 영향)

- [ ] **1.1 의존성 핀 + lock**
  - 파일: [pyproject.toml](../pyproject.toml)
  - 변경: `fastapi>=0.100` → `fastapi>=0.115,<1`, `uvicorn>=0.23` → `uvicorn>=0.30,<1`, `httpx>=0.25` → `httpx>=0.27,<1`
  - 추가: `requirements.lock` 또는 `uv lock` (uv 도입 시) 으로 트랜지티브 deps 고정
  - 검증: `pip install -e ".[dev,http]"` 통과 + 기존 테스트 통과
  - 출처: [reports/04-security-audit.md](../reports/04-security-audit.md) MEDIUM #1, /office-hours, /devex
  - 회귀 테스트: `pyproject.toml` 의 `dependencies` 라인이 정확히 핀 형식인지 lint 단계 추가

- [ ] **1.2 STARTTLS 명시적 SSL context + 미지원 시 명시 실패**
  - 파일: [email_service/sender.py:66-71](../email_service/sender.py)
  - 변경: `import ssl` 추가. `server.starttls()` → `server.starttls(context=ssl.create_default_context())`. starttls 호출 전 `server.has_extn("starttls")` 검사 — 미지원이면 `RuntimeError` 또는 명시 로그 후 False
  - 검증: Mailpit (STARTTLS 미지원) 환경에서 use_tls=True 시 명시 실패하는지 확인
  - 출처: [reports/03-investigation.md](../reports/03-investigation.md) H2 P2
  - 회귀 테스트 (필수, 2건):
    - STRIPTLS 시나리오: `has_extn` 이 False 반환하도록 mock → `sendmail` 이 호출되지 않음을 assert
    - SSL context 타입 assert: `starttls` 가 `context=` 인자로 `ssl.SSLContext` 인스턴스를 받는지 확인

- [ ] **1.3 docker-compose.dev.yml 의 하드코딩 API_KEY 제거**
  - 파일: [docker-compose.dev.yml](../docker-compose.dev.yml)
  - 변경: `API_KEY: dev-secret` → `API_KEY: ${API_KEY:?Set API_KEY in .env or env}` (필수) 또는 `${API_KEY:-dev-only-do-not-use-in-prod}` (기본 + 경고)
  - 추가: [.env.example](../.env.example) 에 `API_KEY=` 라인 + "openssl rand -hex 32 로 생성" 주석
  - 검증: `docker compose -f docker-compose.dev.yml config` 가 API_KEY 비어 있으면 에러
  - 출처: [reports/04-security-audit.md](../reports/04-security-audit.md) LOW #1

### P1 — 결함 가능성 (Defense-in-depth)

- [ ] **1.4 SMTP_FROM 부팅 시 CRLF 검증**
  - 파일: [email_service/api.py:18-22, 102](../email_service/api.py)
  - 변경: `_build_sender_from_env` 에서 `from_addr` 가 set 된 경우 `_no_crlf()` 통과 시킨 후 SmtpConfig 에 전달. 부팅에서 즉시 RuntimeError.
  - 출처: [reports/01-qa-report.md](../reports/01-qa-report.md) MEDIUM #1
  - 회귀 테스트: `SMTP_FROM="foo\r\nBcc: evil@x"` 환경에서 `create_app()` 호출 시 RuntimeError

- [ ] **1.5 `/send/magic-link` dry_run 우선순위 수정**
  - 파일: [email_service/api.py:176-182](../email_service/api.py)
  - 현재: `magic_link is None` 검사 → 503 (dry_run 전에 평가됨). dry_run 으로 페이로드 검증 불가.
  - 변경: dry_run 단축 → magic_link None 검사 순서로 재배치. dry_run=true 일 때는 endpoint 가 구성되지 않아도 페이로드 검증만 성공.
  - 출처: [reports/02-pr-review.md](../reports/02-pr-review.md) MEDIUM #1
  - 회귀 테스트: MAGIC_LINK_BASE_URL 미설정 환경에서 `X-Dry-Run: true` 로 `/send/magic-link` 호출 → 200 + `dry_run=true`

### P2 — 문서화 (코드 변경 없음)

- [ ] **1.6 README 에 매직링크 토큰 엔트로피 책임 명시**
  - 파일: [README.md](../README.md)
  - 변경: "보안 모델" 섹션 추가 — "토큰은 호출자가 `secrets.token_urlsafe(32)` 이상 엔트로피로 생성해야 한다. 본 패키지는 토큰을 검증/저장하지 않는다."
  - 출처: [reports/04-security-audit.md](../reports/04-security-audit.md) MEDIUM #2

## 완료 정의

- [ ] P0 3건 완료
- [ ] P1 2건 완료 (1.4, 1.5)
- [ ] P2 1건 완료 (README)
- [ ] 회귀 테스트 3건 추가 (1.2 ×2, 1.4 ×1, 1.5 ×1 → 총 4건)
- [ ] `pytest tests/ -q` 그린
- [ ] `git diff --stat` 검토 — 파일 수 ≤ 6
- [ ] 커밋 메시지: `phase-1: security & correctness hardening`

## 출구 조건 (다음 단계 진입 전)

- 1.2 회귀 테스트가 그린 — STARTTLS 가드 검증됨
- 1.1 의 핀이 적용된 후 `pip-audit` 결과 없음 (선택)
