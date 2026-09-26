"""Offline visual regression for the supplied emblem and compact header."""
import io
import os
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
