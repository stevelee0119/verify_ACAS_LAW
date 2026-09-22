"""Exercise the published migration graph using real, populated SQLite schemas."""
from datetime import datetime
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine


ROOT = Path(__file__).resolve().parents[1]
MERGED_HEAD = "f3a91c"
CURRENT_HEAD = "a72e10"
CREATED = datetime(2026, 9, 1, 10, 0, 0)
EXPIRES = datetime(2027, 9, 1, 10, 0, 0)
PASSWORD_HASH = "scrypt$32768$8$1$" + "01" * 16 + "$" + "02" * 32
STARTING_REVISIONS = [
    "base", "98e07fd05c9e", "a1c4e77b9d20", "c82d01",
    "d14ac2e9b150", "e2fc39", "b2d5f88c0e31", "both-branches",
]


@pytest.fixture
def migration_db(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "historical.db").as_posix()
    monkeypatch.setenv("LV_DATABASE_URL", url)

    def enforce_foreign_keys(dbapi_connection, _):
        if isinstance(dbapi_connection, sqlite3.Connection):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    # Include Alembic's independently opened connections, not just fixture writes.
    sa.event.listen(Engine, "connect", enforce_foreign_keys)
    engine = sa.create_engine(url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    try:
        yield config, engine
    finally:
        engine.dispose()
        sa.event.remove(Engine, "connect", enforce_foreign_keys)


def _insert(connection, table_name, **values):
    table = sa.Table(table_name, sa.MetaData(), autoload_with=connection)
    connection.execute(table.insert().values(**values))


def _seed_database(engine):
    with engine.begin() as connection:
        tables = set(sa.inspect(connection).get_table_names())
        has_passwords = "session_tokens" in tables
        _insert(connection, "organizations", id="org-original", name="Original organization")
        for user_id, role, org, created in [
            ("owner", "ADMIN", "org-original", CREATED),
            ("viewer", "VIEWER", "org-original", CREATED),
            ("inactive", "MEMBER", "org-original", CREATED),
            ("no-org", "MEMBER", None, None),
            ("unassigned", None, None, CREATED),
        ]:
            credentials = {}
            if has_passwords:
                credentials = dict(
                    password_hash=PASSWORD_HASH, is_active=user_id != "inactive",
                    last_login_at=CREATED, failed_login_count=3, locked_until=EXPIRES,
                )
            _insert(connection, "users", id=user_id, email=f"{user_id}@example.test",
                    display_name=user_id, role=role, organization_id=org,
                    created_at=created, **credentials)
        _insert(connection, "projects", id="case-original", name="Original case",
                owner_id="owner", organization_id="org-original")
        _insert(connection, "projects", id="case-no-org", name="Standalone case",
                owner_id="no-org", organization_id=None)
        _insert(connection, "project_members", project_id="case-original", user_id="viewer", role="VIEWER")
        _insert(connection, "documents", id="document-original", project_id="case-original",
                filename="original.pdf", sha256="1" * 64, storage_key="original-key")
        _insert(connection, "verification_runs", id="run-original", project_id="case-original")
        _insert(connection, "findings", id="finding-original", run_id="run-original",
                project_id="case-original", document_id="document-original")
        _insert(connection, "reports", id="report-original", project_id="case-original", run_id="run-original")
        _insert(connection, "audit_events", sequence=1, project_id="case-original",
                event_type="created", previous_hash="0" * 64, event_hash="2" * 64, actor="owner")
        if has_passwords:
            for session_id, revoked_at in [("session-active", None), ("session-revoked", CREATED)]:
                _insert(connection, "session_tokens", id=session_id, user_id="owner",
                        token_hash=session_id.ljust(64, "0"), issued_at=CREATED,
                        expires_at=EXPIRES, revoked_at=revoked_at, user_agent="original-agent")
        if "case_issues" in tables:
            _insert(connection, "case_issues", id="issue-original", project_id="case-original",
                    title="Original issue", revision=2, updated_by="owner", updated_at=CREATED)
            _insert(connection, "finding_workflows", finding_id="finding-original",
                    workflow_state="reviewed", note="Original review", revision=3,
                    updated_by="owner", updated_at=CREATED)
            _insert(connection, "review_drafts", finding_id="finding-original", user_id="viewer",
                    note="Original draft", base_revision=3, updated_at=CREATED)
            _insert(connection, "review_revisions", project_id="case-original", subject_type="finding",
                    subject_id="finding-original", actor="owner", created_at=CREATED)
            _insert(connection, "report_reviews", report_id="report-original", state="finalized",
                    created_by="owner", finalized_by="owner", finalized_at=CREATED, snapshot_hash="3" * 64)
        if "identity_accounts" in tables:
            _insert(connection, "identity_accounts", user_id="owner", enabled=True, created_at=CREATED)
            _insert(connection, "identity_accounts", user_id="viewer", enabled=False, created_at=CREATED)
            _insert(connection, "identity_api_tokens", id="api-original", user_id="owner",
                    token_hash="4" * 64, label="Original token", created_at=CREATED, expires_at=EXPIRES)
            _insert(connection, "identity_external", id="external-original", user_id="owner",
                    issuer="https://issuer.example.test", subject="original-subject")
            _insert(connection, "identity_browser_sessions", id="browser-original", user_id="owner",
                    secret_hash="5" * 64, source_kind="token", source_id="api-original",
                    created_at=CREATED, expires_at=EXPIRES)
            _insert(connection, "durable_jobs", run_id="run-original", project_id="case-original",
                    snapshot="{}", snapshot_hash="6" * 64, dedup_key="7" * 64,
                    budget_run_id="run-original", state="queued", fence=1, attempts=1,
                    max_attempts=3, available_at=CREATED, created_at=CREATED, updated_at=CREATED)
            _insert(connection, "job_attempts", run_id="run-original", fence=1, owner="worker-original",
                    state="retry", partial_result="{}", executions="[]", started_at=CREATED)
            _insert(connection, "budget_accounts", id="month-original", limit_units=10000,
                    reserved_units=100, spent_units=200, updated_at=CREATED)
            _insert(connection, "budget_reservations", id="reservation-original", run_id="run-original",
                    monthly_account="month-original", run_account="run-original", state="reserved",
                    reserved_units=100, detail="{}", created_at=CREATED)


def _snapshot(engine):
    with engine.connect() as connection:
        return {
            name: (table, list(connection.execute(sa.select(table).order_by(*table.primary_key)).all()))
            for name in sa.inspect(connection).get_table_names()
            if name != "alembic_version"
            for table in [sa.Table(name, sa.MetaData(), autoload_with=connection)]
        }


def _assert_preserved(engine, snapshot):
    with engine.connect() as connection:
        for name, (table, old_rows) in snapshot.items():
            rows = connection.execute(sa.select(table).order_by(*table.primary_key)).all()
            if name == "identity_accounts":
                assert set(old_rows) <= set(rows)
            else:
                assert rows == old_rows, f"Existing data changed in {name}"
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []


def test_published_revision_parents_are_unchanged(migration_db):
    config, _ = migration_db
    graph = ScriptDirectory.from_config(config)
    assert graph.get_heads() == [CURRENT_HEAD]
    assert graph.get_revision(CURRENT_HEAD).down_revision == MERGED_HEAD
    for revision, parent in {
        "98e07fd05c9e": None,
        "a1c4e77b9d20": "98e07fd05c9e",
        "b2d5f88c0e31": "a1c4e77b9d20",
        "c82d01": "a1c4e77b9d20",
        "d14ac2e9b150": "c82d01",
        "e2fc39": "d14ac2e9b150",
    }.items():
        assert graph.get_revision(revision).down_revision == parent
    assert set(graph.get_revision(MERGED_HEAD).down_revision) == {"e2fc39", "b2d5f88c0e31"}


@pytest.mark.parametrize("starting_revision", STARTING_REVISIONS)
def test_upgrade_preserves_existing_deployments(migration_db, starting_revision):
    config, engine = migration_db
    if starting_revision == "both-branches":
        command.upgrade(config, "e2fc39")
        command.upgrade(config, "b2d5f88c0e31")
    else:
        command.upgrade(config, starting_revision)
    if starting_revision != "base":
        _seed_database(engine)
    before = _snapshot(engine)

    command.upgrade(config, "head")
    _assert_preserved(engine, before)
    merged = _snapshot(engine)
    command.upgrade(config, "head")
    _assert_preserved(engine, merged)

    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars().all() == [CURRENT_HEAD]
        assert {"session_tokens", "identity_accounts", "identity_api_tokens", "identity_browser_sessions",
                "identity_external", "review_drafts", "review_revisions", "durable_jobs", "budget_accounts"} <= set(merged)
        users = sa.Table("users", sa.MetaData(), autoload_with=connection)
        accounts = sa.Table("identity_accounts", sa.MetaData(), autoload_with=connection)
        records = connection.execute(sa.select(users.c.id, users.c.is_active, users.c.created_at,
                                             accounts.c.enabled, accounts.c.created_at.label("account_created"))
                                     .join(accounts, users.c.id == accounts.c.user_id)).mappings().all()
        assert len(records) == (0 if starting_revision == "base" else 5)
        previous_accounts = {row.user_id: row for row in before.get("identity_accounts", (None, []))[1]}
        for row in records:
            assert row.enabled == (previous_accounts[row.id].enabled if row.id in previous_accounts else row.is_active)
            assert row.account_created is not None
            if row.created_at is not None:
                assert row.account_created == row.created_at


def test_reconciliation_rerun_preserves_account_decisions(migration_db):
    config, engine = migration_db
    command.upgrade(config, "e2fc39")
    command.upgrade(config, "b2d5f88c0e31")
    _seed_database(engine)
    command.upgrade(config, "head")
    with engine.begin() as connection:
        connection.execute(sa.text("UPDATE identity_accounts SET enabled = 0 WHERE user_id = 'owner'"))
        _insert(connection, "users", id="later-user", email="later@example.test", role="VIEWER", is_active=False)
    before = _snapshot(engine)
    # Re-run just the merge after its data work has already been applied, as in a
    # retry restored to the two-parent revision marker. No parent DDL is replayed.
    command.stamp(config, ["e2fc39", "b2d5f88c0e31"], purge=True)
    command.upgrade(config, "head")
    _assert_preserved(engine, before)
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT enabled FROM identity_accounts WHERE user_id = 'later-user'")).scalar_one() == 0
        assert connection.execute(sa.text("SELECT enabled FROM identity_accounts WHERE user_id = 'owner'")).scalar_one() == 0


def test_merge_downgrade_refuses_to_discard_auth_history(migration_db):
    config, engine = migration_db
    command.upgrade(config, "b2d5f88c0e31")
    _seed_database(engine)
    command.upgrade(config, MERGED_HEAD)
    before = _snapshot(engine)
    with pytest.raises(RuntimeError, match="restore a verified backup"):
        command.downgrade(config, "e2fc39")
    _assert_preserved(engine, before)
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == MERGED_HEAD


def test_project_trash_upgrade_from_schema_without_trash_columns(migration_db):
    config, engine = migration_db
    command.upgrade(config, MERGED_HEAD)
    _seed_database(engine)
    assert {"deleted_at", "deleted_by"}.isdisjoint(
        {column["name"] for column in sa.inspect(engine).get_columns("projects")})
    before = _snapshot(engine)
    command.upgrade(config, "head")
    _assert_preserved(engine, before)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT deleted_at, deleted_by FROM projects").all() == [(None, None), (None, None)]
        assert "ix_projects_deleted_at" in {index["name"] for index in sa.inspect(connection).get_indexes("projects")}
    with engine.begin() as connection:
        connection.execute(sa.text("UPDATE projects SET deleted_at=:at, deleted_by='owner' WHERE id='case-original'"), {"at": CREATED})
    before = _snapshot(engine)
    with pytest.raises(RuntimeError, match="restore a verified backup"):
        command.downgrade(config, MERGED_HEAD)
    _assert_preserved(engine, before)
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == CURRENT_HEAD
