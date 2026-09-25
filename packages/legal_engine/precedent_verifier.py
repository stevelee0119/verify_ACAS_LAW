"""판례 판시 요지 왜곡(CIT-MIS) 및 법령 인용문 변형(QUOTE-MOD) 검증 모듈.

인용된 판례의 실제 판시 취지와 서면의 주장이 정반대인 경우(CIT-MIS)를 탐지하고,
따옴표로 인용된 법령 조문이 실제 원문과 임의 변형된 경우(QUOTE-MOD)를 탐지한다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Citation, Evidence, Finding, NormalizedDocument
from packages.common.confidence import score as confidence_score
from packages.document_engine.reading_text import build_reading_text

ENGINE_NAME = "legal_engine.precedent_verifier"

# 주요 리딩 판례의 표준 판시 취지 및 왜곡 패턴 룰베이스
# (모든 규칙은 일반적인 법리 범주와 표준 법률 개념을 기반으로 구성됨)
LEADING_PRECEDENTS: List[Dict[str, Any]] = [
    {
        "case_number_pattern": r"2019두52386",
        "title": "대법원 2020. 2. 20. 선고 2019두52386 전원합의체 판결",
        "topic": "근로관계 종료 후 부당해고 구제이익",
        "true_holding": "근로자가 부당해고 구제신청을 하여 해고의 효력을 다투던 중 정년에 도달하거나 근로계약기간 만료 등으로 근로관계가 종료된 경우라도, 원직복직은 불가능하지만 해고기간 중의 임금 상당액을 지급받을 필요가 있다면 구제신청을 기각한 재결의 취소를 구할 법률상 이익이 있다.",
        "distortion_patterns": [
            re.compile(r"(?:임금\s*(?:상당액)?|금전적\s*보상)[^.\n]{0,50}(?:필요|청구)[^.\n]{0,30}(?:구제이익|소의\s*이익|소송상\s*이익)[^.\n]{0,20}(?:소멸|없|배제|인정되지\s*않|부정)"),
            re.compile(r"(?:근로관계\s*(?:가\s*)?종료|정년\s*(?:에\s*)?도달|기간\s*(?:이\s*)?만료)[^.\n]{0,50}(?:무조건|언제나|예외\s*없이|임금\s*불문|구제명령|원직복직|받을\s*수\s*없)[^.\n]{0,30}(?:구제이익|소의\s*이익|소송상\s*이익)[^.\n]{0,20}(?:소멸|없|배제|부정)"),
            re.compile(r"(?:정년\s*도달|근로관계\s*종료)[^.\n]{0,50}(?:구제이익|소의\s*이익)[^.\n]{0,20}(?:소멸|없|배제|부정)"),
        ],
        "explanation": "대법원 2019두52386 전원합의체 판결은 원직복직이 불가능하더라도 해고기간 중의 '임금 상당액을 지급받을 필요'가 있으면 구제이익이 유지된다고 판시하였습니다. 서면의 주장은 판례의 취지와 정반대입니다.",
    },
    {
        "case_number_pattern": r"2020다247190",
        "title": "대법원 2024. 12. 19. 선고 2020다247190 전원합의체 판결",
        "topic": "재직조건부 정기상여금과 통상임금 판단 기준",
        "reference_url": "https://www.scourt.go.kr/sjudge/1734594587787_164947.pdf",
        "true_holding": "통상임금의 판단 기준에서 고정성을 제외하고 소정근로 대가성·정기성·일률성을 기준으로 판단한다. 순수한 실적 성과급과 소정근로의 대가인 임금을 구별하며, 판례 변경의 적용 시점도 별도로 검토해야 한다.",
        "distortion_patterns": [
            re.compile(r"(?:성과급|경영성과급|인센티브)[^.\n]{0,40}(?:모든\s*금품|일체의\s*급여|예외\s*없이)[^.\n]{0,30}(?:통상임금에\s*해당|통상임금에\s*포함|통상임금으로\s*인정)"),
            re.compile(r"(?:성과급|경영성과급)[^.\n]{0,40}(?:무조건|당연히|원칙적으로)[^.\n]{0,20}(?:통상임금)"),
        ],
        "explanation": "임금 항목의 명칭만으로 통상임금성을 일률적으로 판단하지 않고 지급 조건·소정근로 대가성과 판례 적용 시점을 확인해야 합니다.",
    },
    {
        "case_number_pattern": r"2015두41401",
        "title": "대법원 2015. 9. 10. 선고 2015두41401 판결",
        "topic": "이메일·전자문서에 의한 해고통지의 유효 요건",
        "true_holding": "이메일에 의한 해고통지는 해고사유와 해고시기가 구체적으로 기재되어 있고 근로자가 이를 수령·확인할 수 있는 등 서면에 의한 통지의 취지를 충족하는 특별한 사정이 있는 경우에 한하여 유효하다.",
        "distortion_patterns": [
            re.compile(r"(?:이메일|전자우편|문자|메시지|카카오톡)[^.\n]{0,40}(?:형식[·ㆍ\s]*내용\s*불문|어떠한\s*경우에도|무조건|언제나)[^.\n]{0,20}(?:유효|적법)"),
            re.compile(r"(?:이메일|문자|카톡)[^.\n]{0,30}(?:통지|발송)[^.\n]{0,20}(?:무조건|당연히)\s*(?:유효|도달)"),
        ],
        "explanation": "대법원 2015두41401 판결은 이메일 해고통지에 대해 해고사유·시기의 구체적 기재 및 열람 확인 등 엄격한 요건 하에서만 예외적 효력을 인정합니다. '형식·내용 불문 언제나 유효'하다는 주장은 판례 취지와 어긋납니다.",
    },
]

# 주요 법조문 표준 문구 캐시 (QUOTE-MOD 탐지용)
STANDARD_STATUTE_TEXTS: Dict[str, Dict[str, str]] = {
    "근로기준법": {
        "27": "제27조(해고사유 등의 서면통지) ① 사용자는 근로자를 해고하려면 해고사유와 해고시기를 서면으로 통지하여야 한다. ② 해고는 제1항에 따라 서면으로 통지하여야 효력이 있다.",
        "23": "제23조(해고 등의 제한) ① 사용자는 근로자에게 정당한 이유 없이 해고, 휴직, 정직, 전직, 감봉, 그 밖의 징벌(懲罰)(이하 \"부당해고등\"이라 한다)을 하지 못한다.",
        "37": "제37조(미지급 임금에 대한 지연이자) ① 사용자는 제36조에 따라 지급하여야 하는 임금 및 「근로자퇴직급여 보장법」 제2조제5호에 따른 급여의 전부 또는 일부를 그 지급 사유가 발생한 날부터 14일 이내에 지급하지 아니한 경우 그 다음 날부터 지급하는 날까지의 지연일수에 대하여 연 100분의 20의 범위에서 대통령령으로 정하는 이율에 따른 지연이자를 지급하여야 한다.",
    },
    "민법": {
        "750": "제750조(불법행위의 내용) 고의 또는 과실로 인한 위법행위로 타인에게 손해를 가한 자는 그 손해를 배상할 책임이 있다.",
        "390": "제390조(채무불이행과 손해배상) 채무자가 채무의 내용에 좇은 이행을 하지 아니한 때에는 채권자는 손해배상을 청구할 수 있다. 그러나 채무자의 고의나 과실없이 이행할 수 없게 된 때에는 그러하지 아니하다.",
    }
}

_QUOTE_EXTRACT_RE = re.compile(r'["“]([^"”]{5,200})["”]')


def _get_doc_text(doc: NormalizedDocument) -> str:
    """NormalizedDocument에서 텍스트를 안전하게 추출한다."""
    return build_reading_text(doc).text


def verify_precedent_distortions(doc: NormalizedDocument, citations: Optional[List[Citation]] = None) -> List[Finding]:
    """판례 인용 주변 문맥을 분석하여 판시 취지 왜곡(CIT-MIS)을 탐지한다."""
    findings: List[Finding] = []
    text = _get_doc_text(doc)

    for rule in LEADING_PRECEDENTS:
        pat = rule["case_number_pattern"]
        if not re.search(pat, text):
            continue

        # 판례 번호 주변 문단/문장 탐색
        for match in re.finditer(pat, text):
            start = max(0, match.start() - 300)
            end = min(len(text), match.end() + 300)
            context_window = text[start:end]

            for dist_re in rule["distortion_patterns"]:
                m = dist_re.search(context_window)
                if m:
                    claim_snippet = m.group(0)
                    features = {
                        "precedent_distortion": True,
                        "case_number_pattern": pat,
                        "defect_code": "CIT-MIS",
                        "topic": rule["topic"],
                        "source_verified": False,
                    }
                    findings.append(
                        Finding.create(
                            type=FindingType.CASE_HOLDING_DISTORTION,
                            status=VerificationStatus.UNVERIFIED,
                            severity=Severity.MEDIUM,
                            evidence_grade=EvidenceGrade.C,
                            advisory_only=True,
                            title=f"판례 취지 대조 필요(CIT-MIS): {rule['title']} — '{claim_snippet[:50]}'",
                            detail=(f"'{claim_snippet}'에 해당하는 검토 후보를 찾았습니다. 공식 원문과 적용 시점을 "
                                    f"확인하지 않아 왜곡을 확정하지 않습니다. 검토 주제: {rule['topic']}"),
                            confidence=confidence_score(features),
                            confidence_features=features,
                            document_id=doc.document_id,
                            engine=ENGINE_NAME,
                            tags=["LEGAL", "CASE", "CIT-MIS", "DISTORTION"],
                            evidence=[
                                Evidence.create(
                                    description="서면의 왜곡 주장 문맥",
                                    grade=EvidenceGrade.B,
                                    document_id=doc.document_id,
                                    excerpt=context_window[:300],
                                    supports=False,
                                ),
                                Evidence.create(
                                    description="정적 참고 요약(공식 원문 미검증)",
                                    grade=EvidenceGrade.C,
                                    excerpt=rule["true_holding"][:300],
                                ),
                            ],
                        )
                    )
                    break

    return findings


def verify_statute_quotes(doc: NormalizedDocument, citations: Optional[List[Citation]] = None) -> List[Finding]:
    """법령 조문 인용 시 따옴표 내 인용구가 실제 조문과 임의 변형되었는지(QUOTE-MOD) 탐지한다."""
    findings: List[Finding] = []
    text = _get_doc_text(doc)

    if citations is None:
        from packages.legal_engine.citation_extractor import extract_from_text
        citations = extract_from_text(text)

    for cit in citations:
        cit_type_str = cit.type.value if hasattr(cit.type, "value") else str(cit.type)
        if cit_type_str != "STATUTE" or not cit.law_name or not cit.article:
            continue

        law_clean = re.sub(r"[\s\-_ㆍ·「」『』\[\]()]+", "", cit.law_name)
        art_clean = re.sub(r"[^\d]", "", str(cit.article))

        std_dict = None
        for k, v in STANDARD_STATUTE_TEXTS.items():
            if k == law_clean:
                std_dict = v
                break

        if not std_dict or art_clean not in std_dict:
            continue

        std_text = std_dict[art_clean]

        # 해당 인용 주변 150자 내의 따옴표 인용구 추출
        if cit.span and len(cit.span) == 2:
            start = max(0, cit.span[0] - 100)
            end = min(len(text), cit.span[1] + 150)
            window = text[start:end]
        else:
            window = text

        # Only a quote attached to this citation can be compared with its text.
        quoted_text = cit.quoted_text
        if not quoted_text:
            attached = re.search(re.escape(cit.raw_text) + r'\s*(?:은|는|에\s*따르면)?\s*["“]([^"”]{8,200})["”]', window)
            quoted_text = attached.group(1) if attached else None
        for m in _QUOTE_EXTRACT_RE.finditer('"' + quoted_text + '"' if quoted_text else ""):
            quoted = m.group(1).strip()
            if len(quoted) < 8:
                continue

            q_norm = re.sub(r"\s+", "", quoted)
            std_norm = re.sub(r"\s+", "", std_text)

            # 따옴표 인용구가 표준 조문 원문과 일치하지 않는 경우
            if q_norm not in std_norm:
                features = {
                    "statute_quote_modified": True,
                    "defect_code": "QUOTE-MOD",
                    "law_name": cit.law_name,
                    "article": cit.article,
                    "source_verified": False,
                }
                findings.append(
                    Finding.create(
                        type=FindingType.STATUTE_TEXT_MISMATCH,
                        status=VerificationStatus.UNVERIFIED,
                        severity=Severity.MEDIUM,
                        evidence_grade=EvidenceGrade.C,
                        advisory_only=True,
                        title=f"법조문 인용문구 대조 필요(QUOTE-MOD): {cit.law_name} 제{cit.article}조",
                        detail=(f"인용문구 '{quoted[:60]}'가 정적 참고문구와 다릅니다. 해당 시점의 공식 조문을 "
                                "확보하지 않아 변형 여부를 확정하지 않습니다."),
                        confidence=confidence_score(features),
                        confidence_features=features,
                        document_id=doc.document_id,
                        engine=ENGINE_NAME,
                        tags=["LEGAL", "STATUTE", "QUOTE-MOD"],
                        evidence=[
                            Evidence.create(
                                description="서면의 변형 인용구",
                                grade=EvidenceGrade.B,
                                document_id=doc.document_id,
                                excerpt=quoted[:300],
                                supports=False,
                            ),
                            Evidence.create(
                                description="정적 참고문구(공식 원문 미검증)",
                                grade=EvidenceGrade.C,
                                excerpt=std_text[:300],
                            ),
                        ],
                    )
                )

    return findings
