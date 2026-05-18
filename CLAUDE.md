# CLAUDE.md

이 저장소(`email-service`)에서 작업할 때 Claude Code가 따라야 할 지침의 진입점이다. 상세 규칙은 `skills/<skill-name>/SKILL.md` 로 분산되어 있다.

## 프로젝트 한 줄 요약

SMTP 기반 HTML 이메일 발송 패키지 — Python 라이브러리 + FastAPI HTTP 서비스 두 가지 모드. 자세한 사용법은 [README.md](README.md) 참조.

## 적용 스킬

다음 스킬은 이 저장소 작업에 항상 적용된다. 코드 작성/리뷰/리팩토링 전에 해당 SKILL.md 를 따른다.

- [skills/karpathy-guidelines/SKILL.md](skills/karpathy-guidelines/SKILL.md) — LLM 코딩 실수를 줄이는 4가지 행동 지침 (Think Before Coding / Simplicity First / Surgical Changes / Goal-Driven Execution).
- [skills/email-service-conventions/SKILL.md](skills/email-service-conventions/SKILL.md) — 이 프로젝트 고유의 코딩 규약 (보안, 의존성, 테스트, API 호환성).

## Gate 워크플로 (`/hwan-refactor-*`)

모든 `/hwan-refactor-idea | -code | -design | -git` gate 는 **시작 즉시** [.claude/GATE-ADDENDUM.md](.claude/GATE-ADDENDUM.md) 를 읽고 그 정책을 본인의 Phase 0/마지막 Phase 위에 얹는다. 핵심은:

1. **시작 시**: 본인 owner 의 `.claude/learnings/<gate>/learnings.md` + `.claude/learnings/index.md` 의 active learning 을 priors 로 적용. 같은 ID 재발 시 severity 한 단계 상승.
2. **실행 중**: subagent 는 [docs/process/subagent-policy.md](docs/process/subagent-policy.md) 의 사용 조건 2개 이상 충족 시에만 호출.
3. **종료 시 — Compound Learning Closure (필수)**: SUMMARY.md 마지막에 4 섹션 (Active Learnings Applied / New Learnings Captured / Recurrence Risks / Next Gate Prompt Addendum) 추가, learnings.md + index.md 갱신.
4. **종료 검증**: [docs/process/gate-closeout-checklist.md](docs/process/gate-closeout-checklist.md) 의 A~G 모두 통과해야 gate 완료.

세부 schema/절차: [docs/process/compound-learning-loop.md](docs/process/compound-learning-loop.md).

Gate 철학 보존:
- `/hwan-refactor-code` 는 코드 자동 수정 금지. audit + plan only.
- `/hwan-refactor-git` 은 PR/머지/배포 자동 실행 금지. 명시 승인 후만.

## 트레이드오프

이 지침은 **속도보다 신중함**에 가중치를 둔다. 사소한 작업에서는 판단으로 생략 가능. 단, gate 의 Compound Learning Closure 와 subagent ROI 검증은 생략 금지 (관성 방지 장치).
