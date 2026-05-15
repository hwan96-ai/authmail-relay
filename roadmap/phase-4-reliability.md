# Phase 4 — Reliability Features

**목표:** CEO 승인 3건 (retry, test-mode, webhook callback) 구현. 발송 신뢰성을 SES 수준에 근접시킴.

**소요 (CC):** ~3시간 | **위험:** 중간 (새 비동기 경로) | **외부 의존:** 없음 (webhook 은 caller 가 받음)

## 진입 조건

- Phase 2 (SendResult) 완료
- Phase 3 (metrics) 완료 — retry 카운트 메트릭으로 검증 필요

## 핵심 설계 (CEO 플랜 발췌)

- [reports/07-ceo-plan.md](../reports/07-ceo-plan.md) 의 ACCEPTED 3건만 구현. DEFERRED 4건은 손대지 않음.
- 모든 새 기능은 env-var flag 로 default-off 출시 → 3개 독립 PR 분리 가능.

## 작업

### P0 — Retry with Exponential Backoff

- [ ] **4.1 Retry 로직**
  - 파일: [email_service/sender.py](../email_service/sender.py)
  - 변경: `SmtpSender.__init__` 에 `max_retries: int = 0`, `backoff_seconds: tuple[int, ...] = (1, 5, 25)` 추가. 기본 0 = 기존 동작 유지.
  - 재시도 조건: `SMTPServerDisconnected`, `SMTPConnectError`, `socket.timeout`, SMTP 4xx (transient). 5xx 영구 실패는 즉시 반환.
  - 부분 거부 시 **재시도 안 함** (수신자 중복 발송 방지) — `status: partial` 로 즉시 종료
  - `Message-ID` 는 retry 전체 동안 동일하게 유지 (MTA dedup)
  - 출처: [reports/07-ceo-plan.md](../reports/07-ceo-plan.md) Accept #2
  - 테스트: SMTP mock 으로 transient 실패 후 성공 → 1회 재시도 후 sent=True 확인

- [ ] **4.2 Retry 메트릭 라벨**
  - 파일: [email_service/sender.py](../email_service/sender.py) — Phase 3 의 `email_send_total` 에 `retry_attempt` 라벨 추가
  - `email_retry_attempts_total{reason}` Counter 신규
  - 테스트: 재시도 1회 후 성공 → `email_retry_attempts_total{reason="transient"} == 1`

### P0 — Test-mode (.eml capture)

- [ ] **4.3 EMAIL_TEST_CAPTURE_DIR 환경변수**
  - 파일: [email_service/sender.py](../email_service/sender.py)
  - 변경: 환경변수 `EMAIL_TEST_CAPTURE_DIR=/path/to/dir` 이 set 되면 SMTP 호출을 건너뛰고 `<message_id>.eml` 파일로 저장. `sent=True` 반환.
  - 정합성: dry_run 과 다름 — dry_run 은 페이로드 검증 only, test-mode 는 실제 메시지 캡처
  - 출처: [reports/07-ceo-plan.md](../reports/07-ceo-plan.md) Accept #3
  - 테스트: tmpdir 에 캡처 디렉토리 설정 → 발송 → .eml 파일 존재 + 헤더 파싱 가능

- [ ] **4.4 caller integration test 예시**
  - 파일: `examples/integration_test_with_capture.py` (신규)
  - 변경: Phase 5 의 `examples/` 디렉토리 선반영 — Flask 앱 + pytest fixture 가 EMAIL_TEST_CAPTURE_DIR 로 메일 검증하는 예시

### P1 — Webhook Callback

- [ ] **4.5 Webhook callback 페이로드 정의**
  - 파일: [email_service/api.py](../email_service/api.py)
  - 변경: `SendEmailRequest` 에 `webhook_url: str | None`, `webhook_secret: str | None` 필드 추가. webhook_url 제공 시 응답은 즉시 `{"sent": True, "accepted": true}` (실제 발송 결과는 webhook 으로 통지).
  - 비동기 처리: FastAPI `BackgroundTasks` 사용 (Celery 등 외부 인프라 도입 안 함).
  - 출처: [reports/07-ceo-plan.md](../reports/07-ceo-plan.md) Accept #1

- [ ] **4.6 HMAC 서명**
  - 변경: webhook POST body 에 `X-Email-Service-Signature: sha256=<hex>` 헤더. body 전체에 대한 HMAC-SHA256. secret 은 request 의 `webhook_secret` 사용.
  - 페이로드: `{message_id, status: "delivered"|"failed"|"partial", error_code, refused, sent_at, attempts}`
  - 출처: [reports/07-ceo-plan.md](../reports/07-ceo-plan.md) Architecture 섹션

- [ ] **4.7 Webhook 재시도**
  - 변경: webhook delivery 실패 시 `[1s, 10s, 60s]` 3회 재시도. 최종 실패 시 `email_webhook_failed_total` 메트릭 증가 + 로그 ERROR.
  - 게이트: webhook 자체 실패가 발송을 막지 않음 — 발송은 이미 완료된 상태
  - 테스트: webhook 서버를 mock 으로 첫 호출 503 → 재시도 후 200 → 정상 종료

### P2 — 통합

- [ ] **4.8 `EmailServiceClient.send(... , webhook_url=...)`**
  - 파일: [email_service/client.py](../email_service/client.py)
  - 변경: SDK 에도 webhook_url/webhook_secret 파라미터 노출

- [ ] **4.9 docker-compose.dev.yml 에 webhook 수신 예시**
  - 파일: [docker-compose.dev.yml](../docker-compose.dev.yml)
  - 변경: `webhook-sink` 서비스 추가 (간단한 echo HTTP 서버) — 개발자가 webhook 페이로드를 즉시 확인 가능

## 완료 정의

- [ ] P0 4건 완료 (4.1, 4.2, 4.3, 4.4)
- [ ] P1 3건 완료 (4.5, 4.6, 4.7)
- [ ] P2 2건 완료
- [ ] 3개 독립 PR 로 분리 가능 (retry / test-mode / webhook) — 또는 한 PR 로 묶되 커밋 단위 분리
- [ ] 부하 테스트: 100건 발송 중 50% transient 실패 → retry 후 모두 성공
- [ ] 커밋: `phase-4: retry, test-mode, webhook callback`

## 출구 조건

- env-var flag default-off — 기존 호출자 영향 0
- Phase 3 메트릭으로 retry 효과 검증 가능
- webhook 페이로드 스키마가 README + OpenAPI 양쪽에 반영
