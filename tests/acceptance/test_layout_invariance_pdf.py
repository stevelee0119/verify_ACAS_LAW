"""PDF 입력 배치 불변 시험(평가 에이전트 소관, 보호 경로). 인계 티켓 TK-22(PDF 입력 잔여), TK-29.

`test_layout_invariance.py`는 원문 **텍스트** 입력만 잰다. 4차 구현(S2, e6b58fd)은 문단 복원기를 `TextParser`에만 연결했고 PDF용 함수는 호출자가 없다
(독립 감사 Astra 4차가 지적, 평가 측이 코드와 합성 PDF로 확인: 기준 9933548과 4차에서 같은 PDF의 실패 항목이 24개 조합 모두 같다).
서면9에서 Drive 대조가 빠진 것은 PDF 입력(줄 단위 블록)이었다. 이 시험은 같은 서면을 **쪽 폭에 따라 줄 폭만 달라지는 PDF**로 만들어 같은 불변식을 잰다.

방법: 모든 개발 서면(tests/fixtures/probes/*.json 중 온라인 명세 제외)의 원문 텍스트를 reportlab 내장 CID 글꼴(HYSMyeongJo-Medium, 글꼴 설치 불필요)로
(a) 줄 폭 제한 없이 (b) 단어 경계에서 40·48·64자로 감아 PDF를 만들고, 원본 폭 PDF에서 통과하던 항목이 떨어지면 실패한다.
KNOWN_OPEN은 {(명세, 폭): {떨어지는 항목}}이며 집합이 정확히 같아야 통과한다(새 회귀 → 실패, 풀림 → 평가 에이전트가 지우라는 실패).
이 파일의 입력은 개발 자료이며 점수가 아니라 불변식을 잰다. 실제 Google Docs(Skia) PDF가 아니라 합성 PDF라는 한계가 있다(같은 파서 경로를 지난다).
"""
from __future__ import annotations

import functools
import importlib.util
import os
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

os.environ.setdefault("LV_ALLOW_NETWORK", "0")

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "probe_document.py"
PROBES = ROOT / "tests" / "fixtures" / "probes"
FONT = "HYSMyeongJo-Medium"
WIDTHS = [40, 48, 64]


def _probe():
    spec = importlib.util.spec_from_file_location("probe_document_layout_pdf", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("probe_document_layout_pdf", module)
    spec.loader.exec_module(module)
    return module


probe = _probe()
SPECS = sorted(p for p in PROBES.glob("*.json") if not p.stem.endswith("_online"))

# TK-22(PDF 입력): 줄 폭에 따라 떨어지는 항목. 키는 (명세 이름, 줄 폭). 2026-10-01 main 9933548·4차 e6b58fd에서 같다.
KNOWN_OPEN = {
    ("case6_military_secret", 40): {"INJ-1"}, ("case6_military_secret", 48): {"INJ-1"},
    ("case7_suspension", 40): {"CIT-6"},
    ("case8_delay_penalty", 40): {"INJ-1"}, ("case8_delay_penalty", 48): {"INJ-1"},
    ("case9_state_compensation", 40): {"INJ-1"}, ("case9_state_compensation", 48): {"INJ-1"},
    ("variant1_discipline", 40): {"INJ-1b"}, ("variant1_discipline", 48): {"INJ-1b"},
    ("variant2_food_license", 40): {"INJ-1a"},
}


def make_pdf(text: str, path: Path, width: int | None) -> None:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(UnicodeCIDFont(FONT))
    lines = []
    for line in text.split("\n"):
        lines.extend([line] if (width is None or len(line) <= width) else
                     textwrap.wrap(line, width=width, break_long_words=False, break_on_hyphens=False))
    page = canvas.Canvas(str(path), pagesize=(595, 842))
    page.setFont(FONT, 10.5)
    y = 800
    for line in lines:
        if y < 50:
            page.showPage()
            page.setFont(FONT, 10.5)
            y = 800
        page.drawString(56, y, line)
        y -= 15
    page.save()


@functools.lru_cache(maxsize=None)
def passed_ids(spec_path: str, width: int | None) -> frozenset:
    spec = probe.load_spec(Path(spec_path))
    source = (ROOT / spec["text_input"]).read_text(encoding="utf-8")
    path = Path(tempfile.mkdtemp()) / "t.pdf"
    make_pdf(source, path, width)
    obs = probe.observe(ROOT, path, "application/pdf")
    assert not obs["errors"], obs["errors"]
    return frozenset(r["id"] for r in probe.evaluate(spec, obs) if r["passed"])


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("spec_path", SPECS, ids=lambda p: p.stem)
def test_pdf_results_do_not_depend_on_line_width(spec_path, width):
    spec = probe.load_spec(spec_path)
    if "text_input" not in spec:
        pytest.skip("원문 텍스트가 없는 명세")
    base = passed_ids(str(spec_path), None)
    missing = set(base - passed_ids(str(spec_path), width))
    known = KNOWN_OPEN.get((spec["name"], width), set())
    assert not (missing - known), f"새 회귀: 원본 폭 PDF에서 통과하던 {sorted(missing - known)}가 폭 {width} PDF에서 떨어진다"
    assert not (known - missing), f"풀렸다: {sorted(known - missing)} — 평가 에이전트가 KNOWN_OPEN에서 지운다"


def test_known_open_keys_are_real():
    names = {probe.load_spec(p)["name"] for p in SPECS}
    for name, width in KNOWN_OPEN:
        assert name in names and width in WIDTHS, (name, width)
