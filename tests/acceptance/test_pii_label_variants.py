"""당사자 이름 라벨 변형 시험(평가 에이전트 소관, 보호 경로). 인계 티켓 TK-28.

외부 독립 감사(Astra 4차, 2026-10-01)가 새 서면 3건에서 모두 이름 마스킹을 놓쳤다고 보고했고, 평가 측이 기준 코드(9933548)에서 재현·범위를 확정했다.
당사자 라벨(원고·피고인·청구인…) 뒤에 **공백이 아닌 구분자**(콜론·하이픈·괄호·전각 기호)가 오면 이름이 마스킹되지 않는다. 같은 문서의 `소송대리인 변호사: 이재현`은 마스킹된다.
평가 측 서면 6~9·변형 1·2는 라벨과 이름을 공백으로만 이어 써서 이 변형을 한 번도 시험하지 못했다(평가 측 변형 설계의 빈틈).
전송 전 검사(`llm_router.privacy.inspect_request`)도 같은 탐지기를 쓰므로, 마스킹되지 않은 이름은 외부 모델 전송 검사에서도 걸리지 않는다.

한 문서에 서로 다른 이름의 양성 줄을 모아 한 번 처리하고 줄마다 판정한다. 미해결은 strict xfail이다. 고치면 XPASS(strict)로 실패하므로 평가 에이전트가 표시를 지운다.
여기 적힌 이름은 시험 입력이다. 코드에 옮겨 적는 것은 맞춤 수정이다(AGENTS.md).
"""
from __future__ import annotations

import functools
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("LV_ALLOW_NETWORK", "0")

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "probe_document.py"
TICKET = "TK-28"


def _probe():
    spec = importlib.util.spec_from_file_location("probe_document_pii_labels", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("probe_document_pii_labels", module)
    spec.loader.exec_module(module)
    return module


probe = _probe()
OPEN = pytest.mark.xfail(strict=True, reason=f"{TICKET}: 당사자 라벨 뒤 구분자가 공백이 아니면 이름이 마스킹되지 않음(9933548)")

# (id, 이름, 줄 서식, 미해결 여부). 줄 서식의 {n}이 이름 자리. 이름 사이 공백은 서식이 아니라 이름 값에 넣는다.
POSITIVE = [
    ("space", "홍길동", "원고 {n}", False),
    ("tab", "김철수", "원고\t{n}", False),
    ("spaced-name", "박 영 희", "피고인 {n}", False),
    ("colon", "이민수", "원고: {n}", True),
    ("colon-spaced", "최지훈", "피고인 : {n}", True),
    ("hyphen", "정수진", "원고 - {n}", True),
    ("fullwidth-colon", "강하늘", "원고：{n}", True),
    ("fullwidth-slash", "조민재", "원고／{n}", True),
    ("bracket-label", "윤서연", "[원고] {n}", True),
    ("paren-name", "한지우", "원고({n})", True),
    ("claimant", "오세훈", "청구인: {n}", True),
    ("applicant", "임나래", "신청인: {n}", True),
    ("creditor", "문재원", "채권자: {n}", True),
    ("witness", "서도윤", "증인: {n}", True),
    ("victim", "백승아", "피해자: {n}", True),
    ("spaced-name-colon", "남 궁 민", "원고: {n}", True),
]
# 대조군: 이름이 아닌 값은 그대로 남아야 한다(마스킹하면 오탐).
CONTROLS = [
    ("state", "원고: 대한민국"),
    ("state-defendant", "피고: 대한민국"),
    ("see-annex", "원고: 별지 목록 기재와 같다"),
    ("innocent", "피고인: 무죄"),
    ("as-claimed", "원고: 청구취지 기재와 같다"),
    ("no-claim", "원고: 청구를 기각한다는 판결을 구한다"),
]
HEAD = "준 비 서 면\n사 건 2026가합0000 손해배상(기)\n"


@functools.lru_cache(maxsize=None)
def masked(kind: str) -> str:
    if kind == "positive":
        body = "\n".join(fmt.format(n=name) for _, name, fmt, _ in POSITIVE)
    else:
        body = "\n".join(text for _, text in CONTROLS)
    path = Path(tempfile.mkdtemp()) / "t.txt"
    path.write_text(HEAD + body + "\n청구취지는 다음과 같다.\n", encoding="utf-8")
    return probe.observe(ROOT, path, "text/plain")["masked_text"]


def _compact(text: str) -> str:
    return "".join(text.split())


@pytest.mark.parametrize("name", [
    pytest.param(name, id=i, marks=[OPEN] if open_ else []) for i, name, _, open_ in POSITIVE])
def test_party_name_is_masked_whatever_the_label_punctuation(name):
    assert _compact(name) not in _compact(masked("positive")), f"{name}이(가) 마스킹되지 않았다"


@pytest.mark.parametrize("text", [pytest.param(t, id=i) for i, t in CONTROLS])
def test_non_name_values_after_party_label_are_not_masked(text):
    assert _compact(text) in _compact(masked("control")), f"{text}이(가) 과잉 마스킹됐다"


def test_lawyer_name_after_colon_stays_masked():
    """현행 정책 유지: 소송대리인 변호사 성명은 마스킹한다(주소만 예외). 같은 콜론 서식이라도 변호사는 마스킹되는 현재 동작을 고정한다."""
    path = Path(tempfile.mkdtemp()) / "t.txt"
    path.write_text(HEAD + "소송대리인 변호사: 노하윤\n", encoding="utf-8")
    assert "노하윤" not in probe.observe(ROOT, path, "text/plain")["masked_text"]
