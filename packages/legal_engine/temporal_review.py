"""법령 적용 시점(행위시법) 검토(v4 P3).

조문이 개정되어 시행 버전마다 내용이 다를 때, 문서가 조문 내용으로 적은 수치(기간·법정형 등)가 어느 버전과
맞는지 본다. 사건에 어느 버전을 적용할지(부칙·경과규정, 형법 제1조 제2항의 경한 신법 등)는 판단하지 않는다.

기준일(우선순위)
1. 사용자가 입력한 기준일(ProjectContext.case_date).
2. 문장이 스스로 '행위 당시·범행 당시·처분 당시'처럼 시점을 밝히고, 문서가 그 시점으로 적은 날짜가 하나뿐일 때.
3. 문서에서 추정한 후보(v4 검토 4항): 범행일·처분일·불법행위일·원심 선고일을 뽑고, 인용 법령의 성격에 맞는
   종류(소송법 → 원심 선고일, 형사 → 범행일, 처분 서술 → 처분일, 그 밖 → 불법행위일)의 날짜가 하나뿐이면 그 날짜.
   추정 기준일은 '문서에서 추정'으로 표시하고, 어느 시행 버전이 적용되는지는 결론 내리지 않는다.
4. 그 밖에는 기준일 불명 → TEMPORAL_REVIEW 경고(후보 목록을 함께 적는다).

시행 버전
- 내부 Mirror에 버전이 둘 이상 있으면 그것을, 없으면 국가법령정보 법령 연혁(eflaw, 시행일 기준 목록)에서
  기준일 시행본(구법)과 현행본을 받아 조문을 대조한다(official_versions). 기준일이 없으면 현행본과 직전 시행본을 받는다.

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


REFERENCE_KINDS = {"OFFENSE": "범행일", "DISPOSITION": "처분일", "TORT": "불법행위일", "LOWER_JUDGMENT": "원심 선고일"}
TORT_SENTENCE_RE = re.compile(r"사고|불법행위|손해가\s*발생|상해를\s*입|부상을\s*입|폭행을\s*당")
LOWER_JUDGMENT_RE = re.compile(r"원심|제1심|1심|원판결")
PROCEDURAL_LAW_RE = re.compile(r"소송법$|소송규칙$")


def _sentences(text: str):
    return [s for s in re.split(r"(?<=[다음함])\s*[.。]\s*|\n", text or "") if s.strip()]


def reference_candidates(text: str) -> List[Dict[str, Any]]:
    """문서가 적은 범행일·처분일·불법행위일·원심 선고일 후보. 같은 날짜·종류는 한 번만."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for sentence in _sentences(text):
        for m in DATE_RE.finditer(sentence):
            try:
                value = date(int(m.group("y")), int(m.group("m")), int(m.group("d"))).isoformat()
            except ValueError:
                continue
            before, after = sentence[:m.start()], sentence[m.end():]
            kinds = []
            if ACT_SUBJECT_RE.search(before) and ACT_SENTENCE_RE.search(sentence):
                kinds.append("OFFENSE")
            if DISPOSITION_AFTER_RE.match(after):
                kinds.append("DISPOSITION")
            if LOWER_JUDGMENT_RE.search(sentence) and re.match(r"^\s*(?:에\s*)?선고", after):
                kinds.append("LOWER_JUDGMENT")
            if TORT_SENTENCE_RE.search(sentence) and not kinds and not re.match(r"^\s*(?:에\s*)?선고", after):
                kinds.append("TORT")
            for kind in kinds:
                if (kind, value) not in seen:
                    seen.add((kind, value))
                    out.append({"kind": kind, "label": REFERENCE_KINDS[kind], "date": value,
                                "excerpt": sentence.strip()[:120]})
    return out


def preferred_kind(citation, candidates: List[Dict[str, Any]], *, criminal: bool) -> Optional[str]:
    """인용 법령의 성격에 맞는 기준일 종류. 문서에 그 종류의 후보가 없으면 None."""
    kinds = {c["kind"] for c in candidates}
    law = (getattr(citation, "law_name", "") or "").replace(" ", "")
    if PROCEDURAL_LAW_RE.search(law):
        order = ["LOWER_JUDGMENT"]
    elif criminal:
        order = ["OFFENSE"]
    else:
        order = ["DISPOSITION", "TORT"]
    return next((k for k in order if k in kinds), None)


def inferred_reference(citation, text: str, *, criminal: bool) -> Dict[str, Any]:
    candidates = reference_candidates(text)
    kind = preferred_kind(citation, candidates, criminal=criminal)
    if kind is None:
        return {"date": None, "basis": "MISSING", "candidates": candidates}
    dates = sorted({c["date"] for c in candidates if c["kind"] == kind})
    if len(dates) != 1:
        return {"date": None, "basis": "AMBIGUOUS", "kind": kind, "candidates": candidates,
                "note": f"{REFERENCE_KINDS[kind]} 후보가 {len(dates)}개({', '.join(dates)})라 기준일을 정하지 않았다"}
    return {"date": dates[0], "basis": "DOCUMENT_INFERRED", "kind": kind, "candidates": candidates,
            "note": f"문서에서 {REFERENCE_KINDS[kind]}로 추정한 {dates[0]}을 대조 기준으로 썼다(추정 기준일)"}


def reference_for(citation, sentence: str, document_text: str, case_date: Optional[str], *,
                  criminal: bool = False, infer: bool = True) -> Dict[str, Any]:
    if case_date:
        return {"date": case_date, "basis": "EXPLICIT_REVIEW_DATE"}
    qualifier = TIME_QUALIFIER_RE.search(sentence or "")
    if qualifier:
        when = act_date(document_text, qualifier.group("kind"))
        if when:
            return {"date": when, "basis": "DOCUMENT_ASSERTED",
                    "note": f"문장이 '{qualifier.group(0)}'이라고 밝혀, 문서가 그 시점으로 적은 {when}을 대조 기준으로 썼다"}
    if infer:
        return inferred_reference(citation, document_text, criminal=criminal)
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
    elif len(matching) == len(results):
        rule, status, severity = "TEMPORAL.ALL_VERSIONS_MATCH", VerificationStatus.VERIFIED, Severity.INFO
        title_tail = "대조한 모든 시행 버전과 일치(적용 시점과 무관)"
    elif not when:
        rule, status, severity = "TEMPORAL.REVIEW_NEEDED", VerificationStatus.UNVERIFIED, Severity.LOW
        candidates = reference.get("candidates") or []
        listed = ", ".join(f"{c['label']} {c['date']}" for c in candidates[:6]) or "문서에서 찾은 후보 없음"
        title_tail = (f"기준일 불명 — 시행 버전에 따라 결과가 달라진다(후보: {listed}). 사람 확인 필요")
    else:
        rule, status, severity = "TEMPORAL.OTHER_VERSION_MATCH", VerificationStatus.SUSPICIOUS, Severity.MEDIUM
        title_tail = f"기준일 {when} 버전·현행 버전이 아닌 다른 시행 버전과만 일치"
    features = {"deterministic_rule": True, "rule_id": rule, "reference_date": when,
                "reference_basis": reference.get("basis"), "reference_kind": reference.get("kind"),
                "reference_candidates": reference.get("candidates") or [], "claim_text": claim,
                "defect_code": "TEMPORAL_REVIEW" if rule == "TEMPORAL.REVIEW_NEEDED" else rule.split(".")[-1],
                "version_source": (versions[0].get("source") if versions else None),
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


def _day_before(value: str) -> Optional[str]:
    from datetime import timedelta

    try:
        return (date.fromisoformat(value) - timedelta(days=1)).isoformat()
    except (TypeError, ValueError):
        return None


def official_versions(adapter, citation, reference_date: Optional[str], today: str,
                      cache: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """국가법령정보 법령 연혁(eflaw)에서 기준일 시행본(구법)과 현행본을 받아 조문 버전 목록을 만든다.

    기준일이 없으면 현행본과 직전 시행본을 받는다. 조회 실패는 이유와 함께 돌려주고, 버전을 지어내지 않는다.
    반환: {"status": READY|UNAVAILABLE, "versions": [...], "reason": str, "source_urls": [...]}.
    """
    from packages.source_adapters.legal_history import legal_date, select_provision, select_version

    law_name = getattr(citation, "law_name", None)
    if not law_name or not getattr(citation, "article", None):
        return {"status": "UNAVAILABLE", "versions": [], "reason": "법령명·조문 번호가 없음"}
    if adapter is None or not hasattr(adapter, "search_law_history"):
        return {"status": "UNAVAILABLE", "versions": [], "reason": "법령 연혁을 조회할 출처가 없음"}
    status = str(adapter.status()) if hasattr(adapter, "status") else "READY"
    if not status.endswith("READY"):
        return {"status": "UNAVAILABLE", "versions": [], "reason": f"국가법령정보 조회 불가({status})"}
    cache = cache if cache is not None else {}
    history = cache.get(law_name)
    if history is None:
        history = cache[law_name] = adapter.search_law_history(law_name)
    if not getattr(history, "ok", False) or not getattr(history, "complete", False) or not history.records:
        return {"status": "UNAVAILABLE", "versions": [],
                "reason": f"법령 연혁을 확보하지 못함({getattr(history, 'message', '') or getattr(history, 'status', '')})"}
    rows = sorted(history.records, key=lambda r: legal_date(r.get("effective_from")) or "")
    try:
        current = select_version(rows, today)
        wanted = [select_version(rows, reference_date)] if reference_date else []
    except ValueError as exc:
        return {"status": "UNAVAILABLE", "versions": [], "reason": f"시행 버전을 고르지 못함({exc})"}
    if not reference_date:
        # 기준일이 없으면 현행 직전 시행본(구법)을 함께 받아 개정으로 결과가 갈리는지 본다
        earlier = [r for r in rows if (legal_date(r.get("effective_from")) or "") < (current.get("effective_from") or "")]
        if earlier:
            wanted.append(earlier[-1])
    wanted.append(current)
    starts = [legal_date(r.get("effective_from")) for r in rows]
    versions, urls, seen = [], [], set()
    for selected in wanted:
        key = (str(selected.get("version_id")), selected.get("effective_from"))
        if key in seen:
            continue
        seen.add(key)
        detail = adapter.fetch_law_version(selected)
        if not getattr(detail, "ok", False) or not detail.records:
            return {"status": "UNAVAILABLE", "versions": [],
                    "reason": f"{selected.get('effective_from')} 시행본 본문을 받지 못함({getattr(detail, 'message', '')})"}
        provision = select_provision(detail.records[0], str(citation.article))
        if provision.get("status") not in ("VERIFIED", "DELETED"):
            return {"status": "UNAVAILABLE", "versions": [],
                    "reason": f"{selected.get('effective_from')} 시행본에서 제{citation.article}조를 확인하지 못함"}
        start = legal_date(selected.get("effective_from"))
        later = [d for d in starts if d and start and d > start]
        record = getattr(detail, "source_record", None)
        url = getattr(record, "url", "") if record is not None else ""
        urls.append(url)
        versions.append({"text": provision.get("text") or "", "effective_from": start,
                         "effective_to": _day_before(min(later)) if later else None,
                         "version_id": selected.get("version_id"), "source": "OFFICIAL_HISTORY", "source_url": url})
    versions.sort(key=lambda v: v["effective_from"] or "")
    return {"status": "READY", "versions": versions, "reason": "", "source_urls": urls}
