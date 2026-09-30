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
# '2023. 11. 20.'과 '2023년 11월 20일' 표기를 모두 읽는다(공소사실은 흔히 '년월일'로 적는다).
DATE_RE = re.compile(r"(?P<y>(?:19|20)\d{2})\s*[.년]\s*(?P<m>\d{1,2})\s*[.월]\s*(?P<d>\d{1,2})\s*[.일]?")
# 문서가 행위(범행)일로 적은 날짜: '피고인은 2021. 6. 1. …', '2021. 6. 1. … 범행·횡령·공소사실'
ACT_SUBJECT_RE = re.compile(r"(?:피고인|피의자|행위자)\s*(?:은|는|이|가)?\s*$")
ACT_SENTENCE_RE = re.compile(r"공소사실|범행|횡령|절취|편취|폭행|배임|사기|위반행위")
DISPOSITION_AFTER_RE = re.compile(r"^[^.\n]{0,20}?(?:처분|부과|징계)")
CRIMINAL_HINT_RE = re.compile(r"피고인|공소|형사|징역|벌금|법정형|범행")
CRIMINAL_BASIS = ("형법 제1조 제1항(범죄의 성립과 처벌은 행위 시의 법률에 따른다) 및 제2항(범죄 후 법률 변경 시 "
                  "경한 신법)을 기준으로 어느 버전을 적용할지 사람이 검토해야 한다")
# 계약·약정·체결 관련 키워드 정규식 (민사 계약 사건 기준일 특정용)
CONTRACT_SENTENCE_RE = re.compile(r"계약|체결|약정|합의|용역|공급|도급|위탁|납품|발주")


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
    """문서가 그 시점(행위·처분·계약 등)의 날짜로 적은 날짜가 하나뿐이면 그 날짜."""
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
            elif kind in ("계약", "합의", "약정") and (CONTRACT_SENTENCE_RE.search(sentence[:m.start()]) or CONTRACT_SENTENCE_RE.search(sentence[m.end():])):
                found.add(value)  # 계약 체결 관련 날짜 수집
    for dates in (charged, found):
        if len(dates) == 1:
            return next(iter(dates))
    return None


REFERENCE_KINDS = {
    "CONTRACT": "계약·합의일",
    "OFFENSE": "범행일",
    "DISPOSITION": "처분일",
    "TORT": "불법행위일",
    "LOWER_JUDGMENT": "원심 선고일",
}
TORT_SENTENCE_RE = re.compile(r"사고|불법행위|손해가\s*발생|상해를\s*입|부상을\s*입|폭행을\s*당|내원|진료|수술|오진|의료사고|사망")
LOWER_JUDGMENT_RE = re.compile(r"원심|제1심|1심|원판결")
PROCEDURAL_LAW_RE = re.compile(r"소송법$|소송규칙$")


def _sentences(text: str):
    return [s for s in re.split(r"(?<=[다음함])\s*[.。]\s*|\n", text or "") if s.strip()]


LAW_DATE_AFTER_RE = re.compile(r"\s*(?:(?:법률|대통령령|총리령|[가-힣]{1,8}부령|훈령|예규|고시)\s*제\s*\d+\s*호|"
                               r"(?:부터|자로)?\s*시행(?:된|되는|되어|한다|하는|일)|공포)")


def reference_candidates(text: str) -> List[Dict[str, Any]]:
    """문서가 적은 계약체결일·범행일·처분일·불법행위일·원심 선고일 후보. 같은 날짜·종류는 한 번만."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for sentence in _sentences(text):
        for m in DATE_RE.finditer(sentence):
            try:
                value = date(int(m.group("y")), int(m.group("m")), int(m.group("d"))).isoformat()
            except ValueError:
                continue
            before, after = sentence[:m.start()], sentence[m.end():]
            if LAW_DATE_AFTER_RE.match(after):
                continue  # "2022년 6월 10일 법률 제18900호로 개정", "2022. 12. 11.부터 시행": 법령의 날짜다
            kinds = []
            if ACT_SUBJECT_RE.search(before) and ACT_SENTENCE_RE.search(sentence):
                kinds.append("OFFENSE")
            if DISPOSITION_AFTER_RE.match(after):
                kinds.append("DISPOSITION")
            if LOWER_JUDGMENT_RE.search(sentence) and re.match(r"^\s*(?:에\s*)?선고", after):
                kinds.append("LOWER_JUDGMENT")
            if TORT_SENTENCE_RE.search(sentence) and not kinds and not re.match(r"^\s*(?:에\s*)?선고", after):
                kinds.append("TORT")
            # 계약·약정·체결 문맥 판별 (민사 계약 분쟁용)
            if (CONTRACT_SENTENCE_RE.search(before) or CONTRACT_SENTENCE_RE.search(after)) and not kinds and not re.match(r"^\s*(?:에\s*)?선고", after):
                kinds.append("CONTRACT")
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
        # 민사/계약/행정 사건: 계약체결일(CONTRACT)을 최우선으로 검토
        order = ["CONTRACT", "DISPOSITION", "TORT"]
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
    """버전이 둘 이상이거나 행위 당시 부존재하던 신설 조항일 때 행위시법 적용 여부를 판단한다."""
    if not versions:
        return None
    when = reference.get("date")
    earliest_start = min((v.get("effective_from") for v in versions if v.get("effective_from")), default=None)

    # 신설 조항 소급 적용 체크: 행위 당시 조문 자체가 아직 제정/시행되지 않은 경우
    is_not_yet_enacted = bool(when and earliest_start and earliest_start > when)

    if len(versions) < 2 and not is_not_yet_enacted:
        return None
    results = [r for r in version_outcomes(citation, versions) if r["outcome"]["status"] in ("VERIFIED", "CONTRADICTED")]
    if len(results) < 2 and not is_not_yet_enacted:
        return None
    matching = [r for r in results if r["outcome"]["status"] == "VERIFIED"]
    current = next((r for r in results if not r["version"].get("effective_to")), results[-1] if results else {"version": versions[-1], "outcome": {}})
    ref = next((r for r in results if when and _covers(r["version"], when)), None)
    claim = (citation.attributes or {}).get("claim_text") or ""
    values = "; ".join(f"{_label(r['version'])}: {_official_values(r['outcome'])}" for r in results) or (f"{_label(versions[0])} (신설 조항)" if versions else "")
    base_detail = f"문서의 주장 '{claim.strip()[:80]}'을 시행 버전별 조문과 대조했다({values})."
    basis_note = reference.get("note") or ""
    legal_basis = [CRIMINAL_BASIS] if criminal else []

    if is_not_yet_enacted:
        rule, status, severity = "TEMPORAL.STATUTE_NOT_YET_ENACTED", VerificationStatus.CONTRADICTED, Severity.HIGH
        title_tail = (f"행위 당시({when}) 부존재하던 신설 조항 소급 적용 (최초 시행일 {earliest_start}) — "
                      f"행위시법 원칙 위반(RETROACTIVE_APPLICATION_ERROR)")
    elif when and ref is None:
        rule, status, severity, title_tail = ("TEMPORAL.REVIEW_NEEDED", VerificationStatus.UNVERIFIED, Severity.INFO,
                                              f"기준일 {when}에 시행된 버전을 확보하지 못했다")
    elif when and ref in matching:
        differs = ref is not current and current not in matching
        rule, status, severity = "TEMPORAL.REFERENCE_VERSION_MATCH", VerificationStatus.VERIFIED, Severity.INFO
        title_tail = f"기준일 {when} 시행 버전({_label(ref['version'])})과 일치" + (
            f" — 현행과 다름(현행 {_official_values(current['outcome'])})" if differs else "")
    elif when and current in matching:
        rule, status, severity = "TEMPORAL.CURRENT_ONLY_MATCH", VerificationStatus.SUSPICIOUS, Severity.HIGH
        title_tail = (f"증액·개정 규정 소급 적용 오류 — 기준일 {when} 당시 법정 규정은 {_official_values(ref['outcome'])}"
                      f"(현행 {_official_values(current['outcome'])}, RETROACTIVE_APPLICATION_ERROR)")
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
                              "status": r["outcome"].get("status"), "values": _official_values(r["outcome"])}
                             for r in (results or [{"version": v, "outcome": {}} for v in versions])],
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
        tags=["LEGAL", "STATUTE", "TEMPORAL"] + (["RETROACTIVE_APPLICATION_ERROR"] if "RETROACTIVE_APPLICATION_ERROR" in title_tail else []),
        evidence=[Evidence.create(description=f"시행 버전 {_label(r['version'])}", grade=EvidenceGrade.A,
                                  excerpt=paragraph_text(r["version"].get("text") or "", citation.paragraph)[:300])
                  for r in (results or [{"version": v} for v in versions])[:4]])


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
    earliest_start = legal_date(rows[0].get("effective_from")) if rows else None
    is_not_yet_enacted = bool(reference_date and earliest_start and earliest_start > reference_date)
    try:
        current = select_version(rows, today)
        if is_not_yet_enacted:
            # 기준일 당시 아직 법률이 제정/시행되지 않은 신설 법령인 경우: 최초 시행 버전을 wanted에 포함
            wanted = [rows[0]]
        else:
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


# --- 서면이 밝힌 개정 이력과 행위일 대조 --------------------------------------------------------------
#
# 서면이 "2024년 12월 24일 법률 제20589호로 개정되어 2025년 1월 1일부터 시행된 「○○법」 제35조"처럼
# 개정 이력을 스스로 적고 그 조항을 행위에 적용하라고 주장하면, 적힌 시행일과 행위일(기준일)만으로도
# 행위 후 시행 조항에 기댄 주장임을 알 수 있다. 공식 연혁을 조회할 수 있으면 적힌 공포번호·공포일·시행일이
# 그 법령의 연혁에 있는지도 대조한다. 어느 법을 적용할지는 결론 내리지 않는다.
_D = r"(?:19|20)\d{2}\s*[.년]\s*\d{1,2}\s*[.월]\s*\d{1,2}\s*[.일]?"
_LAW_KIND = r"(?:법률|대통령령|총리령|[가-힣]{1,8}부령)"
_LAW_NAME = r"[「『]?\s*(?P<law>[가-힣][가-힣A-Za-z0-9ㆍ·\s]{0,40}?(?:법률|법|령|규칙))\s*[」』]?"
_ARTICLE = r"제\s*(?P<art>\d+)\s*조(?:\s*의\s*(?P<sub>\d+))?(?:\s*제\s*(?P<para>\d+)\s*항)?"
DECLARED_AMENDMENT_RES = (
    # "2024년 12월 24일 법률 제20589호로 개정되어 2025년 1월 1일부터 시행된 (개정) 「방위사업법」 제35조 제4항"
    re.compile(rf"(?P<prom>{_D})\s*(?P<kind>{_LAW_KIND})\s*제\s*(?P<num>\d{{2,6}})\s*호\s*(?:로|으로)?\s*"
               rf"(?:일부|전부)?\s*(?:개정|제정|신설)(?:되어|된|되고|되었으며|하여)?\s*,?\s*"
               rf"(?P<eff>{_D})\s*(?:부터|자로)\s*시행(?:된|되는|되어|되고|중인)?\s*(?:개정\s*|현행\s*)?{_LAW_NAME}\s*{_ARTICLE}"),
    # "「방위사업법」(2024. 12. 24. 법률 제20589호로 개정, 2025. 1. 1. 시행) 제35조"
    re.compile(rf"{_LAW_NAME}\s*\(\s*(?P<prom>{_D})\s*(?P<kind>{_LAW_KIND})\s*제\s*(?P<num>\d{{2,6}})\s*호[^)\n]{{0,20}}?"
               rf"(?P<eff>{_D})\s*시행\s*\)\s*{_ARTICLE}"),
)
# 행위 후 시행 조항을 사건에 적용하라는 주장인지(부합·소급·신법·면책 등)
RELIANCE_RE = re.compile(r"부합|소급|신법|적용되어|적용하여|해당하여|따라\s*(?:피고인|형사|면책|책임|처벌)|조각|면책|무죄|정당화")
# 행위시법·구법을 따로 논하는 문장은 적용 주장이 아니다
ACT_TIME_LAW_RE = re.compile(r"행위\s*(?:당시|시)(?:의)?\s*(?:법|법률|법령)|구법|개정\s*전(?:의)?\s*(?:법|규정|조항)")
FAVORABLE_NEW_LAW_BASIS = (
    "형법 제1조 제1항은 범죄의 성립과 처벌을 행위 시의 법률에 따르게 하고, 제2항은 범죄 후 법률이 변경되어 그 행위가 "
    "범죄를 구성하지 아니하게 되거나 형이 구법보다 가벼워진 경우에만 신법에 따르게 한다. 대법원 2022. 12. 22. 선고 "
    "2020도16420 전원합의체 판결은 해당 형벌법규 자체 또는 그로부터 수권·위임을 받은 법령이 아닌 다른 법령이 변경된 "
    "경우에는 형사법적 관점의 변화를 주된 근거로 하는 법령 변경이어야 형법 제1조 제2항을 적용한다고 보았다")
CIVIL_TIME_BASIS = "법령은 원칙적으로 시행 후의 사실에 적용되므로, 행위 후 시행된 조항의 적용 여부는 부칙·경과규정으로 확인해야 한다"


def _iso(value: str) -> Optional[str]:
    m = DATE_RE.search(value or "")
    if not m:
        return None
    try:
        return date(int(m.group("y")), int(m.group("m")), int(m.group("d"))).isoformat()
    except ValueError:
        return None


def declared_amendments(text: str) -> List[Dict[str, Any]]:
    """서면이 적은 '공포일·법령번호·시행일 + 법령명·조문' 묶음."""
    out, seen = [], set()
    for regex in DECLARED_AMENDMENT_RES:
        for m in regex.finditer(text or ""):
            law = " ".join(m.group("law").split())
            key = (law, m.group("art"), m.group("num"))
            if key in seen:
                continue
            seen.add(key)
            article = m.group("art") + (f"의{m.group('sub')}" if m.group("sub") else "")
            out.append({"law_name": law, "article": article, "paragraph": m.group("para"),
                        "kind": m.group("kind"), "number": m.group("num"),
                        "promulgated": _iso(m.group("prom")), "effective": _iso(m.group("eff")),
                        "span": m.span(), "raw": " ".join(m.group(0).split())})
    return out


def document_reference_date(text: str, *, criminal: bool) -> Dict[str, Any]:
    """법령명과 무관하게 문서에서 기준일(형사: 범행일, 그 밖: 계약·처분·불법행위일)을 하나로 정할 수 있으면 그 날짜."""
    candidates = reference_candidates(text)
    order = ["OFFENSE"] if criminal else ["CONTRACT", "DISPOSITION", "TORT"]
    kind = next((k for k in order if any(c["kind"] == k for c in candidates)), None)
    if kind is None:
        return {"date": None, "basis": "MISSING", "candidates": candidates}
    dates = sorted({c["date"] for c in candidates if c["kind"] == kind})
    if len(dates) != 1:
        return {"date": None, "basis": "AMBIGUOUS", "kind": kind, "candidates": candidates}
    return {"date": dates[0], "basis": "DOCUMENT_INFERRED", "kind": kind, "candidates": candidates,
            "note": f"문서에서 {REFERENCE_KINDS[kind]}로 추정한 {dates[0]}을 기준일로 썼다(추정 기준일)"}


def _official_history_check(adapter, declared: Dict[str, Any]) -> Dict[str, Any]:
    """적힌 법령번호·공포일·시행일이 공식 연혁에 있는가. 조회할 수 없으면 UNAVAILABLE(판정하지 않음)."""
    from packages.source_adapters.legal_history import legal_date

    if adapter is None or not hasattr(adapter, "search_law_history"):
        return {"status": "UNAVAILABLE", "reason": "법령 연혁을 조회할 출처가 없음"}
    status = str(adapter.status()) if hasattr(adapter, "status") else "READY"
    if not status.endswith("READY"):
        return {"status": "UNAVAILABLE", "reason": f"국가법령정보 조회 불가({status})"}
    try:
        history = adapter.search_law_history(declared["law_name"])
    except Exception as exc:  # 조회 실패는 판정하지 않는다
        return {"status": "UNAVAILABLE", "reason": f"법령 연혁 조회 오류({type(exc).__name__})"}
    message = getattr(history, "message", "") or ""
    if not getattr(history, "ok", False) or not getattr(history, "complete", False) or message.startswith("EXACT_LAW_NOT_FOUND"):
        return {"status": "UNAVAILABLE", "reason": f"법령 연혁을 확보하지 못함({message or getattr(history, 'status', '')})"}
    rows = history.records or []
    if not rows:
        return {"status": "UNAVAILABLE", "reason": "법령 연혁이 비어 있음"}
    wanted = str(int(declared["number"]))
    same_number = [r for r in rows if str(r.get("promulgation_number") or "").strip().lstrip("0") == wanted]
    listed = [{"promulgation_number": r.get("promulgation_number"), "promulgation_date": legal_date(r.get("promulgation_date")),
               "effective_from": legal_date(r.get("effective_from")), "amendment_type": r.get("amendment_type")}
              for r in same_number]
    urls = [getattr(rec, "url", "") for rec in (getattr(history, "source_records", None) or []) if getattr(rec, "url", "")]
    if not same_number:
        return {"status": "NOT_IN_HISTORY", "history_rows": len(rows), "source_urls": urls[:3],
                "reason": f"공식 연혁 {len(rows)}건에 {declared['kind']} 제{declared['number']}호에 의한 개정이 없다"}
    dates_match = any((not declared["promulgated"] or row["promulgation_date"] == declared["promulgated"])
                      and (not declared["effective"] or row["effective_from"] == declared["effective"]) for row in listed)
    return {"status": "MATCH" if dates_match else "DATE_MISMATCH", "history_rows": len(rows), "matches": listed,
            "source_urls": urls[:3]}


def _sentence(value: str) -> str:
    value = (value or "").strip()
    return value if not value or value.endswith(".") else value + "."


def review_declared_amendments(text: str, reference: Dict[str, Any], *, criminal: bool, adapter=None,
                               document_id: Optional[str] = None) -> List[Finding]:
    """서면이 밝힌 시행일이 기준일(행위일) 뒤인 조항을 행위에 적용하라고 주장하는 경우를 알린다."""
    when = reference.get("date")
    findings: List[Finding] = []
    for declared in declared_amendments(text):
        effective = declared["effective"]
        if not when or not effective or effective <= when:
            continue
        start, end = declared["span"]
        context = text[max(0, start - 80):min(len(text), end + 400)]
        # 구법·행위시법 논의는 개정 이력을 적은 문장부터 뒤에서만 본다(앞 표제의 '행위시법'은 주장이 아니다).
        if not RELIANCE_RE.search(context) or ACT_TIME_LAW_RE.search(text[start:min(len(text), end + 300)]):
            continue
        official = _official_history_check(adapter, declared)
        label = f"「{declared['law_name']}」 제{declared['article']}조" + (
            f" 제{declared['paragraph']}항" if declared.get("paragraph") else "")
        stated = (f"서면이 적은 개정 이력: {declared['promulgated'] or '?'} {declared['kind']} 제{declared['number']}호, "
                  f"{effective} 시행")
        if official["status"] in ("NOT_IN_HISTORY", "DATE_MISMATCH"):
            status, grade, severity = VerificationStatus.CONTRADICTED, EvidenceGrade.A, Severity.HIGH
            official_note = (official["reason"] if official["status"] == "NOT_IN_HISTORY" else
                             "공식 연혁의 같은 번호 개정과 공포일·시행일이 다르다: "
                             + "; ".join(f"{r['promulgation_date']} 공포·{r['effective_from']} 시행" for r in official["matches"]))
            tail = "공식 연혁과 다른 개정 이력에 근거한 소급 적용 주장"
        else:
            status, grade, severity = VerificationStatus.SUSPICIOUS, EvidenceGrade.B, Severity.HIGH
            official_note = ("적힌 개정 이력은 공식 연혁과 일치한다. 조문 내용은 인용 검증 결과를 따로 본다."
                             if official["status"] == "MATCH" else f"공식 연혁 대조 미실행: {official.get('reason', '')}")
            tail = "행위 후 시행 조항에 근거한 소급 적용 주장"
        basis = FAVORABLE_NEW_LAW_BASIS if criminal else CIVIL_TIME_BASIS
        findings.append(Finding.create(
            type=FindingType.TEMPORAL_LAW_MISMATCH, status=status, severity=severity, evidence_grade=grade,
            title=(f"법령 적용 시점 검토: {label} — 시행일 {effective}이 기준일({when}, "
                   f"{REFERENCE_KINDS.get(reference.get('kind'), '입력 기준일')}) 뒤인데 {tail} (RETROACTIVE_APPLICATION_ERROR)"),
            detail=" ".join(_sentence(x) for x in (
                stated, reference.get("note") or "", official_note, basis,
                "적힌 조항이 실제로 행위에 적용되는지(유리한 신법·부칙·경과규정)는 법률 판단이므로 결론을 내리지 않는다.") if x),
            confidence=0.85 if status == VerificationStatus.CONTRADICTED else 0.7,
            confidence_features={"deterministic_rule": True, "rule_id": "TEMPORAL.POST_OFFENSE_AMENDMENT_RELIANCE",
                                 "defect_code": "RETROACTIVE_APPLICATION_ERROR", "declared": {
                                     k: declared[k] for k in ("law_name", "article", "paragraph", "kind", "number",
                                                              "promulgated", "effective")},
                                 "reference_date": when, "reference_basis": reference.get("basis"),
                                 "reference_kind": reference.get("kind"), "official_history": official,
                                 "legal_basis": [basis], "human_review": True},
            document_id=document_id, span=declared["span"], engine=ENGINE_NAME,
            tags=["LEGAL", "STATUTE", "TEMPORAL", "RETROACTIVE_APPLICATION_ERROR"],
            evidence=[Evidence.create(description="서면의 개정 이력 기재", grade=EvidenceGrade.B,
                                      document_id=document_id, excerpt=declared["raw"][:300], supports=False)]
            + ([Evidence.create(description="국가법령정보 법령 연혁 대조", grade=EvidenceGrade.A,
                                excerpt=official_note[:300])] if official["status"] in ("NOT_IN_HISTORY", "DATE_MISMATCH", "MATCH") else []),
        ))
    return findings
