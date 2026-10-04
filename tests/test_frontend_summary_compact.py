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
def test_summary_metrics_are_compact(width, height, max_cell, tmp_path):
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
            return route.fulfill(json={"documents": [{"document_id": "d1", "filename": "준비서면.pdf",
                "engine_data": {"related_authorities": {"status": "SOURCE_REVIEW_ONLY", "note": "직접 인용과 별도 검토",
                    "candidates": [{"citation_id": "related1", "raw_text": "민법 제492조"}], "verdicts": []},
                    "rag": {"status": "RETRIEVED_ONLY", "observation_limit_reached": True,
                        "contract_review": {"calculations": [{"outputs": {"delay_days": "12", "daily_penalty": "60000", "penalty": "720000"},
                            "stated_days_match": True, "note": "자료상 날짜의 조건부 검산. 적법성 확정 아님."}]}}}}],
                "run_manifest": {"reference_library": {"status": "READY"}}})
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
            metrics_locator = page.locator("#summary .metric")
            expect(metrics_locator).to_have_count(8)
            sizes = metrics_locator.evaluate_all("""cells => cells.map(cell => {
                const strong = cell.querySelector('strong');
                const span = cell.querySelector('span');
                return {
                    value: strong ? (parseFloat(getComputedStyle(strong).fontSize) || 0) : 0,
                    title: span ? (parseFloat(getComputedStyle(span).fontSize) || 0) : 0,
                    height: cell.getBoundingClientRect().height
                };
            })""")
            assert len(sizes) == 8
            assert all(0 < s["value"] <= 18.5 and 0 < s["title"] <= 12.5 for s in sizes), sizes
            assert all(s["height"] <= max_cell for s in sizes), [round(s["height"]) for s in sizes]
            for title in ("배포가능 상태", "검증위험 지수", "AI 작성 진단"):
                expect(page.locator(".metric", has_text=title)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.evaluate("switchTab('review')")
            page.get_by_text("준비서면.pdf: 추가 관련 법조문 검토", exact=True).click()
            page.get_by_text("준비서면.pdf: 검색 완료 · AI 대조 미실행", exact=True).click()
            expect(page.get_by_text("민법 제492조", exact=False)).to_contain_text("별도 검토 필요")
            expect(page.get_by_text("12일 × 60000원 = 720000원", exact=True)).to_be_visible()
            expect(page.get_by_text("의견 5건 한도 도달 · 전체 주장 검토 완료 아님", exact=True)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(tmp_path / f"evidence-review-{width}.png"), full_page=True)
        finally:
            browser.close()
