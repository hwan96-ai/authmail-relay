# Docs & Ops Readiness Audit — email-service v0.3.0

> 작성일: 2026-05-16 · 역할: SRE + 테크니컬 라이터
> 대상: `D:\email-service\.claude\worktrees\cool-bouman-70eb80` (v0.3.0)
> 기준 문서: README.md, CHANGELOG.md, CONTRIBUTING.md, CLAUDE.md, .github/workflows/release.yml, examples/

---

## 요약

v0.3.0은 **라이브러리/HTTP 양 모드에서 기능적으로 풍부하고 보안 모델이 명시되어 있으나**, 운영 사고 대응(runbook), 키 회전, 배포 롤백, webhook 미배달 대응 등 **"새벽 3시 호출 받았을 때" 필요한 절차 문서가 거의 0%**. 단일 운영자가 머릿속에 다 들고 있어야만 운영 가능한 상태. PyPI 공개 라이브러리로서 외부 이용자(또는 회사 내 타팀)가 자기 환경에 도입하려면 `pip install`→첫 발송까지는 5분 안에 되지만, 그 후 **장애가 한 번이라도 나면 즉시 막힌다**.

운영 준비도: README 품질이 7-8/10인 반면, runbook/SRE 문서는 1-2/10. 종합 점수는 평균이 아니라 **취약 영역에 가중치**를 둔다.

---

## 발견 사항 (Findings)

### F-001 · API_KEY 회전 절차 부재

- **category**: 1 (권한)
- **doc_gap**: `API_KEY` 가 노출되거나 정기 회전이 필요할 때의 절차가 README/CHANGELOG/CONTRIBUTING 어디에도 없음. 단일 키 + zero-downtime 회전 불가능 (이중 키 미지원).
- **production_trigger**: (a) 개발자가 슬랙/깃허브 이슈에 키 일부를 실수로 붙여넣음, (b) 분기별 정기 회전 정책을 가진 회사가 도입, (c) 직원 퇴사 후 키 회전 필요.
- **what_happens_now**: 단일 키이므로 회전 = 다운타임. 모든 호출자(타 서비스)의 키를 동시에 바꿔야 함. 무중단 절차는 추측 기반(앞단 리버스 프록시에서 dual auth 구성 등). README 696줄에 "키 분리는 리버스 프록시 레벨에서" 한 줄 언급뿐.
- **severity**: P1 (보안 사고 시 대응 시간 직결)
- **fix_required**: README 신설 섹션 `## Operations Runbooks > API Key Rotation`, 또는 `docs/runbooks/key-rotation.md`.
- **suggested_content**:
  ```
  ### API Key Rotation

  단일 `API_KEY` 만 지원하므로 무중단 회전은 앞단 리버스 프록시에서 dual-auth 를 일시적으로 받도록 구성한다.

  1. 새 키 생성: `NEW_KEY=$(openssl rand -hex 32)`
  2. 리버스 프록시(nginx 예시)에서 구/신 키 둘 다 허용하도록 설정 (transition window 5-30분).
  3. 모든 호출자(타 서비스)의 환경변수를 `NEW_KEY` 로 업데이트하고 재배포.
  4. 프록시 로그에서 구 키 호출이 0 인지 확인.
  5. email-service `API_KEY` 를 `NEW_KEY` 로 교체하고 재시작.
  6. 프록시의 dual-auth 설정 제거.

  **긴급 회전 (키 유출 확인 시)**: 단계 2-6 을 1 단계로 압축. 호출자 잠시 다운 감수.
  ```

---

### F-002 · 다중 API 키 / 호출자별 키 미지원에 대한 명시적 한계 표기 누락

- **category**: 1 (권한)
- **doc_gap**: README 696줄 "단일 API 키"는 언급되어 있으나, **"Known Limitations"** 섹션이 따로 없어서 외부 이용자가 도입 결정 단계에서 한 눈에 못 봄.
- **production_trigger**: 2개 이상 호출 서비스가 도입할 때 "어떤 서비스가 보낸 건지" 추적 불가능 → 사고 추적 어려움.
- **what_happens_now**: `X-Request-ID` 로 분산 트레이싱은 되지만, "발송 주체(caller identity)" 차원의 라벨링은 없음. 운영자가 caller 별 메트릭 분리 필요시 자체 구현.
- **severity**: P2
- **fix_required**: README 끝부분 `## Known Limitations` 섹션 신설.
- **suggested_content**:
  ```
  ## Known Limitations (v0.3.0)

  - **단일 API 키**: 호출자별 키 분리 미지원. 리버스 프록시에서 분리하거나 인스턴스 다중 기동 필요.
  - **No idempotency key**: 중복 요청 검출 미지원. Webhook 콜백은 `attempts` 필드로 재시도 횟수만 제공.
  - **No application-level rate limit**: 동일 키로 무한 호출 가능. 앞단 프록시에서 제한.
  - **No queue / persistence**: 인-플라이트 메일은 메모리 only — 프로세스가 죽으면 webhook 콜백 못 옴 (메일 자체는 SMTP 에 위탁됨).
  - **단일 SMTP backend**: 다중 SMTP 서버 fail-over 미지원.
  - **Webhook retry 메모리 only**: 재시도 큐가 프로세스 메모리에 있어 재기동 시 손실.
  ```

---

### F-003 · API_KEY 만료 정책 부재

- **category**: 1 (권한)
- **doc_gap**: 키 만료 / 발급 시점 / 사용 추적이 전무. 정적 환경변수 한 개.
- **production_trigger**: 컴플라이언스 감사 시 "키를 마지막으로 회전한 날짜" 답변 불가.
- **what_happens_now**: 외부 secret store(Vault, AWS Secrets Manager) 로 보관 + 그 쪽 회전 정책에 의존하는 게 사실상 유일한 방법. README 미언급.
- **severity**: P2
- **fix_required**: README `## 보안 및 운영 주의사항` 에 한 줄 + Known Limitations.
- **suggested_content**:
  ```
  - **API_KEY 만료/감사 미지원**: 본 패키지는 키 발급일·마지막 사용 시각을 기록하지 않는다. 컴플라이언스가 요구되면 외부 secret manager (Vault, AWS Secrets Manager) 에서 보관·회전하고, 회전 절차는 위 "API Key Rotation" 을 따른다.
  ```

---

### F-004 · SMTP 다운 / 장기 outage 시 runbook 부재

- **category**: 2 (장애)
- **doc_gap**: `502` 에러 의미와 재시도 동작은 README에 있으나, **"SMTP 가 30분 이상 다운됐을 때 무엇을 봐야 하고 무엇을 해야 하는지"** 절차가 없음.
- **production_trigger**: SMTP provider (Gmail, SES, SendGrid 등) outage. `email_send_total{result="failure"}` 알람이 울림.
- **what_happens_now**: 운영자는 (a) Prometheus 메트릭에서 error_code 분포 확인, (b) `EMAIL_SERVICE_DEBUG` 켜고 싶지만 보안 경고 때문에 못 켬, (c) `EMAIL_TEST_CAPTURE_DIR` 로 우회는 가능하나 절차 미문서. **메일은 그동안 흘리는 중**.
- **severity**: P0 (메일 손실 직결)
- **fix_required**: `docs/runbooks/smtp-outage.md` (또는 README 내 섹션).
- **suggested_content**:
  ```
  ### SMTP Outage Response

  **신호**: `email_send_total{result="failure",error_code="smtp_connection"}` 또는 `smtp_timeout` 급증.

  **즉시 대응 (분 단위)**:
  1. SMTP provider status page 확인 (Gmail/SES/SendGrid status URL).
  2. `curl -v telnet://$SMTP_HOST:$SMTP_PORT` 로 TCP 연결 확인.
  3. 발송 시도 일시중단이 가능하면 호출 서비스에서 backoff 강제 (email-service 자체는 큐 없음).
  4. 1차 SMTP 가 장시간 다운이면 환경변수 교체 + 재기동으로 2차 provider 로 전환:
     ```
     export SMTP_HOST=backup-smtp.example.com
     export SMTP_USER=...
     export SMTP_PASSWORD=...
     docker compose restart email-service
     ```

  **잔여 영향**: 다운 기간 동안의 발송 시도는 메일 손실 (큐 없음). webhook 콜백은 `status: failed`, `error_code: smtp_connection` 으로 호출자에게 통지됨 → 호출자가 자체 재시도 책임.

  **회복 후**: `email_send_total{result="success"}` 가 정상치로 복귀했는지 5분 관찰.
  ```

---

### F-005 · Webhook 타겟 죽음 / 미배달 대응 절차 부재

- **category**: 2, 3 (장애 + 데이터)
- **doc_gap**: README 168줄 — webhook 전달은 `(1s, 10s, 60s)` 3회 재시도 후 포기, 메트릭 증가. **그 이후 호출자가 어떻게 결과를 알아내야 하는지** 미문서. 인-메모리 큐이므로 프로세스 재시작 시 전부 손실.
- **production_trigger**: webhook 수신 서비스 5분 이상 다운 → 그 시간 발송된 모든 webhook 콜백은 메모리에 in-flight → 재기동 시 전부 소실 → **호출자는 메일이 발송됐는지 영영 모름**.
- **what_happens_now**: 운영자가 발견할 수단은 `email_webhook_failed_total` 카운터뿐. 어떤 message_id가 미전달인지 식별 불가. 대응 매뉴얼 없음.
- **severity**: P0 (상태 일관성 깨짐)
- **fix_required**: README "Webhook 콜백" 섹션에 **"Delivery guarantees"** 명시 + Known Limitations 추가 + runbook.
- **suggested_content**:
  ```
  #### Webhook Delivery Guarantees (중요)

  - **At-most-3 delivery, in-memory queue**: 본 패키지는 webhook 재시도 큐를 프로세스 메모리에서 관리한다.
    - 3회 재시도 모두 실패 → `email_webhook_failed_total` 증가, **메시지 손실**.
    - 프로세스 재기동 (배포/크래시) → 인-플라이트 재시도 큐 **전부 손실**.
  - **호출자 측 대응**: webhook 미수신을 견디는 설계 필요. 권장:
    1. webhook 수신 후 `message_id` 로 idempotent 처리.
    2. 일정 시간(예: 5분) 내 webhook 미도착 시 호출자가 발송 상태를 `unknown` 으로 간주.
    3. 사용자 영향 큰 메일(매직링크 등)은 sync `/send` 호출 사용 권장.

  영구 큐(Redis/RabbitMQ 기반 dead-letter)는 로드맵 외이며, 필요 시 호출자가 자체 ack 인프라 구성.
  ```

  추가 runbook:
  ```
  ### Webhook Sink Outage

  **신호**: `email_webhook_failed_total` 급증.

  **즉시 대응**:
  1. webhook 타겟의 health 확인.
  2. email-service 재기동 **금지** (인-플라이트 큐 손실됨).
  3. 호출자에게 "webhook 미수신 가능성" 통지, 메일 자체는 발송됐음을 알림 (메일 본문은 SMTP 위탁 완료).
  4. 타겟 복구 후 신규 발송분은 정상 동작.

  **잔여 영향**: 다운 기간 발송분 중 일부는 webhook 미수신 → 호출자 측 idempotent 보정 의존.
  ```

---

### F-006 · Rate limit 도달 시 대응 부재

- **category**: 2 (장애)
- **doc_gap**: SMTP provider (예: SES 14 msg/sec 한도, Gmail 일 한도) 에 도달하면 어떤 error_code 가 나오고 어떻게 대응할지 미문서.
- **production_trigger**: 마케팅 캠페인 트리거, 회원가입 폭주.
- **what_happens_now**: `smtp_transient` 또는 `smtp_connection` 으로 떨어지지만 매핑이 명확하지 않음. 자동 backoff는 라이브러리 모드 `max_retries` 만 동작 — HTTP 모드의 webhook 비동기 경로에서는 호출자가 책임.
- **severity**: P1
- **fix_required**: README "Operations" 섹션 + Known Limitations.
- **suggested_content**:
  ```
  ### SMTP Provider Rate Limits

  본 패키지는 application-level rate limit 이 없으므로 SMTP provider 한도가 사실상 throttle.

  - Gmail: `421` / `4.7.0` → `error_code: smtp_transient` 또는 `smtp_connection`.
  - SES: `Throttling` (454) → 동일.

  대응:
  1. 호출자 측 token bucket 등으로 발송 속도 제한 (권장).
  2. 라이브러리 모드: `SmtpSender(max_retries=3, backoff_seconds=(5, 30, 120))` 로 자동 백오프.
  3. HTTP 모드: 502 응답 + `error_code` 확인 → 호출자 큐에서 재시도.
  ```

---

### F-007 · In-flight 메일 손실 시나리오 미문서

- **category**: 3 (데이터)
- **doc_gap**: 비동기 webhook 모드에서 "요청은 받고 (202 accepted) → SMTP 발송 중 프로세스 재시작" 시 무슨 일이 일어나는지 명시 없음.
- **production_trigger**: 배포, OOM kill, 노드 재부팅.
- **what_happens_now**: 사용자/호출자는 `accepted` 응답을 받았으나 메일은 안 나가고 webhook도 안 옴. 영구 손실. 추적 불가능.
- **severity**: P0 (silent data loss)
- **fix_required**: README "Webhook 콜백" 섹션 + Known Limitations.
- **suggested_content**:
  ```
  > ⚠️ **In-flight 손실 주의**: `webhook_url` 을 사용한 비동기 발송은 FastAPI `BackgroundTasks` 위에서 동작하므로, 프로세스가 재기동되면 in-flight 메일 (SMTP 호출 시작 전) 은 손실된다. 배포/크래시 직후 일정 윈도우의 발송은 webhook 도 받지 못한다. Zero-loss 가 필요하면 sync `/send` 를 사용하거나 호출자 측 큐 (Redis/Kafka) 를 앞단에 둔다.
  ```

---

### F-008 · PyPI 배포 절차 / 권한 문서화 누락

- **category**: 4 (운영)
- **doc_gap**: `.github/workflows/release.yml` 의 주석에만 "Trusted Publisher 등록" 한 줄. **누가** 무엇을 등록했는지, 첫 배포 절차, 태그 푸시 절차, 실패 시 대응이 CONTRIBUTING/README 어디에도 없음.
- **production_trigger**: 메인테이너 변경, 또는 첫 배포 시.
- **what_happens_now**: 메인테이너가 부재중이거나 인수인계 시 PyPI 권한과 GitHub Trusted Publisher 설정을 추측해야 함.
- **severity**: P1
- **fix_required**: CONTRIBUTING.md `## Release process` 신설 또는 `docs/release.md`.
- **suggested_content**:
  ```
  ## Release process

  배포는 git tag 푸시로 자동화. 수동 PyPI 업로드 금지.

  **사전 1회 설정 (메인테이너만)**:
  1. PyPI 에서 프로젝트 `email-service` 소유권 보유.
  2. PyPI > Project > Publishing > Trusted publisher: GitHub repo `hwan96-ai/email-service`, workflow `release.yml`, environment `pypi` 등록.
  3. GitHub 리포 Settings > Environments > `pypi` 생성, "Required reviewers" 권장.

  **정기 릴리스**:
  1. `master` 에서 모든 PR 머지 완료, CI green.
  2. `pyproject.toml` `version` 과 `CHANGELOG.md` 의 헤딩이 일치하는지 확인.
  3. tag: `git tag v0.3.1 && git push origin v0.3.1`.
  4. GitHub Actions `release` 워크플로우 진행 확인.
  5. PyPI 페이지에서 새 버전 노출 확인 (`pip index versions email-service`).
  6. README 의 install snippet 으로 smoke test.

  **권한 분리**: PyPI Trusted Publisher 외에는 어떤 API 토큰도 GitHub Secrets 에 두지 않는다.
  ```

---

### F-009 · 잘못된 배포 시 롤백 / yank 절차 누락

- **category**: 4, 5 (운영, 복구)
- **doc_gap**: PyPI 는 `yank` 만 가능하고 동일 버전 재업로드 불가능. 이 제약과 대응 절차가 어디에도 없음.
- **production_trigger**: 0.3.1 배포 후 critical bug 발견.
- **what_happens_now**: 메인테이너가 PyPI 정책을 따로 학습해야 함. yank 와 새 패치 버전 발행 모두 처음 해보는 경우 시간 소요.
- **severity**: P1
- **fix_required**: 위 release.md 에 이어서.
- **suggested_content**:
  ```
  ## Rollback / Hotfix procedure

  PyPI 는 동일 버전 재업로드를 허용하지 않는다. "롤백" 은 (a) yank + (b) hotfix 패치 버전 발행이다.

  **0.3.1 (방금 배포) 가 깨졌을 때**:
  1. PyPI > 해당 릴리스 > "Yank release". 이유 명시. 기존 `pip install email-service==0.3.1` 은 계속 동작하지만 new resolve 에서는 skip 됨.
  2. `git revert <bad-commit>` 또는 fix 작성 → PR → merge.
  3. `CHANGELOG.md` 에 `## [0.3.2]` 추가, yanked 0.3.1 의 영향과 fix 내용 명시.
  4. `pyproject.toml` 버전을 `0.3.2` 로 bump.
  5. `git tag v0.3.2 && git push origin v0.3.2` → 자동 배포.
  6. 호출자에게 `pip install --upgrade email-service` 안내 (긴급도에 따라).

  **이미 운영에 배포된 호출 서비스는?** PyPI yank 만으로는 영향 없음 (이미 wheel 다운로드 완료). 호출자 측 dependency pin 업데이트 + 재배포 필요. SLA 가 있으면 호출자 통지 (CHANGELOG + GitHub Release notes 첨부).
  ```

---

### F-010 · 핫픽스 브랜치 전략 / 백포팅 절차 미문서

- **category**: 4, 5 (운영, 복구)
- **doc_gap**: 현재 `master` 단일 브랜치. 만약 0.3.x 와 다음 minor 0.4.x 가 병존하면 어떻게 핫픽스를 0.3 라인에 백포팅할지 미정의.
- **production_trigger**: 0.4.0 출시 후 0.3.x 사용자가 보안 fix 요청.
- **what_happens_now**: 절차 없음 → 메인테이너 판단.
- **severity**: P3 (지금은 minor 1개 라인뿐)
- **fix_required**: 위 release.md 끝부분 또는 후속 작업.
- **suggested_content**: "현재 단일 라인만 지원. 다중 minor 지원이 필요해지면 `release/0.x` 브랜치 모델 도입."

---

### F-011 · 알람 임계값 / 알림 채널 문서화 미흡

- **category**: 6 (모니터링)
- **doc_gap**: README 87줄에 `EmailFailureRateHigh` (실패율 5% 10분) 알람 예시 1개만 있음. 다른 메트릭(`email_webhook_failed_total`, `email_send_active`, `email_send_duration_seconds` p99) 에 대한 권장 임계값/알람 미정의.
- **production_trigger**: 운영팀이 grafana 대시보드를 처음 만들 때.
- **what_happens_now**: 운영자가 임계값을 추측해서 설정. 알람 폭주 또는 무알람 가능.
- **severity**: P2
- **fix_required**: README "Operations" 의 "권장 알람" 확장.
- **suggested_content**:
  ```
  ### 권장 알람 (Prometheus)

  ```yaml
  groups:
  - name: email-service
    rules:
    - alert: EmailFailureRateHigh
      expr: rate(email_send_total{result="failure"}[5m]) / rate(email_send_total[5m]) > 0.05
      for: 10m
      annotations: { summary: "email-service failure ratio > 5% for 10m" }

    - alert: EmailSendLatencyHigh
      expr: histogram_quantile(0.99, rate(email_send_duration_seconds_bucket[5m])) > 5
      for: 5m
      annotations: { summary: "p99 SMTP send latency > 5s" }

    - alert: WebhookDeliveryFailing
      expr: increase(email_webhook_failed_total[10m]) > 0
      for: 0m
      annotations: { summary: "webhook delivery to caller failing — data loss risk" }

    - alert: EmailSendStalled
      expr: email_send_active > 50
      for: 5m
      annotations: { summary: "many in-flight sends — possible SMTP hang" }

    - alert: AuthFailureSpike
      expr: increase(email_send_total{error_code="smtp_auth_failed"}[15m]) > 0
      for: 0m
      annotations: { summary: "SMTP AUTH failed — credentials rotated or wrong" }
  ```
  ```

---

### F-012 · 로그 수집 위치 / 표준 라벨 미정의

- **category**: 6 (모니터링)
- **doc_gap**: `EMAIL_SERVICE_LOG_FORMAT=json` 만 언급. 어디로 보내는지 (stdout/stderr) , log shipper 권장 (filebeat/vector), 표준 필드 스키마 미문서.
- **production_trigger**: Loki/ELK 통합 시.
- **what_happens_now**: 운영자가 코드 읽고 추측.
- **severity**: P2
- **fix_required**: README "구조화 로그" 섹션 확장.
- **suggested_content**:
  ```
  **로그 출력**: stdout (FastAPI/uvicorn 기본). 컨테이너 환경에서는 `docker logs` 또는 sidecar (filebeat, vector, fluentbit) 로 수집.

  **표준 필드**:
  | 필드 | 타입 | 예시 |
  |---|---|---|
  | `event` | string | `email.send.success`, `email.send.failure` |
  | `request_id` | string | `trace-abc-123` |
  | `to_hash` | string | `a3f9b1c2` (SHA-256 prefix 8) |
  | `error_code` | string | `smtp_timeout` |
  | `duration_ms` | int | `412` |
  | `message_id` | string | `<...@host>` |
  | `attempts` | int | `2` |

  PII (수신자 평문) 는 절대 로그에 남지 않는다.
  ```

---

### F-013 · 헬스체크 종류 / liveness vs readiness 구분 누락

- **category**: 6 (모니터링/k8s)
- **doc_gap**: `/health` 하나만 있음. k8s 도입 시 liveness/readiness 분리 권장사항이 누락. SMTP 연결성을 체크하지 않으므로 SMTP 가 죽어도 `/health` 는 200 반환.
- **production_trigger**: k8s 배포, SMTP outage 시 트래픽 차단 시도.
- **what_happens_now**: SMTP outage 시에도 `/health` 200 → LB 가 트래픽 계속 보냄 → 모든 호출이 502.
- **severity**: P2
- **fix_required**: README "Docker 로 실행" + Known Limitations.
- **suggested_content**:
  ```
  ### Health check 한계

  `GET /health` 는 프로세스 살아있음만 확인하는 **liveness** 만 수행. SMTP 연결성은 검증하지 않으므로 SMTP 다운 시에도 200 반환. k8s readiness probe 로 SMTP 헬스를 반영하려면 외부 sidecar 가 메트릭 `email_send_total{result="failure"}` rate 로 판단하거나, `/send` dry-run 으로 합성 모니터링 구성.
  ```

---

### F-014 · 에러 코드 전체 레퍼런스 분산

- **category**: README 자체 검토
- **doc_gap**: error_code 목록이 README 64줄 (metrics 라벨), CHANGELOG 18줄 (상수 export) 두 곳에 있고, **각 코드의 의미·유저 액션·재시도 여부**를 정리한 단일 레퍼런스 테이블이 없음.
- **production_trigger**: 호출자가 502 응답 받고 `error_code` 분기 처리할 때.
- **what_happens_now**: 코드 읽거나 추측.
- **severity**: P1
- **fix_required**: README 신설 `## Error code reference` 표.
- **suggested_content**:
  ```
  ## Error code reference

  | error_code | 의미 | HTTP | 재시도 가능? | 일반 대응 |
  |---|---|---|---|---|
  | `crlf_in_header` | 헤더에 CR/LF 포함 (인젝션 시도) | 422 | No | 입력값 검증 추가 |
  | `smtp_auth_failed` | SMTP AUTH 실패 | 502 | No | `SMTP_USER`/`SMTP_PASSWORD` 확인 |
  | `smtp_connection` | TCP 연결 실패 | 502 | Yes (backoff) | provider status 확인 |
  | `smtp_timeout` | 응답 타임아웃 | 502 | Yes (backoff) | `SmtpConfig.timeout` 증가 또는 재시도 |
  | `smtp_transient` | SMTP 4xx (rate limit 등) | 502 | Yes (backoff) | 호출 속도 throttle |
  | `recipient_refused` | 모든 수신자 거부 | 502 | No | 주소 확인 |
  | `starttls_unsupported` | STARTTLS 미광고 | 502 | No | provider 변경 또는 `SMTP_USE_TLS=false` (위험) |
  | `template_not_configured` | `MAGIC_LINK_BASE_URL` 누락 | 503 | No | 환경변수 설정 |
  | `unknown` | 위 어디에도 안 맞음 | 502 | Maybe | 로그로 raw 예외 확인 |
  ```

---

### F-015 · 환경변수 전체 레퍼런스 분산

- **category**: README 자체 검토
- **doc_gap**: 환경변수가 README 안에서 4곳에 흩어져 있음 — Operations 50줄(메트릭 2개), 89줄(로그 2개), 130줄(test capture 1개), 670줄(필수 4개), 682줄(선택 6개). **합쳐서 단일 표가 없음**.
- **production_trigger**: 운영자가 helm chart / terraform secrets 작성할 때.
- **what_happens_now**: 운영자가 README 전체 검색.
- **severity**: P2
- **fix_required**: README "환경변수" 섹션을 단일 통합 표로 재구성.
- **suggested_content**: 기존 두 표 + `METRICS_ENABLED`, `METRICS_REQUIRE_AUTH`, `EMAIL_SERVICE_LOG_FORMAT`, `EMAIL_SERVICE_DEBUG`, `EMAIL_TEST_CAPTURE_DIR` 통합. 컬럼: 이름 / 범주 (필수/관측/테스트) / 기본값 / 설명 / 보안 영향.

---

### F-016 · 한국어/영어 혼재 — i18n 안내 없음

- **category**: README 자체 검토
- **doc_gap**: README 본문은 한국어, 코드 주석/CHANGELOG/CONTRIBUTING 은 영어. 영어 사용자가 도입할 때 진입 장벽. README 자체에 "English version is in CHANGELOG / docstrings" 등의 안내 없음.
- **production_trigger**: 영어권 외부 이용자가 PyPI 검색으로 도착.
- **what_happens_now**: README 첫 줄에서 한국어 보고 이탈 가능. PyPI long_description 가 한국어인지 확인 필요.
- **severity**: P2 (외부 공개 라이브러리로서)
- **fix_required**: 최소한 README 최상단에 한 줄 영어 요약 + `README.en.md` 또는 i18n 안내.
- **suggested_content**:
  ```
  > 🌏 **English speakers**: a concise English summary is provided in [README.en.md](README.en.md). All code-level docstrings, error messages, and CHANGELOG are in English. Korean README below.
  ```

---

### F-017 · CHANGELOG "Unreleased" 섹션 미관리

- **category**: CHANGELOG 검토
- **doc_gap**: Keep a Changelog 컨벤션의 핵심인 `## [Unreleased]` 섹션이 없음. 다음 변경사항을 어디에 기록할지 불명확.
- **production_trigger**: 다음 PR 머지 시.
- **what_happens_now**: 메인테이너가 PR 머지할 때마다 직접 판단 → 누락 위험.
- **severity**: P3
- **fix_required**: CHANGELOG 상단에 `## [Unreleased]` 추가, CONTRIBUTING 의 PR checklist 에 "CHANGELOG Unreleased 에 항목 추가" 추가.
- **suggested_content**:
  ```
  ## [Unreleased]

  ### Added
  -

  ### Changed
  -

  ### Fixed
  -
  ```

---

### F-018 · BREAKING change 마커 일관성

- **category**: CHANGELOG 검토
- **doc_gap**: 0.3.0 의 `### Changed (BREAKING)` 는 좋은 시그널인데, 0.1.x → 0.3.0 점프 자체가 semver 상 매우 큰 변경 (0.2.0 태그 충돌로 인한 rename 이긴 하나). 또한 `SmtpSender.send` 의 반환 타입 변경은 major bump 신호인데 0.x 라인이라 minor 로 간주. 외부 이용자에게는 혼란 가능.
- **production_trigger**: 호출자가 0.1.x → 0.3.0 업그레이드 시.
- **what_happens_now**: Migration 섹션 있으나 README 에서 링크되지 않아 발견 어려움. README 의 "사용 방식" 표에서 버전 가이드 누락.
- **severity**: P2
- **fix_required**: README 최상단 또는 "사용 방식" 표 위에 "Upgrading from 0.1.x" 박스 + CHANGELOG migration 으로 링크. semver 정책 명시 ("0.x 라인은 minor 가 breaking 일 수 있음").
- **suggested_content**:
  ```
  > ⬆️ **0.1.x → 0.3.0 업그레이드**: `SmtpSender.send` 의 반환 타입이 `bool` → `SendResult` 로 변경되었다. `__bool__` 호환으로 대부분 코드는 그대로 동작하지만, 새 `error_code` 분기를 권장한다. 자세히는 [CHANGELOG Migration](CHANGELOG.md#migration-01x--030).

  > **Versioning**: 0.x 라인에서는 minor 가 breaking change 를 포함할 수 있다 (semver 0.x 관례). breaking 은 CHANGELOG 에 `(BREAKING)` 라벨로 표기.
  ```

---

### F-019 · "5분 안에 첫 메일" 실측 검증 필요

- **category**: README 자체 검토
- **doc_gap**: "30초 안에 첫 메일" 섹션 존재 (212줄) — Gmail 앱 비밀번호 필요. 실제로 신규 사용자가 Gmail 앱 비밀번호 발급 + 2FA 설정까지 포함하면 **30초로 절대 안 됨** (최소 5-10분). 라벨이 과장.
- **production_trigger**: 신규 도입 시 첫 인상.
- **what_happens_now**: 사용자가 신뢰 잃음 또는 Mailpit 으로 우회하라는 인상.
- **severity**: P3
- **fix_required**: 섹션명을 "30초 만에 SMTP 설정 확인" 또는 "한 줄 발송" 으로 변경, 또는 Mailpit 기반 30초 경로를 primary로.
- **suggested_content**: 섹션 제목 수정 + "Gmail 앱 비밀번호 발급 절차는 별도 5분 소요" 한 줄 명시.

---

### F-020 · async 사용 예 README 노출 부족

- **category**: README 자체 검토
- **doc_gap**: CHANGELOG 에 `AsyncEmailServiceClient` 등장하나 README 에는 미언급. async 호출 예시 없음.
- **production_trigger**: async 서비스 (FastAPI, aiohttp) 가 도입.
- **what_happens_now**: 사용자가 코드/`examples/` 봐야 함.
- **severity**: P2
- **fix_required**: README "Python 클라이언트 SDK" 섹션에 async variant 한 블록.
- **suggested_content**:
  ```
  ### Async client

  ```python
  from email_service.async_client import AsyncEmailServiceClient

  async with AsyncEmailServiceClient("http://email-service:8000", "secret") as c:
      await c.send_otp("user@example.com", "홍길동", "482901")
  ```
  ```

---

### F-021 · 합성 모니터링 / canary 절차 없음

- **category**: 6 (모니터링)
- **doc_gap**: 발송 경로의 end-to-end 합성 점검 (예: 5분마다 dry-run + 매시간 실제 메일 발송 후 IMAP 으로 수신 확인) 권장 없음.
- **production_trigger**: SMTP 가 광고된 prot로는 응답하지만 실제 메일이 도착 안 하는 "soft outage".
- **what_happens_now**: 사용자 신고 시까지 감지 불가.
- **severity**: P2
- **fix_required**: README "Operations" 의 새 subsection "Synthetic monitoring".
- **suggested_content**:
  ```
  ### Synthetic monitoring (권장)

  메트릭이 healthy 여도 실제 메일이 inbox 에 도달하지 않는 case 가 있다 (DNS, DKIM, spam filter). 1시간 주기 합성 검사:

  1. cron: `curl -X POST /send -H "X-Dry-Run: true" ...` (validation only) — 5분 주기.
  2. cron: 실제 mailbox 로 발송 후 IMAP/POP3 로 30초 내 수신 확인 — 1시간 주기.
  3. 실패 시 PagerDuty/Slack 알람.
  ```

---

## README 추가 검토 결과

| 점검 항목 | 상태 | 비고 |
|---|---|---|
| 5분 안에 첫 메일 | ⚠️ 부분 | Mailpit 경로는 30초 OK. Gmail 경로는 앱 비밀번호 발급 시간 미포함. |
| 환경변수 전체 레퍼런스 | ❌ | 4곳 분산 (F-015). |
| 에러 코드 문서화 | ⚠️ | 메트릭 라벨에 코드만 있고 의미·재시도 정책표 없음 (F-014). |
| API 예시 (curl/python sync/python async) | ⚠️ | curl/sync OK, async 없음 (F-020), Node.js 있음. |
| 알려진 제약/한계 | ❌ | 단편적으로 흩어져 있음. 단일 섹션 필요 (F-002). |
| 한국어/영어 i18n 안내 | ❌ | F-016. |

## CHANGELOG 검토 결과

| 점검 항목 | 상태 | 비고 |
|---|---|---|
| Semver 준수 | ⚠️ | BREAKING 마커 OK, 0.x semver 정책 미명시 (F-018). |
| 0.3.0 ↔ README 일치 | ✅ | 대체로 일치. SendResult, error_code, webhook, async client 등 반영. |
| Unreleased 섹션 관리 | ❌ | 부재 (F-017). |
| 0.2.0 rename 설명 | ✅ | 5줄에 명시. |
| Migration guide | ✅ | 62-94줄. README 에서 발견 어려움 (F-018). |

---

## 종합 평가

- **operational_readiness_score**: **4 / 10**
  - 라이브러리 코드 품질·관측 도구 (metrics, 구조화 로그, request-id, webhook signature) 는 **8/10** 수준.
  - 운영 절차 / runbook / 사고 대응 / 키 관리 / 배포-롤백 문서화는 **1-2/10**.
  - 가중평균 (운영 절차에 ×1.5): 약 4점. PyPI 외부 공개를 한 v0.3.0 으로서는 부족.

- **critical_runbooks_missing** (우선순위 순):
  1. **SMTP Outage Response** (F-004) — P0
  2. **Webhook Sink Outage / In-flight Loss Handling** (F-005, F-007) — P0
  3. **API Key Rotation** (F-001) — P1
  4. **PyPI Release & Rollback (yank + hotfix)** (F-008, F-009) — P1
  5. **SMTP Credential Rotation** (`SMTP_PASSWORD` 변경 절차) — P1, 본 보고서 미별도 항목 (F-001 와 묶을 수도 있음)
  6. **Deployment Procedure** (zero-downtime restart, webhook in-flight 보존 고려) — P1
  7. **Incident Postmortem Template** — P3

- **monitoring_gaps**:
  1. SMTP-aware readiness probe (`/health` 가 SMTP 검증 안 함, F-013).
  2. p99 latency 알람 (F-011).
  3. `email_webhook_failed_total` 알람 + dead-letter 로깅 (F-005).
  4. `smtp_auth_failed` 즉시 알람 (F-011).
  5. Synthetic end-to-end 발송 → 수신 확인 (F-021).
  6. Caller identity 라벨 (F-002) — 호출자별 분리 메트릭 불가.
  7. In-flight 메일 수명 / queue depth — `email_send_active` 만으로는 부족.
  8. 로그 표준 스키마 문서 (F-012).

- **chaos_test_candidates**:
  1. **SMTP blackhole**: SMTP 호스트로 가는 트래픽을 iptables 로 DROP. 기대: `smtp_timeout` 에러 발생, webhook 콜백에 `status: failed` 도달, 메트릭 정상 증가. 검증: `email_send_active` 가 timeout 후 0 으로 떨어지는가, `/health` 가 200 인 채로 트래픽 계속 받는가 (이게 F-013 의 핵심 위험).
  2. **Webhook sink kill + email-service restart**: webhook 수신 서비스를 죽이고 email-service 로 발송 요청 5건 → 즉시 email-service `docker compose restart`. 기대: 5건 모두 webhook 미수신 (in-memory 큐 손실 확인, F-005/F-007 증거 수집). 메트릭: `email_webhook_failed_total` 이 증가 안 함 (재시도 시도 자체가 잃어버려서).
  3. **API_KEY 회전 무중단 시나리오**: nginx 앞단에서 dual-auth 구성 → 새 키 발급 → 호출자 1개씩 키 교체 → 마지막에 email-service 의 키 교체. 기대: 전체 시퀀스 동안 401 응답률 0. 검증: F-001 의 제안 절차가 실제로 동작하는가.

- **top_5_doc_gaps_blocking_external_use**:
  1. **F-014: Error code reference table** — 호출자가 502 받았을 때 분기 처리 불가능 → 어떤 외부 통합도 robust 하게 안 됨.
  2. **F-002 / F-005 / F-007: Known Limitations + delivery guarantees** — 단일 키, in-memory webhook queue, in-flight 손실. 도입 결정 단계에서 알아야 함.
  3. **F-004 / F-005: SMTP/Webhook outage runbooks** — 첫 사고 시 대응 불가.
  4. **F-001 / F-008 / F-009: 키 회전 + 배포/롤백 절차** — 메인테이너 단일 의존, 외부 회사가 자기 환경에 도입할 때 거버넌스 통과 불가.
  5. **F-015: 환경변수 통합 레퍼런스** — helm/terraform 작성 시 누락 위험. 또한 F-016 한국어/영어 i18n 안내 부재로 PyPI 외부 검색 진입 장벽.

---

## 다음 조치 제안 (우선순위)

1. (P0, 1일 작업) README 에 `## Known Limitations`, `## Error code reference`, `## Operations Runbooks` (SMTP outage / webhook outage / in-flight loss) 3개 섹션 추가.
2. (P1, 0.5일) `docs/release.md` 신설 — release/rollback/hotfix 절차.
3. (P1, 0.5일) 환경변수 단일 표 통합 + 알람 룰 확장.
4. (P2, 후속) `README.en.md` 또는 영문 요약, `CHANGELOG.md` 의 `## [Unreleased]` 섹션.
5. (P2, 후속) k8s 헬스 probe 가이드 + synthetic monitoring 예시.
6. (P3) chaos test 3개를 `tests/chaos/` 또는 docs 에 시나리오로 명시.

이 6개를 끝내면 operational_readiness_score 7-8/10 도달 가능.
