"""v3 D7: 설정된 출처 가운데 하나라도 조회에 실패하면(키 없음·요청 한도·오류) 학술자료를 NOT_FOUND로 판정하지 않는다."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from packages.common.enums import AdapterStatus, CitationType
from packages.common.schemas import Citation
from packages.legal_engine.verifier import LegalVerifier


def response(status, records=(), name="x"):
    return SimpleNamespace(status=status, records=list(records), source_record=SimpleNamespace(
        source_record_id=f"S-{name}", adapter=name, query="q"), message=f"{name}:{status}", adapter=name)


def verify(responses):
    registry = SimpleNamespace(search_academic=lambda q, doi=None: responses)
    c = Citation.create(type=CitationType.ACADEMIC, raw_text="김○○, 「군 징계법 신론」, 법문사, 2023", document_id="d")
    c.title = "군 징계법 신론"
    return LegalVerifier(registry).verify_citations([c])


@pytest.mark.parametrize("failed", [AdapterStatus.MISSING_KEY, AdapterStatus.RATE_LIMITED, AdapterStatus.ERROR])
def test_reproduction_partial_source_failure_is_unverified_with_failed_source_named(failed):
    result = verify([response(AdapterStatus.READY, name="crossref"), response(failed, name="kci")])
    [verdict] = result.data["verdicts"]
    assert verdict["status"] == "UNVERIFIED"
    [finding] = result.findings
    assert str(finding.status) == "UNVERIFIED" and "kci" in finding.detail


def test_not_found_only_when_every_configured_source_answered():
    result = verify([response(AdapterStatus.READY, name="crossref"), response(AdapterStatus.READY, name="kci")])
    assert result.data["verdicts"][0]["status"] == "NOT_FOUND"


def test_synthetic_all_sources_failed_is_unverified():
    result = verify([response(AdapterStatus.RATE_LIMITED, name="semantic_scholar"),
                     response(AdapterStatus.MISSING_KEY, name="kci")])
    assert result.data["verdicts"][0]["status"] == "UNVERIFIED"
