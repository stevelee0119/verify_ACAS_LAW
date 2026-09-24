"""v3 D5: 같은 인용에 서로 모순되는 판정 항목이 남지 않게 보고서 전에 일관성을 검사한다."""
from __future__ import annotations

from packages.claim_engine.assertion import uncertainty_findings
from packages.common.enums import CitationType, EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Citation, Finding
from packages.verification_engine.finalize import enforce_consistency


def _cite(raw):
    return Citation.create(type=CitationType.CASE, raw_text=raw, document_id="d")


def test_uncertainty_finding_names_the_citations_it_relies_on():
    c = _cite("대법원 2006. 12. 21. 선고 2006두16274 판결")
    [f] = uncertainty_findings("대법원 2006. 12. 21. 선고 2006두16274 판결은 명백히 이를 인정하였다.", unverified_citations=[c])
    assert f.confidence_features["citation_ids"] == [c.citation_id]


def _uncertainty(ids):
    return Finding.create(type=FindingType.UNCERTAINTY_NOT_DISCLOSED, status=VerificationStatus.SUSPICIOUS,
                          severity=Severity.HIGH, evidence_grade=EvidenceGrade.B,
                          title="원문 미확보 상태에서 확정적으로 서술했다", detail="",
                          confidence_features={"citation_ids": ids})


def test_reproduction_uncertainty_is_removed_when_the_citation_was_compared_with_the_original():
    kept, issues = enforce_consistency([_uncertainty(["c1"])], {"c1": "CONTRADICTED"})
    assert kept == [] and issues and issues[0]["rule"] == "UNCERTAINTY_REQUIRES_UNVERIFIED"


def test_synthetic_uncertainty_is_kept_for_not_found_or_unverified():
    for status in ("NOT_FOUND", "UNVERIFIED"):
        kept, issues = enforce_consistency([_uncertainty(["c2"])], {"c2": status})
        assert len(kept) == 1 and not issues


def test_synthetic_mixed_citations_keep_only_when_one_is_still_unverified():
    kept, _ = enforce_consistency([_uncertainty(["c3", "c4"])], {"c3": "VERIFIED", "c4": "UNVERIFIED"})
    assert len(kept) == 1
    kept, _ = enforce_consistency([_uncertainty(["c3", "c5"])], {"c3": "VERIFIED", "c5": "PARTIALLY_VERIFIED"})
    assert kept == []
