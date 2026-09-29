"""제8장 개인정보 탐지 및 비식별화.

사건번호·판례번호·법령번호와 같이 법률 검증에 필요한 식별자를 오탐하지 않도록
도메인 규칙(Guard)을 둔다.
"""
from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# 법률 식별자 Guard — 이 패턴에 걸리는 구간은 PII로 마스킹하지 않는다
# ---------------------------------------------------------------------------
LEGAL_IDENTIFIER_PATTERNS = [
    re.compile(r"\d{4}\s*[가-힣]{1,3}\s*\d{1,6}"),          # 사건번호 2023도12345, 2026가합1234
    re.compile(r"\d{4}\s*헌[가-힣]\s*\d{1,4}"),              # 헌재 사건번호
    re.compile(r"제\s*\d+\s*조(\s*의\s*\d+)?"),               # 법령 조문
    re.compile(r"제\s*\d+\s*[항호]"),
    re.compile(r"법률\s*제\s*\d+\s*호"),
    re.compile(r"대통령령\s*제\s*\d+\s*호"),
    re.compile(r"등기\s*번호|등록\s*번호\s*제"),
    re.compile(r"\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.?"),          # 선고일자
    re.compile(r"\b(19|20)\d{2}\b"),                            # 연도
    re.compile(r"(?:계약번호\s*)?제\s*[\d]{4}-[가-힣A-Za-z0-9]+-\d+호?"), # 계약번호
    re.compile(r"(?:사업자|법인)(?:등록)?번호\s*[:：]?\s*[\d\-]+"),         # 사업자/법인등록번호 라벨 문맥
]

# 법인등록번호·사업자등록번호는 사건 검증에 쓰이므로 기본 마스킹 대상에서 제외한다
BUSINESS_NO_RE = re.compile(r"\b\d{3}-\d{2}-\d{5}\b")
CORP_NO_RE = re.compile(r"\b\d{6}-\d{7}\b")
CORP_LABEL_PREFIX_RE = re.compile(r"(?:법인(?:등록)?번호|법인등기번호)\s*[:：]?\s*$")
RRN_LABEL_PREFIX_RE = re.compile(r"(?:주민등록번호|주민번호)\s*[:：]?\s*$")



@dataclass
class PIIMatch:
    kind: str
    text: str
    start: int
    end: int
    block_id: Optional[str] = None
    page: Optional[int] = None
    confidence: float = 1.0
    context_note: str = ""


# ---------------------------------------------------------------------------
# 규칙 기반 탐지기
# ---------------------------------------------------------------------------
# OCR 본문은 '800101 - 1234567'처럼 하이픈 앞뒤에 공백이 붙는다. 한 글자만 허용하면
# 이런 번호가 가려지지 않은 채 외부 모델로 나갔고, 모델이 정돈해 되돌려 준 번호 때문에
# 응답이 출력 검사에서 격리됐다. 줄바꿈은 넘지 않는다.
# 외국인등록번호 및 가상/변형 번호(9로 시작 등)까지 포괄하도록 [1-9]로 확장한다.
RRN_RE = re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})[ \t]*[-–]?[ \t]*([1-9])(\d{6})(?!\d)")
# 뒷자리가 별표 등으로 일부 마스킹된 주민등록번호(예: 780512-1******)
RRN_MASKED_RE = re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})[ \t]*[-–]?[ \t]*([1-9])([*●xX]{6})(?!\d)")
# 주민등록번호 라벨이 명시된 문맥에서는 뒷자리 첫 글자와 관계없이 13자리 번호 또는 마스킹 번호를 개인정보로 포착한다.
RRN_LABELLED_RE = re.compile(r"(?:주민등록번호|주민번호)\s*[:：]?\s*(\d{2}\d{2}\d{2}[ \t]*[-–]?[ \t]*[\d*●xX]{7})(?!\d)")
PHONE_RE = re.compile(r"(?<!\d)(01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}|0\d{1,2}[-\s.]?\d{3,4}[-\s.]?\d{4})(?!\d)")
# 차량번호: "12가 3456", "345나 7890", "서울 12가 3456" 등 (일반 명사 '차량' 오탐 방지 및 조사 허용)
VEHICLE_RE = re.compile(
    r"(?<![0-9])(?:(?:서울|경기|인천|강원|충북|충남|전북|전남|경북|경남|제주|부산|대구|광주|대전|울산|세종)\s*)?"
    r"\d{2,3}\s*[가-힣]\s*\d{4}(?=[을를은는이가의에도만로]|으로|\s|[.,!?()~-]|$)(?![0-9])"
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
ACCOUNT_RE = re.compile(r"(?<!\d)\d{2,3}[-\s]\d{2,6}[-\s]\d{2,6}(?:[-\s]\d{1,6})?(?!\d)")
MILITARY_ID_RE = re.compile(
    r"(?:군번\s*[:\s]?\s*)(\d{2}[-\s]?\d{5,8})(?![0-9])|"
    r"(?<![0-9A-Za-z])(\d{2}-\d{5,8})(?![0-9])|"
    r"(?<![0-9A-Za-z])\d{2}[-\s]?\d{8}(?![0-9])|"
    r"(?<![A-Za-z])[가-힣]?\d{7,8}(?=\s*군번)"
)
PASSPORT_RE = re.compile(r"\b[MSRODmsrod]\d{8}\b")
DOB_RE = re.compile(
    r"(?:19|20)\d{2}\s*[.\-년]\s*\d{1,2}\s*[.\-월]\s*\d{1,2}\s*[.\-일\s]?\s*(?:생|출생|일생)|"
    r"(?:생년월일|출생일)\s*[:\s]?\s*(?:19|20)\d{2}\s*[.\-년]\s*\d{1,2}\s*[.\-월]\s*\d{1,2}\s*[.\-일]?"
)
# 지명 앞부분의 길이를 제한한다. '[가-힣]+' 뒤에 '시|군|구'를 찾게 하면 한글이 길게
# 이어진 구간에서 시작 위치마다 끝까지 되짚어 비용이 길이의 제곱으로 늘었다.
# 3MB 검증 결과 한 건에 25초가 걸려 보고서 생성 요청이 끊겼다. 실제 시·도명은
# 2~4자, 시·군·구명은 1~5자, 도로·동명은 숫자를 포함해도 20자를 넘지 않는다.
ADDRESS_RE = re.compile(
    r"(?:[가-힣]{1,6}(?:특별시|광역시|특별자치시|도|특별자치도)\s*)?"
    r"[가-힣]{1,8}(?:시|군|구)\s+[가-힣0-9]{1,20}(?:읍|면|동|가|로|길)\s*[\d\-]*(?:번지|호)?"
    r"(?:\s*,\s*|\s+)?(?:\d{1,4}동\s*\d{1,4}호|\d{1,4}호|\d{1,3}층|[가-힣0-9]{1,15}(?:아파트|빌라|오피스텔|마을|단지|타운|맨션)(?:\s*\d{1,4}동\s*\d{1,4}호)?)?"
)
# 이름 뒤에 붙는 조사를 이름으로 오인하지 않도록 조사 목록을 두고 non-greedy로 잡는다.
JOSA = r"(?:은|는|이|가|을|를|과|와|의|에게서|에게|에서|에|도|만|께서|께|으로|로|라고|이라고)"

# 한 글자 친족 호칭(부, 모, 처, 자)은 '부대는', '부사관이', '처분은' 등의 일반 법률/군사용어 오탐을 막기 위해
# 반드시 한자 괄호나 공백이 뒤따르는 독립된 문맥에서만 매칭한다.
# 법인/계약 문서의 대표이사, 대표자, 대표 호칭을 추가하여 대표자 성명을 보호한다.
PREFIX_MULTI = r"(?:원고|피고인|피고|참고인|피의자|증인|고소인|고발인|신청인|피신청인|채권자|채무자|망|소외|배우자|자녀|남편|아들|딸|가족|대리인|대표이사|대표자|대표|지배인)"
PREFIX_SINGLE = r"(?:[부모처자](?:\s*[(（][父母妻子][)）])|\b[부모처자]\b)"

NAME_RE = re.compile(
    rf"(?<![가-힣])(?:{PREFIX_MULTI}[ \t]+|{PREFIX_SINGLE}[ \t]+)"
    r"([가-힣]{2,4}?)(?:\s*\([^)]+\))?" + JOSA + r"?(?![가-힣])"
)
LABELLED_NAME_RE = re.compile(
    r"(?<![가-힣])(?:대표이사|대표자|성명|서명자)[ \t]*(?:[:：|][ \t]*|[(（][ \t]*|[ \t]+|\r?\n[ \t]*)"
    r"([가-힣]{2,4}?)(?=[ \t]*(?:[)）|,.;\n]|$)|[ \t]+(?:서명|인|귀하))"
)

# 정상적인 법률·행정·군사·계약용어가 인명(PERSON)으로 과잉 마스킹되는 것을 방지하기 위한 Stopword 목록
LEGAL_MILITARY_STOPWORDS = {
    "부대", "부사관", "처분", "행정청", "처분청", "지휘관", "사단장", "연대장", "대대장",
    "중대장", "소대장", "징계권자", "심사위원회", "소청심사", "인사위원회", "국방부", "육군본부",
    "해군본부", "공군본부", "사령부", "행정소송", "불복", "사유", "내용", "결과", "사실", "기준",
    "원처분", "징계처분", "재심사", "위원회", "보수", "호봉", "진급", "임용", "복무", "휴직",
    "육아휴직", "평정", "근무평정", "평가", "점수", "가점", "감점", "신청", "이의신청", "심사",
    "의결", "조사", "수사", "군사경찰", "검찰", "군검사", "법무관", "재판부", "법원", "대법원",
    "고등법원", "지방법원", "행정법원", "군사법원", "헌법재판소", "국가", "대한민국", "참모총장",
    "장관", "차관", "총장", "사령관", "군단장", "여단장", "함대사령관", "비행단장", "작위", "부작위",
    "기산점", "제소기간", "불복절차", "행정심판", "입증방법", "서증", "호증", "변론", "판결", "결정",
    # 계약·물품 납품·검수·금융·소송 관련 명사 (PERSON 과잉 마스킹 방지)
    "목적물", "대금조항", "계약금액", "지체상금", "납품기한", "포장상태", "물품", "검수", "입고",
    "납품", "검사원", "검사관", "감독관", "하자보수", "계약조건", "특약사항", "이행보증", "보증금",
    "계좌", "통장", "명의", "소유", "주소", "은행", "청구", "주장", "답안", "답안과", "소송", "서면", "기록", "답변",
    # 공정·물품·계약·보안 관련 비인명 명사 (PERSON 오탐 원천 방지)
    "보안", "인수", "완제품", "안전", "위생", "반입", "정산", "확인", "시스템",
}
# 의료/질병 및 투약/처방 민감정보 탐지:
# '암기용', '암산' 등의 일반 단어가 '암'으로 오탐되지 않도록 단어 경계(?![가-힣])를 두고,
# 임의의 앞 문자열이 질병명에 과도하게 포함되지 않도록 질병 수식어 범위를 의학적 어휘로 한정한다.
CANCER_PREFIXES = r"(?:위|간|폐|대장|유방|췌장|갑상선|혈액|자궁|난소|전립선|뇌|신장|담도|후두|식도|피부|혈액|골수|직장|방광|설|구강)"
DISEASE_NAMES = (
    r"(?:천식|수면장애|우울증|불안장애|공황장애|조현병|외상후스트레스|PTSD|적응장애|당뇨|고혈압|디스크|골절|"
    rf"{CANCER_PREFIXES}\s*암|(?<![가-힣])암(?![가-힣])|종양|알츠하이머|비염|폐렴)"
)
MEDICAL_DIAGNOSIS_RE = re.compile(
    r"(?:진단|치료|투병|질환|질병|증상|환자|진료기록상)?\s*(?:소아청소년과|내과|외과|이비인후과|정신건강의학과|정형외과|안과|피부과)?\s*(?:에서)?\s*"
    rf"((?:(?:만성|급성|중증|악성|양성|원발성|전이성|초기|말기)\s*)?{DISEASE_NAMES}"
    rf"(?:(?:\s*(?:및|또는|과|와)\s*){DISEASE_NAMES})?"
    r"(?:\s*(?:치료|투병|진단|증상|환자))?)"
)
MEDICAL_PRESCRIPTION_RE = re.compile(
    r"(?:처방|복용|투약|약제|약품|약물)\s*(?:내역|기록|은|는|이|가|:\s*)?\s*"
    r"([가-힣A-Za-z0-9\s,·~]+?(?:\d+(?:\.\d+)?\s*(?:mg|g|ml|정|포|캡슐|회|일분)|흡입액|복용약|주사액)[가-힣A-Za-z0-9\s,·~]*)"
)
# 법인 표기. 조사·부사로 끝나는 앞말을 상호로 오인하지 않도록 stopword를 둔다.
COMPANY_SUFFIX_RE = re.compile(r"(?<![가-힣])([가-힣A-Za-z0-9]{2,10})[ \t]*(?:주식회사|㈜|유한회사|합자회사)")
COMPANY_PREFIX_RE = re.compile(r"(?:주식회사|유한회사|합자회사)[ \t]+([가-힣A-Za-z0-9]{1,20})|㈜[ \t]*([가-힣A-Za-z0-9]{1,20})")
COMPANY_STOPWORDS = {
    "따라", "대하여", "관하여", "위하여", "의하여", "그리고", "그러나", "다만", "또한",
    "상대로", "대한", "관한", "위한", "의한", "있는", "없는", "같은", "해당", "본건",
    "목적물", "대금조항", "계약조건", "특약사항", "지체상금", "납품대금", "물품명세",
}

# 물품/공정 검사(Inspection) 명사는 직함 '검사(Prosecutor)'와 구별하여 PERSON 오탐을 방지한다
# 보안 검사, 인수 검사, 납품 검사, 완제품 검사, 서류 검사 등 공정/기술 검사 포함
INSPECTION_NOUNS = {
    "포장상태", "물품", "외관", "품질", "성능", "정밀", "현장", "서류", "합격", "규격", "가공", "검수",
    "보안", "인수", "납품", "완제품", "안전", "위생", "정기", "최종", "확인", "시스템", "입고", "출고", "반입", "전량", "수량", "온도",
}

NAME_TITLE_RE = re.compile(
    rf"(?<![가-힣])([가-힣]{{2,4}})[ \t]*(?:씨|군|양|변호사|검사|판사|사무관|대위|중위|소령|중령|대령|병장|상병|일병|이병)(?:{JOSA})?(?![가-힣])"
)


DETECTORS: List[Tuple[str, re.Pattern[str], float]] = [
    ("RRN", RRN_RE, 1.0),
    ("RRN", RRN_MASKED_RE, 0.95),
    ("EMAIL", EMAIL_RE, 1.0),
    ("PHONE", PHONE_RE, 0.95),
    ("PASSPORT", PASSPORT_RE, 0.8),
    ("MILITARY_ID", MILITARY_ID_RE, 0.85),
    ("ACCOUNT", ACCOUNT_RE, 0.6),
    ("DOB", DOB_RE, 0.9),
    ("ADDRESS", ADDRESS_RE, 0.85),
    ("VEHICLE", VEHICLE_RE, 0.9),
]

RRN_WEIGHTS = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]


def validate_rrn(digits: str) -> bool:
    """주민등록번호 검증부호 확인. 오탐을 줄이되 실패해도 탐지는 유지한다."""
    if len(digits) != 13 or not digits.isdigit():
        return False
    total = sum(int(d) * w for d, w in zip(digits[:12], RRN_WEIGHTS))
    return (11 - (total % 11)) % 10 == int(digits[12])


def legal_identifier_spans(text: str) -> List[Tuple[int, int]]:
    """법률 식별자 구간을 한 번만 찾아 병합해 둔다.

    종전에는 탐지 결과 하나마다 본문 전체를 다시 훑었다. 본문이 길고 숫자가
    많을수록 비용이 제곱으로 늘어, 수백 KB짜리 검증 결과에서는 한 번의 호출이
    수십 초에서 수 분까지 걸렸다. 구간을 미리 구해 두면 같은 판정을 선형
    시간에 내릴 수 있다.
    """
    spans: List[Tuple[int, int]] = []
    for pattern in LEGAL_IDENTIFIER_PATTERNS:
        spans.extend(m.span() for m in pattern.finditer(text))
    if not spans:
        return []
    spans.sort()
    merged: List[Tuple[int, int]] = [spans[0]]
    for start, end in spans[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:  # 겹치거나 맞닿으면 합친다
            if end > last_end:
                merged[-1] = (last_start, end)
        else:
            merged.append((start, end))
    return merged


def _covered_by_span(spans: List[Tuple[int, int]], start: int, end: int) -> bool:
    """[start, end)가 어느 식별자 구간 안에 온전히 들어가는지 본다."""
    if not spans:
        return False
    index = bisect_right(spans, (start, float("inf"))) - 1
    if index < 0:
        return False
    span_start, span_end = spans[index]
    return span_start <= start and end <= span_end


def detect(text: str, *, block_id: Optional[str] = None, page: Optional[int] = None) -> List[PIIMatch]:
    """텍스트에서 개인정보 후보를 찾는다."""
    matches: List[PIIMatch] = []
    if not text:
        return matches

    guard_spans = legal_identifier_spans(text)
    for kind, pattern, base_confidence in DETECTORS:
        for m in pattern.finditer(text):
            start, end = m.start(), m.end()
            if _covered_by_span(guard_spans, start, end):
                continue
            raw = m.group(0)
            confidence = base_confidence
            note = ""
            if kind == "RRN":
                prefix_context = text[max(0, start - 20):start]
                # 법인번호 라벨이 앞서 붙어 있는 경우 법인식별자이므로 RRN에서 제외
                if CORP_LABEL_PREFIX_RE.search(prefix_context) and not RRN_LABEL_PREFIX_RE.search(prefix_context):
                    continue
                digits = re.sub(r"\D", "", raw)
                if validate_rrn(digits):
                    confidence = 1.0
                    note = "검증부호 일치"
                else:
                    confidence = 0.8
                    note = "형식 일치, 검증부호 불일치"
            if kind == "ACCOUNT":
                if BUSINESS_NO_RE.fullmatch(raw.strip()):
                    continue  # 사업자등록번호는 법인 식별에 필요
                if CORP_NO_RE.fullmatch(raw.strip()):
                    continue  # 법인등록번호
            matches.append(PIIMatch(kind, raw, start, end, block_id, page, confidence, note))

    # 주민등록번호 라벨이 명시된 13자리 번호(변형/외국인/합성 포함) 포착
    for m in RRN_LABELLED_RE.finditer(text):
        start, end = m.start(1), m.end(1)
        if _covered_by_span(guard_spans, start, end):
            continue
        raw = m.group(1)
        matches.append(PIIMatch("RRN", raw, start, end, block_id, page, 0.95, "주민등록번호 라벨 문맥"))

    for pattern, kind in ((NAME_RE, "PERSON"), (NAME_TITLE_RE, "PERSON"), (LABELLED_NAME_RE, "PERSON")):
        for m in pattern.finditer(text):
            name = m.group(1).strip()
            start, end = m.start(1), m.end(1)
            if _covered_by_span(guard_spans, start, end):
                continue
            if name in LEGAL_MILITARY_STOPWORDS:
                continue
            if pattern is NAME_TITLE_RE:
                full_matched = m.group(0)
                # "포장상태 검사", "물품 검사" 등 공정·물품 검사(Inspection)인 경우 PERSON 제외
                if "검사" in full_matched and any(word in full_matched or word in name for word in INSPECTION_NOUNS):
                    continue
                # 직함 앞 단어가 조사(과, 와, 은, 는, 이, 가, 을, 를, 의, 에, 로, 도, 만, 에게)로 끝나면 인명이 아니므로 제외
                if re.search(r"(?:과|와|은|는|이|가|을|를|의|에|로|도|만|에게)$", name):
                    continue
            matches.append(PIIMatch(kind, name, start, end, block_id, page, 0.75, "직함·당사자·가족 표기 문맥"))

    for pattern in (MEDICAL_DIAGNOSIS_RE, MEDICAL_PRESCRIPTION_RE):
        for m in pattern.finditer(text):
            idx = 1 if (m.lastindex and m.group(1)) else 0
            med_text = (m.group(idx) or "").strip()
            if not med_text:
                continue
            start, end = m.start(idx), m.end(idx)
            if _covered_by_span(guard_spans, start, end):
                continue
            matches.append(PIIMatch("MEDICAL", med_text, start, end, block_id, page, 0.85, "질병·처방 등 민감 의료정보"))

    for pattern in (COMPANY_SUFFIX_RE, COMPANY_PREFIX_RE):
        for m in pattern.finditer(text):
            # 선택지가 여럿인 패턴에서는 실제로 매치된 그룹의 위치를 써야 한다.
            # 무조건 group(1)의 위치를 쓰면 "㈜라마바"처럼 뒤쪽 선택지가 매치된
            # 경우 위치가 (-1, -1)로 남아 마스킹이 엉뚱한 곳을 가린다.
            index = next((i for i in range(1, (m.re.groups or 0) + 1) if m.group(i) is not None), None)
            if index is None:
                continue
            name = (m.group(index) or "").strip()
            if not name or name in COMPANY_STOPWORDS:
                continue
            matches.append(PIIMatch("COMPANY", name, m.start(index), m.end(index),
                                    block_id, page, 0.8, "법인 표기"))

    # 중복 span 정리 (긴 매치 우선).
    # start 오름차순이므로 앞선 항목의 start는 모두 현재 start 이하다. 따라서
    # "감싸는 항목이 있는가"는 지금까지 본 end의 최댓값 하나로 판정된다.
    # 매번 전체를 다시 훑으면 탐지 결과가 많을 때 비용이 제곱으로 늘어난다.
    matches.sort(key=lambda x: (x.start, -(x.end - x.start)))
    deduped: List[PIIMatch] = []
    covered_until = float("-inf")
    for match in matches:
        if match.end <= covered_until:
            continue
        deduped.append(match)
        covered_until = max(covered_until, match.end)
    return deduped
