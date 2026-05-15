---
name: email-service-conventions
description: email-service 저장소 고유의 코딩/보안/테스트 규약. 이 패키지의 sender, notifier, FastAPI 라우트, 또는 SMTP 관련 코드를 작성·수정할 때 사용.
---

# email-service Conventions

이 저장소에서 코드를 추가/수정할 때 지켜야 할 프로젝트 고유 규칙.

## 1. 의존성 정책

- **라이브러리 코어는 표준 라이브러리만 사용.** `email_service.sender`, `email_service.notifiers`, `email_service.client` 는 외부 패키지를 import 하지 않는다 — `smtplib`, `email`, `html`, `typing` 등 표준 라이브러리만.
- **HTTP 모드 의존성은 extras 로 격리.** FastAPI / Pydantic / Uvicorn 은 `[http]` extras 에 있고 `email_service.api` 에서만 import. 라이브러리 모드 사용자가 설치하지 않아도 동작해야 한다.
- 새 외부 의존성 추가 전 — 표준 라이브러리로 가능한지 먼저 확인.

## 2. 보안 — 변경 시 즉시 회귀하기 쉬운 영역

- **CRLF 인젝션 차단을 우회하지 말 것.** `to`, `subject`, `from`, `cc`, `bcc` 에 `\r` / `\n` 검사가 sender 단과 Pydantic 단 양쪽에 있다. 한 쪽만 수정하면 회귀.
- **사용자 입력은 기본 HTML escape.** `MagicLinkNotifier`, `OTPNotifier`, `TemplateNotifier` 의 `user_name`, `token`, `code`, `context` 값은 `html.escape` 를 거친다. 새 Notifier 도 동일 규칙 적용.
- **API_KEY 비교는 상수 시간.** `email_service.api` 의 인증 헬퍼는 `hmac.compare_digest` 사용. `==` 로 바꾸지 않는다.
- **시크릿 로깅 금지.** `SMTP_PASSWORD`, `API_KEY`, 매직링크 토큰, OTP 코드는 로그/예외 메시지에 포함하지 않는다.

## 3. API 호환성

- `SmtpSender.send`, `Notifier.send`, FastAPI 의 `POST /send` 는 외부 호출자가 의존하는 공개 표면이다. 시그니처/리턴 타입을 깨는 변경은 README 와 `tests/` 양쪽을 동반 수정.
- `dry_run` 같은 안전 플래그는 **keyword-only** 로 유지 (positional 로 받지 않는다 — `a7a8c86` 회귀 방지).

## 4. 테스트

- 새 보안 가드 (헤더 인젝션, escape, 인증) 를 추가하면 양성/음성 테스트를 함께 추가. `tests/test_email_service.py`, `tests/test_api.py` 의 기존 패턴을 따른다.
- SMTP 호출은 실제 네트워크를 치지 않는다 — `unittest.mock` 으로 `smtplib.SMTP` 를 가짜로 만든다.

## 5. Fail-fast 기동

HTTP 모드는 필수 환경변수(`SMTP_HOST`, `API_KEY` 등) 가 비면 부팅에서 `RuntimeError` 로 실패해야 한다. 런타임에 silent default 로 폴백하지 않는다.

## 6. 문서 동기화

공개 API 시그니처, 환경변수 이름, 기본 동작이 바뀌면 같은 PR 에서 `README.md` 의 해당 섹션을 업데이트한다. `SPEC.md` / `DONE.md` / `EVAL.md` 는 파이프라인이 갱신하므로 손대지 않는다.
