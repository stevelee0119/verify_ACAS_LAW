# F3 지시서 — 참고자료(RAG) 부합성 점검 강화 1단계: 설계 보충

작성: 평가 에이전트(claude-code) 2026-10-07 · 기준: `Steve_ACASiaLAW` 04b87e0(= 운영 `main` 43d3132, FT 반영 뒤) · 대상: Antigravity
범위·규칙의 원문:
- [F1 지시서 1절 F3](PROMPT_FOR_FEATURE_ROUND_F1.md)(F3a~F3e, 결정 D4·D6)
- 설계 개정판 [19b 5·6절](requests/19b_f1_design_rev.md)
- 평가 측 회신 [F1_DESIGN_REVIEW_REPLY 4·5절](F1_DESIGN_REVIEW_REPLY.md)

이 문서는 그 원문을 바꾸지 않고, F2·FT 뒤 현재 코드에 맞춘 착수 순서와 수용 기준을 정한다.

## 0. 순서
1. **(이번) 설계 보충만 낸다.** 코드를 쓰지 않는다.
   - `docs/handoff/requests/43_f3_design.md`로 PR을 올리고 '검토 요청'을 단다.
   - 브랜치는 `antigravity/f3-reference-review`(기준 `Steve_ACASiaLAW` 최신)다.
2. 평가 측이 회신한다(승인 또는 보완 요구).
   - 회신 전에 평가 측이 보호 시험 T6~T9와 요청 본문 스키마 시험을 strict xfail로 고정한다(4절).
3. 회신 뒤 구현한다. 같은 브랜치에서 하고, F3 커밋은 다른 기능 커밋과 섞지 않는다.

## 1. 착수 조건 (F1 지시서 0절 F3 추가 조건)
| 조건 | 상태 |
|---|---|
| (i) 개인정보: 연락처·주민등록번호 필수 게이트(누락·도달·오탐 0) | 8F-1에서 충족. **F3 측정 SHA에서 평가 측이 다시 잰다** |
| (ii) 참고자료 발췌가 서면과 같은 마스킹·전송 전 검사를 지나는 경로의 평가 측 시험(T9 포함) | 고정 완료(`tests/acceptance/test_f3_protected.py`, 2026-10-07). 현행 경로는 통과, 주장 단위 경로는 strict xfail |
| (iii) F2 완료, TK-29 해소 | 충족(F2 Steve 8b70497, TK-29 5차 해소) |

## 2. 이미 정해진 것(다시 설계하지 않는다)
- **D4 출력:** 참고자료 대조 의견은 '참고 의견'이다.
  - 심각도·finding 승격이 없고, 검토 상태만 기록한다.
  - TK-09 후보 승격은 계속 끈다.
- **D6 전송:** 기존 라우터, `external_ai_policy`, 전송 전 검사(`llm_router/privacy.py` `inspect_request`)를 그대로 쓴다.
  - 참고자료 전용 외부 전송 설정을 새로 만들지 않는다.
  - `LOCAL_ONLY`나 QUICK이면 모델을 부르지 않는다. 규칙 대조(`provision_quotes`)와 검색 결과만 낸다.
- **19b 5절(조건부 승인 반영분)**
  - 기존 `packages/rag_engine/review.py`(`grounded_observations`·`claim_coverage`)를 확장한다.
  - 대조 기준은 모델에 보낸 마스킹 텍스트(`_contains_flexible`)다.
  - Drive 본문 검색(`drive.search_fulltext`)의 질의는 `relevance.py`의 `query_profile`·`salient_words`로 만든다. 2자 이상 한글 단어만 쓰고, 숫자열은 넣지 않는다.
  - 상한: 주장당 검색 2·모델 3, 문서당 주장 10, 발췌 묶음 4,000자.
  - 상한 초과 주장은 `claim_coverage` 분모에 남기고 `unreviewed` 사유를 단다.
  - 상수는 기존 설정 위치에 두고 매니페스트에 기록한다.
- **19b 6절 요청 본문 스키마(TK-55)**
  - 허용 키 목록을 고정하고, 목록 밖의 키는 fail-closed로 보내지 않는다.
  - 사람을 가리키는 키를 두지 않는다.
  - `inspect_request`는 요청 전체를 검사한다(유지).
- **근거 사다리 두 축(F2에 이미 있음):** `ReviewItem.official_status`와 `ReviewItem.reference_status`(`ReferenceSupportStatus`: SUPPORTED·CONTRADICTED·NOT_MENTIONED·NOT_CHECKED)는 별개 축이다. 지금은 `review_items.py`가 `reference_status`를 `NOT_CHECKED`로만 둔다.
- **새 `rule_id`·`FindingType` 0, 고정 시험·probe 점수 변화 0**(F1 지시서 3절). FT와 달리 예외가 없다.

## 3. 설계 보충에 담을 것(F2·FT 뒤 현재 코드 기준)
1. **`reference_status` 채우기(F3a·F3c).**
   - 주장·인용 단위 대조 결과가 `ReviewItem.reference_status`로 들어가는 경로를 적는다(어느 함수에서 어느 키로).
   - 공식 미발견 인용이 참고자료 본문에 같은 인용으로 있을 때 `official_status=OFFICIAL_NOT_FOUND`는 그대로 두고 `reference_status=SUPPORTED`와 출처 링크만 더하는 방법을 적는다. 같은 인용은 사건번호, 또는 법령명+조문이다(T6).
   - 일치 규칙은 5차 U1(TK-29, `test_reference_match_guard.py`)을 재사용한다. 제목 부분 일치나 미독 파일로는 올리지 않는다.
2. **위계 표시(F3a).**
   - 모든 Drive 출처에 "참고자료(공식 법령·판례 아님)"를 고정 표기한다(`authority_limitation` 활용).
   - 자료 이름·폴더 낱말로 법령·지침을 추측해 분류하지 않는다(낱말 목록 금지).
3. **주장 단위 검색·대조(F3b).**
   - 현행 문서 단위 경로(`review_document`의 배치 대조)는 **제거하지 않고 유지**하며, 주장 단위 단계를 더한다.
   - 두 경로의 결과를 합치는 규칙을 적는다. 같은 주장·같은 발췌의 중복 의견은 하나로 합친다.
   - 전후 비교 방법을 적는다. 같은 입력에서 문서 단위만 쓴 의견 수·채택 수와 합친 뒤의 수를 비교한다.
4. **통합 표 노출(F3d).**
   - F2 통합 표(`documents[].review_items`)에 '참고 의견' 행을 어떻게 넣는지 적는다(행 종류, 배지, 기존 행과의 연결).
   - 서면 인용문·자료 인용문(출처 쪽·Drive 링크)을 함께 보이고, 기각 의견은 건수만 보인다.
   - `claim_coverage`(N건 중 M건 대조, 미대조 사유)를 어디에 보이는지 적는다.
   - T1(단일 판정)·T2(손실 없음)·T4(AI 탭 배타성)를 깨지 않는 근거를 적는다.
5. **전송 경로와 호출 수(F3e).**
   - 주장 단위 요청이 `LLMRouter.run`과 `inspect_request`를 지나는 경로를 적는다(새 우회 경로 금지).
   - 요청 본문 스키마의 최종 키 목록을 19b 6.1과 맞춰 적는다.
   - 서면 10주장 기준 최대 외부 호출 수를 산식으로 적는다.
   - `LOCAL_ONLY`에서 외부 호출이 0이 되는 분기 위치를 적는다(T9).
6. **영향 범위.**
   - 고정 시험·probe·회귀 게이트에서 점수가 바뀌지 않는다는 근거를 적는다. 오프라인에는 Drive가 없으므로 F3 경로가 돌지 않아야 한다.
   - 확인 방법은 전후 `scripts/scorecard.py`와 관련 시험 실제 출력이다.
7. **다른 분야 동작(T8).** 사건·분야 낱말 없이 동작한다는 근거를 적는다. 평가 측은 서로 다른 분야의 합성 참고자료 2세트로 같은 동작을 확인한다.

## 4. 보호 시험(평가 측이 설계 회신 전에 고정 — 구현 측은 고치지 않는다)
| 시험 | 내용 | 고정 시 |
|---|---|---|
| T6 참고자료 위계 | 공식 미발견 인용이 참고자료에 있어도 `official_status=OFFICIAL_NOT_FOUND`가 유지되고, `reference_status`만 SUPPORTED가 된다. 제목 부분 일치·미독 파일로는 SUPPORTED가 되지 않는다 | strict xfail(+ 지금도 맞아야 하는 대조는 통과) |
| T7 대조율 표시 | `claim_coverage`의 분모 = 대조 대상 주장 수, 상한 초과 주장은 `unreviewed` 사유와 함께 분모에 남음, 화면 표시 값 = 데이터 값 | strict xfail |
| T8 다른 분야 동작 | 분야가 다른 합성 자료 2세트에서 같은 절차·같은 구조의 결과 | strict xfail |
| T9 `LOCAL_ONLY` 외부 호출 0 | `LOCAL_ONLY`·QUICK에서 주장 단위 경로를 포함해 공급자 호출 0. 참고자료 발췌도 서면과 같은 마스킹·`inspect_request`를 지남 | 지금 통과해야 하는 부분은 통과, 새 경로 부분은 strict xfail |
| 요청 본문 스키마 | 허용 키 밖이면 전송 안 함(fail-closed), 사람 키 없음 — 가짜 공급자로 `LLMRouter.run` 경로에서 확인 | strict xfail |

- **고정 완료(2026-10-07):** `tests/acceptance/test_f3_protected.py` — 통과 9(지금도 맞아야 하는 대조·하네스 전제), strict xfail 6(T6 SUPPORTED, T7 상한 사유·화면 표시, T8 두 분야 SUPPORTED, T9 주장 단위 경로, 스키마).
  - 하네스: 실제 `VerificationPipeline`·`LLMRouter.run`에 가짜 Drive·가짜 공급자만 붙인다. 공식 판례 조회는 '조회 성공·결과 없음'으로 대역한다.
  - 가짜 공급자는 참고자료 대조 요청에 빈 의견을 준다. 그래서 SUPPORTED는 인용 동일성 대조(3절 1)에서 와야 한다.
  - 시험이 쓰는 이름은 이미 정해진 것뿐이다: `reference_status` 값, `claim_coverage` 키, `REASON_BUDGET_EXCEEDED`·허용 키 4개(19b 5.2·6.1), 화면 'N건 중 M건'(또는 'M/N').
  - 허용 목록 밖 키의 fail-closed 단위 시험: 설계 메모(PR #32) 5.2의 `validate_claim_request_payload`(review.py, bool 반환) 대상 strict xfail 10건(2026-10-07 추가).
- T1~T5(F1·F2), T2r·T6a(F1 화면), T10·T11(FT)은 계속 통과해야 한다.

## 5. 구현 수용 기준(회신 뒤 구현 PR에서 평가 측이 확인)
- T6~T9와 스키마 시험이 XPASS가 된다. strict XPASS 실패는 예정된 것이다. 보고에 'XPASS(strict) 외 실패 0'으로 적고, 표시는 평가 측이 지운다.
- 고정 시험 dev 81.7 / holdout 79.2 / 오탐 0이 그대로이고, probe·회귀 게이트에 회귀가 없다. 새 `rule_id`·`FindingType`은 0이다.
- 평가 측이 F3 측정 SHA에서 연락처·주민등록번호 필수 게이트 0/0/0을 다시 잰다.
- 평가 측 `verify_all` 전체 모드 종료 0(수용 SHA).
- 온라인(사용자 실행, 서면9 같은 조건)
  - 기존 통과 항목에서 새 실패가 0이어야 한다.
  - RAG-1(Drive 규정 정면 모순, 참고 의견)이 통과해야 한다. FT 릴리스 때 처음 통과했으며 아직 재현을 확인하지 않았다.
  - FP-1(Drive 내부 규정을 '존재하지 않는 법령'으로 알리지 않음)이 통과해야 한다.
  - **RAG-2(모순이 finding 목록에 SUSPICIOUS·CONTRADICTED로 오름)는 D4(승격 없음)와 맞지 않는다.** F3 수용 기준에서 뺀다. 명세는 비교 가능성을 위해 바꾸지 않고 '설계상 실패'로 기록한다.
- 릴리스: 이번 FT 판정에 쓴 봉인 세트는 다시 쓰지 않는다(AGENT_ROLES 4절). F3 릴리스 전에 **새 봉인 세트**를 새 격리 세션에서 만든다.

## 6. 보고(PR 3줄 코멘트 + 본문)
- 바꾼 것·남은 것·'검토 요청'
- 전후 `python scripts/scorecard.py` 출력 원문, 관련 시험 pytest 요약 줄 원문. 요약만 적지 않는다.
- 확인하지 못한 것: 실제 Drive 연동·모델 대조 품질·화면 사용성은 오프라인에서 재지 못한다고 적는다.

## 7. 금지
- 회신 전 F3 코드 작성
- 보호 경로(`tests/acceptance/**`·`tests/fixtures/**`·`scripts/` 평가 도구·`docs/scorecards/**`) 수정, skip·xfail 표시 변경
- 참고자료 전용 외부 전송 설정 신설, 전송 전 검사 우회 경로
- 자료 이름·폴더·분야 낱말 목록 하드코딩, 사건 고유 값 하드코딩
- 참고 의견의 심각도·finding 승격(D4), `official_status`를 참고자료로 덮어쓰기
- 새 `rule_id`·`FindingType`, 작업 커밋에서 버전 변경
