"""종합행정학교 법무교육단 ACASia_LAW 알림 및 이메일 발송 패키지."""
from .mailer import (
    send_approval_email,
    send_quota_warning_email,
)

__all__ = [
    "send_approval_email",
    "send_quota_warning_email",
]
