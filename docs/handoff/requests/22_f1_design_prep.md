# F1 설계 준비서 - 현행 모델 보존과 참고자료 검토 확장 (7D 정정본)

작성, 코드 대조: 2026-10-03. 확인 기준은 `a1f3d1e`이며, 이 문서는 설계 준비 문서다. 아래에서 **현행 구현**과 **후속 제안**을 구분한다. 이 문서 수정으로 F1 코드, DB, API가 구현되거나 F1 착수가 승인되지는 않는다.

## 1. 목적과 범위

기존 검증 결과, 사람의 검토 이력, 개인정보 정책을 보존하면서 F1 화면을 확장할 기준을 정한다. 현행 프런트엔드는 `apps/web/static/*.js`의 순수 JavaScript이며, 워크플로 연동은 `workflow.js`에 이미 있다. 화면 구현 언어나 상태 체계를 새로 가정하지 않는다.

## 2. 현행 코드와 후속 설계의 구분

### 2.1. 검토 상태와 워크플로

**현행 구현:** `apps/api/workspace.py`에 다음 세 모델이 정의되어 있다.

| 모델 | 실제 필드와 의미 | F1에서 보존할 동작 |
|---|---|---|
| `FindingWorkflow` | `finding_id`, `workflow_state`, `decision`, `priority`, `assignee`, `note`, `revision`, `updated_by`, `updated_at` | 검토 진행과 판단 내용을 각각 저장하고, 서버가 반환한 revision으로 갱신 |
| `ReviewDraft` | `finding_id` + `user_id` 복합 키, `note`, `base_revision`, `updated_at` | 사용자별 초안. 현재 workflow revision과 일치할 때만 복원 |
| `ReviewRevision` | `id`, `project_id`, `subject_type`, `subject_id`, `actor`, `before`, `after`, `created_at` | 변경 전후 값과 변경자를 이력으로 유지 |

`apps/api/routers/workspace.py::WorkflowInput`의 허용 값은 다음과 같다.

- `workflow_state`: `NOT_STARTED`, `IN_PROGRESS`, `ACTION_REQUIRED`, `COMPLETED`, `DEFERRED`.
- `decision`: `UNDECIDED`, `AGREED`, `FALSE_POSITIVE`, `PARTLY_AGREED`.
- 최초 조회 시 저장된 workflow가 없으면 `revision=0`으로 응답하고, 최초 저장은 revision 0을 받아 저장 revision 1을 만든다. 이후 저장은 현재 revision과 비교하여 1씩 증가시킨다.
- `NOT_STARTED`는 실제 workflow 기본값이다. 프런트엔드 임의 값으로 배제하면 안 된다.

`packages/common/enums.py::ReviewStatus`의 `NEEDS_REVIEW`, `ACCEPTED`, `FALSE_POSITIVE`, `RESOLVED`는 `Finding.review_status`의 별도 체계다. `update_workflow()`는 다음과 같이 기존 필드와 호환한다.

| workflow 저장값 | 기존 `review_status` |
|---|---|
| `COMPLETED` + `AGREED` | `ACCEPTED` |
| `COMPLETED` + `FALSE_POSITIVE` | `FALSE_POSITIVE` |
| `COMPLETED` + 나머지 decision | `RESOLVED` |
| `COMPLETED`가 아닌 모든 상태 | `NEEDS_REVIEW` |

저장된 workflow가 없는 구형 기록을 조회할 때는 `workflow_value()`가 기존 `NEEDS_REVIEW`를 `NOT_STARTED`, 나머지를 `COMPLETED`로 보여 준다. decision은 기존 `ACCEPTED`를 `AGREED`, `FALSE_POSITIVE`를 동일 값, 나머지를 `UNDECIDED`로 변환한다. 이 조회용 호환 변환과 실제 저장값을 혼동하지 않는다.

**현행 API:** 아래 경로는 라우터 선언 기준이다.

| API | 실제 동작 |
|---|---|
| `GET /findings/{finding_id}/workflow` | workflow와 현재 사용자의 동일 revision draft 조회 |
| `PUT /findings/{finding_id}/workflow` | revision 비교 저장, 기존 review_status 동기화, 저장한 사용자의 draft 삭제, 변경 이력 기록 |
| `PUT /findings/{finding_id}/review-draft` | 현재 revision 일치 시 사용자별 초안 저장 |
| `POST /projects/{project_id}/reviews` | 각 항목의 expected_revisions를 받아 일괄 갱신 |
| `GET /projects/{project_id}/review-workflows?run_id=...` | 해당 실행의 workflow 목록 |
| `GET /projects/{project_id}/review-history` | 프로젝트 이력 조회, subject_id로 항목 제한 가능 |

`save_versioned()`의 revision 불일치, 동시 최초 생성 충돌, `save_draft()`의 오래된 초안 저장은 HTTP 409다. 기존 `PATCH /findings/{finding_id}/review`도 구조화 workflow가 이미 있으면 409로 새 workflow API 사용을 요구한다. `workflow.js`는 이미 GET/PUT, revision 전달, 초안 저장과 이력 조회를 사용한다.

**후속 제안:** F1의 확장 화면도 이 API를 재사용한다. 409가 발생하면 서버 최신 상태와 사용자가 편집하던 내용을 함께 보여 주고 재검토 후 저장하도록 한다. 자동으로 최신 revision을 대입하여 덮어쓰지 않는다. 이 추가 충돌 비교 화면의 완성을 현행 코드에서 확인한 것으로 보고하지 않는다.

### 2.2. 참고자료 검토(F3)의 현재 호출 단위와 한계

**현행 구현:**

- `packages/rag_engine/review.py::review_document()`는 문서 전체 분석문과 요청 쟁점으로 `library.select()`를 한 번 수행한다. 선택 자료를 6개씩 묶어 배치마다 `LLMRouter.run()`을 호출하며, 실패한 공급자가 있으면 그 공급자를 제외하고 한 번 더 호출한다. `claim_coverage`는 결과를 주장에 연결한 뒤 집계한다. **주장(`claim_id`)마다 검색, 대조를 예약하는 구조는 아니다.**
- `packages/verification_engine/pipeline.py::_semantic_review()`는 공식 전문이 있는 인용 검토 항목별로 `router.cascade()`를 사용한다. `QUICK`, 공식 전문 없음, 격리된 지시문 블록 등의 사유는 미검증으로 남긴다. 이것도 F3의 주장별 호출 상한과는 다르다.
- `LLMRouter.run()`은 공급자 선택 후 MASKED 정책의 외부 요청을 `inspect_request()`로 검사하고, 비용, 토큰 한도 확인 및 `BudgetLedger.reserve()/dispatch()`를 거쳐 발송한다. 예산, 단가, 토큰 한도 문제가 있으면 `BUDGET_ADMISSION_FAILED`와 `NOT_SENT` 기록을 반환한다. 월간, 실행 예산과 입출력 토큰 한도는 `packages/llm_router/budget.py`의 `budget_settings()`, `estimate_call()`에서 다룬다.
- `run()`의 기본 일시 오류 재시도는 최초 시도 + 2회다. 이는 **한 router 호출의 공급자 재시도 수**이며, 주장당 최대 3회 검토가 구현되었다는 뜻이 아니다. `run_any()`의 공급자 전환, `consult_all()`의 복수 공급자 호출, `cascade()`의 primary/critic/grounder 단계를 합치면 실제 발송 수가 달라진다. 최종 `judge()`는 로컬 판단 함수다.
- 캐시는 용도가 나뉜다. `packages/rag_engine/library.py`에는 Drive 자료의 증분 색인 캐시가 있고 매 실행 권한, 목록을 확인한다. 목록 조회나 인증 실패 시 이전 캐시를 참고자료로 대신 사용하지 않는다. `packages/source_adapters/transport.py`에는 실행 단위 공식 출처 응답 캐시가 있다. 이들을 **claim별 LLM 응답 캐시**로 설명하면 안 된다.
- 검토 실패, 자료 부족은 현행 `UNVERIFIED`, `RETRIEVED_ONLY`, `INCOMPLETE_COVERAGE` 및 reason/실행 기록으로 구분한다. 특정 오류의 결과를 확인 완료 또는 자료 부존재로 바꾸지 않는다. 후속 기능은 이 의미를 보존한다.

**후속 제안 - 아직 구현하지 않은 주장별 검색, 대조 제어:**

1. 처리 키는 프로젝트, 실행, 문서 버전, `claim_id`로 고정한다. 메타, 지시문 주장은 대상에서 제외한다. 검색과 대조 각각에 시도 수, 성공 수, 캐시 적중, 미실행 사유를 기록한다.
2. 설정 초안은 주장당 공식 검색 발송 최대 2회, LLM 대조 발송 최대 3회다. 이 수치는 후속 설계 검토 대상이며 현행 기본값이 아니다. 재시도, 대체 공급자 발송도 같은 상한에 포함한다. 현재 router 내부 재시도까지 합산할 공유 카운터/발송 직전 검사가 필요하다. 여러 주장에 걸친 동시 요청에서도 실행 비용 원장과 별도로 원자적으로 예약한다.
3. 검색 질의 캐시와 대조 결과 캐시를 구분한다. 대조 키에는 프로젝트/권한 범위, 마스킹된 주장과 근거의 해시, 자료 revision/검색 기준일, 모델, 프롬프트, 스키마, 개인정보 정책 버전을 포함한다. 자료, 권한, 정책이 바뀌면 재사용하지 않는다. 원문 개인정보를 캐시 키나 로그에 넣지 않는다.
4. 예산 부족, 상한 소진, 타임아웃, 입력 차단, 근거 부족은 각각 미검증 사유를 남긴다. 이미 얻은 결정론적 결과는 유지하고, 검증되지 않은 후속 주장은 coverage의 미완료 목록에 남긴다. 실패를 피하기 위해 원문 전송이나 다른 공급자로의 무제한 재시도를 허용하지 않는다.
5. 수용 시험은 주장 수가 늘어날 때의 전체 발송 수, 캐시 적중 시 0회 발송, 캐시 무효화, 경쟁 요청의 상한, 재시도/공급자 전환 합산, 예산 부족 시 provider 미호출, 근거 없는 성공 승격 방지를 확인한다. 현재 자료 배치 방식과 이 설계의 비용, 범위 차이는 같은 입력으로 비교한다.

### 2.3. 개인정보 보호 경로

`packages/pii_engine/engine.py::PIIEngine.mask_text()`가 `detect()` 결과로 마스킹하고, 소비자가 마스킹된 문서, 참고자료로 요청을 구성한다. `LLMRouter.run()`은 외부 공급자이며 정책이 `MASKED`일 때 **조립된 전체 요청**을 `inspect_request()`로 다시 검사한다. 동적 system/schema 및 user 입력을 포함하며, 등록된 고정 상수와 정확히 일치하는 system/schema에 한해 정적 오탐 예외가 있다. 검사 자체가 실패해도 외부 전송을 차단한다.

F1/F3 확장은 이 경로를 우회하지 않는다. `ORIGINAL`, `LOCAL_ONLY`의 기존 정책 의미와 접근 권한을 보존하고, 새로운 원문 열람 권한을 요구하지 않는다. 검출기 존재만으로 모든 이름이 탐지된다고 주장하지 않으며, 미해결 개인정보 시험은 별도 안정화 대상이다.

## 3. FindingType 97개 전수 패널 배정표

`packages/common/enums.py::FindingType`의 실제 멤버와 아래 97개 행을 집합 및 개수로 대조했다. 표의 패널 배정은 **F1 제안**이며 현행 화면의 구현 완료 목록이 아니다. 기존 97개 배정행은 보존했다. 뱃지의 "확인 필요"는 검토 진입 안내이고, 실제 판정, 심각도, 증거 수준을 대신하는 고정 판정값으로 쓰지 않는다.

후속 구현 시 `tests/web/test_f1_finding_panels.py`(제안 경로)에 실제 JavaScript 매핑과 enum 집합이 정확히 같은지 검사하는 시험을 추가한다. 누락, 중복, 존재하지 않는 타입, 알 수 없는 타입의 조용한 숨김은 실패로 처리한다. 해당 시험과 패널 구현은 이번 문서 수정에 포함하지 않는다.

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

## 4. Finding 데이터와 화면 대응

**현행 엔진 스키마:** `packages/common/schemas.py::Finding`을 기준으로 한다. `finding_type`, `description`, `location`이라는 대체 필드명을 만들지 않는다.

| 실제 필드 | 화면 대응, 주의 |
|---|---|
| `finding_id`, `type`, `title`, `detail` | 항목 식별, 패널 배정, 제목, 상세 설명 |
| `status`, `severity`, `evidence_grade`, `confidence`, `confidence_features` | 검증 상태, 심각도, 증거 등급, 확신도/근거를 구분하여 표시 |
| `document_id`, `block_id`, `page`, `bbox`, `span` | 문서, 블록, 쪽 위치. bbox는 `(x0, y0, x1, y1)`, span은 문자 범위이며 없을 수 있음 |
| `evidence`, `source_record_ids` | 근거, 출처. `to_dict()`는 source_record_ids를 `sources`라는 키로 직렬화 |
| `engine`, `tags`, `meta_message_type`, `forensic_level`, `adversarial_class`, `advisory_only` | 탐지 출처, 분류, 참고 신호 구분 |
| `sealed_excerpt` | 기본 직렬화에서 원문 비공개. `has_sealed_content`로 봉인 내용 유무를 표시 |
| `review_status`, `review_note`, `created_at` | 기존 검토 필드, 생성 시각. workflow_state/decision/revision과 구분 |

**현행 API 응답과 차이:** `apps/api/schemas.py::FindingOut` 및 `apps/api/routers/verification.py::_finding_out()`은 식별자를 `id`로 반환하고 `run_id`, `project_id`를 포함한다. `workflow.js`가 `f.id`로 API를 호출하는 것이 현재 계약이다. `bbox`, `block_id`, `page`, `evidence`, `sources`는 응답에 있으나, 엔진에 있는 `span`, `confidence_features` 전체, `forensic_level`, `adversarial_class`, `created_at`가 이 API에서 모두 전달되는 것은 아니다. `citation_id`는 confidence_features에서 뽑아 별도 제공한다. F1이 미제공 필드를 요구하면 별도 API 확장 검토, 호환 시험이 필요하며, 이 문서에서는 이를 구현했다고 보고하지 않는다.

**후속 렌더링 제안:** `document_id`와 `page`로 뷰어를 선택하고 유효한 `bbox`가 있으면 해당 영역을 표시한다. bbox가 없으면 `block_id`를 현행 뷰어의 보이는 블록 목록과 대조하여 위치를 찾고, 위치를 확인할 수 없으면 상세 설명만 보여 준다. 가상의 좌표나 가공 span으로 하이라이트하지 않는다. 봉인 원문은 기존 개별 열람 절차를 거친다.

문단 복원은 별도 안정화 범위다. a1f3d1e의 `reconstruct_page_blocks()`는 문단 내부 줄들로 폭을 계산하지만 `join_lines()`의 어절 경계 미해결은 남아 있다. 7adf43f 상태를 "국소 구조 판정 완료"라고 기술하지 않는다. 화면은 원문, 검증 결과를 임의로 보정하여 시험 결과를 바꾸지 않는다.

## 5. 확인 명령과 남은 수용 절차

아래 명령은 저장소 루트에서 실행한다. 문서 사실 확인과 후속 기능의 동작 시험은 서로 구분한다.

```text
rg -n "class FindingWorkflow|class ReviewDraft|class ReviewRevision" apps/api/workspace.py
rg -n "class WorkflowInput|workflow_state|decision|revision|409|/workflow|review-draft|review-history" apps/api/routers/workspace.py
rg -n "class ReviewStatus|class FindingType" packages/common/enums.py
rg -n "class Finding|block_id|bbox|span|source_record_ids|sealed_excerpt" packages/common/schemas.py
rg -n "class FindingOut|citation_id" apps/api/schemas.py
rg -n "def _finding_out|Structured review exists" apps/api/routers/verification.py
rg -n "workflow_state|decision|review-draft|review-history" apps/web/static/workflow.js
rg -n "def review_document|library.select|batch_size|router.run|claim_coverage" packages/rag_engine/review.py
rg -n "def _semantic_review|router.cascade" packages/verification_engine/pipeline.py
rg -n "async def run|inspect_request|reserve|retry_delays|provider.generate|BUDGET_ADMISSION_FAILED|async def cascade" packages/llm_router/router.py
rg -n "run_limit|monthly_limit|max_input_tokens|max_output_tokens" packages/llm_router/budget.py
rg -n "reference-cache|No offline fallback|def select" packages/rag_engine/library.py
rg -n "cache|def request" packages/source_adapters/transport.py
python -m pytest -q tests/acceptance/test_f1_design_doc_facts.py --runxfail
```

97개 표 대조 재현 명령:

```python
from pathlib import Path
import re
from packages.common.enums import FindingType

doc = Path("docs/handoff/requests/22_f1_design_prep.md").read_text(encoding="utf-8")
rows = re.findall(r"^\| ([A-Z][A-Z0-9_]+) \| [^|]+ \| [^|]+ \|$", doc, flags=re.MULTILINE)
members = {item.name for item in FindingType}
assert len(rows) == len(set(rows)) == len(members) == 97
assert set(rows) == members
assert not any(ord(ch) < 32 and ch not in "\n\r\t" for ch in doc)
```

보호 시험의 strict xfail 표시를 이 문서 작업에서 바꾸지 않는다. `--runxfail`은 기존 기대값을 그대로 실행해 실질 통과 여부를 확인하는 명령이며, 정규 실행의 strict XPASS는 평가 담당자의 개별 승격 대상으로 남는다. 문서의 세 가지 사실 시험 통과만으로 호출 상한, 캐시, 동시 저장, 패널 기능의 구현 완료를 판단하지 않는다. 후속 F1 착수는 안정화 재평가와 기존 승인 절차를 거친다.
