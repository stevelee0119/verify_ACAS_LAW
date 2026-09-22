"""Upgrade legacy databases without losing documents or review records."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_upgrade_existing_review_database(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "legacy.db").as_posix()
    monkeypatch.setenv("LV_DATABASE_URL", url)
    engine = create_engine(url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "c82d01")
    with engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO projects (id, name) VALUES ('existing-project', 'Original case')")
        connection.exec_driver_sql(
            "INSERT INTO documents (id, project_id, filename, sha256, storage_key) "
            "VALUES ('existing-document', 'existing-project', 'original.pdf', 'original-hash', 'original-key')"
        )
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
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "b83f21"
    engine.dispose()
