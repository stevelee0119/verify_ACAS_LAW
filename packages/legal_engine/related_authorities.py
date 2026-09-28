"""Explicitly separated discovery of bounded related authorities, never invented citations."""
import re

from packages.common.enums import CitationType
from packages.common.schemas import Citation
from .normalize import canonical_law_name

NATIONAL_CONTRACT = "국가를 당사자로 하는 계약에 관한 법률"


def candidates(doc, citations):
    statutes = {(canonical_law_name(c.law_name or "").replace(" ", ""), c.article) for c in citations
                if c.type == CitationType.STATUTE}
    national = canonical_law_name(NATIONAL_CONTRACT).replace(" ", "")
    if not any(name == national for name, _ in statutes) or not re.search(r"지체상금", doc.visible_text):
        return []
    authorities = [(NATIONAL_CONTRACT, "26", "지체상금의 요건·귀책 및 면제 사유 검토"),
                   ("민법", "492", "납품대금 원금과의 상계 요건 별도 검토"),
                   ("민법", "493", "상계 의사표시 및 효력 별도 검토")]
    return [Citation.create(CitationType.STATUTE, f"{law} 제{article}조", document_id=doc.document_id,
                law_name=law, article=article, attributes={"origin": "DISCOVERED_AUTHORITY", "purpose": purpose})
            for law, article, purpose in authorities
            if (canonical_law_name(law).replace(" ", ""), article) not in statutes]


def review_related_authorities(doc, citations, verifier, *, case_date=None, quick=False):
    related = candidates(doc, citations)
    if not related:
        return None, []
    note = ("국가계약법 제15조 제3항의 지급지연 이자와 지체상금 상계는 납품대금 원금 상계와 구별한다. "
            "약정 효력·감액·귀책·상계 요건은 별도 판단이며 산술 검산만으로 적법성을 확정하지 않는다.")
    if quick:
        return {"origin": "DISCOVERED_AUTHORITY", "status": "NOT_ASSESSED", "note": note,
                "candidates": [c.to_dict() for c in related], "reason": "QUICK_PROFILE", "advisory_only": True}, []
    verified = verifier.verify_citations(related, case_date=case_date)
    return {"origin": "DISCOVERED_AUTHORITY", "status": "SOURCE_REVIEW_ONLY", "note": note,
            "candidates": [c.to_dict() for c in related], "verdicts": verified.data.get("verdicts", []),
            "reference_date": case_date, "temporal_applicability": "REVIEW_REQUIRED",
            "advisory_only": True, "included_in_explicit_citation_count": False}, verified.source_records


def report_lines(documents):
    lines = []
    for doc in documents:
        review = doc.engine_data.get("related_authorities")
        if not review:
            continue
        lines.append(f"{doc.filename}: 추가 관련 법조문 검토 / {review['status']} (문서의 직접 인용과 별도)")
        lines.append(review.get("note") or review.get("reason", "추가 확인 필요"))
        for candidate in review.get("candidates", []):
            verdict = next((v for v in review.get("verdicts", [])
                            if v.get("citation_id") == candidate.get("citation_id")), {})
            lines.append(f"{candidate['raw_text']} / 출처 조회: {verdict.get('status', 'NOT_ASSESSED')} / "
                         "사건 당시 적용·주장 타당성: 별도 검토 필요")
    return lines
