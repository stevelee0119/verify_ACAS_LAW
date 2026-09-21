"""The progress screen distinguishes slow work from a lost polling connection."""
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def test_progress_staleness_reconnect_and_layout(tmp_path):
    static = ROOT / "apps/web/static"
    files = {f"/static/{path.relative_to(static).as_posix()}": path for path in static.rglob("*") if path.is_file()}
    files["/"] = ROOT / "apps/web/index.html"
    disconnected = [True]
    run = {"id": "run", "state": "VERIFYING", "stage_message": "검토의견서.docx 법률 인용 확인 12/46건",
           "progress": 0.52, "document_ids": [], "started_at": "2026-09-21T00:00:00"}

    def respond(route):
        path = urlsplit(route.request.url).path
        if path in files:
            route.fulfill(path=str(files[path]))
        elif path == "/api/health":
            route.fulfill(json={"status": "ok", "version": "0.5.0"})
        elif path == "/api/verification-runs/run":
            if disconnected[0]:
                route.abort("failed")
            else:
                route.fulfill(json=run)
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
                page.goto("http://progress.test/")
                expect(page.get_by_role("dialog", name="작업 공간 로그인")).to_be_visible()
                page.keyboard.press("Escape")
                page.evaluate("""run => {
                    state.project = {id:'project', name:'진행 상태 검토', external_ai_policy:'LOCAL_ONLY'};
                    state.run = run;
                    document.getElementById('emptyState').hidden = true;
                    document.getElementById('projectView').hidden = false;
                    renderProject();
                }""", run)
                notice = page.locator("#progressNotice")
                expect(notice).to_be_hidden()
                page.evaluate("state.progressSeen.at -= 65000; renderProgressNotice()")
                expect(notice).to_contain_text("변경되지 않았습니다")
                disconnected[0] = True
                page.evaluate("pollRun(state.generation)")
                expect(notice).to_contain_text("자동으로 다시 연결", timeout=5000)
                assert notice.evaluate("el => el.scrollWidth <= el.clientWidth")
                page.screenshot(path=str(tmp_path / f"progress-reconnect-{width}.png"), full_page=True)
                disconnected[0] = False
                expect(notice).to_contain_text("서버 응답은 정상", timeout=5000)
                page.evaluate("state.run.progress = .6; renderProject(); clearTimeout(state.timer)")
                expect(notice).to_be_hidden()
                expect(page.locator("#progressPercent")).to_have_text("60%")
                expect(page.get_by_role("button", name="검증 취소", exact=True)).to_be_enabled()
                page.evaluate("""() => {
                    state.run.stage_message = '검토의견서.docx 법률 인용 확인 46/46건 · 지연된 인용 다시 확인 12/18건';
                    renderProject();
                }""")
                expect(page.locator("#progressText")).to_contain_text("지연된 인용 다시 확인")
                assert page.locator("#progress").evaluate("el => el.scrollWidth <= el.clientWidth")
                page.screenshot(path=str(tmp_path / f"progress-source-recovery-{width}.png"), full_page=True)
                assert not errors
                page.close()
        finally:
            browser.close()
