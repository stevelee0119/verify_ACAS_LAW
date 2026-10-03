# TK-36 예외 문구가 그대로 응답에 실림(구성 정보 노출)
- 유형: 보안(정보 노출, 낮음~중간) · 기준 커밋: 028ca14 · 작성: evaluator 2026-10-03 · **6차 라운드 범위 밖**(6차 직후 소규모 보안 보강 후보 — 사용자 결정 대기)
- 근거 경고: CodeQL "Information exposure through an exception"(medium). 경고 위치는 읽지 못했다. 아래는 코드에서 **예외 문구를 응답 본문에 싣는 곳**을 찾은 후보다(7곳). 경고 건수와 일치하는지는 확인하지 못했다.

## 후보와 평가
| 위치 | 응답에 실리는 것 | 평가 |
|---|---|---|
| `apps/api/access.py:367-369` (`StorageKeyConfigurationError` → 503 `{"detail": str(exc)}`) | `storage.py:188-193`·`310-313`이 만든 문구: 환경변수 이름(`LV_VAULT_KEY_PROVIDER`·`LV_VAULT_KEYS`·`LV_VAULT_ACTIVE_KEY_ID`·`LV_STORAGE_ENCRYPTION`)과 하위 예외 `클래스명: 메시지` | **구성 정보 노출.** 하위 예외 메시지는 `key_provider.py`의 고정 문구(키 값 자체는 없음). 이 예외가 인증 미들웨어에서 응답으로 나가므로 인증 전 요청에도 나갈 수 있으나, 호출 경로를 끝까지 추적하지는 않았다 |
| `apps/api/routers/calculations.py:101`(`ValueError`), `:164`(`CalculationError`) → 422 | 계산 입력 검증 문구(사용자가 보낸 값 기반) | 사용자에게 알려야 하는 입력 오류 문구. 위험 낮음 — 단 `ValueError`는 어느 하위 호출이든 올릴 수 있어 문구 범위가 계산 모듈 밖으로 넓어질 수 있다 |
| `apps/api/routers/jobs.py:67,80`, `verification.py:78,127`(`JobConflict` → 409) | `job_control.py`의 고정 문구 | 내부 식별자·경로 없음(`JobConflict("…")` 호출 문구를 확인). 낮음 |

대조: 처리하지 못한 예외는 `apps/api/main.py:120-150`이 **예외 문구를 응답에 싣지 않고** 문의 번호와 예외 종류만 싣는다(설계상 모범). 위 후보도 이 방식에 맞추는 것이 일관적이다.

## 수용 기준(착수 시)
- `access.py`의 503 응답은 고정 문구 + 문의 번호(`request_id`)만 싣고, 상세(환경변수 이름·하위 예외)는 서버 로그로만 남긴다. 기동 시 `record_storage_encryption_error`가 진단 화면용으로 같은 문구를 보관하는 경로(`main.py:180-185`)와 관리자 진단 노출 범위는 구현이 정한다 — 관리자에게만 보이는지 확인 요청.
- 사용자에게 필요한 입력 오류(422/409)는 **알려진 예외 클래스의 고정 문구**만 싣는다(`ValueError` 포괄 포착 금지 후보: `calculations.py:101`).
- 평가 측 시험: 키 설정 오류 상태에서 응답 본문에 `LV_` 접두 환경변수 이름이 없을 것(착수 시 평가 측이 strict xfail로 먼저 고정).
