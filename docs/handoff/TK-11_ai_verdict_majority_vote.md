# TK-11 AI 작성 판정: 만장일치가 아니라 다수결
- 유형: 정책 변경(사용자 결정 2026-09-30) · 기준 커밋: 4ad64a7 · 작성: evaluator 2026-09-30
- 대상: `packages/verification_engine/ai_document_detector.py` `_combine_model_verdicts` (제품 코드, 구현 에이전트 소관)

## 결정
문서의 AI 작성 판정은 모델 의견의 **다수결**로 정한다. 지금은 라벨이 모두 같아야 합의(AGREE)로 보고, 갈리면(PARTIAL과 FULL 등) 유보(HELD_DISAGREEMENT)하며, 합의여도 문체 경보·가상 인용 군집·객관적 흔적 중 하나가 없으면 유보(HELD_NO_OBJECTIVE_TRACE)한다.

## 해석(사용자 확인 대상)
사용자 지시는 "만장일치가 아니라 다수결로 결정하는 규칙"이다. 평가 에이전트는 **다수결이 판정을 정하고, 객관적 흔적 부재는 판정을 막지 않는 것**으로 해석했다.
- 이유: 서면7은 모델 3개가 모두 AI 쪽(FULL 2, PARTIAL 1)인데 객관적 흔적이 없어 유보됐다. 라벨 단위로만 다수를 세고 흔적 요건을 남겨 두면 서면7은 그대로 `UNCERTAIN`이라 변경의 효과가 없다.
- 대안 해석(흔적 요건 유지)을 택하려면 아래 시험 `test_majority_*` 중 "흔적 없음" 경우의 기대값을 `UNCERTAIN`으로 바꾸면 된다. 사용자가 정한다.
- 기존 안전장치는 판정과 별도 축으로 남긴다: `involvement`(`NO_OBJECTIVE_TRACES`/`TRACES_FOUND`), `objective_traces`, `verdict_distribution`을 보고서에 계속 싣는다. 판정 문구는 "모델 다수 의견(참고)"이며 작성 주체의 단정이 아니다(`authorship.note` 유지).

## 규칙(명세)
응답한 모델 수를 n이라 한다(응답 못 한 모델은 세지 않는다). `HUMAN_AUTHORED_LIKELY`는 지금처럼 `UNCERTAIN`으로 바꿔 센다.
1. AI 표 = `AI_FULL_GENERATION_LIKELY` + `AI_PARTIAL_GENERATION`. AI 표가 n의 **과반(n/2 초과)**이면 문서 판정은 AI 쪽이다. 아니면 `UNCERTAIN`.
2. AI 쪽일 때 라벨: `AI_FULL_GENERATION_LIKELY` 표가 n의 과반이면 FULL, 아니면 `AI_PARTIAL_GENERATION`.
3. n=1이면 지금 규칙(규칙 판정으로 상한)을 유지한다. n=2는 둘 다 AI여야 AI 쪽이다(과반 정의에 따라).
4. `signals["decision_rule"]`은 AI 다수결이면 `MAJORITY`로 시작하는 값, 유보면 `HELD_`로 시작하는 값으로 둔다. `verdict_distribution`·`llm_agreement` 신호는 유지한다.

## 고쳐야 하는 기존 시험(`tests/`, 구현 에이전트가 새 규칙에 맞게 고친다)
- `tests/test_verification_regressions.py::test_unanimous_models_without_objective_trace_hold_and_explain_score_vs_confidence` — 만장일치 FULL + 흔적 없음이 `HELD_NO_OBJECTIVE_TRACE`라는 기대가 새 규칙과 충돌한다.
- `tests/test_case6_military_secret_defense_opinion.py::test_cluster_controls` — (UNCERTAIN, FULL, FULL) + 군집 없음 → `UNCERTAIN` 기대가 충돌한다.
- `tests/test_case5_medical_malpractice_complaint.py`, `tests/test_case6_...`의 `decision_rule == "MAJORITY_AI_CONSENSUS"`, `llm_agreement == "MAJORITY_AI_AGREE"` 기대(이름을 바꾸면 함께 고친다).
- 이 시험을 고칠 때 기대값만 바꿔 통과시키지 않는다. 바뀐 규칙에 맞는 새 양성·대조군을 넣는다.

## 수용 기준
- `python -m pytest tests/acceptance/test_ai_majority_rule.py` 통과(평가 에이전트 작성, 현재는 미해결 항목이 strict xfail). 고친 뒤 XPASS(strict)로 실패하면 평가 에이전트가 xfail 표시를 지운다.
- 서면7 온라인 보고서 재채점(사용자가 새 보고서를 주면 `scripts/score_report.py`)에서 AI-1(문서 판정이 AI 쪽)이 통과한다. 오프라인으로는 모델 경로를 재지 못한다.
- 고정 시험(`score_gate`) 점수 하락·오탐 증가 없음.

## 사용자 확인(2026-10-03)
평가 측 해석을 승인했다: 다수결이 판정을 정하고 객관적 흔적 부재는 판정을 막지 않는다. 단정 방지 장치(문구 '모델 다수 의견(참고)', `involvement`·`objective_traces`·`verdict_distribution` 표시)는 유지한다. 대안 해석(흔적 요건 유지)은 택하지 않았다.
