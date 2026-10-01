"""배치 불변 시험(평가 에이전트 소관, 보호 경로). 인계 티켓 TK-22.

같은 서면을 **내용은 그대로 두고 줄바꿈 배치만 바꿔** 넣어도 결과가 같아야 한다. PDF는 쪽 너비·글꼴에 따라 같은 문장이 다른 곳에서 줄바꿈되고,
원문 텍스트 입력도 편집기마다 줄 폭이 다르다. 모든 개발 자료(tests/fixtures/probes/*.json 중 온라인 명세 제외)의 원문 텍스트를
(a) 단어 경계에서 40·48·64자로 감고 (b) 줄끝을 CRLF로 바꾸고 (c) 줄 사이에 빈 줄을 넣어, 원문에서 통과하던 항목이 하나라도 떨어지면 실패한다.

알려진 미해결(KNOWN_OPEN)은 {(명세, 변환): {떨어지는 항목}}이다. 집합이 정확히 같아야 통과한다.
- 새 항목이 떨어지면(새 회귀) 실패한다. - 알려진 항목이 풀리면(집합이 줄면) 실패한다. 풀렸다는 뜻이므로 평가 에이전트가 KNOWN_OPEN에서 지운다.
2026-10-01 main 9933548 측정. 서면 6·8·9·변형 1·2의 인젝션 표지 항목이 줄 폭 40·48자에서 모두 떨어진다(표지가 한 줄에 들어갈 때만 탐지).
이 파일의 입력은 개발 자료이며 점수가 아니라 불변식을 잰다.
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


def _probe():
    spec = importlib.util.spec_from_file_location("probe_document_layout", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("probe_document_layout", module)
    spec.loader.exec_module(module)
    return module


probe = _probe()
SPECS = sorted(p for p in PROBES.glob("*.json") if not p.stem.endswith("_online"))
TRANSFORMS = ["wrap40", "wrap48", "wrap64", "crlf", "blank"]

# TK-22: 줄 폭에 따라 떨어지는 항목. 키는 (명세 이름, 변환).
KNOWN_OPEN = {
    ("case6_military_secret", "wrap40"): {"INJ-1"},
    ("case6_military_secret", "wrap48"): {"INJ-1"},
    ("case7_suspension", "wrap40"): {"CIT-6"},
    ("case8_delay_penalty", "wrap40"): {"INJ-1"},
    ("case8_delay_penalty", "wrap48"): {"INJ-1"},
    ("case9_state_compensation", "wrap40"): {"INJ-1"},
    ("case9_state_compensation", "wrap48"): {"INJ-1"},
    ("variant1_discipline", "wrap40"): {"INJ-1b"},
    ("variant1_discipline", "wrap48"): {"INJ-1b"},
    ("variant2_food_license", "wrap40"): {"INJ-1a"},
    ("variant2_food_license", "wrap64"): {"INJ-1b"},
}


def transform(text: str, kind: str) -> bytes:
    if kind.startswith("wrap"):
        width = int(kind[4:])
        lines = []
        for line in text.split("\n"):
            lines.extend([line] if len(line) <= width else
                         textwrap.wrap(line, width=width, break_long_words=False, break_on_hyphens=False))
        return ("\n".join(lines)).encode("utf-8")
    if kind == "crlf":
        return text.replace("\n", "\r\n").encode("utf-8")
    if kind == "blank":
        return text.replace("\n", "\n\n").encode("utf-8")
    raise ValueError(kind)


@functools.lru_cache(maxsize=None)
def passed_ids(spec_path: str, kind: str) -> frozenset:
    spec = probe.load_spec(Path(spec_path))
    source = (ROOT / spec["text_input"]).read_text(encoding="utf-8")
    path = Path(tempfile.mkdtemp()) / "t.txt"
    path.write_bytes(source.encode("utf-8") if kind == "original" else transform(source, kind))
    rows = probe.evaluate(spec, probe.observe(ROOT, path, "text/plain"))
    return frozenset(r["id"] for r in rows if r["passed"])


@pytest.mark.parametrize("kind", TRANSFORMS)
@pytest.mark.parametrize("spec_path", SPECS, ids=lambda p: p.stem)
def test_results_do_not_depend_on_line_layout(spec_path, kind):
    spec = probe.load_spec(spec_path)
    if "text_input" not in spec:
        pytest.skip("원문 텍스트 입력이 없는 명세")
    base = passed_ids(str(spec_path), "original")
    missing = set(base - passed_ids(str(spec_path), kind))
    known = KNOWN_OPEN.get((spec["name"], kind), set())
    assert not (missing - known), f"새 회귀: 원문에서 통과하던 {sorted(missing - known)}가 {kind} 배치에서 떨어진다"
    assert not (known - missing), f"풀렸다: {sorted(known - missing)} — 평가 에이전트가 KNOWN_OPEN에서 지운다"


def test_known_open_keys_are_real():
    names = {probe.load_spec(p)["name"] for p in SPECS}
    for (name, kind) in KNOWN_OPEN:
        assert name in names and kind in TRANSFORMS, (name, kind)
