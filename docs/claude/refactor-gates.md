# Hwan Refactor Gates

## When to use this

사용자가 `/hwan-refactor-idea`, `/hwan-refactor-code`, `/hwan-refactor-design`, `/hwan-refactor-git` 중 하나를 호출할 때 사용한다.

## Gate 시작

모든 `/hwan-refactor-*` gate 는 시작 즉시 [.claude/GATE-ADDENDUM.md](../../.claude/GATE-ADDENDUM.md) 를 읽고, 그 정책을 본인의 Phase 0 과 마지막 Phase 위에 얹는다.

또한 gate owner 의 active learning 을 읽는다:

- `.claude/learnings/<gate>/learnings.md`
- `.claude/learnings/index.md`

active learning 을 priors 로 적용한다. 같은 learning ID 가 재발하면 severity 를 한 단계 올린다.

## Gate 실행 중

subagent 는 [subagent-policy.md](../process/subagent-policy.md) 의 사용 조건 중 2개 이상을 충족할 때만 호출한다. 관성으로 호출하지 않는다.

## Gate 종료

모든 gate 는 완료로 간주되기 전에 Compound Learning Closure 를 반드시 끝낸다:

1. `SUMMARY.md` 마지막에 다음 4개 섹션을 추가한다:
   - Active Learnings Applied
   - New Learnings Captured
   - Recurrence Risks
   - Next Gate Prompt Addendum
2. gate owner 의 `learnings.md` 를 갱신한다.
3. `.claude/learnings/index.md` 를 갱신한다.
4. [gate-closeout-checklist.md](../process/gate-closeout-checklist.md) 의 A~G 를 모두 통과한다.

[compound-learning-loop.md](../process/compound-learning-loop.md) 의 schema 와 절차를 따른다.

## Gate 철학

- `/hwan-refactor-code` 는 audit + plan only 이다. 코드를 자동 수정하지 않는다.
- `/hwan-refactor-git` 은 PR 생성, 머지, 배포를 자동 실행하지 않는다. 명시 승인 후에만 수행한다.
