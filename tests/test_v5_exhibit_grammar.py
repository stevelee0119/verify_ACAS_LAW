"""v5 3-1: 호증 표기 문법, 속성 기반 왕복 시험, 대조군(정상 서면) 증거 오탐 0건.

원인(재현: 테스트셋 v1 TC-01): 두 단으로 짠 입증방법 목록이 한 줄로 읽혀('갑 제2호증항고장 접수증 갑 제3호증…')
줄의 첫 호증만 목록으로 잡혔고, 나머지(제3·5·7호증)를 결번·목록 누락으로 판정했다. 또 '갑 제2, 3호증',
'갑 제4·7호증', '갑 제4호증의 1, 2', '피고인 증 제1호증' 표기를 읽지 못했다.
문서·사건·금액은 시험용으로 새로 지었다.
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from packages.claim_engine.evidence_consistency import check_document, exhibit_rows
from packages.claim_engine.exhibits import canonical, parse_exhibits, render, split_items

PARTIES = ["갑", "을", "병", "을가", "을나", "증", "피고인증", "검증"]


# --- 문법 ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("text, expected", [
    ("갑 제5호증의 1 내지 3", [("갑", 5, (1, 2, 3))]),
    ("갑 제4호증의 1, 2", [("갑", 4, (1, 2))]),
    ("갑 제2, 3호증", [("갑", 2, ()), ("갑", 3, ())]),
    ("갑 제4·7호증", [("갑", 4, ()), ("갑", 7, ())]),
    ("갑 제4ㆍ7호증", [("갑", 4, ()), ("갑", 7, ())]),
    ("차용증갑 제2호증의 1, 2", [("갑", 2, (1, 2))]),
    ("갑 제2 내지 4호증", [("갑", 2, ()), ("갑", 3, ()), ("갑", 4, ())]),
    ("갑 제2호증, 제3호증", [("갑", 2, ()), ("갑", 3, ())]),
    ("갑 제6호증 및 제8호증", [("갑", 6, ()), ("갑", 8, ())]),
    ("을가 제1호증", [("을가", 1, ())]),
    ("증 제7호 압수조서", [("증", 7, ())]),
    ("피고인 증 제2호증의 1", [("피고인증", 2, (1,))]),
    ("갑제３호증의１～２", [("갑", 3, (1, 2))]),
])
def test_grammar_reads_every_notation(text, expected):
    assert canonical(parse_exhibits(text)) == sorted(expected)


@pytest.mark.parametrize("text", ["군인사법 제56조 제2호", "보증 제2호 계약", "제3호증", "같은 조 제1호",
                                  "위 사실을 제3호증", "검증 결과 제2호"])
def test_statute_items_and_partyless_numbers_are_not_exhibits(text):
    assert parse_exhibits(text) == []


def test_two_column_line_splits_into_each_exhibit_with_its_name():
    items = split_items("갑 제2호증항고장 접수증 갑 제3호증항고결정서 및 송달증명")
    assert [(ref["number"], name) for ref, name in items] == [(2, "항고장 접수증"), (3, "항고결정서 및 송달증명")]
    shared = split_items("갑 제2, 3호증 각 사실확인서")
    assert [(ref["number"], name) for ref, name in shared] == [(2, "사실확인서"), (3, "사실확인서")]


# --- 속성 기반 왕복 시험: 무작위 구조 → 여러 표기 → 파싱 → 같은 구조 ----------------------------------
def _random_exhibits(rng):
    exhibits = {}
    for _ in range(rng.randint(1, 8)):
        party = rng.choice(PARTIES)
        number = rng.randint(1, 60)
        branches = sorted(rng.sample(range(1, 9), rng.randint(1, 5))) if rng.random() < 0.4 else []
        exhibits[(party, number)] = branches
    return exhibits


def _random_style(rng):
    return {"space": rng.random() < 0.8, "je": rng.random() < 0.9, "branch_space": rng.random() < 0.7,
            "range_word": rng.choice(["내지", "~", "∼"]), "sep": rng.choice([", ", ",", "·", " 및 "]),
            "use_range": rng.random() < 0.7, "bare_ho": rng.random() < 0.3}


@pytest.mark.parametrize("seed", range(120))
def test_random_exhibit_notation_round_trips(seed):
    rng = random.Random(seed)
    exhibits = _random_exhibits(rng)
    pieces = []
    for (party, number), branches in exhibits.items():
        name = rng.choice(["", " 진술서", " 각 사실확인서", "계약서", " 금융거래내역(○○은행)"])
        pieces.append(render(party, number, branches, _random_style(rng)) + name)
    joiner = rng.choice([" ", "\n", ", ", "  "])
    text = joiner.join(pieces)
    expected = sorted((p, n, tuple(b)) for (p, n), b in exhibits.items())
    assert canonical(parse_exhibits(text)) == expected, text


def test_grouped_numbers_round_trip():
    rng = random.Random(7)
    for _ in range(40):
        numbers = sorted(rng.sample(range(1, 40), rng.randint(2, 5)))
        sep = rng.choice([", ", "·", " 및 제", ", 제"])
        text = f"갑 제{sep.join(str(n) for n in numbers)}호증"
        assert canonical(parse_exhibits(text)) == [("갑", n, ()) for n in numbers], text


# --- 대조군: 정상 서면 3종(민사·형사·가사)에서 증거 관련 CONTRADICTED 0건 --------------------------------
def _two_column_pdf(path: Path, title: str, body, columns, trailing=()):
    """본문 문단 + 두 단 입증방법 목록(왼쪽·오른쪽 칸을 한 줄에 그림) PDF."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    try:
        pdfmetrics.getFont("HYSMyeongJo-Medium")
    except Exception:
        pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("HYSMyeongJo-Medium", 10.5)
    y = A4[1] - 70
    c.drawString(70, y, title)
    y -= 30
    for paragraph in body:
        c.drawString(60, y, paragraph)
        y -= 18
    y -= 10
    c.drawString(60, y, "입 증 방 법")
    y -= 20
    for left, right in columns:
        c.drawString(60, y, left)
        if right:
            c.drawString(310, y, right)
        y -= 18
    y -= 10
    for line in trailing:
        c.drawString(60, y, line)
        y -= 18
    c.save()
    return path


def _parse(path: Path):
    from packages.document_engine.registry import parse_document
    return parse_document(str(path), document_id=path.stem, filename=path.name, mime_type="application/pdf",
                          sha256="0" * 64)


def _evidence_contradictions(doc):
    return [f for f in check_document(doc) if str(f.status) == "CONTRADICTED" and str(f.type).startswith("EVIDENCE")]


CONTROLS = {
    "civil_loan": ("소 장(대여금)",
                   ["1. 원고는 2024. 3. 5. 피고에게 30,000,000원을 빌려주었습니다(갑 제1호증, 갑 제2호증의 1, 2).",
                    "2. 원고는 두 차례 변제를 최고하였으나(갑 제3ㆍ4호증) 피고는 응하지 않았습니다.",
                    "3. 피고도 차용 사실을 인정하는 문자메시지를 보냈습니다(갑 제5호증의 1 내지 3)."],
                   [("갑 제1호증 차용증", "갑 제2호증의 1, 2 각 계좌이체내역"),
                    ("갑 제3, 4호증 각 내용증명", "갑 제5호증의 1 내지 3 각 문자메시지")],
                   ["2026. 9. 1.", "위 원고 소송대리인 변호사 ○○○ (인)"]),
    "criminal_defense": ("변 론 요 지 서",
                         ["1. 피고인은 공소사실 기재 일시에 다른 장소에 있었습니다(피고인 증 제1 내지 3호증).",
                          "2. 피해자와 합의가 이루어졌습니다(피고인 증 제4호증의 1, 2).",
                          "3. 피고인의 가족과 직장 동료가 선처를 탄원합니다(피고인 증 제5호증 및 제6호증)."],
                         [("피고인 증 제1호증 출입기록", "피고인 증 제2호증 영수증"),
                          ("피고인 증 제3호증 통화내역", "피고인 증 제4호증의 1, 2 각 합의서"),
                          ("피고인 증 제5호증 탄원서(가족)", "피고인 증 제6호증 탄원서(동료)")],
                         ["2026. 8. 20.", "피고인의 변호인 변호사 ○○○ (인)"]),
    "family_divorce": ("소 장(이혼 등)",
                       ["1. 원고와 피고는 2015. 5. 9. 혼인신고를 마친 법률상 부부입니다(갑 제1, 2호증).",
                        "2. 피고는 2023년부터 가정에 생활비를 보내지 않았습니다(갑 제3호증의 1 내지 4).",
                        "3. 혼인 중 취득한 아파트가 있습니다(갑 제4호증). 지인들의 진술도 같습니다(갑 제5ㆍ6호증)."],
                       [("갑 제1호증 혼인관계증명서", "갑 제2호증 가족관계증명서"),
                        ("갑 제3호증의 1 내지 4 각 금융거래내역", "갑 제4호증 부동산등기사항전부증명서"),
                        ("갑 제5, 6호증 각 진술서", "")],
                       ["2026. 7. 15.", "위 원고 소송대리인 변호사 ○○○ (인)"]),
}


@pytest.mark.parametrize("name", sorted(CONTROLS))
def test_control_briefs_have_no_evidence_contradiction(tmp_path, name):
    title, body, columns, trailing = CONTROLS[name]
    doc = _parse(_two_column_pdf(tmp_path / f"{name}.pdf", title, body, columns, trailing))
    rows = exhibit_rows(doc)
    assert len({(r["party"], r["number"]) for r in rows}) >= 4
    assert _evidence_contradictions(doc) == []


def test_real_gap_and_missing_listing_are_still_reported(tmp_path):
    """같은 문법으로 읽고도 진짜 결번(제3호증)과 목록에 없는 본문 인용(제7호증)은 그대로 잡는다(민사)."""
    doc = _parse(_two_column_pdf(tmp_path / "gap.pdf", "준 비 서 면",
                                 ["1. 원고는 매매대금을 모두 지급하였습니다(갑 제1, 2호증, 갑 제4호증의 1, 2).",
                                  "2. 피고의 하자 주장은 근거가 없습니다(갑 제7호증)."],
                                 [("갑 제1호증 매매계약서", "갑 제2호증 영수증"),
                                  ("갑 제4호증의 1, 2 각 사진", "갑 제5호증 감정서")],
                                 ["2026. 6. 1.", "위 원고 소송대리인 변호사 ○○○ (인)"]))
    titles = " ".join(f.title for f in _evidence_contradictions(doc))
    assert "제3호증 결번" in titles and "갑 제7호증" in titles
