# F3 1단계 설계 보충 메모 (개정 1) — 참고자료(RAG) 부합성 점검 강화

- **작성**: 구현 에이전트 (Antigravity)
- **일자**: 2026-10-07
- **개정 이력**: 개정 1 (PR #32 평가 측 보완 요구 8건 및 사실 정정 5건 전면 반영)
- **대상 지시서**: [docs/handoff/PROMPT_FOR_F3.md](../PROMPT_FOR_F3.md)
- **기준 커밋**: `Steve_ACASiaLAW` 최신 (`7110273830362d46c1b4df9fa049c39a262f7f7e`, PR #31 병합 완료)
- **작업 브랜치**: `antigravity/f3-reference-review` (base: `Steve_ACASiaLAW`, PR #32)
- **제출 성격**: **1단계: 설계 보충 전용 (제품 코드·보호 시험 변경 0, 본 설계 문서 1건만 제출)**

---

## 0. 기확정 사항 전제 (지시서 2절 재설계 금지 원칙 준수)

본 설계서는 지시서 2절에 명시된 기확정 사항을 엄격한 불변 전제로 삼으며, 이를 다시 설계하지 않습니다:

1. **D4 출력 원칙**: 참고자료 대조 의견은 '참고 의견'(`advisory_only=True`)이며, 심각도·finding 승격을 일절 두지 않고 검토 상태만 기록합니다. TK-09 후보 승격(`candidate_promotion_enabled`)은 계속 차단 상태를 유지합니다.
2. **D6 전송 원칙**: 기존 라우터(`LLMRouter`), `external_ai_policy`, 라우터 내부 전송 전 검사(`packages/llm_router/router.py:367` 경유 `inspect_request`)를 그대로 사용합니다. 참고자료 전용 외부 전송 설정이나 신규 우회 경로를 만들지 않으며, `LOCAL_ONLY` 및 `QUICK` 모드에서는 외부 모델을 일체 부르지 않고 규칙 대조(`provision_quotes`)와 검색 메타데이터만 산출합니다.
3. **19b 5절 조건부 승인분**: 기존 `packages/rag_engine/review.py`(`grounded_observations`·`claim_coverage`)를 확장합니다. 대조 기준은 모델에 전송된 마스킹 텍스트(`_contains_flexible`)이며, Drive 본문 검색(`drive.search_fulltext`) 질의는 `relevance.py`의 `salient_words` 기반 2자 이상 한글 단어로만 구성하고 숫자열을 배제합니다. 상한(주장당 검색 2회 / 공급자 요청 3회, 문서당 주장 10개, 발췌 묶음 4,000자)을 엄수하며, 상한 초과 주장은 `claim_coverage` 분모에 유지하고 `REASON_BUDGET_EXCEEDED` 사유를 부여합니다.
4. **19b 6절 요청 본문 스키마(TK-55)**: 허용 키 4개 화이트리스트(`system_instructions`, `claim_id`, `claim_text`, `reference_sources`)를 고정하고 fail-closed로 전송을 차단하며, 인명/당사자 키를 일체 두지 않습니다.
5. **근거 사다리 2축 분리**: `ReviewItem.official_status`(`OfficialConfirmationStatus`)와 `ReviewItem.reference_status`(`ReferenceSupportStatus`: SUPPORTED, CONTRADICTED, NOT_MENTIONED, NOT_CHECKED)는 상호 독립된 별개 축으로 운영됩니다.
6. **규칙·지표 불변 원칙**: 신규 `rule_id` 0건, 신규 `FindingType` 0건, 고정 시험(dev 81.7 / holdout 79.2 / 오탐 0) 및 probe 점수 변화 0을 보장합니다.

---

## 1. `reference_status` 채우기 (F3a · F3c)

### 1.1 대조 결과가 `ReviewItem.reference_status`로 들어가는 유입 경로 및 우선순위
1. **대조 수행 모듈 (`packages/rag_engine/review.py`)**:
   - `review_document` 함수 실행 시, 사용자 참고자료 대조를 통해 다음 결과를 `result.engine_data["rag"]`에 적재합니다:
     - `observations`: 검증 통과된 관찰의견 목록 (`[{"claim_quote": ..., "source_id": ..., "source_quote": ..., "relationship": "SUPPORTS"|"CONTRADICTS"|"CONTEXT"|"INSUFFICIENT", "explanation": ...}]`)
     - `reference_matches`: 인용 대상(사건번호 또는 법령명+조문)과 본문을 실제로 읽은 참고자료(`summary["sources"]`) 본문 간의 동일 인용 매칭 맵 (`Dict[str, Dict[str, Any]]`, 키는 `citation_id`):
       ```python
       # reference_matches[cid] 구조 예시
       {
           "status": ReferenceSupportStatus.SUPPORTED,
           "source_id": "ref_01",
           "source_title": "[RAG참고자료] 취업규칙.pdf",
           "file_id": "refsafety000000001",
           "drive_link": "https://drive.google.com/file/d/refsafety000000001/view",
           "matched_authority": "2019다246795"
       }
       ```
2. **관찰의견과 인용의 연결 방식 (`packages/rag_engine/contract_facts.py:119`)**:
   - 모델 관찰의견과 인용 행은 텍스트 유사도 매칭이 아니라, 기존 `link_observations`가 산출하는 `issues`의 `claim_ids`를 매개로 연결합니다.
   - 각 인용(`Citation`)이 보유한 `claim_id`와 `issues` 내 각 관찰의견의 `claim_ids`가 일치하는 경우 해당 인용 행에 관찰의견이 귀속됩니다.
3. **통합 객체 생성 모듈 (`packages/verification_engine/review_items.py`)**:
   - `build_document_review_items` 함수 내 인용 행 생성 루프(`for cit in citations:`)에서 `rag_data = engine_data.get("rag", {})`의 `reference_matches` 및 `issues`를 참조하여 `reference_status`를 결정합니다.
   - **엄격한 상태 우선순위**:
     $$\mathbf{CONTRADICTED > SUPPORTED > NOT\_MENTIONED > NOT\_CHECKED}$$
     1) **`CONTRADICTED` (최우선)**:
        - 해당 인용과 연결된 관찰의견(`link_observations`의 issue) 중 근거 인용구가 확인된 `relationship == "CONTRADICTS"` 의견이 존재하는 경우.
        - 동일성 대조에서 SUPPORTED 매칭이 있더라도 참고자료와의 모순/상충 경고가 가려지지 않도록 `CONTRADICTED`를 최우선 부여합니다.
     2) **`SUPPORTED` (동일성 대조 U1 전용)**:
        - 인용 동일성 대조(`reference_matches`)에서 해당 `citation_id`에 대해 실질적 일치(`SUPPORTED`)가 확인된 경우.
        - **원칙**: 모델 의견의 `SUPPORTS`는 판례·조문의 실질 존재를 보증하지 않으므로, **인용 행(`ReviewItemKind.CITATION`)의 `SUPPORTED`는 오직 규칙 기반 인용 동일성 대조(U1)에서만 도출**됩니다. 모델의 `SUPPORTS` 의견만 있는 경우에는 인용 행을 `SUPPORTED`로 올리지 않고 주장 행 또는 별도의 `REFERENCE_OBSERVATION` 행으로 보존합니다.
     3) **`NOT_MENTIONED`**:
        - 본문을 읽은 참고자료가 존재하여 대조를 수행하였으나, 동일성 대조에서 해당 인용의 언급이 전혀 발견되지 않은 경우(`NOT_MENTIONED`는 오직 '대조 본문에 언급 없음'일 때만 적용).
        - **주의**: 모델 의견의 `CONTEXT`나 `INSUFFICIENT`를 `NOT_MENTIONED`로 변환하지 않습니다.
     4) **`NOT_CHECKED`**:
        - 참고자료가 없거나 읽기 실패하여 대조가 수행되지 않았거나 대조 대상이 아닌 경우.

### 1.2 공식 미발견 인용의 참고자료 대조 처리 (T6 보호 시험 원칙)
- **독립 축 보존 (No Overwrite)**:
  공식 DB 조회 결과 해당 판례나 법령이 발견되지 않아 `official_status == OfficialConfirmationStatus.OFFICIAL_NOT_FOUND`로 판정된 경우, 참고자료 본문에 해당 인용이 존재하더라도:
  - `official_status`는 절대로 변경되지 않고 **`OfficialConfirmationStatus.OFFICIAL_NOT_FOUND`를 100% 유지**합니다.
  - 기존의 부존재/미확인 관련 `Finding` 목록, `severity`(심각도), `verdict_label`도 일체 승격되거나 변경되지 않습니다 (D4 원칙 준수).
- **참고자료 축 지지 및 Drive 링크 필수 반영**:
  - `item.reference_status = ReferenceSupportStatus.SUPPORTED`
  - `item.evidence_sources`에는 단순 제목 문자열뿐만 아니라, **보호 시험 T6이 확인하는 Drive 식별자(`file_id`가 든 URL/문자열)**를 반드시 포함합니다:
    ```python
    item.evidence_sources.append(
        f"참고자료(공식 법령·판례 아님): {source_title} (https://drive.google.com/file/d/{file_id}/view)"
    )
    ```
  - 이를 통해 `(row["official_status"], row["reference_status"]) == ("OFFICIAL_NOT_FOUND", "SUPPORTED")` 상태가 형성되어, 공식적 권위의 부존재 사실과 사적 참고자료의 지지 사실이 명확히 공존합니다.

### 1.3 인용 동일성 대조 규칙 (5차 U1 · TK-29 재사용)
`tests/acceptance/test_reference_match_guard.py`에 고정된 5차 U1(TK-29) 가드를 그대로 재사용하며, 다음 규칙을 엄격히 적용합니다:
1. **읽기 성공 본문 한정**:
   - `ReferenceLibrary`의 `summary["sources"]`에 등록된, **실제로 본문을 읽은 문서(READ/OK)**의 본문만을 대조 대상으로 합니다.
   - `inventory` 목록에만 존재하는 미처리 문서, 읽기 실패 문서(HTTP 403, 파싱 에러 등)는 대조 대상에서 원천 배제합니다.
2. **사건번호 대조 (경계 일치)**:
   - 정규화된 사건번호(`canonical_case_number`, 예: `2019다246795`)의 **경계 일치(Word Boundary Match)**를 적용합니다.
   - 앞뒤에 숫자가 붙어 다른 사건번호가 되는 것을 방지하기 위해 정규식 경계(`(?<!\d)2019다246795(?!\d)`)로 본문 일치를 판정합니다.
3. **법령 대조 (근접 대조)**:
   - 정규화된 법령명과 해당 조문 번호('법령명 + 조')가 동일 문장 또는 동일 발췌 구간(100자 이내)에 함께 출현하는 근접 기준(Proximity Match)을 적용합니다.
4. **마스킹 본문 대조 근거**:
   - 대조 대상 본문은 외부 모델에 전송되는 본문과 동일한 마스킹 본문입니다.
   - `packages/llm_router/privacy.py`의 마스킹 대상은 전화번호, 주민등록번호, 계좌번호 등 개인식별정보(PII)에 한정되며, 사건번호 및 법령 조문 번호는 마스킹 대상에서 제외되므로 마스킹 후에도 100% 보존되어 대조가 정확히 성립합니다.
5. **규칙 대조의 상시 실행**:
   - 동일성 대조는 순수 규칙 기반 대조이므로, **`LOCAL_ONLY` 및 `QUICK` 프로필에서도 정상 실행**되어 `reference_matches`와 `reference_status`를 산출합니다 (D6 원칙).
6. **제목 일치 차단**:
   - 참고자료 파일명/제목에 가공 법령명이나 사건번호가 포함되어 있다는 이유만으로 지지(`SUPPORTED`)로 올리지 않으며, 반드시 본문 텍스트 내 실질 인용이 확인된 경우에만 지지 상태를 부여합니다 (제목 부분 일치 배제).

---

## 2. 위계 표시 (F3a)

### 2.1 모든 Drive 출처에 "참고자료(공식 법령·판례 아님)" 고정 표기
- 모든 Drive 기반 대조 결과, 관찰의견, 출처 목록에 고정 한계 문구를 명시합니다:
  - `ReviewItem.evidence_sources`: `f"참고자료(공식 법령·판례 아님): {source_title} (https://drive.google.com/file/d/{file_id}/view)"` 형태로 출처 문자열을 표준화합니다 (`file_id` 포함 필수).
  - (`ReviewItem` 스키마에는 `authority_limitation` 필드가 존재하지 않으므로, 신규 필드를 무단 추가하지 않고 `evidence_sources` 문자열 머리말 및 UI 툴팁을 통해 위계 한계를 명확히 전달합니다.)
  - 화면 UI 배지: Drive 참고자료 배지에 `[참고자료 (공식 법령·판례 아님)]` 툴팁 및 안내 문구를 고정 렌더링합니다.

### 2.2 자료 이름·폴더 낱말로 법령·지침 추측 분류 금지
- 파일명이나 폴더 경로에 `"법률"`, `"대통령령"`, `"훈령"`, `"예규"`, `"지침"`, `"규정"` 등의 단어가 포함되어 있더라도, 이를 근거로 공적 규범 위계를 추측하거나 자의적으로 분류하지 않습니다 (낱말 사전/휴리스틱 매핑 일체 금지).
- Drive에 업로드된 모든 자료는 공적 효력이 없는 **동일한 위계의 '사적 참고자료'**로 일관되게 취급합니다.

---

## 3. 주장 단위 검색 및 대조 (F3b)

### 3.1 현행 문서 단위 경로 유지 및 주장 단위 단계 추가
1. **문서 단위 경로 유지**:
   - 현행 `packages/rag_engine/review.py`의 `batches` 기반 배치 대조(서면 전체 텍스트와 참고자료 묶음 대조)는 제거하지 않고 100% 보존합니다.
2. **주장 단위 단계 추가 (선택적 심층 대조)**:
   - 배치 대조 완료 후, 서면의 적격 주장 목록(`claims`, `DOCUMENT_META` 및 `ADVERSARIAL_INSTRUCTION` 제외, 최대 10개 주장)을 순회하며 주장 단위 검색 및 모델 대조를 수행합니다:
     1) **Drive 본문 검색 및 처리 방식 ((a) 라이브러리 색인 우선)**:
        - 각 주장의 텍스트로부터 추출한 `salient_words`(2자 이상 한글 단어, 숫자열 배제)로 `drive.search_fulltext` 실행 (주장당 최대 2회 검색).
        - **미독 파일 처리 원칙 (선택 (a))**: `search_fulltext`가 반환한 `file_id` 중 **이미 본문을 읽어 라이브러리에 색인된 문서(`summary["sources"]`) 안에서만 찾기**를 채택합니다. 아직 읽지 않은 파일(미독 파일)은 U1상 대조할 본문이 없으므로, 추가 다운로드 예산 소진이나 지연을 방지하기 위해 이미 읽은 유효 본문 풀 내에서만 발췌를 구성합니다.
        - **검색 거절 처리**: `search_fulltext` 실행 중 `DRIVE_HTTP_401`, `DRIVE_HTTP_403`, `DRIVE_HTTP_429`, `DRIVE_FULLTEXT_FORBIDDEN`, `SYNC_BUDGET_EXHAUSTED` 등의 거절 예외 발생 시, `packages/rag_engine/library.py:220`의 기존 게이트 패턴과 동일하게 반복하지 않고 즉시 루프를 중단(`break`)합니다.
     2) **발췌문 묶음 (길이 한도 엄수)**:
        - 색인된 참고자료 본문에서 해당 주장과 관련된 발췌문(최대 5개 항목, 총합 최대 4,000자 `EXCERPT_CHARS`)을 구성.
     3) **모델 대조 요청**:
        - 주장당 `LLMRouter.run`을 단 1회 호출하여 부합성 대조 수행 (5.3절에 따라 공급자 요청 최대 3회로 엄격 제한).

### 3.2 두 경로의 결과 합치는 결정적 규칙 (중복 제거)
- **중복 제거 (Deduplication)**:
  - 문서 단위 배치 대조의 `observations`와 주장 단위 대조의 `observations`를 합칠 때, `(obs["claim_quote"], obs["source_quote"])` 튜플을 고유 키로 삼습니다.
  - 동일한 키를 가진 의견이 양쪽 경로에서 모두 산출된 경우, 다음의 **결정적 규칙(Deterministic Rule)**으로 단일 의견을 채택합니다:
    1) 설명(`explanation`) 문자열의 길이가 더 긴 의견을 우선 채택.
    2) 설명 길이가 동일한 경우, 주장 단위 대조에서 생성된 의견을 우선 채택.
- **규칙 대조 우선권**:
  - 규칙 기반 조항 인용 대조(`provision_quotes`) 결과는 모델 의견보다 우선하여 보존합니다.
- **후보 승격 차단 (TK-09 가드)**:
  - 모든 관찰의견에는 `advisory_only = True` 속성을 고정 바인딩하여 TK-09 모델 의견 후보 승격 경로(`candidate_promotion_enabled`)에 진입하지 못하도록 원천 차단합니다 (D4 원칙).

### 3.3 전후 비교(A/B Comparison) 측정 방법
- 주장 단위 도입의 실효성과 추가 효과를 정량 검증하기 위해, `engine_data["rag"]["comparison_metrics"]`에 다음 메트릭을 기록합니다:
  ```json
  {
      "batch_only_observations": 3,
      "batch_accepted_count": 2,
      "claim_level_observations": 5,
      "claim_accepted_count": 4,
      "merged_total_observations": 5,
      "incremental_observations_count": 2
  }
  ```
  *(D4 원칙상 finding이 생성되지 않으므로 `incremental_findings_count`가 아닌 `incremental_observations_count`(의견 수)로 명명합니다.)*

---

## 4. 통합 표 노출 (F3d)

### 4.1 F2 통합 표(`documents[].review_items`) 내 '참고 의견' 행 구성 및 검토 상태
- **행 종류**:
  - 인용 행(`kind == ReviewItemKind.CITATION`)에 연결되는 참고자료 지지는 기존 인용 행의 `reference_status` 및 `evidence_sources`로 자연스럽게 수용됩니다.
  - 인용에 귀속되지 않는 순수 사실관계/주장 대조 관찰의견은 `ReviewItemKind.REFERENCE_OBSERVATION` 행으로 생성합니다.
- **배지 및 심각도**:
  - 배지: `[참고 의견]`
  - 심각도: `Severity.INFO` 고정 (D4 원칙: 어떠한 경우에도 WARNING이나 CRITICAL로 승격되지 않음)
  - 속성: `advisory_only = True`
- **검토 상태 저장 위치 (F3 1단계 읽기 전용)**:
  - F2의 행별 검토 상태(`review_status`)는 `apps/api/db.py`의 `FindingRow` 단위로 저장됩니다.
  - finding이 없는 `ReviewItemKind.REFERENCE_OBSERVATION` 행은 연결된 `FindingRow`가 없으므로, **이번 F3 1단계에서는 순수 읽기 전용(Read-Only)**으로 운영하며 사용자 검토 상태 변경 대상에서 제외합니다 (D4 원칙 준수).
- **기존 행과의 연결**:
  - `claim_id` 및 `location`(페이지, 텍스트 구간)을 통해 서면의 원본 주장 위치와 연결합니다.

### 4.2 인용문 표시 및 기각 의견 건수 처리
- **인용문 병기**: 서면의 주장 인용문(`claim_text` / `claim_quote`)과 참고자료의 근거 인용문(`source_quote`, 문서명, 쪽 번호, Drive 링크)을 나란히 대비하여 표시합니다.
- **기각 의견(Rejected Observations)**:
  - 검증에 실패한 의견(환각 인용구, 스키마 불일치 등)은 본문을 노출하지 않고, 요약 카드에 기각 건수(`len(rejected_observations)`)만 표시합니다.

### 4.3 `claim_coverage` 노출 위치 및 형식
- **노출 위치**: 통합 검토 화면 상단 요약 카드 및 `engine_data.rag.claim_coverage`.
- **노출 문구**: `"참고자료 대조율: 대조 대상 {eligible_claims}건 중 {linked_claims}건 완료 ({coverage_pct}%)"` (화면 검증 정규식: `(?:\d+건\s*중\s*\d+건|\d+\s*/\s*\d+)`, 예: "7건 중 3건 대조 완료").
- **상한 초과 주장 처리 (T7 보호 시험 충족)**:
  - 문서당 상한(10개 주장)을 초과한 주장은 탈락시키지 않고 분모(`eligible_claims`)에 그대로 남깁니다.
  - 해당 주장은 `unreviewed` 목록에 `{"claim_id": c_id, "reason": "REASON_BUDGET_EXCEEDED"}` 사유와 함께 기록되어 화면에 미대조 사유가 투명하게 공개됩니다 (T7 충족).

### 4.4 T1(단일 판정) · T2(손실 없음) · T4(AI 탭 배타성) 준수 근거
- **T1 (단일 판정 준수)**: 1개 인용에 대해 1개의 `ReviewItemKind.CITATION` 행만 생성되며, `official_status`와 `reference_status`가 한 행의 두 축으로 통합되어 중복 행이 발생하지 않습니다.
- **T2 (정보 손실 없음)**: 기존의 모든 `Finding`과 검토 항목은 `finding_ids`를 통해 100% 보존되며 누락되지 않습니다.
- **T4 (AI 탭 배타성 유지)**: 모든 참고자료 관찰의견은 오직 '검토 항목' 탭에만 배정되며, AI 진단·보안 탭으로 절대 혼입되지 않습니다.

---

## 5. 전송 경로와 호출 수 (F3e)

### 5.1 라우터 및 전송 전 검사 경로 (우회 금지)
- 주장 단위 모델 호출은 다음의 표준 단일 경로를 엄격히 경유합니다:
  ```
  [주장 단위 요청 생성 (claim_text 최대 1000자, reference_sources 최대 5개)] 
       ↓
  [validate_claim_request_payload (fail-closed 화이트리스트 스키마 검증)] 
       ↓
  [PII 마스킹 (연락처·주민번호 마스킹)] 
       ↓
  [LLMRouter.run 호출] 
       ↓
  [router.py:367 내부: inspect_request (전송 전 전수 보안 검사 자동 실행)] 
       ↓
  [외부 LLM 공급자 전송 (최대 3회 재시도)]
  ```
- `inspect_request`는 별도로 수동 호출할 필요 없이, `LLMRouter.run` 내부(line 367)에서 외부 공급자 및 MASKED 정책일 때 자동으로 실행됩니다.
- 별도의 독립적인 HTTP 클라이언트나 우회 경로를 일절 신설하지 않습니다.

### 5.2 요청 본문 스키마 및 fail-closed 검사 함수 (19b 6.1 · TK-55 고정)
1. **fail-closed 검사 함수 정의**:
   - 위치: `packages/rag_engine/review.py` (또는 `packages/rag_engine/schemas.py`)
   - 함수 시그니처: `validate_claim_request_payload(payload: Dict[str, Any]) -> bool`
   - 실패 신호:
     - 허용되지 않은 키가 포함되어 있거나 길이 한도를 초과한 경우 `False`를 반환(또는 `ValueError("INVALID_CLAIM_REQUEST_SCHEMA")` 발생).
     - 검증 실패 시 해당 주장의 모델 전송을 즉시 차단(fail-closed)하고, `claim_coverage.unreviewed`에 `{"claim_id": c_id, "reason": "REASON_SCHEMA_VALIDATION_FAILED"}`를 기록.
2. **요청 본문(`LLMRequest.user`) 스키마 및 길이 한도**:
   - 최상위 키 4개 화이트리스트 고정:
     ```python
     ALLOWED_REQUEST_KEYS = {
         "system_instructions",  # 고정 시스템 지침
         "claim_id",             # 비식별 주장 식별자
         "claim_text",           # 마스킹된 주장 텍스트 (최대 1,000자)
         "reference_sources",    # 마스킹된 참고자료 발췌 목록 (최대 5개 항목, 총합 4,000자)
     }
     ```
   - **`reference_sources` 항목 스키마**:
     - 각 항목의 허용 키: `{"source_id", "text", "page"}`로 한정.
     - **`title` 제외 권고 반영**: 파일명에 개인 성명이 포함될 수 있으나 PII 마스킹은 연락처·주민등록번호에 한정되므로, 개인정보 유출을 방지하기 위해 `reference_sources` 항목에서 `title` 키를 완전히 배제합니다.
   - **인명 키 원천 배제**:
     - `PERSON_KEY = re.compile(r"name|party|client|suspect|victim|owner|author|user|email|이름|성명|당사자|피해자|의뢰인", re.IGNORECASE)`에 매칭되는 키를 본문 전체에서 원천 배제합니다.

### 5.2 개정(TK-63): 주장 선별 규칙 및 예산형 상한 (사용자 결정 (나)안)

기존 설계 5.2의 고정 10개 상한(`CLAIM_LIMIT_PER_DOCUMENT = 10`)은 문서 앞쪽의 형식적 문장이 상한을 소진하여 후반부의 중요 인용 주장이 누락되는 한계(TK-63)가 확인되어, 아래와 같이 **결정적 선별 규칙**과 **예산형 상한(개수·시간·비용)**으로 개정합니다.

1. **선별 규칙(결정적 우선순위)**:
   - 대상 주장(`DOCUMENT_META`·`ADVERSARIAL_INSTRUCTION` 제외)을 다음 5단계 순위로 정렬하며, 동일 순위 내에서는 원래 문서 순서를 유지(stable sort)합니다:
     - ① **인용 연결 주장**: `citation_ids`가 존재하는 주장 (최우선 대조)
     - ② **법률효과·요건 주장**: `type`이 `LEGAL_RULE`·`LEGAL_ARGUMENT`이거나 요건사실 값(`amount` 또는 `asserted_date`)이 존재하는 주장
     - ③ **사실 주장**: `type == "FACT"`인 주장 (공백 제외 15자 이상)
     - ④ **그 밖의 주장**: `OPINION` 등 일반 주장 (공백 제외 15자 이상)
     - ⑤ **형식 문장**: 공백 제외 길이가 15자 미만인 주장(예: '다 음' 등). 단, ①·②에 해당하는 경우 ⑤로 강등하지 않습니다.
   - 규칙 판 식별자: `"TK63_CITATION_LEGAL_FACT_LENGTH_V1"`
   - 순위 판정에는 기존 주장의 메타데이터 필드만을 사용하며, 특정 서면이나 개별 규정명에 특화된 하드코딩 규칙을 일절 배제합니다.

2. **예산형 상한(설정값 기반 제어)**:
   - 고정 상수 `CLAIM_LIMIT_PER_DOCUMENT`를 폐지하고, `Settings` 객체 및 환경변수로 제어되는 동적 예산 상한을 도입합니다:
     - `rag_claim_max_per_document` (`LV_RAG_CLAIM_MAX_PER_DOCUMENT`): 기본값 30 (허용범위 1~100), 문서당 대조 주장 수의 절대 상한
     - `rag_claim_budget_seconds` (`LV_RAG_CLAIM_BUDGET_SECONDS`): 기본값 240, 주장 단위 단계의 경과 시간 예산 (초)
     - `rag_claim_budget_usd` (`LV_RAG_CLAIM_BUDGET_USD`): 기본값 1.00, 주장 단위 단계의 외부 모델 누적 비용 예산 ($) (0이면 비용 한도 비활성화)
   - **판정 시점**: 진행 중인 호출을 강제 중단하지 않고, **다음 주장을 공급자로 전송하기 직전에** 개수·시간·비용 한도 초과 여부를 사전 검사합니다.
   - **예산 초과 처리**: 예산 제한으로 대조되지 못한 주장은 분모(`eligible_claims`)에 온전히 보존되며, 사유를 `"REASON_BUDGET_EXCEEDED"`로 기록하여 T7 불변식(`eligible_claims == linked_claims + len(unreviewed)`)을 엄격히 충족합니다.
   - 주장당 최대 3회 공급자 요청(`MODEL_CALLS_PER_CLAIM = 3`), 최대 4,000자 발췌(`EXCERPT_CHARS = 4000`), 스키마 검증(`validate_claim_request_payload`)은 그대로 유지합니다.

3. **기록 (`claim_coverage`)**:
   - `claim_coverage`에 `selection_rule`과 `budget` 객체를 추가 기록합니다:
     - `budget.max_per_document`: 적용된 최대 주장 수 상한
     - `budget.budget_seconds`: 적용된 시간 예산
     - `budget.budget_usd`: 적용된 비용 예산
     - `budget.halt_reason`: 대조 중단 원인 (`"COUNT"`, `"TIME"`, `"COST"`, 또는 정상 완주 시 `None`)

### 5.3 공급자로 나간 요청 수 단위 엄격 상한 산식
- **상한 단위 정의**:
  - 19b 5.2에 따라 상한의 기준 단위는 **'공급자로 나간 요청 수'** (일시 장애 재시도 및 대체 포함 합산)입니다.
- **주장당 상한 (최대 3회) 보장 방식**:
  - `LLMRouter.run`은 일시 과부하(503, 529, 429) 시 내부 `retry_delays`(`router.py:421`)에 의해 최대 3회(`attempt=0, 1, 2`)까지 공급자 호출을 보냅니다.
  - 따라서 주장 단위 대조에서는 **주장당 `LLMRouter.run`을 단 1회만 호출**하고, 대체 공급자를 위한 추가 호출(`exclude=failed` 재시도)을 일절 수행하지 않습니다.
  - 이를 통해 각 주장별로 공급자로 나간 요청 수가 정확히 **최대 3회 이하(`MODEL_CALLS_PER_CLAIM = 3`)**로 엄격히 통제됩니다 (T9 시험 완벽 충족).
- **문서당 상한 및 총량 산식**:
  - 대조 대상 주장 수: 최대 10개 주장 (`CLAIM_LIMIT_PER_DOCUMENT = 10`).
  - 주장 단위 공급자 요청 수: $10 \text{ 주장} \times \text{최대 } 3 \text{ 회} = \mathbf{30 \text{ 회}}$.
  - 문서 단위 배치 대조 공급자 요청 수: 최대 2개 배치 $\times$ (기본 1회 + 대체 1회) $\times$ 시도 3회 = 최대 12회.
  - **서면 1건당 공급자로 나간 전체 요청 수 엄격 상한**: $12 \text{ (배치)} + 30 \text{ (주장 단위)} = \mathbf{42 \text{ 회}}$.
- **상한 상수 위치 및 매니페스트 키**:
  - 상한 상수 정의 위치: `packages/common/config.py` (`CLAIM_LIMIT_PER_DOCUMENT = 10`, `MODEL_CALLS_PER_CLAIM = 3`, `SEARCH_CALLS_PER_CLAIM = 2`, `EXCERPT_CHARS = 4000`).
  - 매니페스트 기록 키: `run_manifest["rag_limits"]`에 `claim_limit_per_document`, `model_calls_per_claim`, `search_calls_per_claim`, `excerpt_chars_limit`를 명시적으로 기록합니다.

### 5.4 `LOCAL_ONLY` 및 QUICK 모드 외부 호출 0 분기 위치 (T9 보호 시험)
- **분기 위치**:
  - 함수 진입부에서 조기 반환하면 Drive 검색, `provision_quotes`, `drive_used` 플래그 설정이 누락되어 현행 동작이 퇴행하고 T9 통과 시험 `test_t9_quick_profile_sends_no_reference_excerpt`가 실패합니다.
  - 따라서 현행 분기 위치인 **`packages/rag_engine/review.py:146` (`provision_obs` 계산 직후)의 QUICK 분기**에서 조건만 확장합니다:
    ```python
    # packages/rag_engine/review.py:146
    if (
        context.profile == VerificationProfile.QUICK
        or context.external_ai_policy == ExternalAIPolicy.LOCAL_ONLY
        or not router.has_available_provider(policy=context.external_ai_policy)
    ):
        review.update(status="RETRIEVED_ONLY", reason="MODEL_NOT_AVAILABLE_OR_QUICK_PROFILE")
        if provision_obs:
            from .contract_facts import link_observations
            masked_claims = [{**c, "text": mask(c.get("text", ""))} for c in getattr(result, "claims", [])]
            review.update(observations=provision_obs, source_quotes_validated=True,
                          issues=link_observations(provision_obs, sources, masked_claims))
        return review
    ```
- **주장 단위 루프의 배치**:
  - 외부 모델 호출을 수행하는 주장 단위 대조 루프는 위 분기보다 뒤쪽에 배치 루프와 함께 위치합니다.
  - 이를 통해 `LOCAL_ONLY` 환경에서는 공급자로 나간 요청 수가 정확히 0건(`sent == []`)으로 보장되고, `QUICK` 프로필에서는 참고자료 발췌를 실은 외부 호출이 0건으로 보장됩니다 (T9 보호 시험 완벽 통과).

---

## 6. 영향 범위

### 6.1 고정 시험·probe·회귀 게이트 점수 불변 근거
1. **오프라인 환경 내 `review_document` 미호출 구조**:
   - 오프라인 CI 및 로컬 환경에서 수행되는 고정 시험(개발/홀드아웃), probe 문서 점검, 12개 회귀 게이트는 Drive 폴더 설정(`rag_drive_folder_id`)이 비어 있는 상태로 실행됩니다.
   - `VerificationPipeline`은 `rag_drive_folder_id`가 설정되지 않은 경우 `review_document` 함수 자체를 아예 호출하지 않습니다 (코드 사실).
   - 따라서 F3의 신규 LLM 대조 및 주장 단위 경로는 오프라인 평가 파이프라인에서 실행조차 되지 않으므로 기존 점수에 어떠한 영향도 미치지 않습니다.
2. **규칙 체계 불변**:
   - 신규 `rule_id` 및 신규 `FindingType`을 1건도 추가하지 않으므로, 기존 탐지 엔진 점수와 심각도 계산식에 영향도가 0입니다.
   - 고정 시험 점수(dev 81.7 / holdout 79.2 / 오탐 0)는 100% 동일하게 유지됩니다.

### 6.2 검증 계획
- 구현 커밋 전후로 `python scripts/scorecard.py`를 실행하여 점수 불변을 입증합니다.
- `tests/acceptance/test_f3_protected.py`의 오프라인 하네스 시험(T6~T9, 요청 본문 스키마)을 통해 신규 경로의 동작을 독립적으로 검증합니다.

---

## 7. 다른 분야 동작 (T8 보호 시험)

### 7.1 사건·분야 낱말 하드코딩 일체 배제
- 특정 소송 사건이나 법률 도메인(예: "산업안전보건법", "임대차보호법", "국가배상" 등)을 전제하는 키워드 화이트리스트나 특화 분기를 코드에 일절 두지 않습니다.
- 질의어 생성은 형태소 기반 2자 이상 한글 단어 추출(`salient_words`)로 자동 일반화되며, 대조는 유연 텍스트 비교(`_contains_flexible`) 및 시스템 프롬프트의 범용 대조 지침에 따라 실행됩니다.

### 7.2 평가 측 합성 자료 2세트 호환 보장
- 평가 측이 `test_f3_protected.py`에 구축한 분야 A(산업안전·손해배상, `2019다246795`) 및 분야 B(주택임대차·보증금, `2020다218925`)의 상이한 합성 참고자료 세트에서:
  - 완전히 동일한 절차(`review_document` → 주장 추출 → 검색 → 대조 → 병합)가 수행됩니다.
  - 완전히 동일한 결과 구조(`official_status=OFFICIAL_NOT_FOUND`, `reference_status=SUPPORTED`, `claim_coverage` 산출)가 생성되어 T8 시험을 완벽히 통과할 수 있도록 설계되었습니다.
