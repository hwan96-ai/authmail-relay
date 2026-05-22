# Runbook: Public Deploy Readiness

운영 환경에 `authmail-relay` 를 인터넷 경유로 노출(또는 신뢰 경계 바깥의 caller 가 접근 가능한 URL 로 노출)하기 전 통과해야 하는 보안/안정성 체크리스트.

> **중요**: 저장소가 public-ready 라는 사실은 *코드/문서가 공개 가능하다* 는 뜻일 뿐이다. **deployed URL 의 public 노출이 안전하다는 의미가 아니다**. 본 runbook 의 게이트를 모두 통과한 뒤에만 실제 endpoint 를 공개한다.

## Purpose and scope

- 대상: `python -m authmail_relay` 로 띄운 HTTP 서비스 모드를 외부에서 접근 가능한 URL 뒤에 배치하는 모든 배포.
- 비대상: 라이브러리 모드(같은 프로세스 import) 사용. 내부망 only, mTLS/VPN 안에서만 접근 가능한 deploy 는 일부 항목 완화 가능 — 단 본 문서의 default 는 "interneten 노출" 기준.

## Public URL readiness decision rule

다음을 **모두 yes** 로 답할 수 있어야 public URL 노출 허용:

1. 모든 게이트 항목(아래)이 통과되어 있다.
2. 동일 환경에서 smoke test 가 최근 통과했다.
3. rollback 절차가 문서화되어 있고 1회 이상 dry-run 됐다.
4. on-call/owner 가 정해져 있고, 알림 채널이 연결되어 있다.

하나라도 no 면 **public URL 노출 금지**. 내부 노출/베타로 강등하거나 게이트 항목을 먼저 해결한다.

## TLS termination

- TLS 는 앞단 reverse proxy / API gateway / load balancer 에서 종료한다.
- uvicorn 자체에 직접 인증서를 묶어 `0.0.0.0:443` 으로 노출하지 않는다.
- 최소 TLS 1.2, 가능하면 1.3. 약한 cipher suite 비활성.
- HSTS 는 도메인 정책상 안전할 때만 활성 (잘못 켜면 rollback 어려움).
- 인증서 만료 모니터링 + 자동 갱신(Let's Encrypt / ACM 등) 필수.

## Reverse proxy / API gateway requirement

- **raw uvicorn / FastAPI 앱을 인터넷에 직접 노출하지 않는다.**
- 앞단에 nginx / Caddy / Envoy / API Gateway / managed LB 중 하나를 둔다.
- 앞단의 역할:
  - TLS termination
  - body-size cap
  - failed-auth rate limit / WAF
  - IP allowlist (필요 시)
  - `/docs`, `/openapi.json`, `/metrics` 같은 민감 경로 차단/제한
  - request/response 로그 (PII 주의)
- 앱은 loopback 또는 private network 에만 listen 한다(예: `127.0.0.1:8000`, 또는 컨테이너 internal network).

## Request body-size limits

- README 의 [Public deployment guardrails](../../README.md#public-deployment-guardrails) 와 일치해야 한다.
- nginx 예시: `client_max_body_size 12m;` (10 MB body + 2 MB overhead).
- gateway 마다 동등 옵션 적용 (Caddy `request_body { max_size 12MB }`, AWS ALB target group / Cloud Run request size 등).
- 이유: FastAPI 는 body 를 전체 메모리 buffer 후 Pydantic 검증. proxy 단 cap 이 없으면 memory DoS 가능.

## Failed-auth rate limiting

- 잘못된 `Authorization: Bearer` 토큰 시도는 **앞단 proxy / gateway / WAF** 에서 rate limit.
  - 앱 내부 `API_RATE_LIMIT_PER_MINUTE` 는 **인증된** `/send*` 호출에만 적용되므로 brute-force 토큰 탐색을 막지 않는다.
- 권장 패턴:
  - IP 단위 분당 N회 cap (예: 60/min).
  - 동일 IP 에서 401 비율이 임계치 초과 시 1~5분 차단.
- 가능하면 fail2ban / WAF 룰 / cloud 제공 bot protection 활용.

## Strong `API_KEY`

- 반드시 `openssl rand -hex 32` 또는 동등한 CSPRNG 출력값 사용.
- 길이/엔트로피 부족한 문자열, 사람이 외울 수 있는 비밀, 다른 시스템과 공유되는 비밀 금지.
- 절대 git, 로그, 이미지 layer, CI artifact, screenshot 에 노출 금지.
- 회전 절차: [`api-key-rotation.md`](api-key-rotation.md).

## Strong `WEBHOOK_SECRET`

- caller 가 webhook 결과 통보를 받는 경우, `webhook_secret` 도 `openssl rand -hex 32` 수준.
- caller 측은 **V2 timestamp 서명**을 검증해야 한다 (V1 은 replay 취약, 향후 제거 예정).
- 같은 secret 을 여러 caller 와 공유하지 않는다.

## SMTP credential handling

- `SMTP_PASSWORD` 는 절대 코드/문서/PR/issue 에 포함하지 않는다.
- 가능한 한 provider 의 app password / IAM SMTP credential 사용 (개인 계정 비밀번호 직접 사용 금지).
- 회전 가능성을 전제로 secret store 또는 배포 플랫폼 secret 으로 주입.
- `EMAIL_SERVICE_DEBUG=1` 은 **production 금지** — smtplib 가 SMTP 비밀번호를 stderr 에 base64 로 출력한다.

## Secrets / env var handling

- secret 은 다음 중 하나로만 주입:
  - 배포 플랫폼 secret manager (AWS Secrets Manager, GCP Secret Manager, k8s Secret + RBAC, fly.io secrets 등).
  - CI 가 보호된 env 에서 주입하는 환경변수.
  - `.env` 파일은 host 안에서만, 권한 600, git 밖.
- secret 을 image layer 에 굽지 않는다.
- 컨테이너 `env` 출력 / process listing / `/proc` 접근이 가능한 사용자 범위를 점검한다.
- 로그/메트릭에 secret 이 새는지 grep 검증.

## Webhook replay protection expectations

- 본 서비스는 V2 timestamp HMAC 서명을 함께 전송한다. caller 가 반드시 다음을 수행해야 한다:
  - `X-Email-Service-Timestamp` 와 현재 시각 차이가 5분 초과면 거부.
  - `X-Email-Service-Signature-V2` 를 constant-time 비교.
- caller 가 V1 only 면 replay 가능 — 마이그레이션 일정 합의 후 노출한다.
- webhook target 은 receiver 측에서 idempotent (caller 가 `message_id` 로 dedup) 해야 한다. 본 서비스는 영구 실패 webhook 을 DLQ 에 보관하지 않는다 ([`webhook-outage.md`](webhook-outage.md) 참고).

## Authenticated / internal-only metrics

- `METRICS_ENABLED=true` 인 경우 **반드시** `METRICS_REQUIRE_AUTH=true` 함께 설정.
- 가능하면 `/metrics` 는 앞단 proxy 에서 internal network / VPN / IP allowlist 로 제한.
- Prometheus scrape 도 동일 `API_KEY` 또는 별도 scrape-only credential 로 인증.
- public 인터넷 어디서든 익명으로 `/metrics` 가 보이면 안 된다.

## Log and PII safety

- 로그는 다음을 포함하지 않는다:
  - SMTP 비밀번호, `API_KEY`, `WEBHOOK_SECRET`, Authorization 헤더 raw 값.
  - 이메일 본문 (특히 매직링크 토큰).
- `EMAIL_SERVICE_LOG_FORMAT=json` 사용 시 구조화 필드 review.
- 수신자 이메일 주소는 PII — 보존 기간 정책에 맞춰 rotation/삭제.
- 외부로 logs 를 ship 한다면 데이터 거주(region)/접근 권한 확인.

## Health check behavior

- 앞단 LB / 오케스트레이터는 가벼운 health endpoint 만 호출.
- health check 가 SMTP 로 실제 메일을 보내는 형태가 되지 않도록 한다(비용/스팸/오발송).
- 인증되지 않은 health 경로가 노출된다면 그것이 정보 누출(버전, 환경, internal IP)을 일으키지 않는지 확인.
- health 실패 시 자동 재기동/롤아웃 정책 정의.

## CORS / public access assumptions

- `authmail-relay` 는 **server-to-server** 사용을 전제로 한다. 브라우저에서 직접 호출하는 모델 아님.
- CORS 를 열어 브라우저에서 `API_KEY` 를 그대로 사용하면 키 노출 — 금지.
- 정말 필요한 경우는 frontend 가 자체 backend 를 통해 proxy 하는 패턴만 사용.
- `/docs` / `/openapi.json` 공개 필요 없다면 앞단에서 차단.

## Backup / rollback plan

- 배포 직전 마지막 known-good 이미지/태그/commit 을 기록한다.
- rollback 명령(예: `kubectl rollout undo`, `fly releases rollback`, blue/green switch) 은 미리 dry-run.
- 환경변수 변경은 별도 commit 으로 추적 가능해야 한다.
- DB 가 없는 서비스이므로 schema rollback 부담은 없지만, secret rotation 중간 상태(이중 키 적용 등)는 [`api-key-rotation.md`](api-key-rotation.md) 절차 참고.
- 인시던트 시 빠른 차단을 위해 앞단 proxy 에서 traffic 0% 로 떨어뜨릴 수 있는 토글을 준비.

## Smoke test checklist

배포 직후 다음을 순서대로 확인:

- [ ] `curl -i https://PUBLIC_URL/health` (또는 동등) → 정상 응답, TLS 검증 OK.
- [ ] `curl -i -H "Authorization: Bearer WRONG"`  → `401`, body 에 stack trace 없음.
- [ ] `curl -i -H "Authorization: Bearer $API_KEY"` 정상 발송 1건 → 수신함 확인.
- [ ] 본문 12 MB 초과 요청 → 앞단 proxy 가 `413` 응답.
- [ ] `/metrics` 익명 호출 → `401` 또는 `404` (configuration 에 따라). 절대 200 + 데이터 노출 아님.
- [ ] 로그에 SMTP 비밀번호 / API_KEY / 본문 토큰이 새지 않는지 grep.
- [ ] webhook end-to-end: caller 가 V2 서명 검증 성공.
- [ ] failed-auth 반복 시도 → 앞단 rate limit / 차단 동작 확인.

## Go / no-go checklist

배포 책임자가 sign-off 하기 전 모두 ✅ 여야 한다.

- [ ] TLS 종료가 앞단에서 수행되고 인증서 만료 모니터링이 있다.
- [ ] uvicorn/FastAPI 가 인터넷에 직접 노출되어 있지 않다.
- [ ] 앞단에 body-size cap 이 설정되어 있다.
- [ ] failed-auth rate limit (proxy/WAF) 이 활성화되어 있다.
- [ ] `API_KEY` 가 강한 랜덤이며 git/로그/이미지에 없다.
- [ ] `WEBHOOK_SECRET` 이 강한 랜덤이며 caller 가 V2 서명을 검증한다.
- [ ] SMTP credential 이 secret store 에서 주입된다.
- [ ] `EMAIL_SERVICE_DEBUG` 가 production 에서 꺼져 있다.
- [ ] `/metrics` 가 인증 또는 내부망 한정으로만 접근 가능하다.
- [ ] `/docs`, `/openapi.json` 노출 정책이 의도적이다.
- [ ] 로그에 secret/PII 누출 검증을 마쳤다.
- [ ] health check 가 발송을 트리거하지 않는다.
- [ ] CORS 가 server-to-server 가정에 맞게 설정되어 있다.
- [ ] rollback 절차가 문서화되고 dry-run 됐다.
- [ ] smoke test 체크리스트가 통과했다.
- [ ] on-call / 알림 채널이 연결되어 있다.

하나라도 ❌ 면 public 노출 보류.

## Reminder

> **공개 저장소 readiness ≠ deployed URL readiness.**
> 이 두 가지는 별개의 게이트다. 코드/문서가 공개 가능한 상태라 해도, 실제 URL 의 공개 여부는 본 runbook 의 모든 항목을 통과한 뒤에만 결정한다.
