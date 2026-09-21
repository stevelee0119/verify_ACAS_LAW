"""Advisory source reviews without pipeline or persistence schema dependencies.

Call verify_citations(case_date=<one explicit issue date>, incident_date=...)
once per issue. Today's date never supplies the missing reference date.
Source records retain every list page/detail snapshot in EngineResult.
"""
from __future__ import annotations

import re

from packages.common.enums import CitationType, EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding
from packages.source_adapters.legal_history import legal_date, select_provision, today_korea

from .spec_mapping import relevance_review


def date_context(as_of=None, incident_date=None, current_date=None):
    return {"reference_date": as_of, "incident_date": incident_date,
            "current_date": current_date if current_date is not None else today_korea(),
            "reference_basis": "EXPLICIT_REVIEW_DATE" if as_of else "MISSING",
            "advisory_only": True}


def _mismatch(verdict, title, detail, excerpt):
    citation = verdict.citation
    ids = [r.source_record_id for r in verdict.source_records]
    verdict.findings.append(Finding.create(
        type=FindingType.LAW_CITATION_ERROR, status=VerificationStatus.CONTRADICTED,
        severity=Severity.MEDIUM, evidence_grade=EvidenceGrade.A,
        title=title, detail=detail, document_id=citation.document_id,
        block_id=citation.block_id, page=citation.page, span=citation.span,
        engine="legal_engine", source_record_ids=ids, tags=["LEGAL", "SOURCE_TEXT"],
        evidence=[Evidence.create(description="조회한 공식 버전의 원문", grade=EvidenceGrade.A,
                                  excerpt=excerpt, source_record_ids=ids)],
    ))


def verify_statute_source(verifier, citation, *, as_of=None, incident_date=None, current_date=None):
    from .verifier import CitationVerdict

    verdict = CitationVerdict(citation, VerificationStatus.UNVERIFIED)
    verdict.review = {"dates": date_context(as_of, incident_date, current_date),
                      "advisory_only": True, "applicability": "REVIEW_NEEDED"}
    verdict.levels.update(temporal="UNVERIFIED", content="UNVERIFIED", applicability="REVIEW_NEEDED")
    if any(value is not None and not legal_date(value) for value in (as_of, incident_date, current_date)):
        verdict.notes.append("유효한 기준일이 필요하다. 누락·오류 날짜를 오늘로 대체하지 않는다")
        return verdict
    response = verifier.registry.law.resolve_statute(citation.law_name, as_of=as_of, current_date=current_date)
    verdict.source_records.extend(response.source_records)
    if not response.ok or not response.complete or len(response.records) != 1:
        verdict.notes.append(response.message or "완전한 시행법 연혁과 전문을 확보하지 못했다")
        verdict.findings.append(verifier._unverified_finding(citation, verdict.notes[-1], response.source_record))
        return verdict
    official = response.records[0]
    verdict.official_record = official
    verdict.levels.update(existence="VERIFIED", version="VERIFIED")
    verdict.review["version"] = {key: official.get(key) for key in (
        "law_id", "version_id", "effective_from", "effective_until", "promulgation_date",
        "date_basis", "history_complete", "current_version", "current_as_of")}
    verdict.review["supplementary_provisions"] = official.get("supplementary_provisions", [])
    verdict.review["transitional_review_needed"] = bool(official.get("transitional_review_needed"))
    verdict.review["supplementary_review_needed"] = not official.get("supplementary_complete")
    # Citation has no subitem field. Only recover an explicit locator from its
    # preserved raw_text, never from surrounding context.
    subitems = re.findall(r"([가-힣])\s*목", citation.raw_text)
    if len(subitems) > 1 or "부칙" in citation.raw_text:
        verdict.notes.append("부칙 직접 인용 또는 복수 목 지정은 자동 대응하지 않는다")
        return verdict
    provision = select_provision(official, citation.article or "", citation.paragraph,
                                 citation.item, subitems[0] if subitems else None)
    verdict.review["provision"] = provision
    verdict.levels["article"] = provision["status"]
    verdict.levels["provision"] = provision["status"]
    if provision["status"] != "VERIFIED":
        verdict.notes.append(provision.get("reason", "지정 조항호목의 전문을 확인하지 못했다"))
        return verdict
    article_start = provision.get("article_effective_from")
    enforcement = official.get("enforcement_note") or ""
    supplement_text = "\n".join(s.get("text", "") for s in official.get("supplementary_provisions", []))
    partial = bool(enforcement.strip()) or bool(re.search(
        r"다만|일부\s+.*시행|각 호.*시행|대통령령으로 정하는 날|별도로 정하는 날",
        supplement_text))
    verdict.review["enforcement_review_needed"] = bool(
        partial or not article_start or (as_of and article_start > legal_date(as_of)))
    if as_of and article_start and article_start <= legal_date(as_of) and not partial:
        verdict.levels["temporal"] = "VERIFIED"
    else:
        verdict.notes.append("기준일·조문 시행일 또는 부분 시행 조건 확인이 필요하다")
    if not official.get("supplementary_complete") or official.get("transitional_review_needed"):
        verdict.notes.append("부칙·경과조치의 사건 적용 여부는 검토자가 확인해야 한다")
        verdict.levels["temporal"] = "UNVERIFIED"
    verdict.levels["content"] = "AVAILABLE"
    verdict.status = VerificationStatus.PARTIALLY_VERIFIED
    if citation.quoted_text:
        level, ratio = verifier._compare_quote(citation.quoted_text, provision["text"])
        if level == "CONTRADICTED" and verdict.levels["temporal"] != "VERIFIED":
            level = "UNVERIFIED"
        verdict.levels["content"] = level
        verdict.review["quote_similarity"] = ratio
        if level == "CONTRADICTED":
            verdict.status = VerificationStatus.CONTRADICTED
            _mismatch(verdict, "지정 조항호목의 공식 원문과 인용문 불일치",
                      "조회한 시행 버전의 해당 조항호목에 대한 문언 대조 결과이다. 사건 적용 결론은 아니다.",
                      provision["text"])
        elif level != "VERIFIED":
            verdict.notes.append("직접 인용문은 해당 조항호목 원문 대조가 더 필요하다")
    verdict.notes.append("시행 버전·본문 대조는 사건에 대한 법률 적용 결론이 아니다")
    return verdict


def verify_decision_source(verifier, citation):
    from .verifier import CitationVerdict

    verdict = CitationVerdict(citation, VerificationStatus.UNVERIFIED)
    verdict.review = {"advisory_only": True, "applicability": "REVIEW_NEEDED"}
    interpretation = citation.type == CitationType.INTERPRETATION
    if interpretation and citation.court not in (None, "", "법제처"):
        verdict.notes.append("중앙부처별 1차 해석은 별도 공식 API 대상이다. 법제처 해석례로 대체하지 않는다")
        return verdict
    search = getattr(verifier.registry.law, "search_interpretation" if interpretation else "search_admin_decision", None)
    fetch = getattr(verifier.registry.law, "fetch_interpretation" if interpretation else "fetch_admin_decision", None)
    if not citation.case_number or search is None or fetch is None:
        verdict.notes.append("자료 종류에 맞는 공식 어댑터와 정확한 안건·사건번호가 필요하다")
        return verdict
    response = search(citation.case_number)
    verdict.source_records.extend(response.source_records)
    if not response.ok or not response.complete:
        verdict.notes.append(response.message or "공식 목록 검색을 완료하지 못했다")
        return verdict
    target = re.sub(r"\s+", "", citation.case_number)
    matches = [r for r in response.records if r.get("case_number") == target]
    if len(matches) > 1 and citation.court:
        matches = [r for r in matches if r.get("court", "").replace(" ", "") == citation.court.replace(" ", "")]
    if len(matches) != 1 or not matches[0].get("source_id"):
        verdict.notes.append("같은 안건·사건번호의 공식 기록이 없거나 여러 기록이 중복된다")
        return verdict
    official = dict(matches[0])
    verdict.official_record = official
    verdict.levels["existence"] = "VERIFIED"
    detail = fetch(official)
    verdict.source_records.extend(detail.source_records)
    if not detail.ok or not detail.records:
        verdict.notes.append(detail.message or "공식 전문 확인 불가")
        return verdict
    official = {**official, **detail.records[0]}
    verdict.official_record = official
    metadata_missing = not official.get("decision_date") or not official.get("court")
    mismatches = verifier._compare_metadata(citation, official)
    verdict.levels["metadata"] = "CONTRADICTED" if mismatches else "UNVERIFIED" if metadata_missing else "VERIFIED"
    verdict.levels["full_text"] = "VERIFIED" if detail.complete else "UNVERIFIED"
    verdict.levels["applicability"] = "REVIEW_NEEDED"
    if not detail.complete or metadata_missing:
        verdict.notes.append("공식 전문 또는 결정 메타데이터가 불완전하다")
        return verdict
    verdict.status = VerificationStatus.PARTIALLY_VERIFIED
    if mismatches:
        verdict.status = VerificationStatus.CONTRADICTED
        description = "; ".join(f"{field}: 문서 {doc} / 공식 {off}" for field, doc, off in mismatches)
        verdict.notes.append(description)
        _mismatch(verdict, "해석례·재결례 메타데이터 불일치", description, official["full_text"])
    if citation.quoted_text:
        level, ratio = verifier._compare_quote(citation.quoted_text, official["full_text"])
        verdict.levels["quote"] = level
        verdict.review["quote_similarity"] = ratio
        if level == "CONTRADICTED":
            verdict.status = VerificationStatus.CONTRADICTED
            _mismatch(verdict, "해석례·재결례 공식 전문과 인용문 불일치",
                      "공식 전문 문언 대조이며 사건 적용 결론은 아니다.", official["full_text"])
    verdict.notes.append("해석례·재결례의 존재·전문 확인과 사건 적용 가능성 판단은 별도이다")
    return verdict


def case_applicability_review(citation, official, *, source_record_ids=(), extracted=None):
    """Anchor supplied structured excerpts; never invent facts or legal rules.

    extracted accepts facts/issues/rules/conditions/exceptions/conclusion and
    subsequent_treatment lists of {excerpt, ...}. Only exact official full-text
    excerpts survive. Persist this advisory object in existing result data.
    """
    fields = ("facts", "issues", "rules", "conditions", "exceptions", "conclusion", "subsequent_treatment")
    text = (official or {}).get("full_text") or ""
    result = {
        "citation_id": citation.citation_id, "case_number": citation.case_number,
        "citation_context": citation.context, "source_record_ids": list(source_record_ids),
        "status": "REVIEW_NEEDED", "advisory_only": True, "applies_to_case": None,
        "precedential_effect": "NOT_DETERMINED", "sections": {}, "rejected_excerpts": [],
    }
    for key in fields:
        accepted = []
        rows = (extracted or {}).get(key, [])
        rows = rows if isinstance(rows, list) else [rows]
        for row in rows:
            excerpt = row.get("excerpt") if isinstance(row, dict) else None
            if text and source_record_ids and isinstance(excerpt, str) and excerpt.strip() and excerpt in text:
                start = text.index(excerpt)
                accepted.append({"excerpt": excerpt, "span": [start, start + len(excerpt)]})
            else:
                result["rejected_excerpts"].append({"section": key, "reason": "No exact official full-text anchor"})
        result["sections"][key] = accepted
    result["missing_sections"] = [key for key in fields if not result["sections"][key]]
    result["full_text_available"] = bool(text)
    # 제4.2장 관련성. 측정하지 않았으면 0점이 아니라 미측정이며, 관련성 검증을
    # 마쳤다는 표시로 쓸 수 없다. 값은 검토자나 임베딩 단계가 채운다.
    result["relevance"] = relevance_review((extracted or {}).get("relevance_axes"))
    return result
