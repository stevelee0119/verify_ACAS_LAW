"""7차(4da3910) 독립 측정에서 새로 확인된 회귀와 미해결의 보호 시험 (평가 에이전트 소관, 구현 측은 수정하지 않는다).

근거: docs/scorecards/HISTORY.md 12절, docs/handoff/TK-42~TK-45. 시작 7adf43f에서 통과하던 것이 4da3910에서 실패하면 일반 시험(회귀),
시작에서도 실패하던 것은 strict xfail(해결되면 XPASS로 알려 평가 측이 표시를 지운다)이다.
입력은 평가 측이 새로 지었다. 비공개 변형(저장소 밖, G2 다·G10)의 입력은 여기에 옮기지 않는다 — 구현 측이 읽을 수 있기 때문이다.
이 시험의 입력도 구현 측은 복사해 맞추지 않는다(낱말 목록·분기로 맞추면 7차 지시서 금지 항목이다).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# R7-01 관리자 화면 스크립트가 불러올 때와 초기화에서 죽지 않는다 (회귀: 4da3910에서 `initialized is not defined`)
# ---------------------------------------------------------------------------
# admin.js가 app.js·workflow.js에서 가져다 쓰는 전역 도우미는 가짜로 둔다. 목록 밖의 이름을 쓰면 시험이 실패하므로
# 새 전역 의존이 생기면 평가 측이 이 목록을 갱신한다(선언이 지워진 변수와 구별하기 위한 것이다).
ADMIN_GLOBALS = ("button", "node", "$", "workflowUI", "iconButton", "icons")
ADMIN_SMOKE = r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[2], "utf8");
const globalsNeeded = JSON.parse(process.argv[3]);
function stub() {
  const h = {
    get(_t, p) { if (p === Symbol.toPrimitive) return () => ""; if (p === "then") return undefined; return new Proxy(function () {}, h); },
    set() { return true; }, apply() { return new Proxy(function () {}, h); }, construct() { return new Proxy(function () {}, h); },
  };
  return new Proxy(function () {}, h);
}
const loc = { _hash: "", get hash() { return this._hash; }, set hash(v) { this._hash = v; }, href: "" };
const sandbox = { document: stub(), window: { addEventListener() {} }, location: loc, console,
  fetch: async () => ({ ok: true, json: async () => ({}) }), setTimeout, clearTimeout, URLSearchParams };
for (const name of globalsNeeded) sandbox[name] = stub();
const ctx = vm.createContext(sandbox);
const steps = [["load", null], ["init", "adminUI.init()"],
  ["setIdentity", 'adminUI.setIdentity({user_id:"u1", role:"ADMIN", organization_id:"o1"})'],
  ["open", 'adminUI.open("users")'], ["open-proto", 'adminUI.open("__proto__")']];
const out = [];
for (const [name, code] of steps) {
  try { name === "load" ? vm.runInContext(src, ctx) : vm.runInContext(code, ctx); out.push([name, "ok"]); }
  catch (e) { out.push([name, `${e.name}: ${e.message}`]); }
}
console.log(JSON.stringify({ out, polluted: ({}).query !== undefined, hash: loc._hash }));
"""


def _run_admin_smoke():
    node = shutil.which("node")
    if not node:
        pytest.skip("node가 없어 관리자 화면 스크립트를 실행하지 못했다(CI는 node가 있다)")
    done = subprocess.run([node, "-e", ADMIN_SMOKE, "-", str(ROOT / "apps/web/static/admin.js"), json.dumps(ADMIN_GLOBALS)],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_admin_script_initializes_without_reference_errors():
    result = _run_admin_smoke()
    failed = [(name, status) for name, status in result["out"] if status != "ok"]
    assert not failed, (
        "관리자 화면 스크립트가 초기화 단계에서 실패한다 — 쪽 로드 때 operations.init()이 중단되어 사용자 관리 메뉴와 작업 제어가 만들어지지 않는다: "
        f"{failed}")


# 승격(2026-10-03, Round 7 종결): TK-37 관리자 탭·TK-43 라벨 어휘 확대·TK-45 '없으나' 요건 부정 — 61ef12f에서 통과해 strict xfail 표시를 지웠다
def test_admin_script_still_rejects_prototype_tab_names_and_keeps_object_prototype_clean():
    result = _run_admin_smoke()
    assert dict(result["out"]).get("open-proto") == "ok"
    assert result["polluted"] is False
    assert result["hash"] == "#admin/users"  # `#admin/__proto__`는 users 탭으로 돌아온다


# ---------------------------------------------------------------------------
# R7-02 당사자 라벨 뒤 일반 명사를 인명으로 가리지 않는다 (회귀: TK-39의 '라벨 직후 후보는 후행 문맥으로 제외하지 않음'이
# 성명 라벨뿐 아니라 원고·피고·증인 등 모든 라벨로 넓어져 '진술 조서'·'심문 기일'이 인명으로 잡힌다)
# ---------------------------------------------------------------------------
PARTY_LABELS = ["원고", "피고", "증인", "참고인", "피해자", "채무자"]
COMMON_NOUN_PHRASES = ["진술 조서는", "심문 기일은"]


def _person_text(text: str):
    from packages.pii_engine.detector import detect
    return [text[m.start:m.end] for m in detect(text)
            if "PERSON" in str(getattr(m, "type", None) or getattr(m, "pii_type", None) or getattr(m, "kind", None)).upper()]


# 승격(2026-10-03, 8차): 170c647에서 12건 모두 통과해 strict xfail 표시를 지웠다(사용자 결정: 과마스킹 일반화는 별도 트랙 TK-43)
@pytest.mark.parametrize("label", PARTY_LABELS)
@pytest.mark.parametrize("phrase", COMMON_NOUN_PHRASES)
def test_common_noun_after_a_party_label_is_not_masked_as_a_person(label, phrase):
    text = f"{label} {phrase} 제출되지 않았다."
    assert _person_text(text) == [], f"일반 명사가 인명으로 가려진다: {text!r}"


# ---------------------------------------------------------------------------
# R7-03 요건을 긍정으로 소명한 정상 항변이 '~하지 않고'·'~하지 않았으므로'에 걸려 과대주장 경고를 받지 않는다
# (회귀: TK-40이 부정 어미를 요건 뒤 35자 안의 낱말 일치로 읽어 요건 충족 서술의 부정어를 요건 부정으로 오인)
# ---------------------------------------------------------------------------
OVERCLAIM = "GEN.DEFENSE_OVERCLAIM_WITHOUT_REQUIREMENTS"
POSITIVE_REQUIREMENT_WITH_NEGATIVE_NEIGHBOUR = [
    "설령 대여 사실이 인정되더라도, 피고가 변제기 도래 후 지체하지 않고 전액을 지급하였으므로 이 사건 채무에 관한 책임이 없다.",
    "만약 대여 사실이 인정되더라도, 원고의 수령거절이 있자 피고가 주저하지 않고 변제공탁을 하였으므로 이 사건 채무에 관한 책임을 질 수 없다.",
    "가령 금전 수수가 인정되더라도, 상계의 의사표시가 원고에게 도달하였고 원고가 이의하지 않았으므로 해당 채무에 관한 책임이 없다.",
]


def _overclaim_warned(text: str) -> bool:
    from packages.legal_engine.legal_rules import review_legal_rules
    from tests.regression.test_ledger import make_synthetic_doc
    return any(OVERCLAIM in finding.tags for finding in review_legal_rules(make_synthetic_doc("청 구 원 인", text)))


@pytest.mark.parametrize("index", range(len(POSITIVE_REQUIREMENT_WITH_NEGATIVE_NEIGHBOUR)))
def test_positive_requirement_followed_by_a_negative_verb_is_not_flagged(index):
    text = POSITIVE_REQUIREMENT_WITH_NEGATIVE_NEIGHBOUR[index]
    assert not _overclaim_warned(text), f"요건 충족 서술의 부정어를 요건 부정으로 읽는다: {text}"


# ---------------------------------------------------------------------------
# R7-04 줄 결합 — 같은 문단의 결합 결과는 쪽의 다른 줄에 의존하지 않는다 (회귀: 7차가 쪽 전역 플래그만 문단 국소로 바꾸고
# 오른쪽 끝 right_edge는 쪽 전체에서 구해, 다른 문단의 꽉 찬 줄 수에 따라 같은 문단이 다르게 결합된다)
# ---------------------------------------------------------------------------
FILL = "이 사건 계약은 갑 제1호증에 따라 체결되었으며 그 이행 여부가 다투어지고 있다고 서술한다."
PARAGRAPH_LINES = [
    "피고는 원고가 주장하는 채권이 이미 소멸하였다고 다툴 수",
    "있을 뿐 아니라 그 소멸시효가 완성되었다고 주장할 수",
    "있다고 밝혔다.",
]


def _reconstruct(extra_full_lines: int) -> str:
    from packages.common.schemas import BBox, Block
    from packages.document_engine.paragraph_reconstruction import reconstruct_page_blocks

    def block(block_id, text, y, x1):
        return Block(block_id=block_id, text=text, page=1, bbox=BBox(72, y, x1, y + 12))

    blocks, y = [], 80
    for k in range(extra_full_lines):
        blocks.append(block(f"other{k}", FILL, y, 520.0))
        y += 14
    y += 30
    for index, line in enumerate(PARAGRAPH_LINES):
        blocks.append(block(f"p{index}", line, y, 500.0 if index < len(PARAGRAPH_LINES) - 1 else 300.0))
        y += 14
    out = reconstruct_page_blocks(blocks, page_num=1, page_width=595.0, page_height=842.0)
    return [b.text for b in out if "소멸" in b.text][-1]


def test_same_paragraph_joins_identically_whatever_other_full_lines_the_page_has():
    results = {n: _reconstruct(n) for n in (0, 1, 2, 3)}
    assert len(set(results.values())) == 1, f"다른 줄 수에 따라 결합이 달라진다: {results}"


# ---------------------------------------------------------------------------
# R7-05 (미해결, strict xfail) 낱말 목록 밖의 낱말에서도 줄 결합이 구조로 판정된다 — 6차·7차 R3의 요구
# 7차가 괄호 뒤 관형사 8개·독립 1음절 어절 18개의 목록으로 맞췄으므로 목록 밖 낱말은 시작과 같이 틀린다.
# ---------------------------------------------------------------------------
UNLISTED_BOUNDARY_PAIRS = [
    # (앞 줄, 뒷 줄, join_lines 호출 인자, 기대 결합 — 어절 경계라 공백이 있어야 하는 쌍)
    ("피고는 (당시", "상황)을 이렇게 설명한다", {}, "피고는 (당시 상황)을 이렇게 설명한다"),
    ("원고는 (관련", "규정)을 근거로 든다", {}, "원고는 (관련 규정)을 근거로 든다"),
    ("위 약정에 따라 지급할 의무가 있는 때", "피고는 지체 없이 이행하여야 한다", {"prev_full": True},
     "위 약정에 따라 지급할 의무가 있는 때 피고는 지체 없이 이행하여야 한다"),
    ("원고가 매도한 목적물 중", "일부는 이미 인도되었다", {"prev_full": True}, "원고가 매도한 목적물 중 일부는 이미 인도되었다"),
    ("위 약정서 작성 당시 피고가 알 수", "없었던 사정이 있다", {"prev_full": True}, "위 약정서 작성 당시 피고가 알 수 없었던 사정이 있다"),
]


@pytest.mark.parametrize("index", range(len(UNLISTED_BOUNDARY_PAIRS)))
def test_word_boundary_join_does_not_depend_on_a_word_list(index):
    from packages.document_engine.paragraph_reconstruction import join_lines
    prev, nxt, kwargs, expected = UNLISTED_BOUNDARY_PAIRS[index]
    assert join_lines(prev, nxt, boundary_signal="SPACE_CONFIRMED", **kwargs) == expected


# ---------------------------------------------------------------------------
# R7-06 (미해결, strict xfail) 라벨 어휘 밖의 인명 표지 — 사용자 결정(2026-10-03 '추천대로')으로 어휘 확대 승인(TK-43 요구 3)
# 여기에는 대표 라벨 4개만 둔다. 같은 범주(성명 직접 표지·작성/담당/진술 관계인·거래 당사자·가족/보호 관계)의 다른 낱말은
# 평가 측 비공개 변형으로 따로 잰다 — 목록을 이 시험의 4개에 맞추는 것으로는 통과하지 못한다.
# ---------------------------------------------------------------------------
NEW_LABELS = ["이름", "작성자", "담당자", "진술인"]
NEW_LABEL_FORMATS = ["{label}: {name} 확인 요망", "{label} {name}은 기일에 출석하였다."]
NEW_LABEL_NAMES = ["한도현", "서윤재"]


# 승격(2026-10-03, Round 7 종결): TK-37 관리자 탭·TK-43 라벨 어휘 확대·TK-45 '없으나' 요건 부정 — 61ef12f에서 통과해 strict xfail 표시를 지웠다
@pytest.mark.parametrize("label", NEW_LABELS)
@pytest.mark.parametrize("form", range(len(NEW_LABEL_FORMATS)))
def test_name_after_a_person_reference_label_outside_the_old_vocabulary_is_fully_masked(label, form):
    name = NEW_LABEL_NAMES[(NEW_LABELS.index(label) + form) % 2]
    text = NEW_LABEL_FORMATS[form].format(label=label, name=name)
    covered = set()
    from packages.pii_engine.detector import detect
    for match in detect(text):
        if "PERSON" in str(getattr(match, "type", None) or getattr(match, "pii_type", None) or getattr(match, "kind", None)).upper():
            covered.update(range(match.start, match.end))
    start = text.index(name)
    assert all(index in covered for index in range(start, start + len(name))), f"이름이 전부 가려지지 않았다: {text!r}"


# ---------------------------------------------------------------------------
# R7-07 명시 성명의 끝 음절이 조사처럼 보이고 앞 두 음절이 일반 불용어일 때 이름이 통째로 제외되지 않는다
# (회귀: 7차 R1이 후보 전체를 평가하기 전에 조사를 떼어 stem 불용어 검사를 한다 — 독립 감사 Astra A7-01, 공개 재현 `성명: 임용은`)
# 이름은 모두 합성이며 실제 사람을 가리키지 않는다. 한 이름만 예외로 풀 수 없도록 서로 다른 stem·끝 음절 6개를 둔다.
# ---------------------------------------------------------------------------
STEM_LIKE_NAMES = ["임용은", "정산이", "조사도", "신청은", "공지이", "심사가"]


@pytest.mark.parametrize("name", STEM_LIKE_NAMES)
def test_explicit_name_is_kept_when_its_leading_syllables_look_like_a_common_noun(name):
    text = f"성명: {name}"
    covered = set()
    from packages.pii_engine.detector import detect
    for match in detect(text):
        if "PERSON" in str(getattr(match, "type", None) or getattr(match, "pii_type", None) or getattr(match, "kind", None)).upper():
            covered.update(range(match.start, match.end))
    start = text.index(name)
    assert all(index in covered for index in range(start, start + len(name))), f"명시 성명이 제외된다: {text!r}"


# ---------------------------------------------------------------------------
# R7-08 (미해결, strict xfail) 요건을 '~한 적/사실이 없으나'로 부정한 한정 결론도 경고가 유지된다
# (독립 감사 A7-02 공개 재현 2건 + 평가 측 새 문장 2건. 시작·4da3910 모두 경고 0. TK-45)
# ---------------------------------------------------------------------------
DENIED_WITH_NEGATIVE_EXISTENTIAL = [
    "설령 대여 사실이 인정되더라도, 원고에게 전액을 지급한 적이 없으나 민법 제460조에 따라 이 사건 채무에 관한 책임을 질 수 없다.",
    "설령 차용 사실이 인정되더라도, 변제공탁을 한 사실이 없으나 민법 제487조에 따라 해당 채무에 관한 책임을 질 수 없다.",
    "가사 금전 수수가 인정되더라도, 상계의 의사표시를 한 사실이 없으나 이 사건 채무에 관한 책임을 질 수 없다.",
    "만약 대여 사실이 인정되더라도, 변제기가 도래한 적이 없으나 본건 채무에 관한 책임을 질 수 없다.",
]


# 승격(2026-10-03, Round 7 종결): TK-37 관리자 탭·TK-43 라벨 어휘 확대·TK-45 '없으나' 요건 부정 — 61ef12f에서 통과해 strict xfail 표시를 지웠다
@pytest.mark.parametrize("index", range(len(DENIED_WITH_NEGATIVE_EXISTENTIAL)))
def test_requirement_denied_by_a_negative_existential_keeps_the_overclaim_warning(index):
    text = DENIED_WITH_NEGATIVE_EXISTENTIAL[index]
    assert _overclaim_warned(text), f"요건 부정 문장의 과대주장 경고가 없다: {text}"


# ---------------------------------------------------------------------------
# R7-09 성명·이름 라벨 뒤에 이름이 아닌 말이 와도 PII 탐지기가 예외로 끝나지 않는다
# (회귀: 7차 보완 9506481이 `josa_match`를 `if not is_name_label:` 안에서만 만들고 뒤에서 무조건 읽어 UnboundLocalError — TK-48, P1)
# ---------------------------------------------------------------------------
ORDINARY_PHRASES_AFTER_NAME_LABELS = [
    "성명 불상의 직원이 현장에 있었다고 주장한다.",
    "성명 미상의 자가 문서를 작성하였다.",
    "성명: 불상",
    "이름: 확인 불가",
    "원고 성명 불상",
    "피고 서명자는 불명이다.",
    "성명 표시 생략",
    "성명: 가나다라마",
    # 9506481 독립 감사(Sol B7-01)·평가 측 재현: 후보마다 `josa_match`가 보장되지 않아 첫 후보에서 예외
    "성명: 가나다",
    "성명: 김도현은 출석하였다.",
    "성명 김도현은 출석하였다.",
    "담당자: 박민수는 기록을 확인했다.",
    "피청구인: 각하한다",
    "원고: 청구를 기각한다",
    "피고: 항변을 철회한다",
]


@pytest.mark.parametrize("text", ORDINARY_PHRASES_AFTER_NAME_LABELS)
def test_pii_detection_does_not_raise_on_ordinary_text_after_a_name_label(text):
    from packages.pii_engine.detector import detect
    detect(text)  # 예외가 나면 실패 — 한 문서의 한 문구가 검증 전체를 멈춘다


@pytest.mark.parametrize("text", ["성명: 김도현은 출석하였다.", "성명 김도현은 출석하였다."])
def test_explicit_name_label_keeps_the_name_and_drops_the_particle(text):
    # 시작(7adf43f)·4da3910에서 통과한 동작. 9506481은 예외로 멈춘다(TK-48).
    assert _person_text(text) == ["김도현"], _person_text(text)


# ---------------------------------------------------------------------------
# R7-10 새 라벨(사용자·근로자·보증인·후견인 등) 뒤 일반 명사를 인명으로 가리지 않는다
# (회귀: 9506481의 라벨 어휘 확대가 `{새 라벨} {일반 명사}`의 36%를 PERSON으로 가린다 — 사용자 승인 조건 '새 라벨 뒤 일반 명사 오탐 0' 위반, TK-43)
# 시작·4da3910에서는 이 라벨들이 어휘에 없어 PERSON 0이다.
# ---------------------------------------------------------------------------
NEW_VOCAB_LABELS = ["사용자", "근로자", "보증인", "후견인", "임차인", "도급인"]
COMMON_NOUNS_AFTER_LABEL = ["계정은", "서명은", "지시는", "의견은"]


# 승격(2026-10-03, 8차): 170c647에서 24조합 모두 통과해 xfail 표시를 지웠다
@pytest.mark.parametrize("label", NEW_VOCAB_LABELS)
@pytest.mark.parametrize("noun", COMMON_NOUNS_AFTER_LABEL)
def test_common_noun_after_an_added_label_is_not_masked_as_a_person(label, noun):
    text = f"{label} {noun} 이 사건과 무관하다."
    assert _person_text(text) == [], f"일반 명사가 인명으로 가려진다: {text!r}"


# ---------------------------------------------------------------------------
# R7-11 당사자 라벨 + 콜론 뒤 소송 용어를 인명으로 가리지 않는다
# (회귀: 9506481은 `is_name_label`에 ':'를 넣어 당사자·직책 라벨까지 '성명 표지'로 완화한다 — Sol B7-01, TK-43)
# 시작(7adf43f)·4da3910은 모두 PERSON 0이다. (참고: `채무자: 변제를`·`증인: 진술을`은 시작부터 있던 오탐이라 이 시험 대상이 아니다.)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    ["신청인: 기각을 구한다", "피청구인: 각하한다", "원고: 청구를 기각한다", "피고: 항변을 철회한다"],
)
def test_colon_after_a_party_label_does_not_relax_to_an_explicit_name(text):
    assert _person_text(text) == [], f"소송 용어가 인명으로 가려진다: {text!r}"


# ---------------------------------------------------------------------------
# R7-12 당사자 라벨 + 실명 + 인사·절차 후행 문맥에서 이름 전체 마스킹 (TK-43 ↔ TK-39 잔여)
# 시작(7adf43f)은 새고(`선임 안건`·`해임 건`이 후행 문맥 제외 목록에 있다), 4da3910은 라벨 완화로 막았으나
# 9506481이 완화를 성명 표지·콜론으로 줄이자 되돌아왔다. TK-43 요구 ①(과마스킹 제거)과 이 시험은 같은 목록을 두고 부딪히므로
# **R7-02(`{당사자 라벨} 진술 조서는` 오탐 0)와 이 시험을 함께 만족**해야 한다. 입력은 평가 측 비공개 변형과 다른 이름·문맥이다.
# ---------------------------------------------------------------------------
LEAK_LABELS = ["원고", "피고", "신청인", "증인", "피해자", "채무자"]
LEAK_NAMES = ["하준서", "백다온"]
LEAK_CONTEXTS = ["{L} {n} 선임 안건을 상정한다.", "{L} {n} 해임 건을 의결한다."]


@pytest.mark.parametrize("label", LEAK_LABELS)
@pytest.mark.parametrize("name", LEAK_NAMES)
@pytest.mark.parametrize("ctx", LEAK_CONTEXTS)
def test_party_label_real_name_before_an_appointment_phrase_is_fully_masked(label, name, ctx):
    text = ctx.format(L=label, n=name)
    assert name in _person_text(text), f"실명이 가려지지 않는다: {text!r} → {_person_text(text)}"
