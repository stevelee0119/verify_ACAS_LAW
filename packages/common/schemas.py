"""핵심 데이터 구조.

제6.2장 Normalized Document, 제11장 Claim/Entity/Event,
제16장 Finding/Evidence, 제15장 SourceRecord에 대응한다.

DB(SQLAlchemy) 모델과 분리된 순수 도메인 객체이며 엔진 계층은
이 구조만 사용한다. 이렇게 하여 폐쇄망(제23장) 재사용성을 확보한다.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from .enums import (
    AdapterStatus,
    AdversarialClass,
    AttributionLevel,
    AuthorshipVerdict,
    CitationType,
    ClaimType,
    EntityType,
    EvidenceGrade,
    FindingType,
    ForensicLevel,
    MetaMessageType,
    ReviewStatus,
    Severity,
    VerificationStatus,
)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 6.2 Normalized Document
# ---------------------------------------------------------------------------
SourceLayer = str  # visible_text | hidden_text | ocr_layer | xml | metadata | image | annotation

# 본문으로 취급하는 레이어. 스캔본은 OCR 결과가 본문이다.
BODY_LAYERS = ("visible_text", "ocr_layer")


@dataclass
class BBox:
    """Canonical coordinate: 좌상단 원점, 단위 pt (72dpi 기준)."""

    x0: float
    y0: float
    x1: float
    y1: float

    def as_tuple(self) -> Tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

    def overlaps(self, other: "BBox", tolerance: float = 0.0) -> bool:
        return not (
            self.x1 < other.x0 - tolerance
            or other.x1 < self.x0 - tolerance
            or self.y1 < other.y0 - tolerance
            or other.y1 < self.y0 - tolerance
        )

    def contains(self, other: "BBox", tolerance: float = 1.0) -> bool:
        return (
            self.x0 - tolerance <= other.x0
            and self.y0 - tolerance <= other.y0
            and self.x1 + tolerance >= other.x1
            and self.y1 + tolerance >= other.y1
        )


@dataclass
class Block:
    """문단·표·이미지·머리말 등 최소 단위. block_id/text/page/bbox/source_layer 보존."""

    block_id: str
    text: str
    page: int
    bbox: Optional[BBox] = None
    source_layer: SourceLayer = "visible_text"
    block_type: str = "paragraph"  # paragraph|table|image|header|footer|footnote|comment
    visible: bool = True
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["bbox"] = self.bbox.as_tuple() if self.bbox else None
        return d


@dataclass
class Page:
    page_number: int
    width: float = 0.0
    height: float = 0.0
    blocks: List[Block] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)

    @property
    def visible_text(self) -> str:
        return "\n".join(b.text for b in self.blocks if b.visible and b.source_layer == "visible_text")


@dataclass
class NormalizedDocument:
    document_id: str
    filename: str
    mime_type: str
    sha256: str
    pages: List[Page] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    raw_layers: Dict[str, str] = field(default_factory=dict)
    """레이어별 원문. keys: rendered_text, raw_text, ocr_layer, xml, metadata_text, image_text"""
    parser_name: str = ""
    parse_warnings: List[str] = field(default_factory=list)
    structure: Dict[str, Any] = field(default_factory=dict)
    """파서가 추출한 구조정보(주석, 변경이력, incremental update 등 포렌식 입력)."""

    # -- 편의 접근자 ------------------------------------------------------
    @property
    def blocks(self) -> List[Block]:
        return [b for p in self.pages for b in p.blocks]

    def visible_blocks(self) -> List[Block]:
        """화면에 표시되는 텍스트 블록만."""
        return [b for b in self.blocks if b.visible and b.source_layer == "visible_text"]

    def body_blocks(self) -> List[Block]:
        """본문으로 취급할 블록.

        스캔 문서는 OCR 결과가 곧 본문이므로 ocr_layer를 포함한다.
        숨은 텍스트·메타데이터·주석은 적대적 콘텐츠로 별도 처리하므로 제외한다.
        """
        return [b for b in self.blocks if b.visible and b.source_layer in BODY_LAYERS]

    @property
    def visible_text(self) -> str:
        return "\n".join(b.text for b in self.body_blocks())

    @property
    def full_text(self) -> str:
        return "\n".join(b.text for b in self.blocks)

    def block_by_id(self, block_id: str) -> Optional[Block]:
        for b in self.blocks:
            if b.block_id == block_id:
                return b
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "sha256": self.sha256,
            "parser_name": self.parser_name,
            "metadata": self.metadata,
            "parse_warnings": self.parse_warnings,
            "pages": [
                {
                    "page_number": p.page_number,
                    "width": p.width,
                    "height": p.height,
                    "attributes": p.attributes,
                    "blocks": [b.to_dict() for b in p.blocks],
                }
                for p in self.pages
            ],
        }


# ---------------------------------------------------------------------------
# 15. SourceRecord / Evidence
# ---------------------------------------------------------------------------
@dataclass
class SourceRecord:
    """외부 Source 조회 기록. Source, Query, 조회시각, 결과 ID, 응답 Hash 보존."""

    source_record_id: str
    adapter: str
    query: str
    retrieved_at: datetime
    status: AdapterStatus
    result_id: Optional[str] = None
    response_hash: Optional[str] = None
    used_fields: List[str] = field(default_factory=list)
    url: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(adapter: str, query: str, status: AdapterStatus, **kw: Any) -> "SourceRecord":
        return SourceRecord(
            source_record_id=new_id("SRC"),
            adapter=adapter,
            query=query,
            retrieved_at=datetime.utcnow(),
            status=status,
            **kw,
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["retrieved_at"] = self.retrieved_at.isoformat()
        d["status"] = str(self.status)
        return d


@dataclass
class Evidence:
    evidence_id: str
    description: str
    grade: EvidenceGrade
    source_record_ids: List[str] = field(default_factory=list)
    document_id: Optional[str] = None
    block_id: Optional[str] = None
    page: Optional[int] = None
    span: Optional[Tuple[int, int]] = None
    excerpt: Optional[str] = None
    sealed: bool = False
    """True이면 원문을 사용자 확인 전 노출하지 않는다(부록 C 제11항)."""
    supports: bool = True

    @staticmethod
    def create(description: str, grade: EvidenceGrade, **kw: Any) -> "Evidence":
        return Evidence(evidence_id=new_id("EV"), description=description, grade=grade, **kw)

    def to_dict(self, reveal_sealed: bool = False) -> Dict[str, Any]:
        d = asdict(self)
        d["grade"] = str(self.grade)
        if self.sealed and not reveal_sealed:
            d["excerpt"] = None
            d["sealed_notice"] = "SEALED: 사용자 명시적 열람 요청 시에만 원문이 공개된다."
        return d


# ---------------------------------------------------------------------------
# 16. Finding
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    finding_id: str
    type: FindingType
    status: VerificationStatus
    severity: Severity
    evidence_grade: EvidenceGrade
    title: str
    detail: str = ""
    confidence: float = 0.0
    confidence_features: Dict[str, Any] = field(default_factory=dict)
    document_id: Optional[str] = None
    block_id: Optional[str] = None
    page: Optional[int] = None
    bbox: Optional[BBox] = None
    span: Optional[Tuple[int, int]] = None
    evidence: List[Evidence] = field(default_factory=list)
    source_record_ids: List[str] = field(default_factory=list)
    engine: str = ""
    meta_message_type: Optional[MetaMessageType] = None
    forensic_level: Optional[ForensicLevel] = None
    adversarial_class: Optional[AdversarialClass] = None
    advisory_only: bool = False
    """True이면 보고서 본문이 아닌 참고 신호(Advisory Signals) 섹션에 배치한다."""
    sealed_excerpt: Optional[str] = None
    """MM-2/MM-3 원문. 봉인 상태로 저장하고 열람은 Audit에 기록한다."""
    tags: List[str] = field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW
    review_note: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)

    @staticmethod
    def create(
        type: FindingType,
        status: VerificationStatus,
        severity: Severity,
        evidence_grade: EvidenceGrade,
        title: str,
        **kw: Any,
    ) -> "Finding":
        return Finding(
            finding_id=new_id("F"),
            type=type,
            status=status,
            severity=severity,
            evidence_grade=evidence_grade,
            title=title,
            **kw,
        )

    def to_dict(self, reveal_sealed: bool = False) -> Dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "type": str(self.type),
            "status": str(self.status),
            "severity": str(self.severity),
            "confidence": round(self.confidence, 4),
            "confidence_features": self.confidence_features,
            "evidence_grade": str(self.evidence_grade),
            "title": self.title,
            "detail": self.detail,
            "document_id": self.document_id,
            "block_id": self.block_id,
            "page": self.page,
            "bbox": self.bbox.as_tuple() if self.bbox else None,
            "span": list(self.span) if self.span else None,
            "engine": self.engine,
            "meta_message_type": str(self.meta_message_type) if self.meta_message_type else None,
            "forensic_level": str(self.forensic_level) if self.forensic_level else None,
            "adversarial_class": str(self.adversarial_class) if self.adversarial_class else None,
            "advisory_only": self.advisory_only,
            "tags": self.tags,
            "review_status": str(self.review_status),
            "review_note": self.review_note,
            "sources": list(self.source_record_ids),
            "evidence": [e.to_dict(reveal_sealed) for e in self.evidence],
            "sealed_excerpt": self.sealed_excerpt if reveal_sealed else None,
            "has_sealed_content": self.sealed_excerpt is not None,
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# 9. Citation
# ---------------------------------------------------------------------------
@dataclass
class Citation:
    citation_id: str
    type: CitationType
    raw_text: str
    document_id: Optional[str] = None
    block_id: Optional[str] = None
    page: Optional[int] = None
    span: Optional[Tuple[int, int]] = None
    # 판례
    court: Optional[str] = None
    decision_date: Optional[str] = None
    case_number: Optional[str] = None
    canonical_case_number: Optional[str] = None
    case_kind: Optional[str] = None  # 판결/결정/명령
    # 법령
    law_name: Optional[str] = None
    article: Optional[str] = None
    paragraph: Optional[str] = None
    item: Optional[str] = None
    # 학술
    title: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    journal: Optional[str] = None
    doi: Optional[str] = None
    # 인용문
    quoted_text: Optional[str] = None
    context: str = ""

    @staticmethod
    def create(type: CitationType, raw_text: str, **kw: Any) -> "Citation":
        return Citation(citation_id=new_id("CIT"), type=type, raw_text=raw_text, **kw)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["type"] = str(self.type)
        d["span"] = list(self.span) if self.span else None
        return d


# ---------------------------------------------------------------------------
# 11. Claim / Entity / Event
# ---------------------------------------------------------------------------
@dataclass
class Claim:
    claim_id: str
    type: ClaimType
    text: str
    document_id: Optional[str] = None
    block_id: Optional[str] = None
    page: Optional[int] = None
    citation_ids: List[str] = field(default_factory=list)
    entity_ids: List[str] = field(default_factory=list)
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    evidence: List[Evidence] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(type: ClaimType, text: str, **kw: Any) -> "Claim":
        return Claim(claim_id=new_id("CLM"), type=type, text=text, **kw)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "type": str(self.type),
            "text": self.text,
            "document_id": self.document_id,
            "block_id": self.block_id,
            "page": self.page,
            "citation_ids": self.citation_ids,
            "entity_ids": self.entity_ids,
            "status": str(self.status),
            "attributes": self.attributes,
        }


@dataclass
class Entity:
    entity_id: str
    type: EntityType
    name: str
    aliases: List[str] = field(default_factory=list)
    mentions: List[Dict[str, Any]] = field(default_factory=list)
    merge_confidence: float = 1.0
    needs_user_confirmation: bool = False
    attributes: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(type: EntityType, name: str, **kw: Any) -> "Entity":
        return Entity(entity_id=new_id("ENT"), type=type, name=name, **kw)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["type"] = str(self.type)
        return d


@dataclass
class Event:
    event_id: str
    date: Optional[date]
    description: str
    document_id: Optional[str] = None
    block_id: Optional[str] = None
    page: Optional[int] = None
    entity_ids: List[str] = field(default_factory=list)
    event_kind: str = "GENERIC"
    raw_date_text: str = ""

    @staticmethod
    def create(date_value: Optional[date], description: str, **kw: Any) -> "Event":
        return Event(event_id=new_id("EVT"), date=date_value, description=description, **kw)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["date"] = self.date.isoformat() if self.date else None
        return d


# ---------------------------------------------------------------------------
# 13. Authorship 분석 결과
# ---------------------------------------------------------------------------
@dataclass
class AuthorshipAssessment:
    verdict: AuthorshipVerdict
    score: float
    signals: Dict[str, Any] = field(default_factory=dict)
    attribution: AttributionLevel = AttributionLevel.UNDETERMINED
    attributed_model: Optional[str] = None
    segment_verdicts: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": str(self.verdict),
            "score": round(self.score, 4),
            "signals": self.signals,
            "attribution": str(self.attribution),
            "attributed_model": self.attributed_model,
            "segment_verdicts": self.segment_verdicts,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# 엔진 공통 결과 컨테이너
# ---------------------------------------------------------------------------
@dataclass
class EngineResult:
    engine: str
    findings: List[Finding] = field(default_factory=list)
    source_records: List[SourceRecord] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    unverified_items: List[Dict[str, Any]] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)

    def merge(self, other: "EngineResult") -> "EngineResult":
        self.findings.extend(other.findings)
        self.source_records.extend(other.source_records)
        self.warnings.extend(other.warnings)
        self.unverified_items.extend(other.unverified_items)
        for k, v in other.data.items():
            self.data.setdefault(k, v)
        return self
