"""Upload recovery never repeats an uncertain POST or mistakes a broken response for success."""
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = b"Synthetic document bytes"


@pytest.fixture
def upload_page():
    static = ROOT / "apps/web/static"
    files = {f"/static/{p.relative_to(static).as_posix()}": p for p in static.rglob("*") if p.is_file()}
    files["/"] = ROOT / "apps/web/index.html"
    project = {"id": "project", "name": "업로드 시험", "external_ai_policy": "LOCAL_ONLY", "document_count": 0}
    document = {"id": "document", "project_id": "project", "filename": "검토의견서.docx",
                "sha256": hashlib.sha256(PAYLOAD).hexdigest(), "size_bytes": len(PAYLOAD),
                "included_in_verification": True, "mime_type": "application/octet-stream"}
    control = {"mode": "success", "documents": [], "posts": 0, "document": document}

    def respond(route):
        path = urlsplit(route.request.url).path
        if path in files:
            route.fulfill(path=str(files[path]))
        elif path == "/api/health":
            route.fulfill(json={"status": "ok", "version": "0.5.0"})
        elif path == "/api/projects":
            route.fulfill(json=[project])
        elif path == "/api/projects/project":
            route.fulfill(json=project)
        elif path == "/api/projects/project/documents":
            if route.request.method == "GET":
                route.fulfill(json=control["documents"])
                return
            control["posts"] += 1
            assert PAYLOAD in route.request.post_data_buffer
            mode = control["mode"]
            if mode in {"success", "lost_saved"}:
                control["documents"] = [document]
            if mode in {"lost_saved", "network"}:
                route.abort("failed")
            elif mode == "bad_json":
                route.fulfill(status=201, content_type="text/html", body="<html>Invalid response</html>")
            elif mode == "http_error":
                route.fulfill(status=503, content_type="text/html", body="Unavailable")
            else:
                route.fulfill(status=201, json=document)
        else:
            route.fulfill(status=401, json={"detail": "Login required"})

    with sync_playwright() as playwright:
        options = {"headless": True}
        if os.getenv("LV_TEST_BROWSER_CHANNEL"):
            options["channel"] = os.environ["LV_TEST_BROWSER_CHANNEL"]
        browser = playwright.chromium.launch(**options)
        try:
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/*", respond)
            page.goto("https://uploads.test/")
            expect(page.get_by_role("dialog", name="작업 공간 로그인")).to_be_visible()
            page.keyboard.press("Escape")
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


def select_file(page):
    page.locator("#fileInput").set_input_files({"name": "검토의견서.docx", "mimeType": "application/octet-stream", "buffer": PAYLOAD})
    expect(page.locator("#uploadStatus")).to_contain_text("파일 등록 결과")


@pytest.mark.parametrize("mode,expected", [
    ("success", "REGISTERED"), ("lost_saved", "REGISTERED"),
    ("network", "UNCONFIRMED"), ("bad_json", "UNCONFIRMED"), ("http_error", "UNCONFIRMED"),
])
def test_registration_outcome_and_no_blind_post_retry(upload_page, mode, expected):
    page, control = upload_page
    control["mode"] = mode
    select_file(page)
    assert page.evaluate("state.uploadBatch.entries[0].status") == expected
    assert control["posts"] == 1
    if mode in {"bad_json", "http_error", "network"}:
        assert page.evaluate("state.uploadBatch.entries[0].error.code") == {
            "bad_json": "INVALID_RESPONSE", "http_error": "HTTP_ERROR", "network": "NETWORK_ERROR"
        }[mode]
        if mode == "http_error":
            expect(page.locator("#uploadStatus")).to_contain_text("HTTP 503")
        # A later completed request can be reconciled by hash without another POST.
        control["documents"] = [control["document"]]
        page.get_by_role("button", name="등록 내역 다시 확인").click()
        expect(page.locator("#uploadStatus")).to_contain_text("1/1개 확인")
        assert control["posts"] == 1


def test_unreadable_local_file_is_not_sent(upload_page):
    page, control = upload_page
    page.evaluate("""async () => {
        const file = new File(['data'], 'unavailable.docx');
        file.arrayBuffer = async () => {throw new DOMException('Unavailable', 'NotReadableError');};
        await upload([file]);
    }""")
    expect(page.locator("#uploadStatus")).to_contain_text("기기에서 파일을 읽지 못했습니다")
    assert page.evaluate("state.uploadBatch.entries[0].status") == "FAILED"
    assert control["posts"] == 0


def test_timeout_is_not_rethrown_as_raw_dom_exception(upload_page):
    page, _ = upload_page
    result = page.evaluate("""async () => {
        const original = window.fetch;
        window.fetch = (url, options) => new Promise((resolve, reject) => {
            options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
        });
        try { await send('/timeout', {timeoutMs: 10}); }
        catch (error) { return {code: error.code, uncertain: error.uncertain}; }
        finally { window.fetch = original; }
    }""")
    assert result == {"code": "TIMEOUT", "uncertain": True}


def test_upload_status_responsive_and_project_scoped(upload_page, tmp_path):
    page, control = upload_page
    control["mode"] = "network"
    select_file(page)
    for width, height in ((1440, 960), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        area = page.locator("#uploadStatus")
        area.locator("summary").click()
        assert area.evaluate("el => el.scrollWidth <= el.clientWidth")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / f"upload-state-{width}.png"), full_page=True)
        area.locator("summary").click()
    page.evaluate("state.project = {...state.project, id:'another-project'}; renderProject()")
    expect(page.locator("#uploadStatus")).to_be_hidden()
