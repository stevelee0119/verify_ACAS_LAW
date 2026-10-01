# -*- coding: utf-8 -*-
"""입력 계층 문단 복원 (Paragraph Reconstruction) 모듈.

물리적 줄바꿈(하드 래핑)으로 조각난 텍스트와 PDF 줄 블록을 구조 신호에 기반하여 문단 단위로 복원한다.
- 블록은 원래의 물리적 줄(lines)과 좌표를 attributes에 보존하고 소비자가 쓰는 text는 문단 단위로 결합한다.
- 당사자 표시란, 사건 표제부, 주소, 표 등 줄 단위가 의미를 갖는 영역은 줄을 그대로 유지한다.
- 짝 괄호 및 인젝션 위장 표지는 닫힐 때까지 하나의 블록으로 온전하게 결합한다.
- 일반 본문의 줄바꿈 결합 시 한글 낱말 사이 공백을 유지한다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from packages.common.schemas import BBox, Block, new_id

# 새 문단 또는 번호 목록/목차를 여는 패턴
ENUMERATOR_RE = re.compile(
    r"^(?:\d{1,2}\s*[.)]\s|[가-하]\s*[.)]\s|\(\s*\d{1,2}\s*\)|\(\s*[가-하]\s*\)|[①-⑳]|[※▶■□●○◆◇▪•]\s|[-–]\s|[I|V|X]+\.\s)"
)

# 당사자 표시란 및 사건 표제부 등 줄 단위 유지가 필수적인 패턴 목록
STANDALONE_LINE_PATTERNS = [
    # 소송 서면 제목 (준비서면, 소장, 답변서 등)
    re.compile(r"^[ \t]*(?:준[ \t]*비[ \t]*서[ \t]*면|소[ \t]*장|답[ \t]*변[ \t]*서|항[ \t]*소[ \t]*장|상[ \t]*고[ \t]*장|변[ \t]*호[ \t]*인[ \t]*의[ \t]*견[ \t]*서|의[ \t]*견[ \t]*서|탄[ \t]*원[ \t]*서|고[ \t]*소[ \t]*장|신[ \t]*청[ \t]*서)[ \t]*$"),
    # 사건 번호 라벨 ("사 건 2026가합...", "사건: ...")
    re.compile(r"^[ \t]*사[ \t]*건[ \t:]+(?:\d{4}[가-힣]+\d+|\d{2,4}\s*[가-힣]+)"),
    # 소송 당사자 역할 라벨 ("원 고", "피 고", "피고인" 등)
    re.compile(r"^[ \t]*(?:원[ \t]*고|피[ \t]*고(?:[ \t]*인)?|피[ \t]*의[ \t]*자|신[ \t]*청[ \t]*인|피[ \t]*신[ \t]*청[ \t]*인|채[ \t]*권[ \t]*자|채[ \t]*무[ \t]*자|망\b|소[ \t]*외\b)[ \t]+"),
    # 소송대리인, 대표자, 담당변호사 등 라벨
    re.compile(r"^[ \t]*(?:소[ \t]*송[ \t]*대[ \t]*리[ \t]*인|대[ \t]*리[ \t]*인|담[ \t]*당[ \t]*변[ \t]*호[ \t]*사|변[ \t]*호[ \t]*인|법[ \t]*률[ \t]*상[ \t]*대[ \t]*표[ \t]*자|소[ \t]*송[ \t]*수[ \t]*행[ \t]*자|대[ \t]*표[ \t]*이[ \t]*사|대[ \t]*표[ \t]*자)[ \t]+"),
    # 당사자 인적사항 라벨 (주소, 연락처, 이메일, 계좌번호 등)
    re.compile(r"^[ \t]*(?:주[ \t]*소|등[ \t]*록[ \t]*기[ \t]*준[ \t]*지|송[ \t]*달[ \t]*장[ \t]*소|연[ \t]*락[ \t]*처|전[ \t]*화|이[ \t]*메[ \t]*일|수[ \t]*령[ \t]*계[ \t]*좌|운[ \t]*전[ \t]*면[ \t]*허[ \t]*번[ \t]*호|군[ \t]*번|주[ \t]*민[ \t]*등[ \t]*록[ \t]*번[ \t]*호|생[ \t]*년[ \t]*월[ \t]*일)[ \t]*[:：]?[ \t]+"),
    # 괄호로 시작하는 당사자 신상 정보 줄 ("(예비역 중사...", "(군번: ...")
    re.compile(r"^[ \t]*\([ \t]*(?:예비역|군번|생년월일|주민등록번호|연락처|주소)"),
    # 법원 제출처 ("...법원 ... 귀중")
    re.compile(r"[가-힣\s\(\)]+법원(?:\s+제\s*\d+\s*[가-힣]+부(?:\([가-힣]+\))?)?\s*귀[ \t]*중[ \t]*$"),
    # "다 음" 구분 표제
    re.compile(r"^[ \t]*다[ \t]+음[ \t]*$"),
]

# 단독 도로명/지번 주소 줄 패턴 (시/도 및 시/군/구로 시작하여 행정구역 주소로만 끝나는 줄)
STANDALONE_ADDRESS_RE = re.compile(
    r"^[ \t]*(?:(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|충청북도|충청남도|전라북도|전라남도|경상북도|경상남도|강원도|경기도|제주도|[가-힣]{1,6}(?:특별시|광역시|특별자치시|도|특별자치도))\s*)?[가-힣]{1,8}(?:시|군|구)\s+[가-힣0-9\s,·\-(?:로|길|동|리|호|층|번지)]+$"
)

# 짝 괄호 및 구조적 인젝션 구분자 쌍
DELIMITER_PAIRS = [
    ("[", "]"),
    ("<<", ">>"),
    ("{{", "}}"),
    ("<!--", "-->"),
    ("/*", "*/"),
    ("@@", "@@"),
    ("##", "##"),
    ("$$", "$$"),
    ("**", "**"),
    ("~~", "~~"),
    ("||", "||"),
]

# 어절 한가운데 줄바꿈 판별용 조사/어미 (앞 줄 끝과 공백 없이 결합)
MID_WORD_STARTS = frozenset({
    "은", "는", "을", "를", "의", "에", "에게", "에게서", "에서", "에서는", "에는", "에도", "으로", "으로서", "으로써",
    "으로는", "로서", "로써", "와", "과", "께서", "한테", "부터", "까지", "라고", "이라고", "여", "며", "으며",
    "는데", "었다", "였다", "였고", "었고", "하여", "하였다"
})


def is_standalone_line(text: str) -> bool:
    """당사자 표시란, 표제부 등 독립된 줄 단위 유지가 필수적인 영역인지 판정."""
    s = text.strip()
    if not s:
        return False
    for pat in STANDALONE_LINE_PATTERNS:
        if pat.search(s):
            return True
    if STANDALONE_ADDRESS_RE.match(s):
        return True
    return False


def is_short_heading(text: str) -> bool:
    """단독 목차 제목 줄인지 판정 (예: '1. 사건의 실체적 경위', '가. 피고의 ...')."""
    s = text.strip()
    if not s or len(s) > 50:
        return False
    if not ENUMERATOR_RE.match(s):
        return False
    # 서술형 종결어미로 끝나는 완전한 문장은 제목이 아니라 본문 문장으로 판정
    if re.search(r"(?:다|음|함|습니다|입니다|시오|지요)\s*[.!?]?$", s):
        return False
    return True


def get_unclosed_delimiter(text: str) -> Optional[str]:
    """줄이 열림 기호로 시작하지만 닫히지 않은 경우 닫힘 기호를 반환."""
    s = text.strip()
    for opener, closer in DELIMITER_PAIRS:
        if s.startswith(opener):
            content = s[len(opener):]
            if closer not in content:
                return closer
    return None


def join_lines(prev: str, nxt: str) -> str:
    """두 줄의 텍스트를 올바른 공백 보존 규칙으로 결합한다."""
    p = prev.rstrip()
    n = nxt.lstrip()
    if not p:
        return n
    if not n:
        return p
    last = p[-1]
    first = n[0]
    # 열림 기호 직후나 닫힘 기호 직전은 공백 없이 연결
    if last in "([{「『“‘<《〈【":
        return p + n
    if first in ")]}」』”’>》〉】,.;:!?%·":
        return p + n
    # 조사/어미로 시작하면 어절 중간 줄바꿈이므로 공백 없이 붙임
    first_word = n.split(" ", 1)[0].rstrip(".,;:)]」』”’'\"")
    if re.match(r"[가-힣]", last) and first_word in MID_WORD_STARTS:
        return p + n
    # 일반적인 단어 경계 줄바꿈: 한글 낱말 사이 공백 1개 유지
    return p + " " + n


def reconstruct_paragraphs_from_text(raw_text: str, page_num: int = 1) -> List[Block]:
    """원문 텍스트로부터 문단을 복원하여 Block 리스트를 생성한다."""
    blocks: List[Block] = []
    raw_lines = raw_text.splitlines()
    curr_lines: List[str] = []
    active_closer: Optional[str] = None

    def flush_current() -> None:
        nonlocal curr_lines, active_closer
        if not curr_lines:
            return
        combined = curr_lines[0]
        for nxt in curr_lines[1:]:
            combined = join_lines(combined, nxt)

        blk = Block(
            block_id=new_id("B"),
            text=combined,
            page=page_num,
            block_type="paragraph",
            attributes={"lines": list(curr_lines)} if len(curr_lines) > 1 else {},
        )
        blocks.append(blk)
        curr_lines = []
        active_closer = None

    for raw_line in raw_lines:
        line = raw_line.strip()
        if not line:
            # 빈 줄은 문단 경계
            flush_current()
            continue

        # 미닫힌 구분자(인젝션/헤더 등) 수집 중인 경우
        if active_closer is not None:
            curr_lines.append(line)
            if active_closer in line:
                flush_current()
            continue

        # 새로운 미닫힌 구분자로 시작하는지 확인
        closer = get_unclosed_delimiter(line)
        if closer is not None:
            flush_current()
            curr_lines.append(line)
            active_closer = closer
            continue

        # 완전히 닫힌 독립 괄호/인젝션 표지 줄
        is_full_delimiter = any(
            line.startswith(op) and line.endswith(cl) and len(line) >= len(op) + len(cl)
            for op, cl in DELIMITER_PAIRS
        )
        if is_full_delimiter:
            flush_current()
            curr_lines.append(line)
            flush_current()
            continue

        # 당사자 표시란, 표제부 등 독립 줄
        if is_standalone_line(line):
            flush_current()
            curr_lines.append(line)
            flush_current()
            continue

        # 단독 목차 제목(Heading)
        if is_short_heading(line):
            flush_current()
            curr_lines.append(line)
            flush_current()
            continue

        # 새 번호 목록으로 시작하는 본문 줄
        if ENUMERATOR_RE.match(line):
            flush_current()
            curr_lines.append(line)
            continue

        # 일반 본문 줄 누적
        curr_lines.append(line)

    flush_current()
    return blocks


def reconstruct_page_blocks(
    blocks: List[Block],
    page_num: int = 1,
    page_width: float = 0.0,
    page_height: float = 0.0,
) -> List[Block]:
    """PDF 또는 구조화 파서에서 줄 단위로 추출된 Block들을 문단 단위로 결합하여 복원한다."""
    reconstructed: List[Block] = []
    curr_group: List[Block] = []
    active_closer: Optional[str] = None

    def flush_group() -> None:
        nonlocal curr_group, active_closer
        if not curr_group:
            return
        if len(curr_group) == 1:
            reconstructed.append(curr_group[0])
            curr_group = []
            active_closer = None
            return

        # 여러 줄 블록을 결합
        combined_text = curr_group[0].text
        for b in curr_group[1:]:
            combined_text = join_lines(combined_text, b.text)

        # 외접 bounding box 계산
        bboxes = [b.bbox for b in curr_group if b.bbox is not None]
        union_bbox = None
        if bboxes:
            union_bbox = BBox(
                x0=min(b.x0 for b in bboxes),
                y0=min(b.y0 for b in bboxes),
                x1=max(b.x1 for b in bboxes),
                y1=max(b.y1 for b in bboxes),
            )

        first_block = curr_group[0]
        merged_attributes = dict(first_block.attributes)
        merged_attributes["lines"] = [
            {"text": b.text, "bbox": b.bbox.as_tuple() if b.bbox else None}
            for b in curr_group
        ]

        merged_block = Block(
            block_id=new_id("B"),
            text=combined_text,
            page=page_num,
            bbox=union_bbox,
            source_layer=first_block.source_layer,
            block_type=first_block.block_type,
            visible=first_block.visible,
            attributes=merged_attributes,
        )
        reconstructed.append(merged_block)
        curr_group = []
        active_closer = None

    for block in blocks:
        text = (block.text or "").strip()
        if not text:
            continue

        # 숨김 텍스트, 표, 머리글 등 특수 블록은 결합하지 않고 단독 유지
        if (
            not block.visible
            or block.source_layer != "visible_text"
            or block.block_type in ("table", "table_line", "running_head", "header", "footer", "comment")
            or block.attributes.get("hidden_reason")
            or block.attributes.get("table_ref")
        ):
            flush_group()
            reconstructed.append(block)
            continue

        # 미닫힌 구분자(인젝션 표지 등) 수집 중인 경우
        if active_closer is not None:
            curr_group.append(block)
            if active_closer in text:
                flush_group()
            continue

        closer = get_unclosed_delimiter(text)
        if closer is not None:
            flush_group()
            curr_group.append(block)
            active_closer = closer
            continue

        # 완전히 닫힌 독립 괄호/인젝션 표지 줄
        is_full_delimiter = any(
            text.startswith(op) and text.endswith(cl) and len(text) >= len(op) + len(cl)
            for op, cl in DELIMITER_PAIRS
        )
        if is_full_delimiter:
            flush_group()
            reconstructed.append(block)
            continue

        # 당사자 표시란, 표제부 등 독립 줄
        if is_standalone_line(text):
            flush_group()
            reconstructed.append(block)
            continue

        # 단독 목차 제목(Heading)
        if is_short_heading(text):
            flush_group()
            reconstructed.append(block)
            continue

        # 세로 간격(Vertical gap) 검사: 이전 줄과의 거리가 너무 멀면 문단 경계로 취급
        if curr_group and curr_group[-1].bbox and block.bbox:
            prev_bbox = curr_group[-1].bbox
            font_size = float(curr_group[-1].attributes.get("size", 10.0) or 10.0)
            gap = block.bbox.y0 - prev_bbox.y1
            if gap > font_size * 2.0:
                flush_group()
                curr_group.append(block)
                continue

        # 새 번호 목록으로 시작하는 본문 줄
        if ENUMERATOR_RE.match(text):
            flush_group()
            curr_group.append(block)
            continue

        # 일반 본문 줄 결합
        curr_group.append(block)

    flush_group()
    return reconstructed
