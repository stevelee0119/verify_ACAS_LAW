# F3 1단계 설계 보충 메모 (개정 1) — 참고자료(RAG) 부합성 점검 강화

- **작성**: 구현 에이전트 (Antigravity)
- **일자**: 2026-10-07
- **대상 지시서**: [docs/handoff/PROMPT_FOR_F3.md](../PROMPT_FOR_F3.md)
- **기준 커밋**: `Steve_ACASiaLAW` 최신 (`7110273830362d46c1b4df9fa049c39a262f7f7e`, PR #31 병합 완료)
- **작업 브랜치**: `antigravity/f3-reference-review` (base: `Steve_ACASiaLAW`)
- **제출 성격**: **1단계: 설계 보충 전용 (평가 측 판정 3398943 필수 보완 8건 및 사실 정정 5건 반영, 제품 코드·시험 수정 0)**

---

## 0. 기확정 사항 전제 (지시서 2절 재설계 금지 원칙 준수)

본 설계서는 지시서 2절에 명시된 기확정 사항을 엄격한 불변 전제로 삼으며, 이를 다시 설계하지 않습니다:

1. **D4 출력 원칙**: 참고자료 대조 의견은 '참고 의견'(`advisory_only=True`)이며, 심각도·finding 승격을 일절 두지 않고 검토 상태만 기록합니다. TK-09 후보 승격은 계속 차단 상태를 유지합니다.
2. **D6 전송 원칙**: 기존 라우터(`LLMRouter`), `external_ai_policy`, 전송 전 검사([`packages/llm_router/router.py:367`](file:///C:/Users/mrlee/.gemini/antigravity/worktrees/verify_ACAS_LAW/verify_acas_law_tasks/packages/llm_router/router.py#L367) 내부의 `inspect_request`)를 그대로 사용합니다. 참고자료 전용 외부 전송 설정이나 신규 우회 경로를 만들지 않으며, `LOCAL_ONLY` 및 `QUICK` 모드에서는 외부 모델을 일체 부르지 않고 규칙 대조(`provision_quotes`, 동일성 대조)와 검색 메타데이터만 산출합니다.
3. **19b 5절 조건부 승인분**: 기존 [`packages/rag_engine/review.py`](file:///C:/Users/mrlee/.gemini/antigravity/worktrees/verify_ACAS_LAW/verify_acas_law_tasks/packages/rag_engine/review.py)(`grounded_observations`·`claim_coverage`)를 확장합니다. 대조 기준은 모델에 전송된 마스킹 텍스트(`_contains_flexible`)이며, Drive 본문 검색 질의는 `relevance.py`의 `salient_words` 기반 2자 이상 한글 단어로만 구성하고 숫자열을 배제합니다. 상한(공급자 요청 수 기준 주장당 3회, 문서당 주장 10개, 발췌 묶음 4,000자)을 엄수하며, 상한 초과 주장은 `claim_coverage` 분모에 유지하고 `REASON_BUDGET_EXCEEDED` 사유를 부여합니다.
4. **19b 6절 요청 본문 스키마(TK-55)**: 허용 키 4개 화이트리스트(`system_instructions`, `claim_id`, `claim_text`, `reference_sources`)를 고정하고 fail-closed로 전송을 차단하며, 인명/당사자 키를 일체 두지 않습니다.
5. **근거 사다리 2축 분리**: `ReviewItem.official_status`(`OfficialConfirmationStatus`)와 `ReviewItem.reference_status`(`ReferenceSupportStatus`: SUPPORTED, CONTRADICTED, NOT_MENTIONED, NOT_CHECKED)는 상호 독립된 별개 축으로 운영됩니다.
6. **규칙·지표 불변 원칙**: 신규 `rule_id` 0건, 신규 `FindingType` 0건, 고정 시험(dev 81.7 / holdout 79.2 / 오탐 0) 및 probe 점수 변화 0을 보장합니다.

---

## 1. `reference_status` 채우기 (F3a · F3c)

### 1.1 대조 결과가 `ReviewItem.reference_status`로 들어가는 유입 경로 및 우선순위
1. **대조 수행 모듈 ([`packages/rag_engine/review.py`](file:///C:/Users/mrlee/.gemini/antigravity/worktrees/verify_ACAS_LAW/verify_acas_law_tasks/packages/rag_engine/review.py))**:
   - `review_document` 함수 실행 시, 사용자 참고자료 대조를 통해 다음 결과를 `result.engine_data["rag"]`에 적재합니다:
     - `observations`: 검증 통과된 관찰의견 목록 (`[{"claim_quote": ..., "source_id": ..., "source_quote": ..., "relationship": "SUPPORTS"|"CONTRADICTS"|"CONTEXT"|"INSUFFICIENT", "explanation": ...}]`)
     - `reference_matches`: 인용 대상(사건번호 또는 법령명+조문)과 본문을 읽은 참고자료(`summary["sources"]`) 본문 간의 **인용 동일성 대조(U1)** 결과 맵 (`Dict[str, Dict[str, Any]]`, 키는 `citation_id`):
       ```python
       # reference_matches[cid] 구조
       {
           "status": ReferenceSupportStatus.SUPPORTED,
           "source_id": "R1",
           "file_id": source.get("file_id"),
           "source_title": source.get("title"),
           "matched_authority": cit.canonical_case_number or cit.raw_text
       }
       ```
     - `issues`: [`packages/rag_engine/contract_facts.py:119`](file:///C:/Users/mrlee/.gemini/antigravity/worktrees/verify_ACAS_LAW/verify_acas_law_tasks/packages/rag_engine/contract_facts.py#L119)의 `link_observations(observations, sources, claims)`를 통해 의견과 주장(`claim_ids`), 출처(`file_id`, `span`)를 연결한 결과.
2. **통합 객체 생성 모듈 ([`packages/verification_engine/review_items.py`](file:///C:/Users/mrlee/.gemini/antigravity/worktrees/verify_ACAS_LAW/verify_acas_law_tasks/packages/verification_engine/review_items.py))**:
   - 실제 함수명은 **`build_document_review_items`**입니다.
   - 인용 행(`ReviewItemKind.CITATION`) 생성 루프에서 `reference_status`는 다음 원칙과 우선순위로 결정됩니다:
     - **원칙 1: 인용 행의 `SUPPORTED`는 인용 동일성 대조(U1)에서만 온다**:
       모델 의견의 `SUPPORTS`는 판례·조문의 실존을 뜻하지 않으므로 인용 행을 SUPPORTED로 올리지 않습니다. (모델 의견은 별도의 주장 행 또는 참고 의견 행에만 배치).
     - **원칙 2: `CONTRADICTED` 우선순위 보장 (모순 은폐 방지)**:
       동일성 대조로 판례/조문이 존재하더라도, 해당 인용에 연결된(`link_observations`의 `claim_ids` 또는 인용 매핑) 근거 확인된 `CONTRADICTS` 관찰의견이 존재할 경우 모순이 가려지지 않도록 `CONTRADICTED`를 최우선 적용합니다:
       $$\mathbf{CONTRADICTED > SUPPORTED > NOT\_MENTIONED > NOT\_CHECKED}$$
     - **원칙 3: `CONTEXT` 보존**:
       모델의 `CONTEXT` 의견을 `NOT_MENTIONED`로 임의 변환하지 않습니다. `NOT_MENTIONED`는 "대조한 본문에 해당 인용 언급이 없음(동일성 대조 결과 미발견)"일 때만 사용합니다.
     - **의견-인용 연결 방식**:
       단순 텍스트 유사도가 아니라, 기존 `link_observations`(`contract_facts.py:119`)에서 생성된 `claim_ids`와 인용의 `citation_id` 매핑 관계를 기준으로 결정적으로 연결합니다.

### 1.2 공식 미발견 인용의 참고자료 대조 처리 (T6 보호 시험 원칙)
- **독립 축 보존 (No Overwrite)**:
  공식 DB 조회 결과 `official_status == OfficialConfirmationStatus.OFFICIAL_NOT_FOUND`인 경우:
  - 참고자료 본문에 동일 인용이 존재하더라도 `official_status`는 절대로 `OFFICIAL_CONFIRMED`로 변경되지 않고 **`OFFICIAL_NOT_FOUND`를 100% 유지**합니다.
  - 기존의 부존재/미확인 관련 `Finding` 목록, `severity`(심각도), `verdict_label`도 일체 승격되거나 변경되지 않습니다 (D4 원칙 준수).
- **참고자료 축만 지지 반영**:
  - `item.reference_status = ReferenceSupportStatus.SUPPORTED`
  - `item.evidence_sources`에 **Drive 링크(`file_id`가 포함된 URL)**를 반드시 추가합니다 (보호 시험 T6 검증 충족):
    ```python
    drive_url = f"https://drive.google.com/file/d/{file_id}/view"
    item.evidence_sources.append(drive_url)
    ```
  - 이를 통해 `(row["official_status"], row["reference_status"]) == ("OFFICIAL_NOT_FOUND", "SUPPORTED")` 상태가 형성됩니다.

### 1.3 동일성 대조 규칙 (5차 U1 · TK-29 재사용 및 세부 기준)
`tests/acceptance/test_reference_match_guard.py`의 5차 U1 가드를 재사용하며 다음 구체적 대조 기준을 적용합니다:
1. **사건번호 경계 일치 (Word Boundary Match)**:
   - 사건번호는 정규화된 형태(`canonical_case_number`, 예: `2022다29841`)에 대해 숫자/문자 경계 일치(`(?<!\d)` 및 `(?!\d)`)를 엄격히 적용합니다:
     ```python
     re.search(rf"(?<!\d){re.escape(case_no)}(?!\d)", text)
     ```
   - 앞뒤로 숫자가 붙은 다른 사건번호(예: `12022다298410`)나 오인식 텍스트와의 부분 일치를 완전히 배제합니다.
2. **법령명 + 조 근접 기준 (Proximity Criterion)**:
   - 정규화된 법령명(`_normalize_reference_name`)과 조문 번호(예: `제10조`)는 **동일 문장 또는 동일 단락 내 $\pm 100$자 이내**에 공존해야 동일 인용으로 인정합니다.
   - 법령명만 따로 있고 수백 자 떨어진 다른 조항 번호와 결합되는 오인식을 차단합니다.
3. **마스킹 본문 대조 및 보존 근거**:
   - 대조 대상 텍스트는 모델에 전송되는 것과 동일한 **마스킹 본문**입니다.
   - `packages/document_engine/pii.py`의 마스킹 대상은 전화번호, 주민등록번호, 계좌번호 등 개인식별정보이며, 법원 사건번호(`\d{4}[가-힣]{1,3}\d+`) 및 법령 조문(`제\d+조`)은 마스킹 대상 정규식에 포함되지 않고 보존됨을 코드에서 확인하였습니다.
4. **규칙 대조 실행 환경 (LOCAL_ONLY · QUICK 지원)**:
   - 동일성 대조는 LLM을 사용하지 않는 순수 규칙 대조이므로, **`LOCAL_ONLY` 및 `QUICK` 프로필에서도 동일하게 실행되어 결과를 산출**합니다 (D6 준수).
5. **읽기 성공 본문 한정**:
   - `ReferenceLibrary`의 `summary["sources"]`에 등록된, **실제로 본문을 읽은 문서(READ/OK)**의 본문만을 대조 대상으로 합니다 (inventory 미독/실패 파일 배제). 제목 부분 일치로 SUPPORTED 승격하지 않습니다.

---

## 2. 위계 표시 (F3a)

### 2.1 모든 Drive 출처에 "참고자료(공식 법령·판례 아님)" 고정 표기
- 모든 Drive 기반 대조 결과 및 출처 표시에 고정 한계 안내를 결합합니다:
  - `ReviewItem.evidence_sources`: `f"https://drive.google.com/file/d/{file_id}/view (참고자료: {source_title})"` 형태로 Drive 링크와 함께 표준화합니다.
  - UI 렌더링: 참고자료 뱃지 및 상세 팝오버에 `[참고자료 (공식 법령·판례 아님)]` 고정 문구를 필수 노출합니다.
  - (정정: `ReviewItem.authority_limitation`은 현행 스키마에 부존재하는 필드이므로 신규 필드를 추가하지 않고, `verdict_label` 및 `evidence_sources`와 화면 컴포넌트 안내로 일원화합니다.)

### 2.2 자료 이름·폴더 낱말로 법령·지침 추측 분류 금지
- 파일명이나 폴더 경로에 `"법률"`, `"대통령령"`, `"훈령"`, `"예규"`, `"지침"`, `"규정"` 등의 단어가 포함되어 있더라도 공적 규범으로 추측 분류하지 않습니다 (낱말 사전/휴리스틱 매핑 일체 금지).
- 모든 Drive 문서는 일관되게 '사적 참고자료' 위계로 단일 처리됩니다.

---

## 3. 주장 단위 검색 및 대조 (F3b)

### 3.1 현행 문서 단위 경로 유지 및 주장 단위 단계 추가
1. **문서 단위 경로 유지**:
   - 현행 [`packages/rag_engine/review.py`](file:///C:/Users/mrlee/.gemini/antigravity/worktrees/verify_ACAS_LAW/verify_acas_law_tasks/packages/rag_engine/review.py)의 `batches` 기반 배치 대조는 제거하지 않고 100% 보존합니다.
2. **주장 단위 검색 결과의 처리 방식**:
   - `drive.search_fulltext`는 파일 ID 목록(`list[str]`)만 반환합니다([`packages/rag_engine/drive.py:215`](file:///C:/Users/mrlee/.gemini/antigravity/worktrees/verify_ACAS_LAW/verify_acas_law_tasks/packages/rag_engine/drive.py#L215)).
   - **선택 방안 (a) 색인 내 탐색**:
     U1 원칙(미독 파일 대조 배제)을 완벽히 지키기 위해, `search_fulltext` 결과 중 **이미 다운로드·추출되어 라이브러리에 색인된 문서([`ReferenceLibrary.summary["sources"]`](file:///C:/Users/mrlee/.gemini/antigravity/worktrees/verify_ACAS_LAW/verify_acas_law_tasks/packages/rag_engine/library.py)) 안에서만 발췌 및 대조**를 수행합니다. 색인되지 않은 미독 파일은 대조하지 않습니다.
   - **검색 거절(401·403·429) 시 즉시 중단**:
     Drive API 검색 요청 중 401, 403, 429 오류가 발생하면 기존 게이트처럼 반복 재시도하지 않고 즉시 검색 루프를 중단합니다([`packages/rag_engine/library.py:220`](file:///C:/Users/mrlee/.gemini/antigravity/worktrees/verify_ACAS_LAW/verify_acas_law_tasks/packages/rag_engine/library.py#L220) 준용). `review["reason"] = "DRIVE_SEARCH_REJECTED"`를 기록하고 안전하게 종료합니다.
3. **주장 단위 모델 대조 실행**:
   - 적격 주장(claims, `DOCUMENT_META` 및 `ADVERSARIAL_INSTRUCTION` 제외)을 순회하며 마스킹된 주장과 색인 발췌문(최대 4,000자)을 대상으로 주장 단위 대조를 수행합니다.

### 3.2 두 경로의 결과 합치는 규칙 (결정적 병합 및 중복 제거)
- **결정적 중복 제거 규칙 (Deterministic Merge)**:
  - 문서 단위 배치 대조의 `observations`와 주장 단위 대조의 `observations`를 합칠 때, `(obs["claim_quote"], obs["source_quote"])` 튜플을 고유 키로 삼습니다.
  - 동일한 `(claim_quote, source_quote)` 쌍이 중복될 경우, **주장 단위 대조 의견(`claim_level`)을 항상 우선 채택**합니다.
  - 동일 레벨 내에서 중복이 발생할 경우 `(source_id, -len(explanation), index)` 기준의 결정적 정렬 키로 1건만을 선택하여 임의성이나 비결정성을 배제합니다.
- **규칙 대조 우선권**:
  - 규칙 기반 조항 인용 대조(`provision_quotes`) 및 인용 동일성 대조(`reference_matches`) 결과는 모델 의견보다 항상 우선하여 보존됩니다.

### 3.3 전후 비교(A/B Comparison) 측정 방법
- 주장 단위 도입의 추가 효과를 정량 검증하기 위해, `engine_data["rag"]["comparison_metrics"]`에 다음 메트릭을 기록합니다:
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
  *(정정: D4 원칙상 새로운 finding이 추가되지 않으므로, 지표명을 `incremental_findings_count`가 아닌 `incremental_observations_count`로 통일합니다).*

---

## 4. 통합 표 노출 (F3d)

### 4.1 F2 통합 표([`documents[].review_items`](file:///C:/Users/mrlee/.gemini/antigravity/worktrees/verify_ACAS_LAW/verify_acas_law_tasks/packages/common/schemas.py)) 내 '참고 의견' 행 구성 및 검토 상태 저장
- **행 종류**:
  - 인용 행(`kind == ReviewItemKind.CITATION`): 인용 자체에 대한 지지/모순은 인용 행의 `reference_status` 및 `evidence_sources`로 수용.
  - 순수 사실관계/주장 대조 관찰의견: `ReviewItemKind.REFERENCE_OBSERVATION` 행으로 생성.
- **배지 및 심각도**:
  - 배지: `[참고 의견]`, `advisory_only = True`
  - 심각도: `Severity.INFO` 고정 (D4 원칙: 승격 없음)
- **참고 의견 행의 검토 상태 저장 위치 (읽기 전용)**:
  - F2의 행별 검토 상태 저장은 finding 단위([`apps/api/db.py`](file:///C:/Users/mrlee/.gemini/antigravity/worktrees/verify_ACAS_LAW/verify_acas_law_tasks/apps/api/db.py) `FindingRow.review_status`)로 수행됩니다.
  - finding이 연결되지 않은 `REFERENCE_OBSERVATION` 행은 **이번 단계(F3)에서 '읽기 전용(저장 불가 정보)'으로 둡니다** (F2에서 finding 없는 인용 행을 저장 불가 정보로 둔 설계와 동일). 체크박스/수정 컨트롤을 비활성화하고 정보 열람 전용으로 렌더링합니다.
- **TK-09 후보 승격 차단 (D4 권고 반영)**:
  - 주장 단위 의견에는 `advisory_only=True` 및 `source_id`를 명시하여, TK-09 후보 승격 경로(`candidate_promotion_enabled`)에 진입하지 않도록 원천 차단합니다.

### 4.2 인용문 표시 및 기각 의견 건수 처리
- **인용문 병기**: 서면의 주장 인용문(`claim_text` / `claim_quote`)과 참고자료의 근거 인용문(`source_quote`, Drive URL 링크)을 나란히 대비하여 표시합니다.
- **기각 의견(Rejected Observations)**:
  - 검증에 실패한 의견(환각 인용구, 스키마 불일치 등)은 본문을 노출하지 않고 요약 카드에 기각 건수(`len(rejected_observations)`)만 표시합니다.

### 4.3 `claim_coverage` 노출 위치 및 형식
- **노출 위치**: 통합 검토 화면 상단 요약 카드 및 `engine_data.rag.claim_coverage`.
- **노출 문구**: 데이터 값을 그대로 반영하여 `"참고자료 대조율: 대조 대상 {eligible_claims}건 중 {linked_claims}건 완료"` (예: "7건 중 3건 대조 완료", T7 정규식 `COVERAGE_SHOWN` 일치).
- **상한 초과 주장 처리**:
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
  [주장 단위 요청 생성] 
       ↓
  [validate_structured_claim_request (화이트리스트 스키마 검사, fail-closed)] 
       ↓
  [LLMRequest 생성 (PII 마스킹 본문)] 
       ↓
  [LLMRouter.run(LLMRole.PRIMARY_REASONER, ...)] 
       ├── 내부: inspect_request (router.py:367 전송 전 전수 보안 검사)
       └── 내부: 공급자 호출 루프 (router.py:421, 재시도 delays)
       ↓
  [외부 LLM 공급자]
  ```
  *(사실 정정: `inspect_request`는 별도로 호출하는 것이 아니라 `LLMRouter.run` 내부([`packages/llm_router/router.py:367`](file:///C:/Users/mrlee/.gemini/antigravity/worktrees/verify_ACAS_LAW/verify_acas_law_tasks/packages/llm_router/router.py#L367))에서 외부 공급자 및 MASKED 모드 시 자동으로 실행됩니다).*

### 5.2 fail-closed 검사 함수 및 요청 항목 스키마 (19b 6.1 · TK-55)
1. **검사 함수 명세**:
   - **모듈 위치**: [`packages/rag_engine/review.py`](file:///C:/Users/mrlee/.gemini/antigravity/worktrees/verify_ACAS_LAW/verify_acas_law_tasks/packages/rag_engine/review.py)
   - **함수명**: `validate_structured_claim_request(body: dict) -> bool`
   - **실패 신호 및 차단 동작**:
     - 스키마 허용 키 목록 밖의 키가 포함되거나 길이 한도를 초과할 경우 `jsonschema.ValidationError`를 발생시키거나 `False`를 반환합니다.
     - 차단된 주장은 LLM 전송을 즉시 중단(fail-closed)하고, `unreviewed` 목록에 `{"claim_id": c_id, "reason": "SCHEMA_VALIDATION_FAILED"}` 사유를 기록합니다. 평가 측은 이 함수명을 대상으로 단위 시험을 추가합니다.
2. **요청 본문 스키마 및 길이 한도**:
   - 최상위 허용 키 (4개 화이트리스트 고정):
     ```python
     ALLOWED_REQUEST_KEYS = {"system_instructions", "claim_id", "claim_text", "reference_sources"}
     ```
   - **길이 한도**:
     - `claim_text`: 최대 1,000자
     - `reference_sources`: 최대 5개 항목
   - **`reference_sources` 항목 키 목록 (권고 반영: `title` 제외)**:
     - 허용 항목 키: `{"source_id", "text", "page"}`
     - 파일명에 사람 이름이 포함될 위험(마스킹 보장 범위는 연락처·주민등록번호 중심)을 원천 차단하기 위해 평가 측 권고대로 `title`은 제외합니다.
     - 항목당 `text` 길이: 최대 800자 (5개 항목 합산 4,000자 이내 바운딩).
   - **인명 키 원천 배제**: `name`, `party`, `client`, `suspect`, `victim`, `owner`, `author`, `user`, `email` 등 인명이나 당사자를 가리키는 키는 스키마에 일체 두지 않습니다.

### 5.3 호출 수의 단위 및 산식 (공급자 요청 수 기준)
- **단위 정의**: 상한의 단위는 `router.run` 호출 수가 아니라 **'공급자로 나간 실제 요청 수(HTTP Request to Provider)'**입니다.
- **주장당 3회 보장 방식**:
  - `LLMRouter.run` 1회 실행 시 내부 일시 장애 재시도 루프([`router.py:421`](file:///C:/Users/mrlee/.gemini/antigravity/worktrees/verify_ACAS_LAW/verify_acas_law_tasks/packages/llm_router/router.py#L421), `retry_delays=(2.0, 6.0)`)에 의해 공급자 호출이 최대 3회 나갈 수 있습니다.
  - 따라서 주장 단위 대조에서는 **단일 `router.run` 1회만 호출**하며, 실패 시 대체 공급자(`exclude`) 재시도를 수행하지 않습니다. 이를 통해 **주장당 공급자 요청 수가 정확히 최대 3회 이하로 엄격 보장**됩니다 (평가 측 T9 시험의 `claim_id`별 공급자 요청 수 $\le 3$ 통과).
- **문서 단위 배치 호출 수**:
  - 배치 최대 2개 $\times$ (기본 1회 + 대체 재시도 1회) $\times$ 공급자 시도 최대 3회 = **최대 12회**.
- **서면 1건당 전체 외부 호출 수 산식 (공급자 요청 수 단위)**:
  $$\text{문서 단위 배치 (최대 12회)} + \text{주장 단위 (10개 주장 } \times \text{최대 3회 = 30회)} = \mathbf{\text{최대 42회}}$$

### 5.4 `LOCAL_ONLY` 및 QUICK 모드 외부 호출 0 분기 위치 (T9 보호 시험)
- **분기 위치 (현행 위치 유지 및 조건 확장)**:
  진입부가 아니라, [`packages/rag_engine/review.py:146`](file:///C:/Users/mrlee/.gemini/antigravity/worktrees/verify_ACAS_LAW/verify_acas_law_tasks/packages/rag_engine/review.py#L146)의 **`provision_obs` 및 인용 동일성 대조(`reference_matches`) 계산 완료 직후**에서 조건을 확장합니다:
  ```python
  # packages/rag_engine/review.py:146 부근
  if (
      context.profile == VerificationProfile.QUICK
      or context.external_ai_policy == ExternalAIPolicy.LOCAL_ONLY
      or not router.has_available_provider(policy=context.external_ai_policy)
  ):
      review.update(status="RETRIEVED_ONLY", reason="MODEL_NOT_AVAILABLE_OR_QUICK_PROFILE")
      # 규칙 대조(provision_obs) 및 동일성 대조(reference_matches) 결과는 온전히 보존
      if provision_obs or reference_matches:
          masked_claims = [{**c, "text": mask(c.get("text", ""))} for c in getattr(result, "claims", [])]
          review.update(observations=provision_obs, source_quotes_validated=True,
                        issues=link_observations(provision_obs, sources, masked_claims))
      return review
  ```
- **효과**:
  - `drive_used`, `provision_obs`, `reference_matches`가 그대로 유지되어 `test_t9_quick_profile_sends_no_reference_excerpt`가 통과합니다.
  - 신규 주장 단위 LLM 호출 루프는 이 분기 **뒤**에 배치되므로, `LOCAL_ONLY` 및 `QUICK` 환경에서 외부 공급자 호출이 정확히 0건(`sent == []`)으로 차단됩니다 (T9 충족).

---

## 6. 영향 범위

### 6.1 고정 시험·probe·회귀 게이트 점수 불변 근거
1. **오프라인 CI에서 `review_document` 미호출**:
   - 오프라인 CI 환경에서는 Drive 폴더 환경변수(`LV_RAG_DRIVE_FOLDER_ID`)가 설정되지 않아, [`packages/verification_engine/pipeline.py:382`](file:///C:/Users/mrlee/.gemini/antigravity/worktrees/verify_ACAS_LAW/verify_acas_law_tasks/packages/verification_engine/pipeline.py#L382)의 `if self.settings.rag_drive_folder_id:` 분기에 진입하지 않습니다.
   - 따라서 오프라인 CI에서는 **`review_document` 함수 자체가 아예 호출되지 않습니다**.
2. **규칙 체계 불변**:
   - 신규 `rule_id` 및 신규 `FindingType`을 1건도 추가하지 않으므로, 기존 탐지 엔진 점수와 심각도 계산식에 영향도가 0입니다.
   - 고정 시험 점수(dev 81.7 / holdout 79.2 / 오탐 0)는 100% 동일하게 유지됩니다.

### 6.2 상한 상수 위치 및 매니페스트 기록
- **상수 선언 위치**: [`packages/common/config.py`](file:///C:/Users/mrlee/.gemini/antigravity/worktrees/verify_ACAS_LAW/verify_acas_law_tasks/packages/common/config.py)
  ```python
  CLAIM_LIMIT_PER_DOCUMENT: int = 10
  MODEL_CALLS_PER_CLAIM: int = 3
  EXCERPT_CHARS_LIMIT: int = 4000
  ```
- **매니페스트 키**:
  `manifest.add_metadata("rag_limits", {"claim_limit": 10, "calls_per_claim": 3, "excerpt_chars": 4000})` 형태로 기록합니다.

---

## 7. 다른 분야 동작 (T8 보호 시험)

### 7.1 사건·분야 낱말 하드코딩 일체 배제
- 특정 소송 사건이나 법률 도메인(예: "산업안전보건법", "임대차보호법", "국가배상" 등)을 전제하는 키워드 화이트리스트나 특화 분기를 코드에 일절 두지 않습니다.
- 질의어 생성은 형태소 기반 2자 이상 한글 단어 추출(`salient_words`)로 자동 일반화되며, 대조는 유연 텍스트 비교(`_contains_flexible`) 및 시스템 프롬프트의 범용 대조 지침에 따라 실행됩니다.

### 7.2 평가 측 합성 자료 2세트 호환 보장
- 평가 측이 `test_f3_protected.py`에 구축한 분야 A(산업안전·손해배상) 및 분야 B(주택임대차·보증금)의 상이한 합성 참고자료 세트에서:
  - 완전히 동일한 절차(`review_document` → 주장 추출 → 검색 → 대조 → 병합)가 수행됩니다.
  - 완전히 동일한 결과 구조(`official_status=OFFICIAL_NOT_FOUND`, `reference_status=SUPPORTED`, `claim_coverage` 산출)가 생성되어 T8 시험을 완벽히 통과할 수 있도록 설계되었습니다.
