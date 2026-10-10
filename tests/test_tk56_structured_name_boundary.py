"""TK-56 synthetic privacy cases: both leakage and overblocking, no private data."""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from time import perf_counter
from types import SimpleNamespace

import pytest

from packages.common.enums import LLMRole
from packages.llm_router import privacy, router as router_module
from packages.llm_router.providers import LLMRequest, LLMResponse
from packages.pii_engine.pseudonym import PseudonymStore


NAMES = ("한예솔", "유다린", "남궁서율")
KEYS = ("fullName", "담당관 성함", "수탁명의자", "custodianNm")
SHAPES = (
    lambda name: f"{name[0]} {name[1:]}",
    lambda name: f"{name}와 문예준",
    lambda name: f"{name} 회계책임자",
    lambda name: f"{name} 외 3명",
    lambda name: f"{name}께는",
)


def _request(payload, position):
    text = json.dumps(payload, ensure_ascii=False)
    kwargs = dict(system="s", user="u")
    if position in {"system", "user"}:
        kwargs[position] = text
    elif position == "schema":
        kwargs[position] = {"type": "object", "default": payload}
    else:
        kwargs["metadata"] = payload
    return LLMRequest(**kwargs)


def _route(monkeypatch, request):
    monkeypatch.setattr(router_module, "estimate_call", lambda *a: (Decimal("0.01"), {}))
    sent, reserved = [], []

    class FakeProvider:
        name, available = "anthropic", True
        config = SimpleNamespace(name="anthropic", kind="cloud", model="fake", enabled=True)

        async def generate(self, request):
            sent.append(request)
            return LLMResponse(False, error="synthetic service failure")

    def reserve(*args, **kwargs):
        reserved.append(True)
        return SimpleNamespace(id="synthetic-reservation", amount=Decimal("0.01"))

    ledger = SimpleNamespace(reserve=reserve, dispatch=lambda *a, **k: None)
    router = router_module.LLMRouter(providers={"anthropic": FakeProvider()}, ledger=ledger)
    result = asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request))
    return result, sent, reserved


@pytest.mark.parametrize("position", ("system", "user", "schema", "metadata"))
@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("shape", SHAPES, ids=("spacing", "list", "title", "count", "particle"))
def test_synthetic_name_shapes_block_in_inspection_and_actual_router(monkeypatch, position, key, name, shape):
    request = _request({key: shape(name)}, position)
    report = privacy.inspect_request(request)
    assert report["status"] == "BLOCKED"
    assert report["failure_code"] == "PII_INPUT_BLOCKED"
    result, sent, reserved = _route(monkeypatch, request)
    assert not sent and not reserved
    assert result.executions[0].cost_status == "NOT_SENT"
    # Receipt contains codes/counts/paths, not the value.
    assert shape(name) not in json.dumps(report, ensure_ascii=False)


@pytest.mark.parametrize("position", ("system", "user"))
@pytest.mark.parametrize("key", ("name", "claimantName", "담당관 성함"))
@pytest.mark.parametrize("value", ("Taylor Morgan", 58213, {"value": "未確認"}, None, ["Casey", "River"]))
def test_synthetic_uncertain_name_values_block_before_send(monkeypatch, position, key, value):
    request = _request({key: value}, position)
    assert privacy.inspect_request(request)["status"] == "BLOCKED"
    _, sent, reserved = _route(monkeypatch, request)
    assert not sent and not reserved


@pytest.mark.parametrize("position", ("system", "user"))
@pytest.mark.parametrize("key,value", (
    ("locationName", "초록광역시"),
    ("organizationName", "가람문화 법인"),
    ("documentName", "도시계획 검토자료"),
    ("facilityName", "해빛환경관측센터"),
    ("ensembleName", "푸른문화연구원"),
    ("archiveName", "초록자료보관소"),
    ("피고", "가람환경 사업본부"),
    ("원고", "초록농원 법인"),
    ("담당자", "업무배정"),
))
def test_synthetic_nonperson_values_keep_actual_send(monkeypatch, position, key, value):
    request = _request({key: value}, position)
    assert privacy.inspect_request(request)["status"] == "PASSED"
    _, sent, reserved = _route(monkeypatch, request)
    assert len(sent) == len(reserved) == 1


@pytest.mark.parametrize("key", ("locationName", "documentName", "facilityName"))
@pytest.mark.parametrize("position", ("system", "user"))
@pytest.mark.parametrize("value", (
    "전화번호: 010-5321-8094",
    "주민등록번호: 950412-2145827",
    "작성자 한예솔은 확인하였다.",
))
def test_synthetic_nonperson_key_never_exempts_raw_pii(monkeypatch, key, position, value):
    request = _request({key: value}, position)
    assert privacy.inspect_request(request)["status"] == "BLOCKED"
    _, sent, reserved = _route(monkeypatch, request)
    assert not sent and not reserved


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("position", ("system", "user"))
def test_real_pseudonym_store_tokens_are_transmittable(monkeypatch, tmp_path, name, position):
    token = PseudonymStore(project_id="synthetic-tk56", root=tmp_path).pseudonym_for("PERSON", name)
    request = _request({"fullName": token}, position)
    assert privacy.inspect_request(request)["status"] == "PASSED"
    _, sent, reserved = _route(monkeypatch, request)
    assert len(sent) == len(reserved) == 1
    assert name not in json.dumps(vars(sent[0]), ensure_ascii=False)


@pytest.mark.parametrize("value", ("PERSON_001 Han Yeseol", "[PERSON_001] 한예솔", "PERSON_001; Yoon Areum"))
def test_synthetic_pseudonym_prefix_does_not_exempt_remaining_name(value):
    assert privacy.inspect_request(_request({"fullName": value}, "user"))["status"] == "BLOCKED"


@pytest.mark.parametrize("payload", (
    {"nested": {"fullName": "한 예솔"}},
    {"encoded": json.dumps({"custodianNm": "유다린 외 3명"}, ensure_ascii=False)},
    [{"담당관 성함": "남궁서율 회계책임자"}],
))
def test_synthetic_nested_and_encoded_fields_share_the_boundary(payload):
    assert privacy.inspect_request(_request(payload, "user"))["status"] == "BLOCKED"


@pytest.mark.parametrize("key", (
    "管理人 name", "full_name", "ＦｕｌｌＮａｍｅ", "수탁 명의자", "보고담당명", "관리직원명",
))
@pytest.mark.parametrize("name", NAMES)
def test_synthetic_name_key_grammar_variants_keep_context(key, name):
    assert privacy.inspect_request(_request({key: name}, "user"))["status"] == "BLOCKED"


@pytest.mark.parametrize("key", ("회사명", "문서 이름", "사업명"))
def test_synthetic_nonperson_key_grammar_is_not_a_person_exception(key):
    assert privacy._person_label_for_key(key) is None
    assert privacy.inspect_request(_request({key: "초록계획자료"}, "user"))["status"] == "PASSED"
    assert privacy.inspect_request(_request({key: "담당자 한예솔"}, "user"))["status"] == "BLOCKED"


@pytest.mark.parametrize("name", ("남궁서율", "황보연우", "제갈다솔"))
def test_synthetic_double_surname_particle_restores_full_stem(name):
    assert privacy._name_like_value(name + "은") == name
    assert privacy.inspect_request(_request({"피고": name + "은"}, "user"))["status"] == "BLOCKED"


@pytest.mark.parametrize("name", ("한예은", "유다이", "남궁서은"))
def test_synthetic_particle_like_name_end_preserves_full_name(name):
    assert privacy._name_like_value(name) == name
    assert privacy.inspect_request(_request({"피고": name}, "user"))["status"] == "BLOCKED"


@pytest.mark.parametrize("schema", tuple(privacy.REGISTERED_SCHEMA_CONSTANTS.values()))
def test_registered_schema_source_contract_is_retained(schema):
    report = privacy.inspect_request(LLMRequest(system="", user="", schema=schema))
    assert report["status"] == "PASSED"


def test_synthetic_key_classification_thousands_under_point_one_second():
    keys = ("등록인 성함", "companyRepresentativeName", "guardianNm", "facilityName", "caseTitle") * 600
    started = perf_counter()
    for key in keys:
        privacy._person_label_for_key(key)
        privacy._has_name_field_marker(key)
    elapsed = perf_counter() - started
    print(f"TK-56 key grammar 3,000 pairs: {elapsed:.6f}s")
    assert elapsed < 0.1


def test_synthetic_value_paths_thousands_under_point_one_second():
    values = ("한 예솔", "유다린께는", "PERSON_001", "PERSON_001 한예솔", "가람환경 사업본부") * 600
    started = perf_counter()
    for value in values:
        privacy._name_like_value(value)
        privacy._uncertain_person_value(value, explicit_name=True)
    elapsed = perf_counter() - started
    print(f"TK-56 value boundary 3,000 pairs: {elapsed:.6f}s")
    assert elapsed < 0.1


def test_synthetic_field_collection_thousands_under_point_one_second():
    payload = [{"fullName": "한 예솔", "facilityName": "푸른기상관측센터"} for _ in range(1000)]
    blocked = []
    started = perf_counter()
    texts = privacy._collect_texts_from_value(payload, _uncertain_paths=blocked)
    elapsed = perf_counter() - started
    print(f"TK-56 collector 2,000 fields: {elapsed:.6f}s")
    assert len(blocked) == 1000 and len(texts) == 2000
    assert elapsed < 0.1


def test_synthetic_long_key_and_value_paths_are_linear():
    key = "field_" * 2000 + "claimantName"
    value = "PERSON_001; " * 2000 + "한예솔"
    started = perf_counter()
    assert privacy._person_label_for_key(key) == "claimant"
    assert privacy._uncertain_person_value(value, explicit_name=True)
    elapsed = perf_counter() - started
    print(f"TK-56 repeated long key/value: {elapsed:.6f}s")
    assert elapsed < 0.1
