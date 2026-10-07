# F3 1단계 설계 보충 메모 — 참고자료(RAG) 부합성 점검 강화

- **작성**: 구현 에이전트 (Antigravity)
- **일자**: 2026-10-07
- **대상 지시서**: [docs/handoff/PROMPT_FOR_F3.md](../PROMPT_FOR_F3.md)
- **기준 커밋**: `Steve_ACASiaLAW` 최신 (`7110273830362d46c1b4df9fa049c39a262f7f7e`, PR #31 병합 완료)
- **작업 브랜치**: `antigravity/f3-reference-review` (base: `Steve_ACASiaLAW`)
- **제출 성격**: **1단계: 설계 보충 전용 (제품 코드·보호 시험 변경 0, 본 설계 문서 1건만 제출)**

---

## 0. 기확정 사항 전제 (지시서 2절 재설계 금지 원칙 준수)

본 설계서는 지시서 2절에 명시된 기확정 사항을 엄격한 불변 전제로 삼으며, 이를 다시 설계하지 않습니다:

1. **D4 출력 원칙**: 참고자료 대조 의견은 '참고 의견'(`advisory_only=True`)이며, 심각도·finding 승격을 일절 두지 않고 검토 상태만 기록합니다. TK-09 후보 승격은 계속 차단 상태를 유지합니다.
2. **D6 전송 원칙**: 기존 라우터(`LLMRouter`), `external_ai_policy`, 전송 전 검사(`packages/llm_router/privacy.py` `inspect_request`)를 그대로 사용합니다. 참고자료 전용 외부 전송 설정이나 신규 우회 경로를 만들지 않으며, `LOCAL_ONLY` 및 `QUICK` 모드에서는 외부 모델을 일체 부르지 않고 규칙 대조(`provision_quotes`)와 검색 메타데이터만 산출합니다.
3. **19b 5절 조건부 승인분**: 기존 `packages/rag_engine/review.py`(`grounded_observations`·`claim_coverage`)를 확장합니다. 대조 기준은 모델에 전송된 마스킹 텍스트(`_contains_flexible`)이며, Drive 본문 검색(`drive.search_fulltext`) 질의는 `relevance.py`의 `salient_words` 기반 2자 이상 한글 단어로만 구성하고 숫자열을 배제합니다. 상한(주장당 검색 2회/모델 3회, 문서당 주장 10개, 발췌 묶음 4,000자)을 엄수하며, 상한 초과 주장은 `claim_coverage` 분모에 유지하고 `REASON_BUDGET_EXCEEDED` 사유를 부여합니다.
4. **19b 6절 요청 본문 스키마(TK-55)**: 허용 키 4개 화이트리스트(`system_instructions`, `claim_id`, `claim_text`, `reference_sources`)를 고정하고 fail-closed로 전송을 차단하며, 인명/당사자 키를 일체 두지 않습니다. 전송 전 전체 검사(`inspect_request`)를 필수로 거칩니다.
5. **근거 사다리 2축 분리**: `ReviewItem.official_status`(`OfficialConfirmationStatus`)와 `ReviewItem.reference_status`(`ReferenceSupportStatus`: SUPPORTED, CONTRADICTED, NOT_MENTIONED, NOT_CHECKED)는 상호 독립된 별개 축으로 운영됩니다.
6. **규칙·지표 불변 원칙**: 신규 `rule_id` 0건, 신규 `FindingType` 0건, 고정 시험(dev 81.7 / holdout 79.2 / 오탐 0) 및 probe 점수 변화 0을 보장합니다.

---

## 1. `reference_status` 채우기 (F3a · F3c)

### 1.1 대조 결과가 `ReviewItem.reference_status`로 들어가는 유입 경로 (함수 및 키)
1. **대조 수행 모듈 (`packages/rag_engine/review.py`)**:
   - `review_document` 함수 실행 시, 사용자 참고자료 대조를 통해 다음 결과를 `result.engine_data["rag"]`에 적재합니다:
     - `observations`: 검증 통과된 관찰의견 목록 (`[{"claim_quote": ..., "source_id": ..., "source_quote": ..., "relationship": "SUPPORTS"|"CONTRADICTS"|"CONTEXT"|"INSUFFICIENT", "explanation": ...}]`)
     - `reference_matches`: 인용 대상(사건번호 또는 법령명+조문)과 본문을 읽은 참고자료(`summary["sources"]`) 본문 간의 동일 인용 매칭 맵 (`Dict[str, Dict[str, Any]]`, 키는 `citation_id`):
       ```python
       # reference_matches[cid] 구조 예시
       {
           "status": ReferenceSupportStatus.SUPPORTED,
           "source_id": "R1",
           "source_title": "[RAG참고자료] 취업규칙.pdf",
           "matched_authority": "2022다29841"
       }
       ```
2. **통합 객체 생성 모듈 (`packages/verification_engine/review_items.py`)**:
   - `build_review_items` 함수 4절(인용 행 생성 루프 `for cit in citations:`)에서 각 인용에 대해:
     - `rag_data = engine_data.get("rag", {})`로부터 `reference_matches` 및 `observations`를 참조합니다.
     - 기존의 고정 코드(`ref_status = ReferenceSupportStatus.NOT_CHECKED`)를 대체하여 다음 분기 규칙으로 `reference_status`를 결정합니다:
       1) 해당 `cid`에 대해 `reference_matches`에 `SUPPORTED` 매칭이 존재하는 경우:
          → `ref_status = ReferenceSupportStatus.SUPPORTED`
       2) `observations` 중 해당 인용의 주장 구절(`claim_text` 또는 `raw_text`)과 매핑되는 항목이 있는 경우:
          - `relationship == "SUPPORTS"` → `ReferenceSupportStatus.SUPPORTED`
          - `relationship == "CONTRADICTS"` → `ReferenceSupportStatus.CONTRADICTED`
          - `relationship`이 `"CONTEXT"` 또는 `"INSUFFICIENT"`인 경우 → `ReferenceSupportStatus.NOT_MENTIONED`
       3) 그 외 대조가 수행되지 않았거나 대조 대상이 아닌 경우:
          → `ref_status = ReferenceSupportStatus.NOT_CHECKED`

### 1.2 공식 미발견 인용의 참고자료 대조 처리 (T6 보호 시험 원칙)
- **독립 축 보존 (No Overwrite)**:
  공식 DB(대법원 종합법률정보, 국가법령정보) 조회 결과 해당 판례나 법령이 발견되지 않아 `official_status == OfficialConfirmationStatus.OFFICIAL_NOT_FOUND`로 판정된 경우, 참고자료 본문에 해당 인용이 존재하더라도:
  - `official_status`는 절대로 `OFFICIAL_CONFIRMED`로 변경되지 않고 **`OfficialConfirmationStatus.OFFICIAL_NOT_FOUND`를 100% 유지**합니다.
  - 기존의 부존재/미확인 관련 `Finding` 목록, `severity`(심각도), `verdict_label`도 일체 승격되거나 변경되지 않습니다 (D4 원칙 준수).
- **참고자료 축만 지지 반영**:
  - `item.reference_status = ReferenceSupportStatus.SUPPORTED`
  - `item.evidence_sources`에 `f"참고자료: {source_title}"` (또는 Drive 링크/문서명)만 추가합니다.
  - 이를 통해 `(row["official_status"], row["reference_status"]) == ("OFFICIAL_NOT_FOUND", "SUPPORTED")` 상태가 형성되며, 공식적 권위의 부존재 사실과 사적 참고자료의 지지 사실이 명확히 공존합니다.

### 1.3 인용 일치 규칙 (5차 U1 · TK-29 재사용)
`tests/acceptance/test_reference_match_guard.py`에 고정된 5차 U1(TK-29) 가드를 그대로 재사용합니다:
1. **읽기 성공 본문 한정**:
   - `ReferenceLibrary`의 `summary["sources"]`에 등록된, **실제로 본문을 읽은 문서(READ/OK)**의 본문만을 대조 대상으로 합니다.
   - `inventory` 목록에만 존재하는 미처리 문서, 읽기 실패 문서(HTTP 403, 파싱 에러 등)는 대조 대상에서 원천 배제합니다.
2. **동일 인용 기준**:
   - **사건번호 인용**: 정규화된 사건번호(`canonical_case_number`, 예: `2022다29841`)가 참고자료 본문에 정확히 등장해야 합니다.
   - **법령 인용**: 정규화된 법령명(`_normalize_reference_name`)과 해당 조·항·호가 참고자료 본문에서 정확히 일치해야 합니다.
3. **부분 일치 및 제목 일치 차단**:
   - 참고자료 파일명/제목에 가공 법령명이나 사건번호가 포함되어 있다는 이유만으로 지지(`SUPPORTED`)로 올리지 않습니다 (제목 부분 일치 배제).
   - 반드시 참고자료 본문 텍스트 내 실질 인용이 확인된 경우에만 지지 상태를 부여합니다.

---

## 2. 위계 표시 (F3a)

### 2.1 모든 Drive 출처에 "참고자료(공식 법령·판례 아님)" 고정 표기
- 모든 Drive 기반 대조 결과, 관찰의견, 출처 목록에 고정 한계 문구를 명시합니다:
  - `ReviewItem.evidence_sources`: `f"참고자료(공식 법령·판례 아님): {source_title}"` 형태로 출처 문자열을 표준화합니다.
  - `ReviewItem.authority_limitation`: `"참고자료(공식 법령·판례 아님)"` 필드를 활용하거나, 관찰의견 객체의 설명 머리말에 고정 안내를 바인딩합니다.
  - 화면 UI 배지: Drive 참고자료 배지에 `[참고자료 (공식 법령·판례 아님)]` 툴팁 및 안내 문구를 고정 렌더링합니다.

### 2.2 자료 이름·폴더 낱말로 법령·지침 추측 분류 금지
- 파일명이나 폴더 경로에 `"법률"`, `"대통령령"`, `"훈령"`, `"예규"`, `"지침"`, `"규정"` 등의 단어가 포함되어 있더라도, 이를 근거로 공적 규범 위계를 추측하거나 자의적으로 분류하지 않습니다 (낱말 사전/휴리스틱 매핑 일체 금지).
- Drive에 업로드된 모든 자료는 공적 효력이 없는 **동일한 위계의 '사적 참고자료'**로 일관되게 취급합니다.

---

## 3. 주장 단위 검색 및 대조 (F3b)

### 3.1 현행 문서 단위 경로 유지 및 주장 단위 단계 추가
1. **문서 단위 경로 유지**:
   - 현행 `packages/rag_engine/review.py`의 `batches` 기반 배치 대조(서면 전체 텍스트와 참고자료 묶음 대조)는 제거하지 않고 100% 보존합니다.
   - 이를 통해 문서 전체 맥락에서 파악되는 포괄적 모순/상충 관찰의견을 누락 없이 확보합니다.
2. **주장 단위 단계 추가**:
   - 배치 대조 완료 후, 서면의 적격 주장 목록(`claims`, `DOCUMENT_META` 및 `ADVERSARIAL_INSTRUCTION` 제외)을 순회하며 주장 단위 검색 및 모델 대조를 수행합니다:
     1) **Drive 본문 검색**: 각 주장의 텍스트로부터 추출한 `salient_words`(2자 이상 한글 단어, 숫자열 배제)로 `drive.search_fulltext` 실행 (주장당 최대 2회 검색).
     2) **발췌문 묶음**: 검색된 관련 참고자료 본문에서 해당 주장과 관련된 발췌문(최대 4,000자)을 구성.
     3) **모델 대조 요청**: `LLMRouter.run`을 호출하여 해당 주장과 발췌문 간의 부합성 대조 수행 (주장당 최대 3회 호출).

### 3.2 두 경로의 결과 합치는 규칙 (병합 및 중복 제거)
- **중복 제거 (Deduplication)**:
  - 문서 단위 배치 대조의 `observations`와 주장 단위 대조의 `observations`를 합칠 때, `(obs["claim_quote"], obs["source_quote"])` 튜플을 고유 키로 삼습니다.
  - 동일한 주장 인용구와 동일한 출처 인용구를 가진 의견은 하나로 병합하며, 설명(`explanation`)이 더 구체적인 주장 단위 의견을 우선 채택합니다.
- **규칙 대조 우선권**:
  - 규칙 기반 조항 인용 대조(`provision_quotes`) 결과는 모델 의견보다 우선하여 보존합니다.

### 3.3 전후 비교(A/B Comparison) 측정 방법
- 주장 단위 도입의 실효성과 추가 효과를 정량 검증하기 위해, `engine_data["rag"]["comparison_metrics"]`에 다음 메트릭을 기록합니다:
  ```json
  {
      "batch_only_observations": 3,
      "batch_accepted_count": 2,
      "claim_level_observations": 5,
      "claim_accepted_count": 4,
      "merged_total_observations": 5,
      "incremental_findings_count": 2
  }
  ```
- 동일 입력에 대해 문서 단위 단독 실행 결과와 합산 실행 결과를 매니페스트 및 엔진 데이터로 비교 검증합니다.

---

## 4. 통합 표 노출 (F3d)

### 4.1 F2 통합 표(`documents[].review_items`) 내 '참고 의견' 행 구성
- **행 종류**:
  - 인용 행(`kind == ReviewItemKind.CITATION`)에 연결되는 참고자료 지지는 기존 인용 행의 `reference_status` 및 `evidence_sources`로 자연스럽게 수용됩니다.
  - 인용에 귀속되지 않는 순수 사실관계/주장 대조 관찰의견은 `ReviewItemKind.REFERENCE_OBSERVATION` 행으로 생성합니다.
- **배지 및 심각도**:
  - 배지: `[참고 의견]`
  - 심각도: `Severity.INFO` 고정 (D4 원칙: 어떠한 경우에도 WARNING이나 CRITICAL로 승격되지 않음)
  - 속성: `advisory_only = True`
- **기존 행과의 연결**:
  - `claim_id` 및 `location`(페이지, 텍스트 구간)을 통해 서면의 원본 주장 위치와 연결합니다.

### 4.2 인용문 표시 및 기각 의견 건수 처리
- **인용문 병기**: 서면의 주장 인용문(`claim_text` / `claim_quote`)과 참고자료의 근거 인용문(`source_quote`, 문서명, 쪽 번호, Drive 링크)을 나란히 대비하여 표시합니다.
- **기각 의견(Rejected Observations)**:
  - 검증에 실패한 의견(환각 인용구, 스키마 불일치 등)은 본문을 노출하지 않고, 요약 카드에 기각 건수(`len(rejected_observations)`)만 표시합니다.

### 4.3 `claim_coverage` 노출 위치 및 형식
- **노출 위치**: 통합 검토 화면 상단 요약 카드 및 `engine_data.rag.claim_coverage`.
- **노출 문구**: `"참고자료 대조율: 대조 대상 {eligible_claims}건 중 {linked_claims}건 완료 ({coverage_pct}%)"` (예: "7건 중 3건 대조 완료").
- **상한 초과 주장 처리**:
  - 문서당 상한(10개 주장)을 초과한 주장은 탈락시키지 않고 분모(`eligible_claims`)에 그대로 남깁니다.
  - 해당 주장은 `unreviewed` 목록에 `{"claim_id": c_id, "reason": "REASON_BUDGET_EXCEEDED"}` 사유와 함께 기록되어 화면에 미대조 사유가 투명하게 공개됩니다 (T7 충족).

### 4.4 T1(단일 판정) · T2(손실 없음) · T4(AI 탭 배타성) 준수 근거
- **T1 (단일 판정 준수)**:
  - 1개 인용에 대해 1개의 `ReviewItemKind.CITATION` 행만 생성되며, `official_status`와 `reference_status`가 한 행의 두 축으로 통합되어 중복 행이 발생하지 않습니다.
- **T2 (정보 손실 없음)**:
  - 기존의 모든 `Finding`과 검토 항목은 `finding_ids`를 통해 100% 보존되며 누락되지 않습니다.
- **T4 (AI 탭 배타성 유지)**:
  - 모든 참고자료 관찰의견은 오직 '검토 항목' 탭에만 배정되며, AI 진단·보안 탭으로 절대 혼입되지 않습니다.

---

## 5. 전송 경로와 호출 수 (F3e)

### 5.1 라우터 및 전송 전 검사 경로 (우회 금지)
- 주장 단위 모델 호출은 다음의 표준 단일 경로를 엄격히 경유합니다:
  ```
  [주장 단위 요청 생성] 
       ↓
  [화이트리스트 스키마 검증 (TK-55)] 
       ↓
  [PII 마스킹 (연락처·주민번호 마스킹)] 
       ↓
  [inspect_request (전송 전 전수 보안 검사)] 
       ↓
  [LLMRouter.run(LLMRole.PRIMARY_REASONER, ...)] 
       ↓
  [외부 LLM 공급자]
  ```
- 별도의 독립적인 HTTP 클라이언트나 우회 경로를 일절 신설하지 않습니다.

### 5.2 요청 본문 스키마 화이트리스트 (19b 6.1 · TK-55 고정)
- 주장 단위 대조 시 `LLMRequest.user`에 담기는 JSON 본문 최상위 키는 다음 4개로 화이트리스트 고정합니다:
  ```python
  ALLOWED_REQUEST_KEYS = {
      "system_instructions",  # 고정 시스템 지침
      "claim_id",             # 비식별 주장 식별자
      "claim_text",           # 마스킹된 주장 텍스트
      "reference_sources",    # 마스킹된 참고자료 발췌 목록
  }
  ```
- **Fail-Closed 원칙**: 위 4개 외의 키가 포함된 요청 객체는 `LLMRouter.run` 진입 전 즉시 차단(거절)됩니다.
- **인명 키 원천 배제**: `name`, `party`, `client`, `suspect`, `victim`, `owner`, `author`, `user`, `email` 등 인명이나 당사자를 가리키는 키는 스키마에 일체 두지 않습니다.

### 5.3 서면 10주장 기준 최대 외부 호출 수 산식
- **주장당 상한**:
  - 기본 대조 1회 + 일시적 장애/형식 오류 시 대체 공급자 재시도 최대 2회 = 주장당 최대 3회 모델 호출.
- **문서당 상한**:
  - 대조 대상 주장 수: 최대 10개 주장.
  - 주장 단위 최대 외부 호출 수: $10 \text{ 주장} \times 3 \text{ 회} = \mathbf{30 \text{ 회}}$.
- **문서 단위 배치 호출 합산**:
  - 기존 문서 단위 배치 대조 (최대 2개 배치 $\times$ 재시도 1회): 최대 4회.
- **서면 1건당 전체 외부 호출 엄격 상한**: $\mathbf{34 \text{ 회}}$.

### 5.4 `LOCAL_ONLY` 및 QUICK 모드 외부 호출 0 분기 위치 (T9 보호 시험)
- `packages/rag_engine/review.py`의 `review_document` 함수 진입부:
  ```python
  if (
      context.external_ai_policy == ExternalAIPolicy.LOCAL_ONLY
      or context.profile == VerificationProfile.QUICK
      or not router.has_available_provider(policy=context.external_ai_policy)
  ):
      # 모델 대조 루프(배치 및 주장 단위)를 완전히 건너뛰고
      # 규칙 대조(provision_obs) 및 검색 메타데이터만 반환
      review.update(status="RETRIEVED_ONLY", reason="MODEL_NOT_AVAILABLE_OR_QUICK_PROFILE")
      return review
  ```
- 이 분기를 통해 `LOCAL_ONLY` 환경에서는 공급자 호출이 정확히 0건(`sent == []`)으로 보장됩니다 (T9 시험 통과).

---

## 6. 영향 범위

### 6.1 고정 시험·probe·회귀 게이트 점수 불변 근거
1. **오프라인 Drive 부재 격리**:
   - CI 및 로컬 환경에서 수행되는 고정 시험(개발/홀드아웃), probe 문서 점검, 12개 회귀 게이트는 Drive 연결이 없는 상태(`library.summary["status"] != "READY"` 또는 `sources == []`)에서 실행됩니다.
   - 따라서 F3의 신규 LLM 대조 및 주장 단위 경로는 오프라인 환경에서 전혀 트리거되지 않고 기존 안전 폴백(`SKIPPED` 또는 `NOT_RELEVANT`)으로 빠져나갑니다.
2. **규칙 체계 불변**:
   - 신규 `rule_id` 및 신규 `FindingType`을 1건도 추가하지 않으므로, 기존 탐지 엔진 점수와 심각도 계산식에 영향도가 0입니다.
   - 고정 시험 점수(dev 81.7 / holdout 79.2 / 오탐 0)는 100% 동일하게 유지됩니다.

### 6.2 검증 계획
- 구현 커밋 전후로 `python scripts/scorecard.py`를 실행하여 점수 불변을 입증합니다.
- `tests/acceptance/test_f3_protected.py`의 오프라인 하네스 시험(T6~T9, 요청 스키마)을 통해 신규 경로의 동작을 독립적으로 검증합니다.

---

## 7. 다른 분야 동작 (T8 보호 시험)

### 7.1 사건·분야 낱말 하드코딩 일체 배제
- 특정 소송 사건이나 법률 도메인(예: "산업안전보건법", "임대차보호법", "국가배상" 등)을 전제하는 키워드 화이트리스트나 특화 분기를 코드에 일절 두지 않습니다.
- 질의어 생성은 형태소 기반 2자 이상 한글 단어 추출(`salient_words`)로 자동 일반화되며, 대조는 유연 텍스트 비교(`_contains_flexible`) 및 시스템 프롬프트의 범용 대조 지침에 따라 실행됩니다.

### 7.2 평가 측 합성 자료 2세트 호환 보장
- 평가 측이 `test_f3_protected.py`에 구축한 분야 A(산업안전·손해배상) 및 분야 B(주택임대차·보증금)의 상이한 합성 참고자료 세트에서:
  - 완전히 동일한 절차(`review_document` → 주장 추출 → 검색 → 대조 → 병합)가 수행됩니다.
  - 완전히 동일한 결과 구조(`official_status=OFFICIAL_NOT_FOUND`, `reference_status=SUPPORTED`, `claim_coverage` 산출)가 생성되어 T8 시험을 완벽히 통과할 수 있도록 설계되었습니다.
