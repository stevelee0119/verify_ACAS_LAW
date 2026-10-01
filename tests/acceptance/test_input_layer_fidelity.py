"""입력 단계 불변식(평가 에이전트 소관, 보호 경로).

저장소의 모든 시험 PDF(tests/fixtures/**.pdf)를 프로젝트 파서로 읽어, 본문에 사용자 영역 문자(유니코드 범주 Co)나
대체 문자(U+FFFD)가 남지 않는지 본다. 이런 문자는 글꼴의 대체 글리프를 복원하지 못한 흔적이고, 번호·괄호·하이픈이 깨져
개인정보·인용 추출이 조용히 빗나가는 원인이 된다(서면7, 인계 티켓 TK-01).
서면 한 건이 아니라 모든 PDF에 거는 불변식이라 새 PDF를 fixtures에 넣으면 자동으로 대상이 된다.

알려진 미해결은 strict xfail이다. 고치면 XPASS(strict)로 실패하므로 평가 에이전트가 표시를 지운다.
"""
from __future__ import annotations

import os
import unicodedata
from pathlib import Path

import pytest

os.environ.setdefault("LV_ALLOW_NETWORK", "0")

ROOT = Path(__file__).resolve().parents[2]
PDFS = sorted((ROOT / "tests" / "fixtures").rglob("*.pdf"))

KNOWN_OPEN: dict = {}     # 2026-10-01 cf7c739에서 TK-01이 해결되어 비었다


def _suspect_characters(text: str) -> dict:
    found: dict = {}
    for ch in text:
        if unicodedata.category(ch) == "Co" or ch == "�":
            found[f"U+{ord(ch):04X}"] = found.get(f"U+{ord(ch):04X}", 0) + 1
    return found


def _param(path: Path):
    rel = str(path.relative_to(ROOT))
    ticket = KNOWN_OPEN.get(rel)
    marks = [pytest.mark.xfail(strict=True, reason=f"{ticket}: 사용자 영역 문자가 본문에 남는다")] if ticket else []
    return pytest.param(path, marks=marks, id=rel)


@pytest.mark.parametrize("path", [_param(p) for p in PDFS])
def test_extracted_text_has_no_private_use_or_replacement_characters(path):
    from packages.document_engine.registry import parse_document

    doc = parse_document(str(path), document_id="fidelity", filename=path.name, mime_type="application/pdf", sha256="x")
    text = "\n".join(block.text for page in doc.pages for block in page.blocks)
    assert text.strip(), "본문을 하나도 읽지 못했다"
    assert _suspect_characters(text) == {}


def test_known_open_files_exist():
    for rel in KNOWN_OPEN:
        assert (ROOT / rel).is_file(), rel


def test_suspect_character_detector():
    assert _suspect_characters("군번: 09108273 � 정상 텍스트 - ( )") == {"U+E088": 1, "U+FFFD": 1}
    assert _suspect_characters("군번: 09-108273 [ADMIN: X]") == {}
