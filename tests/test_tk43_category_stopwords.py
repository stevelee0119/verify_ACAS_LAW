"""Synthetic TK-43 nouns and names; no user briefs or evaluation inputs.

Each category has three independently specified noun controls and three
name examples with the same initial letters. They exercise both loss of names
and excess masking through detection, masking and the provider boundary.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from time import perf_counter
from types import SimpleNamespace

import pytest

from packages.common.enums import LLMRole
from packages.llm_router import privacy, router as router_module
from packages.llm_router.providers import LLMRequest, LLMResponse
from packages.pii_engine import PIIEngine, PseudonymStore, detect
from packages.pii_engine.detector import _is_category_person_stopword


# Synthetic examples chosen by category, not extracted from protected tests.
CATEGORY_EXAMPLES = [
    ("procedure", "서약", "서약윤"),
    ("procedure", "진정", "진정솔"),
    ("procedure", "구제", "구제린"),
    ("records", "서식", "서식윤"),
    ("records", "원본", "원본솔"),
    ("records", "명세", "명세린"),
    ("financial", "소득", "소득윤"),
    ("financial", "연금", "연금솔"),
    ("financial", "금융", "금융린"),
    ("identity", "신원", "신원윤"),
    ("identity", "신분", "신분솔"),
    ("identity", "성별", "성별린"),
    ("work", "이력", "이력윤"),
    ("work", "경력", "경력솔"),
    ("work", "연차", "연차린"),
]
LABELS = ["원고", "증인", "작성자", "수신자", "임차인", "보호자"]


@pytest.fixture
def engine(tmp_path):
    return PIIEngine(PseudonymStore("synthetic-tk43", root=tmp_path))


@pytest.mark.parametrize("category,noun,name", CATEGORY_EXAMPLES)
@pytest.mark.parametrize("label", LABELS)
@pytest.mark.parametrize("delimiter", [" ", ": ", "：", "\n"])
def test_complete_category_noun_field_stays_readable(engine, category, noun, name, label, delimiter):
    text = f"{label}{delimiter}{noun}: 확인 자료"
    assert not [m for m in detect(text) if m.kind == "PERSON"]
    assert engine.mask_text(text).masked_text == text
    assert privacy.inspect_request(LLMRequest(system="합성 자료 검토", user=text))["status"] == "PASSED"


@pytest.mark.parametrize("category,noun,name", CATEGORY_EXAMPLES)
@pytest.mark.parametrize("label", LABELS)
@pytest.mark.parametrize("style", ["plain", "spaced", "particle"])
def test_same_prefix_name_is_masked_and_raw_request_is_blocked(engine, category, noun, name, label, style):
    rendered = " ".join(name) if style == "spaced" else name
    suffix = "은" if style == "particle" else ""
    text = f"{label}: {rendered}{suffix}"
    masked = engine.mask_text(text).masked_text
    assert masked == f"{label}: [PERSON_001]{suffix}"
    assert privacy.inspect_request(LLMRequest(system="합성 자료 검토", user=text))["status"] == "BLOCKED"
    assert privacy.inspect_request(LLMRequest(system="합성 자료 검토", user=masked))["status"] == "PASSED"


@pytest.mark.parametrize("prefix", ["서약", "소득", "신원", "경력"])
@pytest.mark.parametrize("last", ["은", "이", "도"])
@pytest.mark.parametrize("label", ["원고", "작성자", "성명"])
@pytest.mark.parametrize("spacing", ["", " "])
def test_particle_like_name_syllable_is_not_discarded(engine, prefix, last, label, spacing):
    """Synthetic ambiguous stems remain masked, even without an outer particle."""
    name = prefix + last
    rendered = spacing.join(name)
    text = f"{label}: {rendered}"
    masked = engine.mask_text(text).masked_text
    assert masked == f"{label}: [PERSON_001]"
    assert privacy.inspect_request(LLMRequest(system="합성 자료 검토", user=text))["status"] == "BLOCKED"


@pytest.mark.parametrize("noun", ["신원", "진정", "경력"])
def test_explicit_name_field_with_noun_spelling_remains_private(engine, noun):
    text = f"성명: {noun}"
    assert engine.mask_text(text).masked_text == "성명: [PERSON_001]"
    assert privacy.inspect_request(LLMRequest(system=text, user="합성 자료 검토"))["status"] == "BLOCKED"


@pytest.mark.parametrize("position", ["system", "user"])
@pytest.mark.parametrize("noun,name", [("소득", "소득윤"), ("신분", "신분솔"), ("경력", "경력린")])
def test_router_keeps_nouns_and_blocks_raw_same_prefix_names(monkeypatch, engine, position, noun, name):
    """Synthetic cloud-provider double: both directions through LLMRouter.run."""
    sent = []
    monkeypatch.setattr(router_module, "estimate_call", lambda *args: (Decimal("0.01"), {}))

    class Provider:
        name, available = "anthropic", True
        config = SimpleNamespace(name="anthropic", kind="cloud", model="fake", enabled=True)

        async def generate(self, request):
            sent.append(request)
            return LLMResponse(True, text="확인", provider=self.name, model=self.config.model)

    ledger = SimpleNamespace(
        reserve=lambda *args, **kwargs: SimpleNamespace(id="r", amount=Decimal("0.01")),
        dispatch=lambda *args, **kwargs: None,
        settle=lambda *args, **kwargs: None,
    )
    router = router_module.LLMRouter(providers={"anthropic": Provider()}, ledger=ledger)

    def run(text):
        request = LLMRequest(system=text if position == "system" else "합성 자료 검토",
                             user=text if position == "user" else "합성 자료 검토")
        asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request))

    normal = f"작성자: {noun}: 확인 자료"
    run(normal)
    assert len(sent) == 1
    assert normal in getattr(sent[0], position)
    raw = f"작성자: {name}"
    run(raw)
    assert len(sent) == 1
    run(engine.mask_text(raw).masked_text)
    assert len(sent) == 2
    assert all(name not in request.system + request.user for request in sent)


def test_category_candidate_repeated_input_time():
    """Synthetic 6,000 calls time the new path, excluding unchanged scanners."""
    candidates = [
        ("소득", False, True), ("경력", False, True), ("신분", False, True),
        ("신원은", False, False), ("소득윤", False, False), ("신원", True, False),
    ] * 1000
    started = perf_counter()
    results = [_is_category_person_stopword(value, explicit_name=explicit)
               for value, explicit, _ in candidates]
    elapsed = perf_counter() - started
    assert results == [expected for _, _, expected in candidates]
    print(f"TK-43 supplemental path 6,000 synthetic candidates: {elapsed:.6f}s")
    assert elapsed < 0.1
