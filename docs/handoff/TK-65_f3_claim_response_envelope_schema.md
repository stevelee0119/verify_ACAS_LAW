# TK-65 F3 주장 단위 대조에서 인용 주장 응답이 형식 검사에 걸려 대조되지 않는다 — 응답 최상위 형식을 프롬프트에 명시 (P2, 기능 목표 미달)
- 유형: 기능 목표 미달(P2). 오탐·회귀는 없다. 운영본(`main` 1f38751, 릴리스 TK-63)에 있다.
- 발견: 평가 측, 릴리스 TK-63 배포 직후 온라인 점검(2026-10-09, 서면9, run_1ed170a0c2e44cd2, 보고서 commit 1f38751).
- 작성: evaluator 2026-10-09

## 1. 증상
- 온라인 점검은 19/23으로, 직전 F3 점검과 같다. 새 실패는 0이다. RAG-1(내부 규정 제22조 정면 모순)은 여전히 실패다.
- TK-63의 선별은 의도대로 동작했다.
  - `claim_coverage.selection_rule`이 `TK63_CITATION_LEGAL_FACT_LENGTH_V1`로 기록됐다.
  - `budget`은 `{max_per_document 30, budget_seconds 240, budget_usd 1.0, halt_reason null}`이다.
  - 대상 주장 19개를 모두 보냈다. `REASON_BUDGET_EXCEEDED`는 0개다(직전 9개).
- 그러나 **선별 순위 1~5번인 인용 연결 주장 5개가 모두 `MODEL_UNAVAILABLE`**이다. 제22조 인용 주장도 여기에 들어 있다.
  - 이 5개에 대한 주장 단위 실행은 모두 `INVALID_RESPONSE_SCHEMA: required 위반(최상위)`로 실패했다.
  - 대조 결과: 대상 19, 대조됨 6, 미대조 13이다. 미대조 사유는 `MODEL_UNAVAILABLE` 7(인용 주장 5, 기타 2), `NOT_LINKED_TO_SELECTED_EXCERPTS` 6이다.
- 문서 단위 대조 3회 중 2회도 실패했다(출력 잘림 1, 같은 최상위 required 위반 1).

## 2. 원인(코드 근거, 응답 원문은 보고서에 없어 추정 포함)
1. **응답 최상위 형식이 모델에 전달되지 않는다.**
   - 라우터는 응답을 `ENVELOPE_SCHEMA`(`{"observations": [...]}`가 필수)로 검사한다(`packages/llm_router/router.py`의 `validate(parsed, request.schema)`).
   - 그러나 공급자 요청에는 이 스키마가 실리지 않는다.
     - Anthropic 어댑터는 `system`·`messages`만 보낸다.
     - OpenAI 어댑터는 `response_format: json_object`만 보낸다.
   - `RAG_REVIEW_SYSTEM_PROMPT`(`packages/rag_engine/review.py`)는 끝에 '**출력 항목**의 형식'으로 `ITEM_SCHEMA`(의견 한 건의 형식)만 보인다.
     - 최상위 키 `observations`는 '근거가 없으면 observations를 빈 배열로 반환하라'는 문장에만 나온다.
2. 그래서 **할 말이 있는 주장**일수록, 곧 인용이 연결되어 참고자료와 맞닿는 주장일수록, 모델이 의견 한 건을 최상위 객체로 바로 내기 쉽다.
   - 이 경우 `_extract_json`이 객체 하나를 읽고, 그 객체에 `observations`가 없어 required 위반이 된다.
   - 반대로 관련이 없는 주장은 프롬프트 문장대로 `{"observations": []}`를 내기 쉬워 형식 검사를 통과한다. `NOT_LINKED` 6건은 이런 응답이거나 인용이 원문과 맞지 않은 응답이다(보고서로 둘을 가르지 못한다).
   - 주장 단위 형식 실패는 6건이다. 그중 5건이 선별 1~5번, 곧 인용 주장 5개 전부다. 나머지 1건은 그 밖의 주장이다. 주장 19건 중 성공은 12건이다(형식 실패 6, 빈 오류 1 제외).
3. 주장 단위 요청은 대체 재시도가 없다(TK-63 3.2, 설계 유지). 따라서 형식 실패가 곧바로 `MODEL_UNAVAILABLE`이 된다.

## 3. 함께 본 기록 결함(같은 실행)
- 주장 단위 실행 1건이 `ok false`, 토큰 0, 지연 0, **오류 문구 빈칸**으로 기록됐다. 비용 상태는 `RESERVED_UNCERTAIN`이고 예약액 $0.4532가 그대로 비용에 잡혔다.
  - 원인(코드): Anthropic 어댑터는 예외를 `error=str(exc)`로 남긴다. 메시지가 빈 예외(일부 httpx 시간 초과 등)는 빈칸이 된다. 실패 이유를 알 수 없다.
  - 영향: 주장 단위 비용 합계는 $1.0188이다. 이 중 $0.4532가 '청구 여부 불확실' 예약액이다. 실제 보고 비용만 더하면 약 $0.57이다.
    - 마지막 주장을 보내기 전 누계는 $1.00 바로 아래였다. 주장이 하나 더 있었다면 비용 예산(`COST`)으로 멈췄을 것이다.
    - 예약액을 보수적으로 세는 것 자체는 안전한 쪽이다. 다만 지금은 기록에서 확정 비용과 구별되지 않는다.
- 주장 단위 단계 경과는 약 213초로, 시간 예산 240초에 가깝다.

## 4. 요구
1. **응답 최상위 형식을 프롬프트에 명시한다**(`RAG_REVIEW_SYSTEM_PROMPT`).
   - 최상위는 `{"observations": [항목, ...]}` 객체 하나이고, 의견이 하나여도 배열에 넣는다는 문장을 넣는다.
   - 형식 예시는 `ITEM_SCHEMA` 대신 전체 `SCHEMA`(이미 등록된 `SCHEMA_RAG_FULL`)를 보인다.
   - 문서 단위·주장 단위 요청이 같은 상수를 쓰므로 둘 다 적용된다.
2. **요청 스키마는 `ENVELOPE_SCHEMA`를 그대로 둔다.**
   - 이것은 등록 스키마(TK-28)이고, 평가 측 보호 시험의 가짜 공급자도 최상위 `required`의 `observations`로 요청을 알아본다.
   - 아래 '사전 점검' 3을 본다. 요청 스키마를 바꾸는 방식(관대한 수용 스키마 등)은 이 티켓에서 하지 않는다.
3. **빈 오류 문구를 남기지 않는다.**
   - 공급자 어댑터 전부(`providers.py`의 `error=str(exc)` 4곳)에서 예외 메시지가 비면 예외 형식 이름을 남긴다(예: `PROVIDER_EXCEPTION: ReadTimeout`).
   - 라우터의 일시 장애 재시도 판정은 바꾸지 않는다.
4. **비용 기록을 나눈다.** `claim_coverage.budget`에 새 키 2개를 더한다.
   - `spent_usd`: 주장 단위 단계의 비용 합계로, 예산 판정에 쓴 값이다.
   - `uncertain_usd`: 그중 `RESERVED_UNCERTAIN` 예약액 합계다.
   - 예산 판정 방식(예약액 포함)과 기존 키는 바꾸지 않는다.
5. 시험(합성 입력, 시험 설명에 합성임을 적는다)
   - 프롬프트: `RAG_REVIEW_SYSTEM_PROMPT`에 최상위 형식 문장과 전체 `SCHEMA`가 들어 있고, 등록 프롬프트 검사(`is_registered_system_prompt`)를 통과한다.
   - 빈 예외: 가짜 전송이 빈 메시지 예외를 내면 실행 기록 `error`가 비어 있지 않고 예외 형식 이름을 담는다. 공급자 어댑터마다 확인한다.
   - 비용 기록: 가짜 실행 비용(확정·`RESERVED_UNCERTAIN` 섞음)으로 `spent_usd`·`uncertain_usd`가 맞게 기록된다.
6. 서면9의 문장·규정명이나 특정 조항 번호에 맞춘 규칙을 넣지 않는다.

## 5. 지시 사전 점검 (평가 측, 97d597a(= 운영 1f38751 제품 코드) + 임시 패치, 커밋 안 함, 되돌림)
1. **요구 4.1만 넣은 판**(프롬프트에 최상위 형식 문장과 전체 `SCHEMA`, 요청 스키마 그대로)
   - RAG·F3 관련 시험 13개 파일: **256 passed**.
     - `test_drive_rag`·`test_drive_rag_relevance`·`test_evidence_rag_review`·`test_f3_claim_search`·`test_tk09_candidate_verifier`·`test_v096_sanitized_input`·`test_v098_drive_gate`·`test_verification_completeness`·`test_efficacy_improvements`·`test_case4`·`test_case5`·`acceptance/test_f3_protected`·`acceptance/test_no_case_literals`
   - 개인정보·등록 프롬프트 관련 시험 29개 파일과 `tests/regression`: **947 passed, 22 xfailed**, 실패 0.
2. 오프라인 점수는 바뀌지 않는다. 네트워크를 끄면 RAG 단계가 돌지 않기 때문이다.
3. **요청 스키마를 관대한 수용 스키마로 바꾼 판은 충돌한다.**
   - 이 판은 `observations` 또는 단일 항목을 받고, 받은 단일 항목을 감싸서 쓴다.
   - 평가 측 보호 시험 T7 2건이 실패한다. 수용 스키마를 등록 목록에 더해도 같다.
   - 원인: 보호 시험의 가짜 공급자가 최상위 `required`로 요청을 알아본다.
   - 그래서 4.2를 둔다. 프롬프트 수정만으로 부족하다고 확인되면, 그때 평가 측이 하네스와 함께 다시 설계한다.
4. 요구 4.3·4.4는 임시 패치에 넣지 않았다. 구현 PR의 시험으로 확인한다.
5. 온라인 효과(인용 주장 형식 실패 감소, RAG-1)는 이 점검으로 재지 못한다.

## 6. 수용
- 4.5의 시험이 추가되어 통과한다. 기존 F3 보호 시험과 fail-closed 시험이 평가 측 하네스 아래에서 계속 통과한다.
- 고정 시험 점수가 같고(81.7/79.2/0) CI 필수 3개가 성공한다.
- RAG 엔진 변경이므로 수용 SHA에서 평가 측이 `verify_all` 전체 모드를 돌린다. 릴리스 전 봉인 채점은 새 세트로 한다(AGENT_ROLES 4절).
- 배포 뒤 서면9 온라인 점검에서 다음을 본다.
  - 주장 단위 `INVALID_RESPONSE_SCHEMA` 건수, 인용 주장의 대조 여부, RAG-1
  - `budget.spent_usd`·`uncertain_usd`
- 모델 응답은 실행마다 달라질 수 있다. 한 번의 결과로 효과를 단정하지 않는다.
