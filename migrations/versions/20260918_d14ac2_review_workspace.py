"""Human review workspace and document submission date."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d14ac2e9b150"
down_revision = "c82d01"
branch_labels = None
depends_on = None


def _json(name):
    return sa.Column(name, sa.Text().with_variant(postgresql.JSONB(), "postgresql"))


def _id(name, target=None, primary=False, nullable=False):
    args = [sa.String(40)]
    if target:
        args.append(sa.ForeignKey(target))
    return sa.Column(name, *args, primary_key=primary, nullable=nullable)


def _review_fields():
    return [sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("updated_by", sa.String(80), nullable=False),
            sa.Column("updated_at", sa.DateTime())]


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "submitted_on" not in {c["name"] for c in sa.inspect(bind).get_columns("documents")}:
        op.add_column("documents", sa.Column("submitted_on", sa.String(10)))
    tables = {
        "case_issues": [
            _id("id", primary=True), _id("project_id", "projects.id"),
            sa.Column("title", sa.String(300), nullable=False), _json("elements"),
            sa.Column("reference_date", sa.String(10)), sa.Column("legal_basis", sa.Text()),
            sa.Column("priority", sa.Integer()), sa.Column("note", sa.Text()), *_review_fields()],
        "case_profiles": [
            _id("project_id", "projects.id", primary=True), sa.Column("lead_reviewer", sa.String(120)),
            sa.Column("represented_party", sa.String(200)), *_review_fields()],
        "claim_assessments": [
            _id("id", primary=True), _id("project_id", "projects.id"), _id("run_id", "verification_runs.id"),
            _id("document_id", "documents.id"), sa.Column("claim_id", sa.String(80), nullable=False),
            _id("issue_id", "case_issues.id", nullable=True), sa.Column("position", sa.String(30)),
            sa.Column("support_status", sa.String(30)), _json("evidence_links"),
            sa.Column("missing_material", sa.Text()), sa.Column("note", sa.Text()), *_review_fields(),
            sa.UniqueConstraint("run_id", "claim_id")],
        "finding_workflows": [
            _id("finding_id", "findings.id", primary=True), sa.Column("workflow_state", sa.String(30)),
            sa.Column("decision", sa.String(30)), sa.Column("priority", sa.Integer()),
            sa.Column("assignee", sa.String(120)), sa.Column("note", sa.Text()), *_review_fields()],
        "review_drafts": [
            _id("finding_id", "findings.id", primary=True), sa.Column("user_id", sa.String(80), primary_key=True),
            sa.Column("note", sa.Text()), sa.Column("base_revision", sa.Integer(), nullable=False, server_default="0"), sa.Column("updated_at", sa.DateTime())],
        "review_revisions": [
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), _id("project_id", "projects.id"),
            sa.Column("subject_type", sa.String(30), nullable=False), sa.Column("subject_id", sa.String(80), nullable=False),
            sa.Column("actor", sa.String(80), nullable=False), _json("before"), _json("after"), sa.Column("created_at", sa.DateTime())],
        "document_relations": [
            _id("child_id", "documents.id", primary=True), _id("parent_id", "documents.id"), _id("project_id", "projects.id"),
            sa.Column("kind", sa.String(20)), sa.Column("note", sa.Text()), sa.Column("created_by", sa.String(80), nullable=False),
            sa.Column("created_at", sa.DateTime())],
        "report_reviews": [
            _id("report_id", "reports.id", primary=True), sa.Column("audience", sa.String(20)), sa.Column("state", sa.String(20)),
            sa.Column("note", sa.Text()), sa.Column("created_by", sa.String(80), nullable=False), sa.Column("finalized_by", sa.String(80)),
            sa.Column("finalized_at", sa.DateTime()), _json("review_snapshot"), sa.Column("snapshot_hash", sa.String(64), nullable=False)],
    }
    for name, columns in tables.items():
        if name not in existing:
            op.create_table(name, *columns)
            if any(c.name == "project_id" for c in columns if isinstance(c, sa.Column)) and name != "case_profiles":
                op.create_index(f"ix_{name}_project_id", name, ["project_id"])


def downgrade():
    raise RuntimeError("Review history must be retained. Restore a verified backup for rollback.")
