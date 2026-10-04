# F1 기능 라운드 개정 설계 요청서 (19b_f1_design_rev)

- **작성**: 구현 담당 에이전트 (Antigravity)
- **일자**: 2026-10-04
- **대상**: F0 설계 요청서(`19_f1_design.md`)에 대한 평가 측 회신서([docs/handoff/F1_DESIGN_REVIEW_REPLY.md](docs/handoff/F1_DESIGN_REVIEW_REPLY.md)) 조건부 승인 및 필수 수정 6건, 스키마 고정, FT 설계 보충 전면 반영
- **시작 SHA**: `a04826f6959dee0e1fed9d402d61cbfbdbdf5457` (`upstream/Steve_ACASiaLAW`)
- **병합 커밋**: `upstream/evaluator/round8-promotion` (`b3a6a43`)
- **작업 브랜치**: `antigravity/f1-review-screen`

---

## 0. 개정 개요 및 회신 반영 요약

본 문서는 `19_f1_design.md`에 대한 평가 측의 조건부 승인 회신([docs/handoff/F1_DESIGN_REVIEW_REPLY.md](docs/handoff/F1_DESIGN_REVIEW_REPLY.md))에 따라 모든 필수 수정 사항 및 보충 요구를 반영한 최종 개정 설계서입니다.

| 회신 항목 | 회신 결과 | 개정판 반영 핵심 내용 |
|---|---|---|
| **1. `review_items` 필드** | 조건부 승인 (필수 6건) | 모델 위치 `packages/common/schemas.py`로 정정, 배열 위치 `documents[].review_items` 단일화, 근거 사다리 2축(`official_status`, `reference_status`) 분리, 단일 심각도 기존 불변 및 파생 규칙 명시, `item_id` 실행 단위 및 결정적 생성 규칙 정의, 실제 사유값 기반 사람 말 변환표 갱신 |
| **2. 행별 검토 상태 저장** | 조건부 승인 (안 (b)) | 1단계(F2)는 finding 있는 행 기존 API 사용, 없는 행 '저장 불가(정보)' 표시(안 (a) 준용). 2단계 확장은 기존 `finding_workflows` 불변 새 테이블 분리로 단계화 |
| **3. 유형→화면 배정** | 승인 (재배정 2건) | 요약 수치(AI·보안 49 / 검토 48) 일치, `MODEL_FACT_REMARK`→검토 항목(사실관계), `OCR_LOW_QUALITY`→검토 항목(처리 상태) 재배정, `packages/common/finding_category_map.py` 단일 모듈화 |
| **4. F3 주장 단위 대조** | 조건부 승인 | 기존 `packages/rag_engine/review.py` 확장으로 명시, 대조 기준 모델 송신 텍스트(`_contains_flexible`), Drive 본문 검색(한글 단어만 사용, 연락처·주민번호 미포함), 문서당 주장 수(10건) 및 발췌 글자 수(4,000자) 상한 설정 |
| **5. 자유 텍스트 스키마 고정** | 신규 필수 (TK-55) | 허용 목록 키 화이트리스트 고정, 인명/당사자 키 배제, `fail-closed` 전송 차단 |
| **6. FT 설계 보충** | 신규 필수 | 목 단위 본문 대조(TK-34), 동일 시행일 복수 버전 병기·대조, 개정 성격 구분, 오탐 대조군, `rule_id` 충분성 |
| **7. 문서 형식 정비** | 필수 | 로컬 파일 경로 일체 제거 및 저장소 상대 경로 통일, CI Linux 기준 환경 명시 |

---

## 1. 개정 설계 원칙

1. **정보 손실 0 (Zero Information Loss)**: 기존 화면/보고서에서 제공되던 모든 정보는 통합 탭 또는 상단 고정 안내로 상시 도달 가능합니다.
2. **단일 판정 및 순수 파생 (Single Verdict & Pure Derivation)**: 동일 판례·법령 인용에 대한 불일치를 단일 `ReviewItem`으로 해소하되, 기존 `documents[].findings`의 심각도/필드는 100% 불변으로 보존하며 `review_items`는 오직 순수 파생값으로만 계산합니다.
3. **근거 사다리 2축 분리 (T6 원칙 준수)**: 공식 확인 여부(`official_status`)와 참고자료 지지 여부(`reference_status`)를 독립된 2축 필드로 분리하여, 참고자료 지지가 공식 미발견(`OFFICIAL_NOT_FOUND`)을 덮어쓰거나 지우지 못하도록 원천 차단합니다.
4. **추가 전용 하위 호환성 (Append-Only Compatibility)**: 기존 응답 필드는 100% 유지되며, 신규 필드는 `documents[].review_items`에만 추가됩니다.

---

## 2. 통합 탭용 서버 단일 판정 객체 (`review_items`) 상세 명세

### 2.1 실제 코드 모듈 배치 (`packages/common/schemas.py`)
기존 `Finding` 모델이 정의된 `packages/common/schemas.py`에 다음 열거형 및 Pydantic 모델을 추가합니다.

```python
from enum import StrEnum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from .enums import Severity

class OfficialConfirmationStatus(StrEnum):
    """공식 DB(대법원 종합법률정보, 국가법령정보센터) 확인 상태 (축 1)"""
    OFFICIAL_CONFIRMED = "OFFICIAL_CONFIRMED"    # 공식 원문에서 실존 및 내용 일치 확인됨
    OFFICIAL_NOT_FOUND = "OFFICIAL_NOT_FOUND"    # 공식 조회 범위 내 미발견 (부존재 확정 아님, T6 보호)
    UNVERIFIED_SCOPE = "UNVERIFIED_SCOPE"        # 조회 불가/형식 불일치/버전 모호 등 미확인 범위
    NOT_ASSESSED = "NOT_ASSESSED"                # 공식 확인 대상 아님 (예: 일반 사실관계)

class ReferenceSupportStatus(StrEnum):
    """Drive 참고자료(RAG) 대조 부합성 상태 (축 2, 승격 없는 보조 의견)"""
    SUPPORTED = "SUPPORTED"                      # 참고자료 본문에서 지지 구절 확인됨
    CONTRADICTED = "CONTRADICTED"                # 참고자료 본문과 상충 구절 확인됨
    NOT_MENTIONED = "NOT_MENTIONED"              # 참고자료 본문에 언급 없음
    NOT_CHECKED = "NOT_CHECKED"                  # 참고자료 대조 미실시 또는 대상 아님

class ReviewItemKind(StrEnum):
    CITATION = "CITATION"                        # 법령·판례·행정규칙 인용 검토 행
    CLAIM = "CLAIM"                              # 서면의 핵심 사실/법리 주장 (TK-22 해결 후)
    TEMPORAL = "TEMPORAL"                        # 행위시법·시점 모순·연표 불일치 검토 행
    FACT = "FACT"                                # 사실관계·서증 대조·수치 모순 행
    REFERENCE_OBSERVATION = "REFERENCE_OBSERVATION" # 순수 참고자료 관찰의견 행 (D4)
    UNVERIFIED_SCOPE = "UNVERIFIED_SCOPE"        # 미확인 범위 (사유 사람 말 변환 적용)
    PROCESSING_QUALITY = "PROCESSING_QUALITY"    # 처리 품질 신호 (예: OCR_LOW_QUALITY)

class ReviewItem(BaseModel):
    item_id: str                                 # 실행 단위 결정적 고유 식별자 (예: "doc1_CITATION_cit_123")
    kind: ReviewItemKind                         # 항목 종류
    document_id: str                             # 소속 문서 ID
    location: Optional[Dict[str, Any]] = None    # {page, paragraph_index, char_start, char_end}
    claim_text: str                              # 본문 주장 또는 인용 원문 구절
    cited_authority: Optional[str] = None        # 인용 대상 권위 (예: "2022다29841", "국가배상법 제2조")
    
    # 근거 사다리 2축 분리 (회신 1.3절 준수)
    official_status: OfficialConfirmationStatus  # 공식 확인 상태
    reference_status: ReferenceSupportStatus    # 참고자료 지지 상태
    evidence_sources: List[str] = []             # 근거 출처 목록
    
    verdict_label: str                           # 사용자 노출용 단일 판정 문구
    severity: Severity                           # 기존 findings로부터 순수 파생된 최고 심각도
    
    finding_ids: List[str] = []                  # 연동된 기존 Finding ID 목록
    citation_id: Optional[str] = None            # 연동된 Citation ID
    claim_id: Optional[str] = None               # 연동된 Claim ID
    issue_ids: List[str] = []                    # 연동된 쟁점 ID 목록 (통합 탭 쟁점 필터용)
    
    review: Optional[Dict[str, Any]] = None      # 행별 검토 상태 (F2에서는 finding 있는 행만)
    advisory_only: bool = False                  # 참고의견 여부 (True면 심각도 승격 없음)
    reasoning_sections: Optional[Dict[str, str]] = None  # {validity, counter_argument, strategy}
    counteraction: Optional[str] = None          # 권고 대응 방향
```

### 2.2 배열 위치 단일화 및 계약 버전
- **단일 위치**: `documents[].review_items` (문서별 하위 배열). 결과 최상위 배열 표기는 전면 삭제합니다.
- **계약 변화**: 기존 JSON 구조(`documents[].findings`, `ai_hallucination_table`, `engine_data.rag`)는 100% 동일하게 유지되며, `documents[].review_items`가 추가 필드로 탑재됩니다.

### 2.3 단일 심각도 순수 파생 규칙
- `review_items`의 `severity`는 **순수 파생값(pure derived value)**입니다:
  ```python
  def derive_item_severity(linked_findings: List[Finding]) -> Severity:
      if not linked_findings:
          return Severity.INFO
      # Severity.rank 기준 최고 심각도 선택 (기존 findings 값 불변)
      return max(linked_findings, key=lambda f: f.severity.rank).severity
  ```
- 기존 `documents[].findings`의 필드나 심각도는 절대 변경하지 않습니다 (기존 필드 불변 및 점수 불변 원칙 준수).

### 2.4 `item_id`의 범위 및 결정적 생성 규칙
- `item_id`는 **실행 단위(run-scoped)** 식별자입니다.
- 동일 실행 내에서 결정적으로 생성합니다:
  - 인용 행: `f"{doc_id}_CITATION_{citation_id}"`
  - 단일 Finding 연결 행: `f"{doc_id}_FINDING_{finding_id}"`
  - 복수 Finding 연결 행: `f"{doc_id}_{kind}_{sorted(finding_ids)[0]}"`
  - RAG 관찰 행: `f"{doc_id}_OBS_{source_id}_{obs_index}"`
- 재실행 간 검토 상태 인계는 현행 시스템에도 존재하지 않는 기능이므로, 이번 F1/F2 범위에 포함하지 않습니다.

### 2.5 사람 말(Human-Readable) 변환표 (실제 코드 사유값 전수 대조)
실제 코드베이스(`packages/`)에 존재하는 사유 문자열을 전수 대조하여 사람 말 변환 규칙을 수립하였습니다:

| 실제 코드 사유값 | 발생 위치 | 사용자 노출 변환 문구 |
|---|---|---|
| `Multiple versions share the requested effective boundary` | `packages/source_adapters/legal_history.py:106` | 해당 조문의 시행일자 기준 복수 개정판이 존재하여 특정 판본 확인 필요 |
| `NO_READABLE_DRIVE_REFERENCE` | `packages/rag_engine/review.py:135` | 판독 가능한 Drive 참고자료 문서 없음 |
| `RELEVANT_REFERENCES_NOT_FULLY_READ` | `packages/rag_engine/review.py:131` | 참고자료 분량 초과로 일부 문서 미대조 |
| `NO_TEXT_AFTER_REMOVING_INSTRUCTIONS` | `packages/rag_engine/review.py:110` | 지시문 제거 후 분석 대상 본문 텍스트 부족 |
| `DOCUMENT_UNREADABLE` | `packages/rag_engine/review.py:103` | 서면 문서 텍스트 정규화 실패로 판독 불가 |
| `REFERENCE_LIBRARY_UNAVAILABLE` | `packages/rag_engine/review.py:106` | 참고자료 라이브러리 색인 준비 미완료 |
| `BUDGET_ADMISSION_FAILED` | `packages/llm_router/router.py` | 요청 예산 한도 도달로 모델 대조 미실시 |
| `MODEL_NOT_AVAILABLE_OR_QUICK_PROFILE` | `packages/rag_engine/review.py:147` | 빠른 검토 프로필 설정 또는 모델 가용성 부족 |
| `document_truncated` | `packages/rag_engine/review.py:112` | 서면 길이 한도 초과로 일부 구간 수동 검토 권장 |

- **안전 대체 경로**: 위 표에 정의되지 않은 새 사유값이 발생할 경우 `f"미확인 사유: {original_reason}"` 형태로 원본 코드를 그대로 노출하여 사유가 누락되거나 사라지지 않도록 보장합니다.
- 미대응 사유 발생 시 실패하는 단위 시험을 `tests/test_unverified_reasons.py`에 구현합니다.

---

## 3. 행별 검토 상태 저장 (F2 단계적 확장안)

회신서 2절 조건부 승인에 따라 다음과 같이 2단계로 분리합니다:

1. **1단계 (F2 구현 범위)**:
   - `finding_id`가 연결된 행은 기존 `FindingWorkflow` API (`/api/workspace/projects/{p_id}/findings/{finding_id}/workflow`)를 그대로 재사용합니다.
   - Finding이 연결되지 않은 순수 인용 행이나 처리 상태 행은 화면에서 **'저장 불가(정보)'** 상태로 표시하고 체크/수정 인터페이스를 비활성화합니다.
   - 기존 테이블이나 API 수정 없이 안전하게 F2 UI를 완성합니다.

2. **2단계 (F2 이후 확장 요건 명시)**:
   - 기존 `finding_workflows` 행을 수정하거나 변경하지 않고, 별도의 `review_item_workflows` 신규 테이블을 추가합니다.
   - 마이그레이션 스크립트는 SQLite와 PostgreSQL 양쪽에서 작성·검증하며, rollback 절차를 필수로 구비합니다.
   - 감사 기록(`audit chain`)에 새 `subject_type="REVIEW_ITEM"` 이벤트를 등록합니다.
   - 본 2단계는 F2 브랜치에 포함하지 않고 후속 개선 과제로 분리합니다.

---

## 4. 97개 전수 유형 화면 배정표 및 단일 모듈화

### 4.1 배정 요약 수치
- **전체 FindingType 수**: 97개
- **AI·보안 탭 배정**: **49개** (적대적 인젝션 16개 + MM4 권고 5개 + 포렌식/위변조 28개)
- **검토 항목 탭 배정**: **48개** (법률/인용 9개 + 사실/모순 26개 + 시점/연표 11개 + 처리 상태 2개)
- 요약 수치와 상세 표의 총합이 97개로 완벽히 일치합니다.

### 4.2 필수 재배정 내역 (회신서 3절 반영)
1. **`MODEL_FACT_REMARK` → 검토 항목 (사실관계, 참고 표시)**:
   - 생성 코드(`packages/ai_document_detector/detector.py`의 `_fact_remark_finding`)에서 "AI 작성 근거가 아니라 내용 검증 대상"으로 명시하고 `advisory_only=True`이므로, T4(AI 탭 배타성) 준수를 위해 검토 항목 탭으로 재배정합니다.
2. **`OCR_LOW_QUALITY` → 검토 항목 ('처리 상태')**:
   - `pipeline.py`가 쪽 단위 OCR 품질로부터 생성하는 처리 품질 신호이므로 위·변조 징후가 아닌 검토 항목의 '처리 상태'로 재배정합니다.
3. **`AI_HALLUCINATED_CONTENT`·`PLACEHOLDER_IDENTIFIER`·`INVALID_IDENTIFIER`**:
   - `AI_HALLUCINATED_CONTENT`: 환각 모델 이상 탐지 카테고리로 AI·보안 탭에 배정하되, 현재 a04826f 코드에서는 미생성(enum만 존재).
   - `PLACEHOLDER_IDENTIFIER`, `INVALID_IDENTIFIER`: `packages/forensic_engine/specimen.py`에서 서식 조작/식별자 위변조 징후를 탐지하므로 보안 카드에 배정. 판례 인용 검증과 충돌하지 않음을 확인.

### 4.3 배정표 단일 모듈화 (`packages/common/finding_category_map.py`)
- 서버 단일 모듈에 97개 전수 배정 매핑 딕셔너리(`FINDING_TYPE_CATEGORY_MAP`)를 정의합니다.
- API 엔드포인트 `GET /api/finding-categories`를 통해 프론트엔드와 공유하여 화면과 서버가 100% 동일한 배정 기준을 참조하도록 합니다.
- `tests/test_finding_categories.py`를 신설하여:
  - 97개 `FindingType` 멤버의 100% 매핑 보장.
  - `ADVERSARIAL_FINDING_TYPES` 16개 전수가 보안 카드로 배정되었는지 검증.
  - `MM4_ADVISORY_TYPES` 5개 전수가 권고 카드로 배정되었는지 검증.
  - `LEGAL_FINDING_TYPES` 9개 전수가 검토 항목으로 배정되었는지 검증.
  - `MODEL_FACT_REMARK`가 AI 탭이 아닌 검토 항목에 배정되었는지 검증.

---

## 5. F3 주장 단위 Drive 본문 검색 및 대조 보완

### 5.1 기존 함수 확장 명세 (`packages/rag_engine/review.py`)
기존에 구축된 `grounded_observations` 및 `claim_coverage` 함수를 재사용 및 확장합니다:
- **대조 기준**: 회신 4.1절에 따라 서면 원문 100% 부분 문자열이 아니라, **모델에 전송된 마스킹 텍스트 기준**으로 유연 대조(`_contains_flexible`)합니다. 이를 통해 마스킹된 인용이 부당하게 기각되는 결함을 원천 방지합니다. 화면 노출 위치는 원문 텍스트 인덱스로 역매핑합니다.
- **Drive 본문 검색 명시**: 공식 법률 DB 조회가 아닌 **Drive 본문 검색**(`drive.search_fulltext`, `fullText contains`)임을 명확히 합니다.
- **질의어 성질 유지**: 현행 Drive 질의어 정책대로 2자 이상 한글 단어(`salient_words`, 최대 5개)만 사용하며, 숫자열(전화번호, 주민등록번호)이 질의어에 일체 포함되지 않도록 유지하고 전용 단위 시험으로 보증합니다.
- **기존 점수·임계값 재사용**: 임의의 새 휴리스틱(IDF 8~12 등) 대신 현행 `relevance.py`의 `query_profile` 및 `salient_words` 함수를 그대로 사용합니다.

### 5.2 문서 단위 상한 및 매니페스트 기록
- **상한 규칙**:
  - 주장당 상한: Drive 검색 최대 2회, LLM 대조 호출 최대 3회 (재시도/대체 포함 합산).
  - 문서당 대조 주장 수 상한: 최대 10개 주장.
  - 대조 발췌문 묶음 글자 수 상한: 최대 4,000자.
- 상한 초과로 대조되지 못한 주장은 `claim_coverage` 분모에 유지하고 `unreviewed` 사유(`REASON_BUDGET_EXCEEDED`)로 명시합니다.
- 상한 상수는 `packages/common/config.py`에 선언하고 `manifest`에 기록합니다.

### 5.3 개인정보 필수 게이트 준수
- 2026-10-04 정책에 따라 연락처 및 주민등록번호에 대해 누락 0, 도달 0, 오탐 0 필수 게이트를 통과한 상태에서만 F3를 진행합니다.

---

## 6. 빠진 항목 1 — 자유 텍스트 키 허용 목록 (스키마 고정, TK-55 대응)

F3가 모델로 전송하는 구조화 요청 본문의 키 목록을 엄격히 화이트리스트로 고정합니다:

### 6.1 요청 본문 스키마 화이트리스트
```python
STRUCTURED_REQUEST_ALLOWED_KEYS = {
    "system_instructions": {"type": str, "max_length": 2000, "contains_free_text": False},
    "claim_id":            {"type": str, "max_length": 50,   "contains_free_text": False},
    "claim_text":          {"type": str, "max_length": 1000, "contains_free_text": True},
    "reference_sources":   {"type": list, "max_items": 5,    "contains_free_text": True},
}
```
- **Fail-Closed 원칙**: 화이트리스트 외의 키가 포함된 요청 객체는 `LLMRouter.run` 진입 전 즉시 차단(거절)합니다.
- **인명/당사자 키 배제**: `client_name`, `party_name`, `suspect`, `victim` 등 인명을 가리키는 키는 스키마에 일체 두지 않습니다.
- **자유 텍스트 키 집중 검사**: 자유 텍스트를 허용하는 키(`claim_text`, `reference_sources[].text`)에 대해서만 전송 전 검사(`inspect_request`)를 수행합니다.
- **응답 스키마와의 대응**: 기존 `ITEM_SCHEMA` 및 `ENVELOPE_SCHEMA`의 `claim_quote`, `source_quote`, `explanation`과 1:1로 정확히 대응합니다.

---

## 7. 빠진 항목 2 — FT(행위시법 검토 보강) 설계 보충

2026-10-04 사용자 결정에 따라 본 라운드에 통합된 행위시법(FT) 검토 보강 설계안입니다:

### 7.1 목 단위 본문 대조 방식 (TK-34 해결)
- 현행 `packages/source_adapters/legal_history.py`의 조문 파싱 로직(`parse_law_body`)을 확장하여, 조(Article) 단위뿐만 아니라 **호(Item) 및 목(Sub-item)** 단위까지 분할 파싱합니다.
- 행위일자 당시 시행되던 규정과 현행 규정 간에 조 번호가 같더라도 하위 호·목이 신설/삭제/개정된 경우를 감지하여 정밀 대조합니다.

### 7.2 동일 시행일 복수 버전 병기 및 대조 (요청 16)
- 현행 코드 `packages/source_adapters/legal_history.py:106`의 `raise ValueError("Multiple versions share the requested effective boundary")` 예외 경로를 다음과 같이 안전하게 대체합니다:
  - 동일 시행일을 공유하는 복수 법령 개정판(예: 법률 제12345호, 제12346호 동시 시행)이 존재할 경우, 예외를 던지는 대신 **두 버전을 모두 추출하여 병기(Both Versions Presented)**합니다.
  - 두 버전의 조문을 대조하여 차이점을 `FT_MULTI_VERSION_AMBIGUITY` 안내 신호와 함께 사용자 화면에 표시합니다.

### 7.3 번호만 바뀐 개정 vs 내용이 바뀐 개정 구분
- 조문 번호만 자구 이동(예: 제3조 -> 제4조)되고 본문 실질 내용이 동일한 경우(`_clean_str(text1) == _clean_str(text2)`):
  - 심각도: `INFO` (단순 조문 이동 안내)
- 조문 번호 유지 여부와 무관하게 구성요건이나 법정형 등 본문 실질 내용이 변경된 경우:
  - 심각도: `HIGH` (실질 법리 변경 경고)

### 7.4 오탐 대조군 계획
- 법령명만 언급되고 특정 조문이 인용되지 않은 일반 서술문 5건.
- 개정 이력이 전혀 없는 단일 제정 법률 인용 서면 5건.
- 시행일 이전 행위에 대해 유리한 신법을 명시적으로 원용하는 정당한 소급효 주장 서면 5건.
- 위 15건의 대조군에 대해 불필요한 행위시법 경고가 발생하지 않는지 검증합니다.

### 7.5 기존 `rule_id`의 충분성
- 기존 `TEMPORAL_LAW_MISMATCH`, `AMBIGUOUS_LAW_VERSION`, `OUTDATED_PROVISION_CITED` 3개 규칙으로 기본 커버리지가 확보되며, 목 단위 변경 안내를 위한 `SUB_PROVISION_AMENDMENT` 1종만 추가 정의하여 충분히 커버 가능합니다.

---

## 8. 실행 환경 및 문서 링크 정비

- **실행 환경**: 본 개정안 작성 및 향후 F1/F2 구현 검증은 CI 환경(Linux, Python 3.11, Tesseract 5.3.4)과의 일치를 원칙으로 하며, Windows 로컬 환경에서 실행 시 환경 차이와 영향을 보고서에 명확히 밝힙니다.
- **상대 경로**: 본 문서 및 향후 모든 보고서의 링크는 저장소 상대 경로(`docs/handoff/...`)로만 기술하며, 로컬 파일 시스템 경로(`file:///C:/...`)는 일체 포함하지 않습니다.

---

## 9. 결론 및 F1·F2 착수 선언

회신서([docs/handoff/F1_DESIGN_REVIEW_REPLY.md](docs/handoff/F1_DESIGN_REVIEW_REPLY.md)) 0절에 따라:
1. `review_items` 필수 수정 6건 반영 완료.
2. 행별 검토 상태 저장 1단계(F2) 및 2단계 분리 완료.
3. 97개 전수 유형 배정표 수치 정정, 재배정 2건, 단일 모듈화 완료.
4. F3 기존 함수 확장 및 스키마 고정(TK-55) 반영 완료.
5. FT 설계 보충 반영 완료.

조건부 승인 조건이 모두 충족되었으므로, **F1(상세 패널 탭 축소 및 AI·보안 카드 분리) 및 F2(검토 항목 통합 탭 및 단일 판정 연동) 구현에 즉시 착수**합니다.
