"""Friendly operational status and optional technical detail at desktop/mobile widths."""
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def test_diagnostics_layout_and_technical_disclosure(tmp_path):
    static = ROOT / "apps/web/static"
    files = {f"/static/{path.relative_to(static).as_posix()}": path for path in static.rglob("*") if path.is_file()}
    files["/"] = ROOT / "apps/web/index.html"
    data = {"verdict": "DEGRADED", "note": "스캔 문서 읽기 준비가 완료되지 않았습니다.", "capabilities": {
        "ocr": {"ready": False, "available": False, "status": "NOT_INSTALLED", "missing_languages": None},
        "rasterizer": {"available": True}, "database": {"dialect": "sqlite"}, "worker_mode": "auto",
        "browser_session": {"idle_hours": 12, "absolute_hours": 168, "renew_on_activity": True,
                            "analysis_protection_hours": 72, "result_review_hours": 6},
        "network_allowed": True, "source_keys_present": {"law_go_kr": True}}}
    def respond(route):
        path = urlsplit(route.request.url).path
        if path in files:
            route.fulfill(path=str(files[path]))
        elif path == "/api/health":
            route.fulfill(json={"status": "ok", "version": "0.5.0"})
        elif path == "/api/diagnostics":
            route.fulfill(json=data)
        else:
            route.fulfill(status=401, json={"detail": "Login required"})
    with sync_playwright() as playwright:
        options = {"headless": True}
        if os.getenv("LV_TEST_BROWSER_CHANNEL"):
            options["channel"] = os.environ["LV_TEST_BROWSER_CHANNEL"]
        browser = playwright.chromium.launch(**options)
        try:
            for width, height in ((1440, 960), (390, 844)):
                page = browser.new_page(viewport={"width": width, "height": height})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/*", respond)
                page.goto("http://diagnostics.test/")
                expect(page.get_by_role("dialog", name="작업 공간 로그인")).to_be_visible()
                page.keyboard.press("Escape")
                page.locator("#settingsButton").click()
                dialog = page.locator("#settingsDialog")
                expect(dialog).to_be_visible()
                expect(dialog).to_contain_text("점검 필요")
                expect(dialog).to_contain_text("Tesseract")
                expect(dialog).to_contain_text("백업")
                expect(dialog).to_contain_text("사용 중 자동 연장")
                expect(dialog).to_contain_text("일반 미사용 12시간 · 일반 로그인 최대 168시간")
                expect(dialog).to_contain_text("분석 시작부터 최대 72시간 보호")
                expect(dialog).to_contain_text("종료 후 6시간 결과 확인")
                expect(dialog.locator("pre")).to_be_hidden()
                assert dialog.evaluate("el => el.scrollWidth <= el.clientWidth")
                page.screenshot(path=str(tmp_path / f"diagnostics-{width}.png"), full_page=True)
                dialog.locator("summary").click()
                expect(dialog.locator("pre")).to_contain_text('"missing_languages": null')
                assert dialog.evaluate("el => el.scrollWidth <= el.clientWidth")
                healthy = {**data, "capabilities": {**data["capabilities"], "ocr": {"ready": True}}}
                page.evaluate("data => renderDiagnostics(data)", healthy)
                expect(dialog).to_contain_text("준비 완료")
                expect(dialog.locator("pre")).to_be_hidden()
                assert not errors
                page.close()
        finally:
            browser.close()
