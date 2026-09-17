# 비동기 Worker (제3.1장)

검증 Job은 두 경로 중 하나로 실행된다. 어느 쪽이든 동일한 `execute_run()`을 호출하므로
Verification Core는 하나이다.

| 모드 | 조건 | 동작 |
|---|---|---|
| `inprocess` | 브로커 미설정 (기본) | API 프로세스의 데몬 스레드에서 실행 |
| `celery` | `LV_CELERY_BROKER` 설정 | Redis 큐를 통해 별도 워커 프로세스가 실행 |

`LV_WORKER_MODE`로 강제할 수 있다(`auto`·`celery`·`inprocess`).

## 실행

```bash
export LV_CELERY_BROKER='redis://localhost:6379/0'
export LV_DATABASE_URL='postgresql+psycopg://legal:비밀번호@localhost:5432/legal_verifier'
celery -A workers.celery_app worker -l info -Q verification,report --concurrency 2
```

## 설계상 유의점

- **프로듀서·컨슈머 분리** — API는 태스크 구현을 임포트하지 않고 `send_task("verification.run", ...)`로
  이름만 보낸다. 워커를 독립 배포·스케일할 수 있고, API 이미지에 분석 의존성이 없어도 된다.
- **Graceful Degradation** — 브로커 연결에 실패하면 인프로세스로 강등해 Job을 계속 처리한다.
  브로커 장애가 전체 기능 상실로 이어지지 않는다(제2장).
- **late ack + prefetch 1** — 문서 분석은 장시간 작업이므로 완료 후 ack하고, 워커당 하나씩만 선점한다.
  워커가 죽으면 다른 워커가 그 Job을 다시 가져간다.
- **경로 부트스트랩** — `celery` 콘솔 스크립트로 기동하면 `sys.path[0]`이 `.venv/bin`이 되어
  저장소 루트가 빠진다. 모듈 로드 시점과 태스크 실행 시점 양쪽에서 루트를 보장한다.

## 큐

| 큐 | 용도 |
|---|---|
| `verification` | 문서 검증 파이프라인 |
| `report` | 보고서 생성 (현재는 API에서 동기 처리) |
