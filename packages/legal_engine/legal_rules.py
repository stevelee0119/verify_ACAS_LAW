"""법리 규칙 검토(v2 Phase 6).

config/legal_rules/rules.json의 규칙을 서면에 적용한다. 규칙마다 공식 원문 근거(조문·판결요지와 URL)를 싣고,
서면의 주장이 그 근거와 어긋나는 형태인지 본다. 사건의 결론(인용·기각)을 내리지 않으며, 사람 판단이 필요한
규칙(human_review)은 그렇게 표시한다. 산출: claim, rule_id, verdict, basis, confidence.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding, NormalizedDocument
from packages.document_engine.reading_text import build_reading_text, sentence_bounds

from .predicate_semantics import assertion_extent_evidence, past_predicate_evidence, sense_evidence
from .polarity import asserted
from .defense_scope import (
    categorical_patterns, clause_end, conclusion_scopes, linked_conclusion_text, mask_quotations,
    quotation_projection, structural_effect_pattern,
)

ENGINE_NAME = "legal_engine.legal_rules"
RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "legal_rules" / "rules.json"
DEFENSE_GROUPS_PATH = Path(__file__).resolve().parents[2] / "config" / "legal_defense_groups.json"
RELIEF_HEAD_RE = re.compile(r"청\s*구\s*취\s*지")
GROUNDS_HEAD_RE = re.compile(r"청\s*구\s*원\s*인")
DEFENDANT_HEAD_RE = re.compile(r"(?:^|\n)\s*피\s*고")
ITEM_SPLIT_RE = re.compile(r"\n|(?=(?:^|\s)\d{1,2}\.\s)")
CITATION_HINT_RE = re.compile(r"(?:19|20)?\d{2}\s*[가-힣]{1,3}\s*\d{2,6}|제\s*\d+\s*조|헌법재판소|결정")
GRADES = {"A": EvidenceGrade.A, "B": EvidenceGrade.B, "C": EvidenceGrade.C}
CONFIDENCE = {"A": 0.9, "B": 0.75, "C": 0.5}


@lru_cache(maxsize=1)
def load_rules() -> Dict[str, Any]:
    try:
        return json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"rules": [], "sources": {}}


@lru_cache(maxsize=1)
def load_defense_groups() -> Dict[str, Any]:
    """무리한 법리 주장 판별을 위한 법리 군집 및 구조 신호 로드 (TK-26 단일 진실 원천)."""
    try:
        return json.loads(DEFENSE_GROUPS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"clusters": {}, "structural_signals": {}}


@lru_cache(maxsize=1)
def get_defense_overclaim_pattern() -> re.Pattern[str]:
    """legal_defense_groups.json으로부터 체계로 닫힌 법리 군집 기반 과대주장 정규식을 동적 생성."""
    groups = load_defense_groups()
    clusters = groups.get("clusters", {})
    signals = groups.get("structural_signals", {})

    all_articles = set()
    all_terms = set()
    for c in clusters.values():
        all_articles.update(c.get("article_numbers", c.get("articles", [])))
        # 편·장·절 범위(ranges 또는 article_ranges)가 정의된 경우 조문 번호 전체를 체계로 닫아 포함
        for r in c.get("ranges", c.get("article_ranges", [])):
            start = r.get("from") or r.get("start")
            end = r.get("to") or r.get("end")
            if start and end:
                for art_num in range(int(start), int(end) + 1):
                    all_articles.add(str(art_num))
        all_terms.update(c.get("terms", []))

    concessions = "|".join(signals.get("hypothetical_concessions", ["설령", "가사", "백보\\s*양보하여", "가령", "만일", "만약"]))
    connectors = "|".join(signals.get("concession_connectors", ["하더라도", "되더라도", "더라도", "으나", "지만"]))
    p1 = rf"(?P<concession>(?:{concessions})[^.\n]{{0,60}}?(?:{connectors}))"

    art_pattern = "|".join(sorted(all_articles, key=lambda x: -len(x)))
    term_pattern = "|".join(re.escape(t).replace(r"\ ", r"\s*") for t in sorted(all_terms, key=lambda x: -len(x)))
    p2 = rf"(?:(?:헌법|민법|형법)?\s*(?:제\s*(?:{art_pattern})\s*조(?:의\s*\d+)?|상)?\s*(?:{term_pattern})|제\s*(?:{art_pattern})\s*조(?:의\s*\d+)?)"
    requirement_patterns = "|".join(signals.get("stated_requirements", []))
    if requirement_patterns:
        p2 = rf"(?:{p2}|(?:{requirement_patterns}))"

    c_alt = "|".join(categorical_patterns(signals.get("categorical_conclusions", ["당연(?:히)?\\s*무효", "허용될\\s*수\\s*없", "전면\\s*면책", "전액\\s*면제"])))
    # One effect per match lets a later independent authored statement survive
    # a preceding reported claim; effects are scoped separately below.
    p3 = rf"(?:{c_alt}|{structural_effect_pattern()})"

    return re.compile(rf"{p1}[^.\n]{{0,100}}?{p2}[^.\n]{{0,100}}?{p3}")


def _sections(text: str) -> Dict[str, str]:
    relief = RELIEF_HEAD_RE.search(text)
    grounds = GROUNDS_HEAD_RE.search(text, relief.end() if relief else 0)
    defendant = DEFENDANT_HEAD_RE.search(text)
    out = {"BODY": text[grounds.end():] if grounds else text, "RELIEF": "", "PARTIES": ""}
    if relief:
        out["RELIEF"] = text[relief.end():grounds.start() if grounds else min(len(text), relief.end() + 1500)]
        if defendant and defendant.start() < relief.start():
            out["PARTIES"] = text[defendant.end():relief.start()]
    return out


def _is_admin_suit(text: str, relief: str) -> bool:
    """처분의 취소·무효확인을 구하는 행정소송 서면인지(청구취지에 처분과 취소·무효가 함께 있음)."""
    return bool(relief) and "처분" in relief and bool(re.search(r"취소|무효", relief))


def _items(section: str) -> List[str]:
    return [" ".join(part.split()) for part in ITEM_SPLIT_RE.split(section) if part and part.strip()]


def _calculate_dynamic_deadline(doc: NormalizedDocument, claim: str) -> str:
    """문서 텍스트에서 실제 처분일, 통지일, 소제기일을 추출하여 동적으로 일수를 계산한다."""
    from datetime import date
    full_text = getattr(doc, "full_text", "") or ""
    scope_text = claim + "\n" + full_text

    def parse_d(m):
        if not m:
            return None
        y, mo, d = int(m.group("y")), int(m.group("m")), int(m.group("d"))
        try:
            return date(y, mo, d)
        except ValueError:
            return None

    # DATE_RE는 named group (?P<y>\d{4}), (?P<m>\d{1,2}), (?P<d>\d{1,2})
    from packages.claim_engine.evidence_consistency import DATE_RE

    # 1. 처분일 탐지
    disp_date = None
    m_disp = re.search(r"(?:처분일|원처분일|처분을\s*안\s*날|처분(?:이)?\s*있은\s*날)\s*[:：]?\s*" + DATE_RE.pattern, scope_text)
    if m_disp:
        disp_date = parse_d(m_disp)
    else:
        m_disp2 = re.search(DATE_RE.pattern + r"[^.\n]{0,25}?(?:처분|결정)을?\s*(?:받|하|내렸|고지)", scope_text)
        if m_disp2:
            disp_date = parse_d(m_disp2)

    # 2. 통지일/통보일 탐지
    notif_date = None
    m_notif = re.search(r"(?:통지일|통보일|송달일|결과\s*통보)\s*[:：]?\s*" + DATE_RE.pattern, scope_text)
    if m_notif:
        notif_date = parse_d(m_notif)
    else:
        m_notif2 = re.search(DATE_RE.pattern + r"[^.\n]{0,25}?(?:통지|통보|송달)받", scope_text)
        if m_notif2:
            notif_date = parse_d(m_notif2)

    # 3. 소제기일/작성일 탐지
    from packages.claim_engine.evidence_consistency import document_date
    filing_date = document_date(doc)
    if not filing_date:
        all_dates = [parse_d(m) for m in DATE_RE.finditer(full_text)]
        valid_dates = [d for d in all_dates if d]
        filing_date = max(valid_dates) if valid_dates else None

    if not filing_date:
        filing_date = date.today()

    parts = []
    if disp_date and filing_date and filing_date >= disp_date:
        days_from_disp = (filing_date - disp_date).days
        over_str = f"90일 도과({days_from_disp}일 경과, 각하 위험)" if days_from_disp > 90 else f"90일 이내({days_from_disp}일 경과, 기간 준수)"
        parts.append(f"원처분일({disp_date.year}. {disp_date.month}. {disp_date.day}.) 기준: {over_str}")

    if notif_date and filing_date and filing_date >= notif_date:
        days_from_notif = (filing_date - notif_date).days
        within_str = f"90일 이내({days_from_notif}일 경과)" if days_from_notif <= 90 else f"90일 도과({days_from_notif}일 경과)"
        parts.append(f"이의신청 통보일({notif_date.year}. {notif_date.month}. {notif_date.day}.) 기준: {within_str}")

    if parts:
        return " [실제 일수 동적 계산] " + " / ".join(parts) + f" (소제기·작성일: {filing_date.year}. {filing_date.month}. {filing_date.day}.)"
    return ""


def _finding(doc: NormalizedDocument, rule: Dict[str, Any], claim: str, sources: Dict[str, Any]) -> Finding:
    basis = [{"name": name, **sources.get(name, {})} for name in rule.get("basis") or []]
    grade = rule.get("grade", "C")
    features = {"deterministic_rule": True, "rule_id": rule["rule_id"], "verdict": rule["verdict"],
                "claim": claim[:300], "basis": basis, "human_review": bool(rule.get("human_review")),
                # 공식 원문을 아직 받지 못한 근거 조문. 원문 없이 근거로 싣지 않고 이름만 알린다.
                "basis_pending": list(rule.get("basis_pending") or []),
                "confidence": CONFIDENCE.get(grade, 0.5)}
    if rule.get("defense_scope") is not None:
        features["defense_scope"] = rule["defense_scope"]
    kind = FindingType.OVERCLAIM if rule["rule_id"].startswith("GEN.") else FindingType.LEGAL_ARGUMENT_INVALID
    evidence = [Evidence.create(description="서면의 주장", grade=EvidenceGrade.B, document_id=doc.document_id,
                                excerpt=claim[:300], supports=False)]
    for source in basis:
        evidence.append(Evidence.create(description=f"근거: {source['name']} ({source.get('url', '')})",
                                        grade=EvidenceGrade.A, excerpt=str(source.get("text", ""))[:300]))

    explanation = rule.get("explanation", "")
    if rule.get("rule_id") == "ADMIN.DEADLINE_CALCULATION_SCENARIOS":
        dynamic_calc = _calculate_dynamic_deadline(doc, claim)
        if dynamic_calc:
            explanation += dynamic_calc

    return Finding.create(
        type=kind, status=VerificationStatus(rule.get("status", "SUSPICIOUS")),
        severity=Severity.HIGH if grade in ("A", "B") and not rule.get("human_review") else Severity.MEDIUM,
        evidence_grade=GRADES.get(grade, EvidenceGrade.C),
        title=f"법리 검토: {rule['verdict']} — '{claim[:70]}'" + (" (사람 판단 필요)" if rule.get("human_review") else ""),
        detail=explanation + (" 근거: " + "; ".join(b["name"] for b in basis) if basis else "")
        + (f" 근거 조문({', '.join(rule['basis_pending'])})의 공식 원문은 아직 수집하지 않았으므로 원문 대조는 사람이 한다."
           if rule.get("basis_pending") else ""),
        confidence=CONFIDENCE.get(grade, 0.5), confidence_features=features, document_id=doc.document_id,
        engine=ENGINE_NAME, tags=["LEGAL_RULE", rule["rule_id"]] + (["HUMAN_REVIEW"] if rule.get("human_review") else []),
        evidence=evidence,
    )


NEGATION_WORDS_RE = re.compile(
    r"(?:대상이\s*아니(?:다|라고|라|며|었던|면)?|해당하지\s*않(?:는다|았다|고|으며|을)?|"
    r"볼\s*수\s*없(?:다|으며|고|어서)?|인정되지\s*않(?:는다|았다|고)?|"
    r"아니(?:다|라고|라|며|었)|않(?:는다|았다|고|으며)|"
    r"아닙니다|아니었습니다|않습니다|않았습니다|없습니다|볼\s*수\s*없습니다|"
    r"이유\s*없(?:다|어|으므로)?|배척되어야|배제되어야|적용되지\s*않(?:는다|았다)?)"
)


def _is_negated_expression(rule: Dict[str, Any], unit: str, match: re.Match) -> bool:
    """문장이 규칙의 명제를 긍정 주장하는 것이 아니라 부정·배척하는 표현인지 검사한다(과제 4)."""
    pat_str = rule.get("pattern", "")
    rule_targets_negation = bool(re.search(r"않|아니|없|불가|배제", pat_str))
    end_pos = match.end()
    # 매칭부 바로 직후(최대 25자)의 연결 서술어 확인
    immediate_following = unit[end_pos:end_pos + 25].strip()

    if not rule_targets_negation:
        # 규칙이 긍정 명제(예: '위법성 조각', '책임을 진다')인 경우:
        # 매칭부 직후에 '된다고 볼 수 없다', '되는 것은 아니다', '되지 않는다', '라 할 수 없다' 등
        # 해당 명제 자체를 직접 부정하는 서술어가 이어지는 경우에만 부정으로 판정
        direct_negation = re.search(
            r"^(?:된다고|되는|한다고|하는|이라|라|다)\s*(?:볼\s*수\s*없|것은\s*아니|지\s*않|기\s*어렵|없다|아니다)",
            immediate_following,
        )
        if direct_negation:
            return True
        # 또한 '…라는 피고 주장은 이유 없다 / 배척되어야 한다'처럼 상대방 주장을 배척하는 경우
        if re.search(r"(?:주장|항변)(?:은|는|이|가)?\s*(?:이유\s*없|배척|받아들일\s*수\s*없|타당하지\s*않)", unit):
            return True
    else:
        # 규칙 자체가 이미 부정 명제인 경우 (예: '적용되지 않는다', '필요 없다')
        # 상대방 주장을 배척하거나 이중 부정인 경우
        if re.search(r"(?:주장|항변)(?:은|는|이|가)?\s*(?:이유\s*없|배척|타당하지\s*않)|것은\s*아니", unit):
            return True

    return False


# Grammatical boundaries keep quotative -다고/-라고 together and do not
# mistake party nouns ending in -고 for connective endings.
_PAST_STEM_FINALS = "".join(chr(n) for n in range(0xAC00, 0xD7A4)
                          if (n - 0xAC00) % 28 == 20)  # Korean past-tense final ssang-siot.
_ADNOMINAL_FINALS = "".join(chr(n) for n in range(0xAC00, 0xD7A4)
                          if (n - 0xAC00) % 28 == 4)  # Adnominal final nieun.
_REQUIREMENT_CLAUSE_END_RE = re.compile(
    r"[,;.!?\n]|(?:으므로|므로|기에|음에도|는데도|더라도|더니|던데|다가|"
    r"느라고|느라|아서|어서|으나|지만|는데|"
    rf"[{_PAST_STEM_FINALS}](?:고|자|으며)|"
    r"(?:하|되|있|없|않)(?:고|으며|자)|으며|면서|하여|되어|"
    r"(?:을|를)\s+(?:[가-힣]+(?:히|게)\s+)*[가-힣]+자|"
    rf"[{_ADNOMINAL_FINALS}]\s*(?:뒤|후|다음))"
    r"(?=\s|[,;.!?]|$)"
)
# Count negating morphemes, not their overlapping auxiliary phrases:
# e.g. -없지 않- contains two negations, while -지 아니하- contains one.
_REQUIREMENT_NEGATION_RE = re.compile(
    r"않(?:았|으|음|다|고|아|는|은|을|습|지|기)|못(?:하|했|해|한)|"
    r"아니(?:하|었|다|라|며|고|므로|어서)|아닌|아닙|아님|아닐|"
    r"없(?:었|으|음|다|고|어|는|을|습|지|이)|"
    r"(?<![가-힣])(?:안|못)\s+(?=[가-힣])"
)
_REQUIREMENT_NEGATIVE_MODIFIER_RE = re.compile(
    r"(?:없(?:는|었던)|않(?:은|는|았던)|못(?:한|하는|했던)|아닌|"
    r"전무(?:한|했던)|불가(?:능)?(?:한|했던))\s*$"
)
_REQUIREMENT_ADJUNCT_RE = re.compile(
    r"^\s*(?:에\s*(?:따라|의하여|관하여|대하여)|"
    r"(?:의\s*)?(?:직후|직전|이후|이전|후|전|뒤)"
    r"(?:에|부터|까지|에도)?)(?:\s|$)"
)
_REQUIREMENT_BARE_SUFFIX_RE = re.compile(r"[\s이가은는을를도만의,;.!?]*")
_ARGUMENT_CASE_RE = re.compile(r"(?<![가-힣])[가-힣]{2,}(?:이|가|은|는|을|를)(?=\s|[,;.!?]|$)")
_SEMANTIC_ARGUMENT_CASE_RE = re.compile(r"(?<![가-힣])[가-힣]+(?:이|가|은|는|을|를)(?=\s|[,;.!?]|$)")
_DIRECT_NEGATIVE_AUXILIARY_RE = re.compile(
    r"^\s*[을를이가은는도만]*\s*(?:[가-힣]+\s+)*?"
    r"(?P<predicate>[가-힣]+?)(?:지는|지도|지)\s*(?P<auxiliary>않|아니|못)"
)
_DIRECT_EXISTENTIAL_RE = re.compile(r"^\s*[을를이가은는도만]*\s*(?:[가-힣]+\s+)*?(?P<predicate>없|있)")
_FINITE_PREDICATE_RE = re.compile(
    rf"[{_PAST_STEM_FINALS}](?:다|습니다)(?=\s|[,;.!?]|$)|"
    r"(?:한다|된다|이다|있다)(?=\s|[,;.!?]|$)"
)
_EMBEDDED_PREDICATE_RE = re.compile(
    rf"(?:다고|라고|다는|라는|[{_ADNOMINAL_FINALS}])(?=\s|$)"
)


def _has_requirement_predicate(text: str) -> bool:
    return bool(_FINITE_PREDICATE_RE.search(text) or any(
        match.group() not in ",;.!?\n" for match in _REQUIREMENT_CLAUSE_END_RE.finditer(text)
    ))


def _finite_negative_attachment(after: str, match: re.Match | None) -> bool:
    """The auxiliary itself must end the governing clause, not modify a later verb."""
    if match is None:
        return False
    if _EMBEDDED_PREDICATE_RE.search(after[:match.start('predicate')]):
        return False
    auxiliary = after[match.start('auxiliary'):]
    token = re.match(r'[가-힣]+', auxiliary)
    return bool(token and _has_requirement_predicate(token.group()))


def _requirement_extent_observations(
    text: str, argument_start: int, argument_end: int, predicate_end: int,
) -> List[Dict[str, Any]]:
    """Retain extent inside this predicate and immediately on this argument.

    A qualifier inside the same chain can have ambiguous attachment. It blocks
    whole-fulfillment support without proving denial. Prefix attachment never
    skips an intervening subject, object, action or arbitrary word.
    """
    rows = assertion_extent_evidence(text[argument_end:predicate_end])
    for row in rows:
        row['span'] = [argument_end + offset for offset in row['span']]
        row['attachment'] = 'PREDICATE_CHAIN'
    prefix_start = max((boundary.end() for boundary in _REQUIREMENT_CLAUSE_END_RE.finditer(
        text, 0, argument_start)), default=0)
    prefix = text[prefix_start:argument_start]
    cursor = len(prefix)
    attached = []
    for row in reversed(assertion_extent_evidence(prefix)):
        if prefix[row['span'][1]:cursor].strip():
            break
        cursor = row['span'][0]
        row['span'] = [prefix_start + offset for offset in row['span']]
        row['attachment'] = 'ARGUMENT_PREFIX'
        attached.append(row)
    return list(reversed(attached)) + rows


def _defense_requirement_observations(
    unit: str, requirements: List[str], limited_conclusions: List[str],
    polarities: Dict[str, str], *, quotation_uncertain: bool = False,
    projected_text: str | None = None,
) -> List[Dict[str, Any]]:
    """Attach polarity to governing predicates; retain unbound scope as uncertain."""
    if projected_text is None:
        masked, _, uncertain_quote = mask_quotations(unit)
    else:
        masked, uncertain_quote = projected_text, False
    uncertain_quote = uncertain_quote or quotation_uncertain
    conclusions = [
        m.span() for pat in limited_conclusions for m in re.finditer(pat, masked)
    ]
    observations = []
    for pattern in requirements:
        for match in re.finditer(pattern, masked):
            end = clause_end(masked, match.end(), _REQUIREMENT_CLAUSE_END_RE)
            later_conclusions = [
                start for start, _ in conclusions if match.end() <= start < end
            ]
            if later_conclusions:
                end = min(later_conclusions)
            if any(start <= match.start() < stop for start, stop in conclusions):
                continue
            first_end = end
            first_after = masked[match.end():end]
            first_auxiliary = _DIRECT_NEGATIVE_AUXILIARY_RE.match(first_after)
            continuation = bool(first_auxiliary and re.search(
                r"(?:않|아니하|못하)(?:고|으며)\s*$", first_after))
            chain = None
            if continuation:
                # Nonpast -지 않고 can qualify a following act. It is not a
                # completed denial, and an arbitrary final positive act does
                # not certify fulfillment of the requirement either.
                end = clause_end(masked, first_end + 1, _REQUIREMENT_CLAUSE_END_RE)
                later = [left for left, _ in conclusions if match.end() <= left < end]
                if later:
                    end = min(later)
                if masked[first_end:end].strip():
                    chain = {"negative_span": [match.end(), first_end],
                             "continuation_span": [first_end, end],
                             "relation": "UNRESOLVED", "asserted_fulfillment_supported": False}
                else:
                    end = first_end
            after = masked[match.end():end]
            state, reason = "UNCERTAIN", "UNBOUND_PREDICATE"
            semantic_evidence = None
            changed_argument = False
            finite_auxiliary = False
            negations = []
            requires_absence = polarities.get(pattern) == 'absent'
            auxiliary = None
            if _REQUIREMENT_ADJUNCT_RE.match(after):
                state, reason = "CONTEXT", "ADJUNCT"
            elif _REQUIREMENT_NEGATIVE_MODIFIER_RE.search(masked[:match.start()]):
                reason = "NEGATIVE_MODIFIER"
            else:
                negations = list(_REQUIREMENT_NEGATION_RE.finditer(after))
                auxiliary = _DIRECT_NEGATIVE_AUXILIARY_RE.match(after)
                finite_auxiliary = _finite_negative_attachment(after, auxiliary)
                # -지는 is the focused negative connective of this predicate,
                # not a new noun taking the topic particle -는. Independent
                # arguments before the governing token remain visible.
                argument = next((candidate for candidate in _ARGUMENT_CASE_RE.finditer(after)
                                 if not (finite_auxiliary and auxiliary
                                         and auxiliary.start('predicate') <= candidate.start()
                                         and candidate.end() <= auxiliary.start('auxiliary'))), None)
                changed_argument = bool(argument and (not negations or argument.start() < negations[0].start()))
                existential = _DIRECT_EXISTENTIAL_RE.match(after) if not changed_argument else None
                if auxiliary and not negations:
                    # Nonfinite -지 않게/-지 않도록 still needs scope review;
                    # it is not an asserted positive governing predicate.
                    negations = [auxiliary]
                direct_negative = not changed_argument and (
                    finite_auxiliary
                    or existential and existential.group("predicate") == "없"
                )
                if len(negations) > 1:
                    reason = "NESTED_NEGATION"
                elif len(negations) == 1 and direct_negative:
                    state = "POSITIVE" if requires_absence else "DENIED"
                    reason = "ATTACHED_NEGATIVE_PREDICATE"
                elif negations:
                    reason = "CHANGED_ARGUMENT" if changed_argument else "UNBOUND_NEGATION"
                elif requires_absence:
                    if existential and existential.group("predicate") == "있":
                        state, reason = "DENIED", "DISQUALIFYING_PRESENCE"
                    else:
                        reason = "UNBOUND_ABSENCE_PREDICATE"
                elif (_REQUIREMENT_BARE_SUFFIX_RE.fullmatch(after)
                      and not _REQUIREMENT_CLAUSE_END_RE.search(match.group())):
                    reason = "BARE_REFERENCE"
                elif changed_argument:
                    reason = "CHANGED_ARGUMENT"
                elif not _has_requirement_predicate(match.group() + after):
                    reason = "UNBOUND_PREDICATE"
                else:
                    state, reason = "POSITIVE", "ASSERTED_PREDICATE"
            syntax_state = state
            if chain and state != "CONTEXT" and reason != "NEGATIVE_MODIFIER":
                state, reason = "UNCERTAIN", "PREDICATE_CHAIN_RELATION_UNRESOLVED"
            # Public lexical senses may support the final assertion, never an
            # arbitrary positive act sharing the object. Changed arguments,
            # embedding, prospectivity and reported scope remain unresolved.
            tokens = list(re.finditer(r"[가-힣]+", after))
            independent_argument = any(
                not (finite_auxiliary and auxiliary
                     and auxiliary.start('predicate') <= candidate.start()
                     and candidate.end() <= auxiliary.start('auxiliary'))
                for candidate in _SEMANTIC_ARGUMENT_CASE_RE.finditer(after))
            object_case = re.match(r"^\s*(?P<case>[을를])(?:도|만)?(?=\s)", after)
            event_object = bool(object_case
                                and not changed_argument and not independent_argument
                                and not _EMBEDDED_PREDICATE_RE.search(after)
                                and not requires_absence
                                and not _REQUIREMENT_NEGATIVE_MODIFIER_RE.search(masked[:match.start()])
                                and state != "CONTEXT" and reason != "NEGATIVE_MODIFIER")
            final_token = tokens[-1] if tokens else None
            if final_token:
                semantic_evidence = past_predicate_evidence(final_token.group(), event_object=event_object)
                if (semantic_evidence and any(sense['frame'] == 'STATE_SUBJECT' for sense in semantic_evidence['senses'])
                        and re.search(r"[가-힣]+(?:으로|로)(?=\s)", after)):
                    semantic_evidence = past_predicate_evidence(final_token.group(), event_object=False)
                    semantic_evidence['frame_conflict'] = True
                if semantic_evidence:
                    extent = _requirement_extent_observations(
                        masked, match.start(), match.end(), match.end() + final_token.start())
                    if extent:
                        semantic_evidence['scope_limitations'] = extent
                        semantic_evidence['supports_asserted_fulfillment'] = False
                        semantic_evidence['total_completion_asserted'] = False
                    semantic_evidence['argument_span'] = list(match.span())
                    semantic_evidence['case_span'] = ([match.end() + offset for offset in object_case.span('case')]
                                                      if object_case else None)
                    semantic_evidence['argument_binding'] = ('MATCHED_REQUIREMENT_DIRECT_OBJECT'
                                                             if event_object else 'UNRESOLVED')
                    semantic_evidence['span'] = [match.end() + offset for offset in final_token.span()]
                    prior_predicate = first_auxiliary.group('predicate') if chain and first_auxiliary else ''
                    prior_meaning = sense_evidence(prior_predicate + '다', event_object=event_object)
                    prior_head = prior_predicate[:-1] if prior_predicate.endswith('하') else prior_predicate
                    same_event_denial = (prior_predicate == '하'
                                         or prior_meaning['supports_asserted_fulfillment']
                                         or bool(prior_head and match.group().endswith(prior_head)))
                    if chain and (event_object and len(negations) == 1
                                  and semantic_evidence['supports_asserted_fulfillment']
                                  and not same_event_denial and not uncertain_quote):
                        state, reason = "POSITIVE", "ASSERTED_REQUIREMENT_REALIZATION"
                        chain['relation'] = 'FINAL_REQUIREMENT_REALIZATION'
                        chain['asserted_fulfillment_supported'] = True
                    elif state == 'POSITIVE' and not negations:
                        if semantic_evidence['supports_asserted_fulfillment']:
                            reason = 'ASSERTED_REQUIREMENT_REALIZATION'
                        elif (event_object and not extent
                              and any(sense['category'] in {'COMPLETION', 'REALIZATION'}
                                      for sense in semantic_evidence['selected_senses'])):
                            # Preserve existing normal single-clause assertions.
                            # An unresolved transitive homonym is not a new
                            # source-backed fulfillment certificate.
                            reason = 'LEGACY_ASSERTED_PREDICATE_SENSE_UNRESOLVED'
                        else:
                            state, reason = 'UNCERTAIN', 'FINAL_ACT_NOT_REQUIREMENT_REALIZATION'
            if uncertain_quote and state != "CONTEXT":
                state, reason = "UNCERTAIN", "UNRESOLVED_QUOTATION"
            observations.append({"span": list(match.span()), "predicate_span": [match.end(), end],
                                 "state": state, "reason": reason, "legacy_syntax_state": syntax_state})
            if semantic_evidence:
                observations[-1]['predicate_semantics'] = semantic_evidence
            if chain:
                observations[-1]["predicate_chain"] = chain
            if auxiliary and reason == "ATTACHED_NEGATIVE_PREDICATE":
                observations[-1]['governing_predicate_span'] = [match.end() + offset for offset in auxiliary.span('predicate')]
                observations[-1]['negative_auxiliary_span'] = [match.end() + offset for offset in auxiliary.span('auxiliary')]
            if reason == "NEGATIVE_MODIFIER":
                start = max((m.end() for m in _REQUIREMENT_CLAUSE_END_RE.finditer(masked)
                             if m.end() <= match.start()), default=0)
                observations[-1]["modifier_span"] = [start, match.start()]
    return observations


def _defense_requirement_state(
    unit: str, requirements: List[str], limited_conclusions: List[str], polarities: Dict[str, str],
) -> tuple[bool, bool, bool]:
    states = {row["state"] for row in _defense_requirement_observations(unit, requirements, limited_conclusions, polarities)}
    return "POSITIVE" in states, "DENIED" in states, "UNCERTAIN" in states


def _review_defense_statement(
    doc: NormalizedDocument, rule: Dict[str, Any], unit: str, pattern: re.Pattern[str],
    prior: str, sources: Dict[str, Any], seen: set,
    *, context_link: Dict[str, Any] | None = None,
) -> List[Finding]:
    """Review independent authored spans; a reported statement cannot mask a rebuttal."""
    masked, unit_quotes = quotation_projection(unit, previous=prior)
    matches = list(pattern.finditer(masked))
    signals = load_defense_groups().get("structural_signals", {})
    req_list, lim_list = signals.get("stated_requirements", []), signals.get("limited_conclusions", [])
    findings = []
    for index, match in enumerate(matches):
        stop = matches[index + 1].start() if index + 1 < len(matches) else len(unit)
        claim = unit[match.start():stop]
        local_masked = masked[match.start():stop]
        quote_rows = [{'span': [max(0, row['span'][0] - match.start()), min(len(claim), row['span'][1] - match.start())],
                       'role': row['role']} for row in unit_quotes
                      if row['span'][0] < stop and row['span'][1] > match.start()]
        uncertain_quote = any(row['role'] in {'UNCERTAIN', 'UNCLOSED'} for row in quote_rows)
        local_match = pattern.search(local_masked)
        if local_match is None:
            continue
        observations = _defense_requirement_observations(
            claim, req_list, lim_list, signals.get("requirement_polarities", {}),
            quotation_uncertain=uncertain_quote, projected_text=local_masked,
        )
        states = {row["state"] for row in observations}
        positive, denied, uncertain = "POSITIVE" in states, "DENIED" in states, "UNCERTAIN" in states
        has_lim = any(re.search(pat, local_masked) for pat in lim_list)
        excluded = [(row["span"][0], row["predicate_span"][1]) for row in observations]
        excluded.extend(tuple(row["modifier_span"]) for row in observations if "modifier_span" in row)
        scopes = conclusion_scopes(claim, signals.get("categorical_conclusions", []), lim_list,
                                  _REQUIREMENT_CLAUSE_END_RE, previous=prior,
                                  start=local_match.end("concession"), speaker_prefix=masked[:match.start()],
                                  excluded_spans=excluded, projected_text=local_masked,
                                  quotation_uncertain=uncertain_quote, structural_anchor=True)
        if context_link and not any(
            row['authored'] and row['span'][0] + match.start() >= context_link['current_sentence_span'][0]
            for row in scopes):
            continue
        if not scopes or (not any(row["authored"] for row in scopes) and not uncertain_quote):
            continue
        scope_uncertain = any(row['authored'] and row.get('scope_uncertain', False) for row in scopes)
        is_extended = has_lim and any(row["authored"] and not row["limited"] for row in scopes)
        established_unlimited = any(row['authored'] and not row['limited']
                                    and not row.get('scope_uncertain', False) for row in scopes)
        needs_scope_review = scope_uncertain and not denied and not established_unlimited
        if positive and not denied and not uncertain and not uncertain_quote and has_lim and not is_extended:
            continue
        mod_rule = dict(rule)
        mod_rule["defense_scope"] = {"requirements": observations, "conclusions": scopes,
                                     "uncertain": uncertain or uncertain_quote or scope_uncertain or not (positive or denied),
                                     "quotation_spans": [row['span'] for row in quote_rows],
                                     "quotations": quote_rows,
                                     "uncertain_quotation": uncertain_quote,
                                     "statement_span": [match.start(), stop]}
        if context_link:
            mod_rule['defense_scope']['context_link'] = context_link
        if uncertain_quote or needs_scope_review or (has_lim and not denied and not is_extended and (not positive or uncertain)):
            mod_rule["verdict"] = "요건 확인 요청 (구체적 요건 소명 확인 필요)"
            mod_rule["explanation"] = (
                "항변의 결론이 해당 채무로 한정되어 있으나 법정 요건에 관한 구체적 근거 또는 소명이 부족하므로, "
                "관련 요건의 충족 여부를 확인해야 합니다."
            )
        if needs_scope_review:
            mod_rule['verdict'] = "요건 확인 요청 (연결된 결론의 법적 효과·범위 확인 필요)"
            mod_rule['explanation'] = (
                "법적 항변과 연결된 부정적 결론이 있으나, "
                "사실행위 부정인지 별도 법적 효과의 주장인지 확정되지 않아 결론의 범위를 확인해야 합니다."
            )
        key = (rule["rule_id"], claim[:80])
        if key not in seen:
            seen.add(key)
            findings.append(_finding(doc, mod_rule, claim, sources))
    return findings


def review_legal_rules(doc: NormalizedDocument) -> List[Finding]:
    table = load_rules()
    sources = table.get("sources") or {}
    text = build_reading_text(doc).text
    sections = _sections(text)
    admin = _is_admin_suit(text, sections["RELIEF"])
    # 금전 지급·배상을 구하는 민사 청구취지(행정소송 서면은 제외)
    civil = (bool(sections["RELIEF"]) and not admin
             and bool(re.search(r"지급하라|지급한다|배상하라|반환하라", sections["RELIEF"])))
    out: List[Finding] = []
    seen: set = set()
    for rule in table.get("rules") or []:
        if rule.get("requires_admin_suit") and not admin:
            continue
        if rule.get("requires_civil_suit") and not civil:
            continue
        if rule.get("context") and not re.search(rule["context"], text):
            continue
        if rule.get("rule_id") == "GEN.DEFENSE_OVERCLAIM_WITHOUT_REQUIREMENTS":
            pattern = get_defense_overclaim_pattern()
        else:
            pattern = re.compile(rule["pattern"])
        scope = rule.get("scope", "BODY")
        if scope == "RELIEF_ALL":
            relief = sections["RELIEF"]
            if pattern.search(relief) and not re.search(rule.get("absent_pattern", "$^"), relief):
                claim = next((item for item in _items(relief) if pattern.search(item)), relief)
                out.append(_finding(doc, rule, claim, sources))
            continue
        if scope in ("RELIEF", "PARTIES"):
            units = _items(sections[scope])
        else:
            body = sections["BODY"]
            # 하드 래핑 줄바꿈 결합: 문장 종결 부호 없이 단순 개행된 줄을 공백으로 이어 문장 단절 방지
            body_unwrapped = re.sub(r"(?<![.\?!:;])\n(?!\s*(?:\d+[\.)]|[가-하][\.)]|[-•*]))", " ", body)
            units = [body_unwrapped[s:e].strip() for s, e in sentence_bounds(body_unwrapped)]
        previous = ""
        for unit in units:
            prior, previous = previous, unit
            if not unit:
                continue
            if rule.get("rule_id") == "GEN.DEFENSE_OVERCLAIM_WITHOUT_REQUIREMENTS":
                signals = load_defense_groups().get('structural_signals', {})
                linked = None if pattern.search(unit) else linked_conclusion_text(
                    prior, unit, signals.get('categorical_conclusions', []),
                    signals.get('limited_conclusions', []), _REQUIREMENT_CLAUSE_END_RE, pattern)
                review_unit, context_link = linked if linked else (unit, None)
                out.extend(_review_defense_statement(doc, rule, review_unit, pattern, prior, sources, seen,
                                                     context_link=context_link))
                continue
            m = pattern.search(unit)
            if not m:
                continue
            # 부정 표현('아니다', '않는다', '대상이 아니라고' 등) 처리 (과제 4 및 v5 극성 검사)
            if _is_negated_expression(rule, unit, m):
                continue
            # 부정·전달(판례·상대방 주장)·가정으로 쓴 명제는 작성자의 주장이 아니다(v5 3-2). 청구취지·당사자 칸은 제외.
            if scope == "BODY" and not asserted(unit, pattern, previous=prior):
                continue
            if rule.get("requires_no_citation") and CITATION_HINT_RE.search(unit):
                continue
            # 법이 정한 예외를 근거로 든 문장은 규칙이 겨냥한 무리한 주장이 아니다(추가지시 G4 오탐 방지).
            if rule.get("unless") and re.search(rule["unless"], unit):
                continue

            key = (rule["rule_id"], unit[:80])
            if key in seen:
                continue
            seen.add(key)
            out.append(_finding(doc, rule, unit, sources))
    return out
