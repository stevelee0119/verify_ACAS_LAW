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
from .verification_labels import provision_label


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
    alias = (citation.attributes or {}).get("law_alias_candidate")
    if response.ok and (response.message or "").startswith("EXACT_LAW_NOT_FOUND:") and alias:
        # 적힌 이름이 목록에 없고, 같은 문서가 정식 법령명을 함께 쓴 경우: 정식명으로 다시 조회한다.
        retried = verifier.registry.law.resolve_statute(alias, as_of=as_of, current_date=current_date)
        verdict.source_records.extend(retried.source_records)
        verdict.review["law_alias"] = {"written": citation.law_name, "resolved": alias,
                                       "basis": citation.attributes.get("law_alias_basis"),
                                       "found": bool(retried.ok and not (retried.message or "").startswith(
                                           "EXACT_LAW_NOT_FOUND:"))}
        if verdict.review["law_alias"]["found"]:
            verdict.notes.append(f"'{citation.law_name}'은(는) 목록에 없어 문서의 정식 법령명 「{alias}」로 조회했다"
                                 "(약칭으로 판단한 근거는 문서 안의 표기다)")
            response = retried
        else:
            # An unresolved alias (including a failed detail parse) is not a nonexistent law.
            verdict.notes.append("법령 약칭 후보를 확인하지 못했다. 정식명칭·조회 상태를 확인해야 한다")
            verdict.findings.append(verifier._unverified_finding(citation, verdict.notes[-1], retried.source_record))
            return verdict
    if response.ok and (response.message or "").startswith("EXACT_LAW_NOT_FOUND:"):
        _law_absent(verdict, response, verifier=verifier)
        return verdict
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
    if provision["status"] == "NOT_FOUND":
        _article_absent(verdict, official, provision, as_of)
        return verdict
    if provision["status"] != "VERIFIED":
        verdict.notes.append(provision.get("reason", "지정 조항호목의 전문을 확인하지 못했다"))
        return verdict
    _offense_name_check(verdict, official, provision)
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
        verdict.notes.append(f"사건 특정 기준일({as_of}) 당시 시행 법령(시행일: {official.get('effective_from') or article_start}) 제{citation.article}조 특정 검토 완료")
    else:
        verdict.notes.append("기준일·조문 시행일 또는 부분 시행 조건 확인이 필요하다")
    if not official.get("supplementary_complete") or official.get("transitional_review_needed"):
        supplements = official.get("supplementary_provisions") or []
        trans_texts = [s.get("text", "").strip() for s in supplements if s.get("transitional")]
        if trans_texts:
            verdict.notes.append(f"부칙·경과조치의 사건 적용 여부는 검토자가 확인해야 한다 (부칙 내용: {trans_texts[0][:100]}...)")
        else:
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
    else:
        _compare_asserted_content(verdict, provision)
    if (verdict.levels["content"] in ("VERIFIED", "NOT_ASSERTED") and verdict.levels["temporal"] == "VERIFIED"
            and verdict.status != VerificationStatus.CONTRADICTED):
        # 법령·조문 존재, 문서가 주장한 내용(또는 주장 없음), 기준일 시행 버전까지 확인했다.
        # 기준일이 없으면 본문 대조를 마쳐도 PARTIALLY_VERIFIED로 두고, 본문 대조 완료는
        # component_summary의 content_confirmed로 따로 센다.
        verdict.status = VerificationStatus.VERIFIED
    # v3 D4: 기준일이 없으면 현행 버전 기준 일치로 확인 완료하고 기준일 확인은 권고로만 둔다.
    verdict.status, label, advisory = provision_label(verdict.levels, verdict.status, as_of)
    verdict.review["verification_label"] = label
    verdict.review["applicability"] = "APPLICABILITY_UNREVIEWED"
    if advisory:
        verdict.review.setdefault("advisories", []).append(advisory)
        verdict.levels["temporal_basis"] = "CURRENT_VERSION"
    verdict.notes.append("시행 버전·본문 대조는 사건에 대한 법률 적용 결론이 아니다")
    return verdict


GENERIC_OFFENSE_WORDS = {"위반", "처벌", "범죄", "본죄", "해당", "같은", "동조", "이법", "위법"}
OFFENSE_NAME_RE = re.compile(r"^\s*의\s*(?P<name>[가-힣·ㆍ]{1,12}?)(?:죄|범죄)")
ARTICLE_TITLE_RE = re.compile(r"^\s*제\s*\d+\s*조(?:\s*의\s*\d+)?\s*\((?P<title>[^)\n]{1,60})\)")


def _offense_name_check(verdict, official, provision):
    """'제10조의 누설죄'처럼 서면이 조문에 붙인 죄명이 공식 조문 제목과 맞는지 본다.

    죄명의 핵심어(두 글자 이상)가 조문 제목에 하나도 없으면, 같은 법에서 그 핵심어가 제목에 든 조문을
    함께 적어 알린다. 죄명은 약칭으로 쓰는 일이 있어 CONTRADICTED가 아니라 SUSPICIOUS로 둔다.
    """
    citation = verdict.citation
    claim = (citation.attributes or {}).get("claim_text") or ""
    named = OFFENSE_NAME_RE.match(claim)
    if not named:
        return
    title = provision.get("article_title")
    if not title:
        found = ARTICLE_TITLE_RE.match(provision.get("text") or "")
        title = found.group("title") if found else None
    if not title:
        return
    compact_title = re.sub(r"\s+", "", title)
    # '위반죄'·'처벌규정 위반죄'처럼 조문 내용을 가리키지 않는 일반 죄명은 대조하지 않는다.
    stems = [s for s in re.split(r"[·ㆍ\s]", named.group("name")) if len(s) >= 2 and s not in GENERIC_OFFENSE_WORDS]
    if not stems or any(s in compact_title for s in stems):
        return
    others = [f"제{r['number']}조({r['title']})" for r in official.get("provisions") or []
              if r.get("title") and any(s in re.sub(r"\s+", "", r["title"]) for s in stems)][:4]
    compared = compared_label(citation)
    ids = [r.source_record_id for r in verdict.source_records]
    verdict.review["offense_name_check"] = {"claimed": named.group("name") + "죄", "article_title": title,
                                            "articles_with_term": others}
    verdict.findings.append(Finding.create(
        type=FindingType.LAW_CITATION_ERROR, status=VerificationStatus.SUSPICIOUS, severity=Severity.MEDIUM,
        evidence_grade=EvidenceGrade.A,
        title=f"조문 제목과 서면이 적은 죄명이 다르다: {compared} — 서면 '{named.group('name')}죄' / 조문 제목 '{title}'",
        detail=(f"조회한 시행 버전의 {compared} 제목은 '{title}'이다. 서면은 이 조문을 '{named.group('name')}죄'의 근거로 적었다. "
                + (f"같은 법에서 제목에 '{'·'.join(stems)}'이(가) 든 조문: {', '.join(others)}. " if others else "")
                + "조문 번호 오기이거나 다른 조문의 죄를 잘못 연결했을 수 있으므로 사람이 확인한다."),
        document_id=citation.document_id, block_id=citation.block_id, page=citation.page, span=citation.span,
        engine="legal_engine", source_record_ids=ids, tags=["LEGAL", "SOURCE_TEXT", "OFFENSE_NAME_MISMATCH"],
        confidence_features={"deterministic_rule": True, "rule_id": "LEGAL.OFFENSE_NAME_VS_ARTICLE_TITLE",
                             "claimed_offense": named.group("name"), "article_title": title,
                             "articles_with_term": others},
        evidence=[Evidence.create(description="조회한 공식 버전의 조문 제목·본문", grade=EvidenceGrade.A,
                                  excerpt=f"({title}) " + (provision.get("text") or "")[:300], source_record_ids=ids),
                  Evidence.create(description="문서의 주장", grade=EvidenceGrade.B, document_id=citation.document_id,
                                  block_id=citation.block_id, excerpt=claim[:200])],
    ))


def _compare_asserted_content(verdict, provision):
    """직접 인용문이 없을 때, 문서가 조문에 대해 풀어 쓴 주장(claim_text)을 조문 본문과 대조한다(v2 R5)."""
    from .provision_content import compare_claim_to_provision

    citation = verdict.citation
    claim = (citation.attributes or {}).get("claim_text")
    outcome = compare_claim_to_provision(
        claim, provision.get("text") or "",
        numbers_only=(citation.attributes or {}).get("claim_mode") == "PARENTHETICAL_BASIS",
        subject=(citation.attributes or {}).get("claim_subject"))
    verdict.review["content_comparison"] = {**outcome, "claim_text": claim}
    status = outcome["status"]
    verdict.levels["content"] = status
    if status != "CONTRADICTED":
        return
    verdict.status = VerificationStatus.CONTRADICTED
    exact_version = verdict.levels.get("temporal") == "VERIFIED"
    compared = compared_label(citation)
    ids = [r.source_record_id for r in verdict.source_records]

    # 1) 조문의 재량/의무 왜곡 (MODALITY)
    if outcome.get("basis") == "MODALITY":
        verdict.findings.append(_modality_finding(verdict, provision, claim, outcome.get("modality", {}), compared, ids,
                                                  exact_version))
        return

    # 2) 조문 준용 규정 및 적용 배제 주장 상충 (STATUTORY_APPLICATION_CONFLICT, STATUTORY_MISQUOTATION)
    if outcome.get("basis") in ("STATUTORY_APPLICATION_CONFLICT", "STATUTORY_MISQUOTATION"):
        verdict.findings.append(Finding.create(
            type=FindingType.LAW_CITATION_ERROR, status=VerificationStatus.CONTRADICTED,
            severity=Severity.HIGH, evidence_grade=EvidenceGrade.A if exact_version else EvidenceGrade.B,
            title=f"조문 취지·준용 규정과 상충되는 주장이다: {compared}",
            detail=(f"비교 대상 조문: {compared}. 문서의 주장: '{claim}'. "
                    f"사유: {outcome.get('reason', '')}. "
                    + ("" if exact_version else "기준일이 없어 현행(조회) 버전과 비교했다. 사건 당시 시행 버전이 다르면 "
                       "결론이 달라질 수 있으므로 시행 버전을 확인해야 한다.")),
            document_id=citation.document_id, block_id=citation.block_id, page=citation.page, span=citation.span,
            engine="legal_engine", source_record_ids=ids, tags=["LEGAL", "SOURCE_TEXT", "STATUTORY_CONFLICT"],
            confidence_features={"claim_text": claim, "reason": outcome.get("reason"),
                                 "compared_version": (verdict.review.get("version") or {}).get("version_id")},
            evidence=[Evidence.create(description="조회한 공식 버전의 조문 본문", grade=EvidenceGrade.A,
                                      excerpt=(provision.get("text") or "")[:400], source_record_ids=ids),
                      Evidence.create(description="문서의 주장", grade=EvidenceGrade.B,
                                      document_id=citation.document_id, block_id=citation.block_id,
                                      excerpt=claim or "")],
        ))
        return

    # 3) 수치 불일치 (NUMERIC)
    mismatches = outcome.get("mismatches") or []
    pairs = "; ".join(f"문서 {m['claimed']} / 조문 {m['official']}" for m in mismatches) if mismatches else (outcome.get("reason") or "불일치")
    verdict.findings.append(Finding.create(
        type=FindingType.LAW_CITATION_ERROR, status=VerificationStatus.CONTRADICTED,
        severity=Severity.HIGH, evidence_grade=EvidenceGrade.A if exact_version else EvidenceGrade.B,
        title=f"조문 본문과 수치가 다르다: {compared} ({pairs})",
        detail=(f"비교 대상 조문: {compared}. 문서가 이 조문의 내용으로 적은 기간·비율이 조회한 시행 버전의 조문 본문과 다르다. "
                + ("" if exact_version else "기준일이 없어 현행(조회) 버전과 비교했다. 사건 당시 시행 버전이 다르면 "
                   "결론이 달라질 수 있으므로 시행 버전을 확인해야 한다.")),
        document_id=citation.document_id, block_id=citation.block_id, page=citation.page, span=citation.span,
        engine="legal_engine", source_record_ids=ids, tags=["LEGAL", "SOURCE_TEXT", "NUMERIC_MISMATCH"],
        confidence_features={"numeric_mismatches": mismatches, "claim_text": claim,
                             "compared_version": (verdict.review.get("version") or {}).get("version_id")},
        evidence=[Evidence.create(description="조회한 공식 버전의 조문 본문", grade=EvidenceGrade.A,
                                  excerpt=(provision.get("text") or "")[:400], source_record_ids=ids),
                  Evidence.create(description="문서의 주장", grade=EvidenceGrade.B,
                                  document_id=citation.document_id, block_id=citation.block_id,
                                  excerpt=claim or "")],
    ))


def _modality_finding(verdict, provision, claim, modality, compared, ids, exact_version):
    """조문의 재량('할 수 있다')을 의무로, 또는 의무('하여야 한다')를 재량으로 적은 주장(v4 P5)."""
    citation = verdict.citation
    kind = modality["kind"]
    heading = ("조문은 재량('할 수 있다')인데 의무로 주장했다" if kind == "DISCRETION_AS_MANDATE"
               else "조문은 의무('하여야 한다')인데 재량·의무 없음으로 주장했다")
    return Finding.create(
        type=FindingType.LEGAL_ARGUMENT_INVALID, status=VerificationStatus.CONTRADICTED, severity=Severity.HIGH,
        evidence_grade=EvidenceGrade.A if exact_version else EvidenceGrade.B,
        title=f"{heading}: {compared} — 문서 {modality['claimed']} / 조문 {modality['official']}",
        detail=(f"비교 대상 조문: {compared}. 문서는 '{modality['act']}'을(를) {modality['claimed']}로 적었으나 조회한 조문 본문은 "
                f"{modality['official']}로 정한다. 재량과 의무의 차이는 처분의 위법성 판단 등 결론을 바꿀 수 있다. "
                + ("" if exact_version else "기준일이 없어 조회(현행) 버전과 비교했다. ")
                + "사건에 대한 적용 결론은 내리지 않는다."),
        document_id=citation.document_id, block_id=citation.block_id, page=citation.page, span=citation.span,
        engine="legal_engine", source_record_ids=ids, tags=["LEGAL", "SOURCE_TEXT", "MODALITY"],
        confidence=0.85 if exact_version else 0.75,
        confidence_features={"deterministic_rule": True, "rule_id": f"CLAIM.{kind}", "modality": modality,
                             "claim_text": claim, "compared_version": (verdict.review.get("version") or {}).get("version_id")},
        evidence=[Evidence.create(description="조회한 공식 버전의 조문 본문", grade=EvidenceGrade.A,
                                  excerpt=(provision.get("text") or "")[:400], source_record_ids=ids),
                  Evidence.create(description="문서의 주장", grade=EvidenceGrade.B, document_id=citation.document_id,
                                  block_id=citation.block_id, excerpt=claim or "")],
    )


def _normalize_reference_name(name: str) -> str:
    """비교를 위한 규범·파일명 정규화 (확장자, 괄호, 특수기호, 공백 제거)."""
    # 파일 확장자(.pdf, .hwp, .hwpx, .docx, .txt 등) 제거
    name = re.sub(r"\.(?:pdf|hwpx?|docx?|txt)$", "", name, flags=re.IGNORECASE)
    # 낫표, 따옴표, 괄호, 공백 제거
    return re.sub(r"[「」『』\[\]()\"'\s]", "", name)


def _is_internal_or_admin_rule(law_name: str) -> bool:
    """법률·대통령령 등 일반 법령이 아닌 내부 규정·행정규칙·지침 형태인지 판정."""
    cleaned = re.sub(r"[「」『』\s]", "", law_name or "")
    if not cleaned:
        return False
    # 일반 법령 접미사 (법, 법률, 시행령, 대통령령, 시행규칙, 부령, 총리령, 조례)
    statute_suffixes = ("법", "법률", "시행령", "대통령령", "시행규칙", "부령", "총리령", "조례")
    # 내부 규정 / 행정규칙 / 사규 접미사
    internal_suffixes = (
        "규정", "지침", "훈령", "예규", "고시", "공고", "기준",
        "특수조건", "일반조건", "사규", "정관", "요령", "세칙",
        "수칙", "준칙", "편람", "매뉴얼",
    )
    if any(cleaned.endswith(s) for s in internal_suffixes):
        return True
    if any(cleaned.endswith(s) for s in statute_suffixes):
        return False
    return False


def _find_matching_user_reference(law_name: str, verifier, citation, verdict) -> str | None:
    """사용자 참고자료(Drive 등)에서 인용 규범과 일치하는 문서명이 있는지 확인."""
    if not law_name:
        return None
    target_norm = _normalize_reference_name(law_name)
    if not target_norm:
        return None

    candidate_names: list[str] = []

    # 1) verdict / citation 속성에서 확인
    for container in (verdict.review if verdict else {}, getattr(citation, "attributes", None) or {}):
        refs = container.get("user_references") or container.get("user_refs") or []
        if isinstance(refs, list):
            for r in refs:
                if isinstance(r, str):
                    candidate_names.append(r)
                elif isinstance(r, dict):
                    candidate_names.append(r.get("name") or r.get("filename") or r.get("title") or "")

    # 2) verifier 속성(references / reference_library / user_references)에서 확인
    if verifier is not None:
        direct_refs = getattr(verifier, "user_references", None) or getattr(verifier, "user_refs", None) or []
        if isinstance(direct_refs, list):
            for r in direct_refs:
                if isinstance(r, str):
                    candidate_names.append(r)
                elif isinstance(r, dict):
                    candidate_names.append(r.get("name") or r.get("filename") or r.get("title") or "")

        lib = getattr(verifier, "references", None) or getattr(verifier, "reference_library", None)
        if lib is not None:
            summary = getattr(lib, "summary", {}) or {}
            for item in summary.get("sources", []) + summary.get("inventory", []):
                if isinstance(item, dict):
                    name = item.get("name") or item.get("filename") or item.get("title")
                    if name:
                        candidate_names.append(name)
            eligible = getattr(lib, "eligible", {}) or {}
            for item in eligible.values():
                if isinstance(item, dict) and item.get("name"):
                    candidate_names.append(item["name"])

    for cand in candidate_names:
        cand_norm = _normalize_reference_name(cand)
        if cand_norm and (target_norm == cand_norm or target_norm in cand_norm or cand_norm in target_norm):
            return cand
    return None


def _law_absent(verdict, response, verifier=None):
    """법령 목록 조회는 성공했으나 같은 이름의 법령이 없다(NOT_FOUND_LAW).

    국가법령정보 법령 목록에서 찾지 못했다는 뜻이다.
    1) 사용자 참고자료(Drive)에 있는 경우: '참고자료에서 확인(공식 법령 아님)'으로 처리하고 CRITICAL 미발행.
    2) 내부 규정·행정규칙·지침 형태인 경우: 존재하지 않는 법령(CRITICAL)이 아니라 내부 규정 가능성(LOW)으로 알림.
    3) 일반 법령(법·법률 등) 형태인 경우: 기존대로 부존재 가능성 CRITICAL(증거 B) 유지.
    """
    import json

    citation = verdict.citation
    candidates = json.loads(response.message.split(":", 1)[1] or "[]")
    verdict.status = VerificationStatus.NOT_FOUND
    verdict.levels.update(existence="NOT_FOUND", article="NOT_FOUND", provision="NOT_FOUND")
    verdict.review["law_candidates"] = candidates
    ids = [r.source_record_id for r in verdict.source_records]

    # 1. 사용자 참고자료(Drive) 매칭 확인: 참고자료에 존재하는 내부 규정이면 CRITICAL 미발행
    matched_ref = _find_matching_user_reference(citation.law_name, verifier, citation, verdict)
    if matched_ref:
        verdict.status = VerificationStatus.PARTIALLY_VERIFIED
        verdict.levels["existence"] = "FOUND_IN_USER_REFERENCES"
        verdict.review["user_reference_match"] = matched_ref
        verdict.notes.append(
            f"공식 법령 목록에는 없으나 사용자 참고자료(Drive) 「{matched_ref}」에서 확인되었다. "
            "공식 법령이 아닌 내부 규정이므로 해당 참고자료 원문과의 대조 대상으로 처리한다"
        )
        return

    # 2. 내부 규정 / 행정규칙 / 지침 등 비법령 규범 형태 확인: 심각도 LOW (HIGH 미만)
    if _is_internal_or_admin_rule(citation.law_name) or citation.type == CitationType.ADMIN_RULE:
        verdict.levels["existence"] = "NOT_FOUND_IN_STATUTE_LIST"
        verdict.notes.append(
            f"공식 법령 목록에서 「{citation.law_name}」을(를) 찾지 못했으나, 법령이 아닌 내부 규정·행정규칙·지침 형태이다. "
            "공식 법령 목록에 없는 것이 정상이거나 기관 내부 규범일 수 있으므로 사람이 원문을 확인해야 한다"
        )
        verdict.findings.append(Finding.create(
            type=FindingType.LAW_CITATION_ERROR, status=VerificationStatus.NOT_FOUND, severity=Severity.LOW,
            evidence_grade=EvidenceGrade.B,
            title=f"법령 목록에서 찾지 못한 규범(내부 규정·지침 가능): {citation.law_name}",
            detail=("국가법령정보 법령 목록에서 같은 이름의 법령을 찾지 못했다(조회 범위 내 미발견). "
                    + (f"비슷한 이름: {', '.join(candidates)}. " if candidates else "")
                    + "법령이 아닌 기관 내부 규정·행정규칙·지침일 수 있으므로 존재하지 않는 법령으로 단정하지 않는다. "
                    + "소관 기관 원문이나 첨부 자료를 확인해야 한다."),
            document_id=citation.document_id, block_id=citation.block_id, page=citation.page, span=citation.span,
            engine="legal_engine", source_record_ids=ids, tags=["LEGAL", "ADMIN_RULE", "INTERNAL_REGULATION"],
            confidence_features={"verdict_label": "NOT_FOUND_IN_STATUTE_LIST", "absence_scope": "SEARCHED_SCOPE_ONLY",
                                 "law_candidates": candidates, "law_name": citation.law_name,
                                 "is_internal_or_admin_rule": True},
            evidence=[Evidence.create(description="법령 목록 조회 결과", grade=EvidenceGrade.B,
                                      excerpt=", ".join(candidates) or "(목록 없음)", source_record_ids=ids,
                                      supports=False)],
        ))
        return

    # 3. 일반 법령(법, 법률 등) 형태: 기존 CRITICAL 부존재 판정 유지 (대조군)
    verdict.findings.append(Finding.create(
        type=FindingType.STATUTE_NONEXISTENT, status=VerificationStatus.NOT_FOUND, severity=Severity.CRITICAL,
        evidence_grade=EvidenceGrade.B,
        title=f"법령 목록에서 찾지 못한 법령(NOT_FOUND_LAW): {citation.law_name}",
        detail=("국가법령정보 법령 목록에서 같은 이름의 법령을 찾지 못했다(조회 범위 내 미발견, 부존재 확정 아님). "
                + (f"비슷한 이름: {', '.join(candidates)}. " if candidates else "비슷한 이름의 법령도 없다. ")
                + "법령명 오기·약칭·폐지 여부를 원문으로 확인해야 한다."),
        document_id=citation.document_id, block_id=citation.block_id, page=citation.page, span=citation.span,
        engine="legal_engine", source_record_ids=ids, tags=["LEGAL", "STATUTE", "NOT_FOUND_LAW", "FAKE_REGULATION"],
        confidence_features={"verdict_label": "NOT_FOUND_LAW", "absence_scope": "SEARCHED_SCOPE_ONLY",
                             "law_candidates": candidates, "law_name": citation.law_name},
        evidence=[Evidence.create(description="법령 목록 조회 결과", grade=EvidenceGrade.B,
                                  excerpt=", ".join(candidates) or "(목록 없음)", source_record_ids=ids,
                                  supports=False)],
    ))


def _article_absent(verdict, official, provision, as_of):
    """조회한 시행 버전의 전체 조문에 인용 조문이 없을 때의 판정.

    법령 자체는 공식 기록으로 확인됐으므로 법령 부존재가 아니다. 조문 조회가 실패한
    것도 아니다. 확인한 범위(버전·시행일·조문 수)를 그대로 적고, 그 범위 밖(다른 시행
    버전·부칙·별표)에 있었을 가능성은 열어 둔다. 허위·위조로 단정하지 않는다.
    """
    citation = verdict.citation
    verdict.status = VerificationStatus.NOT_FOUND
    verdict.levels["article"] = "NOT_FOUND_IN_SELECTED_VERSION"
    verdict.levels["provision"] = "NOT_FOUND_IN_SELECTED_VERSION"
    version = official.get("version_id")
    effective = official.get("effective_from")
    scope = (f"{official.get('law_name') or citation.law_name} 시행 버전 {version or '미상'}"
             f"(시행 {effective or '미상'})의 전체 조문 {provision.get('searched_articles')}개")
    basis = "기준일 " + str(as_of) if as_of else "기준일이 없어 현행 버전"
    compared = compared_label(citation)
    verdict.notes.append(f"{scope}를 대조했으나 {compared}에 해당하는 제{citation.article}조가 없다({basis} 기준). "
                         "다른 시행 버전·부칙에 있었는지는 확인하지 않았다")
    ids = [r.source_record_id for r in verdict.source_records]
    verdict.findings.append(Finding.create(
        type=FindingType.LAW_CITATION_ERROR, status=VerificationStatus.NOT_FOUND,
        severity=Severity.MEDIUM, evidence_grade=EvidenceGrade.A,
        title=f"조회한 시행 버전의 전체 조문에서 해당 조문을 찾지 못함: {compared}",
        detail=(f"법령은 공식 기록으로 확인했다. {scope}를 모두 대조했으나 {compared}에 해당하는 제{citation.article}조는 없다. "
                f"({basis} 기준) 조문 번호 오기, 다른 시행 버전의 조문, 부칙 조항일 수 있으므로 "
                "허위 인용으로 단정하지 않는다."),
        document_id=citation.document_id, block_id=citation.block_id, page=citation.page,
        span=citation.span, engine="legal_engine", source_record_ids=ids,
        confidence_features={"official_source_match": True, "absence_scope": "SELECTED_VERSION_FULL_TEXT",
                             "searched_articles": provision.get("searched_articles"),
                             "version_id": version, "reference_date": as_of},
        tags=["LEGAL", "STATUTE", "ARTICLE"],
        evidence=[Evidence.create(description="조회한 공식 버전의 조문 목록에 해당 조문 없음",
                                  grade=EvidenceGrade.A, excerpt=citation.raw_text,
                                  source_record_ids=ids, supports=False)],
    ))


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


def verify_admin_rule_source(verifier, citation):
    """행정규칙(훈령·예규·고시·지침) 인용 검증.

    존재·식별정보·조항·본문·위임 근거·법적 효력을 따로 판정한다. 행정규칙은 원칙적으로
    행정조직 내부에서만 효력을 가지며, 상위법령의 위임과 결합하는 등 예외적인 경우에만
    대외적 구속력이 논의된다. 문서가 "법률과 같은 효력"이라고 적었다는 사실만으로
    효력을 확인 처리하지 않는다. 공식 기록이 불완전하면 미확인으로 남긴다.
    """
    from .verifier import CitationVerdict

    attrs = citation.attributes or {}
    verdict = CitationVerdict(citation, VerificationStatus.UNVERIFIED)
    verdict.review = {"advisory_only": True, "applicability": "REVIEW_NEEDED",
                      "document_claims": {key: attrs.get(key) for key in (
                          "rule_name", "issuing_agency", "rule_kind", "rule_number", "effective_date",
                          "delegation_basis", "claimed_effect")}}
    verdict.levels.update(existence="UNVERIFIED", metadata="UNVERIFIED", content="UNVERIFIED",
                          delegation="NOT_STATED" if not attrs.get("delegation_basis") else "UNVERIFIED",
                          legal_effect="CLAIM_NOT_VERIFIED" if attrs.get("claimed_effect") else "REVIEW_NEEDED",
                          applicability="REVIEW_NEEDED")
    if citation.article:
        verdict.levels["article"] = "UNVERIFIED"
    if attrs.get("claimed_effect"):
        verdict.notes.append(
            f"문서는 이 행정규칙이 '{attrs['claimed_effect']}'을 가진다고 적었으나, 행정규칙의 대외적 "
            "구속력은 위임 근거·내용에 따라 사람이 판단할 사항이어서 자동으로 확인하지 않는다")
    name = citation.law_name or attrs.get("rule_name")
    search = getattr(verifier.registry.law, "search_admin_rule", None)
    fetch = getattr(verifier.registry.law, "fetch_admin_rule", None)
    if search is None or fetch is None:
        verdict.notes.append("행정규칙 공식 조회 경로가 지원되지 않아 확인하지 못했다")
        verdict.findings.append(verifier._unverified_finding(citation, verdict.notes[-1]))
        return verdict
    agency = attrs.get("issuing_agency")
    kind = attrs.get("rule_kind")
    number = attrs.get("rule_number")
    query = name or f"{agency or ''} {kind or ''}".strip() or citation.raw_text
    response = search(query)
    verdict.source_records.extend(response.source_records)
    if not response.ok or not response.complete:
        verdict.notes.append(response.message or "행정규칙 공식 목록 검색을 완료하지 못했다")
        verdict.findings.append(verifier._unverified_finding(citation, verdict.notes[-1], response.source_record))
        return verdict
    from packages.source_adapters.law_go_kr import _same_law_name

    if name:
        matched = [r for r in response.records if _same_law_name(name, r.get("rule_name"))]
    else:
        matched = [r for r in response.records if (not agency or agency in str(r.get("agency") or ""))
                   and (not kind or kind in str(r.get("rule_kind") or ""))]
    exact = [r for r in matched if not number or str(r.get("number") or "").replace(" ", "") == number]
    if not matched or (number and not exact):
        verdict.status = VerificationStatus.NOT_FOUND
        verdict.levels["existence"] = "NOT_FOUND"
        verdict.notes.append(f"공식 행정규칙 목록 {len(response.records)}건에서 일치하는 규칙을 찾지 못했다"
                             "(조회 범위 내 미발견). 폐지·명칭 변경·미수록일 수 있어 부존재로 단정하지 않는다")
        ids = [r.source_record_id for r in verdict.source_records]
        verdict.findings.append(Finding.create(
            type=FindingType.LAW_CITATION_ERROR, status=VerificationStatus.NOT_FOUND,
            severity=Severity.MEDIUM, evidence_grade=EvidenceGrade.B,
            title=f"조회 범위 내에서 찾지 못한 행정규칙 인용: {citation.raw_text}",
            detail=verdict.notes[-1], document_id=citation.document_id, block_id=citation.block_id,
            page=citation.page, span=citation.span, engine="legal_engine", source_record_ids=ids,
            confidence_features={"absence_scope": "SEARCHED_SCOPE_ONLY", "searched_records": len(response.records),
                                 "searched_query": query},
            tags=["LEGAL", "ADMIN_RULE"],
        ))
        return verdict
    if len(exact) != 1:
        verdict.notes.append("일치하는 행정규칙이 여러 건이거나 발령번호가 일치하는 기록이 없어 하나로 특정하지 못했다")
        verdict.review["candidates"] = [{k: r.get(k) for k in ("rule_name", "number", "agency", "effective_from")}
                                        for r in matched[:10]]
        return verdict
    official = dict(exact[0])
    verdict.official_record = official
    verdict.levels["existence"] = "VERIFIED"
    detail = fetch(official)
    verdict.source_records.extend(detail.source_records)
    if detail.ok and detail.records:
        official = {**official, **detail.records[0]}
        verdict.official_record = official
    mismatches = []
    for field_name, doc_value, off_value in (
            ("발령기관", attrs.get("issuing_agency"), official.get("agency")),
            ("규칙 종류", attrs.get("rule_kind"), official.get("rule_kind")),
            ("시행일", attrs.get("effective_date"), official.get("effective_from"))):
        if doc_value and off_value and str(doc_value).replace(" ", "") not in str(off_value).replace(" ", ""):
            mismatches.append((field_name, doc_value, off_value))
    identity_known = all(official.get(k) for k in ("agency", "rule_kind", "effective_from"))
    verdict.levels["metadata"] = "CONTRADICTED" if mismatches else ("VERIFIED" if identity_known else "UNVERIFIED")
    if mismatches:
        description = "; ".join(f"{f}: 문서 {d} / 공식 {o}" for f, d, o in mismatches)
        verdict.notes.append(description)
        _mismatch(verdict, "행정규칙 식별정보 불일치", description, str(official.get("full_text") or "")[:300])
    complete = bool(detail.ok and detail.complete and official.get("articles") is not None)
    if citation.article:
        if not complete:
            verdict.notes.append("행정규칙 전문을 확보하지 못해 조항 존재를 확인하지 못했다")
        else:
            from .normalize import canonical_article
            articles = {canonical_article(a) for a in official.get("articles") or []}
            if canonical_article(citation.article) in articles:
                verdict.levels["article"] = "VERIFIED"
                text = (official.get("article_texts") or {}).get(canonical_article(citation.article), "")
                verdict.levels["content"] = "AVAILABLE" if text else "UNVERIFIED"
                if citation.quoted_text and text:
                    level, ratio = verifier._compare_quote(citation.quoted_text, text)
                    verdict.levels["content"] = level
                    verdict.review["quote_similarity"] = ratio
            else:
                verdict.levels["article"] = "NOT_FOUND_IN_SELECTED_VERSION"
                verdict.notes.append(f"확보한 행정규칙 전문의 조항 {len(articles)}개에 제{citation.article}조가 없다"
                                     "(조회한 버전 기준, 다른 시점 버전은 확인하지 않음)")
    basis = attrs.get("delegation_basis")
    if basis and complete:
        compact = re.sub(r"\s+", "", str(official.get("full_text") or ""))
        law = re.sub(r"[「」『』\s]", "", basis.split("제")[0])
        verdict.levels["delegation"] = "MENTIONED_IN_OFFICIAL_TEXT" if law and law in compact else "UNVERIFIED"
        verdict.notes.append("위임 근거 법령의 해당 조문이 실제로 이 규칙에 위임했는지는 그 법령 조문을 따로 확인해야 한다")
    if mismatches:
        verdict.status = VerificationStatus.CONTRADICTED
    elif verdict.levels.get("article") in ("NOT_FOUND_IN_SELECTED_VERSION",):
        verdict.status = VerificationStatus.NOT_FOUND
    else:
        # 존재·조항이 확인돼도 법적 효력과 사건 적용은 사람 몫이다.
        verdict.status = VerificationStatus.PARTIALLY_VERIFIED
    verdict.notes.append("행정규칙의 존재·조항 확인은 법적 구속력이나 사건 적용 결론이 아니다")
    return verdict


def compared_label(citation) -> str:
    """판정 근거에 적을 비교 대상 조문 이름. 앞 인용을 가리킨 표현은 푼 이름과 원문 표기를 함께 적는다."""
    resolved = (citation.attributes or {}).get("resolved_label")
    if resolved:
        return f"{resolved}('{citation.raw_text}')"
    return citation.raw_text
