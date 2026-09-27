"""Transfer only the project IDs captured by revision f57a63, once."""
import logging
import os
from datetime import datetime

from sqlalchemy import select

from .db import LegacyProjectOwnership, Project, User, get_session_factory
from .identity import user_is_enabled


def migrate_legacy_project_ownership():
    with get_session_factory()() as session:
        if session.get_bind().dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        rows = session.scalars(select(LegacyProjectOwnership).where(
            LegacyProjectOwnership.migrated_at.is_(None)).with_for_update()).all()
        if not rows:
            return 0
        email = os.getenv("LV_BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
        admin = session.scalar(select(User).where(User.email == email).with_for_update()) if email else None
        if not admin or admin.role != "ADMIN" or not admin.organization_id or not user_is_enabled(session, admin):
            raise RuntimeError("Legacy project transfer requires the active LV_BOOTSTRAP_ADMIN_EMAIL administrator")
        now = datetime.utcnow()
        for row in rows:
            project = session.get(Project, row.project_id)
            if project is None:
                raise RuntimeError("A captured legacy project is missing")
            project.owner_id = admin.id
            project.organization_id = admin.organization_id
            row.target_owner_id, row.migrated_at = admin.id, now
        session.commit()
        logging.getLogger(__name__).info("legacy_project_ownership_completed count=%s", len(rows))
        return len(rows)
