"""종합행정학교 법무교육단 ACASia_LAW 이메일 발송 모듈.

- 관리자 승인 완료 안내 메일 (엠블럼 이미지 첨부)
- 70% 저장소 용량 초과 경고 메일
- SMTP 미설정 시 mock 로깅 모드 자동 전환
"""
from __future__ import annotations

import logging
import os
import smtplib
import threading
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

logger = logging.getLogger("notification_engine.mailer")

# SMTP 설정 (환경 변수)
SMTP_HOST = os.getenv("LV_SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("LV_SMTP_PORT", "587"))
SMTP_USER = os.getenv("LV_SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("LV_SMTP_PASSWORD", "").strip()
SMTP_FROM = os.getenv("LV_SMTP_FROM", "noreply@acas-law.mil.kr").strip()
SMTP_USE_TLS = os.getenv("LV_SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")

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


def send_approval_email(to_email: str, user_name: str) -> bool:
    """사용자 등록 승인 완료 안내 이메일을 발송한다.
    
    엠블럼 이미지를 cid:emblem 형태로 인라인 첨부하며,
    종합행정학교 법무교육단의 정중한 안내 문구를 포함한다.
    """
    subject = "[ACASia_LAW] 사용자 등록 신청이 승인되었습니다"
    user_display = user_name or "사용자"

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
      <strong>계정 ID (이메일):</strong> {to_email}<br>
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


def send_quota_warning_email(to_email: str, user_name: str, used_bytes: int, quota_bytes: int) -> bool:
    """개인 저장소 용량 70% 초과 경고 이메일을 발송한다."""
    subject = "[ACASia_LAW] 개인 저장소 용량 70% 초과 경고 안내"
    user_display = user_name or "사용자"
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
    <p>현재 ACASia_LAW 시스템 내 개인 저장소 사용량이 기본 제공 용량(1GB)의 <strong>70%</strong>를 초과하였습니다.</p>
    <div class="box">
      <strong>현재 사용량:</strong> {used_mb:.1f} MB / {quota_mb:.0f} MB ({percent:.1f}%)<br>
      <strong>남은 용량:</strong> {max(0.0, quota_mb - used_mb):.1f} MB
    </div>
    <p>저장소 용량(1GB)을 완전히 초과하는 경우 새로운 파일 등록 및 검증 진행이 제한될 수 있습니다.</p>
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


def _send_email_internal(to_email: str, subject: str, html_content: str, attach_emblem: bool = False) -> bool:
    """실제 메일을 발송하거나 mock 로깅 모드로 처리한다."""
    if not SMTP_HOST:
        logger.info("[Mock Mailer] SMTP_HOST 미설정 - 테스트 로그 발송: To=%s, Subject=%s", to_email, subject)
        return True

    try:
        msg = MIMEMultipart("related")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
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
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            if SMTP_USE_TLS:
                server.starttls()
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

        logger.info("[Mailer] 이메일 발송 성공: %s", to_email)
        return True
    except Exception as exc:
        logger.error("[Mailer] 이메일 발송 실패 (%s): %s", to_email, exc)
        return False


def send_approval_email_background(to_email: str, user_name: str) -> None:
    """백그라운드 스레드로 승인 안내 메일을 비동기 발송한다."""
    thread = threading.Thread(
        target=send_approval_email,
        args=(to_email, user_name),
        daemon=True,
    )
    thread.start()


def send_quota_warning_email_background(to_email: str, user_name: str, used_bytes: int, quota_bytes: int) -> None:
    """백그라운드 스레드로 70% 용량 경고 메일을 비동기 발송한다."""
    thread = threading.Thread(
        target=send_quota_warning_email,
        args=(to_email, user_name, used_bytes, quota_bytes),
        daemon=True,
    )
    thread.start()
