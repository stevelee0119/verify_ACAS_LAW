"""Offline visual regression for the supplied emblem and compact header."""
import io
import os
import pytest
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright
from PIL import Image, ImageColor


ROOT = Path(__file__).resolve().parents[1]


def test_emblem_login_and_header_at_desktop_tablet_and_mobile_sizes(tmp_path):
    static = ROOT / "apps/web/static"
    files = {f"/static/{path.relative_to(static).as_posix()}": path
             for path in static.rglob("*") if path.is_file()}
    files["/"] = ROOT / "apps/web/index.html"

    def respond(route):
        path = urlsplit(route.request.url).path
        if path in files:
            route.fulfill(path=str(files[path]))
        elif path == "/api/health":
            route.fulfill(json={"status": "ok", "version": "0.4.0"})
        else:
            route.fulfill(status=401, json={"detail": "Login required"})

    with sync_playwright() as playwright:
        options = {"headless": True}
        if os.getenv("LV_TEST_BROWSER_CHANNEL"):
            options["channel"] = os.environ["LV_TEST_BROWSER_CHANNEL"]
        browser = playwright.chromium.launch(**options)
        try:
            for width, height in ((1440, 960), (768, 1024), (390, 844), (320, 640)):
                page = browser.new_page(viewport={"width": width, "height": height})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/*", respond)
                page.goto("http://emblem.test/")
                dialog = page.get_by_role("dialog", name="작업 공간 로그인")
                expect(dialog).to_be_visible()
                expect(dialog.get_by_role("heading", name="법률문서 검증시스템", exact=True)).to_be_visible()
                expect(dialog.get_by_role("heading")).to_have_count(1)
                expect(dialog.get_by_text("ACASia_LAW", exact=True)).to_have_count(0)
                assert dialog.locator(".login-heading").evaluate("""element =>
                    element.querySelector('h2').getBoundingClientRect().top >=
                    element.querySelector('.brand-emblem').getBoundingClientRect().bottom + 12""")
                page.wait_for_function("""() => [...document.querySelectorAll('.brand-emblem img')]
                    .every(image => image.complete && image.naturalWidth === 1280)""")
                assert page.locator(".brand-emblem img").count() == 2
                assert dialog.evaluate("element => element.scrollWidth <= element.clientWidth")
                assert page.locator(".brand-emblem").evaluate_all("""elements => elements.every(element => {
                    const rect = element.getBoundingClientRect();
                    const image = element.querySelector('img').getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0 && rect.left >= 0 && rect.right <= innerWidth
                        && Math.abs(rect.width / rect.height - 1280 / 296) < .02
                        && Math.abs(image.bottom - rect.bottom) < 1;
                })""")
                page.screenshot(path=str(tmp_path / f"emblem-login-{width}.png"), full_page=True)
                page.keyboard.press("Escape")
                expect(dialog).not_to_be_visible()
                square = page.locator("#emptyState .empty-emblem")
                expect(square).to_be_visible()
                expect(page.locator("#emptyState button, #emptyCreate, .empty-title")).to_have_count(0)
                credit = page.locator(".emblem-credit")
                expect(credit).to_have_text("created by 스티브, 아나스타샤, 스텔라, 에이미, 쏘니")
                assert credit.evaluate("""el => {
                    const text = el.getBoundingClientRect(), image = el.previousElementSibling.getBoundingClientRect();
                    return Math.abs(text.width - image.width) < 1 && text.top >= image.bottom
                        && el.scrollWidth <= el.clientWidth && image.width >= 200;
                }""")
                expect(square).to_have_attribute("src", "/static/img/acas-law-square-transparent.png")
                page.wait_for_function("""() => {
                    const image = document.querySelector('#emptyState .empty-emblem');
                    return image.complete && image.naturalWidth === 1254 && image.naturalHeight === 1254;
                }""")
                assert square.evaluate("""image => {
                    const rect = image.getBoundingClientRect();
                    return Math.abs(rect.width - rect.height) < 1 && rect.width > 0
                        && rect.left >= 0 && rect.right <= innerWidth
                        && getComputedStyle(image).objectFit === 'contain';
                }""")
                background = ImageColor.getrgb(page.evaluate(
                    "getComputedStyle(document.documentElement).backgroundColor"))
                with Image.open(io.BytesIO(square.screenshot())) as rendered:
                    for point in ((1, 1), (rendered.width - 2, 1),
                                  (1, rendered.height - 2), (rendered.width - 2, rendered.height - 2)):
                        assert rendered.getpixel(point)[:3] == background
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert page.locator(".topbar").evaluate("""bar => {
                    const rects = [...bar.children].filter(element => getComputedStyle(element).display !== 'none')
                        .map(element => element.getBoundingClientRect());
                    return rects.every((rect, index) => rect.left >= 0 && rect.right <= innerWidth
                        && (!index || rect.left >= rects[index - 1].right));
                }""")
                expect(page.get_by_role("link", name="ACASia_LAW 홈")).to_be_visible()
                title = page.locator(".brand-title")
                expect(title).to_be_visible()
                page.evaluate("document.fonts.ready")
                size = float(title.evaluate("el => getComputedStyle(el).fontSize").removesuffix("px"))
                assert size == 22 if width > 700 else 13 <= size <= 22
                assert page.evaluate("document.fonts.check('600 22px \"ACAS Title\"', '종합행정학교 법무교육단 법률문서 검증시스템')")
                # 기관명(윗줄)과 시스템명(아랫줄)이 엠블럼 높이 안에 두 줄로 놓이고, 기관명은 9px 이상이다.
                expect(title.locator(".brand-org")).to_have_text("종합행정학교 법무교육단")
                expect(title.locator(".brand-name")).to_have_text("법률문서 검증시스템")
                assert title.evaluate("""el => {
                    const org = el.querySelector('.brand-org').getBoundingClientRect();
                    const name = el.querySelector('.brand-name').getBoundingClientRect();
                    return org.bottom <= name.top + 1 && parseFloat(getComputedStyle(el.querySelector('.brand-org')).fontSize) >= 9;
                }""")
                # 폭과 무관하게 제목은 엠블럼 바로 옆(같은 줄)에 있어야 한다.
                assert title.evaluate("""el => {
                    const t = el.getBoundingClientRect(), e = document.querySelector('.brand-emblem').getBoundingClientRect();
                    return t.left >= e.right && t.left - e.right <= 24 && t.top < e.bottom && t.bottom > e.top;
                }""")
                assert title.evaluate("""el => {
                    const r = el.getBoundingClientRect(), bar = el.closest('header').getBoundingClientRect();
                    return r.left >= 0 && r.right <= innerWidth && r.bottom <= bar.bottom && el.scrollWidth <= el.clientWidth;
                }""")
                page.screenshot(path=str(tmp_path / f"emblem-workspace-{width}.png"), full_page=True)
                if width <= 700:
                    page.get_by_role("button", name="프로젝트 목록", exact=True).click()
                    expect(page.locator("#sidebar")).to_be_visible()
                assert errors == []
                page.close()
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", [(1440, 960), (390, 844)])
def test_sidebar_is_the_only_project_creation_entry(tmp_path, width, height):
    projects = []
    defaults = {"name": "새 사건", "creation_key": "test-create-once", "parties": [],
                "requested_issues": [], "external_ai_policy": "LOCAL_ONLY", "verification_profile": "STANDARD"}
    def respond(route):
        path = urlsplit(route.request.url).path
        if path == "/":
            route.fulfill(path=str(ROOT / "apps/web/index.html"))
        elif path.startswith("/static/"):
            route.fulfill(path=str(ROOT / "apps/web" / path.lstrip("/")))
        elif path == "/api/health":
            route.fulfill(json={"version": "test", "status": "ok"})
        elif path == "/api/identity/me":
            route.fulfill(json={"user_id": "member", "role": "MEMBER", "authentication": "password"})
        elif path == "/api/auth/me":
            route.fulfill(json={"email": "synthetic@example.test", "affiliation": "합성 법무교육단 문서 검증 담당부서",
                                "display_name": "테스트사용자"})
        elif path == "/api/verification-runs":
            route.fulfill(json={"runs": [], "active_count": 0})
        elif path == "/api/project-defaults":
            route.fulfill(json=defaults)
        elif path == "/api/projects":
            if route.request.method == "POST":
                projects.append({**route.request.post_data_json, "id": "created", "can_delete": True,
                                 "document_count": 0, "scope_revision": 0})
                route.fulfill(status=201, json=projects[-1])
            else:
                route.fulfill(json=projects)
        elif path == "/api/projects/created":
            route.fulfill(json=projects[0])
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
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/*", respond)
            page.goto("https://workspace.test/")
            expect(page.locator(".user-proj-msg")).to_have_text("테스트사용자님의 프로젝트")
            expect(page.locator("#emptyState button")).to_have_count(0)
            expect(page.get_by_text("검토 프로젝트", exact=True)).to_have_count(0)
            page.screenshot(path=str(tmp_path / f"landing-{width}.png"), full_page=True)
            if width <= 700:
                page.get_by_role("button", name="프로젝트 목록", exact=True).click()
            create = page.get_by_role("button", name="새 프로젝트", exact=True)
            expect(create).to_have_count(1)
            expect(create).to_have_text("새프로젝트")
            assert create.evaluate("""el => {
                const button = el.getBoundingClientRect(), title = el.previousElementSibling.getBoundingClientRect();
                return button.top >= title.bottom && Math.abs(button.width - title.width) < 1 && button.width >= 200;
            }""")
            for selector, minimum in ((".user-affil", 14), (".user-proj-msg", 18)):
                assert page.locator(selector).evaluate("el => parseFloat(getComputedStyle(el).fontSize)") >= minimum
                assert page.locator(selector).evaluate("el => el.scrollWidth <= el.clientWidth")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(tmp_path / f"sidebar-{width}.png"), full_page=True)
            create.click()
            expect(page.locator("#projectDialog")).to_be_visible()
            page.locator('#projectForm [name="name"]').fill("통합 생성 경로 검증")
            page.locator("#projectSubmit").click()
            expect(page.locator("#projectTitle")).to_have_text("통합 생성 경로 검증")
            expect(page.locator("#emptyState")).to_be_hidden()
            assert len(projects) == 1 and not errors
        finally:
            browser.close()
