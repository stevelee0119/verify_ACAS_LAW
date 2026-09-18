"""Human review records, separate from immutable engine results."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from .db import Base, JSONType, new_uuid


class CaseIssue(Base):
    __tablename__ = "case_issues"
    id = Column(String(40), primary_key=True, default=lambda: new_uuid("iss_"))
    project_id = Column(String(40), ForeignKey("projects.id"), nullable=False, index=True)
    title = Column(String(300), nullable=False)
    elements = Column(JSONType, default=list)
    reference_date = Column(String(10))
    legal_basis = Column(Text, default="")
    priority = Column(Integer, default=2)
    note = Column(Text, default="")
    revision = Column(Integer, nullable=False, default=1)
    updated_by = Column(String(80), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)


class CaseProfile(Base):
    __tablename__ = "case_profiles"
    project_id = Column(String(40), ForeignKey("projects.id"), primary_key=True)
    lead_reviewer = Column(String(120), default="")
    represented_party = Column(String(200), default="")
    revision = Column(Integer, nullable=False, default=1)
    updated_by = Column(String(80), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)


class ClaimAssessment(Base):
    __tablename__ = "claim_assessments"
    __table_args__ = (UniqueConstraint("run_id", "claim_id"),)
    id = Column(String(40), primary_key=True, default=lambda: new_uuid("ca_"))
    project_id = Column(String(40), ForeignKey("projects.id"), nullable=False, index=True)
    run_id = Column(String(40), ForeignKey("verification_runs.id"), nullable=False)
    document_id = Column(String(40), ForeignKey("documents.id"), nullable=False)
    claim_id = Column(String(80), nullable=False)
    issue_id = Column(String(40), ForeignKey("case_issues.id"))
    position = Column(String(30), default="UNASSESSED")
    support_status = Column(String(30), default="UNASSESSED")
    evidence_links = Column(JSONType, default=list)
    missing_material = Column(Text, default="")
    note = Column(Text, default="")
    revision = Column(Integer, nullable=False, default=1)
    updated_by = Column(String(80), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)


class FindingWorkflow(Base):
    __tablename__ = "finding_workflows"
    finding_id = Column(String(40), ForeignKey("findings.id"), primary_key=True)
    workflow_state = Column(String(30), default="NOT_STARTED")
    decision = Column(String(30), default="UNDECIDED")
    priority = Column(Integer, default=2)
    assignee = Column(String(120), default="")
    note = Column(Text, default="")
    revision = Column(Integer, nullable=False, default=1)
    updated_by = Column(String(80), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)


class ReviewDraft(Base):
    __tablename__ = "review_drafts"
    finding_id = Column(String(40), ForeignKey("findings.id"), primary_key=True)
    user_id = Column(String(80), primary_key=True)
    note = Column(Text, default="")
    base_revision = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow)


class ReviewRevision(Base):
    __tablename__ = "review_revisions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(40), ForeignKey("projects.id"), nullable=False, index=True)
    subject_type = Column(String(30), nullable=False)
    subject_id = Column(String(80), nullable=False)
    actor = Column(String(80), nullable=False)
    before = Column(JSONType, default=dict)
    after = Column(JSONType, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class DocumentRelation(Base):
    __tablename__ = "document_relations"
    child_id = Column(String(40), ForeignKey("documents.id"), primary_key=True)
    parent_id = Column(String(40), ForeignKey("documents.id"), nullable=False)
    project_id = Column(String(40), ForeignKey("projects.id"), nullable=False, index=True)
    kind = Column(String(20), default="REVISION")
    note = Column(Text, default="")
    created_by = Column(String(80), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ReportReview(Base):
    __tablename__ = "report_reviews"
    report_id = Column(String(40), ForeignKey("reports.id"), primary_key=True)
    audience = Column(String(20), default="INTERNAL")
    state = Column(String(20), default="DRAFT")
    note = Column(Text, default="")
    created_by = Column(String(80), nullable=False)
    finalized_by = Column(String(80))
    finalized_at = Column(DateTime)
    review_snapshot = Column(JSONType, default=dict)
    snapshot_hash = Column(String(64), nullable=False)


def as_dict(row):
    if row is None:
        return {}
    return {c.name: (value.isoformat() if isinstance(value, datetime) else value)
            for c in row.__table__.columns for value in [getattr(row, c.name)]}
