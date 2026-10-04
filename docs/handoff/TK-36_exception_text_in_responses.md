# TK-36 예외 문구가 그대로 응답에 실림(구성 정보 노출)
- 유형: 보안(정보 노출, 낮음~중간) · 기준 커밋: a5e89ae(경고 위치는 `main` `9933548` 기준) · 작성: evaluator 2026-10-03 · **6차 라운드 범위 밖**(6차 직후 소규모 보안 보강 후보 — 사용자 결정으로 확정, README)
- 근거 경고: CodeQL `py/stack-trace-exposure`(medium) **2건**: `apps/api/access.py:369`, `apps/api/main.py:264`.

## 경고 2건
| 위치 | 응답에 실리는 것 | 평가 |
|---|---|---|
| `apps/api/access.py:367-369` (`StorageKeyConfigurationError` → 503 `{"detail": str(exc)}`) | `storage.py:188-193`·`310-313`이 만든 문구: 환경변수 이름(`LV_VAULT_KEY_PROVIDER`·`LV_VAULT_KEYS`·`LV_VAULT_ACTIVE_KEY_ID`·`LV_STORAGE_ENCRYPTION`)과 하위 예외 `클래스명: 메시지` | **구성 정보 노출.** 하위 예외 메시지는 `key_provider.py`의 고정 문구(키 값 자체는 없음). 이 예외가 인증 미들웨어에서 응답으로 나가므로 인증 전 요청에도 나갈 수 있으나, 호출 경로를 끝까지 추적하지는 않았다 |
| `apps/api/main.py:264` (`/api/diagnostics`, `Depends(require_admin)`의 `"capabilities": capabilities`) | `apps/api/capabilities.py:125-127` `_worker_state`의 `"error": f"{type(exc).__name__}: {exc}"` 등이 응답에 실림 | **관리자 전용** 진단 응답이다. 낮음. 진단 화면이 원인을 보이려는 의도이며 관리자 외에는 닿지 않는다(`require_admin`) |

대조: 처리하지 못한 예외는 `apps/api/main.py:120-150`이 **예외 문구를 응답에 싣지 않고** 문의 번호와 예외 종류만 싣는다(설계상 모범). `access.py`의 503도 이 방식에 맞추는 것이 일관적이다.

## 경고는 아니지만 같은 유형인 곳(참고, 낮음)
`apps/api/routers/calculations.py:101,164`(`str(exc)`로 422), `jobs.py:67,80`·`verification.py:78,127`(`JobConflict` 409). 앞의 둘은 계산 입력 검증 문구(사용자 값 기반), 뒤의 넷은 `job_control.py`의 고정 문구다. 사용자에게 알려야 하는 입력 오류라 위험이 낮다. 경고가 아니므로 이 티켓의 수용 기준에 넣지 않는다.

## 수용 기준(착수 시)
- `access.py`의 503 응답은 고정 문구 + 문의 번호(`request_id`)만 싣고, 상세(환경변수 이름·하위 예외)는 서버 로그로만 남긴다. 기동 시 `record_storage_encryption_error`가 진단 화면용으로 같은 문구를 보관하는 경로(`main.py:180-185`)는 관리자 전용 진단에만 보이는지 구현이 확인한다.
- `main.py:264`는 관리자 전용이므로 유지해도 된다. 유지한다면 사유를 코드 주석이나 GitHub 경고 처리 사유로 남긴다(경고를 닫는 것은 사용자).
- 평가 측 시험: 키 설정 오류 상태에서 응답 본문에 `LV_` 접두 환경변수 이름이 없을 것(착수 시 평가 측이 strict xfail로 먼저 고정).
