"""요약표(검토에 포함·배포가능 상태·검증위험 지수·AI 작성 진단 …)는 작은 글씨·좁은 여백으로 낮게 보인다(0.9.9).
배포가능 판정 사유 목록은 종전처럼 크게 읽힌다(test_frontend_gate)."""
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright
from frontend_helpers import select_first_project

from test_frontend_metric_explain import FINDINGS, UNVERIFIED

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("width,height,max_cell", [(1440, 1000, 80), (768, 1024, 80), (390, 1200, 80)])  # 종전 97~117px
def test_summary_metrics_are_compact(width, height, max_cell):
    static = ROOT / "apps/web/static"
    files = {f"/static/{p.relative_to(static).as_posix()}": p for p in static.rglob("*") if p.is_file()}
    files["/"] = ROOT / "apps/web/index.html"
    gate = {"release_gate": "BLOCK", "hallucination_risk": 72, "hard_block_reasons": ["판례 인용 확인 불가"]}
    run = {"id": "r1", "project_id": "p1", "state": "COMPLETED", "progress": 1, "stage_message": "",
           "document_ids": ["d1"], "scores": {"release_gate": gate}, "unverified_items": UNVERIFIED, "errors": [],
           "unavailable_sources": [], "input_snapshot": {"scope_revision": 0}, "started_at": "2026-09-24T00:00:00"}
    project = {"id": "p1", "name": "시험 사건", "can_delete": True, "document_count": 1,
               "external_ai_policy": "MASKED", "scope_revision": 0}

    def respond(route):
        path = urlsplit(route.request.url).path
        if path in files:
            return route.fulfill(path=str(files[path]))
        replies = {"/api/health": {"status": "ok", "version": "0.9.9"},
                   "/api/identity/me": {"user_id": "u", "role": "ADMIN", "authentication": "password"},
                   "/api/verification-runs": {"active_count": 0, "runs": []},
                   "/api/projects": [project], "/api/projects/p1": project, "/api/projects/p1/runs": [run],
                   "/api/projects/p1/findings": FINDINGS}
        if path in replies:
            return route.fulfill(json=replies[path])
        if path.endswith("/result"):
            return route.fulfill(json={"documents": [{"document_id": "d1", "filename": "준비서면.pdf"}]})
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
            page.goto("http://summary.test/")
            select_first_project(page)
            first = page.locator(".metric", has_text="검토에 포함")
            expect(first).to_be_visible()
            sizes = page.locator(".metric").evaluate_all("""cells => cells.map(cell => ({
                value: parseFloat(getComputedStyle(cell.querySelector('strong')).fontSize),
                title: parseFloat(getComputedStyle(cell.querySelector('span')).fontSize),
                height: cell.getBoundingClientRect().height}))""")
            assert len(sizes) == 8
            assert all(round(s["value"]) <= 18 and round(s["title"]) <= 12 for s in sizes), sizes
            assert all(s["height"] <= max_cell for s in sizes), [round(s["height"]) for s in sizes]
            for title in ("배포가능 상태", "검증위험 지수", "AI 작성 진단"):
                expect(page.locator(".metric", has_text=title)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        finally:
            browser.close()
