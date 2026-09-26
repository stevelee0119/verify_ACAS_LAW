"""열기 전 선정(폴더·파일명·Drive 본문 검색)과 Drive AI 대조의 공급자 재시도.

파일명·폴더명·본문은 시험용으로 새로 지었다.
"""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from packages.common.config import get_settings
from packages.rag_engine import relevance
from packages.rag_engine.drive import ReferenceError
from packages.rag_engine.library import ReferenceLibrary
from test_drive_rag_relevance import ROOT, Drive, extract


def library(tmp_path, drive, **overrides):
    settings = replace(get_settings(), storage_root=tmp_path, rag_drive_folder_id=ROOT, allow_network=True, **overrides)
    return ReferenceLibrary(settings, client_factory=drive, extractor=extract)


def corpus():
    return {
        ("판례", "민법 도급계약 표준판례.pdf"): "도급계약에서 수급인은 일을 완성하고 도급인은 보수를 지급한다. 하자담보책임을 진다.",
        ("판례", "형사소송법 표준판례.pdf"): "위법하게 수집한 증거는 증거능력이 없다. 영장주의의 예외는 엄격히 해석한다.",
        ("분야별 업무편람", "공무원 징계업무편람.pdf"): "징계위원회는 혐의자에게 진술 기회를 주어야 한다. 징계양정 기준을 따른다.",
        ("국제법", "autonomous weapons review.pdf"): "Weapons review under international humanitarian law requires legal assessment.",
        ("교육분야", "생성형 인공지능 활용 교육 가이드.pdf"): "학교에서 생성형 인공지능을 활용할 때 출처 표시를 지도한다.",
    }


@pytest.mark.parametrize("query, opened", [
    ("원고는 피고와 도급계약을 체결하였고 수급인으로서 일을 완성하였으므로 민법상 보수를 청구한다.", "민법 도급계약 표준판례.pdf"),
    ("검사가 제출한 압수물은 형사소송법이 정한 영장 없이 수집되어 증거능력이 없다.", "형사소송법 표준판례.pdf"),
    ("징계위원회는 공무원인 원고에게 진술 기회를 주지 않고 징계를 의결하였다.", "공무원 징계업무편람.pdf"),
])
def test_only_name_or_path_candidates_are_opened(tmp_path, query, opened):
    drive = Drive(corpus())
    lib = library(tmp_path, drive)
    lib.sync(query=[query])
    statuses = {i["name"]: i["status"] for i in lib.summary["inventory"]}
    assert statuses[opened] == "INDEXED" and drive.downloads == 1
    assert sum(s == "NOT_SELECTED_METADATA" for s in statuses.values()) == len(corpus()) - 1
    assert lib.summary["diagnostics"]["selection_strategy"] == "METADATA_GATE"


@pytest.mark.parametrize("query", [
    "원고는 선박을 임차하여 항만에서 하역 작업을 하였다.",
    "피고는 상표를 무단으로 사용하여 영업상 혼동을 일으켰다.",
    "원고는 교통사고로 부상을 입고 치료비를 청구한다.",
])
def test_unrelated_documents_open_nothing(tmp_path, query):
    drive = Drive(corpus())
    lib = library(tmp_path, drive)
    lib.sync(query=[query])
    assert drive.downloads == 0 and not lib.eligible
    assert lib.summary["status"] == "READY"          # 열지 않은 파일은 미처리 결함이 아니다
    assert lib.select(query)["decision"] == "NOT_USED"


class SearchingDrive(Drive):
    """Drive 서버 본문 검색을 흉내 낸다: 모든 단어가 본문에 있는 파일 ID를 돌려준다."""

    def __init__(self, refs, fail=None):
        super().__init__(refs)
        self.searches, self.fail = [], fail

    def search_fulltext(self, folder_ids, terms, **kwargs):
        self.searches.append((tuple(folder_ids), tuple(terms)))
        if self.fail:
            raise ReferenceError(self.fail)
        return {fid for fid, text in self.contents.items() if all(t in text for t in terms)}


@pytest.mark.parametrize("query, opened", [
    ("수급인은 하자담보책임을 부담한다. 수급인이 하자를 보수하지 않으면 하자담보책임이 남는다.", "민법 도급계약 표준판례.pdf"),
    ("영장주의의 예외를 넓히면 안 된다. 영장주의는 증거능력 판단의 출발점이며 증거능력을 부정한다.", "형사소송법 표준판례.pdf"),
    ("출처 표시 지도가 필요하다. 인공지능 활용 수업에서 출처 표시와 인공지능 사용 내역을 확인한다.", "생성형 인공지능 활용 교육 가이드.pdf"),
])
def test_drive_fulltext_search_finds_files_with_unhelpful_names(tmp_path, query, opened):
    refs = corpus()
    # 파일명이 내용을 알려 주지 않도록 이름을 모두 번호로 바꾼다.
    renamed = {("자료", f"문서{i:02d}.pdf"): text for i, (key, text) in enumerate(refs.items())}
    target = f"문서{list(refs).index(next(k for k in refs if k[1] == opened)):02d}.pdf"
    drive = SearchingDrive(renamed)
    lib = library(tmp_path, drive)
    lib.sync(query=[query])
    statuses = {i["name"]: (i["status"], i["gate"]["reason"]) for i in lib.summary["inventory"]}
    assert statuses[target][0] == "INDEXED" and "DRIVE_FULLTEXT_MATCH" in statuses[target][1]
    assert drive.searches and len(drive.searches[0][1]) <= relevance.FULLTEXT_TERMS
    assert lib.summary["diagnostics"]["metadata_gate"]["fulltext"][0]["files"] >= 1


@pytest.mark.parametrize("error", ["DRIVE_HTTP_400", "DRIVE_HTTP_403", "DRIVE_NETWORK_ERROR"])
def test_fulltext_failure_falls_back_to_names(tmp_path, error):
    drive = SearchingDrive(corpus(), fail=error)
    lib = library(tmp_path, drive)
    lib.sync(query=["원고는 도급계약을 체결하였고 수급인으로서 일을 완성하였으므로 민법상 보수를 청구한다. 도급계약 해제는 없다."])
    assert lib.summary["diagnostics"]["metadata_gate"]["fulltext"][0]["error"] == error
    assert {i["name"] for i in lib.summary["inventory"] if i["status"] == "INDEXED"} == {"민법 도급계약 표준판례.pdf"}


def test_candidates_are_capped_and_cached_files_are_reused(tmp_path, monkeypatch):
    refs = {("판례", f"민법 도급 판례 {i:02d}.pdf"): f"도급계약 수급인 보수 {i}번 사례" for i in range(8)}
    monkeypatch.setattr(relevance, "GATE_MAX_CANDIDATES", 3)
    drive = Drive(refs)
    lib = library(tmp_path, drive)
    query = ["원고는 민법상 도급계약의 수급인으로서 보수를 청구한다."]
    lib.sync(query=query)
    assert drive.downloads == 3
    assert sum(i["gate"]["reason"] == "CANDIDATE_LIMIT" for i in lib.summary["inventory"]) == 5
    lib.sync(query=["선박 하역 작업"])                   # 관련 없는 문서라도 이미 색인된 파일은 무료로 재사용한다
    assert drive.downloads == 3 and lib.summary["files_reused"] == 3


@pytest.mark.parametrize("text, expected", [
    ("수급인은 하자담보책임을 부담한다. 수급인의 하자담보책임은 인도 후 1년이다.", ["하자담보책임", "수급인"]),
    ("영장주의 예외는 좁다. 영장주의를 벗어난 압수는 위법하다.", ["영장주의"]),
    ("원고는 주장한다. 피고는 주장한다.", []),
])
def test_salient_words_strip_particles_and_noise(text, expected):
    assert relevance.salient_words(text) == expected


# --- Drive AI 대조: 한 공급자가 실패하면 다른 공급자로 한 번 더 --------------------------------------------------
def test_review_retries_another_provider_and_accepts_extra_top_level_keys(tmp_path):
    from jsonschema import validate
    from packages.common.enums import ExternalAIPolicy
    from packages.common.schemas import Block, NormalizedDocument, Page
    from packages.llm_router.router import ModelExecution, RouterResult
    from packages.rag_engine.review import SCHEMA, review_document
    from packages.verification_engine.pipeline import DocumentResult, ProjectContext
    validate({"observations": [], "summary": "추가 설명"}, SCHEMA)
    text = "도급계약에서 수급인은 일을 완성하고 도급인은 보수를 지급한다. 하자담보책임을 진다."
    drive = Drive({("판례", "민법 도급계약 표준판례.pdf"): text})
    lib = library(tmp_path, drive)
    query = "원고는 민법상 도급계약의 수급인으로서 일을 완성하였고 도급인은 보수를 지급하여야 한다."
    lib.sync(query=[query])
    calls = []

    class Router:
        def has_available_provider(self, **kwargs):
            return True

        async def run(self, role, request, exclude=None, **kwargs):
            calls.append(exclude)
            if not exclude:
                return RouterResult(executions=[ModelExecution("PRIMARY_REASONER", "anthropic", "m", False,
                                                               error="INVALID_RESPONSE_SCHEMA")])
            quote = "도급인은 보수를 지급한다"
            return RouterResult(used=True, executions=[ModelExecution("PRIMARY_REASONER", "openai", "m", True)],
                                parsed={"observations": [{"claim_quote": "도급인은 보수를 지급하여야 한다", "source_id": "R1",
                                                          "source_quote": quote, "relationship": "SUPPORTS",
                                                          "explanation": "같은 취지"}]})

    doc = NormalizedDocument("d", "d.txt", "text/plain", "h", pages=[Page(1, blocks=[Block("b", query, 1)])])
    result = DocumentResult("d", "d.txt", normalized=doc)
    review = review_document(result, lib, Router(), ProjectContext("p", external_ai_policy=ExternalAIPolicy.MASKED),
                             SimpleNamespace(mask_text=lambda v: SimpleNamespace(masked_text=v)))
    assert calls == [None, ["anthropic"]]
    assert review["status"] == "ADVISORY_REVIEWED" and review["retried_after"] == ["anthropic"]


@pytest.mark.parametrize("exc", [ValueError("x"), IndexError("y"), KeyError("z")])
def test_gate_defect_falls_back_to_previous_priority_order(tmp_path, monkeypatch, exc):
    def broken(*args, **kwargs):
        raise exc
    monkeypatch.setattr(relevance, "metadata_gate", broken)
    drive = Drive(corpus())
    lib = library(tmp_path, drive)
    lib.sync(query=["원고는 민법상 도급계약의 수급인으로서 보수를 청구한다."])
    gate = lib.summary["diagnostics"]["metadata_gate"]
    assert gate["fallback"] == "ALL_FILES_BY_PRIORITY" and gate["error"] == type(exc).__name__
    assert not any(i["status"] == "NOT_SELECTED_METADATA" for i in lib.summary["inventory"])
    assert drive.downloads >= 1
