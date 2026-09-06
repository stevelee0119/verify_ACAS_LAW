"""제17장 주요 데이터 모델 (SQLAlchemy).

MVP는 SQLite, 운영은 PostgreSQL+pgvector를 사용한다(제3.2장).
embedding 컬럼은 pgvector 전환을 고려해 JSON으로 보관한다.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker
from sqlalchemy.types import TypeDecorator

from packages.common.config import get_settings


class Base(DeclarativeBase):
    pass


class JSONType(TypeDecorator):
    """SQLite/PostgreSQL 공통 JSON 컬럼."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[str]:
        return None if value is None else json.dumps(value, ensure_ascii=False, default=str)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        return None if value is None else json.loads(value)


def new_uuid(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
class Organization(Base):
    __tablename__ = "organizations"
    id = Column(String(40), primary_key=True, default=lambda: new_uuid("org_"))
    name = Column(String(200), nullable=False)
    # 기관 정책: LOCAL_ONLY 강제, 봉인 원문 열람 차단 등(제21.3장, 제7-A.6장)
    forced_ai_policy = Column(String(20))
    blocked_providers = Column(JSONType, default=list)
    block_sealed_reveal = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"
    id = Column(String(40), primary_key=True, default=lambda: new_uuid("usr_"))
    email = Column(String(200), unique=True, nullable=False)
    display_name = Column(String(120), default="")
    role = Column(String(30), default="MEMBER")  # ADMIN | MEMBER | VIEWER
    organization_id = Column(String(40), ForeignKey("organizations.id"))
    created_at = Column(DateTime, default=datetime.utcnow)


class Project(Base):
    """제5장 사건 단위 Workspace."""

    __tablename__ = "projects"
    id = Column(String(40), primary_key=True, default=lambda: new_uuid("prj_"))
    name = Column(String(300), nullable=False)
    case_number = Column(String(80))
    court = Column(String(120))
    case_type = Column(String(40))  # 민사·형사·행정·헌법·군사
    parties = Column(JSONType, default=list)
    incident_date = Column(String(20))
    key_dates = Column(JSONType, default=dict)
    purpose = Column(Text, default="")
    owner_id = Column(String(40), ForeignKey("users.id"))
    organization_id = Column(String(40), ForeignKey("organizations.id"))
    tags = Column(JSONType, default=list)
    memo = Column(Text, default="")
    external_ai_policy = Column(String(20), default="MASKED")
    verification_profile = Column(String(20), default="STANDARD")
    enabled_advisory_signals = Column(JSONType)
    requested_issues = Column(JSONType, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)

    documents = relationship("Document", back_populates="project", cascade="all, delete-orphan")


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(40), ForeignKey("projects.id"), nullable=False)
    user_id = Column(String(40), ForeignKey("users.id"), nullable=False)
    role = Column(String(30), default="MEMBER")


class Document(Base):
    __tablename__ = "documents"
    id = Column(String(40), primary_key=True, default=lambda: new_uuid("doc_"))
    project_id = Column(String(40), ForeignKey("projects.id"), nullable=False)
    filename = Column(String(400), nullable=False)
    mime_type = Column(String(120), default="")
    size_bytes = Column(Integer, default=0)
    sha256 = Column(String(64), nullable=False)
    storage_key = Column(String(400), nullable=False)
    document_kind = Column(String(60), default="")
    is_own_document = Column(Boolean, default=False)
    """자기 측 문서 여부. Outbound Guard(제7-A.7장)와 특권 게이트 판단에 사용한다."""
    quarantined = Column(Boolean, default=False)
    rag_indexable = Column(Boolean, default=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="documents")
    versions = relationship("DocumentVersion", back_populates="document", cascade="all, delete-orphan")


class DocumentVersion(Base):
    """제5.3장 문서 버전관리."""

    __tablename__ = "document_versions"
    id = Column(String(40), primary_key=True, default=lambda: new_uuid("dv_"))
    document_id = Column(String(40), ForeignKey("documents.id"), nullable=False)
    version = Column(Integer, default=1)
    sha256 = Column(String(64), nullable=False)
    storage_key = Column(String(400), nullable=False)
    kind = Column(String(30), default="ORIGINAL")  # ORIGINAL | SANITIZED | DERIVATIVE
    note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("Document", back_populates="versions")


class DocumentPage(Base):
    __tablename__ = "document_pages"
    id = Column(String(40), primary_key=True, default=lambda: new_uuid("pg_"))
    document_id = Column(String(40), ForeignKey("documents.id"), nullable=False)
    page_number = Column(Integer, nullable=False)
    width = Column(Float, default=0)
    height = Column(Float, default=0)
    attributes = Column(JSONType, default=dict)


class DocumentBlock(Base):
    __tablename__ = "document_blocks"
    id = Column(String(40), primary_key=True)
    document_id = Column(String(40), ForeignKey("documents.id"), nullable=False)
    page = Column(Integer, default=1)
    text = Column(Text, default="")
    bbox = Column(JSONType)
    source_layer = Column(String(30), default="visible_text")
    block_type = Column(String(30), default="paragraph")
    visible = Column(Boolean, default=True)
    attributes = Column(JSONType, default=dict)
    embedding = Column(JSONType)  # pgvector 전환 대상


class CitationRow(Base):
    __tablename__ = "citations"
    id = Column(String(40), primary_key=True)
    document_id = Column(String(40), ForeignKey("documents.id"), nullable=False)
    project_id = Column(String(40), ForeignKey("projects.id"), nullable=False)
    data = Column(JSONType, default=dict)


class ClaimRow(Base):
    __tablename__ = "claims"
    id = Column(String(40), primary_key=True)
    document_id = Column(String(40), ForeignKey("documents.id"), nullable=False)
    project_id = Column(String(40), ForeignKey("projects.id"), nullable=False)
    data = Column(JSONType, default=dict)


class EntityRow(Base):
    __tablename__ = "entities"
    id = Column(String(40), primary_key=True)
    project_id = Column(String(40), ForeignKey("projects.id"), nullable=False)
    data = Column(JSONType, default=dict)


class EventRow(Base):
    __tablename__ = "events"
    id = Column(String(40), primary_key=True)
    project_id = Column(String(40), ForeignKey("projects.id"), nullable=False)
    document_id = Column(String(40), ForeignKey("documents.id"))
    data = Column(JSONType, default=dict)


class VerificationRun(Base):
    __tablename__ = "verification_runs"
    id = Column(String(40), primary_key=True, default=lambda: new_uuid("run_"))
    project_id = Column(String(40), ForeignKey("projects.id"), nullable=False)
    document_ids = Column(JSONType, default=list)
    profile = Column(String(20), default="STANDARD")
    state = Column(String(30), default="QUEUED")
    progress = Column(Float, default=0.0)
    stage_message = Column(String(300), default="")
    verification_key = Column(String(64), index=True)
    scores = Column(JSONType, default=dict)
    timeline = Column(JSONType, default=list)
    unavailable_sources = Column(JSONType, default=list)
    unverified_items = Column(JSONType, default=list)
    errors = Column(JSONType, default=list)
    result_json = Column(JSONType)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime)


class VerificationCheck(Base):
    __tablename__ = "verification_checks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(40), ForeignKey("verification_runs.id"), nullable=False)
    name = Column(String(80))
    state = Column(String(30))
    detail = Column(JSONType, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class FindingRow(Base):
    __tablename__ = "findings"
    id = Column(String(40), primary_key=True)
    run_id = Column(String(40), ForeignKey("verification_runs.id"), nullable=False)
    project_id = Column(String(40), ForeignKey("projects.id"), nullable=False)
    document_id = Column(String(40), ForeignKey("documents.id"))
    type = Column(String(60), index=True)
    status = Column(String(30), index=True)
    severity = Column(String(20), index=True)
    evidence_grade = Column(String(4))
    confidence = Column(Float, default=0.0)
    page = Column(Integer)
    block_id = Column(String(40))
    title = Column(Text, default="")
    detail = Column(Text, default="")
    engine = Column(String(60))
    meta_message_type = Column(String(10))
    advisory_only = Column(Boolean, default=False)
    tags = Column(JSONType, default=list)
    data = Column(JSONType, default=dict)
    sealed_excerpt = Column(Text)
    """봉인 원문. API 기본 응답에서 제외되며 열람은 Audit에 기록된다(제7-A.6장)."""
    review_status = Column(String(20), default="NEEDS_REVIEW")
    review_note = Column(Text, default="")
    reviewed_by = Column(String(40))
    reviewed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


class EvidenceRow(Base):
    __tablename__ = "evidence"
    id = Column(String(40), primary_key=True)
    finding_id = Column(String(40), ForeignKey("findings.id"), nullable=False)
    data = Column(JSONType, default=dict)


class SourceRecordRow(Base):
    __tablename__ = "source_records"
    id = Column(String(40), primary_key=True)
    run_id = Column(String(40), ForeignKey("verification_runs.id"))
    adapter = Column(String(60))
    query = Column(Text)
    status = Column(String(20))
    result_id = Column(String(200))
    response_hash = Column(String(64))
    url = Column(Text)
    used_fields = Column(JSONType, default=list)
    retrieved_at = Column(DateTime, default=datetime.utcnow)


class ModelExecutionRow(Base):
    __tablename__ = "model_executions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(40), ForeignKey("verification_runs.id"))
    role = Column(String(40))
    provider = Column(String(40))
    model = Column(String(120))
    ok = Column(Boolean, default=True)
    quarantined = Column(Boolean, default=False)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    latency_ms = Column(Integer, default=0)
    prompt_version = Column(String(20))
    created_at = Column(DateTime, default=datetime.utcnow)


class APIExecutionRow(Base):
    __tablename__ = "api_executions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(40), ForeignKey("verification_runs.id"))
    adapter = Column(String(60))
    status = Column(String(20))
    latency_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditEventRow(Base):
    """Append-only. 수정·삭제하지 않는다(부록 C 제7항)."""

    __tablename__ = "audit_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sequence = Column(Integer, nullable=False)
    project_id = Column(String(40), index=True)
    document_id = Column(String(40))
    event_type = Column(String(40), nullable=False)
    actor = Column(String(80), default="system")
    payload = Column(JSONType, default=dict)
    previous_hash = Column(String(64), nullable=False)
    event_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ReportRow(Base):
    __tablename__ = "reports"
    id = Column(String(40), primary_key=True, default=lambda: new_uuid("rpt_"))
    project_id = Column(String(40), ForeignKey("projects.id"), nullable=False)
    run_id = Column(String(40), ForeignKey("verification_runs.id"))
    formats = Column(JSONType, default=list)
    artifacts = Column(JSONType, default=dict)
    include_sealed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ExportArtifactRow(Base):
    __tablename__ = "export_artifacts"
    id = Column(String(40), primary_key=True, default=lambda: new_uuid("exp_"))
    report_id = Column(String(40), ForeignKey("reports.id"))
    format = Column(String(20))
    storage_key = Column(String(400))
    sha256 = Column(String(64))
    size_bytes = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
        _engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
        if settings.database_url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragma(dbapi_connection, connection_record):  # pragma: no cover
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False, future=True)
    return _SessionLocal


def init_db() -> None:
    Base.metadata.create_all(bind=get_engine())


def get_db() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def reset_engine() -> None:  # 테스트용
    global _engine, _SessionLocal
    _engine = None
    _SessionLocal = None
