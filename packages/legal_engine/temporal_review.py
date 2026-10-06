"""법령 적용 시점(행위시법) 검토(v4 P3).

조문이 개정되어 시행 버전마다 내용이 다를 때, 문서가 조문 내용으로 적은 수치(기간·법정형 등)가 어느 버전과
맞는지 본다. 사건에 어느 버전을 적용할지(부칙·경과규정, 형법 제1조 제2항의 경한 신법 등)는 판단하지 않는다.

기준일(우선순위)
1. 사용자가 입력한 기준일(ProjectContext.case_date).
2. 문장이 스스로 '행위 당시·범행 당시·처분 당시'처럼 시점을 밝히고, 문서가 그 시점으로 적은 날짜가 하나뿐일 때.
3. 문서에서 추정한 후보(v4 검토 4항): 범행일·처분일·불법행위일·원심 선고일을 뽑고, 인용 법령의 성격에 맞는
   종류(소송법 → 원심 선고일, 형사 → 범행일, 처분 서술 → 처분일, 그 밖 → 불법행위일)의 날짜가 하나뿐이면 그 날짜.
   추정 기준일은 '문서에서 추정'으로 표시하고, 어느 시행 버전이 적용되는지는 결론 내리지 않는다.
4. 그 밖에는 기준일 불명 → TEMPORAL_REVIEW 경고(후보 목록을 함께 적는다).

시행 버전
- 내부 Mirror에 버전이 둘 이상 있으면 그것을, 없으면 국가법령정보 법령 연혁(eflaw, 시행일 기준 목록)에서
  기준일 시행본(구법)과 현행본을 받아 조문을 대조한다(official_versions). 기준일이 없으면 현행본과 직전 시행본을 받는다.

판정
- 기준일 버전과 일치: 확인(VERIFIED). 현행 버전과 다르면 '현행과 다름'을 함께 적는다.
- 현행 버전과만 일치: 경고(SUSPICIOUS) — 기준일 당시 버전과 다르다.
- 어느 버전과도 불일치: 알려진 모든 버전 값을 적고 CONTRADICTED.
- 기준일이 없고 버전에 따라 결과가 갈리면: TEMPORAL_REVIEW(미확인). CONTRADICTED로 두지 않는다.
형사 사건에는 형법 제1조(제1항 행위시법, 제2항 범죄 후 법률 변경)를 검토 근거로 적는다.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding

from .provision_content import compare_claim_to_provision

ENGINE_NAME = "legal_engine.temporal_review"
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
TIME_QUALIFIER_RE = re.compile(r"(?P<kind>행위|범행|처분|사고|계약|사건)\s*(?:당시|시(?:점)?(?:에|의)?)")
# '2023. 11. 20.'과 '2023년 11월 20일' 표기를 모두 읽는다(공소사실은 흔히 '년월일'로 적는다).
DATE_RE = re.compile(r"(?P<y>(?:19|20)\d{2})\s*[.년]\s*(?P<m>\d{1,2})\s*[.월]\s*(?P<d>\d{1,2})\s*[.일]?")
# 문서가 행위(범행)일로 적은 날짜: '피고인은 2021. 6. 1. …', '2021. 6. 1. … 범행·횡령·공소사실'
ACT_SUBJECT_RE = re.compile(r"(?:피고인|피의자|행위자)\s*(?:은|는|이|가)?\s*$")
ACT_SENTENCE_RE = re.compile(r"공소사실|범행|횡령|절취|편취|폭행|배임|사기|위반행위")
DISPOSITION_AFTER_RE = re.compile(
    r"^[^.\n]{0,35}?(?:"
    r"징계\s*(?:처분|의결|절차)|"
    r"(?:해임|파면|강등|감봉|견책)(?:\s*처분)?|"
    r"(?:영업|자격|면허|허가)?\s*(?:정지|취소|철회|제한)(?:\s*(?:\d+\s*(?:개월|월|년)|처분))|"
    r"정직(?!\s*하[게여였은는])(?:\s*(?:\d+\s*(?:개월|월)|처분))|"
    r"처분(?:을?\s*(?:취소|명|받|하|내렸|내리|고지|처하)|일|[은는이가])|"
    r"(?:과징금|부과금|과태료)\s*(?:부과|처분)"
    r")"
)
DISPOSITION_BEFORE_RE = re.compile(r"(?:처분일(?:자)?|징계일(?:자)?|해임(?:처분)?일(?:자)?|발령일(?:자)?)\s*[:：]?\s*$")
CRIMINAL_HINT_RE = re.compile(r"피고인|공소|형사|징역|벌금|법정형|범행")
CRIMINAL_BASIS = ("형법 제1조 제1항(범죄의 성립과 처벌은 행위 시의 법률에 따른다) 및 제2항(범죄 후 법률 변경 시 "
                  "경한 신법)을 기준으로 어느 버전을 적용할지 사람이 검토해야 한다")
# 계약·약정·체결 관련 키워드 정규식 (민사 계약 사건 기준일 특정용)
CONTRACT_SENTENCE_RE = re.compile(r"계약|체결|약정|합의|용역|공급|도급|위탁|납품|발주|납기|준공|이행기")


def paragraph_text(article_text: str, paragraph: Optional[str]) -> str:
    """조문 본문에서 ①·② 등 항 부분만. 항 표시가 없거나 못 찾으면 조문 전체."""
    if not paragraph or not str(paragraph).isdigit() or not 1 <= int(paragraph) <= len(CIRCLED):
        return article_text or ""
    n = int(paragraph)
    start = (article_text or "").find(CIRCLED[n - 1])
    if start < 0:
        return article_text or ""
    end = (article_text or "").find(CIRCLED[n], start + 1) if n < len(CIRCLED) else -1
    return article_text[start:end if end > 0 else None]


# 한글 법령 목 열거 글자 명시 집합 (유니코드 [가-하] 10,585자 대신 정확한 14자 명시 집합 사용)
SUBITEM_LETTERS = "가나다라마바사아자차카타파하"
SUBITEM_LETTER_SET = frozenset(SUBITEM_LETTERS)

# 목 인식 정규식: 호 표기(제N호 또는 N호)가 반드시 선행해야 함
ITEM_SUBITEM_RE = re.compile(rf"(?:제?\s*(?P<item>\d+)호)\s*(?:제?\s*(?P<subitem>[{SUBITEM_LETTERS}])목)")

# 목 분할 정규식: 호 본문 내부에서 목 열거 글자만을 대상으로 분할
SUBITEM_SPLIT_RE = re.compile(rf"\n\s*(?P<letter>[{SUBITEM_LETTERS}])\.\s*")


def extract_subitem_info(citation) -> Tuple[Optional[str], Optional[str]]:
    """citation에서 호(item)와 목(subitem)을 추출한다.

    목 글자는 명시 집합 [가나다라마바사아자차카타파하]로 한정하며,
    반드시 호 표기(제N호 또는 N호)가 선행하는 경우에만 인정한다.
    '항목'·'품목'·'교과목' 등 일반 명사는 제외된다.
    """
    raw = getattr(citation, "raw_text", "") or ""
    item = getattr(citation, "item", None)
    attributes = citation.attributes or {}
    subitem = attributes.get("subitem")

    m = ITEM_SUBITEM_RE.search(raw)
    if m:
        if not item:
            item = m.group("item")
        if not subitem:
            subitem = m.group("subitem")

    if subitem and subitem in SUBITEM_LETTER_SET and item:
        return str(item), subitem
    return None, None


def extract_item_body(article_text: str, item: str) -> Optional[str]:
    """조문/항 본문에서 특정 호('N.')의 본문을 추출한다."""
    if not item or not str(item).isdigit():
        return None
    n = int(item)
    # 시작: (시작 또는 개행) + n + "."
    # 끝: 다음 호 (\n\s*\d+\.) 또는 다음 항 (\n\s*[①-⑳]) 또는 텍스트 끝
    pattern = re.compile(rf"(?:^|\n)\s*{n}\.\s*(?P<body>.*?)(?=(?:\n\s*\d+\.\s*)|(?:\n\s*[{CIRCLED}])|\Z)", re.DOTALL)
    m = pattern.search(article_text or "")
    if m:
        return m.group("body")
    return None


def split_subitems(item_body: str) -> Dict[str, str]:
    """호 본문에서 [가나다라마바사아자차카타파하] 목들을 분할하여 {목글자: 목본문} 반환."""
    if not item_body:
        return {}
    matches = list(SUBITEM_SPLIT_RE.finditer(item_body))
    if not matches:
        return {}
    subitems: Dict[str, str] = {}
    for i, m in enumerate(matches):
        letter = m.group("letter")
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(item_body)
        subitems[letter] = item_body[start:end].strip()
    return subitems


def version_outcomes(citation, versions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    attributes = citation.attributes or {}
    claim = attributes.get("claim_text")
    numbers_only = attributes.get("claim_mode") == "PARENTHETICAL_BASIS"
    subject = attributes.get("claim_subject")

    # 목 단위 특정 여부 확인 (조건 ①: [가나다라마바사아자차카타파하] 명시 집합 & 호 선행 필수)
    item_num, subitem_letter = extract_subitem_info(citation)

    out = []
    for version in versions:
        article_text = version.get("text") or ""
        para_text = paragraph_text(article_text, citation.paragraph)

        # 목 단위 대조 대상인 경우 (주장 문언이 있을 때만 목 단위 부존재 판정 적용)
        if item_num and subitem_letter and claim and claim.strip():
            item_body = extract_item_body(para_text, item_num)
            subitems = split_subitems(item_body) if item_body else {}

            if subitems:
                # 목 분할이 정상적으로 된 경우
                # 1) 인용된 목 본문과 직접 대조
                cited_outcome = None
                if subitem_letter in subitems:
                    cited_outcome = compare_claim_to_provision(
                        claim, subitems[subitem_letter], numbers_only=numbers_only, subject=subject
                    )

                if cited_outcome and cited_outcome["status"] == "VERIFIED":
                    out.append({"version": version, "outcome": cited_outcome})
                    continue

                # 2) 인용된 목과 불일치하거나 인용된 목이 없는 경우:
                # 해당 버전의 다른 목들 중 내용이 일치하는 목이 있는지 확인 (번호만 바뀐 개정 오탐 방지)
                matching_letter = None
                matching_outcome = None
                for ltr, text in subitems.items():
                    res = compare_claim_to_provision(claim, text, numbers_only=numbers_only, subject=subject)
                    if res["status"] == "VERIFIED":
                        matching_letter = ltr
                        matching_outcome = res
                        break

                if matching_letter and matching_outcome:
                    # 다른 목에 내용이 존재하므로 실질 규범 일치로 판정
                    outcome = dict(matching_outcome)
                    matched_items = list(outcome.get("matched") or [])
                    matched_items.append(f"{matching_letter}목(내용 일치)")
                    outcome["matched"] = matched_items
                    out.append({"version": version, "outcome": outcome})
                    continue

                # 3) 해당 버전의 어느 목에도 내용이 부합하지 않는 경우 (신설 목의 부존재, 진성 소급 오류 근거)
                out.append({
                    "version": version,
                    "outcome": {
                        "status": "CONTRADICTED",
                        "basis": "SUBITEM_NOT_EXIST",
                        "mismatches": [{"official": f"제{item_num}호 내 일치하는 목 규정 부존재", "claim": claim}],
                        "matched": [],
                    }
                })
                continue

            # 호·목 분할에 실패한 경우: 기존 조·항 단위 경로의 결과를 그대로 유지 (새 finding 생성 없음)

        # 일반 조·항 대조 경로
        outcome = compare_claim_to_provision(claim, para_text, numbers_only=numbers_only, subject=subject)
        out.append({"version": version, "outcome": outcome})

    return out


def _covers(version: Dict[str, Any], when: str) -> bool:
    start, end = version.get("effective_from"), version.get("effective_to")
    return (not start or start <= when) and (not end or when <= end)


def _label(version: Dict[str, Any]) -> str:
    return f"{version.get('effective_from') or '?'}~{version.get('effective_to') or '현행'}"


def _official_values(outcome: Dict[str, Any]) -> str:
    if outcome.get("mismatches"):
        return ", ".join(m["official"] for m in outcome["mismatches"])
    return ", ".join(outcome.get("matched") or []) or "-"


def act_date(text: str, kind: str) -> Optional[str]:
    """문서가 그 시점(행위·처분·계약 등)의 날짜로 적은 날짜가 하나뿐이면 그 날짜."""
    found, charged = set(), set()
    for sentence in re.split(r"(?<=[다음함])\s*[.。]\s*|\n", text or ""):
        for m in DATE_RE.finditer(sentence):
            try:
                value = date(int(m.group("y")), int(m.group("m")), int(m.group("d"))).isoformat()
            except ValueError:
                continue
            if kind in ("행위", "범행", "사건") and (ACT_SUBJECT_RE.search(sentence[:m.start()])
                                                  and ACT_SENTENCE_RE.search(sentence)):
                found.add(value)
                if "공소사실" in sentence:
                    charged.add(value)  # 심판 대상인 공소사실의 행위일이 다른 서술보다 우선한다
            elif kind == "처분" and DISPOSITION_AFTER_RE.match(sentence[m.end():]):
                found.add(value)
            elif kind in ("계약", "합의", "약정") and (CONTRACT_SENTENCE_RE.search(sentence[:m.start()]) or CONTRACT_SENTENCE_RE.search(sentence[m.end():])):
                found.add(value)  # 계약 체결 관련 날짜 수집
    for dates in (charged, found):
        if len(dates) == 1:
            return next(iter(dates))
    return None


REFERENCE_KINDS = {
    "CONTRACT": "계약·합의일",
    "OFFENSE": "범행일",
    "DISPOSITION": "처분일",
    "TORT": "불법행위일",
    "LOWER_JUDGMENT": "원심 선고일",
}
TORT_SENTENCE_RE = re.compile(r"사고|불법행위|손해가\s*발생|상해를\s*입|부상을\s*입|폭행을\s*당|내원|진료|수술|오진|의료사고|사망")
LOWER_JUDGMENT_RE = re.compile(r"원심|제1심|1심|원판결")
PROCEDURAL_LAW_RE = re.compile(r"소송법$|소송규칙$")


def _sentences(text: str):
    # 한국어 하드 래핑 줄바꿈 결합: 종결 부호 없이 단순 개행된 줄을 공백으로 이어 문장 단절 방지
    unwrapped = re.sub(r"(?<![.\?!:;])\n(?!\s*(?:\d+[\.)]|[가-하][\.)]|[-•*]))", " ", text or "")
    return [s for s in re.split(r"(?<=[다음함])\s*[.。]\s*|\n", unwrapped) if s.strip()]


LAW_DATE_AFTER_RE = re.compile(
    r"\s*(?:"
    r"(?:법률|대통령령|총리령|[가-힣]{1,8}부령|훈령|예규|고시)\s*제\s*\d+\s*호|"
    r"(?:부터|자로)?\s*(?:개정[·ㆍ\s]?(?:공포|시행)|공포[·ㆍ\s]?(?:시행|개정)|시행[·ㆍ\s]?개정|개정|제정|신설|공포|시행)(?:된|되는|되어|한다|하는|일)?(?:\s*[「『]|\s+|$)|"
    r"[「『][가-힣\s0-9·ㆍ]+[」』]|"
    r"[가-힣]+(?:법률|법|령|규칙)\s*(?:제\s*\d+\s*[호조]|(?:부터|자로)?\s*(?:개정|제정|시행|공포|신설))"
    r")"
)


def reference_candidates(text: str) -> List[Dict[str, Any]]:
    """문서가 적은 계약체결일·범행일·처분일·불법행위일·원심 선고일 후보. 같은 날짜·종류는 한 번만."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for sentence in _sentences(text):
        if "생년월일" in sentence:
            continue  # 당사자·대표자 생년월일 기재 줄은 사건 행위일/계약일 후보에서 제외
        for m in DATE_RE.finditer(sentence):
            try:
                value = date(int(m.group("y")), int(m.group("m")), int(m.group("d"))).isoformat()
            except ValueError:
                continue
            before, after = sentence[:m.start()], sentence[m.end():]
            if LAW_DATE_AFTER_RE.match(after):
                continue  # "2022년 6월 10일 법률 제18900호로 개정", "2022. 12. 11.부터 시행": 법령의 날짜다
            kinds = []
            if ACT_SUBJECT_RE.search(before) and ACT_SENTENCE_RE.search(sentence):
                kinds.append("OFFENSE")
            if DISPOSITION_AFTER_RE.match(after) or DISPOSITION_BEFORE_RE.search(before):
                kinds.append("DISPOSITION")
            if LOWER_JUDGMENT_RE.search(sentence) and re.match(r"^\s*(?:에\s*)?선고", after):
                kinds.append("LOWER_JUDGMENT")
            if TORT_SENTENCE_RE.search(sentence) and not kinds and not re.match(r"^\s*(?:에\s*)?선고", after):
                kinds.append("TORT")
            # 계약·약정·체결 문맥 판별 (민사 계약 분쟁용)
            if (CONTRACT_SENTENCE_RE.search(before) or CONTRACT_SENTENCE_RE.search(after)) and not kinds and not re.match(r"^\s*(?:에\s*)?선고", after):
                kinds.append("CONTRACT")
            for kind in kinds:
                if (kind, value) not in seen:
                    seen.add((kind, value))
                    out.append({"kind": kind, "label": REFERENCE_KINDS[kind], "date": value,
                                "excerpt": sentence.strip()[:120]})
    return out


def preferred_kind(citation, candidates: List[Dict[str, Any]], *, criminal: bool) -> Optional[str]:
    """인용 법령의 성격에 맞는 기준일 종류. 문서에 그 종류의 후보가 없으면 None."""
    kinds = {c["kind"] for c in candidates}
    law = (getattr(citation, "law_name", "") or "").replace(" ", "")
    if PROCEDURAL_LAW_RE.search(law):
        order = ["LOWER_JUDGMENT"]
    elif criminal:
        order = ["OFFENSE"]
    else:
        # 민사/계약/행정 사건: 계약체결일(CONTRACT)을 최우선으로 검토
        order = ["CONTRACT", "DISPOSITION", "TORT"]
    return next((k for k in order if k in kinds), None)


def inferred_reference(citation, text: str, *, criminal: bool) -> Dict[str, Any]:
    candidates = reference_candidates(text)
    kind = preferred_kind(citation, candidates, criminal=criminal)
    if kind is None:
        return {"date": None, "basis": "MISSING", "candidates": candidates}
    dates = sorted({c["date"] for c in candidates if c["kind"] == kind})
    if len(dates) != 1:
        return {"date": None, "basis": "AMBIGUOUS", "kind": kind, "candidates": candidates,
                "note": f"{REFERENCE_KINDS[kind]} 후보가 {len(dates)}개({', '.join(dates)})라 기준일을 정하지 않았다"}
    return {"date": dates[0], "basis": "DOCUMENT_INFERRED", "kind": kind, "candidates": candidates,
            "note": f"문서에서 {REFERENCE_KINDS[kind]}로 추정한 {dates[0]}을 대조 기준으로 썼다(추정 기준일)"}


def reference_for(citation, sentence: str, document_text: str, case_date: Optional[str], *,
                  criminal: bool = False, infer: bool = True) -> Dict[str, Any]:
    if case_date:
        return {"date": case_date, "basis": "EXPLICIT_REVIEW_DATE"}
    qualifier = TIME_QUALIFIER_RE.search(sentence or "")
    if qualifier:
        when = act_date(document_text, qualifier.group("kind"))
        if when:
            return {"date": when, "basis": "DOCUMENT_ASSERTED",
                    "note": f"문장이 '{qualifier.group(0)}'이라고 밝혀, 문서가 그 시점으로 적은 {when}을 대조 기준으로 썼다"}
    if infer:
        return inferred_reference(citation, document_text, criminal=criminal)
    return {"date": None, "basis": "MISSING"}


def review_temporal_application(citation, versions: List[Dict[str, Any]], reference: Dict[str, Any],
                                *, criminal: bool = False) -> Optional[Finding]:
    """버전이 둘 이상이거나 행위 당시 부존재하던 신설 조항일 때 행위시법 적용 여부를 판단한다."""
    if not versions:
        return None
    when = reference.get("date")
    earliest_start = min((v.get("effective_from") for v in versions if v.get("effective_from")), default=None)

    # 신설 조항 소급 적용 체크: 행위 당시 조문 자체가 아직 제정/시행되지 않은 경우
    is_not_yet_enacted = bool(when and earliest_start and earliest_start > when)

    if len(versions) < 2 and not is_not_yet_enacted:
        return None
    results = [r for r in version_outcomes(citation, versions) if r["outcome"]["status"] in ("VERIFIED", "CONTRADICTED")]
    if len(results) < 2 and not is_not_yet_enacted:
        return None
    # 기준일 및 현행 버전 집합 도출
    ref_versions = [r for r in results if when and _covers(r["version"], when)]
    current_versions = [r for r in results if not r["version"].get("effective_to")]
    if not current_versions and results:
        max_eff = max(r["version"].get("effective_from") or "" for r in results)
        current_versions = [r for r in results if (r["version"].get("effective_from") or "") == max_eff]

    # 동일 시행일 복수 버전 내 대조 결과 갈림 여부 검사 (선행 분기)
    ref_split = len({r["outcome"]["status"] for r in ref_versions}) > 1
    current_split = len({r["outcome"]["status"] for r in current_versions}) > 1
    has_same_day_split = ref_split or current_split

    matching = [r for r in results if r["outcome"]["status"] == "VERIFIED"]
    claim = (citation.attributes or {}).get("claim_text") or ""
    values = "; ".join(f"{_label(r['version'])}: {_official_values(r['outcome'])}" for r in results) or (f"{_label(versions[0])} (신설 조항)" if versions else "")
    base_detail = f"문서의 주장 '{claim.strip()[:80]}'을 시행 버전별 조문과 대조했다({values})."
    basis_note = reference.get("note") or ""
    legal_basis = [CRIMINAL_BASIS] if criminal else []
    ambiguity_reason = None

    if is_not_yet_enacted:
        rule, status, severity = "TEMPORAL.STATUTE_NOT_YET_ENACTED", VerificationStatus.CONTRADICTED, Severity.HIGH
        title_tail = (f"행위 당시({when}) 부존재하던 신설 조항 소급 적용 (최초 시행일 {earliest_start}) — "
                      f"행위시법 원칙 위반(RETROACTIVE_APPLICATION_ERROR)")
    elif has_same_day_split:
        # 동일 시행일 복수 버전 결과 불일치: 기존 분기보다 선행하여 확인 요청으로 처리 (FT-b)
        rule, status, severity = "TEMPORAL.REVIEW_NEEDED", VerificationStatus.UNVERIFIED, Severity.INFO
        ambiguity_reason = "SAME_EFFECTIVE_DATE"
        title_tail = "동일 시행일 복수 개정 버전 간 대조 결과 불일치(사람 확인 필요)"
    elif when and not ref_versions:
        rule, status, severity, title_tail = ("TEMPORAL.REVIEW_NEEDED", VerificationStatus.UNVERIFIED, Severity.INFO,
                                              f"기준일 {when}에 시행된 버전을 확보하지 못했다")
    elif when and ref_versions and all(r in matching for r in ref_versions):
        ref_sample = ref_versions[0]
        current_sample = current_versions[0] if current_versions else ref_sample
        differs = current_versions and not any(r in matching for r in current_versions)
        rule, status, severity = "TEMPORAL.REFERENCE_VERSION_MATCH", VerificationStatus.VERIFIED, Severity.INFO
        title_tail = f"기준일 {when} 시행 버전({_label(ref_sample['version'])})과 일치" + (
            f" — 현행과 다름(현행 {_official_values(current_sample['outcome'])})" if differs else "")
    elif when and current_versions and all(r in matching for r in current_versions) and ref_versions and not any(r in matching for r in ref_versions):
        ref_sample = ref_versions[0]
        current_sample = current_versions[0]
        rule, status, severity = "TEMPORAL.CURRENT_ONLY_MATCH", VerificationStatus.SUSPICIOUS, Severity.HIGH
        title_tail = (f"증액·개정 규정 소급 적용 오류 — 기준일 {when} 당시 법정 규정은 {_official_values(ref_sample['outcome'])}"
                      f"(현행 {_official_values(current_sample['outcome'])}, RETROACTIVE_APPLICATION_ERROR)")
    elif not matching:
        rule, status, severity = "TEMPORAL.NO_VERSION_MATCH", VerificationStatus.CONTRADICTED, Severity.HIGH
        title_tail = f"어느 시행 버전과도 다르다({values})"
    elif len(matching) == len(results):
        rule, status, severity = "TEMPORAL.ALL_VERSIONS_MATCH", VerificationStatus.VERIFIED, Severity.INFO
        title_tail = "대조한 모든 시행 버전과 일치(적용 시점과 무관)"
    elif not when:
        rule, status, severity = "TEMPORAL.REVIEW_NEEDED", VerificationStatus.UNVERIFIED, Severity.LOW
        candidates = reference.get("candidates") or []
        listed = ", ".join(f"{c['label']} {c['date']}" for c in candidates[:6]) or "문서에서 찾은 후보 없음"
        title_tail = (f"기준일 불명 — 시행 버전에 따라 결과가 달라진다(후보: {listed}). 사람 확인 필요")
    else:
        rule, status, severity = "TEMPORAL.OTHER_VERSION_MATCH", VerificationStatus.SUSPICIOUS, Severity.MEDIUM
        title_tail = f"기준일 {when} 버전·현행 버전이 아닌 다른 시행 버전과만 일치"
    features = {"deterministic_rule": True, "rule_id": rule, "reference_date": when,
                "reference_basis": reference.get("basis"), "reference_kind": reference.get("kind"),
                "reference_candidates": reference.get("candidates") or [], "claim_text": claim,
                "defect_code": "TEMPORAL_REVIEW" if rule == "TEMPORAL.REVIEW_NEEDED" else rule.split(".")[-1],
                "version_source": (versions[0].get("source") if versions else None),
                "versions": [{"effective_from": r["version"].get("effective_from"),
                              "effective_to": r["version"].get("effective_to"),
                              "status": r["outcome"].get("status"), "values": _official_values(r["outcome"])}
                             for r in (results or [{"version": v, "outcome": {}} for v in versions])],
                "legal_basis": legal_basis, "human_review": True}
    if ambiguity_reason:
        features["ambiguity"] = ambiguity_reason
    detail = " ".join(x for x in (base_detail, basis_note, *(f"{b}." for b in legal_basis),
                                  "어느 버전이 사건에 적용되는지는 법률 판단이므로 결론을 내리지 않는다.") if x)
    return Finding.create(
        type=FindingType.TEMPORAL_LAW_MISMATCH, status=status, severity=severity,
        evidence_grade=EvidenceGrade.A if status == VerificationStatus.CONTRADICTED else EvidenceGrade.B,
        title=f"법령 적용 시점 검토: {citation.raw_text} — {title_tail}", detail=detail,
        confidence=0.85 if status == VerificationStatus.CONTRADICTED else 0.6, confidence_features=features,
        document_id=citation.document_id, block_id=citation.block_id, page=citation.page, span=citation.span,
        engine=ENGINE_NAME, advisory_only=status == VerificationStatus.VERIFIED,
        tags=["LEGAL", "STATUTE", "TEMPORAL"] + (["RETROACTIVE_APPLICATION_ERROR"] if "RETROACTIVE_APPLICATION_ERROR" in title_tail else []),
        evidence=[Evidence.create(description=f"시행 버전 {_label(r['version'])}", grade=EvidenceGrade.A,
                                  excerpt=paragraph_text(r["version"].get("text") or "", citation.paragraph)[:300])
                  for r in (results or [{"version": v} for v in versions])[:4]])


def criminal_context(text: str) -> bool:
    return len(CRIMINAL_HINT_RE.findall(text or "")) >= 2


def _day_before(value: str) -> Optional[str]:
    from datetime import timedelta

    try:
        return (date.fromisoformat(value) - timedelta(days=1)).isoformat()
    except (TypeError, ValueError):
        return None


def select_versions(records: list[dict], as_of: str) -> list[dict]:
    """지정 시점(as_of)에 시행 중인 법령 버전을 구한다.

    legal_history.select_version의 검증 규칙(법령 식별 모호, 공포일>기준일, 폐지 경계, 중복 충돌)을
    후보마다 엄격히 유지하되, 동일 시행일 복수 버전(len(choices) > 1)은 에러를 내지 않고 모두 반환한다.
    """
    from packages.source_adapters.legal_history import legal_date

    when = legal_date(as_of)
    if not when:
        raise ValueError("A valid explicit reference date is required")
    if not records:
        raise ValueError("No historical versions were returned")
    identities = {str(r.get("law_id") or "").lstrip("0") for r in records}
    if len(identities) != 1 or "" in identities:
        raise ValueError("Ambiguous or missing law identity")
    unique: dict[tuple, dict] = {}
    for row in records:
        start = legal_date(row.get("effective_from"))
        promulgated = legal_date(row.get("promulgation_date"))
        mst = str(row.get("version_id") or "")
        if not start or not promulgated or not mst.isdigit():
            raise ValueError("History contains missing or invalid version dates/identifiers")
        key = (mst, start)
        if key in unique and unique[key] != row:
            raise ValueError("Conflicting duplicate historical version")
        unique[key] = row
    eligible = [r for r in unique.values() if r["effective_from"] <= when]
    if not eligible:
        raise ValueError("No effective version covers the requested date")
    latest = max(r["effective_from"] for r in eligible)
    choices = [r for r in eligible if r["effective_from"] == latest]

    # 각 후보에 대해 차단 규칙 검사
    for chosen in choices:
        if chosen["promulgation_date"] > when:
            raise ValueError("Retroactive commencement requires legal review")
        if "폐지" in str(chosen.get("amendment_type") or ""):
            raise ValueError("Repeal boundary requires legal review")

    next_dates = [r["effective_from"] for r in unique.values() if r["effective_from"] > latest]
    out = []
    for chosen in choices:
        item = dict(chosen)
        item.update(
            requested_as_of=when, effective_until=min(next_dates) if next_dates else None,
            version_selection="EXACT", history_complete=True,
            version_history=[{k: r.get(k) for k in (
                "law_id", "version_id", "effective_from", "promulgation_date", "amendment_type"
            )} for r in sorted(unique.values(), key=lambda r: r["effective_from"])],
        )
        out.append(item)
    return out


def official_versions(adapter, citation, reference_date: Optional[str], today: str,
                      cache: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """국가법령정보 법령 연혁(eflaw)에서 기준일 시행본(구법)과 현행본을 받아 조문 버전 목록을 만든다.

    기준일이 없으면 현행본과 직전 시행본을 받는다. 조회 실패는 이유와 함께 돌려주고, 버전을 지어내지 않는다.
    반환: {"status": READY|UNAVAILABLE, "versions": [...], "reason": str, "source_urls": [...]}.
    """
    from packages.source_adapters.legal_history import legal_date, select_provision

    law_name = getattr(citation, "law_name", None)
    if not law_name or not getattr(citation, "article", None):
        return {"status": "UNAVAILABLE", "versions": [], "reason": "법령명·조문 번호가 없음"}
    if adapter is None or not hasattr(adapter, "search_law_history"):
        return {"status": "UNAVAILABLE", "versions": [], "reason": "법령 연혁을 조회할 출처가 없음"}
    status = str(adapter.status()) if hasattr(adapter, "status") else "READY"
    if not status.endswith("READY"):
        return {"status": "UNAVAILABLE", "versions": [], "reason": f"국가법령정보 조회 불가({status})"}
    cache = cache if cache is not None else {}
    history = cache.get(law_name)
    if history is None:
        history = cache[law_name] = adapter.search_law_history(law_name)
    if not getattr(history, "ok", False) or not getattr(history, "complete", False) or not history.records:
        return {"status": "UNAVAILABLE", "versions": [],
                "reason": f"법령 연혁을 확보하지 못함({getattr(history, 'message', '') or getattr(history, 'status', '')})"}
    rows = sorted(history.records, key=lambda r: legal_date(r.get("effective_from")) or "")
    earliest_start = legal_date(rows[0].get("effective_from")) if rows else None
    is_not_yet_enacted = bool(reference_date and earliest_start and earliest_start > reference_date)
    try:
        current_choices = select_versions(rows, today)
        if is_not_yet_enacted:
            # 기준일 당시 아직 법률이 제정/시행되지 않은 신설 법령인 경우: 최초 시행 버전을 wanted에 포함
            wanted = [rows[0]]
        else:
            wanted = select_versions(rows, reference_date) if reference_date else []
    except ValueError as exc:
        return {"status": "UNAVAILABLE", "versions": [], "reason": f"시행 버전을 고르지 못함({exc})"}
    if not reference_date:
        # 기준일이 없으면 현행 직전 시행본(구법)을 함께 받아 개정으로 결과가 갈리는지 본다
        current_start = current_choices[0].get("effective_from") or ""
        earlier = [r for r in rows if (legal_date(r.get("effective_from")) or "") < current_start]
        if earlier:
            earlier_latest = max(legal_date(r.get("effective_from")) or "" for r in earlier)
            wanted.extend([r for r in earlier if (legal_date(r.get("effective_from")) or "") == earlier_latest])
    wanted.extend(current_choices)
    starts = [legal_date(r.get("effective_from")) for r in rows]
    versions, urls, seen = [], [], set()
    for selected in wanted:
        key = (str(selected.get("version_id")), selected.get("effective_from"))
        if key in seen:
            continue
        seen.add(key)
        detail = adapter.fetch_law_version(selected)
        if not getattr(detail, "ok", False) or not detail.records:
            return {"status": "UNAVAILABLE", "versions": [],
                    "reason": f"{selected.get('effective_from')} 시행본 본문을 받지 못함({getattr(detail, 'message', '')})"}
        provision = select_provision(detail.records[0], str(citation.article))
        if provision.get("status") not in ("VERIFIED", "DELETED"):
            return {"status": "UNAVAILABLE", "versions": [],
                    "reason": f"{selected.get('effective_from')} 시행본에서 {_format_article(citation.article)}를 확인하지 못함"}
        start = legal_date(selected.get("effective_from"))
        later = [d for d in starts if d and start and d > start]
        record = getattr(detail, "source_record", None)
        url = getattr(record, "url", "") if record is not None else ""
        urls.append(url)
        versions.append({"text": provision.get("text") or "", "effective_from": start,
                         "effective_to": _day_before(min(later)) if later else None,
                         "version_id": selected.get("version_id"), "source": "OFFICIAL_HISTORY", "source_url": url})
    versions.sort(key=lambda v: (v["effective_from"] or "", str(v.get("version_id") or "")))
    return {"status": "READY", "versions": versions, "reason": "", "source_urls": urls}


# --- 서면이 밝힌 개정 이력과 행위일 대조 --------------------------------------------------------------
#
# 서면이 "2024년 12월 24일 법률 제20589호로 개정되어 2025년 1월 1일부터 시행된 「○○법」 제35조"처럼
# 개정 이력을 스스로 적고 그 조항을 행위에 적용하라고 주장하면, 적힌 시행일과 행위일(기준일)만으로도
# 행위 후 시행 조항에 기댄 주장임을 알 수 있다. 공식 연혁을 조회할 수 있으면 적힌 공포번호·공포일·시행일이
# 그 법령의 연혁에 있는지도 대조한다. 어느 법을 적용할지는 결론 내리지 않는다.
_D = r"(?:19|20)\d{2}\s*[.년]\s*\d{1,2}\s*[.월]\s*\d{1,2}\s*[.일]?"
_LAW_KIND = r"(?:법률|대통령령|총리령|[가-힣]{1,8}부령)"
_LAW_NAME = r"[「『]?\s*(?P<law>[가-힣][가-힣A-Za-z0-9ㆍ·\s\r\n]{0,40}?(?:법률|법|령|규칙))\s*[」』]?"
_ARTICLE = r"제\s*(?P<art>\d+)\s*조(?:\s*의\s*(?P<sub>\d+))?(?:\s*제\s*(?P<para>\d+)\s*항)?"
_AMEND_VERB = r"(?:개정[·ㆍ\s]?(?:공포|시행)|공포[·ㆍ\s]?(?:시행|개정)|시행[·ㆍ\s]?개정|개정|제정|신설|공포|시행)"
DECLARED_AMENDMENT_RES = (
    # (1) "2024년 12월 24일 법률 제20589호로 개정되어 2025년 1월 1일부터 시행된 (개정) 「방위사업법」 제35조 제4항"
    re.compile(rf"(?P<prom>{_D})\s*(?:(?P<kind>{_LAW_KIND})\s*제\s*(?P<num>\d{{1,6}})\s*호\s*(?:로|으로)?\s*)?"
               rf"(?:일부|전부)?\s*(?:개정|제정|신설)(?:되어|된|되고|되었으며|하여)?\s*,?\s*"
               rf"(?P<eff>{_D})\s*(?:부터|자로)?\s*시행(?:된|되는|되어|되고|중인)?\s*(?:개정\s*|현행\s*)?{_LAW_NAME}\s*{_ARTICLE}"),
    # (2) "「방위사업법」(2024. 12. 24. 법률 제20589호로 개정, 2025. 1. 1. 시행) 제35조"
    re.compile(rf"{_LAW_NAME}\s*\(\s*(?P<prom>{_D})\s*(?:(?P<kind>{_LAW_KIND})\s*제\s*(?P<num>\d{{1,6}})\s*호[^)\n]{{0,20}}?)?"
               rf"(?P<eff>{_D})\s*시행\s*\)\s*{_ARTICLE}"),
    # (3) 단일 날짜 개정/시행/공포 패턴 (호수 유무 무관, 개정·시행/개정·공포 등 모든 동사 지원, 서면8·변형1 포섭)
    re.compile(rf"(?P<prom>{_D})\s*"
               rf"(?:(?P<kind>{_LAW_KIND})\s*제\s*(?P<num>\d{{1,6}})\s*호\s*(?:로|으로)?\s*)?"
               rf"(?:일부|전부)?\s*"
               rf"{_AMEND_VERB}"
               rf"(?:된|되어|되고|되었으며|하여|한|되는)?\s*"
               rf"(?:개정\s*|현행\s*)?"
               rf"{_LAW_NAME}\s*{_ARTICLE}"),
)
# 행위 후 시행 조항을 사건에 적용하라는 주장인지(부합·소급·신법·면책 등)
RELIANCE_RE = re.compile(r"부합|소급|신법|적용되어|적용하여|적용해야|적용하|적용될|적용받|해당하여|따라\s*(?:피고인|형사|면책|책임|처벌)|조각|면책|무죄|정당화|단서|위반|부당")
# 행위시법·구법을 적용해야 한다는 변론(신법 소급 적용 주장이 아닌 정상적 구법 원용)
# 단, "구법보다 유리한 신법", "구법 대신"처럼 신법을 적용하라는 주장은 배제하지 않는다.
ACT_TIME_LAW_RE = re.compile(
    r"(?:행위\s*(?:당시|시)(?:의)?\s*(?:법|법률|법령)|구법|개정\s*전(?:의)?\s*(?:법|규정|조항))"
    r"(?!\s*(?:보다|대신|이\s*아닌|에\s*불구|을\s*배제))"
    r"\s*(?:에\s*(?:의하|따르|따른|의한|의거)|이\s*적용|을\s*적용|으로\s*판단)"
)
FAVORABLE_NEW_LAW_BASIS = (
    "형법 제1조 제1항은 범죄의 성립과 처벌을 행위 시의 법률에 따르게 하고, 제2항은 범죄 후 법률이 변경되어 그 행위가 "
    "범죄를 구성하지 아니하게 되거나 형이 구법보다 가벼워진 경우에만 신법에 따르게 한다. 대법원 2022. 12. 22. 선고 "
    "2020도16420 전원합의체 판결은 해당 형벌법규 자체 또는 그로부터 수권·위임을 받은 법령이 아닌 다른 법령이 변경된 "
    "경우에는 형사법적 관점의 변화를 주된 근거로 하는 법령 변경이어야 형법 제1조 제2항을 적용한다고 보았다")
CIVIL_TIME_BASIS = "법령은 원칙적으로 시행 후의 사실에 적용되므로, 행위 후 시행된 조항의 적용 여부는 부칙·경과규정으로 확인해야 한다"
# TK-04: 처분시법주의 — 행정처분 사건에서 처분일보다 뒤에 시행된 법령 적용 주장의 근거
DISPOSITION_TIME_BASIS = (
    "행정처분의 위법 여부는 처분 당시의 법령과 사실상태를 기준으로 판단하여야 하고, 처분 후 법령의 "
    "개폐나 사실상태의 변동에 의하여 영향을 받지 않는다(처분시법주의). "
    "처분일보다 뒤에 시행된 법령을 그 처분에 적용하라는 주장은 처분시법주의에 반할 수 있다")


def _format_article(article: str) -> str:
    """조문 번호 포매팅: '57의3' → '제57조의3', '12' → '제12조'.

    '제{article}조' 형태로 출력하면 '제57의3조'가 되는 비표준 표기를 방지한다.
    """
    if not article:
        return ""
    if "의" in str(article):
        # '57의3' → '제57조의3'
        parts = str(article).split("의", 1)
        return f"제{parts[0]}조의{parts[1]}"
    return f"제{article}조"



def _iso(value: str) -> Optional[str]:
    m = DATE_RE.search(value or "")
    if not m:
        return None
    try:
        return date(int(m.group("y")), int(m.group("m")), int(m.group("d"))).isoformat()
    except ValueError:
        return None


def declared_amendments(text: str) -> List[Dict[str, Any]]:
    """서면이 적은 '공포일·법령번호·시행일 + 법령명·조문' 묶음."""
    out, seen = [], set()
    for regex in DECLARED_AMENDMENT_RES:
        for m in regex.finditer(text or ""):
            law = " ".join(m.group("law").split())
            art = m.group("art")
            num = m.group("num") if "num" in m.groupdict() and m.group("num") else ""
            kind = m.group("kind") if "kind" in m.groupdict() and m.group("kind") else ""
            key = (law, art, num)
            if key in seen:
                continue
            seen.add(key)
            article = art + (f"의{m.group('sub')}" if m.group("sub") else "")
            # 단일 날짜 패턴에는 eff 그룹이 없으므로 prom을 fallback으로 사용
            prom_iso = _iso(m.group("prom"))
            try:
                eff_iso = _iso(m.group("eff"))
            except (IndexError, KeyError):
                eff_iso = None
            out.append({"law_name": law, "article": article, "paragraph": m.group("para"),
                        "kind": kind, "number": num,
                        "promulgated": prom_iso, "effective": eff_iso or prom_iso,
                        "span": m.span(), "raw": " ".join(m.group(0).split())})
    return out


def document_reference_date(text: str, *, criminal: bool) -> Dict[str, Any]:
    """법령명과 무관하게 문서에서 기준일(형사: 범행일, 그 밖: 계약·처분·불법행위일)을 하나로 정할 수 있으면 그 날짜."""
    candidates = reference_candidates(text)
    order = ["OFFENSE"] if criminal else ["CONTRACT", "DISPOSITION", "TORT"]
    kind = next((k for k in order if any(c["kind"] == k for c in candidates)), None)
    if kind is None:
        return {"date": None, "basis": "MISSING", "candidates": candidates}
    dates = sorted({c["date"] for c in candidates if c["kind"] == kind})
    if len(dates) == 1:
        chosen = dates[0]
        return {"date": chosen, "basis": "DOCUMENT_INFERRED", "kind": kind, "candidates": candidates,
                "note": f"문서에서 {REFERENCE_KINDS[kind]}로 추정한 {chosen}을 기준일로 썼다(추정 기준일)"}
    # 후보가 둘 이상이면 임의로 하나를 고르지 않고 불확실성을 보존한다(TK-27)
    return {"date": None, "basis": "AMBIGUOUS", "kind": kind, "candidates": candidates, "dates": dates,
            "note": f"문서에서 {REFERENCE_KINDS[kind]} 후보가 여러 개({', '.join(dates)}) 있어 특정하지 않았다"}


def _official_history_check(adapter, declared: Dict[str, Any]) -> Dict[str, Any]:
    """적힌 법령번호·공포일·시행일이 공식 연혁에 있는가. 조회할 수 없으면 UNAVAILABLE(판정하지 않음)."""
    from packages.source_adapters.legal_history import legal_date

    if adapter is None or not hasattr(adapter, "search_law_history"):
        return {"status": "UNAVAILABLE", "reason": "법령 연혁을 조회할 출처가 없음"}
    status = str(adapter.status()) if hasattr(adapter, "status") else "READY"
    if not status.endswith("READY"):
        return {"status": "UNAVAILABLE", "reason": f"국가법령정보 조회 불가({status})"}
    try:
        history = adapter.search_law_history(declared["law_name"])
    except Exception as exc:  # 조회 실패는 판정하지 않는다
        return {"status": "UNAVAILABLE", "reason": f"법령 연혁 조회 오류({type(exc).__name__})"}
    message = getattr(history, "message", "") or ""
    if not getattr(history, "ok", False) or not getattr(history, "complete", False) or message.startswith("EXACT_LAW_NOT_FOUND"):
        return {"status": "UNAVAILABLE", "reason": f"법령 연혁을 확보하지 못함({message or getattr(history, 'status', '')})"}
    rows = history.records or []
    if not rows:
        return {"status": "UNAVAILABLE", "reason": "법령 연혁이 비어 있음"}
    if not declared.get("number"):
        return {"status": "UNAVAILABLE", "reason": "법령번호 없음"}
    wanted = str(int(declared["number"]))
    same_number = [r for r in rows if str(r.get("promulgation_number") or "").strip().lstrip("0") == wanted]
    listed = [{"promulgation_number": r.get("promulgation_number"), "promulgation_date": legal_date(r.get("promulgation_date")),
               "effective_from": legal_date(r.get("effective_from")), "amendment_type": r.get("amendment_type")}
              for r in same_number]
    urls = [getattr(rec, "url", "") for rec in (getattr(history, "source_records", None) or []) if getattr(rec, "url", "")]
    if not same_number:
        return {"status": "NOT_IN_HISTORY", "history_rows": len(rows), "source_urls": urls[:3],
                "reason": f"공식 연혁 {len(rows)}건에 {declared['kind']} 제{declared['number']}호에 의한 개정이 없다"}
    dates_match = any((not declared["promulgated"] or row["promulgation_date"] == declared["promulgated"])
                      and (not declared["effective"] or row["effective_from"] == declared["effective"]) for row in listed)
    return {"status": "MATCH" if dates_match else "DATE_MISMATCH", "history_rows": len(rows), "matches": listed,
            "source_urls": urls[:3]}


def _sentence(value: str) -> str:
    value = (value or "").strip()
    return value if not value or value.endswith(".") else value + "."


def review_declared_amendments(text: str, reference: Dict[str, Any], *, criminal: bool, adapter=None,
                               document_id: Optional[str] = None) -> List[Finding]:
    """서면이 밝힌 시행일이 기준일(행위일) 뒤인 조항을 행위에 적용하라고 주장하는 경우를 알린다."""
    when = reference.get("date")
    basis_type = reference.get("basis")
    candidates = reference.get("candidates", [])
    kind = reference.get("kind")
    candidate_dates = sorted({c["date"] for c in candidates if c.get("kind") == kind}) if kind else []

    findings: List[Finding] = []
    for declared in declared_amendments(text):
        effective = declared["effective"]
        if not effective:
            continue

        # 단일 기준일 vs 복수 기준일 후보 판정
        is_ambiguous = False
        if when:
            if effective <= when:
                continue
            date_label = when
        elif basis_type == "AMBIGUOUS" and candidate_dates:
            # 개정·시행일이 모든 후보보다 뒤인 경우: 근거 강함 (소급 적용 주장 확실)
            if all(effective > d for d in candidate_dates):
                date_label = f"후보 전체({', '.join(candidate_dates)})"
            # 개정·시행일이 일부 후보보다만 뒤인 경우: 불확실 (사람 확인)
            elif any(effective > d for d in candidate_dates):
                is_ambiguous = True
                date_label = f"후보 일부({', '.join(d for d in candidate_dates if effective > d)})"
            else:
                continue
        else:
            continue

        start, end = declared["span"]
        context = text[max(0, start - 80):min(len(text), end + 400)]
        # 구법·행위시법 논의는 개정 이력을 적은 문장부터 뒤에서만 본다(앞 표제의 '행위시법'은 주장이 아니다).
        if not RELIANCE_RE.search(context) or ACT_TIME_LAW_RE.search(text[start:min(len(text), end + 300)]):
            continue
        official = _official_history_check(adapter, declared)
        # TK-04: 조문 번호 포매팅 — '57의3' → '제57조의3' (기존 '제57의3조' 비표준 표기 수정)
        label = f"「{declared['law_name']}」 {_format_article(declared['article'])}" + (
            f" 제{declared['paragraph']}항" if declared.get("paragraph") else "")
        stated = (f"서면이 적은 개정 이력: {declared['promulgated'] or '?'} {declared['kind']} 제{declared['number']}호, "
                  f"{effective} 시행")
        if official["status"] in ("NOT_IN_HISTORY", "DATE_MISMATCH"):
            status, grade, severity = VerificationStatus.CONTRADICTED, EvidenceGrade.A, Severity.HIGH
            official_note = (official["reason"] if official["status"] == "NOT_IN_HISTORY" else
                             "공식 연혁의 같은 번호 개정과 공포일·시행일이 다르다: "
                             + "; ".join(f"{r['promulgation_date']} 공포·{r['effective_from']} 시행" for r in official["matches"]))
            tail = "공식 연혁과 다른 개정 이력에 근거한 소급 적용 주장"
        elif is_ambiguous:
            status, grade, severity = VerificationStatus.UNVERIFIED, EvidenceGrade.B, Severity.MEDIUM
            official_note = ("적힌 개정 이력은 공식 연혁과 일치하나, 기준일 후보가 여럿이어 적용 여부는 사람이 확인해야 한다."
                             if official["status"] == "MATCH" else f"공식 연혁 대조 미실행: {official.get('reason', '')}")
            tail = "기준일 후보 일부 이후 시행 조항에 근거한 주장(기준일 특정 확인 필요)"
        else:
            status, grade, severity = VerificationStatus.SUSPICIOUS, EvidenceGrade.B, Severity.HIGH
            official_note = ("적힌 개정 이력은 공식 연혁과 일치한다. 조문 내용은 인용 검증 결과를 따로 본다."
                             if official["status"] == "MATCH" else f"공식 연혁 대조 미실행: {official.get('reason', '')}")
            tail = "행위 후 시행 조항에 근거한 소급 적용 주장"
        # TK-04: 처분시법주의 및 계약시법주의 분기
        if criminal:
            basis = FAVORABLE_NEW_LAW_BASIS
        elif reference.get("kind") == "DISPOSITION":
            basis = DISPOSITION_TIME_BASIS
        elif reference.get("kind") == "CONTRACT":
            basis = ("계약 관계에 적용되는 법령은 원칙적으로 계약 당시의 법령이고, "
                     "계약 체결·이행 후 개정된 법령을 소급 적용하려면 특별한 경과규정이 있어야 한다(계약시법주의)")
        else:
            basis = CIVIL_TIME_BASIS
        findings.append(Finding.create(
            type=FindingType.TEMPORAL_LAW_MISMATCH, status=status, severity=severity, evidence_grade=grade,
            title=(f"법령 적용 시점 검토: {label} — 시행일 {effective}이 기준일({date_label}, "
                   f"{REFERENCE_KINDS.get(reference.get('kind'), '입력 기준일')}) 뒤인데 {tail} (RETROACTIVE_APPLICATION_ERROR)"),
            detail=" ".join(_sentence(x) for x in (
                stated, reference.get("note") or "", official_note, basis,
                "적힌 조항이 실제로 행위에 적용되는지(유리한 신법·부칙·경과규정)는 법률 판단이므로 결론을 내리지 않는다.") if x),
            confidence=0.85 if status == VerificationStatus.CONTRADICTED else (0.5 if is_ambiguous else 0.7),
            confidence_features={"deterministic_rule": True, "rule_id": "TEMPORAL.POST_OFFENSE_AMENDMENT_RELIANCE",
                                 "defect_code": "RETROACTIVE_APPLICATION_ERROR", "declared": {
                                     k: declared[k] for k in ("law_name", "article", "paragraph", "kind", "number",
                                                              "promulgated", "effective")},
                                 "reference_date": when or candidate_dates, "reference_basis": reference.get("basis"),
                                 "reference_kind": reference.get("kind"), "official_history": official,
                                 "legal_basis": [basis], "human_review": True, "is_ambiguous_candidates": is_ambiguous},
            document_id=document_id, span=declared["span"], engine=ENGINE_NAME,
            tags=["LEGAL", "STATUTE", "TEMPORAL", "RETROACTIVE_APPLICATION_ERROR"],
            evidence=[Evidence.create(description="서면의 개정 이력 기재", grade=EvidenceGrade.B,
                                      document_id=document_id, excerpt=declared["raw"][:300], supports=False)]
            + ([Evidence.create(description="국가법령정보 법령 연혁 대조", grade=EvidenceGrade.A,
                                excerpt=official_note[:300])] if official["status"] in ("NOT_IN_HISTORY", "DATE_MISMATCH", "MATCH") else []),
        ))
    return findings
