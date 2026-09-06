"""API 요청·응답 스키마."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str
    case_number: Optional[str] = None
    court: Optional[str] = None
    case_type: Optional[str] = None
    parties: List[str] = Field(default_factory=list)
    incident_date: Optional[str] = Field(default=None, description="사건 발생일 YYYY-MM-DD. 시행법 검증 기준일이 된다.")
    key_dates: Dict[str, str] = Field(default_factory=dict)
    purpose: str = ""
    tags: List[str] = Field(default_factory=list)
    memo: str = ""
    external_ai_policy: str = "MASKED"
    verification_profile: str = "STANDARD"
    requested_issues: List[str] = Field(default_factory=list)
    enabled_advisory_signals: Optional[List[str]] = None


class ProjectOut(BaseModel):
    id: str
    name: str
    case_number: Optional[str]
    court: Optional[str]
    case_type: Optional[str]
    parties: List[str]
    incident_date: Optional[str]
    purpose: str
    tags: List[str]
    memo: str
    external_ai_policy: str
    verification_profile: str
    requested_issues: List[str]
    created_at: datetime
    document_count: int = 0


class DocumentOut(BaseModel):
    id: str
    project_id: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    document_kind: str
    is_own_document: bool
    quarantined: bool
    rag_indexable: bool
    uploaded_at: datetime
    version_count: int = 1


class VerifyRequest(BaseModel):
    document_ids: Optional[List[str]] = None
    profile: Optional[str] = None
    force: bool = Field(default=False, description="동일 verification_key의 기존 결과를 무시하고 재실행한다.")


class RunOut(BaseModel):
    id: str
    project_id: str
    state: str
    progress: float
    stage_message: str
    verification_key: Optional[str]
    document_ids: List[str]
    scores: Dict[str, Any] = Field(default_factory=dict)
    unavailable_sources: List[Dict[str, Any]] = Field(default_factory=list)
    unverified_items: List[Dict[str, Any]] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    started_at: datetime
    finished_at: Optional[datetime]
    reused: bool = False


class FindingOut(BaseModel):
    id: str
    run_id: str
    project_id: str
    document_id: Optional[str]
    type: str
    status: str
    severity: str
    evidence_grade: str
    confidence: float
    page: Optional[int]
    block_id: Optional[str]
    title: str
    detail: str
    engine: Optional[str]
    meta_message_type: Optional[str]
    advisory_only: bool
    tags: List[str]
    review_status: str
    review_note: str
    has_sealed_content: bool
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    bbox: Optional[List[float]] = None


class ReviewRequest(BaseModel):
    review_status: str = Field(description="ACCEPTED | FALSE_POSITIVE | RESOLVED | NEEDS_REVIEW")
    note: str = ""
    reviewer: str = "user"


class RevealRequest(BaseModel):
    confirmed: bool = Field(description="열람 전 경고를 확인했는지 여부. False이면 공개하지 않는다.")
    reason: str = ""
    reviewer: str = "user"


class ReportRequest(BaseModel):
    run_id: Optional[str] = None
    formats: List[str] = Field(default_factory=lambda: ["pdf", "xlsx", "csv", "json", "manifest"])
    include_sealed: bool = False


class ProviderOut(BaseModel):
    name: str
    enabled: bool
    kind: str
    model: str
    has_key: bool
    key_env: str


class ProviderPatch(BaseModel):
    enabled: Optional[bool] = None
    model: Optional[str] = None


class OutboundRequest(BaseModel):
    generate_sanitized: bool = True
