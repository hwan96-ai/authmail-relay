# Subagent Policy

이 프로젝트에서 subagent(병렬 Task / Agent 호출)는 **ROI 가 있을 때만** 사용한다. "가능하면 활용" 이 아니다.

## 원칙

1. **필요할 때만** 사용한다.
2. 무조건 병렬화하지 않는다. 1 명의 reviewer 가 정확히 답할 수 있다면 1 명만 호출한다.
3. subagent 가 병목을 만들면 사용하지 않는다 (예: 결과 통합 시간이 직접 작업보다 김).
4. 모든 subagent 결과는 **반드시 synthesis 한다**. 그대로 사용자에게 dump 금지.
5. **Final gate owner (호출한 메인 Claude) 가 증거 기반으로 채택/기각한다**. subagent 의 결론을 그대로 신뢰하지 않는다.
6. 충돌하는 발견은 file:line 근거가 더 구체적인 쪽을 채택, 양쪽 모두 약하면 사용자에게 명시.

## ✅ 사용 조건 (이 중 2개 이상 충족할 때만)

- (A) 서로 다른 전문 관점이 필요. 보안 / 운영 / 배포 / 성능 / 디자인 등 4 차원 이상 동시 검토.
- (B) 3개 이상 파일/모듈을 동시에 봐야 한다.
- (C) Adversarial / edge-case / docs-ops / security 처럼 단일 reviewer 가 놓치기 쉬운 관점 필요.
- (D) 병렬 결과를 통합할 명확한 synthesis 기준이 있다 (예: severity rubric, 출처 convergence).
- (E) Gate 의 phase 명세 자체가 병렬 호출을 요구.

## ❌ 비사용 조건 (다음 중 하나라도 해당하면 단일 흐름)

- (a) 단일 파일의 작은 문구/타입/lint 수정.
- (b) 원인이 이미 명확한 P0 핫픽스 (subagent 가 다시 분석해도 답이 동일).
- (c) "리뷰 이슈" 보다 "구현 분량" 이 더 작은 작업.
- (d) Subagent 결과 통합에 들어갈 시간이 직접 작업 시간보다 크다.
- (e) 보안/신뢰 경계가 없는 단순 정리 작업 (README 줄 정렬, 주석 통일 등).
- (f) 정보가 부족해 subagent 가 결국 사용자에게 되물을 가능성이 높다.

## Synthesis 규칙

1. **출처 cross-check**: 같은 발견이 2+ subagent 에서 나오면 strong-convergence 로 마킹.
2. **증거 우위**: file:line 인용 있는 발견 > 없는 발견. 후자는 보고하기 전에 직접 확인.
3. **Severity 충돌**: 보안 reviewer 가 P0, 일반 reviewer 가 P2 → P0 로 채택 (보안 우위).
4. **운영 reviewer (docs-ops, adversarial-deploy) 의 운영 영향 평가는 코드 reviewer 보다 우선**한다.
5. **중복 제거**: 동일 file:line 의 발견은 가장 구체적인 표현으로 통합, 출처는 모두 기록.

## 게이트별 권장 subagent 사용

| Gate | 기본 subagent 수 | 조건부 추가 |
|------|----------------|------------|
| `/hwan-refactor-idea` | 1–2 (PRD 단일 문서) | PRD 가 길고 다영역이면 +1 |
| `/hwan-refactor-code` | 0–4 (--quick: 0, deep: 4) | 1000 LOC 미만의 단일 모듈 변경이면 0 권장 |
| `/hwan-refactor-design` | 0–2 (시각 검토 시) | 정적 마크업만 변경이면 0 |
| `/hwan-refactor-git` | 2–3 (security/adversarial/docs-ops) | 신규 commit 0개면 0 (현재 상태 audit-only) |

## 안티패턴

- **"reviewer 7 명 무조건 호출"**: ROI 무시. 정해진 phase 라도 직전 gate 가 같은 코드를 이미 review 했으면 중복.
- **subagent 결과 raw dump**: 사용자가 7 개 보고서를 읽어야 한다 → synthesis 실패.
- **subagent 가 만든 P0 무비판 채택**: 증거 file:line 확인 안 했으면 채택 금지.
- **"가능하면 병렬"**: 명시적 ROI 없으면 단일 흐름이 default.
