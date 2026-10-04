"""업로드 개인정보 안내 및 확인 브라우저(UI) 검증 시험 (새 시험).

요구사항:
1. '파일 추가' 근처에 상시 보이는 안내문 3대 문구와 확인 체크박스 노출.
2. 체크 전에는 업로드가 막히며, 이유를 알리는 안내 메시지(aria-live)가 표시된다.
3. 체크 후에는 업로드가 진행되며, privacy_ack 필드가 함께 전송된다.
4. 체크 상태는 프로젝트·세션 단위로 기억되어 유지된다.
5. 검증 보고서 화면 머리에 자동 마스킹 보장 범위가 한 줄로 표시된다.
"""
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = b"Synthetic legal document bytes for browser test"


@pytest.fixture
def browser_test_page():
    """정적 프론트엔드 파일 및 모의 API 라우팅을 제공하는 Playwright fixture."""
    static = ROOT / "apps/web/static"
    files = {f"/static/{p.relative_to(static).as_posix()}": p for p in static.rglob("*") if p.is_file()}
    files["/"] = ROOT / "apps/web/index.html"
    project = {
        "id": "proj_browser_test",
        "name": "개인정보 안내 브라우저 시험",
        "external_ai_policy": "LOCAL_ONLY",
        "document_count": 0,
        "scope_revision": 1,
    }
    document = {
        "id": "doc_test_1",
        "project_id": "proj_browser_test",
        "filename": "합성소장.pdf",
        "sha256": hashlib.sha256(PAYLOAD).hexdigest(),
        "size_bytes": len(PAYLOAD),
        "included_in_verification": True,
        "mime_type": "application/pdf",
    }
    control = {"posts": 0, "last_post_body": None, "document": document}

    def respond(route):
        path = urlsplit(route.request.url).path
        if path in files:
            route.fulfill(path=str(files[path]))
        elif path == "/api/health":
            route.fulfill(json={"status": "ok", "version": "0.5.0"})
        elif path == "/api/projects":
            route.fulfill(json=[project])
        elif path == f"/api/projects/{project['id']}":
            route.fulfill(json=project)
        elif path == f"/api/projects/{project['id']}/documents":
            if route.request.method == "GET":
                route.fulfill(json=[])
                return
            control["posts"] += 1
            control["last_post_body"] = route.request.post_data_buffer
            route.fulfill(status=201, json=document)
        elif path == f"/api/projects/{project['id']}/reports":
            route.fulfill(json=[])
        elif path == "/api/privacy-notice":
            route.fulfill(json={
                "title": "제한적 개인정보 가림 기능 제공 안내",
                "version": "1.1",
                "bullets": [
                    "본 프로그램의 개인정보 가림기능은 제한적으로 적용됩니다.",
                    "개인정보 중 연락처, 주민등록번호는 필수기능으로 제공되지만, 성명·주소 등 그 밖의 개인정보는 보조기능으로만 가려지며 모두 가려진다고 보장하지 않습니다.",
                    "그러므로 민감하다고 생각되는 개인정보는 업로드 전에 직접 가림 처리 하시고 업로드 해 주세요.",
                ],
                "ack_label": "연락처, 주민등록번호 이외의 개인정보는 미포함되었거나 직접 가림 처리 하였음을 확인합니다.",
                "report_header": "제한적 개인정보 가림: 연락처·주민등록번호는 필수 가림, 그 밖의 개인정보는 사용자 처리",
                "ack_error_message": "연락처, 주민등록번호 이외의 개인정보가 미포함되었거나 직접 가림 처리하였음을 확인해야 업로드할 수 있습니다.",
            })
        else:
            route.fulfill(status=401, json={"detail": "Login required"})

    with sync_playwright() as playwright:
        options = {"headless": True}
        channel = os.getenv("LV_TEST_BROWSER_CHANNEL") or ("chrome" if os.name == "nt" else None)
        if channel:
            options["channel"] = channel
        browser = playwright.chromium.launch(**options)
        try:
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            page.route("**/*", respond)
            page.goto("https://uploads.test/")
            # 로그인 모달 닫기
            try:
                login_dialog = page.get_by_role("dialog", name="작업 공간 로그인")
                if login_dialog.is_visible():
                    page.keyboard.press("Escape")
            except Exception:
                pass
            page.evaluate("""() => {
                document.querySelectorAll('dialog[open]').forEach(d => d.close());
            }""")
            page.evaluate("""project => {
                state.project = project;
                document.getElementById('emptyState').hidden = true;
                document.getElementById('projectView').hidden = false;
                renderProject();
            }""", project)
            yield page, control
            assert not errors
        finally:
            browser.close()


def test_privacy_notice_and_checkbox_visible_on_documents_panel(browser_test_page):
    """자료 패널에 제목(새 상수), 판 번호(1.1), 상시 안내문 3대 문구와 확인 체크박스(라벨 연결)가 상시 표시된다."""
    page, _ = browser_test_page

    notice = page.locator(".privacy-notice")
    expect(notice).to_be_visible()

    # 제목 및 판 번호(1.1) 검증 (4절 추가 시험: 제목이 화면에 보인다)
    title = page.locator("#privacyNoticeTitle")
    expect(title).to_be_visible()
    expect(title).to_have_text("제한적 개인정보 가림 기능 제공 안내")

    version = page.locator("#privacyNoticeVersion")
    expect(version).to_have_text("(v1.1)")

    # 상시 안내 3대 확정 문구 검증
    expect(notice).to_contain_text("본 프로그램의 개인정보 가림기능은 제한적으로 적용됩니다.")
    expect(notice).to_contain_text("개인정보 중 연락처, 주민등록번호는 필수기능으로 제공되지만")
    expect(notice).to_contain_text("그러므로 민감하다고 생각되는 개인정보는 업로드 전에 직접 가림 처리 하시고")

    # 체크박스 및 라벨 검증
    checkbox = page.locator("#privacyAck")
    expect(checkbox).to_be_visible()
    expect(checkbox).not_to_be_checked()

    label = page.locator("label.privacy-ack-label")
    expect(label).to_contain_text("연락처, 주민등록번호 이외의 개인정보는 미포함되었거나 직접 가림 처리 하였음을 확인합니다.")


def test_upload_blocked_without_check_and_shows_accessible_error(browser_test_page):
    """체크박스 미체크 상태에서는 파일 업로드가 차단되고 aria-live 에러 메시지가 표시된다."""
    page, control = browser_test_page

    # 체크하지 않은 상태에서 파일 선택 시도
    page.locator("#fileInput").set_input_files({
        "name": "합성소장.pdf",
        "mimeType": "application/pdf",
        "buffer": PAYLOAD,
    })

    # 서버로 POST가 전송되지 않았음 검증
    assert control["posts"] == 0

    # 에러 메시지 표시 및 접근성 속성 검증
    error_el = page.locator("#privacyAckError")
    expect(error_el).to_be_visible()
    expect(error_el).to_contain_text("연락처, 주민등록번호 이외의 개인정보가 미포함되었거나 직접 가림 처리하였음을 확인해야 업로드할 수 있습니다.")
    assert error_el.get_attribute("role") == "status"
    assert error_el.get_attribute("aria-live") == "polite"


def test_upload_proceeds_after_check_and_remembers_state(browser_test_page):
    """체크박스 체크 후 업로드가 정상 진행되며, privacy_ack가 전송되고 상태가 유지된다."""
    page, control = browser_test_page

    # 열려있는 모달이 있으면 닫기
    page.evaluate("document.querySelectorAll('dialog[open]').forEach(d => d.close())")

    # 체크박스 체크 (JS evaluate 또는 direct click)
    page.evaluate("""() => {
        const cb = document.getElementById('privacyAck');
        cb.checked = true;
        cb.dispatchEvent(new Event('change'));
    }""")
    expect(page.locator("#privacyAck")).to_be_checked()

    # 파일 선택 시도
    page.locator("#fileInput").set_input_files({
        "name": "합성소장.pdf",
        "mimeType": "application/pdf",
        "buffer": PAYLOAD,
    })

    # 업로드 성공 및 결과 영역 표시 확인
    expect(page.locator("#uploadStatus")).to_contain_text("파일 등록 결과")
    assert control["posts"] == 1
    # 폼 데이터에 privacy_ack 필드가 포함되어 전송되었는지 검증
    assert b"privacy_ack" in control["last_post_body"]

    # 에러 메시지는 숨겨져야 함
    expect(page.locator("#privacyAckError")).to_be_hidden()

    # 프로젝트 재랜더링 시에도 체크 상태가 유지되는지 검증 (프로젝트·세션 단위 기억)
    page.evaluate("renderProject()")
    expect(page.locator("#privacyAck")).to_be_checked()


def test_report_header_shows_privacy_guarantee_scope(browser_test_page):
    """검증 보고서 화면 머리에 자동 마스킹 보장 범위 안내가 한 줄로 표시된다."""
    page, _ = browser_test_page

    # 보고서 탭으로 전환
    page.evaluate("switchTab('reports')")

    report_notice = page.locator(".report-privacy-notice")
    expect(report_notice).to_be_visible()
    expect(report_notice).to_contain_text("제한적 개인정보 가림: 연락처·주민등록번호는 필수 가림, 그 밖의 개인정보는 사용자 처리")


def test_upload_blocked_when_notice_loading_or_failed():
    """4절 추가 시험: 안내를 불러오기 전과 불러오기 실패 시 업로드가 막힌다."""
    static = ROOT / "apps/web/static"
    files = {f"/static/{p.relative_to(static).as_posix()}": p for p in static.rglob("*") if p.is_file()}
    files["/"] = ROOT / "apps/web/index.html"
    project = {
        "id": "proj_fail_test",
        "name": "안내 로드 실패 시험 프로젝트",
        "external_ai_policy": "LOCAL_ONLY",
        "document_count": 0,
        "scope_revision": 1,
    }
    control = {"posts": 0}

    def failing_respond(route):
        path = urlsplit(route.request.url).path
        if path in files:
            route.fulfill(path=str(files[path]))
        elif path == "/api/health":
            route.fulfill(json={"status": "ok", "version": "0.5.0"})
        elif path == "/api/projects":
            route.fulfill(json=[project])
        elif path == f"/api/projects/{project['id']}":
            route.fulfill(json=project)
        elif path == f"/api/projects/{project['id']}/documents":
            control["posts"] += 1
            route.fulfill(status=201, json={"id": "doc1"})
        elif path == "/api/privacy-notice":
            # 500 서버 오류 모의 (안내 불러오기 실패)
            route.fulfill(status=500, json={"detail": "Internal Server Error"})
        else:
            route.fulfill(status=401, json={"detail": "Unauthorized"})

    with sync_playwright() as playwright:
        options = {"headless": True}
        channel = os.getenv("LV_TEST_BROWSER_CHANNEL") or ("chrome" if os.name == "nt" else None)
        if channel:
            options["channel"] = channel
        browser = playwright.chromium.launch(**options)
        try:
            page = browser.new_page()
            page.route("**/*", failing_respond)
            page.goto("https://uploads.test/")
            page.evaluate("""project => {
                state.project = project;
                document.getElementById('emptyState').hidden = true;
                document.getElementById('projectView').hidden = false;
                renderProject();
            }""", project)

            # 1. 화면에 안내 불러오기 실패 메시지 표시 확인
            title_el = page.locator("#privacyNoticeTitle")
            expect(title_el).to_have_text("안내 불러오기 실패")

            bullets_el = page.locator("#privacyNoticeBullets")
            expect(bullets_el).to_contain_text("개인정보 처리 안내를 불러오지 못했습니다")

            # 2. 파일 추가 input이 disabled 상태인지 확인
            expect(page.locator("#fileInput")).to_be_disabled()

            # 3. 파일 선택 시도 시 업로드가 차단되고 POST가 전송되지 않음을 검증
            page.locator("#fileInput").set_input_files({
                "name": "업로드차단문서.pdf",
                "mimeType": "application/pdf",
                "buffer": PAYLOAD,
            })
            assert control["posts"] == 0, "안내 로드 실패 시 업로드가 차단되어야 한다"

            # 4. 토스트 알림으로 실패 이유가 공지되는지 확인
            toast_el = page.locator("#toast")
            expect(toast_el).to_be_visible()
            expect(toast_el).to_contain_text("개인정보 처리 안내를 불러오지 못했습니다")
        finally:
            browser.close()


def test_upload_blocked_when_privacy_notice_returns_401_unauthenticated():
    """3차 보완 새 시험: 401(로그인 전/인증 만료)이면 안내를 불러오지 못해 업로드가 막힌다."""
    static = ROOT / "apps/web/static"
    files = {f"/static/{p.relative_to(static).as_posix()}": p for p in static.rglob("*") if p.is_file()}
    files["/"] = ROOT / "apps/web/index.html"
    project = {
        "id": "proj_401_test",
        "name": "401 미인증 업로드 차단 시험 프로젝트",
        "external_ai_policy": "LOCAL_ONLY",
        "document_count": 0,
        "scope_revision": 1,
    }
    control = {"posts": 0}

    def unauth_respond(route):
        path = urlsplit(route.request.url).path
        if path in files:
            route.fulfill(path=str(files[path]))
        elif path == "/api/health":
            route.fulfill(json={"status": "ok", "version": "0.5.0"})
        elif path == "/api/projects":
            route.fulfill(json=[project])
        elif path == f"/api/projects/{project['id']}":
            route.fulfill(json=project)
        elif path == f"/api/projects/{project['id']}/documents":
            control["posts"] += 1
            route.fulfill(status=201, json={"id": "doc1"})
        elif path == "/api/privacy-notice":
            # 401 비인증/로그인 전 응답 모의
            route.fulfill(status=401, json={"detail": "Authentication required"})
        else:
            route.fulfill(status=401, json={"detail": "Unauthorized"})

    with sync_playwright() as playwright:
        options = {"headless": True}
        channel = os.getenv("LV_TEST_BROWSER_CHANNEL") or ("chrome" if os.name == "nt" else None)
        if channel:
            options["channel"] = channel
        browser = playwright.chromium.launch(**options)
        try:
            page = browser.new_page()
            page.route("**/*", unauth_respond)
            page.goto("https://uploads.test/")
            page.evaluate("""project => {
                state.project = project;
                document.getElementById('emptyState').hidden = true;
                document.getElementById('projectView').hidden = false;
                renderProject();
            }""", project)

            # 1. 401 응답 시 제품 코드가 임의 문구 사본으로 우회하지 않고 정상적으로 실패 처리됨을 확인
            title_el = page.locator("#privacyNoticeTitle")
            expect(title_el).to_have_text("안내 불러오기 실패")

            bullets_el = page.locator("#privacyNoticeBullets")
            expect(bullets_el).to_contain_text("개인정보 처리 안내를 불러오지 못했습니다")

            # 2. 파일 추가 input이 disabled 상태로 차단되었는지 확인
            expect(page.locator("#fileInput")).to_be_disabled()

            # 3. 파일 선택을 시도해도 업로드가 진행되지 않고 POST가 0건임을 검증
            page.locator("#fileInput").set_input_files({
                "name": "차단문서.pdf",
                "mimeType": "application/pdf",
                "buffer": PAYLOAD,
            })
            assert control["posts"] == 0, "401 응답 시 업로드가 막혀야 한다"

            # 4. 토스트 알림으로 안내 로드 실패 사유가 공지됨을 확인
            toast_el = page.locator("#toast")
            expect(toast_el).to_be_visible()
            expect(toast_el).to_contain_text("개인정보 처리 안내를 불러오지 못했습니다")
        finally:
            browser.close()

