# Runbook: SMTP Outage

## Symptoms
- `email_send_total{result="failure"}` 급증 (error_code 가 `smtp_connection`, `smtp_timeout`, `smtp_transient` 중 하나)
- `/send` 가 502 응답 다수
- 외부 SMTP provider 상태 페이지에 incident 보고

## 즉시 대응 (T+0 ~ T+15min)

1. **provider 상태 확인**:
   ```
   # SES / SendGrid / Gmail 상태 페이지 열기
   # 또는 SMTP 호스트 ping:
   nc -vz $SMTP_HOST 587
   ```

2. **메트릭 확인** (`/metrics` 인증 환경에서):
   ```
   email_send_total{result="failure"} - 1분 rate
   email_send_active                  - 현재 진행 중 send 수
   email_send_duration_seconds        - p99 latency
   ```

3. **결정 트리**:
   - 단순 일시 outage (provider 가 자체 복구) → 4번으로
   - 장기 outage (provider 30분+ 무응답) → 6번으로

4. **rate limit 조정 (옵션)**: 평소보다 많은 retry 가 발생하므로 일시 트래픽 차단:
   ```
   # 환경변수 일시 변경 (재배포 필요)
   API_RATE_LIMIT_PER_MINUTE=10   # 평소 60 → 10
   ```
   알림: caller 가 429 받음. 의도된 동작.

5. **모니터링 유지**: provider 복구까지 대기. SMTP retry 가 자동 재시도하므로 인입 트래픽은 큐잉되지 않음 (즉시 502 반환).

## 장기 대응 (provider 30분+ outage)

6. **백업 SMTP 전환** (configured 시):
   ```
   # 환경변수 변경 + 재배포
   SMTP_HOST=backup-smtp.example.com
   SMTP_USER=...
   SMTP_PASSWORD=...
   ```
   재배포 중 in-flight email 손실 가능 — 받아들임.

7. **공지 발송**: 다른 channel (Slack / dashboard) 로 사용자에게 영향 안내.

## 롤백 / 완화

- rate limit 원복: `API_RATE_LIMIT_PER_MINUTE=60` 환경변수 재배포
- backup → primary SMTP 환원: provider 복구 확인 후 환경변수 환원

## 사후 분석 체크리스트

- [ ] retry budget (max 31s) 가 충분했나?
- [ ] threadpool slot 점유 통계 (workers × max_total_retry_sleep) 검토
- [ ] backup SMTP 가 configured 되어 있었나? 없었으면 추가
- [ ] 다음 outage 시 자동 fallback 정책 정의 가능한가?

## 관련 알람 임계값 (권장)

- `rate(email_send_total{result="failure"}[5m]) > 1/s` → warning
- `rate(email_send_total{result="failure"}[5m]) > 10/s` → critical
- `email_send_active > 30` → threadpool 고갈 임박 (40 default cap)
