# Runbook: `smtp_disconnect_uncertain` 에러 대응

## 컨텍스트

`ERR_SMTP_DISCONNECT_UNCERTAIN` 은 본 서비스의 P0-5 fix (`gate-code-fix-2026-05-18-001`) 가 도입한 신규 에러 코드. **의도된 동작이지 버그가 아니다**.

### 의미

SMTP 서버가 `sendmail()` 호출 **중** disconnect. `sendmail()` 이 정상 return 한 후의 disconnect 는 자동으로 success 로 처리됨 (post-DATA = 메일 도착 확정). 그러나 `sendmail()` *진행 중* disconnect 는:
- 서버가 메시지를 받았을 수도 있고
- 못 받았을 수도 있음

본 서비스는 **재시도하지 않음**. 재시도 시 메일이 도착했었다면 중복 발송 (P0 회귀).

## 증상

- `/send` 가 502 응답, body 에 `"error_code": "smtp_disconnect_uncertain"`
- 로그: `"SMTP server disconnected before sendmail completed"`
- 메트릭: `email_send_total{result="failure", error_code="smtp_disconnect_uncertain"}` 증가

## 즉시 대응 (T+0 ~ T+15min)

1. **빈도 확인**:
   ```
   rate(email_send_total{error_code="smtp_disconnect_uncertain"}[5m])
   ```
   - 1건 / hour 이하 → 정상 운영 noise (SMTP 서버 random disconnect)
   - 10건 / min 이상 → SMTP 서버 불안정. [smtp-outage.md](smtp-outage.md) 참조.

2. **수신자 영향 평가**:
   - **수신자가 메일을 받았는지 확인할 방법 없음** (이게 에러 의미).
   - caller 가 message_id 로 SMTP provider 의 sent log 조회 가능한지 검토:
     - SES: SNS bounce/complaint notification + sent topic
     - SendGrid: Activity Feed
     - Gmail: 관리자 콘솔의 Email log search

3. **caller 통보** (필요 시):
   - 502 응답 자체가 통보 — caller 가 retry 결정 (idempotency-key 사용 권장).
   - caller 가 정확한 발송 확인 필요하면 위 SMTP provider log 와 cross-check.

## 결정 트리

| 빈도 | 원인 추정 | 조치 |
|------|----------|------|
| < 1/hour | provider 의 random connection 정리 | 대응 불필요, 로그 확인 |
| 1-10/min | provider 의 일시 부하 | [smtp-outage.md](smtp-outage.md) 참조 |
| > 10/min | provider 장애 또는 우리 측 keep-alive 설정 문제 | provider 상태 페이지 + SRE 에스컬레이션 |

## 사용자 측 권장

caller 측 application 은:
1. **`Idempotency-Key` 헤더 사용**: 502 받으면 같은 키로 재시도. 본 서비스가 캐시 hit 시 sender 재호출 안 함.
2. **502 + error_code 분기**: `smtp_disconnect_uncertain` 받으면 "보내졌을 수도 있음" 으로 사용자에게 표시 (예: "잠시 후 메일이 도착하지 않으면 다시 보내주세요").

## 롤백 / 완화

운영 시점에 롤백할 것 없음 (에러가 아니라 정확한 상태 보고). 단,
- SMTP provider 변경 (다른 hosting → disconnect 패턴 다름)
- keep-alive 튜닝 (현재 미지원 — `SmtpConfig.timeout=10` 기본)

## 사후 분석 체크리스트

- [ ] 발생 빈도 trend (주간 그래프)
- [ ] provider sent log 와 cross-check 시 실제 발송률
- [ ] caller 측 idempotency-key 사용률
- [ ] keep-alive 또는 connection pool 도입 가치 평가

## 관련

- 코드: `email_service/sender.py` `_send_once` 의 `SMTPServerDisconnected` 분기
- 회귀 테스트: `tests/test_p0_fixes.py::TestP0_5_DisconnectDuringSendmail`
- 학습: `code-L10` (SMTP retry classifier 가 phase 식별 필수)
- 회귀 방지: 본 에러 코드를 retriable 로 분류하지 말 것 (`_RETRIABLE_ERROR_CODES` 에 포함 금지)

## 관련 알람 임계값 (권장)

- `rate(email_send_total{error_code="smtp_disconnect_uncertain"}[5m]) > 0.05/s` → warning
- `rate(email_send_total{error_code="smtp_disconnect_uncertain"}[5m]) > 0.5/s` → critical
