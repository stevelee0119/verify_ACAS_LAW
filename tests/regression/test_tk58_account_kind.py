"""TK-58: synthetic account/RRN examples, never copied from a matter document."""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from time import perf_counter
from types import SimpleNamespace

import pytest

from packages.common.enums import LLMRole
from packages.llm_router import router as router_module
from packages.llm_router.providers import LLMRequest, LLMResponse
from packages.pii_engine import PIIEngine, PseudonymStore, detector


SYNTHETIC_ACCOUNTS = [
    ("계좌번호: ", "357-8246-1357-92"),
    ("은행 ", "4682-1357-24689"),
    ("계좌 ", "579-246813-57924"),
    ("수협 ", "８２４·６１３５·７９２４·６８"),
    ("뱅크 ", "9357—2468—13579"),
    ("계좌번호: ", "357-\n8246-1357-92"),
    ("계좌: ", "4682−1357−24689"),
]
SYNTHETIC_RRNS = [
    ("번호 ", "730428-2345678"),
    ("계좌번호: ", "820911-3456789"),
    ("주민번호: ", "９９９９９９·９·２４６·８１３"),
    ("주민등록번호: ", "8 3\t0\n4 2 9—4 2 6 8 1 3 5"),
    ("번호 ", "940531-\n5678912"),
]


class TokenStore:
    def pseudonym_for(self, kind, value):
        return f"{kind}_synthetic"


@pytest.mark.parametrize("prefix,value", SYNTHETIC_ACCOUNTS)
def test_synthetic_accounts_keep_full_mask_span_and_change_kind(prefix, value):
    text = prefix + value + " 확인"
    result = PIIEngine(TokenStore()).mask_text(text)
    assert len(result.matches) == 1
    match = result.matches[0]
    assert match.kind == "ACCOUNT"
    assert text[match.start:match.end] == value
    assert result.masked_text == prefix + "[ACCOUNT_synthetic] 확인"


@pytest.mark.parametrize("prefix,value", SYNTHETIC_RRNS)
def test_synthetic_rrn_controls_keep_kind_and_full_mask_span(prefix, value):
    text = prefix + value + " 확인"
    result = PIIEngine(TokenStore()).mask_text(text)
    assert len(result.matches) == 1
    match = result.matches[0]
    assert match.kind == "RRN"
    assert text[match.start:match.end] == value
    assert result.masked_text == prefix + "[RRN_synthetic] 확인"


@pytest.mark.parametrize("prefix,value", [
    ("번호 ", "4682·1357·24689"),
    ("주민번호: ", "35782·4·6135792"),
    ("주민등록번호: ", "８２·４６·１３·５７９２４６８"),
])
def test_synthetic_ambiguous_identifiers_still_mask_without_rrn_claim(prefix, value):
    text = prefix + value + " 확인"
    result = PIIEngine(TokenStore()).mask_text(text)
    assert len(result.matches) == 1
    assert result.matches[0].kind == "PII"
    assert text[result.matches[0].start:result.matches[0].end] == value
    assert result.masked_text == prefix + "[PII_synthetic] 확인"


@pytest.mark.parametrize("value", ["357-8246-1357-92", "4682·1357·24689", "820911-3456789"])
@pytest.mark.parametrize("position", ["user", "system", "structured"])
def test_synthetic_identifiers_never_reach_provider(monkeypatch, value, position):
    monkeypatch.setattr(router_module, "estimate_call", lambda *args: (Decimal("0.01"), {}))
    sent = []

    class Provider:
        name, available = "anthropic", True
        config = SimpleNamespace(name="anthropic", kind="cloud", model="synthetic", enabled=True)

        async def generate(self, request):
            sent.append(request)
            return LLMResponse(True, text="확인", provider=self.name, model=self.config.model)

    ledger = SimpleNamespace(
        reserve=lambda *args, **kwargs: SimpleNamespace(id="synthetic", amount=Decimal("0.01")),
        dispatch=lambda *args, **kwargs: None,
        settle=lambda *args, **kwargs: None,
    )
    router = router_module.LLMRouter(providers={"anthropic": Provider()}, ledger=ledger)
    if position == "system":
        request = LLMRequest(system="계좌: " + value, user="확인")
    elif position == "structured":
        request = LLMRequest(system="확인", user=json.dumps({"계좌": value}, ensure_ascii=False))
    else:
        request = LLMRequest(system="확인", user="계좌: " + value)
    execution = asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request))
    assert sent == []
    assert execution.executions
    assert all(item.input_privacy.get("status") == "BLOCKED" for item in execution.executions)


def test_synthetic_generic_pii_uses_persistent_pseudonym(tmp_path):
    store = PseudonymStore("synthetic-tk58", root=tmp_path)
    result = PIIEngine(store).mask_text("번호 4682·1357·24689 확인")
    assert result.masked_text == "번호 [PII_001] 확인"
    assert store.original_for("PII_001") == "4682·1357·24689"


def test_synthetic_repeated_separator_input_is_fast():
    # Exercise the normalized matching/classification path on thousands of
    # synthetic candidates, isolating unrelated person/address detector costs.
    text = ("계좌: 4682·1357·24689 확인\n" * 2000)
    normalized, positions = detector._normalise_contact_view(text)
    start = perf_counter()
    matches = detector._contact_matches(text, normalized, positions, [], None, None)
    elapsed = perf_counter() - start
    assert len(matches) == 2000
    assert all(match.kind == "ACCOUNT" for match in matches)
    assert elapsed < 0.1
