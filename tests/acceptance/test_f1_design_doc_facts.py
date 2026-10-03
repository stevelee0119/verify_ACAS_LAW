"""[평가 에이전트 소관] F1 설계 준비 문서(`docs/handoff/requests/22_f1_design_prep.md`)의 사실 검사 (TK-47).

7B(9506481)·7C(b26754e)가 연속으로 현행 모델과 맞지 않는 문서를 냈다(97개 중 85개만 열거·없는 이름 2개·`FindingWorkflow`를 '존재하지 않는 클래스'로 서술).
문서 품질 자체는 측정하지 않고, 코드에서 기계적으로 확인되는 사실만 본다. 지금은 strict xfail(알려진 미해결, 7D R7D-C)이며
문서가 고쳐지면 XPASS가 되고 평가 측이 표시를 지운다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from packages.common.enums import FindingType

DOC = Path(__file__).resolve().parents[2] / "docs" / "handoff" / "requests" / "22_f1_design_prep.md"
REASON = "TK-47 알려진 미해결(7D R7D-C): F1 설계 문서가 현행 코드와 맞지 않는다"


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


@pytest.mark.xfail(strict=True, reason=REASON + " — FindingType 97개 전수 열거")
def test_design_doc_lists_every_finding_type():
    tokens = set(re.findall(r"\b[A-Z][A-Z0-9_]{3,}\b", _doc()))
    missing = sorted({m.name for m in FindingType} - tokens)
    assert not missing, f"문서에 없는 FindingType {len(missing)}개: {missing[:10]}…"


@pytest.mark.xfail(strict=True, reason=REASON + " — 현행 워크플로 모델(FindingWorkflow·ReviewDraft·ReviewRevision) 명시")
def test_design_doc_names_the_current_workflow_models():
    doc = _doc()
    required = ["FindingWorkflow", "ReviewDraft", "ReviewRevision", "workflow_state", "decision", "revision", "/workflow"]
    missing = [r for r in required if r not in doc]
    assert not missing, f"문서에 없는 현행 모델·필드: {missing}"


@pytest.mark.xfail(strict=True, reason=REASON + " — 실존하는 클래스를 '존재하지 않는다'고 서술")
def test_design_doc_does_not_deny_classes_that_exist():
    doc = _doc()
    for name in ("FindingWorkflow", "ReviewDraft", "ReviewRevision"):
        assert not re.search(rf"{name}[^.\n]{{0,30}}(존재하지 않|없는|가짜)|(존재하지 않|가짜)[^.\n]{{0,30}}{name}", doc), f"{name}는 apps/api/workspace.py에 있다"
    assert not re.search(r"NOT_STARTED[^.\n]{0,20}가짜|가짜[^.\n]{0,20}NOT_STARTED", doc), "NOT_STARTED는 workflow_state의 실제 기본값이다"
