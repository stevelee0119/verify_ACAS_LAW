"""v2 Phase 8: AI 응답 잔재 신호는 범주별로 근거 문구와 함께 '참고용, 확정 불가'로 낸다."""
from __future__ import annotations

from packages.verification_engine.ai_residue import scan_residue


def categories(text):
    return {r.category: r for r in scan_residue(text)}


def test_objective_residues_are_found_with_their_text():
    text = ("물론입니다! 요청하신 내용으로 소장을 작성해 드리겠습니다.\n### 청구취지\n**1. 사건의 개요**\n"
            "제 지식 기준일 현재 관련 판례는 다음과 같습니다.\n이 답변은 법률 자문을 대체하지 않습니다. 궁금한 점은 말씀해 주세요!")
    found = categories(text)
    assert {"CHATBOT_PREFACE", "MARKDOWN", "KNOWLEDGE_CUTOFF", "DISCLAIMER"} <= set(found)
    assert all(found[k].objective for k in ("CHATBOT_PREFACE", "MARKDOWN", "KNOWLEDGE_CUTOFF", "DISCLAIMER"))
    assert "### 청구취지" in found["MARKDOWN"].matches


def test_style_signals_are_weak_and_need_several_kinds():
    assert "CLICHE" not in categories("결론적으로 원고의 청구는 이유 없다.")
    found = categories("결론적으로 중요한 점은 이것이라고 할 수 있습니다. 핵심은 재량이다.")
    assert found["CLICHE"].objective is False


def test_ordinary_brief_has_no_residue():
    text = ("원고는 피고의 처분이 재량권을 일탈·남용하였다고 주장합니다. 대법원 2006. 12. 21. 선고 2006두16274 판결 "
            "참조. 따라서 이 사건 처분은 취소되어야 합니다. 원고 소송대리인 변호사 ○○○ (인)")
    assert scan_residue(text) == []
