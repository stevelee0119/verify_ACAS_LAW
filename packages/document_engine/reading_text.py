"""줄 블록을 사람이 읽는 순서의 본문으로 복원한다.

PDF 파서의 블록은 시각적 '줄'이다. 한국어 서면은 글자 단위로 줄을 바꾸므로 "(대 / 법원",
"하였다 / 는", "2011. 1. 2 / 7."처럼 한 단어나 숫자가 두 줄로 갈린다. 줄을 공백으로 이으면
단어가 쪼개지고, 줄마다 따로 읽으면 인용이 잘린다. 여기서는

1. 여러 쪽에 반복되는 머리글·바닥글(쪽 번호 포함)을 본문에서 뺀다.
2. 줄바꿈이 단어 안에서 일어났는지, 문단 경계인지, 단어 경계인지를 규칙으로 판단해 잇는다.
3. 이어 붙인 본문의 각 글자가 어느 블록의 몇 번째 글자인지 되짚을 수 있게 위치표를 남긴다.

규칙은 문서 종류·파일명과 무관하게 줄의 글자 종류와 좌표만 본다.
"""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from packages.common.schemas import Block, NormalizedDocument

RUNNING_HEAD = "running_head"

# 쪽 번호만 있는 줄: "3", "- 3 -", "3/10", "3 / 10", "3쪽"
PAGE_NUMBER_RE = re.compile(r"^[\s\-–—·(]*\d{1,4}\s*(?:/\s*\d{1,4}|쪽|페이지|page)?[\s\-–—·)]*$", re.I)
# 줄 끝의 쪽 표시: "… · 1/3"
PAGE_COUNTER_TAIL_RE = re.compile(r"\d{1,4}\s*/\s*\d{1,4}\s*$")
# 새 문단을 여는 번호·기호
ENUMERATOR_RE = re.compile(
    r"^(?:\d{1,2}\s*[.)]\s|[가-하]\s*[.)]\s|\(\s*\d{1,2}\s*\)|\(\s*[가-하]\s*\)|[①-⑳]|[※▶■□●○◆◇▪•]\s|"
    r"[-–]\s)"
)
_HANGUL = re.compile(r"[가-힣]")
_DIGIT = re.compile(r"\d")
_LATIN = re.compile(r"[A-Za-z]")
# 줄 끝에 오면 뒤와 붙여 쓰는 여는 기호, 줄 앞에 오면 앞과 붙여 쓰는 닫는 기호
_OPENERS = "([{「『“‘<《〈【"
_CLOSERS = ")]}」』”’>》〉】,.;:!?%·"
EDGE_ZONE = 0.12       # 쪽 위·아래 12% 안의 줄만 머리글·바닥글 후보
FULL_LINE_SLACK = 0.06  # 본문 오른쪽 끝에서 이 비율 안에서 끝나면 '꽉 찬 줄'


def _signature(text: str) -> str:
    """쪽마다 달라지는 숫자를 지운 비교용 서명."""
    return re.sub(r"\d+", "#", re.sub(r"\s+", "", text))


def _vertical(block: Block, height: float) -> Optional[float]:
    if block.bbox is None or not height:
        return None
    return block.bbox.y0 / height


def mark_running_heads(doc: NormalizedDocument) -> List[str]:
    """반복되는 머리글·바닥글과 쪽 번호 줄을 찾아 block_type을 running_head로 바꾼다.

    - 두 쪽 이상에서 같은 서명(숫자 무시)으로 쪽 위·아래 가장자리에 나오는 줄
    - 가장자리에 있고 쪽 번호만 있거나 "n/m" 쪽 표시로 끝나는 줄(한 쪽 문서 포함)
    좌표가 없는 블록(DOCX·HWP 등)은 쪽 가장자리 여부를 알 수 없어 건드리지 않는다.
    """
    candidates: Dict[str, List[Block]] = {}
    marked: List[str] = []
    for page in doc.pages:
        height = page.height or 0.0
        visible = [b for b in page.blocks if b.visible and b.block_type == "paragraph" and (b.text or "").strip()]
        for block in visible:
            where = _vertical(block, height)
            if where is None or EDGE_ZONE < where < 1 - EDGE_ZONE:
                continue
            text = block.text.strip()
            if PAGE_NUMBER_RE.match(text) or (where >= 1 - EDGE_ZONE and PAGE_COUNTER_TAIL_RE.search(text)):
                block.block_type = RUNNING_HEAD
                marked.append(block.block_id)
                continue
            candidates.setdefault(_signature(text), []).append(block)
    for blocks in candidates.values():
        if len({b.page for b in blocks}) >= 2:
            for block in blocks:
                block.block_type = RUNNING_HEAD
                marked.append(block.block_id)
    doc.structure["running_heads_checked"] = True
    if marked:
        doc.structure["running_head_block_ids"] = marked
    return marked


def ensure_running_heads(doc: NormalizedDocument) -> None:
    """아직 검사하지 않은 문서만 머리글·바닥글을 표시한다(여러 모듈이 불러도 한 번만)."""
    if not doc.structure.get("running_heads_checked"):
        mark_running_heads(doc)


def _kind(char: str) -> str:
    if _HANGUL.match(char):
        return "H"
    if _DIGIT.match(char):
        return "D"
    if _LATIN.match(char):
        return "L"
    return "P"


def _is_full_line(block: Block, right_edge: Optional[float], width: float) -> Optional[bool]:
    """줄이 본문 오른쪽 끝까지 찼는지. 좌표가 없으면 None."""
    if block.bbox is None or right_edge is None or not width:
        return None
    return block.bbox.x1 >= right_edge - FULL_LINE_SLACK * width


def join_separator(prev: str, nxt: str, *, prev_full: Optional[bool] = True) -> str:
    """앞 줄과 다음 줄 사이에 넣을 문자. '' = 단어 안 줄바꿈, ' ' = 단어 경계, '\\n' = 문단 경계."""
    prev, nxt = prev.rstrip(), nxt.lstrip()
    if not prev or not nxt:
        return "\n"
    last, first = prev[-1], nxt[0]
    if ENUMERATOR_RE.match(nxt) and not (prev_full is not False and _kind(last) in "HD"):
        # "2. 원고는…"은 새 문단이다. 다만 꽉 찬 줄이 글자·숫자 중간에서 끊기고 다음 줄이 숫자로
        # 시작하면("…2011. 1. 2" / "7. 선고") 번호가 아니라 앞 줄의 이어짐이다.
        return "\n"
    if prev_full is not True:
        # 오른쪽 여백 전에 끝난 줄은 문단의 끝이다. 좌표가 없는 블록(DOCX·HWP 문단, 텍스트 파일 줄)은
        # 원본의 문단·줄 경계이므로 줄바꿈 결합 규칙을 쓰지 않는다.
        return "\n"
    if last in _OPENERS or first in _CLOSERS:
        return ""
    a, b = _kind(last), _kind(first)
    if a == "L" and b == "L":
        return " "  # 영문은 단어 단위로 줄을 바꾼다
    if a == b and a in "HD":
        # 한글끼리·숫자끼리는 글자 단위 줄바꿈이 흔하다("(대 / 법원", "2011. 1. 2 / 7.").
        # 원래 공백이 있었는지는 알 수 없으므로 붙이고, 하위 모듈은 공백 차이에 영향받지 않게 비교한다.
        # 한글–숫자 경계("선고 / 2006두")는 공백을 넣는다. 인용 정규식은 그 자리의 공백을 허용한다.
        return ""
    return " "


@dataclass
class Segment:
    start: int
    end: int
    block: Block


@dataclass
class ReadingText:
    text: str
    segments: List[Segment] = field(default_factory=list)
    _starts: List[int] = field(default_factory=list, repr=False)

    def locate(self, index: int) -> Tuple[Optional[Block], int]:
        """본문 위치 → (블록, 블록 안 위치). 구분 문자 위치는 뒤 블록의 시작으로 본다."""
        if not self.segments:
            return None, 0
        if not self._starts:
            self._starts = [s.start for s in self.segments]
        position = max(0, bisect.bisect_right(self._starts, index) - 1)
        segment = self.segments[position]
        if index >= segment.end and position + 1 < len(self.segments):
            segment = self.segments[position + 1]
        return segment.block, max(0, index - segment.start)

    def blocks_between(self, start: int, end: int) -> List[Block]:
        return [s.block for s in self.segments if s.end > start and s.start < end]


def build_reading_text(doc: NormalizedDocument, blocks: Optional[Iterable[Block]] = None) -> ReadingText:
    """본문 블록(표·머리글 제외)을 읽는 순서대로 이어 하나의 본문으로 만든다."""
    chosen = list(blocks) if blocks is not None else [
        b for b in doc.body_blocks() if b.block_type not in ("table", "table_line", RUNNING_HEAD)]
    pages = {p.page_number: p for p in doc.pages}
    right_edges: Dict[int, float] = {}
    for block in chosen:
        if block.bbox is not None:
            right_edges[block.page] = max(right_edges.get(block.page, 0.0), block.bbox.x1)
    parts: List[str] = []
    segments: List[Segment] = []
    cursor = 0
    previous: Optional[Block] = None
    for block in chosen:
        text = (block.text or "").strip()
        if not text:
            continue
        if previous is not None:
            page = pages.get(previous.page)
            width = page.width if page else 0.0
            full = _is_full_line(previous, right_edges.get(previous.page), width)
            separator = join_separator(previous.text, text, prev_full=full)
            parts.append(separator)
            cursor += len(separator)
        segments.append(Segment(cursor, cursor + len(text), block))
        parts.append(text)
        cursor += len(text)
        previous = block
    return ReadingText("".join(parts), segments)
