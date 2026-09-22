"""Serialize trash/restore and new work against the same project row."""
from sqlalchemy import select

from .db import Project


def lock_project(session, project_id):
    if session.get_bind().dialect.name == "sqlite":
        connection = session.connection()
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
    return session.scalar(select(Project).where(Project.id == project_id).with_for_update()
                          .execution_options(populate_existing=True))
