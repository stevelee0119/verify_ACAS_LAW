"""같은 인용에서 파생된 확인 항목은 한 줄로 묶고, 하위 근거를 펼쳐 볼 수 있다."""
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def finding(fid, ftype, title, citation_id=None, severity="HIGH"):
    return {"id": fid, "run_id": "r1", "project_id": "p1", "document_id": "d1", "type": ftype,
            "status": "NOT_FOUND", "severity": severity, "evidence_grade": "B", "confidence": 0.5, "page": 1,
            "block_id": None, "title": title, "detail": "", "engine": "legal_engine", "meta_message_type": None,
            "advisory_only": False, "tags": [], "review_status": "NEEDS_REVIEW", "review_note": "",
            "has_sealed_content": False, "evidence": [], "sources": [], "citation_id": citation_id}


def test_findings_from_one_citation_are_grouped(tmp_path):
    static = ROOT / "apps/web/static"
    files = {f"/static/{p.relative_to(static).as_posix()}": p for p in static.rglob("*") if p.is_file()}
    files["/"] = ROOT / "apps/web/index.html"
    run = {"id": "r1", "project_id": "p1", "state": "COMPLETED", "progress": 1, "stage_message": "",
           "document_ids": ["d1"], "scores": {}, "unverified_items": [], "errors": [], "unavailable_sources": [],
           "input_snapshot": {"scope_revision": 0}, "started_at": "2026-09-24T00:00:00"}
    project = {"id": "p1", "name": "시험 사건", "can_delete": True, "document_count": 1,
               "external_ai_policy": "MASKED", "scope_revision": 0}
    findings = [finding("f1", "CASE_NOT_FOUND", "조회 범위 내에서 찾지 못한 판례 인용: 대법원 2019다1 판결", "c1"),
                finding("f2", "LEGAL_ARGUMENT_INVALID", "공식 DB에서 확인되지 않은 판례에 기댄 주장", "c1"),
                finding("f3", "LAW_CITATION_ERROR", "다른 인용의 항목", "c2", "MEDIUM")]

    def respond(route):
        path = urlsplit(route.request.url).path
        if path in files:
            return route.fulfill(path=str(files[path]))
        replies = {"/api/health": {"status": "ok", "version": "0.5.0"},
                   "/api/identity/me": {"user_id": "u", "role": "ADMIN", "authentication": "password"},
                   "/api/verification-runs": {"active_count": 0, "runs": []},
                   "/api/projects": [project], "/api/projects/p1": project, "/api/projects/p1/runs": [run],
                   "/api/projects/p1/findings": findings}
        if path in replies:
            return route.fulfill(json=replies[path])
        if path.endswith("/result"):
            return route.fulfill(json={"run_manifest": {"reference_library": {
                "status": "PARTIAL", "files_seen": 2, "files_indexed": 1, "checked_at": "2026-09-26T01:00:00Z",
                "issues": [{"name": "scanned.pdf", "reason": "REFERENCE_PARTIALLY_READ"}]}},
                "documents": [{"document_id": "d1", "filename": "준비서면.pdf", "engine_data": {"rag": {
                    "status": "RETRIEVED_ONLY", "reason": "MODEL_UNAVAILABLE", "sources": [{
                        "source_id": "R1", "file_id": "reference000001", "title": "<img onerror=alert(1)> " + "참고자료" * 20,
                        "page": 2, "modified_time": "2026-09-26", "sha256": "a" * 64,
                        "text": "Drive reference text"}]}}}]})
        if path.endswith("/case-matrix"):
            return route.fulfill(body="null", content_type="application/json")
        return route.fulfill(json=[])

    with sync_playwright() as playwright:
        options = {"headless": True}
        if os.getenv("LV_TEST_BROWSER_CHANNEL"):
            options["channel"] = os.environ["LV_TEST_BROWSER_CHANNEL"]
        browser = playwright.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.route("**/*", respond)
            page.goto("http://groups.test/")
            page.locator("[data-tab='review']").click()
            rows = page.locator("#findings > article.row-item")
            expect(rows).to_have_count(2)
            grouped = rows.filter(has_text="대법원 2019다1")
            expect(grouped.locator(".derived-findings summary")).to_have_text("같은 인용에서 파생된 항목 1건")
            grouped.locator(".derived-findings summary").click()
            expect(grouped.locator(".derived-findings")).to_contain_text("공식 DB에서 확인되지 않은 판례에 기댄 주장")
            expect(rows.filter(has_text="다른 인용의 항목").locator(".derived-findings")).to_have_count(0)
            page.locator("[data-tab='ai-verification']").click()
            references = page.locator(".reference-section")
            expect(references).to_contain_text("일부 자료 미처리")
            expect(references.locator("img")).to_have_count(0)
            references.locator("summary").last.click()
            expect(references.locator("a")).to_have_attribute("href", "https://drive.google.com/file/d/reference000001/view")
            for width in (1280, 390):
                page.set_viewport_size({"width": width, "height": 900})
                references.scroll_into_view_if_needed()
                assert references.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
                references.screenshot(path=str(tmp_path / f"references-{width}.png"))
            assert errors == []
        finally:
            browser.close()
