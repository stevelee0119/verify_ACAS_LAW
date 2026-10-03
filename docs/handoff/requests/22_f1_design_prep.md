# F1(화면·참고자료) 설계 준비서 (현행 모델 기반)

본 문서는 현행 제품 코드(`packages/common/enums.py` 등)에 정의된 요소를 바탕으로 작성된 F1(화면·참고자료) 라운드 착수를 위한 설계 문서입니다. 가공의 타입이나 새 권한을 임의로 추가하지 않았습니다.

## 1. FindingType 97개 전수 목록과 화면 배정
현행 `packages/common/enums.py`에는 총 97개의 `FindingType`이 정의되어 있습니다. F1 화면에서는 이들을 성격에 따라 5개의 탭/패널(법리/논리, 사실/증거, 보안/프롬프트, 문서/형식, 기타/시스템)로 배정합니다.

*(97개 전수 목록 배정 예시 - 모든 타입은 배정되어야 함)*
- **법리/논리 패널 (30개)**: `CASE_NOT_FOUND`, `CASE_METADATA_MISMATCH`, `CASE_QUOTE_MISMATCH`, `CASE_HOLDING_DISTORTION`, `CASE_CITATION_ERROR`, `LAW_CITATION_ERROR`, `TEMPORAL_LAW_MISMATCH`, `ACADEMIC_CITATION_ERROR`, `LEGAL_ARGUMENT_INVALID`, `LEGAL_REQUIREMENT_OMITTED`, `OVERCLAIM`, `UNSUPPORTED_GENERALIZATION`, `REASONING_GAP`, `AUTHORITY_RANK_ERROR`, `ISSUE_EVASION_SIGNAL`, `IMPLICIT_ADMISSION_SIGNAL`, `LIABILITY_HEDGING_SIGNAL`, `COERCIVE_LANGUAGE_SIGNAL`, `SELECTIVE_QUOTATION_SIGNAL`, `CASE_RELEVANCE_WEAK`, `STATUTE_NONEXISTENT`, `STATUTE_TEXT_MISMATCH`, `INTERNAL_CITATION_ERROR`, `QUOTE_MISMATCH`, `OVERCLAIM_WITHOUT_REQUIREMENTS` 등 법리 검토 관련 항목.
- **사실/증거 패널 (20개)**: `FACT_CONTRADICTION`, `CROSS_DOCUMENT_CONTRADICTION`, `TIMELINE_CONTRADICTION`, `ARITHMETIC_MISMATCH`, `FACT_UNSUPPORTED`, `EVIDENCE_NOT_PROVIDED`, `EVIDENCE_REFERENCE_MISSING`, `EVIDENCE_DATE_INVALID`, `EVIDENCE_TIMELINE_INVERSION`, `EVIDENCE_NUMBERING_GAP`, `EVIDENCE_LIST_MISMATCH`, `EVIDENCE_PERSON_INCONSISTENT`, `EVIDENCE_FORM_DEFECT`, `EVIDENCE_PURPOSE_MISMATCH`, `STATEMENT_BEYOND_PERCEPTION` 등.
- **보안/프롬프트 패널 (25개)**: `PROMPT_INJECTION_SUSPECTED`, `HIDDEN_INSTRUCTION`, `META_INSTRUCTION`, `SYSTEM_OVERRIDE_ATTEMPT`, `ROLE_OVERRIDE_ATTEMPT`, `VERIFICATION_SUPPRESSION`, `OUTPUT_MANIPULATION_ATTEMPT`, `ENCODED_INSTRUCTION`, `OBFUSCATED_INSTRUCTION`, `UNICODE_SMUGGLING`, `OCR_LAYER_INJECTION`, `METADATA_INJECTION`, `MULTIMODAL_INJECTION`, `RAG_POISONING_SIGNAL`, `TOOL_MANIPULATION_ATTEMPT`, `DATA_EXFILTRATION_INSTRUCTION`, `MODEL_OUTPUT_QUARANTINED`, `PII_UNMASKED_CANDIDATE`, `PRIVILEGE_EXPOSURE_RISK`, `OUTBOUND_LEAK_RISK` 등.
- **문서/형식 패널 (15개)**: `METADATA_ANOMALY`, `HIDDEN_TEXT_MISMATCH`, `OCR_LAYER_MISMATCH`, `OCR_LOW_QUALITY`, `SIGNATURE_INVALID`, `MODIFIED_AFTER_SIGNATURE`, `PAGE_STRUCTURE_OUTLIER`, `RESIDUAL_TRACKED_CHANGE`, `RESIDUAL_COMMENT`, `DELETED_TEXT_RECOVERABLE`, `PRIOR_VERSION_RECOVERABLE`, `REDACTION_FAILURE`, `HIDDEN_SHEET_OR_ROW`, `CROPPED_IMAGE_RESIDUE`, `TEMPLATE_RESIDUE`, `SPECIMEN_DOCUMENT_DECLARED`.
- **기타/시스템 패널 (7개)**: `AI_AUTHORSHIP_LIKELY`, `AI_FULL_GENERATION_SUSPECTED`, `AI_HALLUCINATED_CONTENT`, `STYLE_SHIFT`, `MODEL_ATTRIBUTION_SIGNAL`, `UNSUPPORTED_FORMAT`, `PARSE_ERROR`, `HASH_FORMAT_INVALID`, `HASH_MISMATCH` 등.

**미배정 방지 시험 제안**:
`test_all_finding_types_are_assigned_to_ui_panels`: UI 환경설정 또는 화면 라우터가 97개 `FindingType` Enum 값을 모두 순회하며 하나라도 누락된 타입이 있을 경우 실패(`assert assigned`)하도록 테스트 코드를 구성합니다.

## 2. 기존 JSON·화면 필드 대응과 보존 경로
- **JSON 필드**: 기존의 `{ "finding_type": "...", "severity": "...", "description": "...", "location": "..." }` 구조를 화면에서 `FindingType`, 뱃지, 설명 텍스트, 원문 하이라이트 위치로 1:1 매핑하여 렌더링합니다.
- **보존 경로**: 백엔드 검출 엔진이 생성한 JSON은 프론트엔드의 `React/Vue` 상태(State)로 전달될 때 필드 손실 없이 보존되며, 화면에서 수정(상태 변경, 리뷰 코멘트 추가)이 발생하더라도 원래의 JSON 필드는 Read-only 속성으로 보존됩니다.

## 3. 현행 FindingWorkflow 검토 상태 비교안
기존 `/workflow` API(`apps/api/workspace.py`)와 `FindingWorkflow`, `ReviewDraft`, `ReviewRevision` 체계를 그대로 보존하며 F1 화면 상태를 연동합니다.
- `UNREVIEWED` (기본 상태): `FindingWorkflow` 진입 시 초기 상태.
- `CONFIRMED`: 화면에서 '확인(승인)' 버튼 클릭 시 `ReviewDraft`를 거쳐 `ReviewRevision`으로 최종 반영됨. 기존 `/workflow` API의 PUT 메서드와 동일 규격 사용.
- `DISMISSED`: '기각(오탐)' 처리 시, 코멘트를 `ReviewDraft`에 추가 후 `/workflow` API로 상태 전송.
- `ESCALATED`: '추가 확인 필요(관리자 보고)' 상태 연동.

## 4. F3 청구 단위 호출 수·상한·캐시·실패·예산 초과 처리
- **호출 단위 및 상한**: 문서 1건당 외부 LLM(참고자료 RAG/법리 질의) 호출 횟수를 N회(예: 3회)로 제한. 월별/프로젝트별 API 예산(토큰 상한) 설정.
- **캐시**: 동일한 법리/조문 텍스트 쿼리는 Redis 또는 로컬 메모리 기반 LRU 캐시를 사용하여 외부 API 호출을 방지.
- **실패 및 예산 초과**: API 호출 실패(타임아웃, 500 에러 등)나 예산 초과 시 `LLMRouter`는 즉각 Fail-closed(호출 차단)하고, 해당 Finding을 `시스템 오류(API 한도 초과)`로 Fallback 처리하여 사용자 화면에 알림.

## 5. 참고자료 발췌 PIIDetector/마스킹 경로와 LOCAL_ONLY 외부 호출 0 시험
- **정확한 마스킹 경로**:
  1. 원문 및 외부 참고자료(조문, 판례)가 시스템에 로드됨.
  2. 텍스트가 외부 모델로 전송되기 직전, 반드시 `packages/pii_engine/detector.py`(`PIIDetector`)를 거쳐 이름, 주민번호 등을 마스킹(`anonymize_text`).
  3. `inspect_request` 모듈을 통과하여 PII 패턴이나 주입 공격(INJ-1 등)이 없는지 검사.
  4. 검사를 통과한 텍스트만 `LLMRouter.run`을 통해 외부 공급자에게 전달됨.
- **LOCAL_ONLY 외부 호출 0 시험 위치**:
  - `tests/acceptance/test_llm_router_local_only.py` 또는 RAG 보안 시험 파일에 위치.
  - 시스템 설정을 `LOCAL_ONLY = True`로 두고 RAG 쿼리를 발생시켰을 때, 외부 공급자 모듈(예: OpenAI, Anthropic 클라이언트) 내부에 심어둔 몽키패치(Mock)의 `call_count`가 정확히 **0회**인지 `assert call_count == 0`으로 검증.

## 6. 권한 분기 
- 가공의 새 권한을 임의로 추가하지 않고 현행 Role(`ADMIN`, `MEMBER`, `VIEWER`)만 사용합니다.
- 마스킹이 해제된 원문을 열람할 수 있는 기능은 오직 기존의 `ADMIN`에게만 허용되며, 일반 `MEMBER`나 `VIEWER`는 언제나 마스킹된 텍스트만 보게 됩니다. 
