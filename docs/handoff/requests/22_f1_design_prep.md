# 안정화 라운드 F1 준비: 화면 및 참고자료 연동 (R7C 수정본)

## 1. 목적
F1(화면·참고자료 기능) 라운드의 설계 및 구현 기준을 명확히 하고, 이전 라운드의 팩트 오류를 정정합니다.

## 2. 팩트 정정 및 확인 (7C 감사 지적 반영)

### 2.1. 리뷰 상태 및 워크플로우 명세 (실제 코드 기준)
* **FindingWorkflow 및 Revision**: pps/api/workspace.py 내에 FindingWorkflow, ReviewDraft, ReviewRevision 모델이 정의되어 있으며, pps/api/routers/workspace.py에서 GET/PUT 등 API 워크플로우와 충돌(409) 처리가 정상 구현되어 있습니다. 이를 F1 화면 연동 시 그대로 보존하고 호출해야 합니다.
* **ReviewStatus**: packages/common/enums.py에 선언된 Enum(NEEDS_REVIEW, ACCEPTED, FALSE_POSITIVE, RESOLVED)을 엄격하게 사용하며, 프론트엔드 임의 상태(NOT_STARTED 등)를 사용하지 않습니다.

### 2.2. F3 호출 상한 및 예산 초과 방어
* F3(LLM 검토 보완) 호출 시 청구별 상한(예: 건당 최대 3회), 캐시 메커니즘, 호출 실패 및 예산 초과 시의 fallback 처리를 파이프라인(packages/llm_router/router.py) 단에서 유지합니다.

### 2.3. 개인정보 보호 파이프라인
* 데이터 흐름: packages/pii_engine/detector.py::detect() -> packages/pii_engine/engine.py (PIIEngine) -> packages/llm_router/privacy.py::inspect_request

## 3. FindingType 97개 전수 패널 배정표
F1 화면의 탭/패널에 모든 FindingType을 누락 없이 배정합니다. 미배정된 항목이 있을 시 CI가 실패하도록 프론트엔드 매핑 테스트를 제안합니다.

| FindingType | 소속 패널/탭 | 뱃지 라벨 |
|---|---|---|
| CASE_NOT_FOUND | 법리 및 판례 검토 | 확인 필요 |
| CASE_METADATA_MISMATCH | 법리 및 판례 검토 | 확인 필요 |
| CASE_QUOTE_MISMATCH | 법리 및 판례 검토 | 확인 필요 |
| CASE_HOLDING_DISTORTION | 법리 및 판례 검토 | 확인 필요 |
| CASE_CITATION_ERROR | 법리 및 판례 검토 | 확인 필요 |
| LAW_CITATION_ERROR | 법리 및 판례 검토 | 확인 필요 |
| TEMPORAL_LAW_MISMATCH | 시간축 검토 | 확인 필요 |
| ACADEMIC_CITATION_ERROR | 참고자료 부합성 | 확인 필요 |
| FACT_CONTRADICTION | 참고자료 부합성 | 확인 필요 |
| CROSS_DOCUMENT_CONTRADICTION | 일반 내용 검토 | 확인 필요 |
| TIMELINE_CONTRADICTION | 시간축 검토 | 확인 필요 |
| ARITHMETIC_MISMATCH | 일반 내용 검토 | 확인 필요 |
| METADATA_ANOMALY | 일반 내용 검토 | 확인 필요 |
| HIDDEN_TEXT_MISMATCH | 일반 내용 검토 | 확인 필요 |
| OCR_LAYER_MISMATCH | 일반 내용 검토 | 확인 필요 |
| OCR_LOW_QUALITY | 일반 내용 검토 | 확인 필요 |
| SIGNATURE_INVALID | 일반 내용 검토 | 확인 필요 |
| MODIFIED_AFTER_SIGNATURE | 일반 내용 검토 | 확인 필요 |
| PAGE_STRUCTURE_OUTLIER | 일반 내용 검토 | 확인 필요 |
| PROMPT_INJECTION_SUSPECTED | 보안 검토 | 확인 필요 |
| HIDDEN_INSTRUCTION | 일반 내용 검토 | 확인 필요 |
| META_INSTRUCTION | 일반 내용 검토 | 확인 필요 |
| SYSTEM_OVERRIDE_ATTEMPT | 일반 내용 검토 | 확인 필요 |
| ROLE_OVERRIDE_ATTEMPT | 일반 내용 검토 | 확인 필요 |
| VERIFICATION_SUPPRESSION | 일반 내용 검토 | 확인 필요 |
| OUTPUT_MANIPULATION_ATTEMPT | 일반 내용 검토 | 확인 필요 |
| ENCODED_INSTRUCTION | 일반 내용 검토 | 확인 필요 |
| OBFUSCATED_INSTRUCTION | 일반 내용 검토 | 확인 필요 |
| UNICODE_SMUGGLING | 일반 내용 검토 | 확인 필요 |
| OCR_LAYER_INJECTION | 보안 검토 | 확인 필요 |
| METADATA_INJECTION | 보안 검토 | 확인 필요 |
| MULTIMODAL_INJECTION | 보안 검토 | 확인 필요 |
| RAG_POISONING_SIGNAL | 일반 내용 검토 | 확인 필요 |
| TOOL_MANIPULATION_ATTEMPT | 일반 내용 검토 | 확인 필요 |
| DATA_EXFILTRATION_INSTRUCTION | 일반 내용 검토 | 확인 필요 |
| MODEL_OUTPUT_QUARANTINED | 일반 내용 검토 | 확인 필요 |
| AI_AUTHORSHIP_LIKELY | 일반 내용 검토 | 확인 필요 |
| AI_FULL_GENERATION_SUSPECTED | 일반 내용 검토 | 확인 필요 |
| AI_HALLUCINATED_CONTENT | 일반 내용 검토 | 확인 필요 |
| LEGAL_ARGUMENT_INVALID | 법리 및 판례 검토 | 확인 필요 |
| STYLE_SHIFT | 일반 내용 검토 | 확인 필요 |
| MODEL_ATTRIBUTION_SIGNAL | 일반 내용 검토 | 확인 필요 |
| RESIDUAL_TRACKED_CHANGE | 일반 내용 검토 | 확인 필요 |
| RESIDUAL_COMMENT | 일반 내용 검토 | 확인 필요 |
| DELETED_TEXT_RECOVERABLE | 일반 내용 검토 | 확인 필요 |
| PRIOR_VERSION_RECOVERABLE | 일반 내용 검토 | 확인 필요 |
| REDACTION_FAILURE | 일반 내용 검토 | 확인 필요 |
| HIDDEN_SHEET_OR_ROW | 일반 내용 검토 | 확인 필요 |
| CROPPED_IMAGE_RESIDUE | 일반 내용 검토 | 확인 필요 |
| TEMPLATE_RESIDUE | 일반 내용 검토 | 확인 필요 |
| SPECIMEN_DOCUMENT_DECLARED | 일반 내용 검토 | 확인 필요 |
| INVALID_IDENTIFIER | 일반 내용 검토 | 확인 필요 |
| PLACEHOLDER_IDENTIFIER | 일반 내용 검토 | 확인 필요 |
| AUTHORSHIP_METADATA_LEAK | 일반 내용 검토 | 확인 필요 |
| GEOLOCATION_METADATA_LEAK | 일반 내용 검토 | 확인 필요 |
| STEGANOGRAPHIC_PAYLOAD | 일반 내용 검토 | 확인 필요 |
| TRACKING_CANARY_DETECTED | 일반 내용 검토 | 확인 필요 |
| DOCUMENT_FINGERPRINT_SUSPECTED | 일반 내용 검토 | 확인 필요 |
| COVERT_CHANNEL_SUSPECTED | 일반 내용 검토 | 확인 필요 |
| PRIVILEGE_EXPOSURE_RISK | 일반 내용 검토 | 확인 필요 |
| OUTBOUND_LEAK_RISK | 일반 내용 검토 | 확인 필요 |
| ISSUE_EVASION_SIGNAL | 일반 내용 검토 | 확인 필요 |
| IMPLICIT_ADMISSION_SIGNAL | 일반 내용 검토 | 확인 필요 |
| LIABILITY_HEDGING_SIGNAL | 일반 내용 검토 | 확인 필요 |
| COERCIVE_LANGUAGE_SIGNAL | 일반 내용 검토 | 확인 필요 |
| SELECTIVE_QUOTATION_SIGNAL | 일반 내용 검토 | 확인 필요 |
| CASE_RELEVANCE_WEAK | 법리 및 판례 검토 | 확인 필요 |
| STATUTE_NONEXISTENT | 법리 및 판례 검토 | 확인 필요 |
| STATUTE_TEXT_MISMATCH | 법리 및 판례 검토 | 확인 필요 |
| INTERNAL_CITATION_ERROR | 참고자료 부합성 | 확인 필요 |
| QUOTE_MISMATCH | 참고자료 부합성 | 확인 필요 |
| FACT_UNSUPPORTED | 참고자료 부합성 | 확인 필요 |
| EVIDENCE_NOT_PROVIDED | 참고자료 부합성 | 확인 필요 |
| EVIDENCE_REFERENCE_MISSING | 참고자료 부합성 | 확인 필요 |
| HASH_FORMAT_INVALID | 일반 내용 검토 | 확인 필요 |
| HASH_MISMATCH | 일반 내용 검토 | 확인 필요 |
| EVIDENCE_DATE_INVALID | 시간축 검토 | 확인 필요 |
| EVIDENCE_TIMELINE_INVERSION | 시간축 검토 | 확인 필요 |
| EVIDENCE_NUMBERING_GAP | 참고자료 부합성 | 확인 필요 |
| EVIDENCE_LIST_MISMATCH | 참고자료 부합성 | 확인 필요 |
| EVIDENCE_PERSON_INCONSISTENT | 참고자료 부합성 | 확인 필요 |
| EVIDENCE_FORM_DEFECT | 참고자료 부합성 | 확인 필요 |
| EVIDENCE_PURPOSE_MISMATCH | 참고자료 부합성 | 확인 필요 |
| STATEMENT_BEYOND_PERCEPTION | 일반 내용 검토 | 확인 필요 |
| CROSS_DOC_COPY | 일반 내용 검토 | 확인 필요 |
| MODEL_FACT_REMARK | 참고자료 부합성 | 확인 필요 |
| SOURCE_CONFLICT_IGNORED | 참고자료 부합성 | 확인 필요 |
| CALCULATION_INVARIANT_VIOLATION | 일반 내용 검토 | 확인 필요 |
| LEGAL_REQUIREMENT_OMITTED | 법리 및 판례 검토 | 확인 필요 |
| OVERCLAIM | 항변 및 요건 검토 | 확인 필요 |
| UNSUPPORTED_GENERALIZATION | 일반 내용 검토 | 확인 필요 |
| REASONING_GAP | 일반 내용 검토 | 확인 필요 |
| AUTHORITY_RANK_ERROR | 일반 내용 검토 | 확인 필요 |
| DRAFT_ARTIFACT | 참고자료 부합성 | 확인 필요 |
| UNCERTAINTY_NOT_DISCLOSED | 일반 내용 검토 | 확인 필요 |
| UNSUPPORTED_FORMAT | 일반 내용 검토 | 확인 필요 |
| PARSE_ERROR | 일반 내용 검토 | 확인 필요 |

## 4. F1 화면 렌더링 주의사항
* F1 프론트엔드는 Finding JSON의 lock_id 및 box를 파싱하여 PDF 뷰어에 하이라이트를 표시합니다.
* 기존 join_lines의 국소 구조 신호(7adf43f 상태)가 탐지 엔진의 입력으로 유지되므로, 문서 파서의 원본 텍스트를 임의로 보정하여 오탐/미탐을 회피하지 않습니다.
