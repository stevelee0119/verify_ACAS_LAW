"""R8-D regression tests for conservative structured name-key inspection."""
from __future__ import annotations

import asyncio
import hashlib
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from packages.common.enums import LLMRole
from packages.llm_router import privacy, router as router_module
from packages.llm_router.providers import LLMRequest, LLMResponse
from packages.pii_engine import detector


def _inspect_payload(payload):
    request = LLMRequest(system="검토 요청", user=json.dumps(payload, ensure_ascii=False))
    return privacy.inspect_request(request)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("claimantDisplayName", "문서하"),
        ("신청자 성함", "배하린"),
        ("계약명의자", "서이겸"),
        ("profileSurname", "윤가람"),
        ("상담직원명", "임다온"),
        ("delegateNm", "오하윤"),
    ],
)
def test_name_fields_outside_exact_label_vocabulary_fail_closed(key, value):
    assert privacy._person_label_for_key(key) is not None
    assert _inspect_payload({key: value})["status"] == "BLOCKED"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("customerName", "신 유주"),
        ("fullName", "문지후와 윤가람"),
        ("personName", "배소율 편집장"),
        ("contactName", "정이안 외 4명"),
        ("plaintiffName", "임서현 님께서는"),
    ],
)
def test_name_key_values_with_spacing_lists_titles_or_particles_are_blocked(key, value):
    assert _inspect_payload({key: value})["status"] == "BLOCKED"


def test_person_role_key_with_attached_particle_keeps_name_stem_context():
    collected = privacy._collect_texts_from_value({"피고": "배수민은"})
    assert ("피고", "피고: 배수민") in collected
    assert _inspect_payload({"피고": "배수민은"})["status"] == "BLOCKED"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("incidentTitle", "가을철 협의 기록"),
        ("locationName", "동백광역시"),
        ("jobDescription", "업무지원"),
        ("companyName", "푸른정원 법인"),
        ("institutionName", "국립수로관측소"),
    ],
)
def test_non_person_keys_keep_scanning_without_name_key_fail_closed(key, value):
    assert privacy._person_label_for_key(key) is None
    assert _inspect_payload({key: value})["status"] == "PASSED"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("피고", "새솔광역시"),
        ("담당자", "업무배정"),
        ("원고", "해오름기술 법인"),
    ],
)
def test_confident_place_job_and_organization_values_remain_transmittable(key, value):
    assert _inspect_payload({key: value})["status"] == "PASSED"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("fullName", "Avery Rowan"),
        ("claimantSurname", "ordinary free text"),
        ("profileName", 71342),
    ],
)
def test_uncertain_non_korean_or_non_string_name_field_values_are_blocked(key, value):
    assert _inspect_payload({key: value})["status"] == "BLOCKED"


def test_english_structured_key_labels_do_not_change_plain_text_label_regex():
    assert hashlib.sha256(detector.LABELLED_PARTY_PERSON_RE.pattern.encode()).hexdigest() == (
        "1f705e3aaae0a06eefa1695b2a2a9130c524eb1bb3930627781890876411a59b"
    )
    assert detector.STRUCTURED_PERSON_KEY_LABELS
    assert not any(label.isascii() for label in detector.PARTY_AND_TITLE_LABELS)
    for text in ("filename 우람", "surname 선우", "employer 강민"):
        assert all(match.kind != "PERSON" for match in detector.detect(text))


def test_key_classifier_exception_still_blocks_before_provider_send(monkeypatch):
    monkeypatch.setattr(
        privacy,
        "_person_label_for_key",
        lambda key: (_ for _ in ()).throw(RuntimeError("inspection error")),
    )
    monkeypatch.setattr(router_module, "estimate_call", lambda *args: (Decimal("0.01"), {}))
    sent = []

    class FakeProvider:
        name, available = "anthropic", True
        config = SimpleNamespace(name="anthropic", kind="cloud", model="fake", enabled=True)

        async def generate(self, request):
            sent.append(request)
            return LLMResponse(False, error="unused")

    ledger = SimpleNamespace(
        reserve=lambda *args, **kwargs: SimpleNamespace(id="reservation", amount=Decimal("0.01")),
        dispatch=lambda *args, **kwargs: None,
    )
    router = router_module.LLMRouter(providers={"anthropic": FakeProvider()}, ledger=ledger)
    request = LLMRequest(system="검토", user=json.dumps({"피고": "문서하"}, ensure_ascii=False))

    asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request))
    assert sent == []
