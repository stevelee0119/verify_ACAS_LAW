"""보고서 생성 중에는 단계·진행률이 보이고, 연결이 잠시 끊겨도 생성 결과를 끝까지 받아 온다."""
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
REPORT = {"report_id": "rpt_1", "project_id": "p1", "run_id": "r1", "formats": ["pdf"], "include_sealed": False,
          "artifacts": {"pdf": {"sha256": "x", "size_bytes": 10, "download": "/api/reports/rpt_1/download/pdf"}},
          "created_at": "2026-09-24T00:00:00", "state": "DRAFT", "audience": "INTERNAL", "created_by": "u",
          "finalized_by": None, "finalized_at": None, "note": "", "snapshot_hash": "abc", "source_report_id": None,
          "label": "초안 · 내부 검토용"}


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 1200)])
def test_report_generation_shows_live_progress(width, height):
    static = ROOT / "apps/web/static"
    files = {f"/static/{p.relative_to(static).as_posix()}": p for p in static.rglob("*") if p.is_file()}
    files["/"] = ROOT / "apps/web/index.html"
    run = {"id": "r1", "project_id": "p1", "state": "COMPLETED", "progress": 1, "stage_message": "",
           "document_ids": ["d1"], "scores": {}, "unverified_items": [], "errors": [], "unavailable_sources": [],
           "input_snapshot": {"scope_revision": 0}, "started_at": "2026-09-24T00:00:00"}
    project = {"id": "p1", "name": "시험 사건", "can_delete": True, "document_count": 1,
               "external_ai_policy": "MASKED", "scope_revision": 0}
    job = {"job_id": "rjb_1", "project_id": "p1", "run_id": "r1", "formats": ["pdf"], "report_id": None,
           "error": None, "created_at": "2026-09-24T00:00:00"}
    # 조회할 때마다 다음 상태를 돌려준다. None은 연결이 끊긴 경우다.
    polls = [dict(job, state="RUNNING", stage="PDF 작성 중 (1/1)", percent=40, elapsed_seconds=3),
             None,
             dict(job, state="RUNNING", stage="보고서 파일을 저장하는 중", percent=96, elapsed_seconds=5),
             dict(job, state="COMPLETED", stage="완료", percent=100, report_id="rpt_1", elapsed_seconds=6)]
    seen = {"posted": None, "done": False}

    def respond(route):
        request = route.request
        path = urlsplit(request.url).path
        if path in files:
            return route.fulfill(path=str(files[path]))
        if path == "/api/projects/p1/report-jobs" and request.method == "POST":
            seen["posted"] = request.post_data_json
            return route.fulfill(status=202, json=dict(job, state="QUEUED", stage="보고서 생성을 기다리는 중",
                                                       percent=0, elapsed_seconds=0))
        if path == "/api/projects/p1/report-jobs/rjb_1":
            reply = polls.pop(0) if len(polls) > 1 else polls[0]
            if reply is None:
                return route.abort()
            seen["done"] = reply["state"] == "COMPLETED"
            return route.fulfill(json=reply)
        if path == "/api/projects/p1/reports":
            return route.fulfill(json=[REPORT] if seen["done"] else [])
        replies = {"/api/health": {"status": "ok", "version": "0.5.0"},
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

    with sync_playwright() as playwright:
        options = {"headless": True}
        if os.getenv("LV_TEST_BROWSER_CHANNEL"):
            options["channel"] = os.environ["LV_TEST_BROWSER_CHANNEL"]
        browser = playwright.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.route("**/*", respond)
            page.goto("http://reports.test/")
            page.locator("[data-tab='reports']").click()
            page.locator("#createReport").click()
            dialog = page.get_by_role("dialog", name="검토 보고서 초안")
            for name in ("docx", "xlsx", "csv", "json", "manifest"):
                dialog.locator(f"input[name='{name}']").uncheck()
            dialog.get_by_role("button", name="초안 생성").click()
            bar = dialog.get_by_role("progressbar")
            expect(bar).to_have_attribute("aria-valuenow", "40")
            expect(dialog.locator(".report-progress")).to_contain_text("PDF 작성 중 (1/1)")
            expect(dialog.locator(".report-progress")).to_contain_text("40%")
            expect(dialog.locator("select[name='audience']")).to_be_disabled()
            expect(dialog.locator(".report-progress")).to_contain_text("연결이 잠시 끊겨 다시 확인하는 중입니다 (1회)")
            expect(bar).to_have_attribute("aria-valuenow", "96")
            expect(dialog).to_be_hidden()
            expect(page.locator("#toast")).to_contain_text("보고서 초안을 생성했습니다.")
            expect(page.locator("#reportList a", has_text="PDF")).to_be_visible()
            assert seen["posted"]["formats"] == ["pdf"] and seen["posted"]["run_id"] == "r1"
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert errors == []
            page.close()
        finally:
            browser.close()
