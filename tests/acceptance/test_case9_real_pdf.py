"""서면9 실제 PDF 원본 시험(평가 에이전트 소관, 보호 경로). 인계 티켓 TK-22(PDF 입력), TK-29.

`tests/fixtures/case9_state_compensation_google_docs.pdf`는 사용자가 서면9 **온라인 실행에 쓴 PDF 원본**이다
(Google Docs Skia/PDF 렌더러, 3쪽, SHA-256 f79abba4…. 온라인 보고서 input_snapshot.documents[0].sha256과 같다). 합성 PDF가 아니다.
같은 서면의 docx(`case9_state_compensation_brief.docx`)와 같은 정답 항목 28개를 잰 뒤(첫 절),
**청구(claim) 분할과 인용 법령명이 입력 방식에 따라 달라지지 않아야 한다**는 불변식을 잰다(둘째 절).

측정 사실(2026-10-02, 오프라인 LV_ALLOW_NETWORK=0, 기준 9933548·4차 e6b58fd 모두 같음):
- 정답 항목은 PDF 27/28(docx·텍스트와 같음, LEG-2는 TK-24).
- 청구는 PDF 70개·docx 40개. PDF는 줄 하나가 청구 하나가 되고 육군 규정 제22조 제4항 인용 문장이 4개로 쪼개진다(앞 3개는 DOCUMENT_META·검증 대상 아님).
  docx는 같은 문장이 LEGAL_RULE 청구 1개다. 온라인 실행(9933548)의 70개·3조각 분할이 오프라인에서 그대로 재현된다.
- 인용 법령명: PDF는 '육군 야외 기동훈련안전통제 및 사고조사 규정'(줄바꿈에서 띄어쓰기가 빠짐), docx는 '육군 야외 기동훈련 안전통제 및 사고조사 규정'.
  이 어긋남이 온라인에서 Drive 참고자료 연결(linked_claims 1/17)이 빠진 직접 원인 후보다(참고자료 이름과 일치하지 않는다).
미해결은 strict xfail이다. 고치면 XPASS(strict)로 실패하므로 평가 에이전트가 표시를 지운다.
"""
from __future__ import annotations

import functools
import hashlib
import importlib.util
import inspect
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("LV_ALLOW_NETWORK", "0")

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "probe_document.py"
SPEC = ROOT / "tests" / "fixtures" / "probes" / "case9_state_compensation.json"
PDF = ROOT / "tests" / "fixtures" / "case9_state_compensation_google_docs.pdf"
DOCX = ROOT / "tests" / "fixtures" / "case9_state_compensation_brief.docx"
ONLINE_RUN_SHA256 = "f79abba4abe4ffa4fecc273a8fc89ccbccc3a91f3e3259a92a5c4003a8d4df92"

# 알려진 미해결(실제 PDF 입력의 정답 항목). 항목 id → 인계 티켓
KNOWN_OPEN_CHECKS = {"LEG-2": "TK-24"}


def _probe():
    spec = importlib.util.spec_from_file_location("probe_document_case9_real_pdf", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("probe_document_case9_real_pdf", module)
    spec.loader.exec_module(module)
    return module


probe = _probe()
CHECKS = {c["id"]: c["label"] for c in probe.load_spec(SPEC)["checks"]}


def _row(obj) -> dict:
    return obj.to_dict() if hasattr(obj, "to_dict") else (obj if isinstance(obj, dict) else {})


@functools.lru_cache(maxsize=None)
def processed(path: str) -> dict:
    """문서를 전체 파이프라인(오프라인)으로 처리해 청구·인용을 모은다."""
    os.environ.setdefault("LV_DATA_DIR", tempfile.mkdtemp(prefix="case9_real_pdf_"))
    from packages.common.storage import sha256_file
    from packages.verification_engine import DocumentInput, ProjectContext, VerificationPipeline
    document = Path(path)
    mime = {".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}.get(
        document.suffix.lower(), "application/pdf")
    params = set(inspect.signature(DocumentInput).parameters)
    raw = dict(document_id="real", path=str(document), filename=document.name, mime_type=mime, sha256=sha256_file(document))
    item = DocumentInput(**{k: v for k, v in raw.items() if k in params})
    init = set(inspect.signature(VerificationPipeline.__init__).parameters)
    kwargs = {}
    if "audit" in init:
        from packages.audit_engine import AuditChain
        kwargs["audit"] = AuditChain()
    result = VerificationPipeline(**kwargs).run("real_run", ProjectContext(project_id="real"), [item])
    doc = result.documents[0]
    claims = []
    for claim in doc.claims:
        row = _row(claim)
        attrs = row.get("attributes") or {}
        claims.append({"text": str(row.get("text") or ""), "type": str(row.get("type") or ""),
                       "target": bool(attrs.get("verification_target"))})
    citations = [{"law": str(_row(c).get("law_name") or ""), "article": str(_row(c).get("article") or ""),
                  "raw": str(_row(c).get("raw_text") or "")} for c in doc.citations]
    return {"claims": claims, "citations": citations}


@functools.lru_cache(maxsize=None)
def pdf_results() -> dict:
    args = [sys.executable, str(SCRIPT), "run", "--spec", str(SPEC), "--input", str(PDF), "--json"]
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=900)
    assert proc.returncode == 0, proc.stderr[-400:]
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    assert data["input"] == "pdf"
    return {row["id"]: row["passed"] for row in data["rows"]}


# ------------------------------------------------------------------------------ 입력 고정 ---
def test_fixture_is_the_online_run_input():
    assert hashlib.sha256(PDF.read_bytes()).hexdigest() == ONLINE_RUN_SHA256


# ------------------------------------------------------------------------------ 정답 항목(실제 PDF) ---
def _case(check_id: str):
    ticket = KNOWN_OPEN_CHECKS.get(check_id)
    marks = [pytest.mark.xfail(strict=True, raises=AssertionError, reason=f"{ticket}: 미해결")] if ticket else []
    return pytest.param(check_id, marks=marks, id=check_id)


@pytest.mark.parametrize("check_id", [_case(c) for c in CHECKS])
def test_case9_check_on_real_pdf(check_id):
    assert pdf_results().get(check_id) is True, f"{check_id} {CHECKS[check_id]}"


def test_known_open_ids_are_real_checks():
    assert set(KNOWN_OPEN_CHECKS) <= set(CHECKS)


# ------------------------------------------------------------------------------ 입력 방식 불변(TK-22) ---
def _claim_with(claims: list, *needles: str) -> list:
    return [c for c in claims if all(n in c["text"] for n in needles)]


def test_docx_regulation_sentence_is_one_claim():
    """기준선: docx는 육군 규정 제22조 제4항 인용 문장이 청구 하나이고 검증 대상이다."""
    hits = _claim_with(processed(str(DOCX))["claims"], "제22조 제4항", "일체 인정하지 아니한다")
    assert len(hits) == 1 and hits[0]["target"] is True


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="TK-22: PDF는 줄 하나가 청구 하나라 인용 문장이 쪼개진다(9933548·e6b58fd 같음)")
def test_pdf_regulation_sentence_is_one_claim():
    """같은 문장이 PDF에서도 청구 하나(검증 대상)여야 한다."""
    hits = _claim_with(processed(str(PDF))["claims"], "제22조 제4항", "일체 인정하지 아니한다")
    assert len(hits) == 1 and hits[0]["target"] is True


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="TK-22: PDF 줄바꿈에서 인용 법령명의 띄어쓰기가 빠진다(9933548·e6b58fd 같음)")
def test_pdf_citation_law_name_matches_docx():
    """인용 법령명은 입력 방식과 무관해야 한다. 참고자료(Drive) 이름 대조가 이 값에 의존한다."""
    def regulation(path):
        return {(c["law"], c["article"]) for c in processed(path)["citations"] if "육군" in c["law"]}
    assert regulation(str(PDF)) == regulation(str(DOCX)) != set()


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="TK-22: PDF는 문단이 아니라 줄 단위로 청구가 된다(PDF 70개·docx 40개, 9933548·e6b58fd 같음)")
def test_pdf_claim_count_close_to_docx():
    """같은 서면의 청구 수는 입력 방식에 따라 크게 달라지지 않아야 한다(머리말 표 등으로 약간 다를 수 있어 20% 이내를 허용)."""
    pdf, docx = len(processed(str(PDF))["claims"]), len(processed(str(DOCX))["claims"])
    assert abs(pdf - docx) <= 0.2 * docx, (pdf, docx)
