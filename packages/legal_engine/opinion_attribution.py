"""판결의 의견 귀속과 결론 방향 검사(v3 D3).

전원합의체 판결은 다수의견과 반대의견·별개의견·보충의견이 한 판결에 함께 실린다. 서면이 반대의견의 취지를
그 판결의 판시처럼 요약하면, 판결을 인용했지만 법리는 정반대가 된다. 판결 전체와의 유사도 하나로는 이것을
가려낼 수 없다(여러 의견이 같은 쟁점을 같은 낱말로 다루므로).

1. 의견 구간 분리: 판결 전문의 "대법관 …의 반대의견은 다음과 같다", 판결요지의 "[다수의견]",
   "[대법관 …의 반대의견]" 표지로 다수의견·반대의견·별개의견·보충의견 구간을 나눈다. 첫 표지 앞의 이유 부분은
   다수의견이다. '반대의견에 대한 보충의견'은 반대의견 쪽으로 센다.
2. 귀속: 서면의 요약 문장을 각 구간과 글자 2-gram 포함률(구간 안 가장 비슷한 창)로 비교한다. 반대의견이
   다수의견보다 뚜렷이 가까우면 MISATTRIBUTED_OPINION이다.
3. 결론 방향: 판시사항·판결요지의 "…인지 여부(적극)/(소극)/(원칙적 소극)" 쟁점 가운데 서면 문장과 같은 쟁점을
   고르고, 서면이 그 쟁점에 대해 판결과 반대 방향으로 단정하는지 부정 표현의 짝수·홀수로 비교한다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

OPINION_KINDS = {"반대의견": "DISSENT", "별개의견": "CONCURRING", "보충의견": "SUPPLEMENTARY",
                 "반대보충의견": "DISSENT", "다수의견": "MAJORITY"}
FULL_MARKER_RE = re.compile(
    r"(?:\d+\s*\.\s*)?(?P<target>(?:다수의견|반대의견|별개의견)에\s*대한\s*)?(?:대법관\s*[^.\n]{1,80}?의\s*)?"
    r"(?P<kind>반대보충의견|반대의견|별개의견|보충의견)은\s*다음과\s*같다\s*\.?")
SUMMARY_MARKER_RE = re.compile(
    r"\[\s*(?P<target>(?:다수의견|반대의견|별개의견)에\s*대한\s*)?(?:대법관\s*[^\]]{1,80}?의\s*)?"
    r"(?P<kind>다수의견|반대보충의견|반대의견|별개의견|보충의견)\s*\]")
DROP_RE = re.compile(r"[\s\"'“”‘’.,·「」『』()\[\]<>《》~\-]")
REPORTING_TAIL_RE = re.compile(
    r"[\s\"'“”‘’]*(?:(?:(?:이?라|다|하)고\s*)?(?:판시|판단|설시)(?:하였|했|한)(?:다|습니다)"
    r"|(?:(?:이?라|다|하)고\s*)(?:보았|밝혔|하였|했)(?:다|습니다))\s*\.?\s*$")
CLAUSE_SPLIT_RE = re.compile(r"\s*[,，;]\s*|\s+(?:하며|이며)\s+")
FINAL_NEGATION_RE = re.compile(r"않|아니|없|못|불요")
FINAL_WINDOW = 7  # 절 끝 서술어(압축 글자 수)만 보고 긍정·부정을 가린다. 앞의 종속절 부정("거치지 않은 채")은 보지 않는다
NEGATION_RE = re.compile(r"않|아니|없|불요|못")
ISSUE_RE = re.compile(r"(?P<issue>[^\[\]]+?)\s*여부\s*\(\s*(?P<principled>원칙적\s*)?(?P<direction>적극|소극)\s*\)")

MISATTRIBUTION_MARGIN = 0.1   # 반대의견이 다수의견보다 이만큼 더 가까워야 한다
MISATTRIBUTION_FLOOR = 0.5    # 그리고 반대의견과 절반 이상 겹쳐야 한다
ISSUE_MATCH_FLOOR = 0.3       # 서면 절이 판시사항 쟁점과 이만큼 겹쳐야 같은 쟁점으로 본다
ISSUE_STRONG = 0.45           # 이 이상이면 확정(B), 그 아래는 사람 확인(C)
ISSUE_MARGIN = 0.08           # 두 번째로 가까운 쟁점보다 이만큼 앞서야 한다
STOP_STEMS = {"대하", "있는", "하는", "하고", "것이", "것은", "것으", "경우", "그", "이를", "으로", "에서", "여부",
              "등", "및", "수", "할", "한", "된다", "이다", "있다", "없다"}


def _compact(text: str) -> str:
    return DROP_RE.sub("", text or "")


def _bigrams(text: str) -> set:
    compact = _compact(text)
    return {compact[i:i + 2] for i in range(len(compact) - 1)}


def _claim_core(claim: str) -> str:
    """서면 문장에서 '…라고 판시하였다' 같은 전달 표현을 뗀 주장 부분."""
    return REPORTING_TAIL_RE.sub("", (claim or "").strip()).strip()


def _containment(claim: str, section: str) -> float:
    """claim의 2-gram이 section 안 가장 비슷한 창에 들어 있는 비율."""
    grams = _bigrams(claim)
    body = _compact(section)
    if not grams or not body:
        return 0.0
    width = max(len(_compact(claim)) * 2, 20)
    step = max(1, width // 4)
    best = 0.0
    for start in range(0, max(1, len(body) - width + 1), step):
        window = body[start:start + width]
        window_grams = {window[i:i + 2] for i in range(len(window) - 1)}
        best = max(best, len(grams & window_grams) / len(grams))
    return best


def _kind(match: re.Match) -> str:
    kind = OPINION_KINDS[match.group("kind").replace(" ", "")]
    target = (match.group("target") or "").replace(" ", "")
    if kind == "SUPPLEMENTARY" and target.startswith("반대의견"):
        return "DISSENT"  # 반대의견에 대한 보충의견은 반대의견 쪽 논거다
    return kind


def split_opinions(text: str) -> Dict[str, Any]:
    """판결 전문·판결요지를 의견 구간으로 나눈다. {'MAJORITY': str, 'DISSENT': [...], ...}"""
    out: Dict[str, Any] = {"MAJORITY": "", "DISSENT": [], "CONCURRING": [], "SUPPLEMENTARY": []}
    text = text or ""
    markers = sorted(list(FULL_MARKER_RE.finditer(text)) + list(SUMMARY_MARKER_RE.finditer(text)),
                     key=lambda m: m.start())
    if not markers:
        out["MAJORITY"] = text
        return out
    majority = [text[:markers[0].start()]]
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        body = text[marker.end():end].strip()
        kind = _kind(marker)
        if kind == "MAJORITY":
            majority.append(body)
        else:
            out[kind].append(body)
    out["MAJORITY"] = " ".join(part.strip() for part in majority if part.strip())
    return out


def attribute_claim(claim: str, full_text: str, summary: str = "") -> Dict[str, Any]:
    """서면의 판결 요약이 어느 의견에 가장 가까운지. verdict는 MISATTRIBUTED_OPINION 또는 None."""
    parts = [split_opinions(full_text), split_opinions(summary)]
    majority = " ".join(p["MAJORITY"] for p in parts)
    sections = {kind: [s for p in parts for s in p[kind]] for kind in ("DISSENT", "CONCURRING", "SUPPLEMENTARY")}
    core = _claim_core(claim)
    scores = {"MAJORITY": round(_containment(core, majority), 3)}
    for kind, texts in sections.items():
        if texts:
            scores[kind] = round(max(_containment(core, t) for t in texts), 3)
    closest = max(scores, key=scores.get)
    verdict = None
    if "DISSENT" in scores and closest == "DISSENT" and scores["DISSENT"] >= MISATTRIBUTION_FLOOR \
            and scores["DISSENT"] - scores["MAJORITY"] >= MISATTRIBUTION_MARGIN:
        verdict = "MISATTRIBUTED_OPINION"
    return {"verdict": verdict, "closest": closest, "scores": scores,
            "dissent_excerpt": (sections["DISSENT"][0][:300] if sections["DISSENT"] else ""),
            "majority_excerpt": majority[:300]}


def holding_issues(holding: str) -> List[Dict[str, Any]]:
    """판시사항·판결요지의 '…인지 여부(적극/소극)' 쟁점."""
    issues = []
    for chunk in re.split(r"\[\s*\d+\s*\]", holding or ""):
        for m in ISSUE_RE.finditer(chunk):
            issues.append({"issue": m.group("issue").strip(" ,/;"), "direction": m.group("direction"),
                           "principled": bool(m.group("principled"))})
    return issues


def _stems(text: str) -> set:
    """어절의 앞 두 글자(조사·어미를 뗀 어간 근사). 서로 다르게 풀어 쓴 같은 쟁점을 잇는다."""
    words = re.findall(r"[가-힣]+", text or "")
    return {w[:2] for w in words if w[:2] not in STOP_STEMS and len(w) >= 1} - {""}


def _overlap(a: str, b: str) -> float:
    ga, gb = _bigrams(a), _bigrams(b)
    bigram = len(ga & gb) / min(len(ga), len(gb)) if ga and gb else 0.0
    sa, sb = _stems(a), _stems(b)
    stem = len(sa & sb) / len(sa) if sa and sb else 0.0
    return max(bigram, stem)


def _clause_negated(text: str) -> bool:
    compact = re.sub(r"(?:지|는지|인지|한지|할지)$", "", _compact(text))
    return bool(FINAL_NEGATION_RE.search(compact[-FINAL_WINDOW:]))


def _clauses(core: str) -> List[str]:
    parts = [part.strip(" \"'“”‘’") for part in CLAUSE_SPLIT_RE.split(core or "")]
    return [part for part in parts if len(_compact(part)) >= 6]


def direction_conflict(claim: str, holding: str) -> Optional[Dict[str, Any]]:
    """서면이 판시사항 쟁점에 대해 판결과 반대 방향으로 단정하면 그 쟁점과 방향을, 아니면 None.

    주장을 절로 나누고, 절마다 가장 가까운 쟁점과 비교한다. 긍정·부정은 절 끝 서술어로만 가린다
    ("거치지 않은 채 … 징계사유가 된다"는 긍정). 쟁점 문장도 "…인지 여부" 앞 서술어로 가린다.
    """
    issues = holding_issues(holding)
    clauses = _clauses(_claim_core(claim))
    if not issues or not clauses:
        return None
    found = []
    for clause in clauses:
        ranked = sorted(issues, key=lambda i: _overlap(clause, i["issue"]), reverse=True)
        best = ranked[0]
        similarity = _overlap(clause, best["issue"])
        runner_up = _overlap(clause, ranked[1]["issue"]) if len(ranked) > 1 else 0.0
        if similarity < ISSUE_MATCH_FLOOR or similarity - runner_up < ISSUE_MARGIN:
            continue
        # 쟁점을 긍정하는 서면 절: 절과 쟁점의 끝 서술어 부정 여부가 같다.
        claim_affirms = _clause_negated(clause) == _clause_negated(best["issue"])
        if claim_affirms == (best["direction"] == "적극"):
            continue
        found.append({"issue": best["issue"], "holding_direction": best["direction"],
                      "principled": best["principled"], "claim_direction": "적극" if claim_affirms else "소극",
                      "issue_similarity": round(similarity, 3), "clause": clause,
                      "strong": similarity >= ISSUE_STRONG})
    if not found:
        return None
    return sorted(found, key=lambda f: (not f["strong"], f["principled"], -f["issue_similarity"]))[0]
