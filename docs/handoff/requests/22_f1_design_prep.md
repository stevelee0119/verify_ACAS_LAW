# 안정화 라운드 F1 준비: 화면 및 참고자료 연동 (R7C-F 정정본)

## 1. 목적
7C 라운드 이후 착수할 안정화 F1(화면·참고자료 기능) 라운드의 설계 및 구현 기준을 명확히 하고, 이전 보고서(7B)에 기재되었던 팩트 오류를 바로잡아 향후 구현 담당 에이전트와 평가 담당 에이전트가 단일 진실 원천(SSOT)에 접근할 수 있도록 한다.

## 2. 팩트 정정 (7B 보고서의 오류 수정)
이전 보고서에서 인용된 경로, 클래스 명칭, 스키마 구조 등에 다수의 오류가 있었으며, 코드를 기준으로 아래와 같이 정정한다.

### 2.1. 탐지 타입 (FindingType)
* **오류**: FindingType이 83개 또는 85개라고 보고되었으며, `OVERCLAIM_WITHOUT_REQUIREMENTS` 등 존재하지 않는 타입이 언급됨.
* **정정**: `packages/common/enums.py`에 선언된 `FindingType` Enum의 항목은 **총 97개**이다. 허위 열거형을 사용해서는 안 되며, F1 UI 및 파이프라인에서 반환할 때 반드시 이 97개 내의 값만 사용해야 한다.

### 2.2. JSON 스키마 필드 (Finding)
* **오류**: UI에서 사용하는 JSON 응답 매핑이 코드의 스키마와 불일치함.
* **정정**: `packages/common/schemas.py`의 `Finding` 클래스는 다음 필드를 가진다:
  * 필수: `finding_id`, `type` (FindingType), `status` (VerificationStatus), `severity` (Severity), `evidence_grade` (EvidenceGrade), `title`
  * 선택/기본값: `detail`, `confidence`, `document_id`, `block_id`, `page`, `bbox`, `span`, `evidence`, `tags`
  따라서 JSON 직렬화 시, `id`가 아닌 `finding_id`를 사용하며, 위치 정보는 `page`, `bbox`, `span`, `block_id`를 활용해야 한다.

### 2.3. 리뷰 상태 및 워크플로우 (ReviewStatus)
* **오류**: 존재하지 않는 `FindingWorkflow` 클래스 및 UI 전용 가짜 상태(`UNREVIEWED`, `NOT_STARTED` 등)를 참조함.
* **정정**: 리뷰 상태는 `packages/common/enums.py`의 `ReviewStatus`를 사용해야 하며, 가용한 상태는 다음과 같다:
  * `NEEDS_REVIEW`
  * `ACCEPTED`
  * `FALSE_POSITIVE`
  * `RESOLVED`
  사용자 검토 단계 및 리뷰 이력은 이 Enum과 연동하여 구축해야 한다.

### 2.4. 파이프라인 경로 (PII 및 프라이버시)
* **오류**: `PIIDetector`, `anonymize_text` 등 코드에 존재하지 않는 경로를 참조함.
* **정정**: 실제 개인정보 보호 파이프라인의 데이터 흐름은 다음과 같다:
  1. **탐지**: `packages/pii_engine/detector.py::detect()`
  2. **마스킹**: `packages/pii_engine/engine.py` 의 `PIIEngine`
  3. **전송 전 검사**: `packages/llm_router/privacy.py::inspect_request`
  4. **통합 실행**: `packages/llm_router/router.py` 내 `LLMRouter.run`

## 3. F1 기능 구현 지침 (UI 및 참고자료)
F1 라운드에서는 위 정정된 스키마와 경로를 바탕으로 다음 사항을 구현한다.

1. **프론트엔드 연동**: `Finding` JSON의 `block_id`와 `bbox`를 파싱하여 PDF 뷰어 화면에 하이라이트를 표시한다.
2. **참고자료 연동**: `Evidence` 리스트를 참조하여, 탐지 결과(Finding)에 대한 근거가 되는 참고자료 페이지나 조항을 툴팁/사이드바로 제공한다.
3. **상태 관리**: `ReviewStatus`를 바탕으로 사용자가 `FALSE_POSITIVE` 또는 `ACCEPTED`로 상태를 토글할 수 있는 API 엔드포인트를 제공한다.
4. **결합 규칙 유지 보수**: `packages/document_engine/paragraph_reconstruction.py`의 문단 결합 로직에 있어 어휘에 의존하지 않는 구조적 결합(7adf43f 상태)을 유지하면서 UI 상에서 어색하게 끊어지는 문단을 렌더링 시 보정한다.
