"""줄바꿈 결합: 어절 중간 줄바꿈의 증거(조사·어미로 시작하는 줄)가 있으면 공백 없이 잇는다(v4 검토 1항 회귀).

0.8.x에서 '짧게 넘어간 줄이 2번 이상인 쪽'을 통째로 어절 단위 줄바꿈 쪽으로 보고 꽉 찬 줄까지 공백으로 이어,
글자 단위로 줄을 바꾼 서면의 '(대 / 법원'이 '(대 법원'이 되었다. 법원·선고일이 인용에서 빠져 선고일 오류를 놓쳤다.
문장·사건번호는 시험용으로 새로 지었다.
"""
from __future__ import annotations

from packages.common.schemas import BBox, Block, NormalizedDocument, Page
from packages.document_engine.reading_text import build_reading_text, starts_mid_word
from packages.legal_engine.citation_extractor import extract_citations

PAGE_W, PAGE_H = 595.0, 842.0
LEFT, RIGHT = 60.0, 535.0
CHAR = 10.0  # 한 글자 폭(시험용)


def page_of(lines, doc_id="doc_join"):
    """(글, 오른쪽 끝) 목록 → 한 쪽 문서. 오른쪽 끝이 None이면 본문 끝(RIGHT)까지 찬 줄이다."""
    page = Page(page_number=1, width=PAGE_W, height=PAGE_H)
    y = 80.0
    for index, (text, right) in enumerate(lines):
        page.blocks.append(Block(block_id=f"b{index}", text=text, page=1,
                                 bbox=BBox(LEFT, y, right if right is not None else RIGHT, y + 12)))
        y += 18
    return NormalizedDocument(document_id=doc_id, filename="서면.pdf", mime_type="application/pdf",
                              sha256="0" * 64, pages=[page])


def test_particle_or_ending_alone_marks_a_mid_word_break():
    assert starts_mid_word("재량권을 맡긴 징계권자", "에게 맡겨진 재량")
    assert starts_mid_word("형의 3분의 1을 감액하", "는 처분이므로")
    assert starts_mid_word("그 전부에 대하", "여 적용한다")
    # 지시어·새 어절로 시작하는 줄, 문장부호로 끝난 줄은 증거가 아니다
    assert not starts_mid_word("원고는 다음과 같이 주장한다", "이 사건 처분은")
    assert not starts_mid_word("청구를 기각한다.", "는 취지로")
    assert not starts_mid_word("피고는 원고", "에너지 공급을")


def _char_wrapped_page(prefix_lines, citation_head, citation_tail):
    """글자 단위로 줄을 바꾼 쪽. 긴 숫자 때문에 짧게 넘어간 줄 2개(어절 단위 쪽처럼 보이게 하는 신호)와
    어절 중간 줄바꿈 증거 1개, 두 줄에 걸친 인용을 담는다."""
    lines = []
    for text in prefix_lines:
        lines.append((text, None))
    lines += [
        ("번호가 긴 사건은 한 번에 넘어가므로 이 줄은 오른쪽 끝 전에서", RIGHT - CHAR * 6),
        ("2026구합123456호 사건과 함께 심리한 결과 처분의 사유가 인정되고", RIGHT - CHAR * 6),
        ("2026구합123457호 사건의 결론도 이와 같으며 그 사유를 밝힌 징계권자", None),
        ("에게 맡겨진 재량권의 범위를 벗어났는지가 쟁점이다. 법원은 " + citation_head, None),
        (citation_tail, LEFT + CHAR * 30),
    ]
    return page_of(lines)


def test_criminal_brief_citation_split_inside_court_name_keeps_court_and_date():
    doc = _char_wrapped_page(["피고인은 공소사실을 다투며 원심의 사실인정에 채증법칙 위반이 있다고 주장한다"],
                             "이 점을 밝혔다(대", "법원 2019. 5. 16. 선고 2018도12345 판결).")
    text = build_reading_text(doc).text
    assert "(대법원 2019. 5. 16. 선고 2018도12345 판결)" in text
    case = [c for c in extract_citations(doc) if c.case_number == "2018도12345"]
    assert case and case[0].court == "대법원" and str(case[0].decision_date) == "2019-05-16"


def test_administrative_brief_citation_split_inside_court_name_keeps_court_and_date():
    doc = _char_wrapped_page(["원고는 징계처분의 취소를 구하며 처분사유의 부존재와 재량권 일탈을 주장한다"],
                             "같은 취지다(대", "법원 2020. 3. 26. 선고 2019두12345 판결).")
    case = [c for c in extract_citations(doc) if c.case_number == "2019두12345"]
    assert case and case[0].court == "대법원" and str(case[0].decision_date) == "2020-03-26"


def test_family_brief_mid_word_break_is_joined_without_space():
    doc = _char_wrapped_page(["청구인은 재산분할을 구하며 혼인 기간 동안의 기여도를 다툰다"],
                             "판단한 바 있다(대", "법원 2021. 6. 10. 선고 2020므12345 판결).")
    text = build_reading_text(doc).text
    assert "징계권자에게 맡겨진" in text and "징계권자 에게" not in text
    case = [c for c in extract_citations(doc) if c.case_number == "2020므12345"]
    assert case and case[0].court == "대법원"


def test_word_wrapped_page_without_mid_word_evidence_still_joins_with_space():
    """어절 단위로 줄을 바꾼 쪽(D1)은 꽉 찬 줄도 공백으로 잇는다(민사 인용문 어절 보존)."""
    lines = [
        ("원고는 사고 당일 작업장에서 넘어져 다쳤고 피고는 그 작업을 지시한", None),
        ("사용자로서 원고에게 안전한 작업 환경을 마련할 계약상 의무가 있으며", None),
        ("원고는 피고의 안전배려의무 위반을 이유로 손해배상을 구하고", RIGHT - CHAR * 5),
        ("대법원은 사용자가 근로자의 생명과 신체를 보호할 의무를", RIGHT - CHAR * 4.5),
        ("부담한다고 보았고 그 의무의 범위를 사회통념상 현저히", None),
        ("타당성을 잃지 않는 범위에서 정한다고 판시하였다.", LEFT + CHAR * 20),
    ]
    text = build_reading_text(page_of(lines)).text
    assert "현저히 타당성을" in text and "의무를 부담한다고" in text
