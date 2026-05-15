# CLAUDE.md

이 저장소(`email-service`)에서 작업할 때 Claude Code가 따라야 할 지침의 진입점이다. 상세 규칙은 `skills/<skill-name>/SKILL.md` 로 분산되어 있다.

## 프로젝트 한 줄 요약

SMTP 기반 HTML 이메일 발송 패키지 — Python 라이브러리 + FastAPI HTTP 서비스 두 가지 모드. 자세한 사용법은 [README.md](README.md) 참조.

## 적용 스킬

다음 스킬은 이 저장소 작업에 항상 적용된다. 코드 작성/리뷰/리팩토링 전에 해당 SKILL.md 를 따른다.

- [skills/karpathy-guidelines/SKILL.md](skills/karpathy-guidelines/SKILL.md) — LLM 코딩 실수를 줄이는 4가지 행동 지침 (Think Before Coding / Simplicity First / Surgical Changes / Goal-Driven Execution).
- [skills/email-service-conventions/SKILL.md](skills/email-service-conventions/SKILL.md) — 이 프로젝트 고유의 코딩 규약 (보안, 의존성, 테스트, API 호환성).

## 트레이드오프

이 지침은 **속도보다 신중함**에 가중치를 둔다. 사소한 작업에서는 판단으로 생략 가능.
