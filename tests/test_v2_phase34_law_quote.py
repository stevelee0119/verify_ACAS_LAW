"""v2 Phase 3·4: 법령 목록에 없는 법령(NOT_FOUND_LAW), 인용문 의미 변형(MODIFIED_QUOTE), 사건명·주어별 수치 대조."""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from packages.common.enums import AdapterStatus, CitationType, VerificationStatus
from packages.legal_engine import LegalVerifier
from packages.legal_engine.citation_extractor import extract_from_text
from packages.legal_engine.provision_content import compare_claim_to_provision
from packages.legal_engine.quote_diff import quote_changes
from packages.source_adapters.law_go_kr import LawGoKrAdapter
from packages.source_adapters.local_mirror import LocalLegalMirror

OFFICIAL = ("징계권자가 재량권의 행사로서 한 징계처분이 사회통념상 현저하게 타당성을 잃어 징계권자에게 맡겨진 "
            "재량권을 남용한 것이라고 인정되는 경우에 한하여 그 처분을 위법하다고 할 수 있다")


@pytest.fixture
def law(monkeypatch, tmp_path):
    adapter = LawGoKrAdapter(mirror=LocalLegalMirror(tmp_path / "empty"))
    monkeypatch.setattr(adapter, "status", lambda: AdapterStatus.READY)
    monkeypatch.setattr(LawGoKrAdapter, "api_key", property(lambda self: "TEST_OC"))
    return adapter


def test_law_missing_from_official_list_is_not_found_law(law, monkeypatch):
    rows = [{"법령명한글": "군인사법", "법령ID": "1", "법령일련번호": "10", "시행일자": "20200101"}]

    def request(url, *, params):
        return httpx.Response(200, json={"LawSearch": {"totalCnt": 1, "page": 1, "law": rows}},
                              request=httpx.Request("GET", url))
    monkeypatch.setattr(law, "_http_get", request)
    [citation] = [c for c in extract_from_text("군간부 징계절차에 관한 특례법 제8조는 초과 징계를 금지한다.")
                  if c.type == CitationType.STATUTE]
    result = LegalVerifier(SimpleNamespace(law=law)).verify_citations([citation], current_date="2026-09-24")
    verdict = result.data["verdicts"][0]
    assert verdict["status"] == "NOT_FOUND"
    [finding] = result.findings
    assert finding.confidence_features["verdict_label"] == "NOT_FOUND_LAW"
    assert finding.confidence_features["law_candidates"] == ["군인사법"]
    assert "부존재 확정 아님" in finding.detail


def test_deleted_degree_adverb_is_a_meaningful_quote_change():
    changed = quote_changes("징계권자가 재량권의 행사로서 한 징계처분이 사회통념상 타당성을 잃어 징계권자에게 맡겨진 "
                            "재량권을 남용한 것이라고 인정되는 경우", OFFICIAL)
    assert changed and changed["changes"][0]["kind"] == "DEGREE" and "현저" in changed["changes"][0]["text"]


def test_exact_or_boundary_only_differences_are_not_flagged():
    assert quote_changes("사회통념상 현저하게 타당성을 잃어 징계권자에게 맡겨진 재량권을 남용한 것", OFFICIAL) is None
    assert quote_changes("사회통념상 현저하게 타당성을 잃어, 징계권자에게 맡겨진 재량권을 남용한 것이라 인정되는 경우",
                         OFFICIAL) is None


def test_case_name_between_number_and_judgment_is_extracted():
    [citation] = extract_from_text("(대법원 2007. 9. 21. 선고 2006두20631 징계처분취소 판결)")
    assert citation.attributes["case_name"] == "징계처분취소"
    [en_banc] = extract_from_text("대법원 1995. 7. 11. 선고 94누4615 전원합의체 판결")
    assert "case_name" not in en_banc.attributes and en_banc.case_kind == "전원합의체 판결"


def test_numbers_are_compared_within_the_clause_of_the_same_subject():
    body = "정직은 그 기간 중 보수의 3분의 2를 감한다. 감봉은 그 기간 보수의 3분의 1을 감한다."
    assert compare_claim_to_provision("보수의 3분의 1을 감액", body, subject="정직")["status"] == "CONTRADICTED"
    assert compare_claim_to_provision("보수의 3분의 2를 감액", body, subject="정직")["status"] == "VERIFIED"
    assert compare_claim_to_provision("보수의 3분의 1을 감액", body, subject="감봉")["status"] == "VERIFIED"


def test_constitution_short_name_resolves_to_official_title():
    # 국가법령정보센터의 공식 제명은 '대한민국헌법'이다(https://www.law.go.kr/법령/대한민국헌법).
    # '헌법'으로 정확 일치 검색하면 목록에 없어 NOT_FOUND_LAW로 잘못 판정되던 실연동 결과(TC-04)의 재현.
    from packages.legal_engine.normalize import canonical_law_name
    assert canonical_law_name("헌법") == "대한민국헌법"
    assert canonical_law_name("대한민국 헌법") == "대한민국헌법"
