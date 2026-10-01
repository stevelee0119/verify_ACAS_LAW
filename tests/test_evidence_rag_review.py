"""Synthetic regressions for authorship coverage, safe reference retrieval and grounded context advice."""
import asyncio
import copy
from types import SimpleNamespace

import pytest

from packages.legal_engine.argument_validity_verifier import _context_review
from packages.legal_engine.opinion_attribution import _clause_negated, direction_conflict
from packages.legal_engine.reasoning_format import format_context_review
from packages.rag_engine import relevance
from packages.rag_engine.extract import extract
from packages.rag_engine.review import report_lines
from packages.verification_engine.ai_document_detector import detect_ai_document
from test_drive_rag_relevance import Drive, library
from test_review_hardening import AgreeingRouter, document
from test_v099_drive_fixes import book, ATTACKS


def test_8803_chars_are_all_reviewed_without_extra_calls():
    router = AgreeingRouter()
    result = asyncio.run(detect_ai_document(document("가" * 8803), [], router=router))
    coverage = result.signals["coverage"]
    assert coverage["inspected_chars"] == 8803 and coverage["omitted_chars"] == 0
    assert coverage["is_full_coverage"] and coverage["char_limit"] == 24000
    # 사용자 결정(2026-09-30, TK-11): AI 판정은 모델 의견의 다수결이 정한다.
    # 객관적 흔적 부재는 별도 축(objective_traces: 0)으로 표시되며 판정을 제한하지 않는다.
    assert result.verdict == "AI_FULL_GENERATION_LIKELY"
    assert result.signals.get("decision_rule") == "MAJORITY_AI_CONSENSUS"
    assert result.signals.get("objective_traces", 0) == 0


def test_human_model_inference_is_not_admitted_as_a_fact():
    class HumanRouter(AgreeingRouter):
        async def consult_all(self, *args, **kwargs):
            self.request = args[1]
            return [SimpleNamespace(used=True, parsed={"verdict": "HUMAN_AUTHORED_LIKELY", "ai_score": 0.01,
                    "reasons": ["전문적 문체와 AI 흔적 부재"]}, text="",
                    executions=[SimpleNamespace(provider=p, model="test")]) for p in ("one", "two")]
    router = HumanRouter()
    result = asyncio.run(detect_ai_document(document('판례는 “책임을 부담한다”라고 판시했다.'), [], router=router))
    assert result.verdict == "UNCERTAIN" and result.signals["decision_rule"] == "AGREED_UNCERTAIN"
    for opinion in result.signals["llm_opinions"]:
        assert opinion["verdict"] == "UNCERTAIN" and opinion["raw_verdict"] == "HUMAN_AUTHORED_LIKELY"
        assert opinion["admissibility_note"]
    assert "빈칸" in router.request.system and "검사기" in router.request.system
    assert result.signals["coverage"]["quote_masked_chars"] > 0


@pytest.mark.parametrize("phrase", ["압수·수색을 적법하다고 평가할 수 없다.",
    "특별한 사정이 없는 이상 압수·수색이 적법하다고 평가할 수 없고 증거능력이 부정된다."])
def test_legal_negative_conclusions_do_not_quarantine_casebooks(tmp_path, phrase):
    parsed = extract(book(tmp_path / "benign.pdf", 30, {p: phrase for p in (4, 8, 12, 16)}), "book.pdf", "application/pdf")
    assert parsed["reason"] == "" and parsed["read_pages"] == 30
    assert parsed["scan_findings"] == []


def test_real_instructions_still_quarantine_after_benign_legal_text(tmp_path):
    phrase = "압수수색을 적법하다고 평가할 수 없다. " + ATTACKS[0]
    parsed = extract(book(tmp_path / "attack.pdf", 30, {p: phrase for p in (4, 8, 12, 16)}), "book.pdf", "application/pdf")
    assert parsed["reason"] == "REFERENCE_QUARANTINED" and not parsed["chunks"]


def test_formal_korean_endings_do_not_dominate_search():
    text = "형법 횡령죄는 성립하지 않습니다. 형사소송법 증거능력을 검토하였습니다. 적용됩니다. 없습니다. 있습니다."
    terms = relevance.query_tokens(text * 30)
    assert not set(terms) & {"없습", "됩니", "습니", "상됩", "않습", "였습", "입니", "합니"}
    assert {"형법", "횡령", "증거", "능력"} <= set(terms)


def test_priority_books_get_independent_search_but_not_a_title_only_pass(tmp_path, monkeypatch):
    text = "형법 형사소송법 횡령죄 재물 보관 증거능력 자백 보강증거를 검토한다."
    refs = {("일반", "사건처리 예제.txt"): text * 100,
            ("판례", "형법표준판례.pdf"): text + " 횡령죄 관련 법리",
            ("판례", "형사소송법표준판례.pdf"): text + " 증거능력 관련 법리",
            ("판례", "민법표준판례.pdf"): "임대차계약 보증금 반환 채무"}
    lib = library(tmp_path, Drive(refs))
    monkeypatch.setattr(relevance, "CANDIDATE_CHUNKS", 1)
    selected = lib.select(text)
    assert {i["title"] for i in selected["sources"]} >= {"형법표준판례.pdf", "형사소송법표준판례.pdf"}
    assert all(i["searched"] and i["selected"] for i in selected["priority_references"])
    assert selected["files_selected"] == len({i["file_id"] for i in selected["sources"]})
    assert not lib.select("형법 표준판례 우주선 궤도추진 우주선 연료항법")["sources"]


def test_multiple_issues_retrieve_each_casebook_without_matching_fictional_names(tmp_path):
    procedure = "형사소송법 자백의 증거능력과 보강증거의 필요성을 다툰다. 증인의 진술과 증거조사의 절차를 검토한다. "
    substance = "형법 횡령죄에서 타인의 재물을 보관하는 지위와 불법영득의사가 필요하다. 재물의 반환을 거부하였다. "
    text = "가나다인물라마바인물사아자인물차카타인물파하인물의 행적을 분석합니다. " * 50 + procedure * 10 + substance * 10
    refs = {("판례", "형사소송법표준판례.pdf"): procedure * 3,
            ("판례", "형법표준판례.pdf"): substance * 3,
            ("다른 분야", "해양 생태계 연구.pdf"): "해류 수온 염분 해조류 서식 해양 생태계" * 10}
    selected = library(tmp_path, Drive(refs)).select(text)
    assert selected["query_windows"] > 1
    assert {s["title"] for s in selected["sources"]} == {"형사소송법표준판례.pdf", "형법표준판례.pdf"}
    assert all(s["shared_terms"] >= 4 for s in selected["sources"])


def test_readable_page_coverage_and_no_text_pages_are_separate(tmp_path):
    from pypdf import PdfWriter
    path = book(tmp_path / "read.pdf", 4, {})
    writer = PdfWriter(clone_from=path)
    writer.add_blank_page(width=595, height=842)
    output = tmp_path / "partial.pdf"
    writer.write(output)
    parsed = extract(output, "partial.pdf", "application/pdf")
    assert parsed["read_pages"] == 4 and parsed["pages"] == 5
    assert parsed["no_text_pages"] == [5] and parsed["unprocessed_pages"] == []
    assert parsed["partial"] and parsed["coverage_note"]


def test_reference_extraction_falls_back_when_native_engine_is_unavailable(tmp_path, monkeypatch):
    import pypdfium2
    def unavailable(*args, **kwargs):
        raise RuntimeError("native unavailable")
    monkeypatch.setattr(pypdfium2, "PdfDocument", unavailable)
    parsed = extract(book(tmp_path / "fallback.pdf", 2, {}), "book.pdf", "application/pdf")
    assert parsed["text_parser"] == "pypdf" and parsed["read_pages"] == 2
    assert parsed["fallback_pages"] == [1, 2]


def test_native_pdf_extraction_in_resource_limited_subprocess(tmp_path):
    from packages.rag_engine.library import isolated_extract

    path = book(tmp_path / "isolated.pdf", 30, {})
    parsed = isolated_extract(path.read_bytes(), path.name, "application/pdf",
                              directory=tmp_path, timeout=30)
    assert parsed["text_parser"] == "pypdfium2"
    assert parsed["read_pages"] == 30 and not parsed["partial"]
    assert parsed["fallback_pages"] == [] and parsed["scan_findings"] == []


def test_reference_extraction_keeps_encryption_boundary(tmp_path):
    from pypdf import PdfWriter
    writer = PdfWriter(clone_from=book(tmp_path / "plain.pdf", 1, {}))
    writer.encrypt("secret")
    encrypted = tmp_path / "encrypted.pdf"
    writer.write(encrypted)
    with pytest.raises(ValueError, match="ENCRYPTED_REFERENCE"):
        extract(encrypted, "encrypted.pdf", "application/pdf")


def test_reference_issues_are_listed_once_in_export():
    summary = {"status": "PARTIAL", "issues": [{"file_id": "a", "name": "casebook.pdf", "reason": "REFERENCE_PARTIALLY_READ"}],
               "inventory": [{"file_id": "a", "name": "casebook.pdf", "status": "INDEXED_PARTIAL",
                              "reason": "REFERENCE_PARTIALLY_READ", "pages": 30, "read_pages": 29, "no_text_pages": [2]}]}
    lines = "\n".join(report_lines(SimpleNamespace(run_manifest={"reference_library": summary}, documents=[])))
    assert "주요 참고문헌 검토 결과(RAG)" in lines
    assert lines.count("casebook.pdf") == 1 and lines.count("REFERENCE_PARTIALLY_READ") == 1
    assert "29/30쪽" in lines and "[2]" in lines


def grounded_pair():
    quote = "판결은 요건 충족 시 책임을 인정한다."
    verdict = {"citation_id": "c1", "review_id": "incident", "official_record": {"full_text": quote}}
    review = {"citation_id": "c1", "review_id": "incident", "model_executed": True, "source_quotes_validated": True,
              "evidence_quotes": [quote], "reason": "법리 취지와 사안 적용을 별도로 검토함",
              "stages": [{"used": True, "name": "primary", "verdict": {"status": "PARTIALLY_VERIFIED",
                          "rationale": "취지는 부합하나 구체적 사실관계 확인이 필요하다.", "evidence_quotes": [quote]}}]}
    return verdict, review


def test_context_opinion_reuses_grounded_review_with_application_limits():
    verdict, review = grounded_pair()
    result = _context_review(verdict, [review])
    assert result["status"] == "ADVISORY_REVIEWED" and result["source_quotes_validated"]
    assert "취지는 부합" in format_context_review(result)
    assert "작성 주체 판정에는 사용하지" in format_context_review(result)
    assert "VERIFIED" != result["status"]


@pytest.mark.parametrize("change", [{"citation_id": "other"}, {"review_id": "precedent"},
    {"evidence_quotes": ["꾸며낸 인용"]}, {"model_executed": False}, {"source_quotes_validated": False}])
def test_ungrounded_or_different_citation_review_cannot_be_reused(change):
    verdict, review = grounded_pair()
    review.update(copy.deepcopy(change))
    result = _context_review(verdict, [review])
    assert result["status"] == "UNVERIFIED" and not result["opinions"]


def test_reporting_tail_preserves_negative_claim_and_subordinate_negative_is_not_predicate():
    assert _clause_negated('피해자에게 재산상 손해가 발생하였다고 할 수 없다”고 판시하였습니다( 등 참조).')
    assert not _clause_negated('진술할 수 없는 때에 해당하는지')
    assert direction_conflict("책임을 인정할 수 있다.", "책임을 인정할 수 있는지 여부(소극)")
    assert direction_conflict("책임을 인정할 수 없다.", "책임을 인정할 수 있는지 여부(소극)") is None
