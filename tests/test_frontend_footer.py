"""화면 하단의 저작권 보호 문구와 개발 기여자 표시: 작게, 모든 화면 폭에서 가로 넘침 없이."""
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CONTRIBUTORS = "개발 기여: 스티브, 아나스타샤, 스텔라, 에이미, 쏘니"


@pytest.mark.parametrize("width, height", [(1440, 960), (768, 1024), (320, 640)])
def test_footer_shows_copyright_and_contributors_small(width, height):
    static = ROOT / "apps/web/static"
    files = {f"/static/{p.relative_to(static).as_posix()}": p for p in static.rglob("*") if p.is_file()}
    files["/"] = ROOT / "apps/web/index.html"

    def respond(route):
        path = urlsplit(route.request.url).path
        if path in files:
            route.fulfill(path=str(files[path]))
        elif path == "/api/health":
            route.fulfill(json={"status": "ok", "version": "0.9.8"})
        else:
            route.fulfill(status=401, json={"detail": "Login required"})

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
            page.goto("http://footer.test/")
            page.keyboard.press("Escape")
            footer = page.locator("footer.site-footer")
            footer.scroll_into_view_if_needed()
            expect(footer).to_be_visible()
            expect(footer.get_by_text("저작권법에 의해 보호")).to_be_visible()
            expect(footer.get_by_text(CONTRIBUTORS, exact=True)).to_be_visible()
            size = footer.evaluate("element => parseFloat(getComputedStyle(element).fontSize)")
            assert size <= 12
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors
        finally:
            browser.close()
