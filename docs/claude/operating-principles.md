# Operating Principles

## When to use this

이 저장소의 모든 작업에서 기본 판단 기준으로 사용한다. 특히 작업이 모호하거나, 여러 단계이거나, 불필요한 정리를 유발할 수 있을 때 사용한다.

## 트레이드오프

속도보다 신중함에 가중치를 둔다.

사소한 작업에서는 판단으로 절차를 가볍게 유지할 수 있다. 단, `/hwan-refactor-*` gate 의 Compound Learning Closure 와 subagent ROI 검증은 생략하지 않는다.

## Instruction style

Claude instruction 은 명시적이고, 실용적이고, 중복이 적어야 한다:

- root [CLAUDE.md](../../CLAUDE.md) 에는 라우팅과 짧은 요약만 둔다.
- 역할/주제별 상세 지침은 `docs/claude/` 아래에 둔다.
- 공유 프로젝트 instruction 을 `.claude/` 아래에 두지 않는다. `.claude/` 는 ignored local Claude artifacts 용도로 남긴다.
- 긴 절차를 반복하지 말고 canonical source 로 링크한다.
