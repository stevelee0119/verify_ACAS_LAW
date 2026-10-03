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
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from packages.common.schemas import BBox, Block, new_id

# 새 문단 또는 번호 목록/목차를 여는 패턴
ENUMERATOR_RE = re.compile(
    r"^(?:\d{1,2}\s*[.)]\s|[가-하]\s*[.)]\s|\(\s*\d{1,2}\s*\)|\(\s*[가-하]\s*\)|[①-⑳]|[※▶■□●○◆◇▪•]\s|[-–]\s|[I|V|X]+\.\s)"
)

# 당사자 표시란 및 사건 표제부 등 줄 단위 유지가 필수적인 패턴 목록
STANDALONE_LINE_PATTERNS = [
    # 소송 서면 제목 (준비서면, 소장, 답변서 등)
    re.compile(r"^\s*(?:준\s*비\s*서\s*면|소\s*장|답\s*변\s*서|항\s*소\s*장|상\s*고\s*장|변\s*호\s*인\s*의\s*견\s*서|의\s*견\s*서|탄\s*원\s*서|고\s*소\s*장|신\s*청\s*서)\s*$"),
    # 사건 번호 라벨 ("사 건 2026가합...", "사건: ...")
    re.compile(r"^\s*사\s*건[\s:]+(?:\d{4}[가-힣]+\d+|\d{2,4}\s*[가-힣]+|[가-힣○△□*]+지방법원|\d{4}구합)"),
    # 소송 당사자 역할 라벨 ("원 고", "피 고", "피고인" 등)
    re.compile(r"^\s*(?:원\s*고|피\s*고(?:[\s]*인)?|피\s*의\s*자|신\s*청\s*인|피\s*신\s*청\s*인|채\s*권\s*자|채\s*무\s*자|망\b|소\s*외\b)(?:\s+|(?=[0-9가-힣]))"),
    # 소송대리인, 대표자, 담당변호사 등 라벨
    re.compile(r"^\s*(?:소\s*송\s*대\s*리\s*인|대\s*리\s*인|담\s*당\s*변\s*호\s*사|변\s*호\s*인|법\s*률\s*상\s*대\s*표\s*자|소\s*송\s*수\s*행\s*자|대\s*표\s*이\s*사|대\s*표\s*자)(?:\s+|(?=[0-9가-힣]))"),
    # 당사자 인적사항 라벨 (주소, 연락처, 이메일, 계좌번호 등)
    re.compile(r"^\s*(?:주\s*소|등\s*록\s*기\s*준\s*지|송\s*달\s*장\s*소|연\s*락\s*처|전\s*화|이\s*메\s*일|수\s*령\s*계\s*좌|운\s*전\s*면\s*허\s*번\s*호|군\s*번|주\s*민\s*등\s*록\s*번\s*호|생\s*년\s*월\s*일|성\s*명|소\s*속(?:[·ㆍ・]?\s*계\s*급)?|진\s*술\s*인)\s*[:：]?\s*"),
    # 괄호로 시작하는 당사자 신상 정보 줄 ("(예비역 중사...", "(군번: ...")
    re.compile(r"^\s*\(\s*(?:예비역|군번|생년월일|주민등록번호|연락처|주소)"),
    # 단독 날짜 줄 ("2026. 9. 5.", "[날짜]" 등)
    re.compile(r"^\s*(?:(?:19|20)\d{2}\s*[.\-년]\s*\d{1,2}\s*[.\-월]\s*\d{1,2}\s*[.일]?|\[\s*날\s*짜\s*\])\s*$"),
    # 서명 / 날인 / 귀중 / 진술인 줄
    re.compile(r"^\s*(?:원\s*고|피\s*고|진\s*술\s*인|신\s*청\s*인)?\s*(?:소\s*송\s*대\s*리\s*인|대\s*리\s*인|변\s*호\s*사|담\s*당\s*변\s*호\s*사)?\s*[가-힣\s○△□*]+\s*(?:\([ \t]*(?:인|서\s*명|날\s*인|서\s*명\s*생\s*략)[ \t]*\)|귀[\s]*중)\s*$"),
    re.compile(r"[가-힣\s\(\)]+법원(?:\s+제\s*\d+\s*[가-힣]+부(?:\([가-힣]+\))?)?\s*귀\s*중\s*$"),
    re.compile(r"^\s*첨\s*부\s*[:：]"),
    # 호증 / 증거 목록 줄
    re.compile(r"^\s*(?:[갑을병정]\s*제\s*\d+|증\s*제\s*\d+|\d{1,2}\s*[.)]\s*[갑을병정]\s*제\s*\d+|[-*•·]\s*[갑을병정]\s*제\s*\d+)"),
    re.compile(r"^\s*※\s*(?:원\s*고|피\s*고|이\s*초안|본\s*서면)"),
    re.compile(r"^\s*(?:증\s*거\s*설\s*명\s*서|입\s*증\s*방\s*법|첨\s*부\s*서\s*류|증\s*거\s*목\s*록|소\s*명\s*방\s*법)\s*$"),
    re.compile(r"^\s*호\s*증\s+서\s*증\s*명"),
    re.compile(r"^\s*(?:진\s*술\s*서|사\s*실\s*확\s*인\s*서|확\s*인\s*서)\s*$"),
    # 마크다운 헤더 / 볼드 목차 / 대괄호 플레이스홀더
    re.compile(r"^\s*#{1,6}\s+"),
    re.compile(r"^\s*\*\*[^*]+\*\*\s*$"),
    re.compile(r"^\s*\[[^\]]+\]\s*$"),
    # AI 어시스턴트 첫인사 줄
    re.compile(r"^\s*(?:물론입니다!|네,\s*알겠습니다|요청하신\s*내용을\s*바탕으로).*?(?:작성해\s*드리겠습니다|드리겠습니다|바랍니다)[.!]?\s*$"),
    # "다 음" 구분 표제
    re.compile(r"^\s*다\s+음\s*$"),
]

# 단독 도로명/지번 주소 줄 패턴 (시/도 및 시/군/구로 시작하여 행정구역 주소로만 끝나는 줄)
STANDALONE_ADDRESS_RE = re.compile(
    r"^\s*(?:(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|충청북도|충청남도|전라북도|전라남도|경상북도|경상남도|강원도|경기도|제주도|[가-힣]{1,6}(?:특별시|광역시|특별자치시|도|특별자치도))\s*)?[가-힣]{1,8}(?:시|군|구)\s+[가-힣0-9\s,·\-(?:로|길|동|리|호|층|번지)]+$"
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
    "는데", "었다", "였다", "였고", "었고", "하여", "하였다", "니다", "습니다", "임", "임을", "이며", "이고",
    "이라", "이라는", "이란", "므로", "으므로", "이나", "거나", "는지", "은지", "던", "었던", "았던"
})


def _norm_s(text: str) -> str:
    """줄바꿈 검사용 공백 및 유니코드 정규화."""
    return unicodedata.normalize("NFKC", (text or "").replace("\xa0", " ")).strip()


def is_standalone_line(text: str) -> bool:
    """당사자 표시란, 표제부 등 독립된 줄 단위 유지가 필수적인 영역인지 판정."""
    s = _norm_s(text)
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
    s = _norm_s(text)
    if not s or len(s) > 50:
        return False
    if re.match(r"^#{1,6}\s+", s):
        return True
    if re.match(r"^\*\*[^*]+\*\*$", s):
        return True
    if not ENUMERATOR_RE.match(s):
        return False
    # 서술형 종결어미로 끝나는 완전한 문장은 제목이 아니라 본문 문장으로 판정
    if re.search(r"(?:다|음|함|습니다|입니다|시오|지요)\s*[.!?]?$", s):
        return False
    # 목차형 어구인지 확인
    if re.search(r"(?:개요|경위|배경|경과|취지|원인|이유|법리|판례|손해배상|결론|판단|주장|당부|관하여|대하여|살피건대|기초사실|인적사항)\s*$", s):
        return True
    # 문장 성분(격조사)이 3개 이상 결합된 복합 절은 제목이 아니라 문장으로 판정
    if len(re.findall(r"(?:이|가|을|를|은|는|에|의)\s", s)) >= 3:
        return False
    return True


def get_unclosed_delimiter(text: str) -> Optional[str]:
    """줄이 열림 기호로 시작하지만 닫히지 않은 경우 닫힘 기호를 반환."""
    s = _norm_s(text)
    # 마크다운 헤더(^#{1,6}\s)는 짝 구분자가 아님
    if re.match(r"^#{1,6}\s", s):
        return None
    for opener, closer in DELIMITER_PAIRS:
        if s.startswith(opener):
            content = s[len(opener):]
            if closer not in content:
                return closer
    return None



# 괄호/따옴표 바로 뒤에 붙는 지시 관형사 (예: '(이 사건)', '(해당 채무)', '(위 계약)') (TK-41)
PAREN_DETERMINERS = {"이", "해당", "위", "본", "그", "저", "동", "각"}

# 독립 어절로 쓰이는 1음절 관형사·접속사·명사·수사 (어절 경계 보존) (TK-41)
STANDALONE_WORDS = {
    "그", "이", "저", "위", "본", "각", "동", "해당",
    "및", "또", "더", "법", "한", "두", "세", "네", "몇", "매"
}


def join_lines(
    prev: str,
    nxt: str,
    *,
    prev_full: bool = False,
    char_wrap_context: bool = False,
) -> str:
    """두 줄을 하나의 문장/어절 단위로 결합한다 (TK-31, TK-41).

    1. 열림/닫힘 기호 경계는 공백 없이 연결.
    2. 괄호 직후 지시 관형사('이', '해당', '위' 등)는 공백 보존, 복합명사 분절('대' + '법원')은 공백 없이 연결.
    3. 조사/어미 시작(`MID_WORD_STARTS`)은 어절 중간 줄바꿈이므로 공백 없이 연결.
    4. 꽉 찬 줄에서 분절된 경우, 독립 1음절 어절('그', '이', '법', '두' 등)은 공백 보존하고 일반 어절 분절만 결합.
    5. 그 외 일반 줄바꿈은 공백 1개 삽입.
    """
    p = unicodedata.normalize("NFKC", prev or "").rstrip()
    n = unicodedata.normalize("NFKC", nxt or "").lstrip()
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

    # 1. 괄호/따옴표 바로 뒤에 1~2음절만 걸치고 줄바꿈된 경우 (TK-31, TK-41)
    m_paren = re.search(r"[\(\[\{“\"'‘「『<《〈【]([가-힣]{1,2})$", p)
    if m_paren and re.match(r"[가-힣]", first):
        paren_stem = m_paren.group(1)
        # 괄호 안의 지시 관형사(이, 해당, 위 등) 뒤에 명사가 오는 경우 공백 유지 (TK-41)
        if paren_stem in PAREN_DETERMINERS:
            return p + " " + n
        # 그 외 고유명사/기관명 분절(예: '판시하였습니다(대' + '법원')은 공백 없이 연결
        return p + n

    # 2. 조사/어미로 시작하면 어절 중간 줄바꿈이므로 공백 없이 붙임 (예: '징계권자' + '에게', '대하' + '여')
    words = n.split()
    first_word = words[0].rstrip(".,;:)]」』”’'\"") if words else ""
    if re.match(r"[가-힣]", last) and first_word in MID_WORD_STARTS:
        return p + n

    # 3. 꽉 찬 줄(prev_full) 또는 글자 단위 줄바꿈 문맥에서 앞 줄 끝이 1음절 한글 단어로 끊긴 경우 (TK-41)
    # 독립 관형사/접속사/명사('그', '이', '저', '위', '본', '각', '및', '또', '더', '법' 등)는 공백 보존
    words_p = p.split()
    last_word = words_p[-1] if words_p else ""
    if (prev_full or char_wrap_context) and len(last_word) == 1 and re.match(r"[가-힣]", last) and re.match(r"[가-힣]", first):
        if last_word not in STANDALONE_WORDS:
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
        norm_l = _norm_s(line)
        if ENUMERATOR_RE.match(norm_l):
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

    # 쪽 내 오른쪽 경계(right edge) 분석 (문단별 마진 참조용)
    x1_values = [round(b.bbox.x1, 1) for b in blocks if b.bbox is not None]
    right_edge = 0.0
    if x1_values:
        repeated = [v for v in set(x1_values) if x1_values.count(v) >= 2]
        right_edge = max(repeated) if repeated else max(x1_values)
        if page_width > 0:
            right_edge = max(right_edge, 0.75 * page_width)

    def flush_group() -> None:
        nonlocal curr_group, active_closer
        if not curr_group:
            return
        if len(curr_group) == 1:
            reconstructed.append(curr_group[0])
            curr_group = []
            active_closer = None
            return

        # 문단 내부 줄들의 레이아웃 신호 분석 (TK-41: 쪽 전체가 아닌 해당 문단 내부 줄들에서만 도출)
        group_x1 = [round(b.bbox.x1, 1) for b in curr_group if b.bbox is not None]
        group_full_count = sum(1 for v in group_x1 if right_edge > 0 and abs(v - right_edge) <= 4.0)
        group_char_wrap = group_full_count >= 2

        # 여러 줄 블록을 결합 (해당 문단의 구조 신호 반영)
        combined_text = curr_group[0].text
        for i in range(len(curr_group) - 1):
            prev_b = curr_group[i]
            next_b = curr_group[i + 1]
            prev_full = False
            if prev_b.bbox is not None and right_edge > 0:
                prev_full = (right_edge - prev_b.bbox.x1) <= 4.0
            combined_text = join_lines(
                combined_text,
                next_b.text,
                prev_full=prev_full,
                char_wrap_context=group_char_wrap,
            )

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
            or block.attributes.get("segments")
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

        # 세로 간격(Vertical gap) 검사: 이전 줄과의 거리가 멀거나 역방향이면 문단 경계로 취급
        if curr_group and curr_group[-1].bbox and block.bbox:
            prev_bbox = curr_group[-1].bbox
            font_size = float(curr_group[-1].attributes.get("size", 10.0) or 10.0)
            gap = block.bbox.y0 - prev_bbox.y1
            if gap > font_size * 1.5 or gap < -font_size * 0.5:
                flush_group()
                curr_group.append(block)
                continue

        # 새 번호 목록으로 시작하는 본문 줄
        norm_t = _norm_s(text)
        if ENUMERATOR_RE.match(norm_t):
            flush_group()
            curr_group.append(block)
            continue


        # 일반 본문 줄 결합
        curr_group.append(block)

    flush_group()
    return reconstructed
