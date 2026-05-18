# Runbook: API_KEY Rotation

## 컨텍스트

본 서비스는 현재 **단일 공유 `API_KEY`** 만 지원. 무중단 회전 (rolling rotation) 은 코드 변경 없이는 불가. 본 runbook 은 짧은 다운타임을 허용하는 회전 절차.

향후 multi-key 지원 추가 시 본 runbook 갱신 필요.

## 회전이 필요한 경우

- 키 유출 의심 (로그/실수 commit/직원 이직)
- 정기 회전 (90일 권장)
- 컴플라이언스 요구 (SOC 2, ISO 27001)

## 사전 준비 (T-1d)

1. **새 키 생성**:
   ```
   openssl rand -hex 32
   # 또는
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

2. **caller 측 적용 계획**:
   - 모든 caller 시스템 목록 (Slack/위키)
   - 각 caller 의 환경변수/secret store 위치 식별
   - rolling 가능한 caller (예: graceful restart 지원) vs 즉시 재시작 필요한 caller

3. **rollback 키 보관**: 현재 키를 임시 secure storage 에 백업 (rollback 용).

## 절차 (다운타임 ~5분)

### 옵션 A: 다운타임 허용 (가장 단순)

1. T0: caller 들에게 1분 전 공지.
2. T+1min: email-service `API_KEY` 환경변수를 새 값으로 변경 + 재배포.
3. T+2min: caller 시스템들 자기 환경변수 새 키로 갱신 + 재배포.
4. T+3min: smoke test:
   ```
   curl -X POST https://email-service.example.com/send \
     -H "Authorization: Bearer <NEW_KEY>" \
     -H "Content-Type: application/json" \
     -H "X-Dry-Run: true" \
     -d '{"to":"test@example.com","subject":"rotation test","html_body":"<p>ok</p>"}'
   # 200 OK 응답 확인
   ```
5. T+5min: 메트릭 확인 — 401 응답 없음 / caller 들 정상.

### 옵션 B: 듀얼 키 (코드 변경 필요, 향후 권장)

현재 단일 키 지원만 → 옵션 A 만 사용 가능. 옵션 B 는 multi-key 지원 추가 시:
1. T0: 새 키를 secondary 로 추가 (둘 다 valid)
2. T+1d: caller 들이 점진적으로 새 키 채택
3. T+7d: 구 키 제거

## 롤백

문제 발생 시:
1. T+N: `API_KEY` 환경변수를 백업한 old 값으로 환원 + 재배포.
2. caller 들 환경변수 환원.
3. 사후 분석 후 재시도 일정 잡기.

## 사후 분석 체크리스트

- [ ] 회전 중 발생한 401 응답 수 (메트릭 / 로그)
- [ ] 가장 늦게 갱신된 caller 와 그 사유
- [ ] 다운타임 실제 측정값 vs 목표 (5min)
- [ ] multi-key 지원 우선순위 격상 검토 (현재 P1, code-L10)

## 관련 환경변수

- `API_KEY` (required) — Bearer 토큰. min 32 hex chars 권장.
- `METRICS_REQUIRE_AUTH` (optional) — `/metrics` 도 같은 키 검증 시 함께 회전 필요.

## 보안 노트

- 절대 commit 금지. `.gitignore` 에 `.env` 등록 확인.
- 로그에 키 출력 금지 (현재 로그 코드는 key 출력 안 함 — `EMAIL_SERVICE_DEBUG=1` 만 SMTP password 출력함, 별개).
- secret store (AWS Secrets Manager / HashiCorp Vault / GitHub Secrets) 사용 권장.
