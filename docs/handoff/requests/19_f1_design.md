# F1 기능 라운드 설계 요청서 (19_f1_design)

- **작성**: 구현 담당 에이전트 (Antigravity)
- **일자**: 2026-10-04
- **근거**: [FR-01 타당성 검토](docs/handoff/FR-01_review_screen_and_reference_integration.md), 사용자 확정 결정 D1~D6 (2026-10-02), [22_f1_design_prep.md](docs/handoff/requests/22_f1_design_prep.md)
- **시작 SHA**: `a04826f6959dee0e1fed9d402d61cbfbdbdf5457` (`upstream/Steve_ACASiaLAW`)
- **작업 브랜치**: `antigravity/f1-review-screen`

---

## 1. 개요 및 설계 원칙

본 설계 요청서는 기능 라운드 F1(검토 화면 중복 해소 및 참고자료 RAG 부합성 점검)의 F0 단계 산출물로서, 후속 구현(F1 축소, F2 통합 탭, F3 주장 단위 RAG)의 데이터 구조, 상태 저장 방식, 97개 전수 유형 배정표, 청구 단위 검색·대조 체계를 정의합니다.

### 핵심 설계 원칙 준수
1. **정보 손실 0 (Zero Information Loss)**: 기존 화면에서 제공되던 모든 정보는 이동/통합 후에도 동일하거나 더 높은 도달 가능성을 가집니다. HIGH 이상 Finding은 통합 탭 행 또는 상단 고정 안내로 상시 도달 가능합니다.
2. **단일 판정 (Single Verdict)**: 동일한 판례·법령 인용에 대해 화면마다 판정 및 심각도가 불일치하던 결함(실측 3/3 불일치)을 서버 측 단일 판정 객체(`review_items`)를 통해 원천 해소합니다.
3. **불확실성의 확정 변환 금지**: 참고자료(RAG) 부합성 결과는 공식 DB 미발견을 지우지 않으며(TK-29 원칙), 승격 없는 '참고 의견'으로만 표시합니다(D4 확정).
4. **하위 호환성 (추가 전용)**: 기존 JSON 필드(`documents[].findings`, `ai_hallucination_table`, `engine_data.rag`)는 일체 삭제/변경 없이 100% 유지되며, 새 객체는 추가 필드로만 제공됩니다.
5. **분야 비종속성 (Domain Invariance)**: 특정 업무 분야(예: 학교폭력 등)에 종속된 낱말이나 규칙을 코드에 하드코딩하지 않고, 일반적인 어휘 IDF 및 구조적 대조 규칙을 적용합니다.

---

## 2. 통합 탭용 서버 단일 판정 객체 (`review_items`) 설계

### 2.1 데이터 모델 명세 (`packages/common/models.py`)
통합 탭('검토 항목')에서 사용할 서버 단일 판정 객체 `ReviewItem`의 필드 구성안입니다:

```python
class EvidenceLadder(StrEnum):
    OFFICIAL_CONFIRMED = "OFFICIAL_CONFIRMED"      # 공식 원문(대법원·국가법령)에서 확인됨
    REFERENCE_SUPPORTED = "REFERENCE_SUPPORTED"    # 참고자료 본문에서 확인됨 (공식 아님, 공식 미발견 미삭제)
    OFFICIAL_NOT_FOUND = "OFFICIAL_NOT_FOUND"      # 공식 조회 범위 내 미발견 (부존재 확정 아님)
    UNCONFIRMED = "UNCONFIRMED"                    # 검증 미완료 / 범위 초과
    NOT_ASSESSED = "NOT_ASSESSED"                  # 검토 대상 외

class ReviewItemKind(StrEnum):
    CITATION = "CITATION"                          # 법령·판례·규정 인용 검토 행
    CLAIM = "CLAIM"                                # 검토 대상 주장 (TK-22 해결 후 노출)
    TEMPORAL = "TEMPORAL"                          # 시점 모순·연표 불일치 검토 행
    FACT = "FACT"                                  # 사실 관계·문서 간 모순·수치 불일치 행
    REFERENCE_OBSERVATION = "REFERENCE_OBSERVATION"# 참고자료(RAG) 대조 참고의견 행 (D4)
    UNVERIFIED_SCOPE = "UNVERIFIED_SCOPE"          # 미확인 범위 (사유 사람 말 변환 적용)

class ReviewItem(BaseModel):
    item_id: str                                   # 안정적 고유 식별자 (예: "rev_doc1_cit_123")
    kind: ReviewItemKind                           # 항목 유형
    document_id: str                               # 소속 문서 ID
    location: Optional[Dict[str, Any]] = None      # {page, paragraph_index, char_start, char_end}
    claim_text: str                                # 본문 주장 또는 인용 원문 문장
    cited_authority: Optional[str] = None          # 인용 대상 권위 (예: "2022다29841", "국가배상법 제2조의3")
    evidence: Dict[str, Any]                       # {ladder: EvidenceLadder, grade: EvidenceGrade, sources: List[str]}
    verdict_label: str                             # 통일된 판정 문구 (예: "공식 DB 미발견(원문 확인 필요)")
    severity: Severity                             # CRITICAL | HIGH | MEDIUM | LOW | INFO (단일 심각도)
    finding_ids: List[str] = []                    # 연동된 기존 Finding ID 목록
    citation_id: Optional[str] = None              # 연동된 Citation ID
    claim_id: Optional[str] = None                 # 연동된 Claim ID
    issue_ids: List[str] = []                      # 연동된 쟁점 ID 목록 (통합 탭 쟁점 필터용, D1)
    review: Optional[Dict[str, Any]] = None        # {state, decision, priority, assignee, revision}
    advisory_only: bool = False                    # 참고의견 여부 (True면 심각도 승격 없음, D4)
    reasoning_sections: Optional[Dict[str, str]]   # {validity, counter_argument, strategy}
    counteraction: Optional[str] = None            # 권고 대응 방향
```

### 2.2 기존 JSON 응답과의 대응표 (호환성 보장)

| 기존 JSON 필드 경로 | F1/F2 처리 방침 | `review_items` 내 대응 |
|---|---|---|
| `documents[].findings` | **100% 불변 유지** | Finding 정보가 `finding_ids`로 매핑되며, 단일 판정 심각도와 동기화 |
| `ai_hallucination_table` | **100% 불변 유지** | 판례 인용표 각 행이 `kind=CITATION`인 `review_items`로 정규화 매핑 |
| `engine_data.rag` | **100% 불변 유지** | 검증된 관찰 결과가 `kind=REFERENCE_OBSERVATION` (`advisory_only=True`)로 매핑 |
| `unverified_citations` | **100% 불변 유지** | `kind=UNVERIFIED_SCOPE`로 매핑, 내부 오류 문자열을 사람 말로 변환 |
| **신규 추가 필드** | `documents[].review_items` 최상위 배열 추가 (버전 계약 명시) |

### 2.3 미확인 범위 사유의 사람 말(Human-Readable) 변환 규칙
사용자 화면 및 보고서에서 기술적 내부 에러 문자열 노출을 방지합니다:

| 내부 오류 / 사유 문자열 | 변환된 사용자 안내 문구 |
|---|---|
| `Multiple versions share the requested effective boundary` | `해당 조문의 시행일자 기준 복수 개정판이 존재하여 특정 판본 확인 필요` |
| `Engine timeout / rate limit` | `공식 법률 DB 응답 지연으로 추가 확인 필요` |
| `Document truncated beyond limit` | `문서 길이 한도 초과 구간으로 수동 검토 권장` |
| `Unrecognized court / jurisdiction format` | `법원명 또는 사건번호 표기 형식 불일치로 공식 조회 불가` |

---

## 3. 행별 검토 상태 저장 방식 비교 및 권고안

### 3.1 현행 검토 상태 저장 메커니즘
- 현재 `apps/api/workspace.py`는 `finding_id`를 기본키로 하는 `FindingWorkflow`, `ReviewDraft`, `ReviewRevision`을 통해 검토 상태를 저장합니다.
- 낙관적 락(`revision` 정수): 조회 시의 revision과 저장 시의 revision이 일치해야 하며, 불일치 시 HTTP 409 Conflict를 반환합니다.
- 문제점: 기존 판례 인용표 행(`ai_hallucination_table`)에는 `finding_id`가 없고 `citation_id`만 존재하여 검토 상태 저장이 불가능합니다.

### 3.2 저장 방식 비교

| 비교 항목 | **안 (a) 기존 Finding ID 강제 연결** | **안 (b) 범용 ReviewItemWorkflow 확장 (권고안)** |
|---|---|---|
| **저장 식별자** | 오직 `finding_id`만 사용 | `subject_type` + `subject_id` (또는 범용 `item_id`) |
| **인용표 처리** | 인용 행은 연결된 Finding ID로 저장. Finding이 없는 인용(정상/일부 확인)은 '저장 불가(정보)' 처리 | Finding이 없는 인용도 `rev_cit_{citation_id}`로 독립 검토 상태 저장 가능 |
| **RAG 참고의견** | D4에 따라 Finding 승격이 없으므로 검토 상태 저장 불가 | `rev_rag_{obs_id}`로 '참고의견 검토 완료/수용' 상태 저장 가능 |
| **스키마 변경** | 스키마 변경 없음 (0 영향) | `ReviewWorkflow`에 `subject_type` 필드 추가 또는 별도 테이블 마이그레이션 |
| **기존 이력 보존** | 기존 FindingWorkflow 100% 보존 | 기존 FindingWorkflow 100% 무손실 보존 + 점진적 승계 |
| **낙관적 잠금** | 현행 revision 409 유지 | 항목별 독립 revision 409 동일 유지 |

### 3.3 권고안 (Recommendation)
- **안 (b) 기반의 점진적 확장(Phased Rollout) 권고**:
  - **1단계 (F1/F2)**: 검토 항목 중 기존 Finding에 연결되는 항목(`finding_ids` 보유)은 기존 `FindingWorkflow` API(`/findings/{id}/workflow`)를 재사용하여 즉시 저장합니다. Finding이 없는 인용 행은 임시로 '정보 확인'으로 표시합니다.
  - **2단계 (마이그레이션)**: `ReviewWorkflow` 모델을 범용 식별자(`item_id`) 기반으로 확장하고, 기존 `FindingWorkflow` 레코드를 `item_id = f"finding_{id}"`로 1:1 매핑하여 기존 검토 이력, 담당자, 우선순위, revision을 무손실 보존합니다.

---

## 4. `FindingType` 97개 전수 유형→화면 배정표

`packages/common/enums.py::FindingType`의 97개 멤버 전체를 3대 화면 묶음으로 전수 배정합니다.  
*(포렌식·위·변조 징후 유형은 사용자 결정 D3의 연장선상에서 **AI·보안 탭의 '보안 카드'**에 기본 배정)*

### 4.1 화면 배정 요약
1. **AI 작성·보안 진단 탭 (`panel-ai-security`)**: 총 45개 유형
   - **AI 생성 진단 카드**: AI 작성/환각 의심 6개 유형
   - **프롬프트 인젝션 카드**: 공격 탐지/은닉 지시문 16개 유형
   - **보안 카드 (D3 확정 및 기본 제안)**: 메타데이터 유출, 잔류 변경, 포렌식 위변조 징후, 식별자 결함 23개 유형
2. **검토 항목 (통합 탭 `panel-review-items`)**: 총 52개 유형
   - **법리·판례 인용**: 11개 유형
   - **시간축 검토**: 4개 유형
   - **사실·논리·수치**: 5개 유형
   - **증거·첨부 정합성**: 17개 유형
   - **법률적 주장 결함·권고 신호**: 12개 유형
   - **형식/처리 상태**: 3개 유형
3. **쟁점 정리 탭 (`panel-issues`, 별도 유지, D1 확정)**:
   - 쟁점 작업대 및 사건 매트릭스는 통합 탭과 분리 유지, 통합 탭에서는 `issue_ids` 필터로만 연동.

### 4.2 97개 FindingType 전수 배정 명세표

| # | FindingType | 소속 화면 패널 | 세부 카드 / 섹션 | 뱃지 라벨 |
|---|---|---|---|---|
| 1 | `AI_AUTHORSHIP_LIKELY` | AI 작성·보안 진단 | AI 진단 카드 | AI 작성 신호 |
| 2 | `AI_FULL_GENERATION_SUSPECTED` | AI 작성·보안 진단 | AI 진단 카드 | 전체 생성 의심 |
| 3 | `AI_HALLUCINATED_CONTENT` | AI 작성·보안 진단 | AI 진단 카드 | AI 환각 의심 |
| 4 | `STYLE_SHIFT` | AI 작성·보안 진단 | AI 진단 카드 | 문체 변화 |
| 5 | `MODEL_ATTRIBUTION_SIGNAL` | AI 작성·보안 진단 | AI 진단 카드 | 모델 특징 |
| 6 | `MODEL_FACT_REMARK` | AI 작성·보안 진단 | AI 진단 카드 | 모델 지적 사항 |
| 7 | `PROMPT_INJECTION_SUSPECTED` | AI 작성·보안 진단 | 인젝션 카드 | 인젝션 의심 |
| 8 | `HIDDEN_INSTRUCTION` | AI 작성·보안 진단 | 인젝션 카드 | 은닉 지시문 |
| 9 | `META_INSTRUCTION` | AI 작성·보안 진단 | 인젝션 카드 | 메타 지시문 |
| 10 | `SYSTEM_OVERRIDE_ATTEMPT` | AI 작성·보안 진단 | 인젝션 카드 | 시스템 무력화 |
| 11 | `ROLE_OVERRIDE_ATTEMPT` | AI 작성·보안 진단 | 인젝션 카드 | 역할 탈취 시도 |
| 12 | `VERIFICATION_SUPPRESSION` | AI 작성·보안 진단 | 인젝션 카드 | 검증 억제 시도 |
| 13 | `OUTPUT_MANIPULATION_ATTEMPT` | AI 작성·보안 진단 | 인젝션 카드 | 출력 조작 시도 |
| 14 | `ENCODED_INSTRUCTION` | AI 작성·보안 진단 | 인젝션 카드 | 인코딩 지시문 |
| 15 | `OBFUSCATED_INSTRUCTION` | AI 작성·보안 진단 | 인젝션 카드 | 난독화 지시문 |
| 16 | `UNICODE_SMUGGLING` | AI 작성·보안 진단 | 인젝션 카드 | 유니코드 은닉 |
| 17 | `OCR_LAYER_INJECTION` | AI 작성·보안 진단 | 인젝션 카드 | OCR 계층 삽입 |
| 18 | `METADATA_INJECTION` | AI 작성·보안 진단 | 인젝션 카드 | 메타데이터 삽입 |
| 19 | `MULTIMODAL_INJECTION` | AI 작성·보안 진단 | 인젝션 카드 | 다중모달 삽입 |
| 20 | `RAG_POISONING_SIGNAL` | AI 작성·보안 진단 | 인젝션 카드 | RAG 오염 신호 |
| 21 | `TOOL_MANIPULATION_ATTEMPT` | AI 작성·보안 진단 | 인젝션 카드 | 도구 조작 시도 |
| 22 | `DATA_EXFILTRATION_INSTRUCTION` | AI 작성·보안 진단 | 인젝션 카드 | 정보 유출 지시 |
| 23 | `AUTHORSHIP_METADATA_LEAK` | AI 작성·보안 진단 | 보안 카드 (D3) | 작성자 정보 노출 |
| 24 | `GEOLOCATION_METADATA_LEAK` | AI 작성·보안 진단 | 보안 카드 (D3) | 위치 정보 노출 |
| 25 | `METADATA_ANOMALY` | AI 작성·보안 진단 | 보안 카드 (포렌식) | 메타데이터 이상 |
| 26 | `HIDDEN_TEXT_MISMATCH` | AI 작성·보안 진단 | 보안 카드 (포렌식) | 숨은 텍스트 불일치 |
| 27 | `OCR_LAYER_MISMATCH` | AI 작성·보안 진단 | 보안 카드 (포렌식) | OCR 계층 불일치 |
| 28 | `OCR_LOW_QUALITY` | AI 작성·보안 진단 | 보안 카드 (포렌식) | OCR 품질 저하 |
| 29 | `SIGNATURE_INVALID` | AI 작성·보안 진단 | 보안 카드 (위변조) | 전자서명 무효 |
| 30 | `MODIFIED_AFTER_SIGNATURE` | AI 작성·보안 진단 | 보안 카드 (위변조) | 서명 후 변경 |
| 31 | `PAGE_STRUCTURE_OUTLIER` | AI 작성·보안 진단 | 보안 카드 (포렌식) | 페이지 구조 이상 |
| 32 | `RESIDUAL_TRACKED_CHANGE` | AI 작성·보안 진단 | 보안 카드 (잔류정보) | 변경 추적 잔류 |
| 33 | `RESIDUAL_COMMENT` | AI 작성·보안 진단 | 보안 카드 (잔류정보) | 메모/댓글 잔류 |
| 34 | `DELETED_TEXT_RECOVERABLE` | AI 작성·보안 진단 | 보안 카드 (잔류정보) | 삭제 텍스트 복원 가능 |
| 35 | `PRIOR_VERSION_RECOVERABLE` | AI 작성·보안 진단 | 보안 카드 (잔류정보) | 이전 판본 복원 가능 |
| 36 | `REDACTION_FAILURE` | AI 작성·보안 진단 | 보안 카드 (잔류정보) | 마스킹 불완전 |
| 37 | `HIDDEN_SHEET_OR_ROW` | AI 작성·보안 진단 | 보안 카드 (잔류정보) | 숨은 시트/행 잔류 |
| 38 | `CROPPED_IMAGE_RESIDUE` | AI 작성·보안 진단 | 보안 카드 (잔류정보) | 잘라낸 이미지 잔류 |
| 39 | `TEMPLATE_RESIDUE` | AI 작성·보안 진단 | 보안 카드 (잔류정보) | 서식 안내문 잔류 |
| 40 | `SPECIMEN_DOCUMENT_DECLARED` | AI 작성·보안 진단 | 보안 카드 (진정성) | 예시 서면 기재 |
| 41 | `INVALID_IDENTIFIER` | AI 작성·보안 진단 | 보안 카드 (진정성) | 유효하지 않은 식별자 |
| 42 | `PLACEHOLDER_IDENTIFIER` | AI 작성·보안 진단 | 보안 카드 (진정성) | 임시 기재 식별자 |
| 43 | `STEGANOGRAPHIC_PAYLOAD` | AI 작성·보안 진단 | 보안 카드 (은닉) | 스테가노그래피 페이로드 |
| 44 | `TRACKING_CANARY_DETECTED` | AI 작성·보안 진단 | 보안 카드 (은닉) | 추적 카나리 발견 |
| 45 | `DOCUMENT_FINGERPRINT_SUSPECTED`| AI 작성·보안 진단 | 보안 카드 (은닉) | 문서 핑거프린트 |
| 46 | `COVERT_CHANNEL_SUSPECTED` | AI 작성·보안 진단 | 보안 카드 (은닉) | 은닉 채널 의심 |
| 47 | `PRIVILEGE_EXPOSURE_RISK` | AI 작성·보안 진단 | 보안 카드 (기밀) | 비밀 특권 노출 위험 |
| 48 | `OUTBOUND_LEAK_RISK` | AI 작성·보안 진단 | 보안 카드 (기밀) | 외부 유출 위험 |
| 49 | `MODEL_OUTPUT_QUARANTINED` | AI 작성·보안 진단 | 인젝션 카드 | 모델 출력 격리 |
| 50 | `CASE_NOT_FOUND` | 검토 항목 (통합 탭) | 판례 검토 행 | 판례 미발견 |
| 51 | `CASE_METADATA_MISMATCH` | 검토 항목 (통합 탭) | 판례 검토 행 | 판례 정보 불일치 |
| 52 | `CASE_QUOTE_MISMATCH` | 검토 항목 (통합 탭) | 판례 검토 행 | 판례 인용문 불일치 |
| 53 | `CASE_HOLDING_DISTORTION` | 검토 항목 (통합 탭) | 판례 검토 행 | 판시사항 왜곡 |
| 54 | `CASE_CITATION_ERROR` | 검토 항목 (통합 탭) | 판례 검토 행 | 판례 인용 형식 오류 |
| 55 | `CASE_RELEVANCE_WEAK` | 검토 항목 (통합 탭) | 판례 검토 행 | 판례 관련성 미약 |
| 56 | `LAW_CITATION_ERROR` | 검토 항목 (통합 탭) | 법령 검토 행 | 법령 인용 오류 |
| 57 | `STATUTE_NONEXISTENT` | 검토 항목 (통합 탭) | 법령 검토 행 | 법령 미존재 |
| 58 | `STATUTE_TEXT_MISMATCH` | 검토 항목 (통합 탭) | 법령 검토 행 | 조문 내용 불일치 |
| 59 | `INTERNAL_CITATION_ERROR` | 검토 항목 (통합 탭) | 법령 검토 행 | 내부 조문 오류 |
| 60 | `ACADEMIC_CITATION_ERROR` | 검토 항목 (통합 탭) | 참고자료 인용 행 | 학술문헌 인용 오류 |
| 61 | `QUOTE_MISMATCH` | 검토 항목 (통합 탭) | 인용 검토 행 | 인용문 불일치 |
| 62 | `TEMPORAL_LAW_MISMATCH` | 검토 항목 (통합 탭) | 시간축 검토 행 | 시점 효력 불일치 |
| 63 | `TIMELINE_CONTRADICTION` | 검토 항목 (통합 탭) | 시간축 검토 행 | 연표 모순 |
| 64 | `EVIDENCE_TIMELINE_INVERSION` | 검토 항목 (통합 탭) | 시간축 검토 행 | 증거 일자 역전 |
| 65 | `EVIDENCE_DATE_INVALID` | 검토 항목 (통합 탭) | 시간축 검토 행 | 유효하지 않은 증거일 |
| 66 | `FACT_CONTRADICTION` | 검토 항목 (통합 탭) | 사실관계 검토 행 | 사실관계 모순 |
| 67 | `CROSS_DOCUMENT_CONTRADICTION` | 검토 항목 (통합 탭) | 사실관계 검토 행 | 문서 간 상호 모순 |
| 68 | `FACT_UNSUPPORTED` | 검토 항목 (통합 탭) | 사실관계 검토 행 | 근거 없는 사실 주장 |
| 69 | `ARITHMETIC_MISMATCH` | 검토 항목 (통합 탭) | 사실관계 검토 행 | 수치 계산 불일치 |
| 70 | `CROSS_DOC_COPY` | 검토 항목 (통합 탭) | 사실관계 검토 행 | 타 서면 문장 복제 |
| 71 | `LEGAL_ARGUMENT_INVALID` | 검토 항목 (통합 탭) | 법률 주장 행 | 법률 주장 결함 |
| 72 | `LEGAL_REQUIREMENT_OMITTED` | 검토 항목 (통합 탭) | 법률 주장 행 | 요건사실 누락 |
| 73 | `OVERCLAIM` | 검토 항목 (통합 탭) | 법률 주장 행 | 과다 청구 주장 |
| 74 | `UNSUPPORTED_GENERALIZATION` | 검토 항목 (통합 탭) | 법률 주장 행 | 근거 없는 전칭 명제 |
| 75 | `REASONING_GAP` | 검토 항목 (통합 탭) | 법률 주장 행 | 논리적 비약 |
| 76 | `AUTHORITY_RANK_ERROR` | 검토 항목 (통합 탭) | 법률 주장 행 | 규범 위계 오류 |
| 77 | `SOURCE_CONFLICT_IGNORED` | 검토 항목 (통합 탭) | 법률 주장 행 | 상충 출처 묵살 |
| 78 | `CALCULATION_INVARIANT_VIOLATION`| 검토 항목 (통합 탭) | 법률 주장 행 | 계산 불변식 위반 |
| 79 | `UNCERTAINTY_NOT_DISCLOSED` | 검토 항목 (통합 탭) | 법률 주장 행 | 불확실성 미고지 |
| 80 | `DRAFT_ARTIFACT` | 검토 항목 (통합 탭) | 법률 주장 행 | 초안 흔적 |
| 81 | `ISSUE_EVASION_SIGNAL` | 검토 항목 (통합 탭) | 권고 신호 (MM-4) | 쟁점 회피 신호 |
| 82 | `IMPLICIT_ADMISSION_SIGNAL` | 검토 항목 (통합 탭) | 권고 신호 (MM-4) | 암묵적 인정 신호 |
| 83 | `LIABILITY_HEDGING_SIGNAL` | 검토 항목 (통합 탭) | 권고 신호 (MM-4) | 책임 회피 신호 |
| 84 | `COERCIVE_LANGUAGE_SIGNAL` | 검토 항목 (통합 탭) | 권고 신호 (MM-4) | 강압적 표현 신호 |
| 85 | `SELECTIVE_QUOTATION_SIGNAL` | 검토 항목 (통합 탭) | 권고 신호 (MM-4) | 취사선택 인용 신호 |
| 86 | `EVIDENCE_NOT_PROVIDED` | 검토 항목 (통합 탭) | 증거 검토 행 | 증거 미제출 |
| 87 | `EVIDENCE_REFERENCE_MISSING` | 검토 항목 (통합 탭) | 증거 검토 행 | 기재 증거 누락 |
| 88 | `HASH_FORMAT_INVALID` | 검토 항목 (통합 탭) | 증거 검토 행 | 해시 형식 오류 |
| 89 | `HASH_MISMATCH` | 검토 항목 (통합 탭) | 증거 검토 행 | 파일 해시 불일치 |
| 90 | `EVIDENCE_NUMBERING_GAP` | 검토 항목 (통합 탭) | 증거 검토 행 | 호증 번호 결번 |
| 91 | `EVIDENCE_LIST_MISMATCH` | 검토 항목 (통합 탭) | 증거 검토 행 | 증거 목록 불일치 |
| 92 | `EVIDENCE_PERSON_INCONSISTENT` | 검토 항목 (통합 탭) | 증거 검토 행 | 인물 표기 불일치 |
| 93 | `EVIDENCE_FORM_DEFECT` | 검토 항목 (통합 탭) | 증거 검토 행 | 증거 형식 결함 |
| 94 | `EVIDENCE_PURPOSE_MISMATCH` | 검토 항목 (통합 탭) | 증거 검토 행 | 입증취지 범위 이탈 |
| 95 | `STATEMENT_BEYOND_PERCEPTION` | 검토 항목 (통합 탭) | 증거 검토 행 | 경험 외 단정 진술 |
| 96 | `UNSUPPORTED_FORMAT` | 검토 항목 (통합 탭) | 처리 상태 행 | 지원되지 않는 형식 |
| 97 | `PARSE_ERROR` | 검토 항목 (통합 탭) | 처리 상태 행 | 구문 분석 오류 |

### 4.3 완전성 보장 자동 시험 (`tests/web/test_f1_finding_panels.py`)
- 배정표의 97개 전수 일치성 검증 시험을 구현합니다:
```python
def test_all_finding_types_are_allocated_without_omission():
    from packages.common.enums import FindingType
    all_enum_types = set(FindingType)
    allocated_types = set(PANEL_ALLOCATION_MAP.keys())
    assert all_enum_types == allocated_types, f"미배정 또는 초과 유형 존재: {all_enum_types ^ allocated_types}"
```
- 신규 `FindingType`이 추가되었는데 화면 배정표에 등록되지 않으면 테스트가 즉시 실패하여 무단 누락을 방지합니다.

---

## 5. F3 청구(주장) 단위 검색·대조 설계

### 5.1 질의(Query) 구성 및 핵심어 추출
- **현행 한계**: 문서 전체 12,000자에서 핵심어 40개(`QUERY_TERMS`)를 추출하는 문서 단위 1회 검색으로 인해, 실측 주장 대조율이 1/17(5.9%)에 불과.
- **주장 단위 질의 구성**:
  - `verification_target`으로 지정된 개별 주장(`Claim`)의 본문 문장에서 불용어(조사·어미 등)를 제거하고 IDF 가중치가 높은 상위 핵심어(8~12개)를 선별.
  - 질의 템플릿: `f"{claim_keywords} {doc_context_keywords}"`
  - 발송 상한: **주장당 공식 검색 발송 최대 2회** (1차 검색 결과 부족 시 완화된 질의로 2차 발송).

### 5.2 상한, 배치(Batch), 및 호출 수 추정
- **주장당 LLM 대조 호출 상한**: **최대 3회** (일시 오류 재시도 및 대체 공급자 전환을 모두 포함한 엄격한 합산 카운터 적용).
- **배치 대조**: 선별된 관련 참고자료 발췌문들을 주장당 최대 6개씩 묶어 단일 LLM 프롬프트로 대조 수행.
- **호출 수 상한 추정**:
  - 검토 대상 주장 $N$개 기준: 최대 발송 수 $\le 3N$ 회로 엄격 제한.
  - `packages/llm_router/budget.py`의 `BudgetLedger.reserve()`를 통해 발송 전 원자적(Atomic) 예산 승인 진행.
  - 예산 소진 또는 호출 한도 도달 시 `BUDGET_ADMISSION_FAILED`와 함께 즉시 차단.

### 5.3 실패·부분 완료 및 범위 표시 (`claim_coverage`)
- **대조율 상시 노출**: 검토 대상 주장 $N$건 중 대조가 완료된 $M$건에 대해 `claim_coverage: M/N (XX.X%)`을 화면 및 보고서 머리에 명시.
- **미대조 항목 명확화**: 상한 초과, 타임아웃, 예산 부족 등으로 대조하지 못한 주장은 `미대조 (사유: 예산 상한 도달)` 또는 `미대조 (사유: 관련 참고자료 없음)` 등으로 명확히 표기하여 '부존재'나 '부합'으로 왜곡되지 않도록 방지.

### 5.4 근거 일치성 검증 (`grounded_observations`)
- 모델이 생성한 관찰 의견 중 다음 두 조건을 모두 만족하는 의견만 `ReviewItem`으로 채택:
  1. 서면 인용문이 실제 입력 서면 본문에 100% 부분 문자열로 존재.
  2. 참고자료 인용문이 실제 선택된 참고자료 본문에 100% 부분 문자열로 존재.
- 위 검증을 통과하지 못한 모델 환각 의견은 즉시 폐기하며, 기각된 건수만 `거부된 참고의견: K건`으로 집계 표시.

### 5.5 프라이버시 및 외부 전송 통제 (D6 확정)
- **새로운 외부 전송 설정을 만들지 않음**: 프로젝트의 `external_ai_policy`(`LOCAL_ONLY`, `MASKED`, `ORIGINAL`)를 그대로 적용.
- `LOCAL_ONLY` 정책: 외부 모델 호출 0회. 규정 조문 규칙 대조(`provision_quotes`)와 검색 매칭만 수행.
- `MASKED` 정책: 서면 주장뿐만 아니라 **참고자료 발췌문도 PII Engine을 통해 마스킹**된 후, `inspect_request()`의 전송 전 검사를 통과해야만 외부 발송.

---

## 6. 검토 요청 사항 (평가 측 확인 대상)

1. **`review_items` 필드 안 승인**: 2.1절의 필드 구조 및 기존 JSON 필드 무손실 유지 방침에 대한 적합성 확인.
2. **행별 검토 상태 저장 방식 승인**: 3.3절의 안 (b) 기반 점진적 확장(F1/F2 FindingWorkflow 재사용 -> 범용 item_id 확장)에 대한 승인 여부.
3. **포렌식·위변조 징후 배정안 승인**: 메타데이터 이상, 잔류 변경, 위변조 징후 유형을 AI·보안 탭의 '보안 카드'에 배정하는 안(4.2절) 승인 여부.
4. **F3 호출 상한 설정**: 주장당 검색 2회, 대조 3회 상한 및 `claim_coverage` 산출 방식 승인 여부.
