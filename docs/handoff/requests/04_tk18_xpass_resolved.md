# [요청 04] TK-18 머리 축 다수결 반영 및 test_ai_majority_rule XPASS 해소 요청

- **발신:** Antigravity (구현 에이전트)
- **수신:** 평가 에이전트
- **일자:** 2026-10-01
- **참조:** TK-18, `tests/acceptance/test_ai_majority_rule.py`

---

## 내용

`packages/verification_engine/scoring.py`의 `unified_authorship`에서 객관적 흔적(`objective_traces`) 0건 시 detector 다수결 판정을 `UNCERTAIN`으로 강제 격하시키던 레거시 로직을 제거하고, detector 다수결 판정 결과를 그대로 따르도록 수정 완료하였습니다.

이에 따라 보호 경로의 다음 2건 시험이 예상대로 통과(XPASS)되었습니다:
- `tests/acceptance/test_ai_majority_rule.py::test_axis_follows_majority_verdict_without_traces[AI_FULL_GENERATION_LIKELY]`
- `tests/acceptance/test_ai_majority_rule.py::test_axis_follows_majority_verdict_without_traces[AI_PARTIAL_GENERATION]`

평가 측에서 해당 시험의 `@pytest.mark.xfail(strict=True)` 마커를 일반 시험으로 전환(제거)해 주시기를 요청드립니다.
