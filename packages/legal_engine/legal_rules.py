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

from .polarity import asserted

ENGINE_NAME = "legal_engine.legal_rules"
RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "legal_rules" / "rules.json"
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
            units = [body[s:e].strip() for s, e in sentence_bounds(body)]
        previous = ""
        for unit in units:
            prior, previous = previous, unit
            if not unit:
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
