"""법령 적용 시점(행위시법) 검토(v4 P3).

조문이 개정되어 시행 버전마다 내용이 다를 때, 문서가 조문 내용으로 적은 수치(기간·법정형 등)가 어느 버전과
맞는지 본다. 사건에 어느 버전을 적용할지(부칙·경과규정, 형법 제1조 제2항의 경한 신법 등)는 판단하지 않는다.

기준일
- 사용자가 입력한 기준일(ProjectContext.case_date)이 있으면 그 날짜.
- 없으면 문장이 스스로 '행위 당시·범행 당시·처분 당시'처럼 시점을 밝힌 경우에만, 문서가 그 사건의 날짜로 적은
  날짜가 하나뿐일 때 그 날짜로 문서의 주장을 대조한다(문서 주장의 검증이지, 적용 법령의 자동 확정이 아니다).
- 그 밖에는 기준일 없음.

판정
- 기준일 버전과 일치: 확인(VERIFIED). 현행 버전과 다르면 '현행과 다름'을 함께 적는다.
- 현행 버전과만 일치: 경고(SUSPICIOUS) — 기준일 당시 버전과 다르다.
- 어느 버전과도 불일치: 알려진 모든 버전 값을 적고 CONTRADICTED.
- 기준일이 없고 버전에 따라 결과가 갈리면: TEMPORAL_REVIEW(미확인). CONTRADICTED로 두지 않는다.
형사 사건에는 형법 제1조(제1항 행위시법, 제2항 범죄 후 법률 변경)를 검토 근거로 적는다.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding

from .provision_content import compare_claim_to_provision

ENGINE_NAME = "legal_engine.temporal_review"
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
TIME_QUALIFIER_RE = re.compile(r"(?P<kind>행위|범행|처분|사고|계약|사건)\s*(?:당시|시(?:점)?(?:에|의)?)")
DATE_RE = re.compile(r"(?P<y>(?:19|20)\d{2})\s*\.\s*(?P<m>\d{1,2})\s*\.\s*(?P<d>\d{1,2})\s*\.?")
# 문서가 행위(범행)일로 적은 날짜: '피고인은 2021. 6. 1. …', '2021. 6. 1. … 범행·횡령·공소사실'
ACT_SUBJECT_RE = re.compile(r"(?:피고인|피의자|행위자)\s*(?:은|는|이|가)?\s*$")
ACT_SENTENCE_RE = re.compile(r"공소사실|범행|횡령|절취|편취|폭행|배임|사기|위반행위")
DISPOSITION_AFTER_RE = re.compile(r"^[^.\n]{0,20}?(?:처분|부과|징계)")
CRIMINAL_HINT_RE = re.compile(r"피고인|공소|형사|징역|벌금|법정형|범행")
CRIMINAL_BASIS = ("형법 제1조 제1항(범죄의 성립과 처벌은 행위 시의 법률에 따른다) 및 제2항(범죄 후 법률 변경 시 "
                  "경한 신법)을 기준으로 어느 버전을 적용할지 사람이 검토해야 한다")


def paragraph_text(article_text: str, paragraph: Optional[str]) -> str:
    """조문 본문에서 ①·② 등 항 부분만. 항 표시가 없거나 못 찾으면 조문 전체."""
    if not paragraph or not str(paragraph).isdigit() or not 1 <= int(paragraph) <= len(CIRCLED):
        return article_text or ""
    n = int(paragraph)
    start = (article_text or "").find(CIRCLED[n - 1])
    if start < 0:
        return article_text or ""
    end = (article_text or "").find(CIRCLED[n], start + 1) if n < len(CIRCLED) else -1
    return article_text[start:end if end > 0 else None]


def version_outcomes(citation, versions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    attributes = citation.attributes or {}
    claim = attributes.get("claim_text")
    out = []
    for version in versions:
        outcome = compare_claim_to_provision(
            claim, paragraph_text(version.get("text") or "", citation.paragraph),
            numbers_only=attributes.get("claim_mode") == "PARENTHETICAL_BASIS", subject=attributes.get("claim_subject"))
        out.append({"version": version, "outcome": outcome})
    return out


def _covers(version: Dict[str, Any], when: str) -> bool:
    start, end = version.get("effective_from"), version.get("effective_to")
    return (not start or start <= when) and (not end or when <= end)


def _label(version: Dict[str, Any]) -> str:
    return f"{version.get('effective_from') or '?'}~{version.get('effective_to') or '현행'}"


def _official_values(outcome: Dict[str, Any]) -> str:
    if outcome.get("mismatches"):
        return ", ".join(m["official"] for m in outcome["mismatches"])
    return ", ".join(outcome.get("matched") or []) or "-"


def act_date(text: str, kind: str) -> Optional[str]:
    """문서가 그 시점(행위·처분 등)의 날짜로 적은 날짜가 하나뿐이면 그 날짜."""
    found, charged = set(), set()
    for sentence in re.split(r"(?<=[다음함])\s*[.。]\s*|\n", text or ""):
        for m in DATE_RE.finditer(sentence):
            try:
                value = date(int(m.group("y")), int(m.group("m")), int(m.group("d"))).isoformat()
            except ValueError:
                continue
            if kind in ("행위", "범행", "사건") and (ACT_SUBJECT_RE.search(sentence[:m.start()])
                                                  and ACT_SENTENCE_RE.search(sentence)):
                found.add(value)
                if "공소사실" in sentence:
                    charged.add(value)  # 심판 대상인 공소사실의 행위일이 다른 서술보다 우선한다
            elif kind == "처분" and DISPOSITION_AFTER_RE.match(sentence[m.end():]):
                found.add(value)
    for dates in (charged, found):
        if len(dates) == 1:
            return next(iter(dates))
    return None


def reference_for(citation, sentence: str, document_text: str, case_date: Optional[str]) -> Dict[str, Any]:
    if case_date:
        return {"date": case_date, "basis": "EXPLICIT_REVIEW_DATE"}
    qualifier = TIME_QUALIFIER_RE.search(sentence or "")
    if qualifier:
        when = act_date(document_text, qualifier.group("kind"))
        if when:
            return {"date": when, "basis": "DOCUMENT_ASSERTED",
                    "note": f"문장이 '{qualifier.group(0)}'이라고 밝혀, 문서가 그 시점으로 적은 {when}을 대조 기준으로 썼다"}
    return {"date": None, "basis": "MISSING"}


def review_temporal_application(citation, versions: List[Dict[str, Any]], reference: Dict[str, Any],
                                *, criminal: bool = False) -> Optional[Finding]:
    """버전이 둘 이상이고 문서가 조문 내용을 주장했을 때만 판단한다."""
    if len(versions) < 2:
        return None
    results = [r for r in version_outcomes(citation, versions) if r["outcome"]["status"] in ("VERIFIED", "CONTRADICTED")]
    if len(results) < 2:
        return None
    matching = [r for r in results if r["outcome"]["status"] == "VERIFIED"]
    current = next((r for r in results if not r["version"].get("effective_to")), results[-1])
    when = reference.get("date")
    ref = next((r for r in results if when and _covers(r["version"], when)), None)
    claim = (citation.attributes or {}).get("claim_text") or ""
    values = "; ".join(f"{_label(r['version'])}: {_official_values(r['outcome'])}" for r in results)
    base_detail = f"문서의 주장 '{claim.strip()[:80]}'을 시행 버전별 조문과 대조했다({values})."
    basis_note = reference.get("note") or ""
    legal_basis = [CRIMINAL_BASIS] if criminal else []

    if when and ref is None:
        rule, status, severity, title_tail = ("TEMPORAL.REVIEW_NEEDED", VerificationStatus.UNVERIFIED, Severity.INFO,
                                              f"기준일 {when}에 시행된 버전을 확보하지 못했다")
    elif when and ref in matching:
        differs = ref is not current and current not in matching
        rule, status, severity = "TEMPORAL.REFERENCE_VERSION_MATCH", VerificationStatus.VERIFIED, Severity.INFO
        title_tail = f"기준일 {when} 시행 버전({_label(ref['version'])})과 일치" + (
            f" — 현행과 다름(현행 {_official_values(current['outcome'])})" if differs else "")
    elif when and current in matching:
        rule, status, severity = "TEMPORAL.CURRENT_ONLY_MATCH", VerificationStatus.SUSPICIOUS, Severity.MEDIUM
        title_tail = (f"현행 버전과만 일치 — 기준일 {when} 시행 버전({_label(ref['version'])})은 "
                      f"{_official_values(ref['outcome'])}")
    elif not matching:
        rule, status, severity = "TEMPORAL.NO_VERSION_MATCH", VerificationStatus.CONTRADICTED, Severity.HIGH
        title_tail = f"어느 시행 버전과도 다르다({values})"
    elif not when:
        rule, status, severity = "TEMPORAL.REVIEW_NEEDED", VerificationStatus.UNVERIFIED, Severity.LOW
        title_tail = "시행 버전에 따라 결과가 달라진다. 기준일이 없어 판단하지 않는다"
    else:
        rule, status, severity = "TEMPORAL.OTHER_VERSION_MATCH", VerificationStatus.SUSPICIOUS, Severity.MEDIUM
        title_tail = f"기준일 {when} 버전·현행 버전이 아닌 다른 시행 버전과만 일치"
    features = {"deterministic_rule": True, "rule_id": rule, "reference_date": when,
                "reference_basis": reference.get("basis"), "claim_text": claim,
                "versions": [{"effective_from": r["version"].get("effective_from"),
                              "effective_to": r["version"].get("effective_to"),
                              "status": r["outcome"]["status"], "values": _official_values(r["outcome"])} for r in results],
                "legal_basis": legal_basis, "human_review": True}
    detail = " ".join(x for x in (base_detail, basis_note, *(f"{b}." for b in legal_basis),
                                  "어느 버전이 사건에 적용되는지는 법률 판단이므로 결론을 내리지 않는다.") if x)
    return Finding.create(
        type=FindingType.TEMPORAL_LAW_MISMATCH, status=status, severity=severity,
        evidence_grade=EvidenceGrade.A if status == VerificationStatus.CONTRADICTED else EvidenceGrade.B,
        title=f"법령 적용 시점 검토: {citation.raw_text} — {title_tail}", detail=detail,
        confidence=0.85 if status == VerificationStatus.CONTRADICTED else 0.6, confidence_features=features,
        document_id=citation.document_id, block_id=citation.block_id, page=citation.page, span=citation.span,
        engine=ENGINE_NAME, advisory_only=status == VerificationStatus.VERIFIED,
        tags=["LEGAL", "STATUTE", "TEMPORAL"],
        evidence=[Evidence.create(description=f"시행 버전 {_label(r['version'])}", grade=EvidenceGrade.A,
                                  excerpt=paragraph_text(r["version"].get("text") or "", citation.paragraph)[:300])
                  for r in results[:4]])


def criminal_context(text: str) -> bool:
    return len(CRIMINAL_HINT_RE.findall(text or "")) >= 2
