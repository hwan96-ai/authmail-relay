# Compound Learning Loop

이 프로젝트(`email-service`)에서 모든 `/hwan-refactor-*` gate는 **마지막에 Compound Learning Closure 단계를 반드시 실행**한다. 목적은 같은 P0/P1/지적사항이 다음 gate, 다음 PR, 다음 릴리스에서 또 발생하지 않게 만드는 것이다.

> **출처 영향**: EveryInc/compound-engineering, obra/superpowers. 이 프로젝트는 두 방법론 중 "review가 끝난 후의 학습 캡처 + 다음 세션 입력 승격" 부분을 의무 단계로 채택한다.

## 1. 적용 범위

| Gate | Owner Path |
|------|-----------|
| `/hwan-refactor-idea` | `.claude/learnings/idea/learnings.md` |
| `/hwan-refactor-code` | `.claude/learnings/code/learnings.md` |
| `/hwan-refactor-design` | `.claude/learnings/design/learnings.md` |
| `/hwan-refactor-git` | `.claude/learnings/git/learnings.md` |
| 전체 누적 인덱스 | `.claude/learnings/index.md` |

모든 gate는 **시작 시 본인 owner 경로 + index.md를 먼저 읽고**, **종료 시 closure를 실행**한다.

## 2. Gate 시작 전 (Pre-Gate Hook)

모든 gate의 Phase 0 다음에 다음을 수행한다:

1. `.claude/learnings/index.md` 를 읽는다 (cross-gate 누적 교훈).
2. 본인 owner 경로의 `learnings.md` 를 읽는다.
3. **status가 `active` 인 learning만 priors 로 채택**한다. `resolved` 는 무시.
4. 각 active learning의 `Next-Session Checklist Item` 을 이번 gate의 체크리스트에 **그대로 복사**한다.
5. **재발 감지 규칙**: 같은 ID 의 learning 이 직전 세션에서도 `active` 였고 이번에도 동일 카테고리에서 발견되면, `Severity` 를 한 단계 올려서 보고한다 (P2 → P1, P1 → P0).
6. 직전 gate (예: code gate 직후의 git gate)의 SUMMARY.md 에서 미해결 P0/P1 을 그대로 inherit 한다.

## 3. Gate 실행 중 (During-Gate)

평소대로 phase 진행. 단, 다음을 별도로 트래킹한다:

- **어떤 active learning 이 실제로 이번 gate 에서 발견 자료로 쓰였는지** (= Applied)
- **어떤 active learning 이 적용되었는데도 같은 이슈가 또 발견됐는지** (= Recurrence)
- **새로 발견된, learnings.md 에 아직 없는 패턴인지** (= New)

## 4. Gate 종료 후 — Compound Learning Closure (필수 단계)

SUMMARY.md 작성 직전에 다음을 수행한다.

### 4.1 학습 수집 입력

다음을 수집한다:
- 이번 gate 의 P0/P1 항목 전체
- 3+ reviewer 가 동시 지적한 strong-convergence 항목
- 직전 gate 에서 inherit 된 미해결 항목
- "테스트는 통과했지만 외부 노출 시 위험" 부류
- "코드 단계가 아니라 문서/운영/배포에서 늦게 발견" 부류
- adversarial / edge-case / docs-ops reviewer 가 단독으로만 잡은 항목

### 4.2 Learning Schema (정규화 형식)

각 learning 은 **반드시** 다음 11개 필드로 정규화한다. 자유 서술 금지.

```yaml
ID: <owner-gate>-LNN (예: code-L11, git-L03)
Source: <session-id> + <reviewer 이름들>
Severity: P0 | P1 | P2 | P3
Mistake / Miss: <한두 문장>
Root Cause: <왜 발생했는가, 1문장>
Recurrence Trigger: <어떤 입력/조건/패턴 보면 또 발생하는가>
Prevention Rule: <이 패턴 보면 이렇게 하라 — 행동 지침 1문장>
Next-Session Checklist Item: <다음 gate 가 그대로 복붙해서 쓸 체크리스트 한 줄>
Applies To: <파일 glob 또는 영역 (예: api.py, **/*.yml, infrastructure)>
Owner Gate: idea | code | design | git
Evidence: <file:line 또는 SUMMARY.md 인용. 절대 모호하게 금지>
Status: active | resolved
```

### 4.3 SUMMARY.md 보강

해당 gate 의 SUMMARY.md **맨 아래**에 다음 4개 섹션을 추가한다.

```markdown
---

## Active Learnings Applied
- ID/링크 + 이 gate 에서 어떻게 사용됐는지 (1줄씩)

## New Learnings Captured
- 신규 ID 와 한 줄 요약 (전체 schema 는 learnings.md 에)

## Recurrence Risks
- 직전 세션 이후에도 재발한 learning ID + 새 severity

## Next Gate Prompt Addendum
> 다음 실행자(사람 또는 LLM)가 다음 gate 시작 시 그대로 prompt 에 붙일 수 있는 텍스트
> 형식: "Before starting, confirm these checks: [Next-Session Checklist Item list]"
```

### 4.4 learnings.md 갱신

- 신규 항목은 위 schema 그대로 append. 절대 overwrite 금지.
- 직전 세션 의 active learning 중 이번 gate 에서 더 이상 발견되지 않고, 코드/문서가 해결된 경우만 `Status: resolved` 로 변경.
- `Status` 변경 시 옆에 `Resolved-By: <session-id>` 추가.

### 4.5 index.md 갱신

`.claude/learnings/index.md` 에 한 줄 추가:

```
<date> | <gate> | <session-id> | applied=<N> new=<N> recurred=<N> | <SUMMARY.md 경로>
```

cross-gate 패턴 식별용. 일정 주기로 사람이 읽어 패턴 재구성.

## 5. 실패 모드 — 이 단계 누락 시

- SUMMARY.md 에 위 4 섹션이 없으면 그 gate 는 **불완전 종료**로 간주.
- 다음 gate 시작 시 unmistakable warning 으로 표시.
- "관성으로 좋은 말만 적기" 금지: 모든 learning 은 file:line 인용 또는 reviewer 출처 필수.

## 6. 운영 약속

- "learnings 너무 많이 쌓이면 어쩌나" 우려: 분기당 1회 사람이 `.claude/learnings/index.md` 를 보고 resolved 정리.
- Prevention Rule 의 단어 수는 가급적 1-2 문장. 길어지면 그 룰은 작동하지 않는다.
- "Next-Session Checklist Item" 은 next-gate prompt 에 그대로 들어갈 수 있어야 한다. 추상어 금지.
