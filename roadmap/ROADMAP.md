# Refactoring Roadmap — email-service

[reports/](../reports/) 의 10개 리뷰 산출물에서 도출된 액션을 우선순위·실행 가능 단위로 묶은 단계 로드맵.

## 단계 개요

| Phase | 목표 | 위험도 | 소요 (CC) | 외부 의존 | 파일 |
|---|---|---|---|---|---|
| **1. Security & Correctness** | 즉시 회귀 가능한 보안·신뢰성 결함 차단 | 낮음 (in-place fix) | ~1h | 없음 | [phase-1-security.md](phase-1-security.md) |
| **2. Developer Experience** | bool/bare 502 → 구조화된 에러, CHANGELOG, PyPI | 중간 (공개 API 변경) | ~2h | PyPI 계정 | [phase-2-dx.md](phase-2-dx.md) |
| **3. Observability** | `/metrics`, debug 모드, 구조화 로그 | 낮음 (additive) | ~1h | (선택) Prometheus | [phase-3-observability.md](phase-3-observability.md) |
| **4. Reliability Features** | Retry, test-mode, webhook callback (CEO 승인 3건) | 중간 (새 코드 경로) | ~3h | 없음 | [phase-4-reliability.md](phase-4-reliability.md) |
| **5. Polish & Community** | a11y/i18n 이메일, Swagger 메타, examples/, async client | 낮음 (additive) | ~2h | 없음 | [phase-5-polish.md](phase-5-polish.md) |

**총 소요 (CC + gstack 기준): ~9시간** — 사람-팀 기준 환산 약 1.5~2주 분량.

## 실행 순서 규칙

1. **Phase 1 → Phase 2 → Phase 3** 은 직렬. 1단계가 보안 베이스라인, 2단계가 API 표면 안정화, 3단계가 그 위에 운영성을 얹는다.
2. **Phase 4** 는 Phase 2 의 `SendResult` 구조에 의존. Phase 2 완료 후 진행.
3. **Phase 5** 는 다른 단계와 병렬 가능 — 별도 worktree 에서 진행해도 충돌 없음.

## 단계 진입 게이트

각 phase 시작 전에 다음 게이트 통과:
- 이전 phase 의 모든 P0/P1 작업 완료
- `python -m pytest tests/ -q` 통과
- 새 의존성 추가 시 [reports/04-security-audit.md](../reports/04-security-audit.md) 의 핀 정책 준수

## 단계별 완료 정의

Phase 가 "완료" 되려면:
1. 해당 phase md 의 모든 P0 체크박스 ✅
2. P1 은 ≥80% 완료
3. 회귀 테스트 추가 (관련 phase 가 다루는 회귀 케이스 모두)
4. CHANGELOG.md 에 변경사항 기록 (Phase 2 이후)
5. `git commit -m "phase-N: <summary>"` 으로 단일 또는 소수 커밋으로 정리

## 교차 모델 합의 항목 (≥3개 리뷰어 동시 지적)

| 액션 | 리뷰어 | Phase |
|---|---|---|
| `pyproject.toml` deps 핀 + lock | /cso, /office-hours, /devex | **1** |
| 구조화 에러 (`SendResult` + `error_code`) | /qa, /devex, /eng | **2** |
| CHANGELOG + semver | /devex, /office-hours | **2** |
| `/metrics` 엔드포인트 | /office-hours, /ceo, /devex | **3** |
| Retry with backoff | /office-hours, /ceo | **4** |

## 단계 외 (DEFERRED) — 별도 백로그

| 항목 | 출처 | 이유 |
|---|---|---|
| Outbox 패턴 | CEO | DB 결합 강제 — 별도 라이브러리가 적합 |
| Template registry | CEO | TemplateNotifier 가 이미 커버 |
| Multi-tenant API_KEY | CEO | 리버스 프록시 영역 |
| Provider abstraction (SendGrid/SES) | CEO | 수요 검증 후 |
| 첨부파일 지원 | Eng | 별도 요청 시 |
| Multi-recipient `to` list | Eng | 별도 요청 시 |

## 진행 추적

각 phase md 의 체크박스 (`- [ ]` → `- [x]`) 로 진행률 추적. 본 ROADMAP 의 단계 개요 표는 진행률 요약에 사용하지 않는다 — 각 phase md 가 단일 진실 소스.
