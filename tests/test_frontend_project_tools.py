"""Background wake-up and reversible project deletion through the real browser UI."""
import os
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("width,height", [(1440, 960), (390, 844)])
def test_background_wake_and_project_trash(tmp_path, width, height):
    static = ROOT / "apps/web/static"
    files = {f"/static/{p.relative_to(static).as_posix()}": p for p in static.rglob("*") if p.is_file()}
    files["/"] = ROOT / "apps/web/index.html"
    projects = {pid: {"id": pid, "name": name, "can_delete": True, "document_count": 0,
                      "external_ai_policy": "LOCAL_ONLY", "scope_revision": 0, "deleted_at": None}
                for pid, name in (("alpha", "Background case"), ("beta", "Second case"))}
    run = {"id": "run-alpha", "project_id": "alpha", "project_name": "Background case", "state": "VERIFYING",
           "progress": .57, "stage_message": "Checking references", "document_ids": [], "unverified_items": [],
           "input_snapshot": {"scope_revision": 0}, "started_at": "2026-09-22T00:00:00"}
    requests, errors = [], []

    def respond(route):
        url = urlsplit(route.request.url)
        path, method = url.path, route.request.method
        requests.append((method, path))
        if path in files:
            route.fulfill(path=str(files[path]))
        elif path == "/api/health":
            route.fulfill(json={"status": "ok", "version": "0.5.0"})
        elif path == "/api/identity/me":
            route.fulfill(json={"user_id": "admin", "role": "ADMIN", "authentication": "password"})
        elif path == "/api/verification-runs":
            rows = [] if projects["alpha"]["deleted_at"] else [run]
            route.fulfill(json={"active_count": sum(r["state"] == "VERIFYING" for r in rows), "runs": rows})
        elif path == "/api/verification-runs/run-alpha":
            route.fulfill(json=run)
        elif path.endswith("/result"):
            route.fulfill(json={"documents": [], "test_marker": "persisted-server-result"})
        elif path == "/api/projects":
            deleted = parse_qs(url.query).get("deleted") == ["true"]
            route.fulfill(json=[p for p in projects.values() if bool(p["deleted_at"]) == deleted])
        elif path.startswith("/api/projects/") and len(path.split("/")) == 4:
            project = projects[path.split("/")[-1]]
            if method == "DELETE":
                project["deleted_at"] = "2026-09-22T00:00:00"
                route.fulfill(status=204)
            else:
                route.fulfill(json=project)
        elif path.endswith("/restore"):
            project = projects[path.split("/")[-2]]
            project["deleted_at"] = None
            route.fulfill(json=project)
        elif path.endswith("/runs"):
            route.fulfill(json=[run] if "/alpha/" in path else [])
        elif path.endswith("/case-matrix"):
            route.fulfill(body="null", content_type="application/json")
        else:
            route.fulfill(json=[])

    with sync_playwright() as playwright:
        options = {"headless": True}
        if os.getenv("LV_TEST_BROWSER_CHANNEL"):
            options["channel"] = os.environ["LV_TEST_BROWSER_CHANNEL"]
        browser = playwright.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/*", respond)
            page.goto("http://workspace.test/")
            expect(page.locator("#projectTitle")).to_have_text("Background case")
            expect(page.locator("#deleteProject")).to_be_disabled()
            expect(page.locator("#backgroundJobsButton")).to_contain_text("1")
            page.evaluate("openProject('beta')")
            expect(page.locator("#projectTitle")).to_have_text("Second case")
            # Simulate browser lifecycle suspension without making server progress depend on a timer.
            page.evaluate("""() => {
                window.simulatedHidden = true;
                Object.defineProperty(document, 'hidden', {configurable:true, get:() => window.simulatedHidden});
                document.dispatchEvent(new Event('visibilitychange'));
                window.dispatchEvent(new Event('pagehide'));
            }""")
            run.update(state="COMPLETED", progress=1, stage_message="Completed")
            page.evaluate("""() => {
                window.simulatedHidden = false;
                document.dispatchEvent(new Event('visibilitychange'));
                for (const event of ['pageshow', 'online', 'focus']) window.dispatchEvent(new Event(event));
            }""")
            expect(page.locator("#backgroundJobsButton")).to_contain_text("0", timeout=5000)
            if width <= 700:
                page.get_by_role("button", name="프로젝트 목록", exact=True).click()
            page.locator("#backgroundJobsButton").click()
            jobs = page.get_by_role("dialog", name="검증 작업", exact=True)
            expect(jobs).to_contain_text("Background case")
            jobs.get_by_role("button", name="Background case", exact=True).click()
            page.wait_for_function("state.result.test_marker === 'persisted-server-result'")
            expect(page.locator("#deleteProject")).to_be_enabled()
            page.screenshot(path=str(tmp_path / f"workspace-{width}.png"), full_page=True)
            page.locator("#deleteProject").click()
            confirmation = page.get_by_role("dialog", name="프로젝트 삭제", exact=True)
            expect(confirmation).to_contain_text("보존")
            confirmation.get_by_role("button", name="취소", exact=True).click()
            assert not [p for m, p in requests if m == "DELETE"]
            page.locator("#deleteProject").click()
            confirmation.get_by_role("button", name="확인", exact=True).click()
            expect(page.locator("#projectTitle")).to_have_text("Second case")
            page.locator("#deleteProject").click()
            confirmation.get_by_role("button", name="확인", exact=True).click()
            expect(page.locator("#emptyState")).to_be_visible()
            assert page.evaluate("localStorage.getItem('acas-project')") is None
            if width <= 700:
                page.get_by_role("button", name="프로젝트 목록", exact=True).click()
            page.locator("#projectTrashButton").click()
            trash = page.get_by_role("dialog", name="프로젝트 휴지통", exact=True)
            expect(trash.locator(".project-trash-item")).to_have_count(2)
            assert trash.evaluate("el => el.scrollWidth <= el.clientWidth")
            page.screenshot(path=str(tmp_path / f"trash-{width}.png"), full_page=True)
            trash.locator(".project-trash-item").filter(has_text="Background case").get_by_role("button", name="복원").click()
            expect(trash.locator(".project-trash-item")).to_have_count(1)
            trash.get_by_role("button", name="닫기", exact=True).click()
            expect(page.locator("#projectTitle")).to_have_text("Background case")
            page.evaluate("state.project.can_delete = false; projectTools.renderControls()")
            expect(page.locator("#deleteProject")).to_be_hidden()
            assert [(m, p) for m, p in requests if m in {"POST", "DELETE"}] == [
                ("DELETE", "/api/projects/alpha"), ("DELETE", "/api/projects/beta"), ("POST", "/api/projects/alpha/restore")]
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors
        finally:
            browser.close()
