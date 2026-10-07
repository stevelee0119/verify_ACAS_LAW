"""[평가 에이전트 소관] F3 보호 시험 T6~T9·요청 본문 스키마 (F3 지시서 docs/handoff/PROMPT_FOR_F3.md 4절, 2026-10-07 고정).

설계 회신 전에 고정한다. 구현 측은 이 파일을 고치지 않는다. 미해결 단언은 strict xfail이고, 구현 중 XPASS가 나면 평가 측이 표시를 지운다.

- T6 참고자료 위계: 공식 미발견 인용이 참고자료 본문에 같은 인용으로 있으면 `reference_status`만 SUPPORTED가 되고
  `official_status=OFFICIAL_NOT_FOUND`·finding·심각도는 그대로다(D4). 제목에만 있거나 읽지 못한 파일로는 올리지 않는다(TK-29 U1).
- T7 대조율 표시: `claim_coverage`의 분모는 대조 대상 주장 수이고, 상한(문서당 10주장, 19b 5.2) 초과 주장은
  `REASON_BUDGET_EXCEEDED`(19b 5.2) 사유로 분모에 남는다. 화면은 데이터 값을 그대로 보인다.
- T8 다른 분야 동작: 분야가 다른 합성 자료 2세트에서 같은 절차·같은 구조의 결과.
- T9 외부 호출: `LOCAL_ONLY`면 공급자 호출 0, QUICK이면 참고자료 발췌를 실은 호출 0. 참고자료 발췌의 연락처·주민등록번호는
  공급자에 도달하지 않고, 공급자에 간 모든 요청은 `inspect_request`를 지난다. 주장 단위 경로도 같다(상한 포함).
- 요청 본문 스키마(19b 6.1, TK-55): 주장 단위 요청의 키는 허용 목록 안에 있고, 사람을 가리키는 키가 없다.
  허용 목록 밖 키의 fail-closed 단위 시험은 설계 보충이 검사 함수의 위치를 정한 뒤(설계 회신 때) 이 파일에 더한다.

하네스: 실제 `VerificationPipeline`·`LLMRouter.run`에 가짜 Drive(`ReferenceLibrary`의 client_factory)와 가짜 공급자만 붙인다.
외부 네트워크는 쓰지 않는다. 공식 판례 조회는 '조회 성공·결과 없음'으로 대역한다(실재 여부와 무관한 합성 조건이다).
가짜 공급자는 참고자료 대조 요청(응답 스키마에 observations가 있는 요청)에 빈 의견을 돌려준다. 그래서 SUPPORTED는 모델 의견이 아니라
인용 동일성 대조(지시서 3절 1)에서 와야 한다. 서면·참고자료·사건번호·연락처·주민등록번호는 모두 지어낸 합성 값이다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("LV_ALLOW_NETWORK", "0")
os.environ.setdefault("LV_DATA_DIR", tempfile.mkdtemp(prefix="f3_protected_"))
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from packages.common.config import get_settings  # noqa: E402
from packages.common.enums import ExternalAIPolicy, VerificationProfile  # noqa: E402
from packages.common.storage import sha256_file  # noqa: E402
from packages.llm_router import privacy as privacy_module  # noqa: E402
from packages.llm_router import router as router_module  # noqa: E402
from packages.llm_router.providers import LLMResponse  # noqa: E402
from packages.rag_engine import library as library_module  # noqa: E402
from packages.rag_engine.drive import ReferenceError as DriveReferenceError  # noqa: E402
from packages.report_engine.exporters import to_payload  # noqa: E402
from packages.source_adapters.base import AdapterResponse, AdapterStatus  # noqa: E402
from packages.verification_engine import DocumentInput, ProjectContext, VerificationPipeline  # noqa: E402

REAL_LIBRARY = library_module.ReferenceLibrary  # 한 시험에서 두 번 돌릴 때 대역이 겹쳐 감싸지지 않게 원본을 잡아 둔다
REAL_INSPECT = privacy_module.inspect_request
FOLDER = "folderf3protected01"
PHONE = "010-4729-3816"
RRN = "850314-1234562"
OWNER_NAME = "도담결"
OWNER_EMAIL = "dodam.owner@example.com"
ALLOWED_REQUEST_KEYS = {"system_instructions", "claim_id", "claim_text", "reference_sources"}  # 19b 6.1
PERSON_KEY = re.compile(r"name|party|client|suspect|victim|owner|author|user|email|이름|성명|당사자|피해자|의뢰인",
                        re.IGNORECASE)
CLAIM_LIMIT_PER_DOCUMENT, MODEL_CALLS_PER_CLAIM, EXCERPT_CHARS = 10, 3, 4000  # 19b 5.2

# 분야 A(산업안전·손해배상)와 분야 B(주택임대차·보증금). 사건번호는 형식만 맞춘 합성 값이다.
DOMAINS = {
    "safety": {
        "case": "2019다246795",
        "brief": ("준 비 서 면\n원고는 피고 회사 현장 책임자로 근무하였다.\n"
                  "1. 피고의 「안전관리 운영지침」 제7조는 추락 위험이 있는 경우 즉시 작업을 중지하도록 규정한다.\n"
                  "2. 대법원 2019다246795 판결은 사용자의 안전배려의무 위반으로 인한 손해배상책임을 인정하였다.\n"
                  "3. 따라서 피고는 원고에게 손해를 배상할 책임이 있다.\n"),
        "title": "안전관리 운영지침 해설.txt",
        "sentinel": "작업중지 의무를 위반한 경우 징계 사유가 된다",
        "with_case": ("제7조(작업중지) 현장 책임자는 추락 위험이 있는 경우 즉시 작업을 중지하여야 한다. "
                      "대법원 2019다246795 판결은 사용자의 안전배려의무 위반으로 인한 손해배상책임을 인정하였다. "
                      "작업중지 의무를 위반한 경우 징계 사유가 된다."),
        "without_case": ("제7조(작업중지) 현장 책임자는 추락 위험이 있는 경우 즉시 작업을 중지하여야 한다. "
                         "사용자의 안전배려의무 위반으로 인한 손해배상책임은 별도로 검토한다. "
                         "작업중지 의무를 위반한 경우 징계 사유가 된다."),
    },
    "lease": {
        "case": "2020다218925",
        "brief": ("준 비 서 면\n원고는 피고 소유 주택의 임차인이었다.\n"
                  "1. 임대차 종료 후 임대인은 보증금을 반환할 의무가 있고 임차인은 목적물을 인도할 의무가 있다.\n"
                  "2. 대법원 2020다218925 판결은 보증금 반환과 목적물 인도가 동시이행 관계에 있다고 보았다.\n"
                  "3. 따라서 피고는 원고에게 임대차보증금을 반환할 책임이 있다.\n"),
        "title": "주택임대차 분쟁 실무 메모.txt",
        "sentinel": "보증금 반환 지연에 대한 지연손해금 기산일은 별도로 확인한다",
        "with_case": ("임대차 종료 후 임대인은 보증금을 반환할 의무가 있고 임차인은 목적물을 인도할 의무가 있다. "
                      "대법원 2020다218925 판결은 보증금 반환과 목적물 인도가 동시이행 관계에 있다고 보았다. "
                      "보증금 반환 지연에 대한 지연손해금 기산일은 별도로 확인한다."),
        "without_case": ("임대차 종료 후 임대인은 보증금을 반환할 의무가 있고 임차인은 목적물을 인도할 의무가 있다. "
                         "보증금 반환과 목적물 인도의 관계는 사안별로 검토한다. "
                         "보증금 반환 지연에 대한 지연손해금 기산일은 별도로 확인한다."),
    },
}

# T7: 문서당 대조 주장 상한(10)을 넘는 서면. 문장마다 서로 다른 주장이다.
MANY_CLAIMS_BRIEF = "준 비 서 면\n" + "".join(
    f"{i}. 피고는 {i}월 {i + 1}일 현장 점검에서 {label} 확인 의무를 이행하지 아니하였다.\n"
    for i, label in enumerate(["난간", "안전망", "개구부 덮개", "작업발판", "안전대 부착설비", "추락방호망", "사다리 고정",
                               "비계 연결", "조명", "통로 표시", "낙하물 방지", "출입 통제", "보호구 지급", "작업계획서"],
                              start=1))


class _Drive:
    """ReferenceLibrary의 client_factory 대역. files: {file_id: (이름, 본문 또는 None=다운로드 실패, 추가 메타)}."""

    def __init__(self, files):
        self.files = files

    def __call__(self, **kwargs):
        return self

    def remaining(self):
        return 120

    def inventory(self, *args, **kwargs):
        return [self.metadata(file_id) for file_id in self.files]

    def metadata(self, file_id):
        name, text, extra = self.files[file_id]
        body = (text or "읽기 실패 대역").encode()
        return {"id": file_id, "name": name, "mimeType": "text/plain", "version": "1",
                "modifiedTime": "2026-09-26T01:00:00Z", "parents": [FOLDER], "size": str(len(body)),
                "capabilities": {"canDownload": True}, "md5Checksum": hashlib.md5(body).hexdigest(), **extra}

    def search_fulltext(self, folder_ids, terms, *, max_results=200):
        """Drive 본문 검색 대역: 모든 단어를 본문에 가진 파일(읽기 실패 대역 포함)의 ID."""
        words = [t for t in terms if t][:5]
        return {file_id for file_id, (_, text, _) in self.files.items()
                if words and all(w in (text or "읽기 실패 대역") for w in words)}

    def download(self, item, **kwargs):
        name, text, _ = self.files[item["id"]]
        if text is None:
            raise DriveReferenceError("DRIVE_HTTP_403")
        return text.encode(), name, "text/plain"

    def close(self):
        pass


def _extract(data, *args, **kwargs):
    return {"sha256": hashlib.sha256(data).hexdigest(), "chunks": [{"page": 1, "start": 0, "text": data.decode()}],
            "pages": 1, "read_pages": 1, "partial": False}


class _Ledger:
    def reserve(self, *args, **kwargs):
        return SimpleNamespace(id="r", amount=Decimal("0.01"))

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _run(monkeypatch, tmp_path, brief, files, *, profile=VerificationProfile.STANDARD,
         policy=ExternalAIPolicy.MASKED, absent_cases=()):
    """합성 서면 하나를 전체 파이프라인으로 돌린다. 반환: 문서 결과, 직렬화 문서, 공급자에 간 요청, 검사를 지난 요청 본문."""
    settings = replace(get_settings(), storage_root=tmp_path, rag_drive_folder_id=FOLDER, allow_network=True)
    monkeypatch.setattr(library_module, "ReferenceLibrary", lambda _settings, **kwargs: REAL_LIBRARY(
        settings, client_factory=_Drive(files), extractor=_extract, **kwargs))
    monkeypatch.setattr(router_module, "estimate_call", lambda *args: (Decimal("0.01"), {}))
    inspected = []

    def recording_inspect(request, *args, **kwargs):
        inspected.append(request.user)
        return REAL_INSPECT(request, *args, **kwargs)

    monkeypatch.setattr(privacy_module, "inspect_request", recording_inspect)
    sent = []

    class Provider:
        name, available = "anthropic", True
        config = SimpleNamespace(name="anthropic", kind="cloud", model="fake", enabled=True)

        async def generate(self, request):
            sent.append(request)
            required = (request.schema or {}).get("required") or []
            if "observations" in required:
                body = {"observations": []}
                return LLMResponse(True, text=json.dumps(body), parsed=body, provider="anthropic", model="fake")
            return LLMResponse(False, error="HTTP 400")

    pipeline = VerificationPipeline(router=router_module.LLMRouter(providers={"anthropic": Provider()},
                                                                    ledger=_Ledger()))
    pipeline.settings = replace(pipeline.settings, rag_drive_folder_id=FOLDER)
    real_search_case = pipeline.registry.law.search_case

    def search_case(case_number, *args, **kwargs):
        if any(case in str(case_number) for case in absent_cases):
            return AdapterResponse(AdapterStatus.READY, [], None, "조회 결과 없음(합성 대역)", [], True)
        return real_search_case(case_number, *args, **kwargs)

    pipeline.registry.law.search_case = search_case
    path = tmp_path / "brief.txt"
    path.write_text(brief, encoding="utf-8")
    context = ProjectContext(project_id="f3", profile=profile, external_ai_policy=policy)
    result = pipeline.run("f3_protected", context, [DocumentInput(
        document_id="d1", path=str(path), filename=path.name, mime_type="text/plain", sha256=sha256_file(path))])
    payload = json.loads(json.dumps(to_payload(result), default=str))
    return result.documents[0], payload["documents"][0], sent, inspected


def _case_row(doc, case):
    rows = [row for row in doc.get("review_items") or []
            if row["kind"] == "CITATION" and case in str(row.get("cited_authority") or "")]
    assert len(rows) == 1, f"사건번호 {case}의 인용 행이 하나가 아님: {len(rows)}"
    return rows[0]


def _findings(doc):
    return sorted((f["type"], f["severity"], f["status"]) for f in doc["findings"])


def _domain_run(monkeypatch, tmp_path, key, body_key="with_case", **kwargs):
    domain = DOMAINS[key]
    files = {f"ref{key}000000001": (domain["title"], domain[body_key], {})}
    return _run(monkeypatch, tmp_path, domain["brief"], files, absent_cases=(domain["case"],), **kwargs)


def _claim_requests(sent):
    """주장 단위 대조 요청(19b 6.1: 본문 최상위에 claim_id)과 그 본문의 쌍."""
    out = []
    for request in sent:
        try:
            body = json.loads(request.user)
        except (TypeError, ValueError):
            continue
        if isinstance(body, dict) and "claim_id" in body:
            out.append((request, body))
    return out


def _keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


# --------------------------------------------------------------------------- T6 ---
@pytest.mark.xfail(strict=True, reason="F3 미구현: reference_status는 아직 NOT_CHECKED뿐이다(PROMPT_FOR_F3 3절 1)")
def test_t6_official_absent_case_found_in_reference_body_is_supported_without_touching_official_status(
        monkeypatch, tmp_path):
    case = DOMAINS["safety"]["case"]
    _, doc, _, _ = _domain_run(monkeypatch, tmp_path, "safety")
    row = _case_row(doc, case)
    assert row["official_status"] == "OFFICIAL_NOT_FOUND"
    assert row["reference_status"] == "SUPPORTED"
    assert any("refsafety000000001" in str(source) for source in row["evidence_sources"]), row["evidence_sources"]


def test_t6_reference_never_changes_official_status_findings_or_severity(monkeypatch, tmp_path):
    """D4: 참고자료에 같은 인용이 있든 없든 공식 상태·finding·행 심각도는 같다(지금도 통과, F3 뒤에도 유지)."""
    case = DOMAINS["safety"]["case"]
    _, with_ref, _, _ = _domain_run(monkeypatch, tmp_path / "with", "safety")
    _, without_ref, _, _ = _domain_run(monkeypatch, tmp_path / "without", "safety", body_key="without_case")
    a, b = _case_row(with_ref, case), _case_row(without_ref, case)
    assert a["official_status"] == b["official_status"] == "OFFICIAL_NOT_FOUND"
    assert a["severity"] == b["severity"]
    assert _findings(with_ref) == _findings(without_ref)


def test_t6_title_only_or_unread_reference_does_not_support(monkeypatch, tmp_path):
    """제목에만 같은 사건번호가 있거나 읽지 못한 파일에만 있으면 SUPPORTED가 아니다(TK-29 U1 재사용)."""
    domain = DOMAINS["safety"]
    case = domain["case"]
    files = {
        "reftitleonly00001": (f"대법원 {case} 판결 정리.txt", domain["without_case"], {}),
        "refunread0000001": ("안전배려의무 판례 모음.txt", None, {}),
    }
    _, doc, _, _ = _run(monkeypatch, tmp_path, domain["brief"], files, absent_cases=(case,))
    row = _case_row(doc, case)
    assert row["official_status"] == "OFFICIAL_NOT_FOUND"
    assert row["reference_status"] != "SUPPORTED"


# --------------------------------------------------------------------------- T7 ---
def _eligible(document_result):
    return [c for c in document_result.claims if c.get("type") not in ("DOCUMENT_META", "ADVERSARIAL_INSTRUCTION")]


def test_t7_claim_coverage_denominator_is_the_eligible_claims(monkeypatch, tmp_path):
    """분모 = 대조 대상 주장 수, 대조 수 + 미대조 수 = 분모, 미대조마다 사유(지금도 통과, F3 뒤에도 유지)."""
    result, _, _, _ = _run(monkeypatch, tmp_path, MANY_CLAIMS_BRIEF,
                           {"refmany000000001": ("현장 안전점검 기준.txt",
                                                 "현장 점검에서는 난간, 안전망, 작업발판, 비계 연결 상태를 확인한다.", {})})
    eligible = _eligible(result)
    coverage = result.engine_data["rag"]["claim_coverage"]
    ids = [item["claim_id"] for item in coverage["unreviewed"]]
    assert coverage["eligible_claims"] == len(eligible)
    assert coverage["linked_claims"] + len(ids) == len(eligible)
    assert len(ids) == len(set(ids)) and set(ids) <= {c["claim_id"] for c in eligible}
    assert all(item.get("reason") for item in coverage["unreviewed"])


def test_t7_fixture_has_more_eligible_claims_than_the_document_limit(monkeypatch, tmp_path):
    """아래 상한 시험의 전제: 합성 서면의 대조 대상 주장이 문서당 상한(10)을 넘는다."""
    result, _, _, _ = _run(monkeypatch, tmp_path, MANY_CLAIMS_BRIEF,
                           {"refmany000000001": ("현장 안전점검 기준.txt",
                                                 "현장 점검에서는 난간, 안전망, 작업발판, 비계 연결 상태를 확인한다.", {})})
    assert len(_eligible(result)) > CLAIM_LIMIT_PER_DOCUMENT


@pytest.mark.xfail(strict=True, reason="F3 미구현: 문서당 주장 상한과 REASON_BUDGET_EXCEEDED 사유가 없다(19b 5.2)")
def test_t7_claims_over_the_document_limit_stay_in_the_denominator_with_budget_reason(monkeypatch, tmp_path):
    result, _, _, _ = _run(monkeypatch, tmp_path, MANY_CLAIMS_BRIEF,
                           {"refmany000000001": ("현장 안전점검 기준.txt",
                                                 "현장 점검에서는 난간, 안전망, 작업발판, 비계 연결 상태를 확인한다.", {})})
    eligible = _eligible(result)
    coverage = result.engine_data["rag"]["claim_coverage"]
    over = [item for item in coverage["unreviewed"] if item.get("reason") == "REASON_BUDGET_EXCEEDED"]
    assert coverage["eligible_claims"] == len(eligible)
    assert len(over) >= len(eligible) - CLAIM_LIMIT_PER_DOCUMENT > 0


COVERAGE_SHOWN = re.compile(r"7\s*건\s*중\s*3\s*건|3\s*/\s*7")


def _screen_text():
    """claim_coverage(분모 7·대조 3)를 실은 합성 결과를 화면에 그리고 본문 글을 돌려준다."""
    sync_api = pytest.importorskip("playwright.sync_api")
    from urllib.parse import urlsplit

    from frontend_helpers import privacy_notice_mock_payload, select_first_project

    project = {"id": "p1", "name": "대조율 표시 시험", "can_delete": True, "document_count": 1,
               "external_ai_policy": "MASKED", "scope_revision": 0, "requested_issues": []}
    run = {"id": "r1", "project_id": "p1", "state": "COMPLETED", "progress": 1, "stage_message": "",
           "document_ids": ["d1"], "scores": {}, "unverified_items": [], "errors": [], "unavailable_sources": [],
           "input_snapshot": {"scope_revision": 0}, "started_at": "2026-10-07T00:00:00"}
    unreviewed = [{"claim_id": f"CLM_{i}", "reason": "REASON_BUDGET_EXCEEDED"} for i in range(4)]
    rag = {"status": "ADVISORY_REVIEWED", "reason": "", "advisory_only": True, "drive_used": True, "sources": [],
           "observations": [], "rejected_observations": [], "model_executed": True, "model_response_accepted": True,
           "review_completed": True,
           "claim_coverage": {"eligible_claims": 7, "linked_claims": 3, "unreviewed": unreviewed,
                              "all_claims_verified": False}}
    library = {"status": "READY", "files_indexed": 1, "files_seen": 1, "checked_at": "2026-10-07T00:00:00",
               "inventory": [], "issues": [], "duplicates": [], "sources": []}
    result = {"status": "COMPLETED", "run_manifest": {"reference_library": library},
              "documents": [{"id": "d1", "document_id": "d1", "filename": "합성.pdf", "quarantined": False,
                             "findings": [], "review_items": [], "ai_hallucination_table": [],
                             "engine_data": {"rag": rag},
                             "ai_detector_result": {"verdict": "UNCERTAIN", "score": 0.5, "reasons": []}}]}
    static_dir = ROOT / "apps/web/static"
    files = {f"/static/{p.relative_to(static_dir).as_posix()}": p for p in static_dir.rglob("*") if p.is_file()}
    files["/"] = ROOT / "apps/web/index.html"

    def handler(route):
        path = urlsplit(route.request.url).path
        if path in files:
            return route.fulfill(path=str(files[path]))
        me = {"user_id": "u", "email": "t@example.com", "display_name": "검토자", "role": "ADMIN",
              "authentication": "local"}
        replies = {"/api/health": {"status": "ok"}, "/api/auth/me": me, "/api/identity/me": me,
                   "/api/verification-runs": {"active_count": 0, "runs": []},
                   "/api/projects": [project], "/api/projects/p1": project,
                   "/api/projects/p1/documents": [{"id": "d1", "filename": "합성.pdf",
                                                   "included_in_verification": True}],
                   "/api/projects/p1/runs": [run], "/api/projects/p1/findings": [],
                   "/api/projects/p1/audit": {"events": []}, "/api/privacy-notice": privacy_notice_mock_payload()}
        if path in replies:
            return route.fulfill(json=replies[path])
        if path.endswith(("/result", "/results")):
            return route.fulfill(json=result)
        if path.endswith("/case-matrix"):
            return route.fulfill(body="null", content_type="application/json")
        return route.fulfill(status=200, json=[])

    launch = {"headless": True}
    if os.environ.get("LV_TEST_BROWSER_CHANNEL"):
        launch["channel"] = os.environ["LV_TEST_BROWSER_CHANNEL"]
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(**launch)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.route("**/*", handler)
        page.goto("http://coverage.test/")
        select_first_project(page)
        page.wait_for_function("state.result && state.result.documents")
        text = ""
        for _ in range(60):
            text = page.evaluate("document.body.textContent")
            if COVERAGE_SHOWN.search(text):
                break
            page.wait_for_timeout(250)
        browser.close()
    return text


def test_t7_screen_harness_renders_the_reference_review_section():
    """아래 화면 시험의 전제: 합성 결과로 참고자료 검토 섹션이 실제로 그려진다(하네스 고장이 xfail에 묻히지 않게)."""
    text = _screen_text()
    assert "참고문헌 검토 결과" in text and "합성.pdf" in text


@pytest.mark.xfail(strict=True, reason="F3 미구현: 화면이 claim_coverage(N건 중 M건 대조)를 보이지 않는다(PROMPT_FOR_F3 3절 4)")
def test_t7_screen_shows_the_claim_coverage_values_from_data():
    assert COVERAGE_SHOWN.search(_screen_text()), "화면에 claim_coverage 값(7건 중 3건)이 보이지 않는다"


# --------------------------------------------------------------------------- T8 ---
def test_t8_both_domains_go_through_the_same_procedure(monkeypatch, tmp_path):
    """분야가 달라도 같은 절차·같은 결과 구조(지금도 통과, F3 뒤에도 유지)."""
    shapes = []
    for key in DOMAINS:
        result, doc, _, _ = _domain_run(monkeypatch, tmp_path / key, key)
        rag = result.engine_data["rag"]
        assert rag["drive_used"] is True, key
        assert _case_row(doc, DOMAINS[key]["case"])["official_status"] == "OFFICIAL_NOT_FOUND"
        shapes.append((rag["status"], sorted(rag), sorted(rag["claim_coverage"])))
    assert shapes[0] == shapes[1]


@pytest.mark.xfail(strict=True, reason="F3 미구현: 두 분야 모두 reference_status가 NOT_CHECKED다")
def test_t8_reference_support_works_in_both_domains(monkeypatch, tmp_path):
    for key in DOMAINS:
        _, doc, _, _ = _domain_run(monkeypatch, tmp_path / key, key)
        row = _case_row(doc, DOMAINS[key]["case"])
        assert (row["official_status"], row["reference_status"]) == ("OFFICIAL_NOT_FOUND", "SUPPORTED"), key


# --------------------------------------------------------------------------- T9 ---
def test_t9_local_only_makes_no_provider_call(monkeypatch, tmp_path):
    _, _, sent, _ = _domain_run(monkeypatch, tmp_path, "safety", policy=ExternalAIPolicy.LOCAL_ONLY)
    assert sent == []


def test_t9_quick_profile_sends_no_reference_excerpt(monkeypatch, tmp_path):
    sentinel = DOMAINS["safety"]["sentinel"]
    result, _, sent, _ = _domain_run(monkeypatch, tmp_path, "safety", profile=VerificationProfile.QUICK)
    assert result.engine_data["rag"]["drive_used"] is True
    assert not [r for r in sent if sentinel in f"{r.system}\n{r.user}"]


def _pii_reference_run(monkeypatch, tmp_path):
    domain = DOMAINS["safety"]
    text = (domain["with_case"] + f" 현장 연락처는 {PHONE}이고 담당자 주민등록번호는 {RRN}이다.")
    owners = {"owners": [{"displayName": OWNER_NAME, "emailAddress": OWNER_EMAIL}],
              "lastModifyingUser": {"displayName": OWNER_NAME, "emailAddress": OWNER_EMAIL}}
    return _run(monkeypatch, tmp_path, domain["brief"], {"refpii0000000001": (domain["title"], text, owners)},
                absent_cases=(domain["case"],))


def test_t9_reference_excerpt_is_masked_and_inspected_before_sending(monkeypatch, tmp_path):
    """참고자료 발췌의 연락처·주민등록번호·Drive 소유자 정보가 공급자에 도달하지 않고, 간 요청은 모두 검사를 지났다."""
    result, _, sent, inspected = _pii_reference_run(monkeypatch, tmp_path)
    assert result.engine_data["rag"]["drive_used"] is True
    sentinel = DOMAINS["safety"]["sentinel"]
    assert [r for r in sent if sentinel in r.user], "참고자료 발췌를 실은 요청이 없어 시험이 성립하지 않는다"
    bodies = [f"{r.system}\n{r.user}\n{json.dumps(r.schema, ensure_ascii=False, default=str)}" for r in sent]
    for value in (PHONE, RRN, RRN.replace("-", ""), OWNER_NAME, OWNER_EMAIL):
        assert not [b for b in bodies if value in b], f"공급자에 도달: {value[:3]}…"
    assert all(r.user in inspected for r in sent), "inspect_request를 지나지 않은 요청이 공급자에 갔다"


@pytest.mark.xfail(strict=True, reason="F3 미구현: 주장 단위 대조 요청이 없다(PROMPT_FOR_F3 3절 3·5)")
def test_t9_claim_level_requests_are_inspected_masked_and_bounded(monkeypatch, tmp_path):
    _, _, sent, inspected = _pii_reference_run(monkeypatch, tmp_path)
    pairs = _claim_requests(sent)
    assert pairs, "주장 단위 대조 요청이 공급자 경로(LLMRouter.run)에 없다"
    assert all(request.user in inspected for request, _ in pairs)
    for value in (PHONE, RRN, RRN.replace("-", ""), OWNER_NAME, OWNER_EMAIL):
        assert not [r for r, _ in pairs if value in f"{r.system}\n{r.user}"]
    per_claim = {}
    for _, body in pairs:
        per_claim[body["claim_id"]] = per_claim.get(body["claim_id"], 0) + 1
        excerpt = json.dumps(body.get("reference_sources", []), ensure_ascii=False)
        assert len(excerpt) <= EXCERPT_CHARS + 500, len(excerpt)  # 키·따옴표 여유 500자
    assert len(per_claim) <= CLAIM_LIMIT_PER_DOCUMENT
    assert max(per_claim.values()) <= MODEL_CALLS_PER_CLAIM


# --------------------------------------------------------------------- 요청 본문 스키마 ---
@pytest.mark.xfail(strict=True, reason="F3 미구현: 주장 단위 요청 본문이 없다(19b 6.1)")
def test_schema_claim_level_request_keys_are_allowlisted_and_name_no_person(monkeypatch, tmp_path):
    _, _, sent, _ = _pii_reference_run(monkeypatch, tmp_path)
    pairs = _claim_requests(sent)
    assert pairs, "주장 단위 대조 요청이 없다"
    for _, body in pairs:
        assert set(body) <= ALLOWED_REQUEST_KEYS, sorted(set(body) - ALLOWED_REQUEST_KEYS)
        person = [key for key in _keys(body) if PERSON_KEY.search(str(key))]
        assert not person, person


# 설계 개정 1(PR #32 60e8266) 5.2: `packages/rag_engine/review.py` `validate_structured_claim_request(body) -> bool`.
# 계약(평가 측 조건부 승인 조건 2): 예외를 내지 않고 bool만 돌려준다. 최상위 허용 키 4개, 항목 키 {source_id, text, page},
# claim_text ≤ 1,000자, reference_sources ≤ 5개, 항목 text ≤ 800자. 하나라도 어기면 False(fail-closed).
_VALID_ITEM = {"source_id": "R1", "text": "현장 점검 기준 발췌", "page": 1}
_VALID_BODY = {"system_instructions": "두 인용을 대조한다", "claim_id": "CLM_1", "claim_text": "합성 주장 문장",
               "reference_sources": [_VALID_ITEM]}
_INVALID_BODIES = {
    "extra-top-key": {**_VALID_BODY, "note": "허용 목록 밖"},
    "person-top-key": {**_VALID_BODY, "party_name": "합성"},
    "item-title": {**_VALID_BODY, "reference_sources": [{**_VALID_ITEM, "title": "합성 파일명"}]},
    "item-owner": {**_VALID_BODY, "reference_sources": [{**_VALID_ITEM, "owner": "합성"}]},
    "claim-text-too-long": {**_VALID_BODY, "claim_text": "가" * 1001},
    "too-many-sources": {**_VALID_BODY, "reference_sources": [dict(_VALID_ITEM, source_id=f"R{i}") for i in range(6)]},
    "item-text-too-long": {**_VALID_BODY, "reference_sources": [{**_VALID_ITEM, "text": "가" * 801}]},
    "sources-not-list": {**_VALID_BODY, "reference_sources": "R1"},
    "body-not-dict": [_VALID_BODY],
}


def _validator():
    from packages.rag_engine import review

    validate = getattr(review, "validate_structured_claim_request", None)
    assert callable(validate), "validate_structured_claim_request가 없다(설계 개정 1 5.2)"
    return validate


@pytest.mark.xfail(strict=True, reason="F3 미구현: validate_structured_claim_request가 없다(설계 개정 1 5.2)")
def test_schema_validator_accepts_an_allowlisted_body():
    assert _validator()(json.loads(json.dumps(_VALID_BODY))) is True


@pytest.mark.xfail(strict=True, reason="F3 미구현: validate_structured_claim_request가 없다(설계 개정 1 5.2)")
@pytest.mark.parametrize("case", sorted(_INVALID_BODIES))
def test_schema_validator_fails_closed_without_raising(case):
    assert _validator()(json.loads(json.dumps(_INVALID_BODIES[case], ensure_ascii=False))) is False, case
