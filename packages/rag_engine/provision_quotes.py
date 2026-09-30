"""서면이 인용한 규정 조항의 허용·금지 방향을 참고자료 원문의 같은 조항과 대조한다(결정론, 모델 불필요).

서면이 「○○지침」 제N조 제M항(또는 '위 지침 제N조 제M항')이 "…할 수 있다"고 정한다고 적었는데,
같은 이름의 참고자료 원문에서 그 항이 "…할 수 없다·하여서는 아니 된다"로 정하고 있고 두 문장이 같은
행위(서술어 어간)를 다루면 두 인용문을 근거로 CONTRADICTS 의견을 남긴다. 반대 방향도 같다.

- 조항 번호·항 번호·규정 이름이 모두 맞는 경우에만 대조한다. 비슷한 내용을 추측으로 잇지 않는다.
- 참고자료는 사용자 보관 자료이므로 공식 원문·효력 확인을 대체하지 않는다(자문 의견).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
RULE_SUFFIX = r"(?:지침|규정|훈령|예규|규칙|내규|요령|기준|수칙|세칙|매뉴얼)"
NAMED_RULE_RE = re.compile(r"[「『]\s*(?P<name>[^」』\n]{2,60}?" + RULE_SUFFIX + r")\s*[」』]")
PROVISION_RE = re.compile(
    r"(?:[「『]\s*(?P<named>[^」』\n]{2,60}?" + RULE_SUFFIX + r")\s*[」』]|"
    r"(?<![가-힣])(?:위|동|같은|해당)\s*(?P<anaphor>" + RULE_SUFFIX + r"))\s*(?:의\s*)?"
    r"제\s*(?P<art>\d+)\s*조(?:\s*의\s*(?P<sub>\d+))?(?:\s*제\s*(?P<para>\d+)\s*항)?")
OPEN_QUOTES = {"\"": "\"", "“": "”", "'": "'", "‘": "’"}
# 서술어 어간 + 허용·금지 어미. 어간(예: '반출')이 두 문장에 함께 있어야 같은 행위로 본다.
PERMIT_RE = re.compile(r"(?P<stem>[가-힣]{2,})(?:[하되]|할|될)?\s*수\s*있(?:다|음|으며|고)|(?P<stem2>[가-힣]{2,})(?:이|을|를)?\s*"
                       r"(?:허용한다|허용된다|가능하다|갈음한다)")
PROHIBIT_RE = re.compile(r"(?P<stem>[가-힣]{2,})(?:[하되]|할|될)?\s*수\s*없(?:다|음|으며|고)|(?P<stem2>[가-힣]{2,})(?:하여서는|해서는|하여선)\s*"
                         r"(?:아니\s*된다|안\s*된다)|(?P<stem3>[가-힣]{2,})(?:을|를|은|는|이|가)?\s*금지(?:한다|된다|하며)")
BRACKETED_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)")


def _key(text: str) -> str:
    return re.sub(r"[^가-힣A-Za-z0-9]", "", BRACKETED_RE.sub("", text or ""))


# 파일 제목에 규정 이름 말고 붙을 수 있는 말(연도·판 표시). 이 밖의 말이 붙으면 다른 규정으로 본다
# ("보안업무규정"과 "군사보안업무규정 시행규칙"은 다른 규정이다).
TITLE_EXTRA_RE = re.compile(r"(?:\d+|개정|개정본|최종|사본|전문|본문|원문|현행|참고자료|자료|의사본)*")


def _same_rule(name: str, title: str) -> bool:
    """서면의 규정 이름과 참고자료 제목이 같은 규정을 가리키는가(괄호 속 기관명·분류 표지는 무시)."""
    a, b = _key(name), _key(re.sub(r"\.[A-Za-z0-9]{2,5}$", "", title or ""))
    if len(a) < 6 or a not in b:
        return False
    return bool(TITLE_EXTRA_RE.fullmatch(b.replace(a, "", 1)))


def _modal(text: str) -> Optional[Tuple[str, str, re.Match]]:
    """문장의 마지막 허용·금지 서술어. (방향, 어간, 매치)."""
    found = []
    for direction, regex in (("PERMIT", PERMIT_RE), ("PROHIBIT", PROHIBIT_RE)):
        for m in regex.finditer(text):
            stem = next(g for g in (m.groupdict().get(k) for k in ("stem", "stem2", "stem3")) if g)
            found.append((m.start(), direction, stem, m))
    if not found:
        return None
    _, direction, stem, m = max(found, key=lambda f: f[0])
    return direction, _stem(stem), m


def _stem(word: str) -> str:
    """'반출하여'·'반출할'의 행위 어간('반출'). 어미 앞의 두 글자 이상 명사형 어간만 남긴다."""
    word = re.sub(r"(?:하여|하고|하거나|하며|할|하는|해|하)$", "", word)
    return word[-4:] if len(word) > 4 else word


def _claim_quote(document: str, start: int) -> Optional[Tuple[int, int]]:
    """조항 표시 뒤 120자 안에서 시작하는 인용부호 속 문장(서면이 조항 내용이라고 적은 부분)."""
    window = document[start:start + 160]
    for offset, ch in enumerate(window):
        if ch in OPEN_QUOTES:
            close = document.find(OPEN_QUOTES[ch], start + offset + 1)
            if close != -1 and close - (start + offset) <= 500:
                return start + offset + 1, close
            return None
    return None


def _merged_file_text(chunks: List[Dict]) -> str:
    """같은 파일의 발췌문을 겹치는 부분으로 이어 붙인다(발췌 경계에서 조항이 끊기지 않게)."""
    merged = ""
    for chunk in sorted(chunks, key=lambda c: (c.get("page") or 0, c.get("start") or 0)):
        text = chunk.get("text") or ""
        if not merged:
            merged = text
            continue
        overlap = next((n for n in range(min(len(merged), len(text), 400), 19, -1)
                        if merged.endswith(text[:n])), 0)
        merged += text[overlap:] if overlap else "\n" + text
    return merged


def _article_text(text: str, article: str, sub: Optional[str]) -> Optional[str]:
    number = rf"제\s*{article}\s*조" + (rf"\s*의\s*{sub}" if sub else r"(?!\s*의\s*\d)")
    head = re.search(r"(?:^|\n)[#*\s]*" + number + r"\s*[\(（]", text)
    if not head:
        return None
    nxt = re.search(r"\n[#*\s]*(?:제\s*\d+\s*조(?:\s*의\s*\d+)?\s*[\(（]|제\s*\d+\s*장|부\s*칙)", text[head.end():])
    return text[head.start():head.end() + nxt.start() if nxt else len(text)]


def _paragraph(article_text: str, para: Optional[str]) -> Optional[str]:
    if not para:
        return article_text
    n = int(para)
    if not 1 <= n <= len(CIRCLED):
        return None
    start = article_text.find(CIRCLED[n - 1])
    if start < 0:
        return None
    end = article_text.find(CIRCLED[n], start + 1) if n < len(CIRCLED) else -1
    return article_text[start:end if end > 0 else len(article_text)]


def _modal_sentences(paragraph: str) -> List[Tuple[str, str, str]]:
    out = []
    for sentence in re.split(r"(?<=다\.)\s+|(?<=다)\s*\n", paragraph):
        sentence = sentence.strip()
        found = _modal(sentence)
        if found:
            out.append((sentence, found[0], found[1]))
    return out


def _resolve_name(document: str, match: re.Match) -> Optional[str]:
    if match.group("named"):
        return match.group("named").strip()
    suffix = match.group("anaphor")
    earlier = [m.group("name").strip() for m in NAMED_RULE_RE.finditer(document, 0, match.start())
               if m.group("name").strip().endswith(suffix)]
    return earlier[-1] if earlier else None


def check_quoted_provisions(document: str, sources: List[Dict]) -> List[Dict]:
    """서면이 인용한 규정 조항과 참고자료 원문 조항의 허용·금지 방향이 반대인 경우의 의견 목록."""
    by_file: Dict[str, List[Dict]] = {}
    for source in sources:
        by_file.setdefault(str(source.get("file_id") or source.get("source_id")), []).append(source)
    out: List[Dict] = []
    seen = set()
    for m in PROVISION_RE.finditer(document or ""):
        name = _resolve_name(document, m)
        span = _claim_quote(document, m.end())
        if not name or not span:
            continue
        claim_quote = document[span[0]:span[1]]
        claim_modal = _modal(claim_quote)
        if not claim_modal:
            continue
        for chunks in by_file.values():
            if not _same_rule(name, chunks[0].get("title") or ""):
                continue
            article = _article_text(_merged_file_text(chunks), m.group("art"), m.group("sub"))
            paragraph = _paragraph(article, m.group("para")) if article else None
            modal_sentences = _modal_sentences(paragraph) if paragraph else []
            if not modal_sentences:
                continue
            flat_claim = _key(claim_quote)

            def same_act(sentence, stem):
                # 같은 행위를 다루는지: 한쪽 서술어 어간이 다른 쪽 문장에 있어야 한다.
                return stem in flat_claim or claim_modal[1] in _key(sentence)

            # 원칙과 단서("…할 수 없다. 다만, …할 수 있다")처럼 같은 방향의 문장이 그 항에 있으면 반대로 보지 않는다.
            if any(d == claim_modal[0] and same_act(sent, stem) for sent, d, stem in modal_sentences):
                continue
            source_sentence, source_direction, source_stem = modal_sentences[0]
            if source_direction == claim_modal[0] or not same_act(source_sentence, source_stem):
                continue
            holder = next((c for c in chunks if source_sentence in (c.get("text") or "")), None)
            if holder is None:
                # 발췌 경계에 걸친 문장은 가장 많이 담은 발췌에 담긴 부분만 인용한다(인용은 늘 원문 그대로).
                holder = max(chunks, key=lambda c: _longest_common_prefix_in(source_sentence, c.get("text") or ""))
                source_sentence = source_sentence[:_longest_common_prefix_in(source_sentence, holder.get("text") or "")]
                if len(source_sentence) < 10:
                    continue
            key = (claim_quote, source_sentence)
            if key in seen:
                continue
            seen.add(key)
            label = f"제{m.group('art')}조" + (f"의{m.group('sub')}" if m.group("sub") else "") + (
                f" 제{m.group('para')}항" if m.group("para") else "")
            words = {"PERMIT": "허용", "PROHIBIT": "금지"}
            out.append({
                "claim_quote": claim_quote,
                "source_id": holder.get("source_id"),
                "source_quote": source_sentence,
                "relationship": "CONTRADICTS",
                "method": "DETERMINISTIC_PROVISION_COMPARISON",
                "provision": {"name": name, "label": label, "claim_direction": claim_modal[0],
                              "source_direction": source_direction},
                "explanation": (f"서면은 「{name}」 {label}이 {words[claim_modal[0]]}한다고 인용하나, 같은 이름의 참고자료 "
                                f"원문 {label}은 {words[source_direction]} 규정이다(허용·금지 방향이 반대). "
                                "참고자료는 사용자 보관 자료이므로 공식 원문과 시행 여부는 따로 확인해야 한다."),
            })
    return out


def _longest_common_prefix_in(sentence: str, text: str) -> int:
    """sentence의 앞부분 중 text에 그대로 들어 있는 가장 긴 길이."""
    low, high = 0, len(sentence)
    while low < high:
        mid = (low + high + 1) // 2
        if sentence[:mid] in text:
            low = mid
        else:
            high = mid - 1
    return low
