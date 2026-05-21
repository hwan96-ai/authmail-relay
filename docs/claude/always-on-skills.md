# Always-On Skills

## When to use this

이 저장소에서 코드 작성/리뷰/리팩토링을 하기 전에 사용한다. 요청이 명확히 비코드 문서 작업에만 한정되지 않는 한 항상 적용한다.

## 필수 스킬

코드 작업 전에 다음 skill 파일을 읽고 따른다:

- [karpathy-guidelines](../../skills/karpathy-guidelines/SKILL.md) — LLM 코딩 실수를 줄이는 행동 지침: Think Before Coding, Simplicity First, Surgical Changes, Goal-Driven Execution.
- [email-service-conventions](../../skills/email-service-conventions/SKILL.md) — 이 프로젝트 고유의 보안, 의존성, 테스트, API 호환성 규칙.

## 실무 읽기 순서

1. 먼저 [karpathy-guidelines](../../skills/karpathy-guidelines/SKILL.md) 를 읽고 작업 자세를 정한다.
2. `email_service/`, `tests/`, API 동작, SMTP 동작, 패키지 설정을 건드리기 전에 [email-service-conventions](../../skills/email-service-conventions/SKILL.md) 를 읽는다.

문서 전용 변경에서도 Karpathy 지침의 surgical-change 와 goal-driven 원칙은 적용한다.
