# FT 1단계 설계 보충 메모 (개정 1) — 행위시법 검토 보강(목 단위 대조 및 동일 시행일 복수 버전)

- **작성**: 구현 담당 에이전트 (Antigravity)
- **일자**: 2026-10-06
- **대상 티켓**: [PROMPT_FOR_FT.md](../PROMPT_FOR_FT.md), [TK-34](../TK-34_item_level_temporal_review.md), 요청 16
- **제출 목적**: FT 구현 전 설계 검토 및 평가 측 판정(PR #24 1~8) 보완 반영 (제품 코드 작성 전 설계 메모 전용)

---

## 1. 목(目) 단위 본문 대조 방식 (FT-a)

### 1.1 목 인식 정규식 및 일반 단어 오인식 방지
- 목 글자는 한글 법령 목 열거 글자(`가` ~ `하`)로 한정하며, 반드시 호 표기("제N호" 또는 "N호")와 결합된 경우에만 인정합니다:
  ```python
  ITEM_SUBITEM_PATTERN = re.compile(r"(?:제?\s*(\d+)호)\s*(?:제?\s*([가-하])목)")
  ```
- '확인할 항목은'('항'), '주요 품목'('품'), '교과목'('과') 등 일반 명사는 호 표기가 선행하지 않으므로 목으로 오인식되지 않습니다. 호 표기 없이 "가목" 등으로 단독 인용된 경우도 목 단위 특정 대상에서 안전하게 제외합니다.

### 1.2 버전별 목 본문 분할 및 대조
- **목 분할 정규식**: 호 본문(`\n\s*\d+\.\s*`) 내부에서 목 열거 글자 집합(`[가-하]`)만을 대상으로 분할합니다:
  ```python
  SUBITEM_SPLIT_PATTERN = re.compile(r"\n\s*([가-하])\.\s*")
  ```
- **대조 기준**: 새로운 유사도 임계값을 도입하지 않고, 기존 `compare_claim_to_provision` 함수를 추출된 목 본문에 그대로 적용합니다.
- **분할 실패 시 폴백**:
  - 부존재 판정의 유일한 근거는 **"기준일 버전의 해당 호를 정상 분할하였으나, 청구 문언이 어느 목에도 부합하지 않을 때"**로 한정합니다.
  - 조문 비표준 서식 등으로 호·목 분할에 실패하거나 호를 찾지 못한 경우 목 단위 판정을 수행하지 않고, 기존 조·항 단위 경로의 결과를 그대로 유지합니다 (새 finding 생성 없음).

---

## 2. 번호만 바뀐 개정과 내용이 바뀐 개정의 구분 원칙 (오탐 방지)

- **번호만 바뀐 개정 (오탐 대조군)**:
  - 서면이 현행 목 번호(예: 파목)로 인용했더라도, 행위 당시 해당 조/호의 분할된 목들 중 청구 문언과 `compare_claim_to_provision` 일치(`VERIFIED`)하는 목(예: 당시 카목)이 존재한다면, 행위 당시 해당 실질 규범이 유효했으므로 **소급 적용 오류(`RETROACTIVE_APPLICATION_ERROR`)로 판정하지 않습니다** (T10 오탐 대조 원칙 준수).
- **내용이 바뀐 개정 (신설 목의 소급 인용, 진성 오류)**:
  - 행위 당시 조/호의 모든 목 본문과 청구 문언이 불일치(`CONTRADICTED`)하고, 행위일 이후 신설된 현행 목 본문과만 일치하는 경우 기존 `TEMPORAL.CURRENT_ONLY_MATCH`로 판정합니다.
- 법령명, 조문 번호, 목 글자, 날짜를 코드나 설정에 일체 하드코딩하지 않고 실질 본문 대조로만 판정합니다.

---

## 3. 동일 시행일 복수 버전 병기 및 확인 요청 (FT-b)

### 3.1 범위 격리 및 fail-closed 보존
- `legal_history.select_version`은 일체 수정하지 않습니다 (`resolve_statute` 경로의 fail-closed 동작 100% 보존).
- 동일 시행일 후보 묶기는 `temporal_review.official_versions` 내부에서만 수행합니다.
- 완화 대상은 `Multiple versions share the same effective date` 사유 하나로 한정하며, 나머지 차단 규칙(법령 식별 모호, 공포일 > 기준일, 폐지 경계, 중복 충돌)은 후보 버전마다 엄격히 유지합니다.
- **기준일 및 현행 경계**: 행위 기준일뿐 아니라 현행(today) 경계에서 동일 시행일 버전이 둘 이상 존재하는 경우에도 동일하게 버전 집합으로 수용합니다.

### 3.2 버전 집합 판정 및 순서 독립성
- `ref = next(...)`, `current = next(...)`와 같이 첫 원소를 임의 선택하는 방식을 제거하고, 기준일을 덮는 **기준일 버전 집합(`ref_versions`)**과 **현행 버전 집합(`current_versions`)**으로 판정합니다.
- **선행 분기 (불일치 시 확인 요청)**:
  - 집합 내 각 버전에 대해 `compare_claim_to_provision`을 수행합니다.
  - 집합 안에서 버전 간 결과가 갈리는 경우(예: 한 버전은 VERIFIED, 다른 버전은 CONTRADICTED), 기존 `REFERENCE_VERSION_MATCH`나 `CURRENT_ONLY_MATCH` 분기보다 **먼저** 확인 요청으로 분기합니다:
    - 판정 규칙: 기존 `TEMPORAL.REVIEW_NEEDED` (새 rule_id 없음)
    - `finding.status = VerificationStatus.UNVERIFIED`
    - `finding.severity != Severity.HIGH` (`RETROACTIVE_APPLICATION_ERROR` 태그 부여 금지)
    - `confidence_features["human_review"] = True`
    - `confidence_features["ambiguity"] = "SAME_EFFECTIVE_DATE"`
    - `confidence_features["versions"]`에 각 버전별 대조 상태(`status: VERIFIED | CONTRADICTED`)를 병기
- **후행 분기 (결과 일치 시)**:
  - 집합 내 모든 버전의 대조 결과가 동일한 경우에만 기존 단일 버전 분기 로직을 수행합니다.
  - 이로써 연혁 입력 순서(forward/reverse)나 공포일·일련번호 순서에 관계없이 100% 동일한 판정 결과를 보장합니다.

---

## 4. 규칙 식별자 (`rule_id`) 및 배정표 호환성

- **신설 목 소급 인용**: 기존 `TEMPORAL.CURRENT_ONLY_MATCH` 재사용 (`FindingType.TEMPORAL_LAW_MISMATCH`).
- **동일 시행일 불일치 확인 요청**: 기존 코드에 존재하는 `TEMPORAL.REVIEW_NEEDED` 재사용 (`FindingType.TEMPORAL_LAW_MISMATCH`).
- 새 `rule_id`나 `FindingType`을 생성하지 않으므로 F2 배정표 및 T3(배정 완전성)과의 호환성이 유지됩니다.

---

## 5. 시험 및 대조군 계획

T10·T11 보호 시험 외에 공식 원문 미러 기반의 추가 대조군 4건을 시험으로 작성합니다:
1. **일반 단어 오인식 방지 대조군**: 인용문에 '항목', '품목', '교과목' 등 일반 명사가 포함된 경우 목 단위 판정으로 오진입하지 않고 기존 조·항 판정을 유지함.
2. **분할 실패 시 안전 폴백 대조군**: 비표준 서식 등으로 호·목 분할에 실패한 경우 임의의 소급 오류 finding을 생성하지 않고 기존 조·항 결과를 유지함.
3. **동일 시행일 복수 버전 전수 불일치 대조군**: 동일 시행일 두 버전이 모두 청구 문언과 불일치하는 경우, 확인 요청이 아닌 기존 불일치 경로(`TEMPORAL.NO_VERSION_MATCH`)로 정상 판정함.
4. **현행(today) 경계 동일 시행일 복수 버전 대조군**: 기준일은 단일이나 현행 경계에 동일 시행일 버전이 복수 개 존재하는 경우, 현행 버전 집합 대조 결과에 따라 정상/확인요청 분기가 결정론적으로 작동함.

---

## 6. 영향 범위 및 검증 측정 방법

- **측정 방법**:
  - 구현 PR 제출 시 변경 전후 `scripts/scorecard.py`(dev, holdout) 점수 변화를 측정하여 점수 하락이 없음을 수치로 보고합니다.
  - `tests/acceptance/test_ft_protected.py` 및 관련 16개 시험 파일의 실제 pytest 요약 출력을 있는 그대로 기재합니다.
  - 평가 측 수용 SHA에서 `verify_all` 전체 모드 및 RELEASE_PROCEDURE 6절에 따른 봉인 세트 채점 절차를 거칩니다.
- **실제 사례(국가재정법 제96조) 원문 확인 여부**:
  - 현재 폐쇄형 오프라인 실행 환경으로 인해 국가법령정보센터 외부 조회가 불가하며, 로컬 미러(`prepared_brief_mirror`)에 해당 법령 원문이 없으므로 **실제 사례 원문은 확인하지 못함**으로 기록하고 T11의 합성 연혁을 통해 구조적 검증을 수행합니다.
- **절차 준수**: 본 설계 메모 개정안에 대한 평가 측 승인 회신 전까지는 제품 코드를 일체 작성하지 않습니다.
