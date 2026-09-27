"""Transactional outbox on the existing database; no external queue required."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from sqlalchemy import select, update

from .db import User, UserNotification, get_session_factory
from packages.notification_engine.mailer import (
    send_approval_email, send_quota_warning_email, smtp_configuration,
)

logger = logging.getLogger(__name__)
RETRYABLE = {"FAILED", "UNAVAILABLE"}


def queue_notification(session, user, kind, payload=None):
    row = UserNotification(user_id=user.id, kind=kind, payload=payload or {})
    session.add(row)
    session.flush()
    return row


def queue_quota_warning(session, user, used_bytes):
    now = datetime.utcnow()
    # The owner row is locked by the upload transaction. Failed attempts also
    # throttle automatic mail; explicit administrator retry remains available.
    recent = session.scalar(select(UserNotification.id).where(
        UserNotification.user_id == user.id, UserNotification.kind == "QUOTA",
        UserNotification.created_at >= now - timedelta(hours=24)).limit(1))
    if recent or (user.quota_warning_sent_at and user.quota_warning_sent_at > now - timedelta(hours=24)):
        return None
    return queue_notification(session, user, "QUOTA", {"used_bytes": used_bytes,
                                                     "quota_bytes": user.storage_quota_bytes})


def notification_out(row):
    return {key: (value.isoformat() + "Z" if isinstance(value, datetime) else value)
            for key in ("id", "user_id", "kind", "status", "attempts", "error_code",
                        "created_at", "attempted_at", "finished_at")
            for value in [getattr(row, key)]}


def dispatch_once():
    factory = get_session_factory()
    now = datetime.utcnow()
    with factory() as session:
        # A crash during SMTP DATA is ambiguous. Do not auto-resend and risk duplicates.
        session.execute(update(UserNotification).where(
            UserNotification.status == "SENDING",
            UserNotification.attempted_at < now - timedelta(minutes=5),
        ).values(status="UNKNOWN", error_code="DELIVERY_UNCONFIRMED", finished_at=now))
        mail_id = session.scalar(select(UserNotification.id).where(
            UserNotification.status == "QUEUED", UserNotification.attempts < 3
        ).order_by(UserNotification.created_at).limit(1))
        session.commit()
        if mail_id is None:
            return False
        claimed = session.execute(update(UserNotification).where(
            UserNotification.id == mail_id, UserNotification.status == "QUEUED",
        ).values(status="SENDING", attempted_at=now, attempts=UserNotification.attempts + 1))
        session.commit()
        if claimed.rowcount != 1:
            return True
        row = session.get(UserNotification, mail_id)
        user = session.get(User, row.user_id)
        if not user or not user.is_active or user.approval_status != "APPROVED":
            row.status, row.error_code, row.finished_at = "CANCELLED", "ACCOUNT_UNAVAILABLE", now
            session.commit()
            return True
        recipient, name, kind, payload = user.email, user.display_name, row.kind, row.payload
    # Never retain a database connection across a network call.
    if kind == "APPROVAL":
        result = send_approval_email(recipient, name)
    else:
        result = send_quota_warning_email(recipient, name, payload["used_bytes"], payload["quota_bytes"])
    with factory() as session:
        row = session.get(UserNotification, mail_id)
        row.status, row.error_code, row.finished_at = result.status, result.error_code, datetime.utcnow()
        if result.status == "SMTP_ACCEPTED" and kind == "QUOTA":
            user = session.get(User, row.user_id)
            if user:
                user.quota_warning_sent_at = row.finished_at
        session.commit()
    return True


class NotificationDispatcher:
    """One bounded dispatcher per process; compare-and-set claims across workers."""
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name="smtp-outbox", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=45)

    def run(self):
        while not self.stop_event.is_set():
            try:
                busy = dispatch_once()
            except Exception as exc:
                logger.warning("notification_dispatch_failed error_type=%s", type(exc).__name__)
                busy = False
            self.stop_event.wait(0.2 if busy else 5)
