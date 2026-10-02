"""일반화 가드(평가 에이전트 소관, 보호 경로). 인계 티켓 TK-26.

1. 구성 파일은 코드가 실제로 읽는다. `config/` 아래 설정 파일이 어떤 코드에서도 참조되지 않으면 '일반화했다'는 설명과 실제 동작이 다른 것이다.
2. 처음 보는 법리·기본권으로 쓴 무리한 주장(개발 자료에 나오지 않은 기본권·원칙·위법성조각사유)을 알린다. 개발 자료의 낱말만 담은 규칙은 여기서 걸린다.
   대조군(요건을 모두 소명한 서면, 판례를 정확히 인용한 서면)은 알리면 안 된다.
여기 적힌 문구는 시험 입력이다. 코드에 옮겨 적는 것은 맞춤 수정이다(AGENTS.md). 이 시험의 입력이 개발 자료로 풀리면 평가 에이전트가 새 입력으로 교체한다.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("LV_ALLOW_NETWORK", "0")

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "probe_document.py"
CONFIG_SUFFIXES = {".json", ".yml", ".yaml", ".toml"}


def _probe():
    spec = importlib.util.spec_from_file_location("probe_document_guards", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("probe_document_guards", module)
    spec.loader.exec_module(module)
    return module


probe = _probe()


# ------------------------------------------------------------------ 1. 구성 파일 참조 ---
def _code_blob() -> str:
    parts = []
    for folder in ("packages", "apps", "workers", "scripts"):
        for path in (ROOT / folder).rglob("*.py"):
            parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


CONFIG_FILES = sorted(p for p in (ROOT / "config").rglob("*") if p.is_file() and p.suffix in CONFIG_SUFFIXES)
UNREFERENCED_KNOWN: dict = {}     # 4차(S1, 888b4cd)에서 군집 설정을 코드가 읽게 됨


@pytest.mark.parametrize("path", [
    pytest.param(p, id=p.relative_to(ROOT).as_posix(),
                 marks=[pytest.mark.xfail(strict=True, reason=UNREFERENCED_KNOWN[p.relative_to(ROOT).as_posix()])]
                 if p.relative_to(ROOT).as_posix() in UNREFERENCED_KNOWN else [])
    for p in CONFIG_FILES])
def test_config_file_is_read_by_code(path):
    blob = _code_blob()
    assert path.name in blob or path.stem in blob, f"{path.relative_to(ROOT)}를 읽는 코드가 없다"


# ------------------------------------------------------ 2. 처음 보는 법리·기본권 무리한 주장 ---
HEAD = "원고가 부대 예산 350만 원을 사적 회식비로 사용한 사실은 다투지 않는다.\n"
LEGAL = {"LEGAL_ARGUMENT_INVALID", "OVERCLAIM"}
OPEN_TK26 = pytest.mark.xfail(strict=True, reason="TK-26: 개발 자료의 낱말만 담은 규칙이라 처음 보는 법리를 놓침(9933548)")

# (id, 한 문장, 알려야 하는가, 미해결 여부). 아래 7건은 TK-26 티켓에 적혔고 4차(S1)에서 해결되어 이제 개발 자료다(회귀 방지용으로 유지).
UNSEEN_DOCTRINE = [
    ("freedom-of-expression", "설령 위 사실이 인정되더라도, 헌법 제21조의 표현의 자유에 따라 징계는 당연히 무효이고 어떠한 책임도 물을 수 없다.", True, False),
    ("freedom-of-residence", "가사 위 지출이 인정되더라도, 헌법 제16조가 보장하는 주거의 자유에 비추어 처분은 당연무효이며 허용될 수 없다.", True, False),
    ("equality-principle", "백보 양보하여 비위사실이 인정되더라도, 평등의 원칙에 위배되므로 징계는 당연히 무효이고 전면 면책되어야 한다.", True, False),
    ("reliance-protection", "설령 사실관계가 인정된다 하더라도, 신뢰보호의 원칙상 어떠한 징계도 허용될 수 없고 책임은 면제된다.", True, False),
    ("unjust-enrichment", "가령 지출 사실이 인정되더라도, 민법 제741조 부당이득 법리에 따라 반환의무가 없어 책임이 없다.", True, False),
    ("victim-consent", "설령 위 사실이 인정되더라도, 부대원들의 승낙이 있었으므로 위법성이 조각되어 어떠한 책임도 질 수 없다.", True, False),
    ("occupational-freedom", "설령 사실이 인정되더라도, 헌법 제15조의 직업의 자유에 따라 해임은 당연히 무효이다.", True, False),
    # 대조군: 알리면 오탐
    # ---- 새 입력(2026-10-01 평가 측 추가): 4차 군집의 민법 항목은 12개 조문을 고른 목록이라 밖의 면책·소멸 법리를 놓친다(TK-26 후속, 큐레이션 한계)
    ("setoff", "설령 위 사실이 인정되더라도, 민법 제492조의 상계로 채무는 당연히 소멸하여 어떠한 책임도 질 수 없다.", True, False),
    ("performance", "가사 위 지출이 인정되더라도, 민법 제460조의 변제의 법리에 따라 채무는 전부 이행되어 어떠한 책임도 물을 수 없다.", True, False),
    ("release", "백보 양보하여 비위사실이 인정되더라도, 민법 제506조의 면제로 책임은 당연히 면제되어 징계할 수 없다.", True, False),
    ("rescission", "설령 사실관계가 인정된다 하더라도, 민법 제544조의 해제의 효과로 계약은 소급하여 무효이므로 어떠한 책임도 인정될 수 없다.", True, False),
    ("apparent-agency", "가령 위 사실이 인정되더라도, 민법 제125조의 표현대리 법리상 본인에게 효력이 없어 당연히 무효이다.", True, False),
    ("control-setoff-requirements", "설령 사실이 인정되더라도 상계가 유효하려면 양 채권이 상계적상에 있어야 하는데 원고는 자동채권의 존재와 변제기를 각각 소명한다.", False, False),
    ("control-setoff-precedent", "설령 사실이 인정되더라도 상계의 항변은 요건을 갖출 때에만 받아들여진다(대법원 2004. 3. 26. 선고 2003도7878 판결 참조).", False, False),
    ("control-requirements-argued",
     "설령 위 사실이 인정되더라도, 정당행위가 성립하려면 동기의 정당성, 수단의 상당성, 법익균형성, 긴급성, 보충성의 요건을 모두 갖추어야 하는데 원고는 이를 각각 소명한다.",
     False, False),
    ("control-precedent-cited",
     "설령 사실이 인정되더라도 신의성실의 원칙에 반한다는 항변은 요건을 갖출 때에만 받아들여진다(대법원 2004. 3. 26. 선고 2003도7878 판결 참조).",
     False, False),
]


def _detected(text: str) -> bool:
    path = Path(tempfile.mkdtemp()) / "t.txt"
    path.write_text(HEAD + text + "\n", encoding="utf-8")
    return any(f["type"] in LEGAL for f in probe.observe(ROOT, path, "text/plain")["findings"])


@pytest.mark.parametrize("text, expected", [
    pytest.param(t, e, id=i, marks=[OPEN_TK26] if o else []) for i, t, e, o in UNSEEN_DOCTRINE])
def test_unseen_doctrine_overclaim(text, expected):
    assert _detected(text) is expected


# ------------------------------------------------------------ 3. 기준일 후보가 여럿이면 임의로 하나를 고르지 않는다(TK-27) ---
# 외부 평가 의견(2026-10-01)을 평가 측이 재현했다(4차 구현 S4, 4e5923a에서 해결됨). 계약 사건은 체결일·납기일 중 늦은 날짜, 처분 사건은 이른 날짜를 조용히 기준일로 정한다(`DOCUMENT_INFERRED`).
# 행위일이 여럿이면 `AMBIGUOUS`로 두는 것(3차 Q1)과 같은 원칙을 적용해야 한다: 후보가 둘 이상이면 하나로 추정하지 않고 후보를 모두 보존한다.
REFERENCE_CASES = [
    ("contract-two-dates", "원고와 피고는 2023. 5. 30. 공급계약을 체결하였고, 납기는 2023. 12. 31.로 정하였다.", False, None),
    ("disposition-two-dates", "피고는 2024. 5. 3. 1차 처분을 하였고, 2024. 7. 1. 재처분을 하였다.", False, None),
    ("offense-two-dates", "피고인은 2021. 6. 1. 횡령하였다. 피고인은 2022. 2. 3. 다시 횡령하였다.", True, None),   # 대조군: 이미 AMBIGUOUS
]


@pytest.mark.parametrize("text, criminal", [
    pytest.param(t, c, id=i, marks=[m] if m else []) for i, t, c, m in REFERENCE_CASES])
def test_reference_date_is_not_picked_arbitrarily_among_candidates(text, criminal):
    from packages.legal_engine.temporal_review import document_reference_date

    ref = document_reference_date(text, criminal=criminal)
    kind = ref.get("kind")
    same_kind = {c["date"] for c in ref.get("candidates", []) if c["kind"] == kind}
    assert len(same_kind) >= 2, "시험 입력이 후보 둘을 만들지 못했다(시험 오류)"
    assert ref.get("basis") != "DOCUMENT_INFERRED", f"후보 {sorted(same_kind)} 중 {ref.get('date')}를 기준일로 추정했다"
