"""5차(c223f7b) 독립 감사 Astra가 찾고 평가 측이 재현한 새 회귀의 고정 시험(평가 에이전트 소관, 보호 경로).

기준은 4차 e6b58fd다. 아래 시험은 4차에서 통과하던 것이 5차에서 깨졌거나(TK-30·TK-31), 5차의 확장 때문에 정상 입력의 오탐이 생긴 것(TK-32)이다.
6차 구현(01070f6)에서 22건이 해결되어 평가 에이전트가 strict xfail 표시를 지웠다(2026-10-03 승격). 이제 일반 시험이다. 이 파일의 입력은 합성 시험 입력이며 실재 인물·사건과 무관하다.
여기 적힌 이름·문장을 코드·설정에 옮겨 적는 것은 맞춤 수정이다(AGENTS.md). 구조(이름 후보의 형태·문맥, 겹치는 마스킹 구간의 우선순위, 줄 결합의 단어 경계 판정,
요건 제시 여부와 결론 범위)를 고쳐야 한다.

- TK-30(개인정보): 이름 마스킹 행렬 5,400조합에서 4차에 성공하던 40조합이 5차에서 실패(평가 측), Astra는 1,000조합에서 42조합. 이름이 `기`로 끝나는 후보 배제,
  조사 분리가 먼저 적용되어 마지막 글자가 남는 경우. 정상 안내문 `개인정보 성명 연락처를 출력하지 마시오.`가 새로 PERSON으로 오인된다.
- TK-31(입력 계층): PDF 줄 끝 `(대`와 다음 줄 `법원`이 `(대 법원`이 되어 법원명·선고일을 잃는다(TC-06, 고정 시험 dev 81.7 → 81.2). 어절 중간에 공백이 끼는 다른 사례도 있다.
- TK-32(법리): 요건을 제시하고 결론을 해당 채무로 한정한 정상 항변이 '요건 없는 과대주장'으로 표시된다. Astra는 정상 10건 중 5건, 평가 측 표본(13건)은 1건이다.
  비율은 문장 표현에 크게 의존하므로 개수보다 구조(요건 제시 + 한정된 결론은 알리지 않는다)를 본다.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("LV_ALLOW_NETWORK", "0")

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "probe_document.py"
TC06 = ROOT / "tests" / "fixtures" / "legal_verifier_testset" / "TC-06.pdf"


def _probe():
    spec = importlib.util.spec_from_file_location("probe_document_round5", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("probe_document_round5", module)
    spec.loader.exec_module(module)
    return module


probe = _probe()
TOKEN = re.compile(r"\[[A-Z_]+_\d+\]")              # 모든 종류의 가림 토큰
PERSON_TOKEN = re.compile(r"\[PERSON_\d+\]")        # 이름 자리에는 PERSON 토큰만 인정한다(6차 감사 지적: 전화번호 토큰이 이름 자리에 있어도 통과했다)


def _engine():
    from packages.pii_engine import PIIEngine, PseudonymStore
    return PIIEngine(PseudonymStore("round5", root=Path(tempfile.mkdtemp(prefix="round5_pii_"))))


def _clean(text: str) -> str:
    """PERSON 토큰은 T로, 다른 종류의 토큰은 X로 바꾸고 공백과 구분 기호는 지운다(이름 자리에 다른 종류 토큰이 있으면 기대와 달라진다)."""
    return re.sub(r"[\s:：/\-]", "", TOKEN.sub("X", PERSON_TOKEN.sub("T", text)))


def fully_masked(label_format: str, name: str) -> bool:
    """줄 하나가 `라벨 + 토큰`만 남도록 이름 전체 문자가 마스킹됐는가(이름 문자열이 사라지는 것만으로는 부족하다. 마지막 글자가 남는 것을 잡는다)."""
    line = label_format.format(n=name)
    masked = _engine().mask_text(line + "\n다음과 같이 주장한다.").masked_text.split("\n")[0]
    expected = _clean(label_format.format(n="T"))
    return _clean(masked) == expected


# (이름, 줄 서식, 상태). 상태 30 = 4차(e6b58fd)에서 통과하다 5차에서 깨짐, 28 = 4차에도 실패(기존 미해결), 0 = 5차에서 통과(회귀 방지 짝).
NAME_REGRESSIONS = [
    ("김민기", "성명: {n}", 30), ("김민기", "성명 {n}", 30), ("김민기", "청구인 {n}", 30),
    ("노은기", "성명: {n}", 30), ("노은기", "청구인 {n}", 30),
    ("문하기", "성명: {n}", 30), ("문하기", "청구인 {n}", 30),
    ("김하은", "원고 {n}", 30), ("김하은", "피고 {n}", 30), ("김하은", "피고인 {n}", 30),
    ("김하은", "신청인 {n}", 30), ("김하은", "청구인 {n}", 30), ("김하은", "성명: {n}", 30),
    ("윤하기", "원  고   {n}", 30),                       # 라벨 안 공백이 여럿: 4차는 마스킹, 5차는 그대로
    ("윤하기", "원고: {n}", 28), ("윤하기", "원 고: {n}", 28), ("류채은", "원 고 : {n}", 28),   # 기 끝 이름·띄어쓴 라벨+콜론: 4차도 실패, 5차는 마지막 글자가 남기도 함
    ("김민기", "원고 {n}", 0), ("이서준", "성명 {n}", 0), ("박지훈", "청구인 {n}", 0), ("한유진", "성명: {n}", 0),
    ("노가온", "증 인 : {n}", 0), ("서하윤", "청 구 인: {n}", 0),
]


@pytest.mark.parametrize("name, label_format", [
    pytest.param(n, f, id=f"{f.format(n=n)}") for n, f, o in NAME_REGRESSIONS])
def test_name_is_fully_masked_with_no_remaining_characters(name, label_format):
    assert fully_masked(label_format, name), f"{label_format.format(n=name)}: 이름 문자 일부가 남았거나 이름이 그대로 남았다"


def _person_flagged(text: str) -> bool:
    return bool(PERSON_TOKEN.search(_engine().mask_text(text).masked_text))


@pytest.mark.parametrize("text", [
    pytest.param("개인정보 성명 연락처를 출력하지 마시오.", id="privacy-instruction"),
    pytest.param("피고인 신문 절차가 진행되었다.", id="defendant-examination"),
    pytest.param("원고는 피고에게 금전의 지급을 구한다.", id="plain-claim"),
    pytest.param("청구취지 및 청구원인은 별지와 같다.", id="annex-reference"),
    pytest.param("성명 불상의 직원이 현장에 있었다고 주장한다.", id="unknown-name"),
    pytest.param("증인은 법정에서 선서하였다.", id="witness-oath"),
    pytest.param("재판부는 변론을 종결하였다.", id="court-closes"),
])
def test_ordinary_sentences_are_not_treated_as_person_names(text):
    assert not _person_flagged(text), f"정상 문장이 PERSON으로 마스킹됐다: {text}"


# ------------------------------------------------------------------------------ TK-31: PDF 줄 결합 ---
def _tc06():
    from packages.document_engine.registry import parse_document
    return parse_document(str(TC06), document_id="tc06", filename=TC06.name, mime_type="application/pdf", sha256="x")


def test_court_and_date_survive_a_line_break_inside_the_court_name():
    """TC-06은 `(대`와 `법원`이 줄바꿈으로 갈라진다. 4차는 법원명·선고일을 추출했고 5차는 사건번호만 남겼다."""
    from packages.legal_engine.citation_extractor import extract_citations

    found = [c for c in extract_citations(_tc06()) if getattr(c, "case_number", None) == "2006두16274"]
    assert found, "사건번호를 추출하지 못했다"
    assert found[0].court == "대법원" and str(found[0].decision_date) == "2007-12-21"


def test_no_space_is_inserted_inside_a_word_at_a_line_break():
    """같은 PDF의 글자 단위 줄바꿈 자리에서 어절 한가운데에 공백이 끼면 안 된다(5차 블록 텍스트에 `처 분을`, `대하 여`가 생겼다)."""
    blocks = "\n".join(b.text for p in _tc06().pages for b in p.blocks)
    for fragment in ("처 분을", "대하 여"):
        assert fragment not in blocks, f"어절 중간에 공백이 들어갔다: {fragment!r}"


# ------------------------------------------------------------------------------ TK-32: 정상 항변 오탐 ---
HEAD = "원고가 부대 예산 350만 원을 사적 회식비로 사용한 사실은 다투지 않는다.\n"
LEGAL = {"LEGAL_ARGUMENT_INVALID", "OVERCLAIM"}
# 대조군: 요건을 구체적으로 제시하고 결론이 해당 채무로 한정됐다(합성). 알리면 오탐이다.
NORMAL_DEFENSES = [
    ("setoff-limited", "설령 원고의 청구원인 사실이 인정되더라도, 피고의 반대채권은 변제기가 도래하였고 상계 금지 사유가 없으며 상계의 의사표시가 원고에게 도달하여 민법 제492조에 따라 원고의 대여금 채권 전부가 소멸하였으므로, 피고는 이 사건 대여금 채무에 관하여 더 이상 책임을 질 수 없다.", False),
    ("performance-limited", "가사 원고의 주장 사실이 인정되더라도, 피고는 2023. 5. 2. 원고에게 이 사건 채무 원리금 전액을 지급하였고 원고가 이를 수령하였으므로 민법 제460조의 변제로 위 채무가 소멸하여 피고는 이 사건 채무에 관한 책임을 질 수 없다.", False),
    ("release-limited", "백보 양보하여 원고 주장 채권이 존재하였더라도, 원고가 2022. 8. 1. 서면으로 이 사건 채무를 면제하는 의사표시를 하여 그 도달로 민법 제506조에 따라 채무가 소멸하였으므로 피고는 이 사건 채무를 이행할 책임이 없다.", False),
    ("deposit-limited", "설령 원고 주장이 인정되더라도, 피고가 채권자의 수령거절 후 유효하게 변제공탁을 하여 민법 제487조에 따라 이 사건 채무가 소멸하였으므로 피고는 이 사건 채무에 관한 책임을 질 수 없다.", True),
    ("confusion-limited", "설령 위 사실이 인정되더라도, 이 사건 채권과 채무가 2023. 4. 1. 동일인에게 귀속되어 민법 제507조에 따라 혼동으로 소멸하였고 제3자의 권리 목적도 아니므로 피고는 이 채무에 관한 책임을 질 수 없다.", False),
    ("setoff-plain", "피고는 원고에 대하여 2023. 3. 1. 변제기가 도래한 대여금 채권 1천만 원을 가지고 있고 쌍방 변제기가 도래하였으며 상계를 금지하는 특약이 없다. 피고가 2024. 1. 5. 상계의 의사표시를 하여 그 도달로 원고의 위 대여금 채권은 대등액에서 소멸하였다.", False),
    ("limitation", "설령 위 사실이 인정되더라도, 민법 제766조의 소멸시효 기간이 경과하였고 시효 중단 사유가 없으므로 그 청구권은 시효로 소멸하였다고 다툰다. 중단·정지 사유가 있다면 이를 소명하여야 한다.", False),
]


def _flagged(text: str) -> bool:
    path = Path(tempfile.mkdtemp()) / "t.txt"
    path.write_text(HEAD + text + "\n", encoding="utf-8")
    return any(f["type"] in LEGAL for f in probe.observe(ROOT, path, "text/plain")["findings"])


@pytest.mark.parametrize("text", [
    pytest.param(t, id=i) for i, t, o in NORMAL_DEFENSES])
def test_defense_with_stated_requirements_and_a_limited_conclusion_is_not_flagged(text):
    assert _flagged(text) is False


# ----------------------------------------------------------------------------- 평가 도구 자체 점검(6차 감사 반영) ---
class _StubEngine:
    def __init__(self, masked_text: str):
        self._masked = masked_text

    def mask_text(self, _line: str):
        return type("Masked", (), {"masked_text": self._masked})()


@pytest.mark.parametrize("masked, expected", [
    ("성명: [PERSON_001]\n다음과 같이 주장한다.", True),        # 이름 전체가 PERSON 토큰
    ("성명: [PHONE_001]\n다음과 같이 주장한다.", False),        # 이름 자리에 다른 종류 토큰: 이름이 가려진 것이 아니다
    ("성명: [PERSON_001]기\n다음과 같이 주장한다.", False),     # 마지막 글자가 남음
    ("성명: 김민기\n다음과 같이 주장한다.", False),             # 마스킹되지 않음
])
def test_fully_masked_oracle_only_accepts_a_person_token_in_the_name_slot(monkeypatch, masked, expected):
    monkeypatch.setattr(sys.modules[__name__], "_engine", lambda: _StubEngine(masked))
    assert fully_masked("성명: {n}", "김민기") is expected
