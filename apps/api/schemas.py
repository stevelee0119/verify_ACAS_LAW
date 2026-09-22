"""API 요청·응답 스키마."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field, field_validator


class ProjectCreate(BaseModel):
    name: str = Field(default="", max_length=300)
    creation_key: Optional[str] = Field(default=None, max_length=80)
    case_number: Optional[str] = None
    court: Optional[str] = None
    case_type: Optional[str] = None
    parties: List[str] = Field(default_factory=list)
    incident_date: Optional[str] = Field(default=None, description="사건 발생일 YYYY-MM-DD. 시행법 검증 기준일이 된다.")
    key_dates: Dict[str, str] = Field(default_factory=dict)
    purpose: str = "법률문서 검증"
    tags: List[str] = Field(default_factory=list)
    memo: str = ""
    external_ai_policy: Literal["LOCAL_ONLY", "MASKED", "ORIGINAL"] = "LOCAL_ONLY"
    verification_profile: Literal["STANDARD", "QUICK", "DEEP_VERIFY"] = "STANDARD"
    requested_issues: List[str] = Field(default_factory=list)
    enabled_advisory_signals: Optional[List[str]] = None

    @field_validator("incident_date")
    @classmethod
    def valid_date(cls, value):
        if not value:
            return None
        from datetime import date
        return date.fromisoformat(value).isoformat()

    @field_validator("name")
    @classmethod
    def trim_name(cls, value):
        return value.strip()


class ProjectUpdate(ProjectCreate):
    """Only explicitly supplied fields are updated."""


class DocumentUpdate(BaseModel):
    included_in_verification: Optional[bool] = None
    exclusion_reason: str = Field(default="", max_length=2000)
    evidence_number: Optional[str] = Field(default=None, max_length=120)
    document_kind: Optional[str] = Field(default=None, max_length=60)
    submitted_by: Optional[Literal["OWN", "OPPONENT", "COURT", "THIRD_PARTY", "UNSPECIFIED"]] = None
    submitted_on: Optional[str] = None

    @field_validator("submitted_on")
    @classmethod
    def valid_submitted_on(cls, value):
        from datetime import date
        return date.fromisoformat(value).isoformat() if value else None


class DocumentScopeUpdate(BaseModel):
    document_ids: List[str] = Field(min_length=1, max_length=1000)
    included_in_verification: bool
    exclusion_reason: str = Field(default="", max_length=2000)


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
    included_document_count: int = 0
    scope_revision: int = 0
    key_dates: Dict[str, str] = Field(default_factory=dict)
    deleted_at: Optional[datetime] = None
    can_delete: bool = False


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
    included_in_verification: bool = True
    exclusion_reason: str = ""
    evidence_number: str = ""
    submitted_by: str = "UNSPECIFIED"
    submitted_on: Optional[str] = None


class VerifyRequest(BaseModel):
    document_ids: Optional[List[str]] = None
    profile: Optional[Literal["STANDARD", "QUICK", "DEEP_VERIFY"]] = None
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
    timeline: List[Dict[str, Any]] = Field(default_factory=list)
    input_snapshot: Dict[str, Any] = Field(default_factory=dict)


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
    audience: Literal["INTERNAL", "SHAREABLE"] = "INTERNAL"

    @field_validator("audience", mode="before")
    @classmethod
    def report_audience(cls, value):
        return value.upper() if isinstance(value, str) else value

    @field_validator("formats")
    @classmethod
    def report_formats(cls, value):
        allowed = {"pdf", "xlsx", "csv", "json", "manifest", "highlight", "docx"}
        if not value or len(value) != len(set(value)) or not set(value) <= allowed:
            raise ValueError("중복 없는 지원 형식을 하나 이상 선택하세요")
        return value


class ReportFinalizeRequest(BaseModel):
    note: str = Field(min_length=1, max_length=20000)
    acknowledge_unresolved: bool = Field(default=False, strict=True)
    acknowledge_stale_scope: bool = Field(default=False, strict=True)
    acknowledge_privacy: bool = Field(default=False, strict=True)
    expected_preflight_hash: Optional[str] = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @field_validator("note")
    @classmethod
    def final_note(cls, value):
        if not value.strip():
            raise ValueError("검토 확정 메모를 입력하세요")
        return value.strip()


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
