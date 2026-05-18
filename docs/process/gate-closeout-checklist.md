# Gate Closeout Checklist

모든 `/hwan-refactor-*` gate 가 종료될 때 **반드시** 다음 체크리스트를 모두 통과해야 "gate 완료" 로 간주한다. 하나라도 빠지면 불완전 종료.

## A. SUMMARY.md 필수 섹션

- [ ] 판정 (🟢/🟡/🔴) 가 명시되어 있다.
- [ ] P0/P1/P2/P3 통계가 있다.
- [ ] 각 P0 항목에 file:line 또는 구체 위치가 있다 (모호 표현 금지).
- [ ] 직전 gate 의 미해결 P0/P1 이 inherit 섹션으로 들어와 있다.
- [ ] 다음 단계 권장 (Sprint 순서) 가 있다.
- [ ] **Active Learnings Applied** 섹션이 있다.
- [ ] **New Learnings Captured** 섹션이 있다.
- [ ] **Recurrence Risks** 섹션이 있다.
- [ ] **Next Gate Prompt Addendum** 섹션이 있다.

## B. learnings.md 갱신

- [ ] 신규 learning 은 11-필드 schema (compound-learning-loop.md §4.2) 를 준수한다.
- [ ] file:line 또는 SUMMARY 인용 증거가 모든 learning 에 있다.
- [ ] 해결된 직전 learning 은 `Status: resolved` + `Resolved-By: <session-id>` 가 추가됐다.
- [ ] 같은 ID 의 재발 learning 은 `Severity` 가 한 단계 올라갔고 그 사실이 SUMMARY 의 Recurrence Risks 에 기록됐다.

## C. index.md 갱신

- [ ] `.claude/learnings/index.md` 에 이번 세션 한 줄이 추가됐다.
- [ ] 형식: `<date> | <gate> | <session-id> | applied=<N> new=<N> recurred=<N> | <SUMMARY 경로>`

## D. Subagent 사용 정당성

- [ ] subagent 를 호출했다면 [subagent-policy.md](subagent-policy.md) 의 사용 조건 (A)–(E) 중 2개 이상에 해당.
- [ ] 결과는 dump 가 아니라 synthesis 됐다.
- [ ] 충돌 발견은 증거 기준으로 해소됐다.

## E. 게이트 철학 보존

- [ ] `/hwan-refactor-code` 는 **자동 수정하지 않았다** (audit + plan only).
- [ ] `/hwan-refactor-git` 은 **PR/머지/배포를 자동 실행하지 않았다** (생성까지만, 명시 승인 필요).
- [ ] 앱/서비스 코드 변경이 있었다면 **이유가 SUMMARY 에 명시**됐다. 없으면 되돌렸다.

## F. 인계 (Hand-off)

- [ ] 다음 gate (또는 다음 사람) 가 본 SUMMARY 만 보고 시작 가능한가? 추측해서 채워야 할 빈칸이 없는가?
- [ ] "Next Gate Prompt Addendum" 을 그대로 복사하면 다음 gate prompt 가 완성되는가?

## G. 운영 안전

- [ ] git tree 가 깨끗하게 정리됐다 (uncommitted 변경 없음 또는 commit 됨).
- [ ] worktree/branch 가 master/main 이 아닌 것이 확인됐다.
- [ ] global hook 이 차단하는 명령 (`git clean -f` 등) 을 사용하지 않았다.
