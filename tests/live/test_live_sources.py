"""국가법령정보센터 실연동 통합 테스트(G1·J1·R3·R4·R6).

실존 헌재 결정 사건번호는 scripts/fetch_official_sources.py의 DETC_PROBES(CI 공식 조회로 실존을 확인한 목록)와
병합 표기 2건이다. 결정일·사건명 같은 사실은 테스트에 적지 않고, 조회 결과로 받은 값을 결과 파일에 남긴다.
"""
from __future__ import annotations

import pytest

from packages.common.enums import CitationType, VerificationStatus
from packages.legal_engine.normalize import same_case_number
from scripts.fetch_official_sources import DETC_PROBES
from tests.live.conftest import record

# 헌가·헌바·헌마·헌나·헌다를 모두 포함한다(11건). 병합 표기는 대표 사건번호로 조회한다.
MERGED = [("헌법재판소 2004헌마554·566(병합) 결정", "2004헌마554"), ("헌법재판소 2011헌바379 등(병합) 결정", "2011헌바379")]


def _exact(response, number):
    return [r for r in response.records if same_case_number(str(r.get("case_number") or ""), number)]


@pytest.mark.live_item("G1")
def test_G1_constitutional_decisions_are_found_by_exact_number(registry):
    kinds = {n[n.index("헌"):n.index("헌") + 2] for n in DETC_PROBES}
    assert {"헌가", "헌바", "헌마"} <= kinds and len(DETC_PROBES) >= 10
    cases, found, wrong = [], 0, 0
    for number in DETC_PROBES:
        response = registry.law.search_case(number, court="헌법재판소")
        exact = _exact(response, number)
        found += bool(exact)
        wrong += sum(1 for r in response.records if not same_case_number(str(r.get("case_number") or ""), number))
        cases.append({"case_number": number, "status": str(response.status), "found": bool(exact),
                      "decision_date": (exact[0].get("decision_date") if exact else None)})
    record("G1", prepared=len(DETC_PROBES), detected=found, false_positive=0, cases=cases,
           summary=f"헌재 결정 {found}/{len(DETC_PROBES)}건 사건번호 정확 일치(다른 번호 기록 {wrong}건은 채택하지 않음)")
    assert found / len(DETC_PROBES) >= 0.9


@pytest.mark.live_item("J1")
def test_J1_merged_notation_is_verified_through_the_lead_number(registry):
    from packages.legal_engine.citation_extractor import extract_from_text
    from packages.legal_engine.verifier import LegalVerifier

    verifier = LegalVerifier(registry)
    cases, ok = [], 0
    for text, lead in MERGED:
        citations = [c for c in extract_from_text(text, document_id="live") if c.type == CitationType.CONSTITUTIONAL]
        assert citations, text
        verdict = verifier.verify_case(citations[0])
        adopted = str((verdict.official_record or {}).get("case_number") or "")
        good = verdict.status != VerificationStatus.NOT_FOUND and same_case_number(adopted, lead)
        ok += good
        cases.append({"text": text, "lead": lead, "merged": (citations[0].attributes or {}).get("merged_case_numbers"),
                      "status": str(verdict.status), "adopted": adopted})
    record("J1", prepared=len(MERGED), detected=ok, cases=cases, summary=f"병합 표기 {ok}/{len(MERGED)}건 대표 번호로 확인")
    assert ok == len(MERGED)


@pytest.mark.live_item("R4")
def test_R4_only_exact_number_records_are_adopted(registry):
    # 앞자리가 같은 다른 사건(예: 554 ↔ 55)을 채택하면 안 된다. 조회 결과가 없으면 '부존재'가 아니라 미확인이다.
    probes = ["2004헌마55", "2011헌바37", "2016헌나10"]
    cases, adopted_wrong = [], 0
    from packages.legal_engine.verifier import LegalVerifier
    from packages.common.schemas import Citation

    verifier = LegalVerifier(registry)
    for number in probes:
        citation = Citation.create(type=CitationType.CONSTITUTIONAL, raw_text=f"헌법재판소 {number} 결정",
                                   document_id="live", case_number=number, court="헌법재판소")
        verdict = verifier.verify_case(citation)
        adopted = str((verdict.official_record or {}).get("case_number") or "")
        bad = bool(adopted) and not same_case_number(adopted, number)
        adopted_wrong += bad
        cases.append({"case_number": number, "status": str(verdict.status), "adopted": adopted or None})
    record("R4", prepared=len(probes), detected=len(probes) - adopted_wrong, false_positive=adopted_wrong, cases=cases,
           summary=f"다른 번호 기록 채택 {adopted_wrong}건")
    assert adopted_wrong == 0


def _pdf(tmp_path, name, header, lines):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    path = tmp_path / name
    c = canvas.Canvas(str(path), pagesize=A4)
    for page_lines in lines:
        c.setFont("HYSMyeongJo-Medium", 9)
        c.drawString(60, 810, header)
        c.setFont("HYSMyeongJo-Medium", 11)
        for i, line in enumerate(page_lines):
            c.drawString(60, 760 - i * 18, line)
        c.showPage()
    c.save()
    return path


def _run(tmp_path, registry, path):
    import hashlib

    from packages.pii_engine import PseudonymStore
    from packages.verification_engine import pipeline as module
    from packages.verification_engine.pipeline import DocumentInput, ProjectContext, VerificationPipeline

    module.PseudonymStore = lambda project_id: PseudonymStore(project_id, root=tmp_path / "vault")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = VerificationPipeline(registry=registry).run(
        "live-run", ProjectContext("live-project"), [DocumentInput("d1", str(path), path.name, "application/pdf", digest)])
    return result.documents[0]


@pytest.mark.live_item("R3")
def test_R3_line_broken_court_and_date_survive_to_the_live_lookup(tmp_path, registry):
    # rules.json의 공식 원문 출처(대법원 1996. 2. 15. 선고 95다38677 전원합의체 판결)를 줄을 나눠 적는다.
    path = _pdf(tmp_path, "r3.pdf", "준비서면", [["1. 이 사건 쟁점에 관하여 대법원 1996. 2. 15.",
                                                  "선고 95다38677 전원합의체 판결을 참조한다."]])
    document = _run(tmp_path, registry, path)
    citations = [c for c in document.citations if c.get("case_number") == "95다38677"]
    verdicts = {v["citation_id"]: v for v in document.engine_data.get("legal_verdicts", [])}
    ok = bool(citations) and citations[0].get("court") == "대법원" and citations[0].get("decision_date") == "1996-02-15" \
        and verdicts.get(citations[0]["citation_id"], {}).get("status") != "NOT_FOUND"
    record("R3", prepared=1, detected=int(ok), cases=[{"citation": citations[0] if citations else None,
                                                        "status": verdicts.get(citations[0]["citation_id"], {}).get("status")
                                                        if citations else None}])
    assert ok


@pytest.mark.live_item("R6")
def test_R6_running_head_citation_is_not_counted(tmp_path, registry):
    header = "준비서면 · 대법원 95다38677 판결 원용"
    path = _pdf(tmp_path, "r6.pdf", header, [["1. 대법원 1996. 2. 15. 선고 95다38677 전원합의체 판결은 공무원 개인 책임을 다룬다."],
                                            ["2. 위 대법원 1996. 2. 15. 선고 95다38677 전원합의체 판결의 다수의견에 따른다."],
                                            ["3. 이상과 같다."]])
    document = _run(tmp_path, registry, path)
    count = sum(1 for c in document.citations if c.get("case_number") == "95다38677")
    record("R6", prepared=1, detected=int(count == 2), false_positive=max(0, count - 2),
           cases=[{"citations_counted": count, "expected": 2}])
    assert count == 2
