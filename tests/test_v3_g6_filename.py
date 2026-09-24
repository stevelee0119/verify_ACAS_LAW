"""추가지시 G6: 근거가 불분명한 '파일명 배포본 식별 문자열' 오탐 제거. 일반 단어·버전 표기로는 내지 않는다."""
from __future__ import annotations

import pytest

from packages.common.schemas import Block, NormalizedDocument, Page
from packages.forensic_engine.covert import scan_covert


def findings_for(filename):
    page = Page(page_number=1, blocks=[Block(block_id="b0", text="본문", page=1)])
    doc = NormalizedDocument(document_id="d", filename=filename, mime_type="application/pdf", sha256="0", pages=[page])
    return [f for f in scan_covert(doc) if "파일명" in f.title]


@pytest.mark.parametrize("name", ["scan_bundle_v2.pdf", "소장_사본.pdf", "copy of brief.pdf", "distribution_list.pdf",
                                  "준비서면_v3_final.pdf"])
def test_ordinary_words_and_versions_are_not_flagged(name):
    assert findings_for(name) == []


@pytest.mark.parametrize("name", ["brief_3f9a1c7e5b2d4a60.pdf", "소장-6f1d2a4b-9c3e-4f5a-8b7c-1d2e3f4a5b6c.pdf"])
def test_long_random_identifier_is_info_only(name):
    [f] = findings_for(name)
    assert str(f.severity) == "INFO"
