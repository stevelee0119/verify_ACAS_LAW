"""보고서는 상단 '보고서 생성' 버튼으로 만들고, 보고서 탭에서는 내려받기만 한다(0.9.9)."""
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from test_frontend_report_progress import REPORT

ROOT = Path(__file__).resolve().parents[1]


def serve(run_state, seen):
    static = ROOT / "apps/web/static"
    files = {f"/static/{p.relative_to(static).as_posix()}": p for p in static.rglob("*") if p.is_file()}
    files["/"] = ROOT / "apps/web/index.html"
    run = {"id": "r1", "project_id": "p1", "state": run_state, "progress": 1, "stage_message": "",
           "document_ids": ["d1"], "scores": {}, "unverified_items": [], "errors": [], "unavailable_sources": [],
           "input_snapshot": {"scope_revision": 0}, "started_at": "2026-09-24T00:00:00"}
    project = {"id": "p1", "name": "시험 사건", "can_delete": True, "document_count": 1,
               "external_ai_policy": "MASKED", "scope_revision": 0}
    job = {"job_id": "rjb_1", "project_id": "p1", "run_id": "r1", "formats": ["pdf"], "error": None,
           "created_at": "2026-09-24T00:00:00"}

    def respond(route):
        request, path = route.request, urlsplit(route.request.url).path
        if path in files:
            return route.fulfill(path=str(files[path]))
        if path == "/api/projects/p1/report-jobs" and request.method == "POST":
            seen["posted"] = request.post_data_json
            return route.fulfill(status=202, json=dict(job, state="QUEUED", stage="대기", percent=0, report_id=None,
                                                       elapsed_seconds=0))
        if path == "/api/projects/p1/report-jobs/rjb_1":
            seen["done"] = True
            return route.fulfill(json=dict(job, state="COMPLETED", stage="완료", percent=100, report_id="rpt_1",
                                           elapsed_seconds=1))
        if path == "/api/projects/p1/reports":
            return route.fulfill(json=[REPORT] if seen.get("done") else [])
        replies = {"/api/health": {"status": "ok", "version": "0.9.9"},
                   "/api/identity/me": {"user_id": "u", "role": "ADMIN", "authentication": "password"},
                   "/api/verification-runs": {"active_count": 0, "runs": []},
                   "/api/projects": [project], "/api/projects/p1": project, "/api/projects/p1/runs": [run]}
        if path in replies:
            return route.fulfill(json=replies[path])
        if path.endswith("/result"):
            return route.fulfill(json={"documents": [{"document_id": "d1", "filename": "준비서면.pdf"}]})
        if path.endswith("/case-matrix"):
            return route.fulfill(body="null", content_type="application/json")
        return route.fulfill(json=[])
    return respond


def browser_page(playwright, width, height):
    options = {"headless": True}
    if os.getenv("LV_TEST_BROWSER_CHANNEL"):
        options["channel"] = os.environ["LV_TEST_BROWSER_CHANNEL"]
    browser = playwright.chromium.launch(**options)
    return browser, browser.new_page(viewport={"width": width, "height": height})


@pytest.mark.parametrize("width,height", [(1440, 1000), (768, 1024), (390, 1200)])
def test_top_button_generates_and_reports_tab_only_downloads(width, height):
    seen = {}
    with sync_playwright() as playwright:
        browser, page = browser_page(playwright, width, height)
        try:
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.route("**/*", serve("COMPLETED", seen))
            page.goto("http://reports.test/")
            button = page.locator("#reportBtn")
            expect(button).to_have_text("보고서 생성")
            expect(button).to_be_enabled()
            expect(page.locator("[data-panel='documents']")).to_be_visible()     # 다른 탭에서도 바로 생성한다
            button.click()
            dialog = page.get_by_role("dialog", name="검토 보고서 초안")
            for name in ("docx", "xlsx", "csv", "json", "manifest"):
                dialog.locator(f"input[name='{name}']").uncheck()
            dialog.get_by_role("button", name="초안 생성").click()
            expect(dialog).to_be_hidden()
            reports = page.locator("[data-panel='reports']")
            expect(reports).to_be_visible()
            expect(reports.locator("#reportList a", has_text="PDF")).to_be_visible()
            expect(reports.locator("button", has_text="보고서 생성")).to_have_count(0)
            expect(reports).to_contain_text("여기에서 내려받습니다")
            assert seen["posted"]["run_id"] == "r1" and seen["posted"]["formats"] == ["pdf"]
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert errors == []
        finally:
            browser.close()


@pytest.mark.parametrize("state", ["RUNNING", "QUEUED", "FAILED"])
def test_top_button_waits_for_a_finished_run(state):
    seen = {}
    with sync_playwright() as playwright:
        browser, page = browser_page(playwright, 1440, 1000)
        try:
            page.route("**/*", serve(state, seen))
            page.goto("http://reports.test/")
            expect(page.locator("#projectTitle")).to_have_text("시험 사건")
            expect(page.locator("#reportBtn")).to_be_disabled()
            expect(page.locator("#reportBtn")).to_have_attribute("title", "검증이 끝나면 보고서를 생성할 수 있습니다")
            assert "posted" not in seen
        finally:
            browser.close()
