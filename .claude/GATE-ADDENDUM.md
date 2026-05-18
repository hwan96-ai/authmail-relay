# Gate Addendum — email-service (project-local)

이 파일은 모든 `/hwan-refactor-*` gate 가 **Phase 0 (Load prior learnings) 직후 무조건 읽어야 하는** 프로젝트 로컬 정책 보강이다. 글로벌 hwan 명령은 수정하지 않는다 — 이 파일이 그 위에 얹힌다.

## 1. 필수 읽기

각 gate 는 시작 시 다음 파일을 **모두** 읽고 prior 로 적용한다:

1. [docs/process/compound-learning-loop.md](../docs/process/compound-learning-loop.md)
2. [docs/process/subagent-policy.md](../docs/process/subagent-policy.md)
3. [docs/process/gate-closeout-checklist.md](../docs/process/gate-closeout-checklist.md)
4. `.claude/learnings/index.md` (전체 누적)
5. 본인 owner 의 `.claude/learnings/<gate>/learnings.md`

## 2. Phase 0 보강 (모든 gate 공통)

기존 Phase 0 ("Load prior learnings") 의 결과에 다음을 **반드시** 추가한다:

- 본인 owner learnings.md 에서 `Status: active` 인 항목만 priors 로 사용.
- 각 active learning 의 `Next-Session Checklist Item` 을 이번 gate 의 체크리스트로 복사.
- **재발 감지**: 같은 ID 가 직전 세션에서도 active 였고 이번에도 같은 카테고리에서 발견되면 → severity 한 단계 상승하여 보고. SUMMARY 의 Recurrence Risks 에 기록.
- 직전 gate (시간순) 의 SUMMARY.md 에서 미해결 P0/P1 을 inherit. 본 gate 의 P0 표에 "inherited" 라벨 부여.

## 3. Subagent 호출 게이트

새 subagent 호출 전, [subagent-policy.md](../docs/process/subagent-policy.md) §"사용 조건" 의 (A)-(E) 중 **2개 이상** 충족 여부를 자체 확인한다. 충족 못 하면 단일 흐름으로 진행.

## 4. 마지막 Phase — Compound Learning Closure (필수)

기존 명령 의 "Phase 7: Capture compound learnings" 보다 **더 엄격하게** 적용한다:

### 4.1 학습 수집 입력 (반드시 모두 검토)

- 이번 gate 의 P0/P1 전체
- 3+ reviewer strong-convergence 항목
- 직전 gate inherit 된 미해결 항목
- 테스트 통과했지만 외부 노출 시 위험 부류
- 코드보다 문서/운영/배포에서 늦게 발견된 부류
- adversarial/edge-case/docs-ops reviewer 가 단독으로 잡은 항목

### 4.2 모든 learning 은 11-필드 schema 강제

자유 서술 금지. 형식은 [compound-learning-loop.md §4.2](../docs/process/compound-learning-loop.md) 참조.

### 4.3 SUMMARY.md 의무 섹션 (마지막 4개)

```markdown
## Active Learnings Applied
## New Learnings Captured
## Recurrence Risks
## Next Gate Prompt Addendum
```

빠지면 [gate-closeout-checklist.md](../docs/process/gate-closeout-checklist.md) §A 위반 → gate 불완전 종료.

### 4.4 learnings.md / index.md 갱신

- 신규는 append. overwrite 금지.
- 해결된 prior 는 `Status: resolved` + `Resolved-By: <session-id>`.
- index.md 에 한 줄 추가.

## 5. 기존 gate 철학 보존 약속

- `/hwan-refactor-code` 는 자동 코드 수정 금지. audit + plan only.
- `/hwan-refactor-git` 은 PR/머지/배포 자동 실행 금지. 명시 승인 후만.
- 앱/서비스 런타임 코드 수정이 발생하면 SUMMARY 에 사유 명시. 없으면 되돌린다.

## 6. Seed Learnings 인덱스

본 프로젝트의 [.claude/learnings/index.md](learnings/index.md) 에 다음 seed learning 이 등록되어 있다. 이 8개는 어떤 gate 든 시작 시 priors 로 강제 적용된다 (status: active).

- L-SEED-01: 테스트 통과만으로 외부 노출 안전성 판단 금지
- L-SEED-02: BackgroundTasks + sync sleep = threadpool starvation 별도 탐지
- L-SEED-03: webhook_url 은 SSRF 관점 allowlist/denylist/private-IP 차단 검토
- L-SEED-04: 외부 입력 (subject/html_body 등) 은 max_length 필수
- L-SEED-05: post-DATA SMTP disconnect 는 단순 retry 금지, 중복 발송 가능성 검토
- L-SEED-06: tag push 즉시 publish 는 smoke/approval gate 없으면 release blocker
- L-SEED-07: mutable GitHub Action refs + OIDC publish 는 supply-chain P0 후보
- L-SEED-08: runbook 부재는 단순 문서 부족이 아니라 operational readiness blocker
