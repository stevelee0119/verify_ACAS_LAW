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
    return Finding.create(
        type=kind, status=VerificationStatus(rule.get("status", "SUSPICIOUS")),
        severity=Severity.HIGH if grade in ("A", "B") and not rule.get("human_review") else Severity.MEDIUM,
        evidence_grade=GRADES.get(grade, EvidenceGrade.C),
        title=f"법리 검토: {rule['verdict']} — '{claim[:70]}'" + (" (사람 판단 필요)" if rule.get("human_review") else ""),
        detail=rule.get("explanation", "") + (" 근거: " + "; ".join(b["name"] for b in basis) if basis else "")
        + (f" 근거 조문({', '.join(rule['basis_pending'])})의 공식 원문은 아직 수집하지 않았으므로 원문 대조는 사람이 한다."
           if rule.get("basis_pending") else ""),
        confidence=CONFIDENCE.get(grade, 0.5), confidence_features=features, document_id=doc.document_id,
        engine=ENGINE_NAME, tags=["LEGAL_RULE", rule["rule_id"]] + (["HUMAN_REVIEW"] if rule.get("human_review") else []),
        evidence=evidence,
    )


def review_legal_rules(doc: NormalizedDocument) -> List[Finding]:
    table = load_rules()
    sources = table.get("sources") or {}
    text = build_reading_text(doc).text
    sections = _sections(text)
    admin = _is_admin_suit(text, sections["RELIEF"])
    out: List[Finding] = []
    seen: set = set()
    for rule in table.get("rules") or []:
        if rule.get("requires_admin_suit") and not admin:
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
        for unit in units:
            if not unit or not pattern.search(unit):
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
