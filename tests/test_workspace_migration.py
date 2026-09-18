"""Upgrade legacy databases without losing documents or review records."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_upgrade_existing_review_database(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "legacy.db").as_posix()
    monkeypatch.setenv("LV_DATABASE_URL", url)
    engine = create_engine(url)
    with engine.begin() as connection:
        for table in ("users", "projects", "verification_runs", "findings", "reports"):
            connection.exec_driver_sql(f"CREATE TABLE {table} (id VARCHAR(40) PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE documents (id VARCHAR(40) PRIMARY KEY, filename VARCHAR(400))")
        connection.exec_driver_sql("INSERT INTO documents VALUES ('existing-document', 'original.pdf')")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.stamp(config, "c82d01")
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    schema = inspect(engine)
    assert {"case_issues", "finding_workflows", "review_drafts", "review_revisions", "claim_assessments",
            "identity_accounts", "identity_api_tokens", "identity_browser_sessions", "identity_external",
            "durable_jobs", "job_attempts", "budget_accounts", "budget_reservations"} <= set(schema.get_table_names())
    assert "submitted_on" in {c["name"] for c in schema.get_columns("documents")}
    assert "base_revision" in {c["name"] for c in schema.get_columns("review_drafts")}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT filename FROM documents WHERE id='existing-document'")).scalar_one() == "original.pdf"
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "e2fc39"
    engine.dispose()
