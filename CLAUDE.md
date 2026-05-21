# CLAUDE.md

이 저장소(`email-service`)에서 Claude Code가 따라야 할 지침의 짧은 진입점이다. 자세한 지침은 `docs/claude/` 의 역할/주제별 문서로 분산한다.

## 읽기 순서

1. [Project Context](docs/claude/project-context.md) — 저장소의 제품 범위와 작업 모드.
2. [Operating Principles](docs/claude/operating-principles.md) — 기본 판단 기준, 트레이드오프, instruction 관리 원칙.
3. [Always-On Skills](docs/claude/always-on-skills.md) — 코드 작성/리뷰/리팩토링 전에 읽을 필수 skill.
4. [Hwan Refactor Gates](docs/claude/refactor-gates.md) — `/hwan-refactor-*` gate 실행 시 필수 절차.

`docs/solutions/` 는 과거 문제 해결 기록(버그, 문서 gap, workflow pattern)을 category와 YAML frontmatter(`module`, `tags`, `problem_type`)로 정리하는 지식 저장소다. 관련 영역을 구현하거나 디버깅할 때 검색하면 이전 시행착오와 예방 규칙을 확인할 수 있다.

## 빠른 라우팅

- 코드 작업이면 [Always-On Skills](docs/claude/always-on-skills.md)를 먼저 적용한다.
- `/hwan-refactor-*` 요청이면 [Hwan Refactor Gates](docs/claude/refactor-gates.md)를 시작 즉시 적용한다.
- 문서 구조 변경이면 [Operating Principles](docs/claude/operating-principles.md)의 instruction style 원칙을 따른다.

공개 사용법은 [README.md](README.md)를 참조한다.
