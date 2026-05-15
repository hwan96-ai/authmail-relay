# Phase 3 — Observability

**목표:** 운영자가 발송 성공률·실패 사유·지연을 볼 수 있게 함. additive — 호환성 무파괴.

**소요 (CC):** ~1시간 | **위험:** 낮음 | **외부 의존:** (선택) Prometheus 스크레이프

## 진입 조건

- Phase 2 의 `SendResult` 가 존재 (error_code 카운터 라벨로 사용)

## 작업

### P0 — 핵심 메트릭

- [ ] **3.1 `/metrics` Prometheus 엔드포인트**
  - 파일: [email_service/api.py](../email_service/api.py)
  - 변경: `prometheus-client` 를 `[http]` extras 에 추가. Counter/Histogram 정의:
    - `email_send_total{result, error_code}` Counter
    - `email_send_duration_seconds` Histogram (SMTP 호출 지연)
    - `email_send_active` Gauge (현재 inflight)
  - 엔드포인트: `GET /metrics` — 기본 auth 없음 (운영망 내부 가정), 환경변수 `METRICS_REQUIRE_AUTH=true` 시 Bearer 강제
  - 게이트: `METRICS_ENABLED=true` 환경변수로 활성화 (기본 false — 의존성 부재 환경에서도 import 가능하도록)
  - 출처: [reports/06-office-hours-design.md](../reports/06-office-hours-design.md), /ceo, /devex
  - 테스트: 발송 후 `/metrics` 호출 → `email_send_total{result="success"} >= 1`

- [ ] **3.2 구조화 로그 (JSON optional)**
  - 파일: [email_service/sender.py](../email_service/sender.py), [api.py](../email_service/api.py)
  - 변경: 환경변수 `EMAIL_SERVICE_LOG_FORMAT=json` 시 `python-json-logger` 사용. 기본은 기존 텍스트 로그.
  - 모든 로그에 `to_hash` (수신자 SHA-256 처음 8자), `error_code`, `duration_ms`, `message_id` 일관 필드.
  - 주의: 수신자 평문 로깅 금지 (PII).

### P1 — Debug & Trace

- [ ] **3.3 `EMAIL_SERVICE_DEBUG=1` verbose 모드**
  - 파일: [email_service/sender.py](../email_service/sender.py)
  - 변경: `smtplib.SMTP(...)` 에 `debuglevel=1` 부여, SMTP wire protocol 로그 활성화 (테스트/디버깅용).
  - **보안:** debug 모드에서도 password 라인은 마스킹 (`AUTH PLAIN ***`).
  - 출처: [reports/10-devex-review.md](../reports/10-devex-review.md) Pass 3

- [ ] **3.4 Trace ID 헤더 전파**
  - 파일: [email_service/api.py](../email_service/api.py)
  - 변경: `X-Request-ID` 헤더가 들어오면 로그·메트릭 라벨에 포함. 부재 시 uuid 생성. 응답 헤더에 echo.
  - 테스트: trace ID 가 SMTP 발송 로그까지 전파되는지 확인

### P2 — 문서

- [ ] **3.5 README "Operations" 섹션**
  - 파일: [README.md](../README.md)
  - 변경: 메트릭 라벨 의미, grafana 대시보드 예시 (json), 알람 권장값 (`rate(email_send_total{result="failure"}[5m]) > 0.05`).

## 완료 정의

- [ ] P0 2건 완료
- [ ] P1 2건 완료
- [ ] P2 1건 완료
- [ ] `/metrics` 응답이 Prometheus 텍스트 포맷 준수
- [ ] PII (수신자 이메일, 토큰, 코드) 가 로그·메트릭에 평문 노출되지 않음 — grep 으로 검증
- [ ] 커밋: `phase-3: observability — metrics, structured logs, debug mode`

## 출구 조건

- `curl http://localhost:8000/metrics` 가 valid Prometheus 출력
- 부하 테스트 (`hey -n 100 -c 5 ...`) 후 메트릭 카운터 일치
