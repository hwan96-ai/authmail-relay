# Phase 2 — Developer Experience

**목표:** 구조화된 에러 응답, CHANGELOG/semver, PyPI 배포로 DX 점수 4.5 → 7 으로 끌어올림.

**소요 (CC):** ~2시간 | **위험:** 중간 (공개 API 변경, breaking) | **외부 의존:** PyPI 계정

## 진입 조건

- Phase 1 완료
- 새 메이저 버전 (`0.2.0`) 으로 브레이킹 체인지 허용 합의

## 핵심 결정

**`SmtpSender.send` 의 반환 타입을 `bool` → `SendResult` dataclass 로 변경.** 호출자의 코드를 깨므로 메이저 버전을 0.2.0 으로 올린다.

```python
@dataclass(frozen=True)
class SendResult:
    sent: bool
    error_code: str | None = None  # "smtp_auth_failed" | "recipient_refused" | "crlf_in_header" | "smtp_timeout" | "smtp_connection" | "template_not_configured"
    error_message: str | None = None
    refused: list[str] | None = None  # 부분 거부 시 거부된 수신자
    message_id: str | None = None
```

`bool(result)` 가 기존 의도와 동일하게 작동하도록 `__bool__` 정의.

## 작업

### P0 — 구조화 에러 (breaking)

- [ ] **2.1 `SendResult` dataclass 도입**
  - 파일: [email_service/sender.py](../email_service/sender.py) — 새 `SendResult` 정의 + `send()` 반환 타입 변경
  - 파일: [email_service/notifiers.py](../email_service/notifiers.py) — `Notifier.send` ABC 시그니처 + 모든 서브클래스 반환 타입 변경
  - 파일: [email_service/api.py:163,185,201](../email_service/api.py) — `if not ok:` → `if not result.sent: HTTPException(502, detail={"error_code": result.error_code, "message": result.error_message})`
  - 검증: `bool(SendResult(sent=True)) == True` 보장 (`__bool__` 메서드)
  - 출처: [reports/10-devex-review.md](../reports/10-devex-review.md) Pass 3, /qa, /eng
  - 테스트: 각 error_code 분기마다 단위 테스트

- [ ] **2.2 FastAPI 응답 모델에 error 필드 명시**
  - 파일: [email_service/api.py:76-79](../email_service/api.py)
  - 변경: `SendResult` Pydantic 모델에 `error_code: str | None`, `error_message: str | None` 필드 추가. `responses={502: {"model": SendResult}}` 라우트 데코레이터에 추가.
  - 출처: [reports/09-design-review.md](../reports/09-design-review.md) Surface B
  - 테스트: 422/502 응답 스키마 검증

- [ ] **2.3 `EmailServiceClient` 클라이언트도 SendResult 반환**
  - 파일: [email_service/client.py](../email_service/client.py)
  - 변경: `_post` 반환 타입을 `dict[str, Any]` → `SendResult` 로 변경. 4xx/5xx 에서도 `raise_for_status()` 대신 응답 body 의 error_code 를 SendResult 로 래핑.
  - **결정 필요:** 4xx/5xx 에서 raise vs 반환? — `raise_for_status` 유지하되 `ResponseError` 예외에 `error_code` 속성 부여 (호환성 보존).

### P1 — 버전·배포

- [ ] **2.4 CHANGELOG.md 도입 + semver 채택**
  - 파일: [CHANGELOG.md](../CHANGELOG.md) (신규)
  - 포맷: [Keep a Changelog](https://keepachangelog.com/) 스타일. 첫 엔트리는 `0.2.0` (이번 phase) + retroactive `0.1.0`.
  - [pyproject.toml](../pyproject.toml) version 0.1.0 → 0.2.0
  - 출처: [reports/10-devex-review.md](../reports/10-devex-review.md) Pass 5, /office-hours

- [ ] **2.5 PyPI 배포 워크플로**
  - 파일: `.github/workflows/release.yml` (신규)
  - 변경: 태그 푸시 → `python -m build && twine upload`. PyPI Trusted Publisher 설정.
  - README 의 `pip install git+...` → `pip install email-service` 로 변경
  - 출처: [reports/10-devex-review.md](../reports/10-devex-review.md) Pass 1 (Distribution)
  - 게이트: PyPI 프로젝트 이름 등록 + Trusted Publisher 사전 설정 필요

### P2 — Magical Moment

- [ ] **2.6 `python -m email_service test --to <addr>` CLI**
  - 파일: [email_service/__main__.py](../email_service/__main__.py) (또는 신규 CLI 모듈)
  - 변경: argparse 로 `serve` (현재 동작) 와 `test` 서브커맨드 분기. `test --to me@x.com` 은 환경변수로 SmtpSender 구성 후 즉시 hello-world 발송.
  - README 에 "30초 안에 첫 메일" 섹션 추가.
  - 출처: [reports/10-devex-review.md](../reports/10-devex-review.md) Step 0D Magical Moment
  - 테스트: subprocess 로 CLI 호출 → exit code 0 검증

## 완료 정의

- [ ] P0 3건 완료
- [ ] P1 2건 완료
- [ ] P2 1건 완료
- [ ] CHANGELOG 에 모든 변경사항 기록
- [ ] 마이그레이션 가이드: README 또는 CHANGELOG 에 "0.1.x → 0.2.0" 섹션 (bool → SendResult 변환 예시)
- [ ] PyPI 에 0.2.0 게시 (P1 게이트 통과 시)
- [ ] 커밋: `phase-2: structured errors + semver release`

## 출구 조건

- `pip install email-service==0.2.0` 가 PyPI 에서 동작
- README 의 quickstart 코드가 그대로 실행됨
- 4xx/502 응답에 `error_code` 가 존재하고 OpenAPI 스키마에 반영됨
