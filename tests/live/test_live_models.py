"""실제 모델 호출 통합 테스트(J2·R10). API 키가 둘 이상 있는 CI 러너에서만 돈다.

- J2: 모델의 사실 모순 지적은 결정론 재계산 결과에 붙거나(확인) 사람 확인 항목으로 남는다. 모델이 '모순 없음'을
  확인한 문장은 모순 지적이 되지 않는다. 모델 근거는 {kind, text}로 구조화된다.
- R10: 요약 점수의 AI 판정 축과 문서별 AI 판정이 같다(문서마다 판정 하나).
"""
from __future__ import annotations

import os

import pytest

from packages.common.enums import FindingType
from tests.live.conftest import record
from tests.live.test_live_sources import _pdf, _run

KEYS = [k for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY") if os.getenv(k)]


@pytest.fixture(scope="module")
def models(live_env):
    if len(KEYS) < 2:
        pytest.fail(f"모델 API 키가 {len(KEYS)}개뿐이라 교차 판정을 실연동으로 확인할 수 없다(미확인으로 남긴다)")
    return KEYS


@pytest.fixture(scope="module")
def analysed(tmp_path_factory, registry, models):
    tmp = tmp_path_factory.mktemp("models")
    # 민사: 표 합계 오류(1,200,000 + 3,400,000 = 4,600,000인데 5,600,000)와 AI 응답 잔재가 있는 합성 서면
    path = _pdf(tmp, "j2.pdf", "준비서면(합성 시험 문서)", [[
        "1. 원고는 2023. 3. 15. 작업 중 사고로 부상을 입었다.",
        "2. 치료비 1,200,000원, 일실수입 3,400,000원, 합계 5,600,000원을 청구한다.",
        "3. 입원 기간은 2023. 3. 16. ~ 2023. 3. 20.(21일간)이다.",
        "도움이 되셨길 바랍니다. 추가로 궁금한 점이 있으면 말씀해 주세요.",
    ]])
    return _run(tmp, registry, path)


@pytest.mark.live_item("J2")
def test_J2_model_remarks_are_reconciled_with_deterministic_recalculation(analysed):
    detector = analysed.ai_detector_result or {}
    opinions = (detector.get("signals") or {}).get("llm_opinions") or []
    kinds_ok = all(r.get("kind") in ("style", "contradiction", "confirmation")
                   for o in opinions for r in o.get("structured_reasons") or [])
    deterministic = [f for f in analysed.findings if f.type == FindingType.ARITHMETIC_MISMATCH]
    attached = sum(len((f.confidence_features or {}).get("model_remarks") or []) for f in deterministic)
    open_remarks = [f for f in analysed.findings if f.type == FindingType.MODEL_FACT_REMARK]
    confirmations = (detector.get("signals") or {}).get("model_confirmations") or []
    leaked = [f for f in open_remarks if any(c.split("] ", 1)[-1][:20] in f.title for c in confirmations)]
    record("J2", prepared=2, detected=len(deterministic), false_positive=len(leaked),
           summary=(f"모델 {len(opinions)}개 응답, 결정론 재계산 {len(deterministic)}건, 모델 지적 연결 {attached}건, "
                    f"사람 확인으로 남은 지적 {len(open_remarks)}건, 확인 문장의 오분류 {len(leaked)}건"),
           cases=[{"provider": o.get("provider"), "verdict": o.get("verdict"),
                   "kinds": [r.get("kind") for r in o.get("structured_reasons") or []]} for o in opinions])
    assert opinions and kinds_ok and len(deterministic) >= 2 and not leaked
    assert all("재계산으로 확인하지 못했" in f.detail for f in open_remarks)


@pytest.mark.live_item("R10")
def test_R10_axis_verdict_matches_document_verdict(analysed):
    from packages.verification_engine.scoring import unified_authorship

    detector = analysed.ai_detector_result or {}
    unified = unified_authorship(analysed)
    ai_findings = [f for f in analysed.findings if f.type in (FindingType.AI_AUTHORSHIP_LIKELY,
                                                              FindingType.AI_FULL_GENERATION_SUSPECTED)
                   and not f.advisory_only]
    consistent = unified["verdict"] == detector.get("verdict") and (
        (unified["verdict"] == "UNCERTAIN") == (not ai_findings))
    record("R10", prepared=1, detected=int(consistent),
           summary=f"문서 판정 {detector.get('verdict')} / 축 판정 {unified['verdict']} / 관여 {unified['involvement']}",
           cases=[unified])
    assert consistent
