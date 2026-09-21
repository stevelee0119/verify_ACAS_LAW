"""제7.2장 누락 탐지 체크리스트.

쟁점이 나오면 그 쟁점에서 통상 함께 검토하는 항목을 제시하고, 문서가
다루지 않은 항목을 "누락 후보"로 표시한다.

체크리스트 매칭만으로 법률 결론을 확정하지 않는다(제7.2장 단서). 이 모듈은
"이 문서는 위법하다"고 말하지 않고 "재원 항목이 문서에 보이지 않는다"고만
말한다. 확정은 담당 변호사의 몫이다.

참조 조문은 검토의 출발점으로 제시하는 것이며, 적용 여부와 현행 문언은
국가법령정보센터 원문으로 확인해야 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from packages.common.enums import (
    EvidenceGrade,
    FindingType,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import Finding

ENGINE_NAME = "legal_engine.omission"


@dataclass
class ChecklistItem:
    key: str
    label: str
    keywords: Sequence[str]
    reference: str = ""

    def mentioned(self, text: str) -> bool:
        compact = re.sub(r"\s+", "", text)
        return any(re.sub(r"\s+", "", k) in compact for k in self.keywords)

    def to_dict(self) -> Dict[str, Any]:
        return {"key": self.key, "label": self.label, "reference": self.reference}


@dataclass
class Checklist:
    issue: str
    triggers: Sequence[str]
    items: Sequence[ChecklistItem]
    severity: Severity = Severity.HIGH

    def triggered(self, text: str) -> bool:
        compact = re.sub(r"\s+", "", text)
        return any(re.sub(r"\s+", "", t) in compact for t in self.triggers)


# 제7.2장이 예로 든 세 쟁점. 항목 구성은 명세의 열거를 그대로 옮겼다.
CHECKLISTS: List[Checklist] = [
    Checklist(
        issue="자기주식 취득",
        triggers=("자기주식", "자기 주식", "자사주", "회사가 매수", "회사가 전량 매수",
                  "회사가 취득", "회사 명의로 취득"),
        items=[
            ChecklistItem("재원", "취득 재원(배당가능이익 등)",
                          ("배당가능이익", "재원", "이익잉여금", "순자산"), "상법 제341조"),
            ChecklistItem("취득방법", "취득 방법",
                          ("취득방법", "거래소", "공개매수", "균등한 조건", "각 주주에게 통지"),
                          "상법 제341조"),
            ChecklistItem("기관결의", "기관 결의(주주총회 또는 이사회)",
                          ("주주총회 결의", "이사회 결의", "주총 결의", "정관에 정한"), "상법 제341조"),
            ChecklistItem("주주평등", "주주평등 원칙과 특정주주로부터의 취득",
                          ("주주평등", "특정 주주", "모든 주주", "기회 균등"), ""),
            ChecklistItem("통지기간", "통지·신청 기간",
                          ("통지", "신청기간", "청약", "기간을 정하여"), ""),
            ChecklistItem("예외", "예외적 취득 사유",
                          ("합병", "영업 전부의 양수", "권리를 실행", "단주", "주식매수청구"),
                          "상법 제341조의2"),
            ChecklistItem("효력", "위반 시 효력",
                          ("무효", "효력", "위반한 경우", "책임"), ""),
        ],
    ),
    Checklist(
        issue="이사회 결의",
        triggers=("이사회 결의", "이사회에서 결의", "이사회 의결", "이사회를 개최"),
        items=[
            ChecklistItem("이사지위", "이사 지위와 자격",
                          ("사내이사", "사외이사", "기타비상무이사", "이사 지위", "등기이사"), ""),
            ChecklistItem("출석", "출석 여부",
                          ("출석", "참석", "불참", "화상회의"), ""),
            ChecklistItem("의결권", "의결권 유무",
                          ("의결권", "표결권", "옵저버", "참관"), ""),
            ChecklistItem("특별이해관계", "특별이해관계 있는 이사",
                          ("특별이해관계", "특별한 이해관계", "이해관계 있는 이사"), "상법 제391조 제3항"),
            ChecklistItem("정족수", "의사정족수와 의결정족수",
                          ("정족수", "과반수", "이사 과반수", "출석이사"), "상법 제391조 제1항"),
            ChecklistItem("하자효과", "결의 하자의 효과",
                          ("무효", "하자", "취소", "부존재", "효력"), ""),
        ],
    ),
    Checklist(
        issue="주식양도 제한",
        triggers=("주식양도", "주식 양도", "양도제한", "양도 제한", "동반매도", "우선매수"),
        items=[
            ChecklistItem("정관제한", "정관상 양도 제한",
                          ("정관", "이사회의 승인", "승인을 받아"), "상법 제335조"),
            ChecklistItem("계약제한", "계약상 양도 제한",
                          ("주주간계약", "계약상", "약정", "합의"), ""),
            ChecklistItem("당사자효력", "당사자 사이의 효력",
                          ("당사자 사이", "채권적 효력", "위약", "손해배상"), ""),
            ChecklistItem("대항", "제3자 대항 요건",
                          ("대항", "제3자", "선의"), "상법 제337조"),
            ChecklistItem("명의개서", "명의개서",
                          ("명의개서", "주주명부"), "상법 제337조"),
            ChecklistItem("보전처분", "가처분·손해배상 등 구제수단",
                          ("가처분", "손해배상", "이행강제", "위약벌"), ""),
        ],
    ),
]

# 권고·결론 문장. 결론이 없는 문서에는 "누락"이라 할 대상이 없다.
# 계약서처럼 조항만 담은 문서에까지 체크리스트를 들이대면, 실제 검토 누락이
# 그 소음에 묻힌다. 그래서 결론이 있는 문서에만 Finding을 만든다.
RECOMMENDATION_RE = re.compile(
    r"(하면\s*된다|하는\s*것이\s*타당|권고(?:한다|드린다|사항)|바람직하다|"
    r"가능하다고\s*판단|문제\s*없다|무방하다|진행하면|취득하면\s*된다|"
    r"결론적으로|검토\s*결과|판단된다|사료된다|하여야\s*할\s*것이다|의견이다)")


@dataclass
class OmissionReport:
    issue: str
    missing: List[ChecklistItem] = field(default_factory=list)
    covered: List[ChecklistItem] = field(default_factory=list)
    has_recommendation: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue": self.issue,
            "missing": [i.to_dict() for i in self.missing],
            "covered": [i.to_dict() for i in self.covered],
            "has_recommendation": self.has_recommendation,
            "note": ("누락 후보를 제시할 뿐 법률 결론을 확정하지 않는다. "
                     "참조 조문은 검토의 출발점이며 원문 확인이 필요하다."),
        }


def analyze_omissions(text: str, *, checklists: Sequence[Checklist] = ()) -> List[OmissionReport]:
    """문서에 나온 쟁점마다 다루지 않은 항목을 추린다."""
    body = text or ""
    reports: List[OmissionReport] = []
    for checklist in (checklists or CHECKLISTS):
        if not checklist.triggered(body):
            continue
        missing = [item for item in checklist.items if not item.mentioned(body)]
        covered = [item for item in checklist.items if item.mentioned(body)]
        reports.append(OmissionReport(
            issue=checklist.issue, missing=missing, covered=covered,
            has_recommendation=bool(RECOMMENDATION_RE.search(body)),
        ))
    return reports


def omission_findings(reports: Sequence[OmissionReport], *,
                      document_id: Optional[str] = None,
                      page: Optional[int] = None,
                      require_conclusion: bool = True) -> List[Finding]:
    """제1.2장 LEGAL_REQUIREMENT_OMITTED.

    결론만 있고 요건 검토가 보이지 않을 때 심각도가 올라간다. 그래도
    "위법하다"고 말하지 않는다. 검토되지 않은 항목이 있다고만 말한다.
    """
    out: List[Finding] = []
    for report in reports:
        if not report.missing:
            continue
        if require_conclusion and not report.has_recommendation:
            continue
        # 항목이 하나도 다루어지지 않았는데 결론만 있으면 가장 위험하다.
        nothing_covered = not report.covered
        severity = (Severity.HIGH if report.has_recommendation and nothing_covered
                    else Severity.MEDIUM if not report.has_recommendation
                    else Severity.HIGH)
        listed = ", ".join(item.label for item in report.missing)
        references = sorted({item.reference for item in report.missing if item.reference})
        out.append(Finding.create(
            type=FindingType.LEGAL_REQUIREMENT_OMITTED,
            status=VerificationStatus.UNVERIFIED,
            severity=severity,
            evidence_grade=EvidenceGrade.C,
            title=f"검토되지 않은 항목이 있다: {report.issue}",
            detail=(f"문서에서 확인되지 않은 항목: {listed}."
                    + (f" 참조 조문: {', '.join(references)}." if references else "")
                    + (" 요건 검토 없이 결론만 제시되어 있다." if report.has_recommendation else "")
                    + " 누락 후보이며 적용 여부는 담당 변호사가 확정한다."),
            confidence=0.6,
            document_id=document_id, page=page, engine=ENGINE_NAME,
            tags=["omission", report.issue],
        ))
    return out
