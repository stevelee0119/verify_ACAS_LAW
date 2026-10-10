# TK-70 Drive 참고자료 '모순' 의견의 조건부 Finding 승격 설계 메모 (D4 개정)

- 작성: Antigravity (구현 에이전트) 2026-10-10
- 관련 티켓: `docs/handoff/TK-70_rag_contradiction_conditional_promotion.md`

## 1. 배경 및 목적 (D4 개정, 사용자 결정)
- **기존 원칙 (D4)**: "참고자료 대조 의견은 법적 구속력을 판단하지 않으므로 finding으로 승격하지 않는다(`advisory_only`)."
- **사용자 결정 (2026-10-09, '단계적 조건부 승격')**:
  - 평가 측 비공개 온라인 측정 세트(양성 6·대조 6) 1단계 검증 통과(대조군 모순 0건, 모순 11건 전원 실제 불일치 문장에 부여).
  - 이에 따라 엄격한 인용문 일치 검증을 통과한 `CONTRADICTS` 의견에 한하여 조건부로 정식 Finding으로 승격함.

## 2. 요구사항 및 설계

### 2.1 승격 대상 및 판정 기준
다음 조건을 **모두** 만족하는 RAG 관찰 의견을 승격 대상으로 선별함:
1. 관계(`relationship`): `"CONTRADICTS"`
2. 결정론적 관찰 제외: `engine == "exhibit_facts"` 또는 `source_type == "deterministic"` 제외
3. 인용문 결정론 검증 통과: `verify_rag_candidate`를 통해 서면 인용(`claim_quote`)과 참고자료 인용(`source_quote`)이 각각 서면 원문과 참고자료 원문에 정확히 일치함이 확인됨
4. 범위: 문서 단위 의견(`stage: drive_rag_advisory`) 및 주장 단위 의견 모두 대상. 기존의 `advisory_only` 속성만으로 배제하지 않음.

### 2.2 승격 Finding의 형식 및 속성 (D4 개정 조건 준수)
- **Finding Type**: `FindingType.FACT_CONTRADICTION`
- **상태 (Status)**: `VerificationStatus.SUSPICIOUS`
- **심각도 (Severity)**: `Severity.LOW` (D4 조건: 결함이 아니며 참고 의견이므로 LOW 부여)
- **증거 등급 (Evidence Grade)**: `EvidenceGrade.C` (C등급)
- **제목 (Title)**: `내부 참고자료 대조 — 법적 구속력 미판단, 사람 확인 필요: {source_title} — {explanation[:80]}`
- **상세 설명 (Detail)**:
  `서면 주장 '{claim_quote}' 및 참고자료({source_title})의 규정 '{basis_quote}' 원문 일치가 확인되었습니다. 모델 의견: {explanation} (참고: 내부 참고자료 대조 결과이며, 공식 법령·판례와 같은 법적 구속력은 판단하지 않았으므로 사람이 최종 확인해야 합니다)`
- **신뢰도 속성 (`confidence_features`)**:
  - `rule_id`: `"RAG.REFERENCE_CONTRADICTION"` (새 규칙 식별자)
  - `claim_id`: 주장 식별자 (있는 경우)
  - `claim_text`: 주장 원문
  - `source_id`: 참고자료 식별자
  - `source_title`: 참고자료 제목
  - `claim_quote`: 서면 인용문
  - `basis_quote`: 참고자료 인용문
  - `human_review`: True
  - `advisory_only`: False (정식 finding 목록 등재)

### 2.3 동일 주장·참고자료 중복 합치기 (Grouping)
- 동일한 주장(`claim_id`, 없는 경우 정규화된 `claim_quote`)과 동일한 참고자료(`source_id`)에서 여러 모순 의견이 발생한 경우, 1개의 통합 Finding으로 합침.
- 근거(`evidence`) 목록 및 모델 설명은 Finding 내부에 통합 보존함.

### 2.4 영향 한정 및 기존 시스템 격리
- **검증위험 지수 (`gate.risk_index`) 격리**:
  - `confidence_features["rule_id"] == "RAG.REFERENCE_CONTRADICTION"`인 Finding은 `risk_index` 계산 시 가중치 합산(30점)에서 제외(`continue`).
- **배포 차단 게이트 (`gate.evaluate_gate`) 영향 없음**:
  - 심각도가 `LOW`이므로 `HARD_BLOCK_IF_CRITICAL`(`severity == CRITICAL` 시 차단)에 걸리지 않으며, 위험지수도 0으로 유지되어 기존 배포 판정에 전혀 영향을 주지 않음.
- **공식 DB 상태 (`official_status`) 및 타 Finding 심각도 불변 (T6 원칙)**.
- **RAG 원본 데이터 보존**: `document_result.engine_data["rag"]["observations"]` 및 대조율 통계는 원본 그대로 유지.

### 2.5 운영 스위치 및 기존 경로와의 관계
- `packages/common/config.py`의 `Settings`:
  - `rag_contradiction_promotion_enabled: bool = True` (환경변수 `LV_RAG_CONTRADICTION_PROMOTION`, 기본 True)
- 기존 `candidate_promotion_enabled`(`LV_CANDIDATE_PROMOTION_ENABLED`)는 기본 False 유지.
- **경로 우선순위 의도**: `rag_contradiction_promotion_enabled`가 켜져 있으면 RAG 관찰 결과 순회 시 새 조건부 승격 경로가 우선 적용되며, 기존 TK-09 RAG 후보 승격 경로(`elif settings.candidate_promotion_enabled`)는 동일 관찰의 중복 승격을 방지하기 위해 진입하지 않습니다 (기본값에서 동작 차이 없음).
- **거부 기록 사유**: `verify_rag_candidate`에서 인용문 불일치 등으로 승격이 거부된 의견을 `review['rejected_observations']`에 기록하는 것은, UI 및 감사 보고서의 '제외 의견 N건'에서 탈락 사유를 투명하게 추적할 수 있도록 기존 TK-09 거부 기록 규칙과 일관성을 유지하기 위함입니다.

---

## 3. 검증 계획
1. **합성 단위 시험 (`tests/test_tk70_rag_contradiction_promotion.py`)**:
   - **양성 예시 3건**:
     1) 문서 단위 대조 모순 의견 승격 (LOW, C등급, SUSPICIOUS, 원문 일치)
     2) 주장 단위 대조 모순 의견 승격 (`claim_id` 및 주장 원문 보존)
     3) 복수 출처 참고자료 모순 의견 승격
   - **대조군 4건**:
     1) 참고자료 인용문이 원문에 없는 경우 (승격 제외, reject)
     2) 서면 인용문이 원문에 없는 경우 (승격 제외, reject)
     3) `SUPPORTS` 또는 `CONTEXT` 의견 (승격 제외)
     4) 결정론적 관찰(`exhibit_facts`) (승격 제외)
   - **중복 합치기 1건**: 동일 `claim_id` + `source_id` 2건 의견이 1개 Finding으로 통합됨 단언
   - **스위치 제어 1건**: `LV_RAG_CONTRADICTION_PROMOTION=false` 시 승격 0건 단언
   - **위험지수/게이트 격리 1건**: 승격 Finding이 있어도 `risk_index == 0` 및 Gate 판정 PASS 단언
2. **기존 시험 회귀 검증**:
   - `tests/test_tk09_candidate_verifier.py`, `tests/acceptance/test_f3_protected.py` 100% 통과 유지
3. **고정 성적표**:
   - `dev 81.7 / holdout 79.2 / 오탐 0 / A등급 0` 불변 확인
