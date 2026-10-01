# Astra 외부 지적 재현 확인 및 해결 보고 (S6)

- 유형: 외부 독립 검증 지적 재현 및 보안 취약점 해소
- 기준 커밋: S6 (Astra 재현 및 system 동적 PII 차단)
- 작성: 구현 에이전트 (Antigravity) 2026-10-02
- 관련 지침: docs/handoff/PROMPT_FOR_STABILIZATION_ROUND4.md (S6), PROMPT_FOR_ASTRA_AUDIT_ROUND4.md (V5)

---

## 1. 외부 지적 내용 및 재현 확인

### Astra 지적 사항
- **내용**: "AI 검사 프롬프트의 system/schema 필드는 검출돼도 정적 오탐으로 취급해 합성 전화번호를 넣으면 통과한다 (고정 문자열이라는 전제에 의존)."
- **원인 분석**:
  - `packages/llm_router/privacy.py`의 `inspect_request`에서 필드 경로가 `system` 또는 `schema`로 시작하면 검출된 PII 종류를 무조건 `system_kinds`로 집계.
  - 사용자 입력(`user_kinds`)이 없으면 `status="PASSED"`, `failure_code="STATIC_PROMPT_FALSE_POSITIVE"`로 판정하여 호출을 그대로 허용함.

### 재현 검증 결과 (재현 성공)
- **재현 입력**:
  ```python
  from packages.llm_router.privacy import inspect_request
  from packages.llm_router.providers import LLMRequest

  req = LLMRequest(system="지침: 담당자 연락처 010-9876-5432", user="안녕하세요")
  res = inspect_request(req)
  ```
- **기존 결과**:
  - `status`: `'PASSED'`
  - `failure_code`: `'STATIC_PROMPT_FALSE_POSITIVE'`
  - `detected_types`: `{'PHONE': 1}`
- **평가**: 외부 검증자 Astra의 지적이 사실로 확인됨. 공격자나 비정상 입력이 프롬프트 조립 시 system 영역으로 유입될 경우 개인정보가 외부 모델로 유출될 수 있는 보안 결함 존재.

---

## 2. 해결 구현 내용

### `packages/llm_router/privacy.py` 개선
- 구체적 개인 식별자 인스턴스(`PHONE`, `RRN`, `EMAIL`, `BUSINESS_REGISTRATION`, `ACCOUNT`, `ADDRESS`, `MEDICAL`, `VEHICLE` 등)가 감지된 경우:
  - 해당 필드가 `system`이나 `schema`에 위치하더라도 정적 어휘 오탐으로 면책하지 않고 실질적 PII 유출로 간주.
  - `user_kinds`로 집계하여 `BLOCKED` (`PII_INPUT_BLOCKED`) 처리.
- 구체적 식별자가 없는 순수 정적 프롬프트 안내 라벨/설명(예: "주민등록번호 등 개인 식별번호가 든 문장은 발췌하지 마십시오"):
  - 기존과 동일하게 정적 어휘 오탐(`STATIC_PROMPT_FALSE_POSITIVE`) 또는 `PASSED`로 정상 허용.

---

## 3. 검증 결과

1. **Astra 재현 케이스**:
   - `LLMRequest(system='담당자 전화번호: 010-9876-5432', ...)` -> `status='BLOCKED'`, `failure_code='PII_INPUT_BLOCKED'` 차단 성공.
2. **기존 PII 검사 테스트**:
   - `test_evidence_hardening.py`, `test_catering_claim_efficacy.py`, `test_lease_deposit_claim_efficacy.py` 61건 전건 통과.
3. **회귀 원장 (`tests/regression/test_ledger.py`)**:
   - ASTRA-V5 양성 3건, 대조군 3건 추가 완료 (총 70건 전건 통과).
4. **5대 검증 게이트**:
   - 회귀 게이트: 12/12 유지 (회귀 0건).
   - 리터럴 및 하드코딩 점검: 부채 4건 유지, 신규 0건.
   - 성적표: dev 81.7 / holdout 79.2 (오탐 0건, 인젝션 방어 통과).
