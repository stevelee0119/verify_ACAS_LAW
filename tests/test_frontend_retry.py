"""A queued retry starts status polling without waiting for a result that does not exist yet."""
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("width,height", [(1440, 960), (390, 844)])
def test_retry_button_tracks_the_new_run_until_completion(tmp_path, width, height):
    static = ROOT / "apps/web/static"
    files = {f"/static/{p.relative_to(static).as_posix()}": p for p in static.rglob("*") if p.is_file()}
    files["/"] = ROOT / "apps/web/index.html"
    project = {"id": "p1", "name": "재시도 검증", "can_delete": True, "document_count": 1,
               "external_ai_policy": "LOCAL_ONLY", "scope_revision": 0}
    failed = {"id": "old", "project_id": "p1", "state": "FAILED", "progress": 0, "stage_message": "실행 실패",
              "document_ids": ["d1"], "scores": {}, "errors": [], "unverified_items": [],
              "input_snapshot": {"scope_revision": 0}, "started_at": "2026-09-27T00:00:00"}
    child = {**failed, "id": "new", "state": "QUEUED", "stage_message": "재분석 대기"}
    posts, early_results, errors, polls = [], [], [], []

    def respond(route):
        path = urlsplit(route.request.url).path
        if path in files:
            return route.fulfill(path=str(files[path]))
        replies = {"/api/health": {"status": "ok", "version": "0.9.12"},
                   "/api/identity/me": {"user_id": "u", "role": "ADMIN", "authentication": "password"},
                   "/api/projects": [project], "/api/projects/p1": project, "/api/projects/p1/runs": [failed],
                   "/api/verification-runs": {"active_count": 0, "runs": []}}
        if path in replies:
            return route.fulfill(json=replies[path])
        if path == "/api/verification-runs/old/retry":
            posts.append(path)
            return route.fulfill(status=202, json=child)
        if path == "/api/verification-runs/new":
            polls.append(path)
            child.update(state="VERIFYING" if len(polls) == 1 else "COMPLETED",
                         stage_message="재분석 중" if len(polls) == 1 else "완료", progress=0.5 if len(polls) == 1 else 1)
            return route.fulfill(json=child)
        if path.endswith("/result"):
            if "/new/" in path and child["state"] != "COMPLETED":
                early_results.append(path)
                return route.fulfill(status=503, json={"detail": "아직 생성되지 않은 결과"})
            return route.fulfill(json={"documents": []})
        if path.endswith("/session"):
            return route.fulfill(json={"protected": True})
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
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/*", respond)
            page.goto("http://retry.test/")
            page.get_by_role("button", name="같은 입력으로 재시도", exact=True).click()
            dialog = page.get_by_role("dialog", name="검증 재시도", exact=True)
            expect(dialog).to_contain_text("현재 분석 엔진")
            dialog.get_by_role("button", name="확인", exact=True).click()
            page.wait_for_function("state.run?.id === 'new' && state.run.state === 'COMPLETED'", timeout=15000)
            assert posts == ["/api/verification-runs/old/retry"]
            assert len(polls) >= 2 and early_results == []
            expect(page.get_by_role("button", name="같은 입력으로 재시도", exact=True)).to_have_count(0)
            assert errors == []
            page.screenshot(path=str(tmp_path / f"retry-complete-{width}.png"), full_page=True)
        finally:
            browser.close()
