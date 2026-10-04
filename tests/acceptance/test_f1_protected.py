"""[평가 에이전트 소관] F1·F2 보호 시험 T1~T5 (F1 지시서 6절, 회신서 8절).

- T1 단일 판정: 인용 하나에 검토 행 하나, 행의 심각도는 연결된 finding에서 순수 파생(19b 2.3).
- T2 손실 없음: 모든 finding이 AI·보안 탭 배정이거나 어떤 검토 행에 연결된다(HIGH 이상 포함).
- T3 배정 완전성: 서버 배정표가 모든 FindingType을 한 번씩 배정하고 기존 유형 집합과 맞는다.
- T4 AI 탭 배타성: 검토 행에 AI·보안 유형이 없고, 화면이 배정표를 따로 하드코딩하지 않으며, AI 탭이 인용·RAG 섹션을 그리지 않는다.
- T5 기존 JSON 키 불변: 결과 JSON의 기존 키(최상위·문서·finding)는 지우지 않는다(추가만).

기능이 없는 커밋(F1 이전 통합 브랜치)에서는 해당 시험을 건너뛴다. F1·F2 병합 판정 때 평가 측이 건너뜀 없이 통과하는지 확인한다.
입력은 저장소의 고정 시험 텍스트이며 오프라인으로 돈다.
"""
from __future__ import annotations

import importlib
import json
import os
import re
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "apps" / "web" / "static" / "app.js"
BASELINE = ROOT / "tests" / "fixtures" / "f1_json_keys_baseline.json"
INPUTS = ("case9_state_compensation", "variant1_discipline")


def _category_map():
    try:
        return importlib.import_module("packages.common.finding_category_map")
    except ModuleNotFoundError:
        pytest.skip("F1 배정표 모듈이 없는 커밋(F1 이전)")


@pytest.fixture(scope="module")
def payloads():
    os.environ["LV_ALLOW_NETWORK"] = "0"
    os.environ.setdefault("LV_DATA_DIR", tempfile.mkdtemp(prefix="f1_protected_"))
    from packages.common.storage import sha256_file
    from packages.report_engine.exporters import to_payload
    from packages.verification_engine import DocumentInput, ProjectContext, VerificationPipeline

    out = []
    for name in INPUTS:
        path = ROOT / "tests" / "fixtures" / "probes" / f"{name}.txt"
        result = VerificationPipeline().run(f"f1_{name}", ProjectContext(project_id="f1"), [DocumentInput(
            document_id="d1", path=str(path), filename=path.name, mime_type="text/plain", sha256=sha256_file(path))])
        out.append(json.loads(json.dumps(to_payload(result), default=str)))
    return out


def _review_items(payload):
    docs = payload["documents"]
    if not any("review_items" in d for d in docs):
        pytest.skip("review_items가 없는 커밋(F2 이전)")
    return [(d, d.get("review_items") or []) for d in docs]


# --------------------------------------------------------------------------- T3 ---
def test_t3_every_finding_type_is_assigned_once_and_matches_existing_sets():
    mod = _category_map()
    from packages.common.enums import ADVERSARIAL_FINDING_TYPES, LEGAL_FINDING_TYPES, MM4_ADVISORY_TYPES, FindingType

    mapping, to_tab = mod.FINDING_CATEGORY_MAP, mod.CATEGORY_TO_TAB
    assert set(mapping) == set(FindingType)
    assert all(category in to_tab for category in mapping.values())
    review, ai = mod.ScreenTab.REVIEW_ITEMS, mod.ScreenTab.AI_SECURITY
    assert {to_tab[mapping[t]] for t in ADVERSARIAL_FINDING_TYPES} == {ai}
    assert {to_tab[mapping[t]] for t in MM4_ADVISORY_TYPES} == {review}
    assert {to_tab[mapping[t]] for t in LEGAL_FINDING_TYPES} == {review}
    # 회신서 3절: 내용 검증 대상·처리 품질 신호는 검토 항목
    assert to_tab[mapping[FindingType.MODEL_FACT_REMARK]] == review
    assert to_tab[mapping[FindingType.OCR_LOW_QUALITY]] == review


# --------------------------------------------------------------------------- T4 ---
def test_t4_screen_reads_the_server_map_instead_of_hardcoding_it():
    _category_map()
    from packages.common.enums import FindingType

    source = APP_JS.read_text(encoding="utf-8")
    named = [n for n in FindingType.__members__ if re.search(rf"\b{n}\b", source)]
    # F1 이전 app.js가 특수 처리로 이름을 직접 쓰는 유형은 1개였다. 배정표를 옮겨 적으면 수십 개가 된다.
    assert len(named) <= 3, f"app.js가 FindingType 이름 {len(named)}개를 직접 적는다(배정표 이중 관리): {named[:8]}"


def test_t4_ai_tab_does_not_render_citation_or_reference_sections():
    _category_map()
    source = APP_JS.read_text(encoding="utf-8")
    match = re.search(r"function renderAIVerification\(\)\s*\{", source)
    assert match, "renderAIVerification을 찾지 못함"
    depth, i = 1, match.end()
    while depth and i < len(source):
        depth += {"{": 1, "}": -1}.get(source[i], 0)
        i += 1
    body = source[match.end():i]
    for marker in ("referenceSection(", "related_authorities", "ai_hallucination_table"):
        assert marker not in body, f"AI 탭 렌더링이 인용·RAG 섹션({marker})을 그린다"


def test_t4_review_items_never_carry_ai_security_types(payloads):
    mod = _category_map()
    from packages.common.enums import FindingType

    for payload in payloads:
        for doc, items in _review_items(payload):
            types = {f["finding_id"]: f["type"] for f in doc["findings"]}
            for item in items:
                for fid in item.get("finding_ids", []):
                    category = mod.FINDING_CATEGORY_MAP[FindingType(types[fid])]
                    assert mod.CATEGORY_TO_TAB[category] == mod.ScreenTab.REVIEW_ITEMS, item["item_id"]


# --------------------------------------------------------------------------- T1 ---
def test_t1_one_row_per_citation_and_severity_is_derived_from_linked_findings(payloads):
    from packages.common.enums import Severity

    for payload in payloads:
        for doc, items in _review_items(payload):
            by_id = {f["finding_id"]: f for f in doc["findings"]}
            citations = [i["citation_id"] for i in items if i.get("citation_id")]
            assert len(citations) == len(set(citations)), "같은 인용이 검토 행 둘 이상에 나온다"
            assert len({i["item_id"] for i in items}) == len(items), "item_id 중복"
            for item in items:
                linked = [Severity(by_id[fid]["severity"]) for fid in item.get("finding_ids", [])]
                expected = max(linked, key=lambda s: s.rank) if linked else Severity.INFO
                assert Severity(item["severity"]) == expected, item["item_id"]


# --------------------------------------------------------------------------- T2 ---
def test_t2_every_finding_is_reachable_either_in_ai_tab_or_a_review_row(payloads):
    mod = _category_map()
    from packages.common.enums import FindingType

    for payload in payloads:
        for doc, items in _review_items(payload):
            linked = {fid for item in items for fid in item.get("finding_ids", [])}
            for finding in doc["findings"]:
                tab = mod.CATEGORY_TO_TAB[mod.FINDING_CATEGORY_MAP[FindingType(finding["type"])]]
                assert tab == mod.ScreenTab.AI_SECURITY or finding["finding_id"] in linked, \
                    f"{finding['type']}({finding['severity']})가 어느 화면에도 도달하지 않는다"


# --------------------------------------------------------------------------- T5 ---
def test_t5_existing_result_json_keys_are_kept(payloads):
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    for payload in payloads:
        assert set(baseline["top"]) <= set(payload), set(baseline["top"]) - set(payload)
        doc = payload["documents"][0]
        assert set(baseline["document"]) <= set(doc), set(baseline["document"]) - set(doc)
        for finding in doc["findings"]:
            assert set(baseline["finding"]) <= set(finding), set(baseline["finding"]) - set(finding)
