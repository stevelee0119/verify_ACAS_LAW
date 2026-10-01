# TK-18 보고서 머리의 AI 작성 판정이 다수결을 따르지 않는다 (TK-11 후속)
- 유형: 정책 이행 누락(같은 정책이 두 곳) · 기준 커밋: cf7c739 · 작성: evaluator 2026-10-01

## 증상·증거
서면8 사용자 온라인 보고서(cf7c739): 모델 3개(PARTIAL 2, FULL 1)가 모두 AI 쪽이라 `ai_detector_result.verdict`는 `AI_PARTIAL_GENERATION`(`MAJORITY_AI_CONSENSUS`)이고 문서 단위 finding(`AI_AUTHORSHIP_LIKELY`, MEDIUM, "문서 일부의 AI 작성 가능성")도 올랐다. 그런데 보고서 머리 점수축 `scores.axes.ai_authorship.documents[0].verdict`는 **`UNCERTAIN`**이다.
원인: `verification_engine/scoring.py`의 `unified_authorship`에 옛 규칙("객관적 흔적 0건이면 확정 판정을 `UNCERTAIN`으로 제한")이 남아 있다. TK-11은 `ai_document_detector.py`만 고쳤다. 사용자는 한 화면에서 서로 다른 판정을 본다.

## 수용 기준
- `python -m pytest tests/acceptance/test_ai_majority_rule.py` — `test_axis_follows_majority_verdict_without_traces` 2건(strict xfail)이 해결(XPASS).
- 축의 `involvement`(`NO_OBJECTIVE_TRACES`)·`objective_traces`는 판정과 별도 항목으로 계속 표시한다(`test_axis_keeps_involvement_separate_from_verdict`).
- 정답지는 "AI 생성 가능성 높음"을 기대한다. 이 서면은 모델 의견이 PARTIAL 다수여서 규칙상 `PARTIAL`("문서 일부")이다. 판정 문구의 표현(`PARTIAL`을 '높음'으로 읽을지)은 사용자가 정한다. 구현 에이전트는 라벨을 임의로 바꾸지 않는다.
- 같은 정책이 코드의 다른 곳에 더 있는지 `grep`으로 확인하고 결과를 커밋 메시지에 적는다(`objective_traces`·`HELD_NO_OBJECTIVE_TRACE` 참조 지점).
