"""Idle browser sessions with a bounded, non-renewable absolute lifetime."""
import os
from datetime import datetime, timedelta


RENEW_INTERVAL = timedelta(minutes=15)


def session_lifetimes() -> tuple[timedelta, timedelta]:
    idle = int(os.getenv("LV_SESSION_TTL_HOURS", "24"))
    absolute = int(os.getenv("LV_SESSION_ABSOLUTE_HOURS", "168"))
    if not 1 <= idle <= 720 or not 1 <= absolute <= 720:
        raise ValueError("Session lifetimes must be between 1 and 720 hours")
    return timedelta(hours=min(idle, absolute)), timedelta(hours=absolute)


def session_deadline(issued_at: datetime, now: datetime) -> datetime:
    idle, absolute = session_lifetimes()
    return min(now + idle, issued_at + absolute)


def absolute_deadline(issued_at: datetime) -> datetime:
    return issued_at + session_lifetimes()[1]
