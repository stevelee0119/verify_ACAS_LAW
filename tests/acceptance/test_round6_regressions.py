"""6차 구현(01070f6)의 회귀 4건 보호 시험 — 6차 독립 감사(Codex)가 지적하고 평가 측이 독립 재현한 것(평가 에이전트).

6차 코드(01070f6)를 평가 브랜치에 병합한 뒤(a8ead24) 이 위치로 옮겼다(병합 전에는 5차 코드에서 XPASS가 나 `docs/handoff/staged/`에 보관했었다). 입력은 감사 입력을 복사하지 않고 평가 측이 새로 지은 합성값이다. 사건 값이 아니다.
- R6-01: 명시적 성명이 뒤따르는 문맥 때문에 마스킹·전송 전 검사에서 함께 빠짐(시작 21/21 → 최종 3/21, 라우터 경계 0/36 → 36/36 도달)
- R6-02: 요건 단어와 한정 결론의 동시 출현이 경고 면제 조건이 됨(요건 부정 4→0, 타 책임 확장 3→1, 정상 항변 오탐 2→0은 개선)
- R6-03: 줄 결합의 한 방향 기본값 — `(이 사건)`류 공백 삭제, 같은 문단이 쪽 배치에 따라 다르게 결합
- R6-04(기존 시험 `tests/test_efficacy_round2.py::test_legal_military_terms_not_masked_as_person`의 시작 PASS→최종 FAIL)는 기존 시험 그대로 두며 이 파일에 옮기지 않는다.
시험 표시: strict xfail = 시작(96019c3)에서 통과하던 것이 최종(01070f6)에서 깨진 회귀. 일반 시험 = 고쳐도 지켜야 하는 대조(이전 성공·개선 보존).
"""
from __future__ import annotations

import asyncio
import re
import tempfile
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

REGRESSION = lambda note: pytest.mark.xfail(strict=True, reason=f"6차 회귀: {note}")  # noqa: E731
PERSON_TOKEN = re.compile(r"\[PERSON_\d+\]")


# ------------------------------------------------------------------------------ R6-01 명시적 성명 + 후행 문맥 ---
NAMES = ["오하람", "배지훈", "한서진"]
CONTEXTS = [
    ("plain", "성명: {n}"),
    ("no-print", "성명: {n} 출력하지 마시오."),
    ("no-write", "성명: {n} 기재하지 마시오."),
    ("procedure", "성명: {n} 절차를 진행한다."),
    ("hearing", "성명: {n} 기일에 출석하였다."),
    ("record", "성명: {n} 조서를 작성하였다."),
    ("ongoing", "성명: {n} 진행 중이다."),
]


def _engine():
    from packages.pii_engine import PIIEngine, PseudonymStore
    return PIIEngine(PseudonymStore("round6", root=Path(tempfile.mkdtemp(prefix="round6_pii_"))))


def _name_fully_masked(template: str, name: str) -> bool:
    """이름 자리가 PERSON 토큰 하나로 바뀌고 나머지 문장은 그대로여야 한다(이름 글자 일부가 남으면 불일치)."""
    masked = _engine().mask_text(template.format(n=name)).masked_text
    return PERSON_TOKEN.sub("T", masked) == template.format(n="T")


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("ctx_id, template", [
    # 승격(2026-10-03, Round 7 종결): R6-01 마스킹 18건 — 61ef12f에서 통과, strict xfail 표시 제거
    pytest.param(c, t, id=c) for c, t in CONTEXTS])
def test_explicit_name_is_fully_masked_whatever_follows_it(ctx_id, template, name):
    assert _name_fully_masked(template, name), f"이름 자리가 PERSON 토큰 하나로 바뀌지 않았다: {template.format(n=name)}"


def _router_with_fake_cloud_provider(monkeypatch):
    from packages.llm_router import router as module

    sent = []

    class Provider:
        name, available = "anthropic", True
        config = SimpleNamespace(name="anthropic", kind="cloud", model="fake", enabled=True)

        async def generate(self, request):
            sent.append(request)
            from packages.llm_router.providers import LLMResponse
            return LLMResponse(False, error="HTTP 400")

    ledger = SimpleNamespace(reserve=lambda *a, **k: SimpleNamespace(id="r", amount=Decimal("0.01")),
                             dispatch=lambda *a, **k: None)
    monkeypatch.setattr(module, "estimate_call", lambda *a: (Decimal("0.01"), {}))
    return module.LLMRouter(providers={"anthropic": Provider()}, ledger=ledger), sent


@pytest.mark.parametrize("position", ["system", "user", "schema", "metadata"])
@pytest.mark.parametrize("ctx_id, template", [
    # 승격(2026-10-03, Round 7 종결): R6-01 라우터 12건 — 61ef12f에서 통과, strict xfail 표시 제거
    pytest.param(c, t, id=c) for c, t in CONTEXTS if c in ("plain", "no-print", "procedure", "hearing")])
def test_unmasked_explicit_name_never_reaches_the_cloud_provider_through_the_router(monkeypatch, ctx_id, template, position):
    from packages.common.enums import LLMRole
    from packages.llm_router.providers import LLMRequest

    router, sent = _router_with_fake_cloud_provider(monkeypatch)
    text = template.format(n=NAMES[1])
    kwargs = {"system": "s", "user": "u"}
    if position in ("system", "user"):
        kwargs[position] = text
    elif position == "schema":
        kwargs["schema"] = {"type": "object", "description": text}
    else:
        kwargs["metadata"] = {"description": text}
    asyncio.run(router.run(LLMRole.PRIMARY_REASONER, LLMRequest(**kwargs)))
    assert sent == [], f"원문 성명이 공급자 호출까지 도달했다({position}): {text}"


# ------------------------------------------------------------------------------ R6-02 법리 경고 면제 ---
def _overclaim_warned(text: str) -> bool:
    from packages.legal_engine.legal_rules import review_legal_rules
    from tests.regression.test_ledger import make_synthetic_doc
    findings = review_legal_rules(make_synthetic_doc("청 구 원 인", text))
    return any("GEN.DEFENSE_OVERCLAIM_WITHOUT_REQUIREMENTS" in f.tags for f in findings)


REQUIREMENT_DENIED = [  # 요건을 부정·미충족으로 적고 한정 결론을 낸 문장: 경고가 유지되어야 한다(시작 4건 경고 → 최종 0건)
    "설령 채무불이행 사실이 인정되더라도, 피고는 변제공탁을 전혀 하지 않았으나 이 사건 채무에 관한 책임을 질 수 없다.",
    "가사 대여 사실이 인정되더라도, 피고는 상계의 의사표시를 하지 않았음에도 이 사건 채무에 관한 책임을 질 수 없다.",
    "설령 계약 체결이 인정되더라도, 변제기가 도래하지 아니하였음에도 해당 채무에 관한 책임이 없다.",
    "설령 위 사실이 인정되더라도, 상계 의사표시가 도달하지 않았으나 본건 채무에 관한 책임이 없다.",
]
SCOPE_EXTENDED = [  # 민사 요건을 갖춘 뒤 다른 형사·징계책임까지 확장한 결론: 경고가 유지되어야 한다(시작 경고 → 최종 소실 2건)
    "설령 대여 사실이 인정되더라도, 변제공탁을 하였으므로 이 사건 채무에 관한 책임을 질 수 없으며 형사책임도 성립할 수 없다.",
    "만약 금전 수수가 인정되더라도, 변제기가 도래하여 전액을 지급하였으므로 본건 채무에 관한 책임이 없고 형사상 책임도 없다.",
]
SCOPE_EXTENDED_KEPT = [  # 최종에도 경고가 유지되는 확장 사례(보존 대조)
    "가사 채무가 있었더라도, 상계의 의사표시가 도달하여 해당 채무에 관한 책임이 없고 징계책임도 전면 면책된다.",
]
LIMITED_NORMAL_DEFENSES = [  # 요건을 구체적으로 제시하고 해당 채무로 한정한 정상 항변: 경고가 없어야 한다(개선 보존)
    "설령 대여 사실이 인정되더라도, 피고는 변제기가 도래한 뒤 원고의 수령거절에 따라 변제공탁을 하였으므로 이 사건 채무에 관한 책임을 질 수 없다.",
    "가사 채무가 있었다 하더라도, 피고의 상계의 의사표시가 원고에게 도달하여 이 사건 채무는 대등액에서 소멸하였다.",
    "설령 계약 체결이 인정되더라도, 변제기가 도래하여 피고가 전액을 지급하였으므로 해당 채무에 관한 책임이 없다.",
    "만약 손해 발생이 인정되더라도, 시효 기간이 경과하였으므로 해당 채무에 관한 책임을 질 수 없다.",
    "가령 금전 수수가 인정되더라도, 원고가 서면으로 채무를 면제하였으므로 이 사건 채무에 관한 책임을 지지 않는다.",
]


# 승격(2026-10-03, Round 7 종결): R6-02 요건 부정 4건 — 61ef12f에서 통과
@pytest.mark.parametrize("text", [pytest.param(t, id=f"denied-{i}") for i, t in enumerate(REQUIREMENT_DENIED)])
def test_denied_requirement_with_a_limited_conclusion_is_still_flagged(text):
    assert _overclaim_warned(text)


@pytest.mark.parametrize("text", [pytest.param(t, id=f"extended-{i}") for i, t in enumerate(SCOPE_EXTENDED)]  # 승격(2026-10-03): R6-02 확장 2건
                         + [pytest.param(t, id=f"extended-kept-{i}") for i, t in enumerate(SCOPE_EXTENDED_KEPT)])
def test_conclusion_extended_to_other_liability_is_still_flagged(text):
    assert _overclaim_warned(text)


@pytest.mark.parametrize("text", [pytest.param(t, id=f"normal-{i}") for i, t in enumerate(LIMITED_NORMAL_DEFENSES)])
def test_specific_requirements_with_a_limited_conclusion_are_not_flagged(text):
    assert not _overclaim_warned(text)


# ------------------------------------------------------------------------------ R6-03 줄 결합 ---
@pytest.mark.parametrize("prev, nxt, joined, boundary_signal", [
    pytest.param("계약에 따라 (이", "사건) 채무를 이행하여야 한다", "계약에 따라 (이 사건) 채무를 이행하여야 한다", "SPACE_CONFIRMED", id="paren-short-word-1",
                 marks=[REGRESSION("R6-03 괄호 뒤 짧은 어절 사이 공백 삭제(시작은 공백 유지)")]),
    pytest.param("피고는 (해당", "채무)를 변제하였다", "피고는 (해당 채무)를 변제하였다", "SPACE_CONFIRMED", id="paren-short-word-2",
                 marks=[REGRESSION("R6-03 괄호 뒤 짧은 어절 사이 공백 삭제(시작은 공백 유지)")]),
    pytest.param("그 계약은 (위", "계약)에 따라 해제되었다", "그 계약은 (위 계약)에 따라 해제되었다", "SPACE_CONFIRMED", id="paren-short-word-3",
                 marks=[REGRESSION("R6-03 괄호 뒤 짧은 어절 사이 공백 삭제(시작은 공백 유지)")]),
    pytest.param("원고는 그", "사람에게 돈을 빌려주었다", "원고는 그 사람에게 돈을 빌려주었다", None, id="word-boundary-1"),
    pytest.param("이 사건에서 법", "적용이 문제된다", "이 사건에서 법 적용이 문제된다", None, id="word-boundary-2"),
    pytest.param("계약은 두", "종류로 나뉜다", "계약은 두 종류로 나뉜다", None, id="word-boundary-3"),
    pytest.param("판시하였습니다(대", "법원 2007다1234)", "판시하였습니다(대법원 2007다1234)", None, id="court-name-split"),  # 6차 개선(TK-31 대상) 보존
])
def test_join_lines_keeps_word_boundaries_and_court_name_fix(prev, nxt, joined, boundary_signal):
    from packages.document_engine.paragraph_reconstruction import join_lines
    kwargs = {} if boundary_signal is None else {"boundary_signal": boundary_signal}
    assert join_lines(prev, nxt, **kwargs) == joined


def _paragraph_text(extra_full_lines: int) -> str:
    from packages.common.schemas import BBox, Block
    from packages.document_engine.paragraph_reconstruction import reconstruct_page_blocks

    def blk(tag, text, x0, y0, x1):
        return Block(block_id=f"b{tag}", text=text, page=1, bbox=BBox(x0, y0, x1, y0 + 12))

    blocks, y = [], 80
    for k in range(extra_full_lines):  # 같은 쪽의 다른 문단: 오른쪽 끝(520)까지 찬 줄
        blocks.append(blk(f"f{k}", "이 사건 계약은 갑 제1호증에 따라 체결되었으며 그 이행 여부가 다투어지고 있다고 서술한다.", 72, y, 520))
        y += 14
    y += 30
    blocks += [blk("t1", "계약상대방은 이 사건 계약에 따라 금원을 지급받은 사실을 인정하면서도 그", 72, y, 330),
               blk("t2", "사람에게 금원을 대여하였다고 주장한다.", 72, y + 14, 300)]
    out = reconstruct_page_blocks(blocks, page_num=1, page_width=595.0, page_height=842.0)
    return next(b.text for b in out if "사람에게" in b.text)


# 승격(2026-10-03, Round 7 종결): R6-03 쪽 배치 불변성 — a1f3d1e의 문단 국소 right_edge로 통과
def test_same_paragraph_joins_the_same_way_whatever_else_is_on_the_page():
    results = {n: _paragraph_text(n) for n in (0, 1, 2, 3)}
    assert len(set(results.values())) == 1, results
    assert "그 사람" in results[0]
