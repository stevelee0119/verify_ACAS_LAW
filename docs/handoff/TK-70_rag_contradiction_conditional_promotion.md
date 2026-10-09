# TK-70 Drive 참고자료 '모순' 의견의 조건부 finding 승격 — D4 개정 (P2, 사용자 결정에 따른 기능 변경)
- 유형: 기능 변경(P2). 사용자 결정 D4 개정에 따른 것이다. 결함이 아니다.
- 근거
  - 사용자 결정(2026-10-09, '단계적 조건부 승격'): D4 '참고자료 대조 의견은 승격하지 않는다'를 조건부 승격으로 바꾼다.
  - 1단계 측정 충족: 평가 측 비공개 온라인 측정 세트(양성 6·대조 6)에서 a8b2a7e 12/12. 대조군 '모순' 의견 0건, '모순' 의견 11건 모두 실제로 어긋난 문장에 달렸다(run_25bc902542f9452f).
- 작성: evaluator 2026-10-09

## 1. 현재
- `packages/verification_engine/pipeline.py`(418행 부근)에 TK-09 승격 경로가 있다. 이 경로는 '모순'(CONTRADICTS) 의견을 `candidate_verifier.verify_rag_candidate`로 결정적으로 검사해 `FACT_CONTRADICTION` finding으로 올린다.
- 그러나 두 겹으로 막혀 있다.
  1. `LV_CANDIDATE_PROMOTION_ENABLED`가 기본으로 꺼져 있다.
  2. F3 뒤의 모든 RAG 의견은 `advisory_only`가 참이어서 건너뛴다.
- 평가 측 모의(이 경로를 그대로 적용, 제품 코드 변경 없음)

| 보고서 | '모순' 의견 | 검사 통과(승격) | 비고 |
|---|---|---|---|
| 측정 세트 run_25bc902542f9452f | 11 | 11 | 모두 양성 문장. 같은 주장에 최대 3건 중복 |
| 서면9 보관 보고서 8건 | 8(3개 실행) | 8 | 모두 제22조 인용 주장·과실상계 주장. 3개 실행에서 RAG-2가 통과 조건을 갖춘다 |

- 지금 승격하면 심각도 MEDIUM·B등급이고, 검증위험 지수에 30점(`gate.RISK_WEIGHTS`)이 더해진다.

## 2. 요구
1. **승격 대상**: 다음을 모두 만족하는 RAG 의견
   - 관계가 `CONTRADICTS`
   - `verify_rag_candidate` 통과(서면 인용과 참고자료 인용이 각각 원문과 일치)
   - 결정론 관찰(`exhibit_facts`, `source_type` deterministic)이 아님
   - 문서 단위 의견·주장 단위 의견 모두 대상이다. `advisory_only` 표시만으로 제외하지 않는다.
2. **승격 형식**(D4 개정의 조건)
   - `FACT_CONTRADICTION`, 상태 `SUSPICIOUS`, 심각도 **LOW**, **C등급**
   - 제목·설명에 '내부 참고자료 대조 — 법적 구속력 미판단, 사람 확인 필요'를 밝힌다.
   - `confidence_features`에 `rule_id`(`RAG.REFERENCE_CONTRADICTION` 등 새 값), `claim_id`, **주장 원문**, `source_id`, 참고자료 제목, 양쪽 인용문을 남긴다.
3. **중복 합치기**: 같은 주장(`claim_id`, 없으면 정규화한 `claim_quote`)과 같은 참고자료(`source_id`)의 승격은 finding 하나로 합친다. 근거·설명은 그 안에 모은다.
4. **영향 한정**
   - 공식 DB 상태(`official_status`)와 다른 finding의 심각도는 바꾸지 않는다(T6 원칙).
   - 이 finding은 검증위험 지수와 차단 게이트에 넣지 않는다(내부 자료이고 법적 구속력을 판단하지 않았다). 방법은 설계 메모로 정한다.
   - 원래 RAG 의견 기록(`engine_data.rag.observations`)과 대조율 기록은 그대로 둔다.
5. **스위치**
   - 이 승격은 기본으로 켠다(사용자 결정).
   - 끌 수 있는 운영 스위치를 하나 둔다(예: `LV_RAG_CONTRADICTION_PROMOTION`, 기본 켬).
   - 기존 `LV_CANDIDATE_PROMOTION_ENABLED`(그 밖의 모델 후보, `ai_document_detector`)는 그대로 둔다.
6. 바꾸지 않는 것: 응답 형식(TK-65), 등록 프롬프트, 주장 단위 예산·선별(TK-63), 개인정보 경로, 요청 메타데이터 `stage` 값.
7. 시험(합성, 가짜 공급자가 '모순' 의견을 내게 한다. 시험 설명에 합성임을 적는다)
   - 양성 3건 이상: 승격되고 LOW·C·SUSPICIOUS이며, 주장 원문과 `claim_id`가 기록된다.
   - 대조 3건 이상
     - 참고자료 인용이 원문에 없는 의견
     - 서면 인용이 원문에 없는 의견
     - `SUPPORTS`·`CONTEXT` 의견
     - 결정론 관찰
   - 중복 합치기 1건, 스위치를 끄면 승격 0 1건, 검증위험 지수·게이트 불변 1건
   - 기존 F3 보호 시험(`tests/acceptance/test_f3_protected.py`)과 TK-09 시험 그대로 통과

## 3. 지시 사전 점검(평가 측, Steve 114f8b3 + 임시 패치, 커밋 안 함, 되돌림)
- 임시 패치: 승격 플래그와 `advisory_only` 건너뛰기만 제거(형식·중복·지수 제외는 넣지 않음).
- RAG·승격 관련 14개 파일
  - `test_tk09_candidate_verifier`·`acceptance/test_f3_protected`·`test_drive_rag`·`test_drive_rag_relevance`·`test_evidence_rag_review`·`test_f3_claim_search`·`test_verification_completeness`·`test_v096_sanitized_input`·`test_v098_drive_gate`·`test_v099_drive_fixes`·`test_tk65_envelope_schema`·`acceptance/test_review_feedback_report`·`test_efficacy_improvements`·`regression/test_ledger`
  - 결과: 패치 전·후 모두 **431 passed, 1 xfailed**
- 해석: 기존 가짜 공급자는 '모순' 의견을 내지 않는다. 그래서 기존 시험은 이 경로를 지키지 않는다. 2.7의 새 시험이 필요하다.
  - T6(`test_t6_reference_never_changes_official_status_findings_or_severity`)도 '모순' 의견이 없는 하네스라 계속 통과한다.
  - 평가 측은 수용 때 T6 설명문을 'D4 개정: 모순 승격 외에는 불변'으로 고친다(보호 경로, 평가 측 몫).
- 오프라인 점수는 바뀌지 않는다(네트워크를 끄면 RAG 단계가 돌지 않는다).

## 4. 수용
- 2.7 시험 추가·통과. 기존 시험 수정 없음. 고정 81.7/79.2/0 같음. CI 필수 3개 성공.
- 수용 SHA에서 평가 측이 `verify_all` 전체 모드를 돌린다.
- 봉인 시험은 하지 않는다. 오프라인 탐지 엔진 밖(RAG 경로)이다(RELEASE_PROCEDURE 2절).
- 배포 뒤 온라인
  - 평가 측 비공개 측정 세트 2회차: 양성 문장에 승격 finding, 대조군 승격 0
  - 서면9: 처음 보는 실패 0. RAG-2는 '모순' 의견이 나온 실행에서 통과해야 한다.
  - 한 번의 결과로 단정하지 않는다.
