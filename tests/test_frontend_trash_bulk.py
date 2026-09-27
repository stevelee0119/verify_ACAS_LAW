"""Bulk purge uses the confirmed snapshot and reports partial/ambiguous results."""
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def trash_page():
    projects = {name: {"id": name, "name": name, "document_count": 1,
                       "deleted_at": "2026-09-27T00:00:00", "can_delete": True}
                for name in ("Alpha", "Beta", "Charlie")}
    control = {"projects": projects, "calls": [], "deferred": [], "failure": None, "hold": True, "list_failure": False}
    def respond(route):
        path = urlsplit(route.request.url).path
        if path == "/":
            route.fulfill(path=str(ROOT / "apps/web/index.html"))
        elif path.startswith("/static/"):
            route.fulfill(path=str(ROOT / "apps/web" / path.lstrip("/")))
        elif path == "/api/health":
            route.fulfill(json={"version": "test", "status": "ok"})
        elif path == "/api/identity/me":
            route.fulfill(json={"user_id": "owner", "role": "MEMBER", "authentication": "password"})
        elif path == "/api/projects":
            if "deleted=true" in route.request.url and control["list_failure"]:
                route.fulfill(status=503, json={"detail": "Unavailable"})
            else:
                route.fulfill(json=list(projects.values()) if "deleted=true" in route.request.url else [])
        elif path == "/api/verification-runs":
            route.fulfill(json={"runs": [], "active_count": 0})
        elif path.endswith("/purge"):
            name = path.split("/")[-2]
            control["calls"].append(name)
            if control["failure"] == "network":
                route.abort("failed")
            elif control["failure"] == "auth":
                route.fulfill(status=401, json={"detail": "Session expired"})
            elif control["hold"] and name == "Alpha":
                control["deferred"].append(route)
            elif name == "Beta" and control["calls"].count(name) == 1:
                route.fulfill(status=409, json={"detail": "보고서를 만드는 중입니다."})
            else:
                projects.pop(name)
                route.fulfill(json={"purged": True, "file_errors": ["retained-blob"] if name == "Charlie" else []})
        else:
            route.fulfill(json=[])
    with sync_playwright() as playwright:
        options = {"headless": True}
        if os.getenv("LV_TEST_BROWSER_CHANNEL"):
            options["channel"] = os.environ["LV_TEST_BROWSER_CHANNEL"]
        browser = playwright.chromium.launch(**options)
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", respond)
        try:
            yield page, control
            assert not errors
        finally:
            browser.close()


def open_trash(page, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.goto("https://trash.test/")
    if width <= 700:
        page.get_by_role("button", name="프로젝트 목록", exact=True).click()
    page.locator("#projectTrashButton").click()
    dialog = page.get_by_role("dialog", name="프로젝트 휴지통", exact=True)
    expect(dialog.locator(".project-trash-item")).to_have_count(3)
    return dialog


@pytest.mark.parametrize("width,height", [(1440, 960), (390, 844)])
def test_bulk_purge_confirmation_snapshot_partial_failure_and_retry(trash_page, tmp_path, width, height):
    page, control = trash_page
    trash = open_trash(page, width, height)
    clear = trash.get_by_role("button", name="휴지통 비우기", exact=True)
    clear.click()
    confirmation = page.get_by_role("dialog", name="휴지통 비우기", exact=True)
    expect(confirmation).to_contain_text("프로젝트 3개")
    expect(confirmation).to_contain_text("되돌릴 수 없습니다")
    confirmation.get_by_role("button", name="취소", exact=True).click()
    expect(clear).to_be_enabled()
    assert not control["calls"]
    clear.click()
    confirmation.get_by_role("button", name="확인", exact=True).click()
    expect(trash.locator(".project-trash-status")).to_contain_text("1 / 3")
    expect(clear).to_be_disabled()
    expect(trash.locator(".dialog-footer").get_by_role("button", name="닫기", exact=True)).to_be_disabled()
    page.keyboard.press("Escape")
    expect(trash).to_be_visible()
    assert control["calls"] == ["Alpha"]
    control["projects"]["Later"] = {**control["projects"]["Alpha"], "id": "Later", "name": "Later"}
    control["projects"].pop("Alpha")
    control["deferred"].pop().fulfill(json={"purged": True, "file_errors": []})
    expect(trash.locator(".project-trash-status")).to_have_text("영구 삭제 2개 · 실패 또는 확인 필요 1개")
    expect(trash.locator(".project-trash-item")).to_have_count(2)
    expect(trash.locator(".project-trash-item").filter(has_text="Beta").get_by_role("alert")).to_contain_text("보고서를 만드는 중")
    expect(trash.locator(".project-trash-results")).to_contain_text("Charlie: 일부 파일을 지우지 못했습니다")
    assert control["calls"] == ["Alpha", "Beta", "Charlie"]
    assert trash.evaluate("el => el.scrollWidth <= el.clientWidth")
    page.screenshot(path=str(tmp_path / f"bulk-trash-{width}.png"), full_page=True)
    clear.click()
    expect(confirmation).to_contain_text("프로젝트 2개")
    confirmation.get_by_role("button", name="확인", exact=True).click()
    expect(trash.locator(".project-trash-status")).to_have_text("영구 삭제 2개 · 실패 또는 확인 필요 0개")
    expect(trash.locator(".project-trash-item")).to_have_count(0)
    expect(clear).to_be_disabled()
    expect(trash).to_contain_text("삭제된 프로젝트가 없습니다")
    assert control["calls"] == ["Alpha", "Beta", "Charlie", "Beta", "Later"]
    trash.locator(".dialog-footer").get_by_role("button", name="닫기", exact=True).click()
    expect(trash).not_to_be_visible()


@pytest.mark.parametrize("failure", ["auth", "network"])
def test_bulk_purge_stops_on_lost_auth_or_unconfirmed_request(trash_page, failure):
    page, control = trash_page
    control["failure"] = failure
    trash = open_trash(page, 390, 844)
    trash.get_by_role("button", name="휴지통 비우기", exact=True).click()
    page.get_by_role("dialog", name="휴지통 비우기", exact=True).get_by_role("button", name="확인", exact=True).click()
    expect(trash.locator(".project-trash-status")).to_contain_text("미시도 2개")
    expect(trash.locator(".project-trash-item")).to_have_count(3)
    expect(page.get_by_role("dialog", name="작업 공간 로그인", exact=True)).to_have_count(0)
    assert control["calls"] == ["Alpha"]


def test_failed_trash_refresh_disables_stale_actions_until_retry(trash_page):
    page, control = trash_page
    trash = open_trash(page, 1440, 960)
    control["hold"] = False
    control["list_failure"] = True
    trash.get_by_role("button", name="휴지통 비우기", exact=True).click()
    page.get_by_role("dialog", name="휴지통 비우기", exact=True).get_by_role("button", name="확인", exact=True).click()
    expect(trash.get_by_text("목록 확인 필요", exact=True)).to_be_visible()
    expect(trash.get_by_role("button", name="휴지통 비우기", exact=True)).to_be_disabled()
    for action in trash.locator(".project-trash-actions button").all():
        expect(action).to_be_disabled()
    control["list_failure"] = False
    trash.get_by_role("button", name="다시 조회", exact=True).click()
    expect(trash.locator(".project-trash-item")).to_have_count(1)
    expect(trash.get_by_role("button", name="휴지통 비우기", exact=True)).to_be_enabled()
    expect(trash.get_by_role("button", name="복원", exact=True)).to_be_enabled()
