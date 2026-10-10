"""Synthetic TK-74 regressions through sync, isolated extraction, reuse and select.

All documents are generated here; no actual Drive or private evaluation inputs.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib

import pytest

from helpers import make_pdf
from packages.common.config import get_settings
from packages.rag_engine.library import ReferenceLibrary


TOPICS = [
    (
        "합성 예산자료",
        "근로계약의 해고에는 정당한 이유가 있어야 한다. 사용자는 해고 사유와 시기를 "
        "서면으로 통지한다. 근로자의 임금과 근로계약 관계를 확인한다.",
        "근로계약 해고 정당한 이유 서면 통지 임금",
        "선박 운항 항만 안전 해상 구조",
    ),
    (
        "통합 운영기록",
        "임대차가 종료되면 임대인은 임대차보증금을 반환한다. 임차인은 목적물을 인도하고 "
        "임대차보증금 반환을 청구한다. 보증금 반환과 목적물 인도의 동시이행 관계를 확인한다.",
        "임대차보증금 반환 목적물 인도 동시이행 관계",
        "저작권 창작 기여 복제 배포 전송",
    ),
    (
        "월별 자산목록",
        "수사기관은 압수수색 영장의 범위에서 전자정보를 선별한다. 피압수자의 참여권을 "
        "보장하고 압수목록을 교부한다. 전자정보 압수수색의 절차와 증거능력을 검토한다. " * 8,
        "전자정보 압수수색 영장 범위 참여권 압수목록 증거능력",
        "혼인 파탄 이혼 위자료 재산분할 양육",
    ),
]
MIMES = {
    "txt": "text/plain",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def document_bytes(tmp_path, kind, body):
    if kind == "txt":
        return body.encode()
    path = tmp_path / f"synthetic.{kind}"
    if kind == "pdf":
        # Keep each line within the page; exercise the actual PDF text reader.
        make_pdf(path, [body[start:start + 40] for start in range(0, len(body), 40)])
    else:
        from docx import Document

        document = Document()
        document.add_paragraph(body)
        document.save(path)
    return path.read_bytes()


class SyntheticDrive:
    folder_id = "synthetic_root_001"
    file_id = "synthetic_document_001"

    def __init__(self, name, mime, data):
        self.data = data
        self.downloads = 0
        self.item = {
            "id": self.file_id, "name": name, "mimeType": mime, "version": "1",
            "modifiedTime": "2026-10-10T00:00:00Z", "parents": [self.folder_id],
            "size": str(len(data)), "capabilities": {"canDownload": True},
            "md5Checksum": hashlib.md5(data).hexdigest(),
        }

    def __call__(self, **kwargs):
        return self

    def remaining(self):
        return 120

    def inventory(self, *args, **kwargs):
        return [deepcopy(self.item)]

    def metadata(self, file_id):
        assert file_id == self.file_id
        return deepcopy(self.item)

    def search_fulltext(self, *args, **kwargs):
        # Force the second query to rely on the real local body cache.
        return []

    def download(self, item, *, max_bytes):
        assert len(self.data) <= max_bytes
        self.downloads += 1
        return self.data, item["name"], item["mimeType"]

    def close(self):
        pass


def new_library(tmp_path, drive):
    settings = replace(
        get_settings(), storage_root=tmp_path / "cache",
        rag_drive_folder_id=drive.folder_id, allow_network=True,
        rag_metadata_first=True,
    )
    # Keep the production isolated_extract default, including its scanner.
    return ReferenceLibrary(settings, client_factory=drive)


@pytest.mark.parametrize("kind", MIMES)
@pytest.mark.parametrize("name,body,related,unrelated", TOPICS, ids=["employment", "tenancy", "digital"])
def test_general_cache_reused_for_body_search_without_name_match(
    tmp_path, kind, name, body, related, unrelated,
):
    """Synthetic positives and negatives: three themes in each real file format."""
    data = document_bytes(tmp_path, kind, body)
    drive = SyntheticDrive(f"{name}.{kind}", MIMES[kind], data)
    first = new_library(tmp_path, drive)
    first_summary = first.sync(query=name)
    assert first_summary["inventory"][0]["gate"]["selected"] is True
    assert first_summary["files_indexed"] == 1
    assert first_summary["diagnostics"]["downloads"]["count"] == 1
    revision = first.eligible[drive.file_id]["revision"]

    # Use a new object to prove disk cache reuse, rather than retained eligibility.
    reused = new_library(tmp_path, drive)
    second = reused.sync(query=related)
    assert second["inventory"][0]["gate"]["selected"] is False
    assert second["files_reused"] == 1
    assert second["diagnostics"]["downloads"]["count"] == 0
    assert drive.downloads == 1
    selection = reused.select(related)
    assert selection["decision"] == "USED", selection
    assert {source["file_id"] for source in selection["sources"]} == {drive.file_id}
    assert all(source["text"] for source in selection["sources"])
    assert reused.eligible[drive.file_id]["revision"] == revision
    assert reused.eligible[drive.file_id]["sha256"] == hashlib.sha256(data).hexdigest()
    assert reused.eligible[drive.file_id]["chunk_count"] > 0

    # Restoring eligibility must not make an unrelated body query use the file.
    negative = new_library(tmp_path, drive)
    third = negative.sync(query=unrelated)
    assert third["inventory"][0]["gate"]["selected"] is False
    assert third["files_reused"] == 1
    assert third["diagnostics"]["downloads"]["count"] == 0
    assert drive.file_id in negative.eligible
    rejection = negative.select(unrelated)
    assert rejection["decision"] == "NOT_USED", rejection
    assert rejection["sources"] == []
    assert drive.downloads == 1


@pytest.mark.parametrize("kind", MIMES)
def test_uncached_general_document_still_requires_metadata_selection(tmp_path, kind):
    """Synthetic controls: body eligibility does not expand the download gate."""
    name, body, related, _ = TOPICS[0]
    drive = SyntheticDrive(f"{name}.{kind}", MIMES[kind], document_bytes(tmp_path, kind, body))
    library = new_library(tmp_path, drive)
    summary = library.sync(query=related)
    assert summary["inventory"][0]["gate"]["selected"] is False
    assert summary["inventory"][0]["status"] == "NOT_SELECTED_METADATA"
    assert summary["files_indexed"] == 0
    assert drive.downloads == 0
    assert library.select(related)["sources"] == []
