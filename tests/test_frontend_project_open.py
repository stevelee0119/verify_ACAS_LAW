"""좌측 목록에서 기존 프로젝트를 눌렀을 때의 반응.

서버가 느리면 응답이 올 때까지 화면이 그대로여서 클릭이 먹지 않는 것처럼
보였다. 누른 즉시 여는 중임을 표시하고, 세 조회를 동시에 보내며, 실패하면
이유를 알린다.
"""
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("width,height", [(1440, 960), (390, 844)])
def test_clicking_an_existing_project_gives_feedback_and_opens_it(width, height):
    static = ROOT / "apps/web/static"
    files = {f"/static/{p.relative_to(static).as_posix()}": p for p in static.rglob("*") if p.is_file()}
    files["/"] = ROOT / "apps/web/index.html"
    projects = {pid: {"id": pid, "name": name, "can_delete": True, "document_count": 1,
                      "external_ai_policy": "LOCAL_ONLY", "scope_revision": 0, "deleted_at": None}
                for pid, name in (("alpha", "첫 사건"), ("beta", "느린 사건"), ("gamma", "고장난 사건"))}
    held, errors = [], []

    def respond(route):
        path = urlsplit(route.request.url).path
        if path in files:
            return route.fulfill(path=str(files[path]))
        if path == "/api/health":
            return route.fulfill(json={"status": "ok", "version": "0.5.0"})
        if path == "/api/identity/me":
            return route.fulfill(json={"user_id": "u", "role": "ADMIN", "authentication": "password"})
        if path == "/api/verification-runs":
            return route.fulfill(json={"active_count": 0, "runs": []})
        if path == "/api/projects":
            return route.fulfill(json=list(projects.values()))
        if path.startswith("/api/projects/beta"):
            return held.append(route)  # 느린 서버: 테스트가 풀어 줄 때까지 응답하지 않는다.
        if path == "/api/projects/gamma":
            return route.fulfill(status=500, json={"detail": "저장소를 읽지 못했습니다"})
        if path.startswith("/api/projects/") and len(path.split("/")) == 4:
            return route.fulfill(json=projects[path.split("/")[-1]])
        return route.fulfill(json=[])

    def project_button(page, name):
        if width <= 700 and not page.locator("#sidebar").is_visible():
            page.get_by_role("button", name="프로젝트 목록", exact=True).click()
        return page.locator("#projectList > button", has_text=name)

    with sync_playwright() as playwright:
        options = {"headless": True}
        if os.getenv("LV_TEST_BROWSER_CHANNEL"):
            options["channel"] = os.environ["LV_TEST_BROWSER_CHANNEL"]
        browser = playwright.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/*", respond)
            page.goto("http://open.test/")
            expect(page.locator("#projectTitle")).to_have_text("첫 사건")

            slow = project_button(page, "느린 사건")
            slow.click()
            # 응답을 기다리는 동안에도 누른 프로젝트가 여는 중으로 보인다.
            expect(slow).to_have_attribute("aria-busy", "true")
            expect(slow).to_have_accessible_name(re.compile("여는 중"))
            # 프로젝트·자료·검증 이력 조회는 순서대로가 아니라 동시에 나간다.
            for _ in range(50):
                if len(held) >= 3:
                    break
                page.wait_for_timeout(50)
            assert sorted(urlsplit(r.request.url).path for r in held) == [
                "/api/projects/beta", "/api/projects/beta/documents", "/api/projects/beta/runs"]
            assert "limit=1" in next(r.request.url for r in held if r.request.url.split("?")[0].endswith("/runs"))
            for route in held:
                route.fulfill(json=projects["beta"] if route.request.url.endswith("/beta") else [])
            expect(page.locator("#projectTitle")).to_have_text("느린 사건")
            expect(page.locator("#projectList > button[aria-busy]")).to_have_count(0)

            project_button(page, "고장난 사건").click()
            expect(page.locator("#toast")).to_contain_text("프로젝트를 열지 못했습니다")
            expect(page.locator("#toast")).to_contain_text("저장소를 읽지 못했습니다")
            expect(page.locator("#projectList > button[aria-busy]")).to_have_count(0)
            expect(page.locator("#projectTitle")).to_have_text("느린 사건")

            project_button(page, "첫 사건").click()
            expect(page.locator("#projectTitle")).to_have_text("첫 사건")
            assert errors == []
            page.close()
        finally:
            browser.close()
