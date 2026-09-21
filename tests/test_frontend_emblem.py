"""Offline visual regression for the supplied emblem and compact header."""
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


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
                expect(dialog.get_by_role("heading", name="ACASia_LAW")).to_be_visible()
                page.wait_for_function("""() => [...document.querySelectorAll('.brand-emblem img')]
                    .every(image => image.complete && image.naturalWidth === 1280)""")
                assert page.locator(".brand-emblem img").count() == 3
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
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert page.locator(".topbar").evaluate("""bar => {
                    const rects = [...bar.children].filter(element => getComputedStyle(element).display !== 'none')
                        .map(element => element.getBoundingClientRect());
                    return rects.every((rect, index) => rect.left >= 0 && rect.right <= innerWidth
                        && (!index || rect.left >= rects[index - 1].right));
                }""")
                expect(page.get_by_role("link", name="ACASia_LAW 홈")).to_be_visible()
                if width <= 700:
                    page.get_by_role("button", name="프로젝트 목록", exact=True).click()
                    expect(page.locator("#sidebar")).to_be_visible()
                page.screenshot(path=str(tmp_path / f"emblem-workspace-{width}.png"), full_page=True)
                assert errors == []
                page.close()
        finally:
            browser.close()
