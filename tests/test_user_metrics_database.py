"""Run grouped metrics against the database selected by the SQLite/PG CI job."""
import os
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from apps.api.db import AuditEventRow, Base, Document, Organization, Project, User, VerificationRun
from apps.api.user_metrics import get_all_users_monthly_metrics
from apps.api.storage_quota import check_user_quota
from apps.api.workspace import ReportJob


def test_metrics_sql_with_real_database(tmp_path):
    engine = create_engine(os.getenv("LV_TEST_DATABASE_URL") or f"sqlite:///{tmp_path}/metrics.db")
    Base.metadata.create_all(engine)
    prefix = uuid4().hex
    at = datetime(2026, 8, 10)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                with Session(connection) as session:
                    org = Organization(name=prefix)
                    session.add(org)
                    session.flush()
                    user = User(email=f"{prefix}@example.test", organization_id=org.id)
                    session.add(user)
                    session.flush()
                    project = Project(name=prefix, owner_id=user.id, organization_id=org.id)
                    session.add(project)
                    session.flush()
                    run = VerificationRun(project_id=project.id, started_at=at,
                                          finished_at=at + timedelta(seconds=60))
                    session.add(run)
                    session.flush()
                    session.add_all([
                        ReportJob(project_id=project.id, run_id=run.id, created_by=user.id,
                                  created_at=at, finished_at=at + timedelta(seconds=30)),
                        Document(project_id=project.id, filename="test.txt", storage_key=prefix,
                                 sha256="a"*64, size_bytes=1048576, uploaded_at=at),
                    ])
                    sequence = session.scalar(select(func.max(AuditEventRow.sequence))) or 0
                    for index, event in enumerate(("LOGIN_SUCCEEDED", "PROJECT_QUERY"), 1):
                        session.add(AuditEventRow(sequence=sequence+index, event_type="API_QUERY",
                            actor=user.id, payload={"event": event}, previous_hash="0"*64,
                            event_hash=uuid4().hex*2, created_at=at))
                    session.flush()
                    metrics = get_all_users_monthly_metrics(session, 2026, 8, org.id)[user.id]
                    assert metrics["login_count"] == 1
                    assert metrics["verification_count"] == 1
                    assert metrics["compute_seconds"] == pytest.approx(90, abs=0.1)
                    assert metrics["storage_used_mb"] == metrics["monthly_upload_mb"] == 1
                    project.deleted_at = at
                    session.flush()
                    metrics = get_all_users_monthly_metrics(session, 2026, 8, org.id)[user.id]
                    assert metrics["storage_used_mb"] == 1
                    assert metrics["storage_quota_mb"] == 1024
                    assert check_user_quota(session, user, 1073741824)[0] is True
                    user.role = "ADMIN"
                    session.flush()
                    metrics = get_all_users_monthly_metrics(session, 2026, 8, org.id)[user.id]
                    assert metrics["storage_used_mb"] == 1
                    assert metrics["storage_unlimited"] is True
                    assert metrics["storage_quota_mb"] is None
                    assert check_user_quota(session, user, 1073741824)[0] is False
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
