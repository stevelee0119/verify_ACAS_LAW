"""Run against an isolated local server with Playwright and save UI evidence."""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from helpers import make_pdf


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
    output = ROOT / "artifacts" / "ui"
    output.mkdir(parents=True, exist_ok=True)
    pdf = make_pdf(output / "sample.pdf", [
        "가상 검토 자료: 원고는 2024. 1. 15. 계약을 체결하였다.",
        "치료비 1,000,000원, 위자료 3,000,000원, 합계 5,000,000원이다.",
        "대법원 2099. 1. 15. 선고 2099도99999 판결을 인용하였다.",
    ])
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base)
        page.locator("#newProjectBtn").click()
        expect(page.locator("#projectForm input[name=name]")).not_to_have_value("")
        page.locator("#projectSubmit").click()
        expect(page.locator("#projectView")).to_be_visible(timeout=20000)
        page.locator("#fileInput").set_input_files(str(pdf))
        expect(page.locator("#documentRows tr")).to_have_count(1, timeout=20000)
        page.locator("#documentRows button[title='자료 정보 편집']").click()
        page.locator("#documentForm input[name=evidence_number]").fill("갑 제1호증")
        page.locator("#documentForm button[type=submit]").click()
        expect(page.locator("#documentRows")).to_contain_text("갑 제1호증")
        page.locator("#documentRows button[title='검토에서 제외']").click()
        page.locator("#confirmationDialog textarea").fill("검토 범위 테스트")
        page.locator("#confirmationDialog button[type=submit]").click()
        expect(page.locator("#scopeCount")).to_contain_text("1개 제외")
        expect(page.locator("#verifyBtn")).to_be_disabled()
        page.reload()
        expect(page.locator("#scopeCount")).to_contain_text("1개 제외")
        page.locator("#documentRows button[title='검토에 다시 포함']").click()
        expect(page.locator("#verifyBtn")).to_be_enabled()
        page.locator("#verifyBtn").click()
        expect(page.locator("#summary")).to_contain_text("일부 미확인", timeout=120000)
        page.screenshot(path=str(output / "desktop-documents.png"), full_page=True)
        page.locator("[data-tab=review]").click()
        expect(page.locator("#findings .row-item").first).to_be_visible()
        page.locator("#findings .row-title").first.click()
        expect(page.locator("#pageArea img")).to_be_visible(timeout=30000)
        page.wait_for_function("document.querySelector('#pageArea img')?.naturalWidth > 0")
        page.screenshot(path=str(output / "desktop-evidence.png"), full_page=True)
        page.locator("#detailContent textarea").fill("가상 자료의 계산 차액 확인")
        page.locator("#detailContent select").select_option("ACCEPTED")
        page.get_by_role("button", name="판단 저장").click()
        page.locator("#detailDialog [data-close]").click()
        page.locator("[data-tab=reports]").click()
        page.locator("#createReport").click()
        expect(page.locator("#reportList a")).to_have_count(5, timeout=30000)
        assert "생성 실패" not in page.locator("#reportList").inner_text()
        page.locator("[data-tab=documents]").click()
        page.locator("#documentRows button[title='검토에서 제외']").click()
        page.locator("#confirmationDialog button[type=submit]").click()
        expect(page.locator("#staleNotice")).to_be_visible()
        for width in (390, 768, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            page.screenshot(path=str(output / f"workspace-{width}.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"overflow: {width}"
        page.set_viewport_size({"width":390,"height":844})
        page.locator("#editProject").click()
        page.screenshot(path=str(output / "mobile-project.png"), full_page=True)
        assert not errors, errors
        browser.close()
        print(json.dumps({"status":"passed","screenshots":str(output),"javascript_errors":errors},ensure_ascii=False))


if __name__ == "__main__":
    main()
