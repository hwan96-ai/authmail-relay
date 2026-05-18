# Runbook: Webhook Target Outage

## Symptoms
- `email_webhook_failed_total` 증가
- 로그에 `"Webhook returned non-2xx"` 또는 `"Webhook delivery failed after 3 attempts"`
- 호출자(caller) 로부터 "이메일 결과 안 옴" 보고

## 중요한 사실

- **이메일은 발송됨**. `deliver_webhook` 은 SMTP 전송 *완료 후* 결과를 통보하는 단계.
- webhook 실패 = caller 가 결과를 모름, 단 메일 자체는 수신자에게 도착.
- 본 서비스는 webhook 미배달 시 **자동 재시도 없음** (max 3 attempts, total ≤8s, 그 후 영구 실패).
- DLQ 없음 — 영구 실패한 webhook 은 메트릭/로그에만 남음.

## 즉시 대응 (T+0 ~ T+15min)

1. **caller 의 webhook endpoint 상태 확인**:
   ```
   curl -i -X POST https://caller.example.com/webhook -d '{"test":1}'
   ```

2. **webhook URL 검증 자체 차단 가능성 확인**:
   ```
   # 로그에서 다음 패턴 검색
   grep "Webhook URL rejected" /var/log/email-service.log
   # 또는
   grep "DNS rebinding" /var/log/email-service.log
   ```
   "rejected" 가 보이면 → caller 의 endpoint 가 private/loopback 으로 resolve. 정상 차단.

3. **caller 와 통신**: webhook endpoint 복구 / 재배포 요청.

## 영구 실패 webhook 사후 처리

본 서비스는 영구 실패 webhook 의 메일 결과를 보존하지 않음. caller 가 이메일 발송 결과를 알아야 한다면:

1. **메트릭 + 로그에서 message_id 식별**:
   ```
   # 영구 실패한 webhook 의 message_id 검색
   grep "Webhook delivery failed" /var/log/email-service.log | jq .message_id
   ```

2. **운영자가 caller 에게 message_id 목록 수동 통보** (Slack / 이메일).

3. **caller 가 자기 시스템에서 message_id 로 dedup 후 재처리**.

## 롤백 / 완화

- 영구 실패한 webhook 자체에 대한 롤백 절차 없음 (메일은 이미 발송됨).
- caller endpoint 복구 후 새 send 요청은 정상 처리됨.

## 사후 분석 체크리스트

- [ ] caller endpoint 의 timeout / 5xx 분포 검토
- [ ] webhook backoff 합계 (1+2+5=8s) 가 충분했나? caller 가 매번 8s 안에 복구 못 한다면 longer backoff 검토
- [ ] DLQ 추가 가치 평가 (P1 향후 항목, 현재 미구현)
- [ ] message_id 기반 caller-side dedup 구축 권장 여부

## SSRF / DNS rebinding 차단된 경우 (false positive 처리)

caller endpoint 가 internal/private 주소이지만 합법이라면:
- `WEBHOOK_ALLOW_HOSTS` 환경변수에 hostname 추가 (예: `internal.svc,prod-callback.internal`)
- `WEBHOOK_ALLOW_LOOPBACK=1` 은 **테스트 전용** — production 에서 사용 금지

## 관련 알람 임계값 (권장)

- `rate(email_webhook_failed_total[5m]) > 0.1/s` → warning
- `rate(email_webhook_failed_total[5m]) > 1/s` → critical (caller 측 문제 강한 시그널)
