"""User-provided synthetic PDF; oracle contents are never passed to the pipeline."""
import json
from pathlib import Path

import pytest

from packages.common.enums import ExternalAIPolicy
from packages.common.storage import sha256_file
from packages.legal_engine import extract_from_text
from packages.source_adapters.legal_history import _children, select_provision
from packages.verification_engine.pipeline import DocumentInput, ProjectContext, VerificationPipeline


def test_synthetic_pdf_preserves_baseline_and_fixes_parsing():
    path = Path(__file__).parent / "fixtures/school_violence_synthetic.pdf"
    result = VerificationPipeline().run("school-regression", ProjectContext(
        "school-regression", case_date="2026-06-20", external_ai_policy=ExternalAIPolicy.LOCAL_ONLY),
        [DocumentInput("school", str(path), path.name, "application/pdf", sha256_file(path))])
    assert not result.errors
    doc = result.documents[0]
    baseline = json.loads((Path(__file__).parent / "golden/school_protected.json").read_text())
    actual = [[f.confidence_features.get("rule_id"), str(f.status), str(f.severity), str(f.evidence_grade)]
              for f in doc.findings]
    for protected in baseline["protected_findings"]:
        assert protected in actual
    assert doc.quarantined is baseline["quarantined"]
    assert doc.authorship["verdict"] == baseline["authorship"]
    assert doc.engine_data["model_input"]["instructions_removed"] >= 1
    from packages.verification_engine.sanitized_input import sanitized_reading_text
    safe, _ = sanitized_reading_text(doc.normalized, doc.findings)
    assert "SYSTEM OVERRIDE" not in safe
    assert not result.model_executions
    assert any(all(f.confidence_features.get(k) == v for k, v in baseline["arithmetic"].items())
               for f in doc.findings)
    citations = {(c["law_name"], c["article"], c["paragraph"]) for c in doc.citations}
    assert ("학교폭력예방 및 대책에 관한 법률", "17", None) in citations
    attachments = doc.engine_data["attachments"]
    numbered = [i for i in attachments["items"] if (i.get("reference") or "").startswith("갑")]
    assert len(numbered) == 6
    assert {i["reference"] for i in numbered} == {f"갑 제{i}호증" for i in range(1, 7)}
    assert all(i["status"] == "REFERENCE_MISSING" for i in numbered)
    assert not any("000원" in i["name"] or i["name"] == "본 파일" for i in attachments["items"])
    [check] = attachments["hashes"]
    assert check["claimed_value"] == "7A4C-TEST-9991-FAKE-VIDEO"
    assert check["related_reference"] == "갑 제6호증"
    assert check["format_status"] == "FORMAT_INVALID" and check["comparison"] == "NO_FILE"
    assert check["authenticity"] == "NOT_ESTABLISHED_BY_HASH"
    assert any("소장 작성자" in f.title and str(f.status) == "UNVERIFIED" for f in doc.findings)
    assert not any("진술서에 서명이 없다" in f.title for f in doc.findings)
    rules = {f.confidence_features.get("rule_id") for f in doc.findings}
    assert {"CALC.CLAIM_TOTAL_MISMATCH", "CALC.INCLUDED_ITEM_NOT_LISTED", "GEN.COST_SCOPE_OVERCLAIM"} <= rules
    assert sum(f.confidence_features.get("rule_id") == "CALC.CLAIM_TOTAL_MISMATCH" for f in doc.findings) == 1


def test_official_alias_field_and_amount_anchor_normalization():
    from packages.source_adapters.law_go_kr import _normalize_law_payload
    from packages.verification_engine.ai_document_detector import value_anchors
    assert _normalize_law_payload({"LawSearch": {"law": [{"법령명한글": "가상법", "법령명약칭": "가법"}]}})[0]["abbreviation"] == "가법"
    assert value_anchors("3천만 원") == value_anchors("30,000,000원") == {"A:30000000"}


@pytest.mark.parametrize("text,listed,expected", [
    ("위 항목을 합산하면 200원이지만 청구서 본문에서는 300원을 청구합니다.", False, "CALC.CLAIM_TOTAL_MISMATCH"),
    ("위 항목을 합산하면 200원이다. 일부 청구로 청구서 본문에서는 100원을 청구합니다.", False, None),
    ("향후 치료비 100원이 이미 합계에 포함되어 있다.", False, "CALC.INCLUDED_ITEM_NOT_LISTED"),
    ("향후 치료비 100원이 이미 합계에 포함되어 있다.", True, None),
])
def test_claim_amount_scope_and_negative_controls(text, listed, expected):
    from packages.claim_engine.claim_amounts import claim_amount_findings
    from packages.common.schemas import Block, NormalizedDocument, Page
    doc = NormalizedDocument("synthetic", "test.txt", "text/plain", "hash",
        pages=[Page(1, blocks=[Block("b1", text, 1)])],
        structure={"tables": [{"cells": [["항목", "금액"], ["진료비", "100원"],
                    ["향후 치료비" if listed else "위자료", "100원"], ["합계", "200원"]]}]})
    assert {f.confidence_features["rule_id"] for f in claim_amount_findings(doc)} == ({expected} if expected else set())


@pytest.mark.parametrize("marker", ["⑥", "6", "제6항"])
def test_paragraph_numbers_preserve_explicit_identifiers(marker):
    children = _children({"항": {"항번호": marker, "항내용": "⑥ 독립 항의 본문"}},
                         "항", "항번호", "항내용", "paragraph")
    assert children[0]["number"] == "6"


def test_empty_number_uses_text_marker_and_article_reading_survives_unknown_number():
    children = _children({"항": [{"항번호": "", "항내용": "⑥ 독립 항의 본문"}]},
                         "항", "항번호", "항내용", "paragraph")
    law = {"provisions": [{"number": "16", "text": "제16조 보호조치", "paragraphs": children}]}
    assert select_provision(law, "16", "6")["text"] == "⑥ 독립 항의 본문"
    unknown = _children({"항": {"항번호": "unreadable", "항내용": "번호를 확인할 수 없는 항"}},
                        "항", "항번호", "항내용", "paragraph")
    law["provisions"][0]["paragraphs"] += unknown
    assert select_provision(law, "16")["status"] == "VERIFIED"
    assert select_provision(law, "16", "6")["status"] == "UNVERIFIED"


def test_topic_continuation_does_not_cross_new_law_or_sentence():
    for text in ("민법 제750조는 손해배상이다. 제751조는 별도이다.",
                 "민법 제750조는 형법과 다르고, 제17조는 별도이다."):
        assert len(extract_from_text(text)) == 1
