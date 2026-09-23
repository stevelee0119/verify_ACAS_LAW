"""배포가능 판정 사유는 누르지 않아도 보여야 한다."""
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
GATE = {"release_gate": "BLOCK", "hallucination_risk": 72,
        "hard_block_reasons": ["성립할 수 없는 사건번호 인용 1건", "은닉 텍스트 2건 발견", "Source 미확인 판례가 핵심 주장의 근거"],
        "review_reasons": ["공식 DB 미확인 인용 4건", "AI 작성 정황(일부)", "계산 결과 불일치 1건"],
        "risk_index_note": "검증위험 지수는 확률이 아니라 규칙 기반 점수입니다."}


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 1400)])
def test_gate_reasons_are_shown_open_and_readable(width, height):
    static = ROOT / "apps/web/static"
    files = {f"/static/{p.relative_to(static).as_posix()}": p for p in static.rglob("*") if p.is_file()}
    files["/"] = ROOT / "apps/web/index.html"
    run = {"id": "r1", "project_id": "p1", "state": "COMPLETED", "progress": 1, "stage_message": "",
           "document_ids": ["d"], "scores": {"release_gate": GATE}, "unverified_items": [],
           "input_snapshot": {"scope_revision": 0}, "started_at": "2026-09-23T00:00:00"}
    project = {"id": "p1", "name": "시험 사건", "can_delete": True, "document_count": 1,
               "external_ai_policy": "MASKED", "scope_revision": 0}

    def respond(route):
        path = urlsplit(route.request.url).path
        if path in files:
            return route.fulfill(path=str(files[path]))
        replies = {"/api/health": {"status": "ok", "version": "0.5.0"},
                   "/api/identity/me": {"user_id": "u", "role": "ADMIN", "authentication": "password"},
                   "/api/verification-runs": {"active_count": 0, "runs": []},
                   "/api/projects": [project], "/api/projects/p1": project, "/api/projects/p1/runs": [run]}
        if path in replies:
            return route.fulfill(json=replies[path])
        if path.endswith("/result"):
            return route.fulfill(json={"documents": []})
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
            page.route("**/*", respond)
            page.goto("http://gate.test/")
            reasons = page.get_by_role("region", name="배포가능 판정 사유")
            expect(reasons).to_contain_text("배포 차단 — 사유 6건")
            assert page.locator("#summary details").count() == 0, "접힌 상자에 숨기지 않는다"
            # 누르지 않은 상태에서 여섯 사유가 모두 화면에 있다.
            for reason in GATE["hard_block_reasons"][:2] + GATE["review_reasons"]:
                expect(reasons.get_by_text(reason, exact=True)).to_be_visible()
            expect(reasons.get_by_text("출처 미확인 판례가 핵심 주장의 근거")).to_be_visible()
            expect(reasons.locator(".gate-group-block h3")).to_have_text("배포 차단 사유 3건")
            expect(reasons.locator(".gate-group-review h3")).to_have_text("사람 검토 사유 3건")
            size = reasons.locator("li").first.evaluate("el => parseFloat(getComputedStyle(el).fontSize)")
            assert size >= 16
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.close()
        finally:
            browser.close()
