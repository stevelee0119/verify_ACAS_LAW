"""제1.2장 DRAFT_ARTIFACT · UNCERTAINTY_NOT_DISCLOSED · OVERCLAIM · AUTHORITY_RANK_ERROR.

네 가지 모두 "표현"을 보는 검사이지만, 문체로 작성자를 판정하는 것과는
성격이 다르다(제8.1장). 여기서 보는 것은 문장의 확신 수준과 그 문장이
기대고 있는 출처의 검증 상태가 어긋나는지다. 출처 상태라는 객관적
사실에 걸려 있으므로 근거를 제시할 수 있다.

출처 상태를 알 수 없으면 아무것도 내지 않는다. "확실하다"는 표현 자체는
결함이 아니다. 원문을 확보하지 못한 채 그렇게 쓴 것이 결함이다.
"""
from __future__ import annotations

import re
from typing import List, Optional, Sequence

from packages.common.enums import (
    CitationType,
    EvidenceGrade,
    FindingType,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import Citation, Evidence, Finding

from packages.common.anonymization import BRACKET_PLACEHOLDER_RE

ENGINE_NAME = "claim_engine.assertion"

# 마침표 앞이 숫자면 문장 끝으로 보지 않는다. "2021. 3. 25. 선고"를 세 문장으로
# 쪼개면 선고일과 판시 내용이 갈라져 그 뒤 검사가 모두 빗나간다.
SENTENCE_SPLIT_RE = re.compile(r"(?<=[^\s\d][.。!?])\s+|\n+")

# --- 초안 흔적 ----------------------------------------------------------------
# 최종본에 남으면 안 되는 작업 메모. 실제로 발견된 형태만 넣는다.
DRAFT_MARKER_PATTERNS = [
    (re.compile(r"\[[^\]\n]{0,30}(추가|보완|확인|검증|삽입|수정|작성)\s*(필요|요망|요)?[^\]\n]{0,10}\]"), "각괄호 작업 메모"),
    (re.compile(r"(인용|출처|근거|판례|조문)\s*(검증|확인)\s*(필요|요망|바람)"), "검증 필요 메모"),
    (re.compile(r"\bTODO\b|\bTBD\b|\bFIXME\b|\bXXX\b", re.IGNORECASE), "영문 작업 표지"),
    # ○○○·△△ 같은 가림 기호는 비식별 처리이므로 넣지 않는다(common/anonymization.py).
    (re.compile(r"(?<![A-Za-z])[xX]{3,}(?![a-zA-Z])|●{3,}"), "미기재 자리표시"),
    (BRACKET_PLACEHOLDER_RE, "각괄호 자리표시(미기재 항목)"),
    (re.compile(r"추후\s*(보완|확인|기재|삽입)"), "추후 보완 메모"),
    (re.compile(r"\(\s*(작성자|검토자)\s*(주|메모|코멘트)\s*:?[^)\n]{0,60}\)"), "작성자 주석"),
    (re.compile(r"※\s*(검토|확인|주의)[^\n]{0,40}"), "검토 표지"),
]

# --- 확신 표현 ----------------------------------------------------------------
CERTAINTY_RE = re.compile(
    r"(명백(?:하|히)|확실(?:하|히)|틀림없|의문의\s*여지가\s*없|당연히|필연적으로|"
    r"반드시\s*[가-힣]{1,6}(?:된다|한다|인다)|"
    r"확정적으로|다툼의\s*여지가\s*없|단언(?:컨대|할)|무효임이\s*분명)"
)
HEDGE_RE = re.compile(
    r"(가능성|것으로\s*보인다|여지가\s*있|다툴\s*수\s*있|일\s*수\s*있|추정된다|"
    r"판단될\s*수|해석될\s*여지|불확실|확인이\s*필요|미확인|검토가\s*필요)"
)

# --- 과잉 일반화 ---------------------------------------------------------------
SETTLED_DOCTRINE_RE = re.compile(
    r"(확립된\s*판례|확고한\s*(판례|입장|태도)|일관(?:되게|된)\s*판시|"
    r"판례의\s*확립된\s*법리|대법원의?\s*확고한|통설(?:이자)?\s*판례)"
)
LOWER_COURT_RE = re.compile(r"(고등법원|지방법원|지원|가정법원|행정법원|특허법원|회생법원)")

# --- 출처 위계 -----------------------------------------------------------------
SECONDARY_SOURCE_RE = re.compile(
    r"(블로그|네이버\s*지식|카페\s*글|보도자료|언론\s*보도|기사에\s*따르면|"
    r"위키|AI\s*(?:답변|응답)|챗봇|생성형\s*AI의?\s*(?:답변|설명))"
)
AUTHORITATIVE_CLAIM_RE = re.compile(
    r"(법리(?:는|상)|판례(?:는|상)|법령(?:은|상)|대법원(?:은|의)|[가-힣]{0,6}법(?:률)?상|조문(?:은|상))")


def _sentences(text: str) -> List[tuple]:
    """(문장, 시작오프셋) 목록."""
    out: List[tuple] = []
    offset = 0
    for piece in SENTENCE_SPLIT_RE.split(text or ""):
        if piece is None:
            continue
        index = (text or "").find(piece, offset)
        if index < 0:
            index = offset
        stripped = piece.strip()
        if stripped:
            out.append((stripped, index))
        offset = index + len(piece)
    return out


def draft_artifact_findings(text: str, *, document_id: Optional[str] = None,
                            page: Optional[int] = None,
                            block_id: Optional[str] = None) -> List[Finding]:
    """제1.2장 DRAFT_ARTIFACT. 최종본에 남은 작업 메모를 찾는다."""
    out: List[Finding] = []
    seen: set = set()
    for pattern, label in DRAFT_MARKER_PATTERNS:
        for match in pattern.finditer(text or ""):
            fragment = match.group(0).strip()
            if fragment in seen:
                continue
            seen.add(fragment)
            out.append(Finding.create(
                type=FindingType.DRAFT_ARTIFACT,
                status=VerificationStatus.SUSPICIOUS,
                severity=Severity.MEDIUM,
                evidence_grade=EvidenceGrade.A,
                title=f"초안 흔적이 남아 있다: {label}",
                detail=f"본문에 '{fragment[:80]}'이(가) 남아 있다. 제출 전 삭제 여부를 확인해야 한다.",
                confidence=0.9,
                document_id=document_id, page=page, block_id=block_id,
                span=(match.start(), match.end()), engine=ENGINE_NAME,
                tags=["draft_artifact"],
            ))
    return out


def uncertainty_findings(text: str, *, unverified_citations: Sequence[Citation] = (),
                         document_id: Optional[str] = None,
                         page: Optional[int] = None) -> List[Finding]:
    """제1.2장 UNCERTAINTY_NOT_DISCLOSED.

    원문을 확보하지 못한 인용에 기대면서 확신 표현을 쓴 문장만 잡는다.
    미검증 인용이 하나도 없으면 아무것도 내지 않는다.
    """
    if not unverified_citations:
        return []
    out: List[Finding] = []
    for sentence, offset in _sentences(text):
        if not CERTAINTY_RE.search(sentence) or HEDGE_RE.search(sentence):
            continue
        touching_citations = [c for c in unverified_citations if c.raw_text and c.raw_text[:12] in sentence]
        touching = [c.raw_text for c in touching_citations]
        if not touching:
            continue
        out.append(Finding.create(
            type=FindingType.UNCERTAINTY_NOT_DISCLOSED,
            status=VerificationStatus.SUSPICIOUS,
            severity=Severity.HIGH,
            evidence_grade=EvidenceGrade.B,
            title="원문 미확보 상태에서 확정적으로 서술했다",
            detail=(f"'{sentence[:120]}' 문장은 확신 표현을 쓰고 있으나, 근거로 든 "
                    f"{touching[0][:60]}은(는) 공식 원문으로 확인되지 않았다. "
                    f"불확실성을 표시하거나 원문을 확보해야 한다."),
            confidence=0.75,
            # 기댄 인용을 남긴다. 보고서 전 일관성 검사가 그 인용의 최종 판정과 대조한다(v3 D5).
            confidence_features={"citation_ids": [c.citation_id for c in touching_citations]},
            document_id=document_id, page=page,
            span=(offset, offset + len(sentence)), engine=ENGINE_NAME,
            evidence=[Evidence.create(description=f"미검증 인용: {touching[0][:120]}",
                                      grade=EvidenceGrade.U)],
            tags=["uncertainty"],
        ))
    return out


def overclaim_findings(text: str, *, citations: Sequence[Citation] = (),
                       document_id: Optional[str] = None,
                       page: Optional[int] = None) -> List[Finding]:
    """제1.2장 OVERCLAIM. 근거의 강도를 넘어선 일반화.

    "확립된 판례"라고 쓰면서 든 판례가 하급심 1건뿐이거나, 판례 인용이
    아예 없는 경우를 잡는다. 대법원 판결 여러 건을 들었다면 잡지 않는다.
    """
    case_citations = [c for c in citations if c.type == CitationType.CASE]
    supreme = [c for c in case_citations
               if (c.court or "").strip().startswith("대법원")
               or "대법원" in (c.raw_text or "")]
    lower = [c for c in case_citations if c not in supreme]

    out: List[Finding] = []
    for sentence, offset in _sentences(text):
        if not SETTLED_DOCTRINE_RE.search(sentence):
            continue
        if len(supreme) >= 2:
            continue  # 대법원 판결 복수 인용이면 일반화의 근거가 있다
        if len(supreme) == 1 and not LOWER_COURT_RE.search(sentence):
            basis = "대법원 판결 1건"
        elif lower and not supreme:
            basis = f"하급심 재판례 {len(lower)}건"
        elif not case_citations:
            basis = "판례 인용 없음"
        else:
            continue
        out.append(Finding.create(
            type=FindingType.OVERCLAIM,
            status=VerificationStatus.SUSPICIOUS,
            severity=Severity.HIGH,
            evidence_grade=EvidenceGrade.B,
            title="증거강도를 넘어선 일반화다",
            detail=(f"'{sentence[:120]}' 문장은 확립된 법리로 서술하나, 제시된 근거는 "
                    f"{basis}이다. 판례의 지위와 범위를 그대로 표현해야 한다."),
            confidence=0.7,
            document_id=document_id, page=page,
            span=(offset, offset + len(sentence)), engine=ENGINE_NAME,
            tags=["overclaim"],
        ))
    return out


def authority_rank_findings(text: str, *, document_id: Optional[str] = None,
                            page: Optional[int] = None) -> List[Finding]:
    """제1.2장 AUTHORITY_RANK_ERROR. 보조출처를 1차 근거로 쓴 경우."""
    out: List[Finding] = []
    for sentence, offset in _sentences(text):
        secondary = SECONDARY_SOURCE_RE.search(sentence)
        if not secondary or not AUTHORITATIVE_CLAIM_RE.search(sentence):
            continue
        out.append(Finding.create(
            type=FindingType.AUTHORITY_RANK_ERROR,
            status=VerificationStatus.SUSPICIOUS,
            severity=Severity.MEDIUM,
            evidence_grade=EvidenceGrade.B,
            title="보조출처를 법령·판례 원문의 근거로 들었다",
            detail=(f"'{sentence[:120]}' 문장은 '{secondary.group(0)}'을(를) 근거로 법리를 "
                    f"서술한다. 보조출처는 발견에만 쓰고 확인은 공식 원문으로 해야 한다."),
            confidence=0.7,
            document_id=document_id, page=page,
            span=(offset, offset + len(sentence)), engine=ENGINE_NAME,
            tags=["authority_rank"],
        ))
    return out


def analyze_assertions(text: str, *, citations: Sequence[Citation] = (),
                       unverified_citations: Sequence[Citation] = (),
                       document_id: Optional[str] = None,
                       page: Optional[int] = None) -> List[Finding]:
    """네 검사를 한 번에 돌린다."""
    findings: List[Finding] = []
    findings.extend(draft_artifact_findings(text, document_id=document_id, page=page))
    findings.extend(uncertainty_findings(text, unverified_citations=unverified_citations,
                                         document_id=document_id, page=page))
    findings.extend(overclaim_findings(text, citations=citations,
                                       document_id=document_id, page=page))
    findings.extend(authority_rank_findings(text, document_id=document_id, page=page))
    return findings
