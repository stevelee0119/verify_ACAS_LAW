from packages.common.privacy_notice import (
    ACK_LABEL,
    NOTICE_BULLETS,
    NOTICE_TITLE,
    PRIVACY_ACK_ERROR_MESSAGE,
    PRIVACY_NOTICE_VERSION,
    REPORT_HEADER_NOTICE,
)


def select_first_project(page):
    if not page.locator("#sidebar").is_visible():
        page.get_by_role("button", name="프로젝트 목록", exact=True).click()
    page.locator("#projectList > button").first.click()


def privacy_notice_mock_payload() -> dict:
    """모의 브라우저 시험용 개인정보 처리 안내 모의 응답 페이로드 (상수 연동)."""
    return {
        "title": NOTICE_TITLE,
        "version": PRIVACY_NOTICE_VERSION,
        "bullets": NOTICE_BULLETS,
        "ack_label": ACK_LABEL,
        "report_header": REPORT_HEADER_NOTICE,
        "ack_error_message": PRIVACY_ACK_ERROR_MESSAGE,
    }

