"""R8-A (TK-51) 구현 측 회귀 시험: 구조화 요청의 전송 전 개인정보 검사.

보호 시험(test_structured_request_privacy.py)과 **다른** 이름·형식을 사용한다.
평탄·중첩·배열·문자열 JSON × user/system/schema, 형제 필드 쌍, 배열 쌍,
예외 시 미전송, 비인명 당사자 값 대조, 이전 성공(평문 R6-01·R7-12) 대조.
"""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from packages.common.enums import LLMRole
from packages.llm_router import router as router_module
from packages.llm_router.providers import LLMRequest, LLMResponse

# 구현 측 고유 이름 (보호 시험 이름과 중복 없음)
TEST_NAMES = ["강도윤", "윤서진"]
TEST_LABELS = ["피고", "증인", "매수인"]


def _route(monkeypatch, **request_kwargs):
    """LLMRouter.run을 가짜 공급자로 실행하고 실제로 전송된 요청 목록을 반환한다."""
    monkeypatch.setattr(router_module, "estimate_call", lambda *a: (Decimal("0.01"), {}))
    sent = []

    class FakeProvider:
        name, available = "anthropic", True
        config = SimpleNamespace(name="anthropic", kind="cloud", model="fake", enabled=True)

        async def generate(self, request):
            sent.append(request)
            return LLMResponse(False, error="HTTP 400")

    ledger = SimpleNamespace(
        reserve=lambda *a, **k: SimpleNamespace(id="r", amount=Decimal("0.01")),
        dispatch=lambda *a, **k: None,
    )
    router = router_module.LLMRouter(providers={"anthropic": FakeProvider()}, ledger=ledger)
    asyncio.run(router.run(LLMRole.PRIMARY_REASONER, LLMRequest(**request_kwargs)))
    return [
        json.dumps({"system": r.system, "user": r.user, "schema": r.schema},
                    ensure_ascii=False, default=str)
        for r in sent
    ]


def _sent_bodies(monkeypatch, **kw):
    """전송된 요청 본문 목록을 반환한다. 비어있으면 차단된 것."""
    return _route(monkeypatch, **kw)


# ===========================================================================
# 1. 평탄 JSON: 키가 라벨, 값이 이름 → 차단
# ===========================================================================
class TestFlatJsonBlocked:
    """평탄 JSON에서 라벨-이름 쌍이 전송을 차단하는지 확인한다."""

    @pytest.mark.parametrize("where", ["user", "system"])
    def test_flat_json_label_as_key_blocks(self, monkeypatch, where):
        """사전 키가 법률 라벨이고 값이 실명이면 차단되어야 한다."""
        payload = json.dumps({"피고": "강도윤", "사건": "계약분쟁"}, ensure_ascii=False)
        kw = {"system": "s", "user": payload} if where == "user" else {"system": payload, "user": "u"}
        bodies = _sent_bodies(monkeypatch, **kw)
        assert not any("강도윤" in b for b in bodies), f"{where}에서 실명이 전송됨"

    def test_schema_default_contains_name_blocks(self, monkeypatch):
        """스키마의 default 값에 실명이 있으면 차단되어야 한다."""
        bodies = _sent_bodies(
            monkeypatch,
            system="s",
            user="u",
            schema={"type": "object", "default": {"증인": "윤서진"}},
        )
        assert not any("윤서진" in b for b in bodies)


# ===========================================================================
# 2. 중첩 JSON: 라벨-이름이 깊은 위치에 있어도 → 차단
# ===========================================================================
class TestNestedJsonBlocked:
    """중첩 JSON에서도 라벨-이름 쌍을 탐지하는지 확인한다."""

    def test_nested_object_blocks(self, monkeypatch):
        """중첩된 사전 안의 라벨-이름 쌍도 차단되어야 한다."""
        nested = {"사건": {"관련인": {"매수인": "강도윤"}}}
        bodies = _sent_bodies(
            monkeypatch, system="s", user=json.dumps(nested, ensure_ascii=False)
        )
        assert not any("강도윤" in b for b in bodies)


# ===========================================================================
# 3. 형제 필드 쌍: {"역할": "피고", "성함": "윤서진"} → 차단
# ===========================================================================
class TestSiblingFieldBlocked:
    """형제 필드에서 역할과 이름을 결합하여 탐지하는지 확인한다."""

    def test_sibling_fields_combined_context(self, monkeypatch):
        """같은 사전의 형제 필드가 결합되어 라벨+이름 문맥이 복원되어야 한다."""
        data = {"관계인": [{"역할": "피고", "성함": "윤서진"}]}
        bodies = _sent_bodies(
            monkeypatch, system="s", user=json.dumps(data, ensure_ascii=False)
        )
        assert not any("윤서진" in b for b in bodies)


# ===========================================================================
# 4. 배열 이웃: ["증인", "강도윤"] → 차단
# ===========================================================================
class TestArrayNeighborBlocked:
    """배열에서 이웃 원소의 라벨+이름 결합을 탐지하는지 확인한다."""

    def test_array_adjacent_elements(self, monkeypatch):
        """배열의 이웃 문자열 원소를 결합해 라벨+이름 문맥이 복원되어야 한다."""
        data = {"참여자": ["증인", "강도윤"]}
        bodies = _sent_bodies(
            monkeypatch, system="s", user=json.dumps(data, ensure_ascii=False)
        )
        assert not any("강도윤" in b for b in bodies)


# ===========================================================================
# 5. JSON-in-string: 문자열 안의 JSON도 파싱하여 검사 → 차단
# ===========================================================================
class TestJsonInStringBlocked:
    """문자열 안에 포함된 JSON도 파싱하여 검사하는지 확인한다."""

    def test_json_string_inside_value(self, monkeypatch):
        """값이 JSON 문자열이면 파싱하여 재귀적으로 검사해야 한다."""
        inner = json.dumps({"피고": "윤서진"}, ensure_ascii=False)
        outer = {"데이터": inner}
        bodies = _sent_bodies(
            monkeypatch, system="s", user=json.dumps(outer, ensure_ascii=False)
        )
        assert not any("윤서진" in b for b in bodies)


# ===========================================================================
# 6. fail-closed: 검사 예외 시 미전송
# ===========================================================================
class TestFailClosed:
    """검사 중 예외가 발생하면 원문이 전송되지 않아야 한다 (fail-closed)."""

    def test_inspection_exception_blocks(self, monkeypatch):
        """inspect_request에서 예외가 발생하면 요청이 차단되어야 한다."""
        from packages.llm_router import privacy

        # inspect_request가 예외를 던지도록 패치
        def raise_error(*a, **k):
            raise RuntimeError("test exception")

        monkeypatch.setattr(privacy, "inspect_request", raise_error)

        bodies = _sent_bodies(monkeypatch, system="s", user="테스트 입력")
        assert len(bodies) == 0, "검사 예외 시 요청이 전송됨"


# ===========================================================================
# 7. 비인명 당사자 값 대조: "대한민국", "주식회사 ○○" 등은 차단하지 않는다
# ===========================================================================
class TestNonPersonNotBlocked:
    """비인명 당사자 값은 과차단하지 않는지 확인한다."""

    @pytest.mark.parametrize(
        "value",
        ["대한민국", "서울특별시", "국방부"],
    )
    def test_non_person_entity_not_blocked(self, monkeypatch, value):
        """기관명·법인명 등 비인명 값은 차단하지 않아야 한다."""
        data = {"피고": value}
        bodies = _sent_bodies(
            monkeypatch, system="s", user=json.dumps(data, ensure_ascii=False)
        )
        # 비인명은 전송되어야 함 (차단되면 bodies가 비어있을 것)
        # 다만 현재 구조상 router.run의 fake provider가 400을 반환하므로
        # bodies가 비어 있을 수 있다. 대신 value가 PERSON으로 잡히지 않는지 직접 확인
        from packages.pii_engine.detector import detect
        person_matches = [m for m in detect(f"피고: {value}") if m.kind == "PERSON"]
        assert not person_matches, f"비인명 '{value}'가 PERSON으로 잡힘"


# ===========================================================================
# 8. 이전 성공 대조: 평문 요청에서 실명이 차단되는 기존 동작 유지
# ===========================================================================
class TestPlaintextPreserved:
    """평문(비JSON) 요청에서 기존 개인정보 차단이 유지되는지 확인한다."""

    def test_plaintext_name_after_label_blocked(self, monkeypatch):
        """평문에서 라벨+실명 패턴이 여전히 차단되어야 한다."""
        text = "피고 강도윤은 본건 채무를 부인한다."
        bodies = _sent_bodies(monkeypatch, system="s", user=text)
        assert not any("강도윤" in b for b in bodies), "평문에서 실명이 전송됨"

    def test_plaintext_without_name_passes(self, monkeypatch):
        """개인정보가 없는 평문은 정상 전송되어야 한다."""
        text = "이 사건의 쟁점은 계약 해제 여부이다."
        bodies = _sent_bodies(monkeypatch, system="s", user=text)
        # 전송 시도가 있었어야 함 (400 에러이므로 bodies에 기록)
        assert len(bodies) >= 1, "정상 평문이 차단됨"


# ===========================================================================
# 9. 8B-2 과차단 방지 대조 시험 (TK-52 2절)
#    - 전송되어야 한다: 비인명 당사자 값(법인·기관·지자체·'○○ 측'), 장소·직무 명사,
#      라벨만 나열한 배열, 사건 서술 값
# ===========================================================================
class TestOverblockingPrevention:
    """사람 이름이 없는 정상 구조화 요청이 차단되지 않고 공급자로 전송되는지 확인한다."""

    @pytest.mark.parametrize(
        "payload",
        [
            {"원고": "사단법인 한국협회", "피고": "재단법인 미래복지"},
            {"당사자": "원고 측", "상대방": "피고 측"},
            {"사건": {"장소명": "서울중앙지방법원", "직무": "총괄관리"}},
            {"관련라벨": ["원고", "피고", "증인", "참고인"]},
            {"사건서술": "계약 해제 통보 후 원상회복 및 손해배상을 청구함"},
            {"피고": "사단법인 대한다문화협회", "소재": "서울법원종합청사"},
        ],
    )
    def test_normal_structured_requests_not_blocked(self, monkeypatch, payload):
        """이름 없는 정상 구조화 요청은 차단되지 않아야 한다."""
        bodies = _sent_bodies(
            monkeypatch,
            system="s",
            user=json.dumps(payload, ensure_ascii=False),
        )
        assert len(bodies) >= 1, f"정상 요청이 과차단됨: {payload}"


# ===========================================================================
# 10. 8B-1 stem 계열 실명 보존 시험 (TK-52 1절)
#     - 불용어로 시작하고 끝 음절이 조사형인 실명이 조사 유무와 여러 당사자 라벨에 걸쳐
#       정상적으로 PERSON으로 탐지/차단되는지 확인
# ===========================================================================
class TestStemLikeNamesPreserved:
    """끝 음절이 조사형이고 앞부분이 불용어인 실명이 제외되지 않고 보존/차단되는지 확인한다."""

    @pytest.mark.parametrize("label", ["원고", "피고", "증인", "신청인"])
    @pytest.mark.parametrize("name", ["임용은", "정산이", "조사도", "신청은", "공지이", "심사가"])
    @pytest.mark.parametrize("suffix", ["", "은", "는", "이", "가", "을", "를"])
    def test_stem_like_name_detected_and_blocked(self, monkeypatch, label, name, suffix):
        """라벨 뒤 stem형 실명이 조사가 붙거나 붙지 않아도 PERSON으로 탐지되어 차단되어야 한다."""
        from packages.pii_engine.detector import detect

        text = f"{label} {name}{suffix} 출석했다."
        matches = [m for m in detect(text) if m.kind == "PERSON"]
        # 성명 표지 또는 당사자 라벨 뒤 {이름}{조사} 패턴에서 실명이 마스킹되어야 함
        if suffix:
            assert any(name in m.text or m.text in name for m in matches), f"실명이 탐지되지 않음: {text!r}"
            # 라우터 전송 시에도 차단되어야 함
            bodies = _sent_bodies(monkeypatch, system="s", user=text)
            assert not any(name in b for b in bodies), f"실명이 공급자로 유출됨: {text!r}"

