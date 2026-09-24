"""제4.4장 첨부문서 조항번호 교차검증.

지시문이나 의견서가 "주주간계약서 제11조의 Fair Value 산정 방식"이라고 적었을 때,
첨부된 계약서 원문에서 제11조의 표제와 내용을 실제로 읽어 대조한다.

중요한 전제가 하나 있다. 사용자가 준 지시문도 검증대상이지 신뢰된 사실이
아니다(제2.1장). 지시문의 조항번호와 첨부계약이 다르면 첨부계약 원문을
우선 표시하되, 법적 우선순위 확정은 사람에게 남긴다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from packages.common.enums import (
    EvidenceGrade,
    FindingType,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import Evidence, Finding, NormalizedDocument

ENGINE_NAME = "legal_engine.internal_citation"

# 제11조 (동반매도권) / 제 24 조 【Fair Value】 / 제24조의2
CLAUSE_HEADING_RE = re.compile(
    r"제\s*(?P<num>\d+)\s*조(?:\s*의\s*(?P<sub>\d+))?\s*"
    r"(?:[(\[（【「]\s*(?P<title>[^)\]）】」\n]{1,60})\s*[)\]）】」])?"
)
# 본문에서 다른 문서의 조항을 가리키는 표현
REFERENCE_RE = re.compile(r"제\s*(?P<num>\d+)\s*조(?:\s*의\s*(?P<sub>\d+))?")

# 조항 참조 주변에서 개념어로 볼 수 있는 덩어리. 조사와 흔한 기능어는 뺀다.
CONCEPT_STOPWORDS = {
    "계약", "계약서", "조항", "규정", "본문", "단서", "각호", "제1항", "내용", "방식",
    "따라", "따른", "의한", "관한", "관하여", "정한", "정하는", "기재", "규정한",
    "및", "또는", "등", "그", "이", "해당", "위", "아래", "상", "상의",
}
CONCEPT_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\s]{2,30}[A-Za-z]|[가-힣]{2,12}")
# 개념어 끝에 붙은 조사. 길이 순으로 벗겨야 "에서의"가 "의"로 잘리지 않는다.
JOSA = ("에서의", "으로서", "에게서", "이라는", "라는", "에서", "에게", "으로", "까지",
        "부터", "에는", "에도", "의", "를", "을", "이", "가", "은", "는", "와", "과", "에", "로")


def clause_key(num: str, sub: Optional[str]) -> str:
    return f"제{int(num)}조" + (f"의{int(sub)}" if sub else "")


@dataclass
class Clause:
    """첨부문서에서 읽어낸 조항 하나."""

    key: str
    title: str
    body: str
    document_id: Optional[str] = None
    page: Optional[int] = None
    block_id: Optional[str] = None

    @property
    def haystack(self) -> str:
        return f"{self.title} {self.body}"

    def to_dict(self) -> Dict[str, Any]:
        return {"clause": self.key, "title": self.title,
                "excerpt": self.body[:200], "document_id": self.document_id,
                "page": self.page}


def _heading_position(text: str, start: int) -> bool:
    """조항 표제는 줄(블록) 첫머리나 앞 문장이 끝난 바로 뒤에 온다.

    문장 안의 "…군인사법 제57조 제1항에 따른"은 조항 표제가 아니다.
    """
    before = text[:start].rstrip()
    return not before or before.endswith((".", "。", ":", "\n"))
# 소송 서면·의견서는 다른 문서의 조항 원문이 아니다(R1). 계약·규정처럼 조항 구조를 가진 문서만 원본 후보다.
NON_SOURCE_KINDS = {"COMPLAINT", "BRIEF", "ANSWER", "APPEAL", "OPINION_LETTER", "CRIMINAL_COMPLAINT", "REPORT"}
# 참조가 첨부문서를 가리킨다고 볼 수 있는 말. 이 말이 참조 바로 앞에 있을 때만 첨부 조항과 대조한다.
ATTACHMENT_POINTERS = ("첨부", "별첨", "위계약", "본계약", "같은계약", "동계약", "계약서", "약정서", "합의서",
                       "협약서", "정관", "약관", "규약", "내규")
SOURCE_ROLE = "SOURCE_TEXT"  # 사용자가 '원문 첨부'(계약서·규정·법령 사본)로 지정한 문서


def build_clause_index(document: NormalizedDocument) -> Dict[str, Clause]:
    """문서에서 조항 색인을 만든다. 줄 첫머리의 조항 표제만 조항으로 보고, 다음 표제까지를 본문으로 담는다."""
    index: Dict[str, Clause] = {}
    current: Optional[Clause] = None
    for page in document.pages:
        for block in page.blocks:
            if not block.visible or block.source_layer not in ("visible_text", "ocr_layer") \
                    or block.block_type == "running_head":
                continue
            text = block.text or ""
            headings = [m for m in CLAUSE_HEADING_RE.finditer(text) if _heading_position(text, m.start())]
            if not headings:
                if current is not None:
                    current.body = f"{current.body} {text.strip()}".strip()
                continue
            if current is not None and headings[0].start() > 0:
                current.body = f"{current.body} {text[:headings[0].start()].strip()}".strip()
            for position, match in enumerate(headings):
                end = headings[position + 1].start() if position + 1 < len(headings) else len(text)
                key = clause_key(match.group("num"), match.group("sub"))
                current = Clause(key=key, title=(match.group("title") or "").strip(),
                                 body=text[match.end():end].strip(), document_id=document.document_id,
                                 page=block.page or page.page_number, block_id=block.block_id)
                existing = index.get(key)
                if existing is None or len(existing.haystack) < len(current.haystack):
                    index[key] = current
    return index


def clause_source_eligible(document: NormalizedDocument, *, role: Optional[str] = None) -> bool:
    """이 문서를 다른 문서의 조항 참조를 대조할 '원문'으로 써도 되는가.

    사용자가 원문 첨부로 지정했으면 쓴다. 지정이 없으면 소송 서면·의견서·보고서는 쓰지 않는다.
    같은 사건의 다른 서면은 조항 원문이 아니며, 법령 원문은 공식 Source에서만 가져온다.
    """
    if role == SOURCE_ROLE:
        return True
    from packages.claim_engine.classification import document_kind
    kind = document_kind(b.text for b in document.prose_blocks()[:8])
    return kind not in NON_SOURCE_KINDS


def source_pointers(document: NormalizedDocument, label: str = "") -> List[str]:
    """참조 앞에 오면 이 원문을 가리킨다고 볼 수 있는 말(문서 제목·파일명 + 일반 첨부 표현)."""
    pointers = list(ATTACHMENT_POINTERS)
    first = next((b.text for b in document.prose_blocks() if (b.text or "").strip()), "")
    for name in (first, re.sub(r"\.[A-Za-z0-9]+$", "", label or "")):
        name = re.sub(r"\s+", "", name or "")
        if 2 <= len(name) <= 30:
            pointers.append(name)
    return pointers


def _concepts(text: str) -> List[str]:
    """참조 주변 문구에서 개념어 후보를 뽑는다."""
    out: List[str] = []
    for token in CONCEPT_TOKEN_RE.findall(text):
        token = token.strip()
        if not token or token in CONCEPT_STOPWORDS or len(token) < 2:
            continue
        if REFERENCE_RE.fullmatch(token):
            continue
        for josa in JOSA:
            if len(token) > len(josa) + 1 and token.endswith(josa):
                token = token[: -len(josa)]
                break
        if token and token not in CONCEPT_STOPWORDS and len(token) >= 2:
            out.append(token)
    return out


def _mentions(clause: Clause, concept: str) -> bool:
    haystack = clause.haystack.lower().replace(" ", "")
    return concept.lower().replace(" ", "") in haystack


@dataclass
class ReferenceCheck:
    """참조 하나의 대조 결과."""

    reference: str
    concepts: List[str]
    found: bool
    matches_concept: Optional[bool]
    cited_clause: Optional[Clause] = None
    candidates: List[Clause] = field(default_factory=list)
    context: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"reference": self.reference, "concepts": self.concepts,
                "found_in_attachment": self.found,
                "matches_concept": self.matches_concept,
                "cited_clause": self.cited_clause.to_dict() if self.cited_clause else None,
                "candidates": [c.to_dict() for c in self.candidates],
                "context": self.context}


def check_references(text: str, index: Dict[str, Clause], *,
                     window: int = 40, exclude_spans: Sequence[Tuple[int, int]] = (),
                     pointers: Optional[Sequence[str]] = None) -> List[ReferenceCheck]:
    """본문의 조항 참조를 색인과 대조한다.

    exclude_spans: 법령·행정규칙 인용 범위. "행정소송법 제27조"는 첨부문서가 아니라 법령을 가리키므로
    첨부 조항과 대조하지 않는다(공식 Source로 검증한다).
    pointers: 주어지면 참조 바로 앞(20자)에 그중 하나가 있을 때만 대조한다.
    """
    checks: List[ReferenceCheck] = []
    compact_pointers = [re.sub(r"\s+", "", p) for p in pointers or ()]
    for match in REFERENCE_RE.finditer(text):
        if any(start <= match.start() < end for start, end in exclude_spans):
            continue
        if pointers is not None:
            lead = re.sub(r"\s+", "", text[max(0, match.start() - 20):match.start()])
            if not any(p and p in lead for p in compact_pointers):
                continue
        key = clause_key(match.group("num"), match.group("sub"))
        start = max(0, match.start() - window)
        end = min(len(text), match.end() + window)
        context = text[start:end].strip()
        concepts = _concepts(text[match.end():end])
        clause = index.get(key)
        if clause is None:
            checks.append(ReferenceCheck(reference=key, concepts=concepts, found=False,
                                         matches_concept=None, context=context))
            continue
        if not concepts:
            # 개념어가 없으면 번호만 확인한 것이다. 일치로 단정하지 않는다.
            checks.append(ReferenceCheck(reference=key, concepts=[], found=True,
                                         matches_concept=None, cited_clause=clause,
                                         context=context))
            continue
        matched = any(_mentions(clause, c) for c in concepts)
        candidates: List[Clause] = []
        if not matched:
            for other in index.values():
                if other.key == key:
                    continue
                if any(_mentions(other, c) for c in concepts):
                    candidates.append(other)
        checks.append(ReferenceCheck(reference=key, concepts=concepts, found=True,
                                     matches_concept=matched, cited_clause=clause,
                                     candidates=candidates, context=context))
    return checks


def internal_citation_findings(checks: Sequence[ReferenceCheck], *,
                               source_label: str = "첨부문서",
                               document_id: Optional[str] = None,
                               page: Optional[int] = None) -> List[Finding]:
    """제4.4장 INTERNAL_CITATION_ERROR."""
    out: List[Finding] = []
    for check in checks:
        if not check.found:
            out.append(Finding.create(
                type=FindingType.INTERNAL_CITATION_ERROR,
                status=VerificationStatus.NOT_FOUND,
                severity=Severity.HIGH,
                evidence_grade=EvidenceGrade.A,
                title=f"{source_label}에 없는 조항을 인용했다: {check.reference}",
                detail=f"인용 문맥: …{check.context}…",
                confidence=0.85,
                document_id=document_id, page=page, engine=ENGINE_NAME,
                tags=["internal_citation", check.reference],
            ))
            continue
        if check.matches_concept is not False:
            continue
        suggestion = ""
        if len(check.candidates) == 1:
            other = check.candidates[0]
            suggestion = f" 해당 내용은 {other.key}" + (f"({other.title})" if other.title else "") + "에 있다."
        elif check.candidates:
            listed = ", ".join(c.key for c in check.candidates)
            suggestion = f" 같은 내용을 담은 조항 후보: {listed}."
        cited = check.cited_clause
        out.append(Finding.create(
            type=FindingType.INTERNAL_CITATION_ERROR,
            status=VerificationStatus.CONTRADICTED,
            severity=Severity.HIGH,
            evidence_grade=EvidenceGrade.A,
            title=f"조항번호와 내용이 다르다: {check.reference}",
            detail=(f"{check.reference}"
                    + (f"의 표제는 '{cited.title}'이다." if cited and cited.title else "의 내용이 인용된 개념과 다르다.")
                    + f" 인용은 '{', '.join(check.concepts[:3])}'을(를) 가리킨다."
                    + suggestion
                    + " 첨부문서 원문을 우선 표시하되, 어느 조항이 적용되는지는 사람이 확정한다."),
            confidence=0.8,
            document_id=document_id, page=page, engine=ENGINE_NAME,
            evidence=[Evidence.create(
                description=f"{source_label} {cited.key} 표제: {cited.title or '(표제 없음)'}",
                grade=EvidenceGrade.A, page=cited.page, document_id=cited.document_id,
                excerpt=cited.body[:200],
            )] if cited else [],
            tags=["internal_citation", check.reference],
        ))
    return out
