"""Drive 참고자료 관련도 선정, 중복 사본 목록, 연결 진단 로그.

참고자료와 질의 문장은 모두 시험용으로 새로 지은 일반 서술이다(사건번호·특정 판결·당사자를 쓰지 않는다).
폴더 이름만 실제 Drive 폴더의 구성 방식(주제별 폴더)을 본떴다.
"""
import copy
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest

from packages.common.config import get_settings
from packages.rag_engine import relevance
from packages.rag_engine.drive import DriveClient, FOLDER, ReferenceError
from packages.rag_engine.library import ReferenceLibrary

ROOT = "folder00000001"

REFS = {
    ("분야별 업무편람", "징계업무편람.pdf"):
        "징계권자는 징계사유가 있는 공무원에 대하여 징계위원회에 징계의결을 요구한다. 징계의 종류는 파면, 해임, 강등, 정직, "
        "감봉, 견책이다. 징계양정은 비위의 유형과 정도, 고의 또는 과실, 평소 근무성적과 공적을 고려한다. 징계위원회는 혐의자에게 "
        "출석을 통지하고 진술의 기회를 주어야 하며, 진술 기회를 주지 아니한 징계의결은 절차상 하자가 있다. 징계처분이 현저히 "
        "타당성을 잃으면 재량권 일탈·남용으로 위법하다.",
    ("분야별 업무편람", "공직자의 이해충돌 방지법 업무편람.pdf"):
        "공직자는 직무관련자가 사적이해관계자임을 안 경우 소속기관장에게 서면으로 신고하고 회피를 신청하여야 한다. 사적이해관계자에는 "
        "가족이나 공직자가 임원으로 있는 법인이 포함된다. 소속기관장은 직무 재배정, 직무 대리자 지정 등의 조치를 한다. 직무상 "
        "미공개정보를 이용하여 재산상 이익을 취득하여서는 아니 된다.",
    ("판례", "공직자 명예훼손.pdf"):
        "공직자의 업무에 관한 언론 보도가 명예훼손인지는 공익성과 진실성, 또는 진실이라고 믿을 상당한 이유가 있는지로 판단한다. "
        "공직자의 청렴성에 대한 의혹 제기는 언론의 감시와 비판 기능에 비추어 폭넓게 허용되고, 악의적인 공격이 아니면 위법성이 "
        "조각된다. 의견 표명은 원칙적으로 명예훼손이 되지 않는다.",
    ("수사", "디지털증거 압수수색 절차와 증거능력.pdf"):
        "정보저장매체 압수는 혐의사실과 관련된 정보만 출력하거나 복제하는 방식이 원칙이다. 이미지 파일을 복제해 사무실에서 탐색할 "
        "때에도 피압수자에게 참여 기회를 보장하여야 한다. 무관한 전자정보를 발견하면 탐색을 중단하고 별도 영장을 받아야 한다. "
        "참여권을 보장하지 않거나 압수목록을 교부하지 않은 압수로 얻은 전자정보는 증거능력이 부정될 수 있다.",
    ("윤리규범 및 저작권", "생성형 AI 저작권 안내서.pdf"):
        "생성형 인공지능 결과물은 인간의 창작적 기여가 없으면 저작물로 보호받기 어렵다. 결과물이 기존 저작물과 실질적으로 유사하고 "
        "의거관계가 인정되면 저작권 침해가 될 수 있다. 학습 데이터 이용은 공정이용 해당 여부가 쟁점이 된다.",
    ("법률서류양식", "고소장 작성례(횡령).hwp"):
        "고소인은 피고소인을 횡령 혐의로 고소합니다. 피고소인은 고소인의 물품 대금을 보관하던 중 임의로 소비하였습니다. 범죄사실에는 "
        "일시, 장소, 행위, 피해 금액을 적습니다. 횡령죄는 타인의 재물을 보관하는 자가 재물을 횡령하거나 반환을 거부한 때 성립합니다.",
    ("프롬프트작성 등 활용가이드", "인공지능 활용 가이드.pdf"):
        "업무에 인공지능을 활용할 때는 역할과 목적을 명확히 주고 형식과 분량을 지정한다. 결과물은 사람이 사실 여부를 확인한다. "
        "보안 자료나 개인정보는 외부 인공지능 서비스에 입력하지 않는다.",
}


def item(file_id, folder, name, text, **extra):
    return {"id": file_id, "name": name, "mimeType": "text/plain", "version": "1",
            "createdTime": extra.pop("created", "2026-06-01T00:00:00Z"), "modifiedTime": "2026-09-26T01:00:00Z",
            "parents": [ROOT], "size": str(len(text.encode())), "capabilities": {"canDownload": True},
            "md5Checksum": hashlib.md5(text.encode()).hexdigest(), "folder_path": folder, **extra}


class Drive:
    def __init__(self, refs=REFS):
        self.items, self.contents = {}, {}
        for index, ((folder, name), text) in enumerate(refs.items()):
            self.add(f"reference{index:06d}", folder, name, text)
        self.metadata_calls = self.downloads = 0

    def add(self, file_id, folder, name, text, **extra):
        self.items[file_id] = item(file_id, folder, name, text, **extra)
        self.contents[file_id] = text

    def __call__(self, **kwargs):
        return self

    def remaining(self):
        return 120

    def inventory(self, *args, **kwargs):
        return copy.deepcopy(list(self.items.values()))

    def metadata(self, file_id):
        self.metadata_calls += 1
        fresh = copy.deepcopy(self.items[file_id])
        fresh.pop("folder_path")
        return fresh

    def download(self, entry, **kwargs):
        self.downloads += 1
        return self.contents[entry["id"]].encode(), "reference.txt", "text/plain"

    def close(self):
        pass


def extract(data, *args, **kwargs):
    text = data.decode()
    return {"sha256": hashlib.sha256(data).hexdigest(), "pages": 1, "read_pages": 1, "partial": False,
            "chunks": [{"page": 1, "start": start, "text": text[start:start + 1200]} for start in range(0, len(text), 1040)]}


def library(tmp_path, drive):
    settings = replace(get_settings(), storage_root=tmp_path, rag_drive_folder_id=ROOT, allow_network=True)
    lib = ReferenceLibrary(settings, client_factory=drive, extractor=extract)
    lib.sync()
    return lib


# --- 관련 자료 선정 -------------------------------------------------------------------------------------
@pytest.mark.parametrize("expected, text", [
    ("징계업무편람", "청구인은 공무원으로서 감봉 징계처분을 받았다. 징계의결 과정에서 진술 기회를 얻지 못하였고 표창 공적 등 "
                  "감경 사유도 고려되지 않아 징계양정의 재량을 벗어났다."),
    ("디지털증거", "경찰은 노트북 저장매체 전체를 이미지로 복제해 반출한 뒤 피의자 참여 없이 전자정보를 탐색하였고 영장에 없는 "
               "별건 파일까지 출력하였다. 압수목록도 교부하지 않았다."),
    ("공직자 명예훼손", "피고 신문사는 군수의 업무추진비 사용 의혹을 보도하였다. 보도는 공직자의 청렴성에 관한 공익적 비판이고, "
                   "피고는 자료를 확인해 진실이라고 믿을 상당한 이유가 있었으므로 위법성이 조각된다."),
    ("이해충돌", "과장은 형제가 대표인 법인의 인허가 신청을 직접 처리하면서 사적이해관계자 신고와 회피 신청을 하지 않았고, "
             "기관은 직무 재배정 조치도 하지 않았다."),
])
def test_relevant_reference_is_selected_by_text_and_name(tmp_path, expected, text):
    log = library(tmp_path, Drive()).select(text)
    assert log["decision"] == "USED" and log["reason"] == "RELEVANT_REFERENCE_FOUND"
    assert {s["title"] for s in log["sources"]} and all(expected in s["title"] for s in log["sources"])
    chosen = [c for c in log["candidates"] if c["selected"]]
    assert chosen and all(expected in c["title"] for c in chosen)
    assert log["thresholds"]["min_file_score"] == relevance.MIN_FILE_SCORE


@pytest.mark.parametrize("text", [
    "원고는 창고 신축 공사를 완료하였으나 피고는 지붕 누수 하자를 이유로 기성고 잔금 지급을 거절한다.",
    "원고와 피고는 혼인관계가 파탄되었고 원고는 이혼과 위자료, 재산분할, 양육자 지정을 청구한다.",
    "피고 차량이 중앙선을 침범해 원고 차량과 충돌하였고 원고는 후유장해에 따른 일실수입과 치료비를 청구한다.",
    "임차인은 계약 만료 후 집을 비웠으나 임대인은 새 임차인을 구할 때까지 임대차보증금을 돌려주지 않는다.",
])
def test_unrelated_document_does_not_use_drive(tmp_path, text):
    log = library(tmp_path, Drive()).select(text)
    assert log["decision"] == "NOT_USED" and not log["sources"]
    assert log["reason"] in ("BELOW_RELEVANCE_THRESHOLD", "NO_CANDIDATE_CHUNK", "NO_SHARED_KEY_TERMS")
    assert all(c["rejected_because"] for c in log["candidates"])


@pytest.mark.parametrize("folder, name, body", [
    ("징계 자료", "징계 절차 해설.txt", "징계위원회는 혐의자에게 출석을 통지하고 진술 기회를 준다. 징계양정은 비위 정도를 고려한다."),
    ("징계", "공무원 징계 요약.txt", "징계위원회는 혐의자에게 출석을 통지하고 진술 기회를 준다. 징계양정은 비위 정도를 고려한다."),
    ("업무 참고", "징계양정 기준.txt", "징계위원회는 혐의자에게 출석을 통지하고 진술 기회를 준다. 징계양정은 비위 정도를 고려한다."),
])
def test_folder_and_file_names_rank_equal_text(tmp_path, folder, name, body):
    drive = Drive({("기타", "참고 메모.txt"): body + " 이 메모는 일반 참고용이다."})
    drive.add("reference900001", folder, name, body + " 이 자료는 부서 참고용이다.")
    log = library(tmp_path, drive).select("징계위원회가 출석 통지 없이 징계의결을 하여 진술 기회를 박탈하였고 징계양정도 과중하다.")
    ranked = {c["title"]: c for c in log["candidates"]}
    assert log["candidates"][0]["title"] == name and ranked[name]["selected"]
    assert ranked[name]["name_coverage"] > ranked["참고 메모.txt"]["name_coverage"]
    assert ranked[name]["file_score"] > ranked["참고 메모.txt"]["file_score"]


@pytest.mark.parametrize("folder, name", [
    ("징계", "징계양정 기준.txt"), ("공무원 징계", "징계 처분 해설.txt"), ("징계 사례", "공무원 징계 모음.txt"),
])
def test_name_match_alone_never_selects_a_file(tmp_path, folder, name):
    drive = Drive({(folder, name): "회의실 예약은 전날까지 신청한다. 비품은 사용 후 제자리에 둔다. 주차 공간은 방문객에게 우선 배정한다."})
    log = library(tmp_path, drive).select("원고는 징계처분을 받았으나 징계위원회가 진술 기회를 주지 않았으므로 징계는 위법하다.")
    assert log["decision"] == "NOT_USED"


def test_review_records_not_relevant_without_model_call(tmp_path):
    from packages.common.enums import ExternalAIPolicy
    from packages.common.schemas import Block, NormalizedDocument, Page
    from packages.rag_engine.review import review_document
    from packages.verification_engine.pipeline import DocumentResult, ProjectContext
    lib = library(tmp_path, Drive())
    text = "원고는 창고 신축 공사를 완료하였으나 피고는 지붕 누수 하자를 이유로 기성고 잔금 지급을 거절한다."
    doc = NormalizedDocument("doc", "document.txt", "text/plain", "hash", pages=[Page(1, blocks=[Block("b", text, 1)])])
    result = DocumentResult("doc", "document.txt", normalized=doc)
    calls = []
    router = SimpleNamespace(has_available_provider=lambda **kw: calls.append("check") or True)
    review = review_document(result, lib, router, ProjectContext("p", external_ai_policy=ExternalAIPolicy.MASKED),
                             SimpleNamespace(mask_text=lambda value: SimpleNamespace(masked_text=value)))
    assert review["status"] == "NOT_RELEVANT" and review["drive_used"] is False and not review["sources"]
    assert review["reason"].startswith("NO_RELEVANT_DRIVE_REFERENCE")
    assert review["selection"]["decision"] == "NOT_USED" and not calls


# --- 중복 사본 ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("copy_name", ["행정법 표준판례.pdf의 사본", "행정법 표준판례 (1).pdf", "Copy of 행정법 표준판례.pdf"])
def test_identical_copies_are_listed_and_not_downloaded_twice(tmp_path, copy_name):
    body = "처분의 근거와 이유를 제시하지 아니한 처분은 절차상 위법하다. 재량권 일탈과 남용을 심사한다."
    drive = Drive({("판례", "행정법 표준판례.pdf"): body})
    drive.add("reference900001", "판례", copy_name, body, created="2026-07-01T00:00:00Z")
    lib = library(tmp_path, drive)
    [group] = lib.summary["duplicates"]
    assert group["keep"]["name"] == "행정법 표준판례.pdf"
    assert [c["name"] for c in group["delete_candidates"]] == [copy_name]
    assert group["reclaimable_bytes"] == len(body.encode())
    assert drive.downloads == 1 and lib.summary["files_indexed"] == 1
    assert lib.summary["diagnostics"]["duplicates_skipped"] == 1 and lib.summary["status"] == "READY"


@pytest.mark.parametrize("first, second", [
    ("민법 표준판례.pdf", "민법 표준판례.pdf의 사본"), ("업무편람.pdf", "업무편람 (2).pdf"), ("가이드북.pdf", "Copy of 가이드북.pdf"),
])
def test_same_name_with_different_content_is_listed_for_review_not_skipped(tmp_path, first, second):
    drive = Drive({("판례", first): "첫 번째 판본의 본문이다. 계약 해석과 손해배상의 범위를 설명한다."})
    drive.add("reference900001", "판례", second, "두 번째 판본의 본문이다. 소멸시효와 부당이득반환을 설명한다.")
    lib = library(tmp_path, drive)
    assert not lib.summary["duplicates"]
    assert len(lib.summary["similar_names"]) == 1 and len(lib.summary["similar_names"][0]["files"]) == 2
    assert drive.downloads == 2


def test_duplicate_report_does_not_skip_copy_when_original_is_unusable(tmp_path):
    body = "헌법재판소 결정의 기속력과 한정위헌 결정의 효력을 설명한다. 심판대상 조항과 청구기간을 다룬다."
    drive = Drive({("판례", "헌법 결정 해설.pdf"): body})
    drive.add("reference900001", "판례", "헌법 결정 해설.pdf의 사본", body)
    drive.items["reference000000"]["capabilities"]["canDownload"] = False
    lib = library(tmp_path, drive)
    assert "reference900001" in lib.eligible and drive.downloads == 1


# --- 캐시 재사용과 요청 수 -------------------------------------------------------------------------------
def test_unchanged_cached_files_need_no_per_file_request(tmp_path):
    drive = Drive()
    lib = library(tmp_path, drive)
    first = drive.metadata_calls
    assert first == 2 * len(REFS)  # before and after each download
    lib.sync()
    assert drive.metadata_calls == first and lib.summary["files_reused"] == len(REFS)
    drive.items["reference000001"]["capabilities"]["canDownload"] = False
    lib.sync()
    assert "reference000001" not in lib.eligible and lib.summary["status"] == "PARTIAL"


# --- 연결 진단 로그 -------------------------------------------------------------------------------------
def test_http_log_records_operations_and_status_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("LV_DRIVE_API_KEY", "secret-key-value-123")
    monkeypatch.delenv("LV_DRIVE_SERVICE_ACCOUNT_FILE", raising=False)
    body = "징계위원회는 혐의자에게 진술 기회를 주어야 하며 징계양정은 비위 정도를 고려한다."
    file_meta = {**item("reference000001", "", "징계.txt", body), "parents": [ROOT]}
    file_meta.pop("folder_path")
    sub = {"id": "folder00000002", "name": "업무편람", "mimeType": FOLDER, "parents": [ROOT]}

    def handler(request):
        path, params = request.url.path, request.url.params
        if path.endswith("/files") and ROOT in params.get("q", ""):
            return httpx.Response(200, json={"files": [sub]})
        if path.endswith("/files"):
            return httpx.Response(200, json={"files": [{**file_meta, "parents": ["folder00000002"]}]})
        if path.endswith("/" + ROOT):
            return httpx.Response(200, json={"id": ROOT, "mimeType": FOLDER})
        if params.get("alt") == "media":
            return httpx.Response(200, content=body.encode())
        return httpx.Response(200, json={**file_meta, "parents": ["folder00000002"]})

    def factory(**kwargs):
        return DriveClient(transport=httpx.MockTransport(handler), **kwargs)

    settings = replace(get_settings(), storage_root=tmp_path, rag_drive_folder_id=ROOT, allow_network=True)
    lib = ReferenceLibrary(settings, client_factory=factory, extractor=extract)
    summary = lib.sync()
    diagnostics = summary["diagnostics"]
    assert summary["status"] == "READY" and diagnostics["credential_mode"] == "api_key"
    assert diagnostics["folder_paths"] == ["업무편람"] and lib.eligible["reference000001"]["folder_path"] == "업무편람"
    operations = [c["operation"] for c in diagnostics["http"]["calls"]]
    assert operations[:3] == ["metadata", "list", "list"] and "download" in operations
    assert diagnostics["http"]["totals"]["by_status"] == {"200": len(operations)}
    assert [s["stage"] for s in diagnostics["stages"]] == ["inventory", "files"]
    assert "secret-key-value-123" not in json.dumps(summary, ensure_ascii=False)


@pytest.mark.parametrize("status, reason", [(403, "DRIVE_HTTP_403"), (404, "DRIVE_HTTP_404"), (500, "DRIVE_HTTP_500")])
def test_failed_connection_is_logged_with_status(tmp_path, monkeypatch, status, reason):
    monkeypatch.setenv("LV_DRIVE_API_KEY", "k")

    def factory(**kwargs):
        return DriveClient(transport=httpx.MockTransport(lambda request: httpx.Response(status)), **kwargs)

    settings = replace(get_settings(), storage_root=tmp_path, rag_drive_folder_id=ROOT, allow_network=True)
    summary = ReferenceLibrary(settings, client_factory=factory, extractor=extract).sync()
    assert summary["status"] == "UNAVAILABLE" and summary["issues"][-1]["reason"] == reason
    diagnostics = summary["diagnostics"]
    assert diagnostics["http"]["calls"][0] == {**diagnostics["http"]["calls"][0], "operation": "metadata",
                                               "status": status, "error": reason}
    assert diagnostics["issue_counts"] == {reason: 1} and diagnostics["outcome"] == "UNAVAILABLE"


def test_missing_credentials_are_visible_in_diagnostics(tmp_path, monkeypatch):
    monkeypatch.delenv("LV_DRIVE_API_KEY", raising=False)
    monkeypatch.delenv("LV_DRIVE_SERVICE_ACCOUNT_FILE", raising=False)
    settings = replace(get_settings(), storage_root=tmp_path, rag_drive_folder_id=ROOT, allow_network=True)
    summary = ReferenceLibrary(settings, extractor=extract).sync()
    assert summary["diagnostics"]["credential_mode"] == "none"
    assert summary["issues"][-1]["reason"] == "DRIVE_CREDENTIALS_MISSING"


def test_pipeline_manifest_carries_drive_health(tmp_path, registry):
    from helpers import make_docx
    from packages.common.enums import VerificationProfile
    from packages.common.storage import sha256_file
    from packages.verification_engine.pipeline import DocumentInput, ProjectContext, VerificationPipeline
    path = make_docx(tmp_path / "document.docx", ["공사대금 잔금 청구에 관한 준비서면이다."])
    pipeline = VerificationPipeline(registry=registry)
    pipeline.settings = replace(get_settings(), rag_drive_folder_id=ROOT, allow_network=False)
    result = pipeline.run("rag-health", ProjectContext("rag-project", profile=VerificationProfile.QUICK),
                          [DocumentInput("doc", str(path), path.name, sha256=sha256_file(path))])
    health = result.run_manifest["reference_library"]["health"]
    assert health["library_status"] == "UNAVAILABLE" and health["listing_succeeded"] is False
    assert health["documents"][0]["drive_used"] is False
    assert health["documents"][0]["reason"] == "REFERENCE_LIBRARY_UNAVAILABLE"


@pytest.mark.parametrize("name, base", [
    ("행정법 표준판례.pdf의 사본", "행정법 표준판례"), ("230425 민법 표준판례 2023년 (1).pdf의 사본", "230425 민법 표준판례 2023년"),
    ("Copy of guide.pdf", "guide"), ("보고서 - 복사본.hwp", "보고서"),
])
def test_copy_markers_are_removed_from_names(name, base):
    assert relevance.base_name(name) == base


def test_reference_error_codes_stay_stable():
    assert str(ReferenceError("DRIVE_HTTP_403")) == "DRIVE_HTTP_403"


@pytest.mark.parametrize("name", ["서식.hwp의 사본", "메모 (1).txt", "Copy of 표.csv"])
def test_copy_named_files_keep_their_format(tmp_path, name):
    from packages.rag_engine.library import SUPPORTED, isolated_extract
    assert relevance.extension(name) in SUPPORTED
    if name.endswith(".txt"):
        parsed = isolated_extract("징계 절차를 설명하는 참고 메모이다.".encode(), name, "application/octet-stream",
                                  directory=tmp_path, timeout=30)
        assert parsed["chunks"]


def test_check_script_prints_delete_candidates(tmp_path):
    from scripts.check_drive_references import duplicate_lines
    body = "소멸시효는 권리를 행사할 수 있는 때부터 진행한다."
    drive = Drive({("판례", "민법 표준판례.pdf"): body})
    drive.add("reference900001", "판례", "민법 표준판례.pdf의 사본", body)
    drive.add("reference900002", "", "민법 표준판례 (1).pdf", body)
    lines = duplicate_lines(library(tmp_path, drive).summary)
    assert lines[0] == "[보존] 판례/민법 표준판례.pdf"
    assert sum(line.strip().startswith("[삭제 후보]") for line in lines) == 2
    assert "[삭제 후보] 민법 표준판례 (1).pdf" in "\n".join(lines)
    assert lines[-1].startswith("중복 묶음 1개")


def test_web_shows_drive_health_selection_and_duplicates():
    import os
    from pathlib import Path
    from urllib.parse import urlsplit
    from playwright.sync_api import expect, sync_playwright

    root = Path(__file__).resolve().parents[1]
    static = root / "apps/web/static"
    files = {f"/static/{p.relative_to(static).as_posix()}": p for p in static.rglob("*") if p.is_file()}
    files["/"] = root / "apps/web/index.html"
    run = {"id": "r1", "project_id": "p1", "state": "COMPLETED", "progress": 1, "stage_message": "",
           "document_ids": ["d"], "scores": {}, "unverified_items": [], "input_snapshot": {"scope_revision": 0},
           "started_at": "2026-09-26T00:00:00"}
    project = {"id": "p1", "name": "합성 사건", "can_delete": True, "document_count": 1,
               "external_ai_policy": "MASKED", "scope_revision": 0}
    copy_entry = {"file_id": "reference900001", "name": "행정법 표준판례.pdf의 사본", "folder_path": "판례", "size": 2048}
    library = {"status": "READY", "files_indexed": 2, "files_seen": 3, "checked_at": "2026-09-26T00:00:00Z", "issues": [],
               "health": {"credential_mode": "api_key", "listing_succeeded": True, "http_calls": 9, "http_errors": 0,
                          "sync_ms": 2300},
               "duplicates": [{"keep": {"file_id": "reference000001", "name": "행정법 표준판례.pdf", "folder_path": "판례"},
                               "delete_candidates": [copy_entry], "reclaimable_bytes": 2048}]}
    rag = {"status": "NOT_RELEVANT", "reason": "NO_RELEVANT_DRIVE_REFERENCE:BELOW_RELEVANCE_THRESHOLD", "sources": [],
           "selection": {"decision": "NOT_USED", "reason": "BELOW_RELEVANCE_THRESHOLD", "candidates_total": 2,
                         "files_selected": 0, "candidates": [
                             {"title": "징계업무편람.pdf", "folder_path": "업무편람", "selected": False,
                              "text_coverage": 0.05, "name_coverage": 0.0, "file_score": 0.05}]}}
    result = {"run_manifest": {"reference_library": library},
              "documents": [{"filename": "a.pdf", "quarantined": False, "findings": [], "ai_hallucination_table": [],
                             "engine_data": {"rag": rag, "adversarial": {"scanned_layers": ["visible_text"],
                                                                         "adversarial_risk": "NONE"}}}]}

    def respond(route):
        path = urlsplit(route.request.url).path
        if path in files:
            return route.fulfill(path=str(files[path]))
        replies = {"/api/health": {"status": "ok", "version": "0.9.4"},
                   "/api/identity/me": {"user_id": "u", "role": "ADMIN", "authentication": "password"},
                   "/api/verification-runs": {"active_count": 0, "runs": []},
                   "/api/projects": [project], "/api/projects/p1": project, "/api/projects/p1/runs": [run]}
        if path in replies:
            return route.fulfill(json=replies[path])
        if path.endswith("/result"):
            return route.fulfill(json=result)
        if path.endswith("/case-matrix"):
            return route.fulfill(body="null", content_type="application/json")
        return route.fulfill(json=[])

    with sync_playwright() as playwright:
        options = {"headless": True}
        if os.getenv("LV_TEST_BROWSER_CHANNEL"):
            options["channel"] = os.environ["LV_TEST_BROWSER_CHANNEL"]
        browser = playwright.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 1400})
            page.route("**/*", respond)
            page.goto("http://drive.test/")
            page.wait_for_function("state.result && state.result.documents && state.result.documents.length === 1")
            page.evaluate("switchTab('ai-verification')")
            section = page.locator(".reference-section")
            expect(section).to_contain_text("인증 api_key · 목록 조회 성공 · API 호출 9건(오류 0건)")
            expect(section).to_contain_text("중복 사본 1묶음")
            link = section.locator("a", has_text="삭제 후보: 판례/행정법 표준판례.pdf의 사본")
            expect(link).to_have_attribute("href", "https://drive.google.com/file/d/reference900001/view")
            expect(section).to_contain_text("a.pdf: 관련 자료 없음 · Drive 자료 미활용")
            expect(section).to_contain_text("제외 · 업무편람/징계업무편람.pdf · 본문 0.05")
            page.close()
        finally:
            browser.close()


def test_unreadable_library_is_unverified_not_irrelevant(tmp_path):
    from packages.common.enums import ExternalAIPolicy
    from packages.common.schemas import Block, NormalizedDocument, Page
    from packages.rag_engine.review import review_document
    from packages.verification_engine.pipeline import DocumentResult, ProjectContext
    drive = Drive({("판례", "징계.txt"): "징계위원회는 진술 기회를 주어야 한다."})
    settings = replace(get_settings(), storage_root=tmp_path, rag_drive_folder_id=ROOT, allow_network=True)
    lib = ReferenceLibrary(settings, client_factory=drive,
                           extractor=lambda *a, **k: {"sha256": "0", "chunks": [], "partial": True, "reason": "REFERENCE_EMPTY"})
    assert lib.sync()["status"] == "PARTIAL" and not lib.eligible
    doc = NormalizedDocument("doc", "d.txt", "text/plain", "h", pages=[Page(1, blocks=[Block("b", "징계 진술 기회", 1)])])
    review = review_document(DocumentResult("doc", "d.txt", normalized=doc), lib, SimpleNamespace(),
                             ProjectContext("p", external_ai_policy=ExternalAIPolicy.MASKED),
                             SimpleNamespace(mask_text=lambda v: SimpleNamespace(masked_text=v)))
    assert review["status"] == "UNVERIFIED" and review["reason"] == "NO_READABLE_DRIVE_REFERENCE"
