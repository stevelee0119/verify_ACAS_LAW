"""R8-E checks for prefixed person signals and bounded name-value handling."""
from __future__ import annotations

import json

import pytest

from packages.llm_router import privacy
from packages.llm_router.providers import LLMRequest


def _inspect_payload(payload):
    request = LLMRequest(system="합성 검토 요청", user=json.dumps(payload, ensure_ascii=False))
    return privacy.inspect_request(request)


@pytest.mark.parametrize(
    ("key", "value", "label"),
    [
        ("기관피고", "도윤서", "피고"),
        ("행정부문Witness", "나세림", "witness"),
        ("분류기준 plaintiffName", "하연우", "plaintiff"),
    ],
)
def test_person_label_survives_a_preceding_nonperson_word(key, value, label):
    assert privacy._person_label_for_key(key) == label
    assert _inspect_payload({key: value})["status"] == "BLOCKED"


@pytest.mark.parametrize(
    "value",
    [
        "가람들 물순환 사업본부",
        "초람군 민생지원 행정청",
        "동해안 공정관리 직무",
    ],
)
def test_multiword_nonperson_structure_under_role_label_is_not_contextualized(value):
    collected = privacy._collect_texts_from_value({"피고": value})
    assert ("피고", value) in collected
    assert all(text != f"피고: {value}" for _, text in collected)
    assert _inspect_payload({"피고": value})["status"] == "PASSED"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("residentName", "문 서윤"),
        ("contactName", "차도윤과 배하린"),
        ("applicantName", "진가람 감정인"),
        ("attendeeName", "강시우 외 2명"),
        ("defendantName", "노다은께는"),
    ],
)
def test_explicit_person_name_fields_keep_fail_closed_value_shapes(key, value):
    assert _inspect_payload({key: value})["status"] == "BLOCKED"


def test_generic_unmarked_role_noun_remains_outside_key_inference():
    assert privacy._person_label_for_key("등록참여자") is None

