"""종합행정학교 법무교육단 ACASia_LAW 이메일 발송 모듈.

- 관리자 승인 완료 안내 메일 (엠블럼 이미지 첨부)
- 70% 저장소 용량 초과 경고 메일
- SMTP 미설정과 전송 실패를 성공으로 취급하지 않는다.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from html import escape
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

logger = logging.getLogger("notification_engine.mailer")

@dataclass(frozen=True)
class MailResult:
    status: str
    error_code: str = ""

    def __bool__(self):
        return self.status == "SMTP_ACCEPTED"


def _env(name: str, default: str = "") -> str:
    return os.getenv("LV_SMTP_" + name, os.getenv("SMTP_" + name, default))


def smtp_configuration() -> dict:
    """Public, credential-free configuration readiness, not a connectivity test."""
    try:
        port = int(_env("PORT", "587"))
    except ValueError:
        port = 0
    host = _env("HOST").strip()
    sender = _env("FROM", _env("USER")).strip()
    tls = _env("USE_TLS", "true").lower() in {"true", "1", "yes"}
    implicit = port == 465 or _env("USE_SSL", "false").lower() in {"true", "1", "yes"}
    missing = [name for name, value in (("HOST", host), ("FROM", sender)) if not value]
    code = "SMTP_NOT_CONFIGURED" if missing else ""
    if not code and (not 1 <= port <= 65535 or "@" not in sender
                     or any(c in sender + host for c in "\r\n")
                     or bool(_env("USER")) != bool(_env("PASSWORD"))
                     or not (tls or implicit)):
        code = "SMTP_INVALID_CONFIGURATION"
    return {"configured": not code, "error_code": code, "missing": missing,
            "port": port, "security": "SSL" if implicit else "STARTTLS",
            "delivery_confirmation": "SMTP_ACCEPTED"}

# 엠블럼 이미지 경로 확인
def _get_emblem_path() -> Optional[Path]:
    """종합행정학교 법무교육단 엠블럼 이미지 경로를 탐색한다."""
    base_dir = Path(__file__).resolve().parents[2]
    candidates = [
        base_dir / "apps" / "web" / "static" / "acas-law-emblem.jpg",
        base_dir / "apps" / "web" / "static" / "img" / "emblem.png",
        base_dir / "apps" / "web" / "static" / "img" / "emblem-192.png",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def send_approval_email(to_email: str, user_name: str) -> MailResult:
    """사용자 등록 승인 완료 안내 이메일을 발송한다.
    
    엠블럼 이미지를 cid:emblem 형태로 인라인 첨부하며,
    종합행정학교 법무교육단의 정중한 안내 문구를 포함한다.
    """
    subject = "[ACASia_LAW] 사용자 등록 신청이 승인되었습니다"
    user_display = escape(user_name or "사용자")
    display_email = escape(to_email)

    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: 'Malgun Gothic', '맑은 고딕', sans-serif; line-height: 1.6; color: #2d3748; background-color: #f7fafc; padding: 20px; }}
  .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; border: 1px solid #e2e8f0; }}
  .header {{ background-color: #1a365d; text-align: center; padding: 25px 20px; }}
  .header img {{ max-width: 240px; height: auto; }}
  .content {{ padding: 30px; }}
  .title {{ font-size: 20px; font-weight: bold; color: #1a365d; margin-bottom: 20px; }}
  .box {{ background: #edf2f7; border-left: 4px solid #3182ce; padding: 15px; margin: 20px 0; border-radius: 4px; }}
  .footer {{ background: #edf2f7; text-align: center; padding: 15px; font-size: 12px; color: #718096; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <img src="cid:emblem" alt="종합행정학교 법무교육단">
  </div>
  <div class="content">
    <div class="title">사용자 등록 승인 안내</div>
    <p>안녕하십니까, <strong>{user_display}</strong>님.</p>
    <p>종합행정학교 법무교육단 <strong>ACASia_LAW 법률문서 검증시스템</strong>에 신청하신 사용자 계정이 정상적으로 승인되었습니다.</p>
    <div class="box">
      <strong>계정 ID (이메일):</strong> {display_email}<br>
      <strong>상태:</strong> 승인 완료 (정상 이용 가능)
    </div>
    <p>이제 등록하신 이메일과 비밀번호로 시스템에 로그인하여 법률문서 검증 및 분석 기능을 이용하실 수 있습니다.</p>
    <p>감사합니다.</p>
  </div>
  <div class="footer">
    종합행정학교 법무교육단 법률문서 검증시스템 (ACASia_LAW)<br>
    본 메일은 발신 전용 메일입니다.
  </div>
</div>
</body>
</html>
"""
    return _send_email_internal(to_email, subject, html_content, attach_emblem=True)


def send_quota_warning_email(to_email: str, user_name: str, used_bytes: int, quota_bytes: int) -> MailResult:
    """개인 저장소 용량 70% 초과 경고 이메일을 발송한다."""
    subject = "[ACASia_LAW] 개인 저장소 용량 70% 초과 경고 안내"
    user_display = escape(user_name or "사용자")
    used_mb = used_bytes / (1024 * 1024)
    quota_mb = quota_bytes / (1024 * 1024)
    percent = (used_bytes / quota_bytes * 100) if quota_bytes > 0 else 0

    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: 'Malgun Gothic', '맑은 고딕', sans-serif; line-height: 1.6; color: #2d3748; background-color: #f7fafc; padding: 20px; }}
  .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; border: 1px solid #e2e8f0; }}
  .header {{ background-color: #742a2a; text-align: center; padding: 25px 20px; color: #ffffff; }}
  .content {{ padding: 30px; }}
  .title {{ font-size: 20px; font-weight: bold; color: #9b2c2c; margin-bottom: 20px; }}
  .box {{ background: #fff5f5; border-left: 4px solid #e53e3e; padding: 15px; margin: 20px 0; border-radius: 4px; }}
  .footer {{ background: #edf2f7; text-align: center; padding: 15px; font-size: 12px; color: #718096; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h2 style="margin:0;">ACASia_LAW 용량 경고 안내</h2>
  </div>
  <div class="content">
    <div class="title">개인 저장소 용량 70% 초과 알림</div>
    <p>안녕하십니까, <strong>{user_display}</strong>님.</p>
    <p>현재 ACASia_LAW 시스템 내 활성 원본 자료의 저장 용량이 설정된 한도의 <strong>70%</strong>에 도달했습니다.</p>
    <div class="box">
      <strong>현재 사용량:</strong> {used_mb:.1f} MB / {quota_mb:.0f} MB ({percent:.1f}%)<br>
      <strong>남은 용량:</strong> {max(0.0, quota_mb - used_mb):.1f} MB
    </div>
    <p>설정된 저장소 한도를 초과하면 새 파일 등록이 제한됩니다.</p>
    <p>원활한 업무 수행을 위해 완료된 사건이나 불필요한 자료를 휴지통으로 이동 후 정리하시기 바랍니다.</p>
    <p>감사합니다.</p>
  </div>
  <div class="footer">
    종합행정학교 법무교육단 법률문서 검증시스템 (ACASia_LAW)<br>
    본 메일은 발신 전용 메일입니다.
  </div>
</div>
</body>
</html>
"""
    return _send_email_internal(to_email, subject, html_content, attach_emblem=False)


def _send_email_internal(to_email: str, subject: str, html_content: str, attach_emblem: bool = False) -> MailResult:
    config = smtp_configuration()
    if not config["configured"]:
        return MailResult("UNAVAILABLE", config["error_code"])
    if any(c in to_email for c in "\r\n") or "@" not in to_email:
        return MailResult("FAILED", "INVALID_RECIPIENT")

    sending = accepted = False
    try:
        msg = MIMEMultipart("related")
        msg["Subject"] = subject
        msg["From"] = _env("FROM", _env("USER")).strip()
        msg["To"] = to_email

        alt = MIMEMultipart("alternative")
        msg.attach(alt)

        # HTML 본문 추가
        html_part = MIMEText(html_content, "html", "utf-8")
        alt.attach(html_part)

        # 엠블럼 이미지 첨부 (cid:emblem)
        if attach_emblem:
            emblem_path = _get_emblem_path()
            if emblem_path and emblem_path.is_file():
                with open(emblem_path, "rb") as f:
                    img_data = f.read()
                img_part = MIMEImage(img_data)
                img_part.add_header("Content-ID", "<emblem>")
                img_part.add_header("Content-Disposition", "inline", filename=emblem_path.name)
                msg.attach(img_part)

        # SMTP 전송
        context = ssl.create_default_context()
        client = smtplib.SMTP_SSL if config["security"] == "SSL" else smtplib.SMTP
        kwargs = {"context": context} if client is smtplib.SMTP_SSL else {}
        with client(_env("HOST").strip(), config["port"], timeout=10, **kwargs) as server:
            if config["security"] == "STARTTLS":
                server.starttls(context=context)
            if _env("USER"):
                server.login(_env("USER").strip(), _env("PASSWORD"))
            sending = True
            if server.send_message(msg):
                return MailResult("FAILED", "SMTP_RECIPIENT_REFUSED")
            accepted = True

        return MailResult("SMTP_ACCEPTED")
    except Exception as exc:
        if accepted:
            return MailResult("SMTP_ACCEPTED")
        logger.warning("smtp_send_failed error_type=%s", type(exc).__name__)
        if sending and (isinstance(exc, smtplib.SMTPServerDisconnected)
                        or (isinstance(exc, OSError) and not isinstance(exc, smtplib.SMTPException))):
            return MailResult("UNKNOWN", "DELIVERY_UNCONFIRMED")
        code = "SMTP_AUTHENTICATION_FAILED" if isinstance(exc, smtplib.SMTPAuthenticationError) else "SMTP_SEND_FAILED"
        return MailResult("FAILED", code)
