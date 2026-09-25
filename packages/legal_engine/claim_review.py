"""법리 주장 검토: 주장 유형 분류 → 근거 조회 → 판단(추가지시 G4).

문구 하나하나를 맞히는 규칙이 아니라, 문장을 먼저 '주장 유형'으로 나누고 유형마다 근거를 찾아 판단한다.

| 유형 | 분류 기준(문장 구조) | 근거 조회 | 판단 |
|---|---|---|---|
| 위헌 주장 | '위헌'·'헌법에 위반' + 대상 조항 | 대상이 헌법 조항이면 심판 대상 규정(헌법재판소법 제41조·제68조), 법률 조항이면 헌재 결정 이력 | 헌법 조항 자체 → 형식상 불가. 단정적 위헌 주장인데 합헌 결정 → 모순, 각하 → 사람 확인. 이력 조회 불가 → 확인 불가 |
| 전칭 일반화 | '언제나'·'어떠한 경우에도'·'예외 없이'·'모든 경우' + 법적 효과 서술 | 같은·앞 문장의 근거 인용 | 근거 인용이 없으면 UNSUPPORTED_GENERALIZATION |
| 법률상 근거 없는 청구 유형 | 청구하는 구제 수단(배수 배상, 비형사 절차의 형벌, 사죄광고) | 구제 수단의 일반 근거 조문 | 개별 법률 근거를 들지 않으면 사람 확인 |
| 조문 요건 불일치 | '제N조에 따라/의하여' + 적용 대상 | 조회한 조문 원문의 주체 | 공적 주체 조문을 사인에게(또는 반대로) 적용하면 확인 필요 |
| 출처 불명 기준 | '기준표'·'지침'·'가이드라인' 등에 기대는 서술 | 발행 기관·번호·일자 | 출처를 특정할 수 없으면 확인 필요 |
| 소송요건 배제 | 제소기간·시효·전심절차·원고적격 + '적용되지 않는다'류 | 소송요건 조문 | 예외 조문·판례 없이 배제하면 확인 필요 |

판정은 서면의 문장과 근거 원문만으로 하며 사건의 결론(인용·기각)을 내리지 않는다. 근거 원문은
config/legal_rules/rules.json의 공식 원문(sources)을 쓰고, 없는 근거는 이름만 싣고 원문 미수록을 밝힌다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding, NormalizedDocument
from packages.document_engine.reading_text import build_reading_text, sentence_bounds

from .legal_rules import load_rules
from .polarity import ASSERTED, NEGATED, polarity

ENGINE_NAME = "legal_engine.claim_review"

# --- 문장 구성 요소 ----------------------------------------------------------------
LAW_NAME = r"[가-힣]+(?:\s[가-힣]+){0,4}?(?:법률|법|헌법|령|규칙)"
PROVISION_RE = re.compile(
    rf"(?P<law>{LAW_NAME})\s*제\s*(?P<art>\d+)\s*조(?:\s*의\s*(?P<sub>\d+))?(?:\s*제\s*(?P<para>\d+)\s*항)?")
BARE_PROVISION_RE = re.compile(r"제\s*\d+\s*조")
# 판례 인용은 사건번호나 '선고'가 있어야 한다. '판결'이라는 낱말만으로는 근거 인용으로 보지 않는다.
CASE_CITE_RE = re.compile(r"(?:19|20)?\d{2}\s*(?:헌[가-힣]|[가-힣]{1,3})\s*\d{2,6}|선고")
CITATION_ANY_RE = re.compile(rf"{PROVISION_RE.pattern}|{CASE_CITE_RE.pattern}|제\s*\d+\s*조")
CONSTITUTION_NAMES = {"헌법", "대한민국헌법", "대한민국 헌법"}

UNCON_RE = re.compile(r"위헌|헌법에\s*(?:위반|위배|반하|반한다|어긋)|헌법\s*위반")
UNCON_NEGATION_RE = re.compile(r"위헌(?:이|은|으로)?\s*(?:아니|라고\s*(?:할|볼)\s*수\s*없)|합헌|위헌\s*여부|위헌법률\s*심판\s*제청|"
                               r"위헌\s*(?:소지|의심|가능성)")
CERTAIN_RE = re.compile(r"명백(?:히|하게|한|하다)|분명(?:히|하게|하다)|당연히|의심의\s*여지(?:가|도)?\s*없|누가\s*보아도|자명")
STANDARD_OF_REVIEW_RE = re.compile(r"\s*(?:에|과|와)\s*(?:위반|위배|반하|반한|어긋|저촉)")
CONSTITUTION_ITSELF_RE = re.compile(r"헌법\s*(?:조항|규정|조문)\s*(?:그\s*)?자체")
# 헌법 조항 바로 뒤에 주어 조사와 '위헌'이 오면 그 조항 자체를 위헌이라고 한 것이다('헌법 제10조 자체가 위헌').
SUBJECT_UNCON_RE = re.compile(r"\s*(?:\(\s*[^)]{0,20}\))?\s*(?:자체|그\s*자체)?\s*(?:가|이|은|는)\s*[^.,]{0,15}?위헌")

QUANTIFIER_RE = re.compile(
    r"어떠한\s*경우(?:에도|라도|에라도)|어떤\s*경우(?:에도|라도)|언제나|항상|예외\s*(?:없이|없는|를\s*불문)|"
    r"모든\s*경우(?:에|에도)?|무조건|절대(?:로|적으로)?\s+(?=[가-힣])|예외가\s*(?:없다|있을\s*수\s*없)")
LEGAL_EFFECT_RE = re.compile(
    r"무효|위법|위헌|취소(?:되어야|하여야|사유|된다)|책임(?:을|이)\s*(?:진다|지게|있|부담)|배상(?:하여야|할\s*책임|책임)|"
    r"인정(?:된다|되어야|되지\s*않|될\s*수\s*없)|허용(?:된다|되지|될\s*수)|금지(?:된다|되)|할\s*수\s*없|하여야\s*한다|해야\s*한다|"
    r"적용(?:된다|되지)|성립(?:한다|하지|된다)|소멸(?:한다|하지|된다)|효력(?:이|을)|의무(?:가|를)|권리(?:가|를)|"
    r"정당화(?:된다|될)|면책(?:된다|되지)|징계(?:할|하여야|사유)|권리\s*남용|해당(?:한다|합니다|하지|된다)|"
    r"(?:될|받을|볼|감액될|거절될|취소될|배제될)\s*수\s*(?:없|있)|배상(?:하여야|해야)|지급(?:하여야|할\s*의무)|"
    # 법원의 판단 경향을 전칭으로 말하는 서술('항상 원고 승소 판결을 해 왔다')
    r"(?:판결|판단|결정|인용|기각|취소)(?:을|를)?\s*(?:해|하여)\s*왔|승소|패소")
QUALIFIER_RE = re.compile(r"특별한\s*사정이\s*없는\s*한|원칙적으로|대체로|일반적으로\s*(?:는|은)?\s*(?:[가-힣]+\s*){0,2}한다고\s*보|"
                          r"경우가\s*많|할\s*수\s*있다")

STANDARD_NOUN_RE = re.compile(
    r"(?:[가-힣]{0,12}\s?)(?:산정\s*기준표|판정\s*기준표|기준표|산정\s*기준|산정표|요율표|가이드라인|지침|매뉴얼|업무\s*기준|내부\s*기준|실무\s*기준|"
    r"업계\s*(?:기준|관행)|표준\s*[가-힣]{0,6}표|판정\s*기준|해설서|안내서|편람|핸드북|업무\s*(?:처리\s*)?요령|실무\s*요령)")
RELIANCE_RE = re.compile(r"\s*(?:에\s*따르면|에\s*의하면|에\s*의하여|에\s*따라|에\s*근거|을\s*적용|를\s*적용|상\s)")
ISSUER_RE = re.compile(
    r"[가-힣]+(?:부|처|청|위원회|공단|공사|협회|학회|법원|재판소|연구원|진흥원|관리원|평가원|보험공단)\s*(?:의|가|이|에서|이\s*정한|가\s*정한)?\s|"
    r"고시|훈령|예규|규정\s*제|제\s*\d+\s*호|[\(（]\s*(?:19|20)\d{2}|(?:19|20)\d{2}\s*\.\s*\d{1,2}\s*\.|https?://|별표|시행령|시행규칙")

REQUIREMENT_TERMS = {
    "제소기간": ("행정소송법 제20조", r"제소\s*기간|출소\s*기간"),
    "소멸시효": ("민법 제162조", r"소멸\s*시효|시효\s*(?:기간|완성)"),
    "전심절차": ("행정소송법 제18조", r"전심\s*절차|전치\s*(?:절차|주의)|행정\s*심판\s*(?:전치|절차)|소청\s*(?:심사|절차)|"
                                  r"항고\s*(?:절차|제기|를\s*거치)"),
    "원고적격": ("행정소송법 제12조", r"원고\s*적격|당사자\s*적격|소의\s*이익|법률상\s*이익"),
}
EXCLUSION_RE = re.compile(
    r"적용되지\s*않|적용(?:이|을)\s*(?:없|받지\s*않)|무관|배제(?:된다|되어야)|필요(?:가|치)?\s*없|필요하지\s*않|불요|거치지\s*않아도|"
    r"문제(?:가\s*)?되지\s*않|문제가\s*없|제한을\s*받지\s*않|고려할\s*필요(?:가)?\s*없|따질\s*필요(?:가)?\s*없|"
    r"지나도\s*(?:된다|무방)|상관(?:이)?\s*없|의미가\s*없")
EXCEPTION_BASIS_RE = re.compile(r"정당한\s*사유|무효\s*(?:등\s*)?확인|단서|제\s*\d+\s*조\s*제\s*\d+\s*항|특별\s*규정|"
                                r"법률에\s*특별한|예외\s*규정")

MULTIPLE = r"(?:\d+|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*배"
PUNITIVE_RE = re.compile(rf"징벌적\s*(?:손해)?\s*배상|(?:손해액|손해|배상액|재산상\s*손해)의?\s*{MULTIPLE}(?:에\s*해당하는|의|를|을)?|"
                         rf"{MULTIPLE}\s*(?:의\s*)?(?:손해)?\s*배상")
CRIMINAL_RELIEF_RE = re.compile(r"(?:징역|금고|벌금|형사\s*처벌|처벌)[^.\n]{0,12}(?:에\s*처한다|에\s*처하라|하라|한다|을\s*구한다)")
# 민사·국가배상 소송에서 법원이 명할 수 없는 인사·징계 조치(파면·해임·징계 등)를 구하는 청구
PERSONNEL_RELIEF_RE = re.compile(r"(?:파면|해임|징계|감봉|정직|강등|직위\s*해제|전보)\s*(?:처분)?\s*(?:하라|시켜라|에\s*처하라|할\s*것을\s*명한다)")
APOLOGY_RELIEF_RE = re.compile(r"사죄\s*광고|사과문을?\s*(?:게재|공표|낭독)하라|사죄문을?\s*(?:게재|공표)하라")
RELIEF_HEAD_RE = re.compile(r"청\s*구\s*취\s*지")
GROUNDS_HEAD_RE = re.compile(r"청\s*구\s*원\s*인")
CRIMINAL_DOC_RE = re.compile(r"공소장|공소사실|피고인|검사\s*[가-힣○]|구형|형사\s*공판")

APPLY_RE = re.compile(r"(?:에\s*따라|에\s*의하여|에\s*의해|에\s*근거하여|이\s*적용되어|을\s*적용하면|를\s*적용하면|에서\s*정한)")
PUBLIC_ACTOR_RE = re.compile(r"국가|지방\s*자치\s*단체|공무원|행정청|공공\s*(?:단체|기관)|장관|처장|청장|시장|군수|구청장|도지사|교육감|사단장|참모총장")
PRIVATE_ACTOR_RE = re.compile(r"주식\s*회사|㈜|\(주\)|유한\s*회사|회사|법인|사업자|개인|사인|임대인|임차인|매도인|매수인|사용자|근로자")


@dataclass
class ClaimMatch:
    claim_type: str
    sentence: str
    start: int
    judgment: str
    grade: str
    status: str
    basis: List[Dict[str, Any]] = field(default_factory=list)
    detail: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


HistoryLookup = Callable[[str, str], Dict[str, Any]]


def _source(name: str) -> Dict[str, Any]:
    sources = load_rules().get("sources") or {}
    entry = sources.get(name)
    if entry:
        return {"name": name, **entry}
    return {"name": name, "text": "", "note": "공식 원문을 규칙표에 수록하지 않았다(이름만 표시)"}


# 법령명 앞에서 멈출 어절 끝(조사·관형형 어미). '의'는 법령명 안에 흔하므로('공공기관의 정보공개에 관한 법률')
# 멈추지 않고, '에'는 '…에 관한 법률'처럼 이름 안에 있을 때만 이어 붙인다.
PARTICLE_END_RE = re.compile(r"(?:은|는|이|가|을|를|에|도|로|와|과|께서|에서|에게|인|된|한|던|적인)$")


def law_name(raw: str) -> str:
    """조항 앞의 어절 가운데 법령명만 남긴다. '피고 회사는 가상공공배상법' → '가상공공배상법'.

    법령명에는 띄어쓰기가 있을 수 있어('제조물 책임법') 끝 어절부터 거꾸로 붙이되, 조사로 끝나는 어절을
    만나면 멈춘다.
    """
    tokens = raw.split()
    kept: List[str] = []
    for token in reversed(tokens):
        # '…에 관한 법률'·'…에 따른 법률'처럼 법령명 안의 조사는 남긴다.
        inside_name = bool(kept) and ((kept[0] in ("관한", "대한", "따른", "의한") and token.endswith("에"))
                                      or token in ("관한", "대한", "따른", "의한"))
        if kept and PARTICLE_END_RE.search(token) and not inside_name:
            break
        kept.insert(0, token)
    return " ".join(kept)


def _provisions(sentence: str):
    return list(PROVISION_RE.finditer(sentence))


def _is_constitution(law: str) -> bool:
    # 앞 어절이 섞여도('…아니라 헌법') 끝 어절이 '헌법'이면 헌법 조항이다.
    tokens = law_name(law).split()
    return bool(tokens) and (tokens[-1] in CONSTITUTION_NAMES or " ".join(tokens[-2:]) in CONSTITUTION_NAMES)


def _has_citation(*texts: str) -> bool:
    return any(t and CITATION_ANY_RE.search(t) for t in texts)


# 앞 문장의 인용은 이 문장이 앞 문장을 이어받을 때만 근거로 본다('따라서', '이에 따라', '위 판결은' 등).
CONTINUATION_RE = re.compile(r"^\s*(?:\d+\.\s*)?(?:따라서|그러므로|그렇다면|이에\s*따라|이러한|이런|그러한|그런|이는|이와\s*같이|위\s*(?:판결|결정|조항|규정|판례)|"
                             r"같은\s*(?:조|법|취지)|동\s*(?:조|법|판결)|즉|결국)")


def _linked_previous(sentence: str, previous: str) -> str:
    return previous if CONTINUATION_RE.match(sentence) else ""


# --- 유형별 판단 ----------------------------------------------------------------------
def _unconstitutionality(sentence: str, lookup: Optional[HistoryLookup]) -> Optional[ClaimMatch]:
    if not UNCON_RE.search(sentence) or UNCON_NEGATION_RE.search(sentence):
        return None
    provisions = _provisions(sentence)
    targets = [m for m in provisions if not STANDARD_OF_REVIEW_RE.match(sentence, m.end())]
    itself = CONSTITUTION_ITSELF_RE.search(sentence)
    subject_const = [m for m in provisions if _is_constitution(m.group("law")) and SUBJECT_UNCON_RE.match(sentence, m.end())]
    if subject_const:
        targets = subject_const
    if itself or (targets and all(_is_constitution(m.group("law")) for m in targets)):
        if not itself and not targets:
            return None
        label = targets[0].group(0) if targets else "헌법 조항"
        return ClaimMatch(
            "UNCONSTITUTIONALITY", sentence, 0, "헌법 조항 자체를 위헌이라고 주장(심판 대상 아님)", "B", "CONTRADICTED",
            [_source("대한민국헌법 제111조"), _source("헌법재판소법 제41조"), _source("헌법재판소법 제68조")],
            f"'{label}'은 헌법 규정이다. 헌법재판소가 관장하는 위헌 심판은 '법률의 위헌여부 심판'(대한민국헌법 제111조 "
            "제1항 제1호)과 '법률이 정하는 헌법소원'(같은 항 제5호)이므로, 헌법 조항 자체는 위헌 여부 심판의 대상이 "
            "아니다.", {"target": label})
    statute_targets = [m for m in targets if not _is_constitution(m.group("law"))]
    if not statute_targets or not CERTAIN_RE.search(sentence):
        return None
    target = statute_targets[0]
    law, article = law_name(target.group("law")), target.group("art") + (
        f"의{target.group('sub')}" if target.group("sub") else "")
    label = f"{law} 제{article}조"
    history = lookup(law, article) if lookup else {"status": "UNAVAILABLE", "message": "헌재 결정 이력 조회기가 없다"}
    decisions = history.get("decisions") or []
    if history.get("status") != "READY":
        return ClaimMatch(
            "UNCONSTITUTIONALITY", sentence, 0, "단정적 위헌 주장(헌재 결정 이력 확인 불가)", "C", "UNVERIFIED", [],
            f"{label}이 명백히 위헌이라고 단정했다. 이 조항에 대한 헌법재판소 결정 이력을 확인하지 못했다"
            f"({history.get('message') or '조회 불가'}). 합헌 결정이 있는지 사람이 확인해야 한다.",
            {"target": label, "history": history})
    uncon = [d for d in decisions if d.get("result") in ("위헌", "헌법불합치", "한정위헌")]
    upheld = [d for d in decisions if d.get("result") in ("합헌", "한정합헌")]
    dismissed = [d for d in decisions if d.get("result") == "각하"]
    if uncon or not (upheld or dismissed):
        return None
    chosen = sorted(upheld or dismissed, key=lambda d: str(d.get("decision_date") or ""))[-1]
    cite = f"헌법재판소 {chosen.get('decision_date', '')} {chosen.get('case_number', '')} {chosen.get('result')} 결정".strip()
    basis = [{"name": cite, "text": chosen.get("summary") or chosen.get("case_name") or "", "url": chosen.get("url", "")}]
    if upheld:
        return ClaimMatch(
            "UNCONSTITUTIONALITY", sentence, 0, "합헌 결정이 있는 조항을 명백히 위헌이라고 주장", "B", "CONTRADICTED", basis,
            f"{label}에 대하여 {cite}이 있다. 이 결정을 다루지 않고 명백히 위헌이라고 단정했다.",
            {"target": label, "decisions": decisions})
    return ClaimMatch(
        "UNCONSTITUTIONALITY", sentence, 0, "각하 결정이 있는 조항을 명백히 위헌이라고 주장(사람 확인)", "C", "SUSPICIOUS", basis,
        f"{label}에 대하여 {cite}이 있다. 각하는 본안 판단이 아니므로 합헌을 뜻하지 않지만, 단정의 근거를 확인해야 한다.",
        {"target": label, "decisions": decisions})


def _generalization(sentence: str, previous: str) -> Optional[ClaimMatch]:
    quantifier = QUANTIFIER_RE.search(sentence)
    if not quantifier or not LEGAL_EFFECT_RE.search(sentence[quantifier.start():]):
        return None
    if QUALIFIER_RE.search(sentence) or _has_citation(sentence, _linked_previous(sentence, previous)):
        return None
    return ClaimMatch(
        "UNSUPPORTED_GENERALIZATION", sentence, 0, "근거 없는 전칭 법리 명제", "B", "SUSPICIOUS", [],
        f"'{quantifier.group(0).strip()}'로 예외를 모두 배제하는 법리 명제인데, 이 문장과 앞 문장에 근거 조문·판례가 없다. "
        "전칭 명제는 그 범위를 뒷받침하는 근거가 있어야 한다.", {"quantifier": quantifier.group(0).strip()})


def _remedy(sentence: str, in_relief: bool, criminal_doc: bool) -> Optional[ClaimMatch]:
    punitive = PUNITIVE_RE.search(sentence)
    if punitive and not _has_citation(sentence):
        return ClaimMatch(
            "NO_BASIS_REMEDY", sentence, 0, "개별 법률 근거 없이 배수·징벌적 배상 청구", "B", "SUSPICIOUS",
            [_source("민법 제393조"), _source("민법 제763조")],
            "민법상 손해배상은 통상의 손해(민법 제393조, 불법행위는 제763조로 준용)를 한도로 한다. 손해액의 배수를 "
            "배상하게 하려면 그렇게 정한 개별 법률 조항이 있어야 하는데, 서면은 근거 조항을 들지 않았다.",
            {"remedy": punitive.group(0)})
    if in_relief and not criminal_doc and CRIMINAL_RELIEF_RE.search(sentence):
        return ClaimMatch(
            "NO_BASIS_REMEDY", sentence, 0, "형사절차가 아닌 소송에서 형벌을 구하는 청구", "B", "CONTRADICTED",
            [_source("형사소송법 제246조")],
            "형벌은 검사가 공소를 제기한 형사절차에서만 과할 수 있다(형사소송법 제246조). 민사·행정 소송의 "
            "청구취지로 징역·벌금 등 형벌을 구할 수 없다.", {"remedy": "형사처벌"})
    if in_relief and PERSONNEL_RELIEF_RE.search(sentence):
        return ClaimMatch(
            "NO_BASIS_REMEDY", sentence, 0, "법원이 명할 수 없는 인사·징계 조치 청구", "B", "SUSPICIOUS",
            [_source("민법 제394조")],
            "손해배상은 다른 의사표시가 없으면 금전으로 한다(민법 제394조). 공무원·직원의 파면·징계 같은 인사 조치는 "
            "임용권자·징계권자의 권한이며, 손해배상 소송의 청구취지로 법원에 명하게 할 법률 근거가 없다.",
            {"remedy": "인사·징계 조치"})
    if in_relief and APOLOGY_RELIEF_RE.search(sentence):
        return ClaimMatch(
            "NO_BASIS_REMEDY", sentence, 0, "사죄광고·사과문 게재 강제 청구(사람 확인)", "C", "SUSPICIOUS",
            [_source("민법 제764조"), _source("헌법재판소 1991. 4. 1. 89헌마160 결정")],
            "명예훼손의 구제로 '명예회복에 적당한 처분'(민법 제764조)을 구할 수 있으나, 헌법재판소는 이 조항이 "
            "사죄광고를 포함하는 취지라면 헌법에 위반된다고 결정했다(헌법재판소 1991. 4. 1. 89헌마160). 청구 형태가 "
            "허용되는지 사람이 확인해야 한다.",
            {"remedy": "사죄광고"})
    return None


def _unsourced_standard(sentence: str) -> Optional[ClaimMatch]:
    for noun in STANDARD_NOUN_RE.finditer(sentence):
        if not RELIANCE_RE.match(sentence, noun.end()):
            continue
        if ISSUER_RE.search(sentence) or _has_citation(sentence):
            return None
        name = noun.group(0).strip()
        return ClaimMatch(
            "UNSOURCED_STANDARD", sentence, 0, "출처를 특정할 수 없는 기준 인용", "B", "SUSPICIOUS", [],
            f"'{name}'에 기대어 판단하지만 발행 기관·문서 번호·일자가 없어 원문을 찾아 대조할 수 없다. 기준의 출처를 "
            "특정해야 한다.", {"standard": name})
    return None


def _requirement_exclusion(sentence: str, previous: str) -> Optional[ClaimMatch]:
    excluded = EXCLUSION_RE.search(sentence)
    if not excluded:
        return None
    for term, (basis, pattern) in REQUIREMENT_TERMS.items():
        hit = re.search(pattern, sentence)
        if not hit or abs(hit.start() - excluded.start()) > 60:
            continue
        # 예외 근거는 소송요건의 예외를 정한 조문·판례여야 한다. 헌법의 일반 기본권 조항(재판청구권 등)만 든
        # 경우는 예외 근거로 보지 않는다.
        previous = _linked_previous(sentence, previous)
        cited = [m for m in PROVISION_RE.finditer(sentence + " " + previous) if not _is_constitution(m.group("law"))]
        other_cite = CASE_CITE_RE.search(sentence) or (previous and CASE_CITE_RE.search(previous))
        constitutional_only = bool(PROVISION_RE.search(sentence)) and not cited and not other_cite
        if EXCEPTION_BASIS_RE.search(sentence) and not constitutional_only:
            return None
        if (cited or other_cite) and not constitutional_only:
            return None
        return ClaimMatch(
            "LITIGATION_REQUIREMENT_EXCLUSION", sentence, 0, f"근거 없이 소송요건({term})을 배제", "B", "SUSPICIOUS",
            [_source(basis)],
            f"{term}은 소송요건 또는 권리 행사의 요건이다({basis}). 서면은 예외를 정한 조문이나 판례를 들지 않고 "
            f"{term}이 적용되지 않는다고 주장했다.", {"requirement": term})
    return None


def requirement_mismatches(doc: NormalizedDocument, provisions: Sequence[Dict[str, Any]]) -> List[ClaimMatch]:
    """조문 요건(주체) 불일치. provisions: {"law", "article", "text", "version"} — 조회한 공식 원문."""
    text = build_reading_text(doc).text
    out: List[ClaimMatch] = []
    for start, end in sentence_bounds(text):
        sentence = " ".join(text[start:end].split())
        for match in PROVISION_RE.finditer(sentence):
            if not APPLY_RE.match(sentence, match.end()):
                continue
            law, article = law_name(match.group("law")), match.group("art")
            official = next((p for p in provisions if p.get("law") == law and str(p.get("article")) == article
                             and p.get("text")), None)
            if not official:
                continue
            subject = re.match(r"\s*(?:①|제\s*\d+\s*조\S*\s*)?\s*(?:\([^)]*\)\s*)?([^,.。]{2,40}?)(?:은|는|이|가)\s",
                               official["text"])
            if not subject:
                continue
            article_subject = subject.group(1)
            # 적용 대상은 법령명 앞 부분이다. 정규식이 법령명 앞 어절까지 잡으므로 법령명만큼 잘라 낸다.
            before = sentence[:match.end("law")].rstrip()
            applied_to = before[:len(before) - len(law)]
            public_rule = bool(PUBLIC_ACTOR_RE.search(article_subject))
            private_rule = bool(PRIVATE_ACTOR_RE.search(article_subject))
            actor_private = bool(PRIVATE_ACTOR_RE.search(applied_to)) and not PUBLIC_ACTOR_RE.search(applied_to)
            # 공적 주체(국가·행정청·공무원 등)를 요건으로 한 조문을 사인(회사·개인)에게 적용한 경우만 본다.
            # 반대 방향(사인 요건 조문을 국가에 적용)은 국가도 사용자·임대인 등이 될 수 있어 판단하지 않는다.
            if public_rule and not private_rule and actor_private:
                label = f"{law} 제{article}조"
                out.append(ClaimMatch(
                    "REQUIREMENT_MISMATCH", sentence, start, "조문의 주체 요건과 적용 대상 불일치", "B", "SUSPICIOUS",
                    [{"name": label, "text": official["text"][:400], "url": official.get("url", ""),
                      "version": official.get("version")}],
                    f"비교 대상 조문: {label}({official.get('version') or '조회 버전'}). 조문의 주체는 "
                    f"'{article_subject.strip()}'인데 서면은 이 조문을 다른 부류의 당사자에게 적용했다. 요건 충족 여부를 "
                    "사람이 확인해야 한다.", {"article_subject": article_subject.strip(), "compared": label}))
    return out


# --- 문서 단위 ----------------------------------------------------------------------
def _relief_span(text: str):
    relief = RELIEF_HEAD_RE.search(text)
    if not relief:
        return None
    grounds = GROUNDS_HEAD_RE.search(text, relief.end())
    return relief.end(), grounds.start() if grounds else min(len(text), relief.end() + 1500)


def classify_claims(text: str, lookup: Optional[HistoryLookup] = None) -> List[ClaimMatch]:
    relief = _relief_span(text)
    criminal_doc = bool(CRIMINAL_DOC_RE.search(text[:3000]))
    out: List[ClaimMatch] = []
    previous = ""
    for start, end in sentence_bounds(text):
        sentence = " ".join(text[start:end].split())
        if not sentence:
            continue
        in_relief = bool(relief and relief[0] <= start < relief[1])
        for check in (lambda s: _unconstitutionality(s, lookup), lambda s: _generalization(s, previous),
                      lambda s: _remedy(s, in_relief, criminal_doc), _unsourced_standard,
                      lambda s: _requirement_exclusion(s, previous)):
            match = check(sentence)
            if match and not in_relief and not _author_asserts(match, previous):
                continue  # 부정·전달·가정으로 쓴 문장은 작성자의 주장이 아니다(v5 3-2)
            if match:
                match.start = start
                out.append(match)
                break  # 한 문장은 가장 앞선 유형 하나로만 판정한다(같은 문장 이중 판정 방지)
        previous = sentence
    return out


# 유형마다 '명제'로 볼 부분: (앞 부분, 명제 끝을 정하는 뒷부분). 극성은 명제 끝 뒤의 글로 판별한다.
_CLAIM_SPANS = {
    "UNCONSTITUTIONALITY": (UNCON_RE, None),
    "UNSUPPORTED_GENERALIZATION": (QUANTIFIER_RE, LEGAL_EFFECT_RE),
    "NO_BASIS_REMEDY": (PUNITIVE_RE, None),
    "UNSOURCED_STANDARD": (STANDARD_NOUN_RE, RELIANCE_RE),
    "LITIGATION_REQUIREMENT_EXCLUSION": (EXCLUSION_RE, None),
}


def _author_asserts(match: ClaimMatch, previous: str) -> bool:
    """이 문장의 명제를 작성자가 단정했는가. 출처 불명 기준은 내용의 긍정·부정과 무관하게 그 기준에 기댄 것이
    문제이므로 부정은 보지 않고 전달·가정만 본다."""
    head, tail = _CLAIM_SPANS.get(match.claim_type, (None, None))
    found = head.search(match.sentence) if head else None
    if not found:
        return True
    end = found.end()
    if tail is not None:
        after = tail.search(match.sentence, found.start())
        if after:
            end = max(end, after.end())
    result = polarity(match.sentence, (found.start(), end), previous=previous)
    if match.claim_type == "UNSOURCED_STANDARD" and result == NEGATED:
        return True
    return result == ASSERTED


def _to_finding(doc: NormalizedDocument, match: ClaimMatch) -> Finding:
    kind = (FindingType.UNSUPPORTED_GENERALIZATION if match.claim_type == "UNSUPPORTED_GENERALIZATION"
            else FindingType.LEGAL_ARGUMENT_INVALID)
    grade = {"A": EvidenceGrade.A, "B": EvidenceGrade.B, "C": EvidenceGrade.C}.get(match.grade, EvidenceGrade.C)
    human = match.grade == "C" or match.status in ("SUSPICIOUS", "UNVERIFIED")
    evidence = [Evidence.create(description="서면의 주장", grade=EvidenceGrade.B, document_id=doc.document_id,
                                excerpt=match.sentence[:300], supports=False)]
    for source in match.basis:
        evidence.append(Evidence.create(description=f"근거: {source['name']}" + (f" ({source['url']})" if source.get("url") else ""),
                                        grade=EvidenceGrade.A if source.get("text") else EvidenceGrade.U,
                                        excerpt=str(source.get("text") or source.get("note") or "")[:300]))
    return Finding.create(
        type=kind, status=VerificationStatus(match.status),
        severity=Severity.HIGH if match.grade in ("A", "B") and match.status == "CONTRADICTED" else Severity.MEDIUM,
        evidence_grade=grade,
        title=f"법리 검토({_TYPE_LABELS[match.claim_type]}): {match.judgment} — '{match.sentence[:70]}'",
        detail=match.detail + (" 근거: " + "; ".join(b["name"] for b in match.basis) if match.basis else ""),
        confidence={"A": 0.9, "B": 0.75, "C": 0.5}.get(match.grade, 0.5),
        confidence_features={"deterministic_rule": True, "rule_id": f"CLAIM.{match.claim_type}",
                             "claim_type": match.claim_type, "judgment": match.judgment, "claim": match.sentence[:300],
                             "basis": match.basis, "human_review": human, **match.extra},
        document_id=doc.document_id, engine=ENGINE_NAME,
        tags=["LEGAL_CLAIM", f"CLAIM.{match.claim_type}"] + (["HUMAN_REVIEW"] if human else []),
        evidence=evidence)


_TYPE_LABELS = {"UNCONSTITUTIONALITY": "위헌 주장", "UNSUPPORTED_GENERALIZATION": "전칭 일반화",
                "NO_BASIS_REMEDY": "근거 없는 청구 유형", "REQUIREMENT_MISMATCH": "조문 요건 불일치",
                "UNSOURCED_STANDARD": "출처 불명 기준", "LITIGATION_REQUIREMENT_EXCLUSION": "소송요건 배제"}


def review_claims(doc: NormalizedDocument, *, lookup: Optional[HistoryLookup] = None,
                  provisions: Sequence[Dict[str, Any]] = (), skip_sentences: Iterable[str] = ()) -> List[Finding]:
    """문서의 법리 주장을 유형별로 검토한다. skip_sentences: 다른 규칙이 이미 판정한 문장(이중 판정 방지)."""
    text = build_reading_text(doc).text
    skip = {" ".join(s.split())[:80] for s in skip_sentences if s}
    matches = classify_claims(text, lookup) + requirement_mismatches(doc, provisions)
    out, seen = [], set()
    for match in matches:
        key = match.sentence[:80]
        if key in skip or key in seen:
            continue
        seen.add(key)
        out.append(_to_finding(doc, match))
    return out


def provision_texts(verdicts: Sequence[Dict[str, Any]], citations: Sequence[Any]) -> List[Dict[str, Any]]:
    """법령 인용 판정에서 조회한 공식 조문 원문을 모은다(조문 요건 대조용)."""
    by_id = {getattr(c, "citation_id", None): c for c in citations}
    out: List[Dict[str, Any]] = []
    for verdict in verdicts:
        citation = by_id.get(verdict.get("citation_id"))
        provision = (verdict.get("review") or {}).get("provision") or {}
        if not citation or not provision.get("text") or not getattr(citation, "law_name", None):
            continue
        version = (verdict.get("review") or {}).get("version") or {}
        out.append({"law": law_name(citation.law_name), "article": str(citation.article or "").replace("조", ""),
                    "text": provision["text"], "version": version.get("version_id") or version.get("effective_from"),
                    "url": ((verdict.get("official_record") or {}).get("url") or "")})
    return out
