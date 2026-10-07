"""TK-61 화면 배치(P3) 회귀 검증 브라우저 시험

검증 대상:
1. '확인할 항목' 표(#reviewTable)에 table-layout: fixed 및 판정 배지 줄바꿈이 적용되어,
   긴 판정 문구가 포함되어도 4개 열 너비 비율이 머리글 비율(10%, 25%, 25%, 40%)의 ±5%p 이내로 유지되는가?
2. AI 작성·보안 진단 탭의 세 카드(AI 진단, 인젝션 검증, 보안) 세부 항목(.security-finding-item)이
   기존 가로 flex에서 세로 block(버튼 상단, 설명 하단)으로 배치되어 정렬이 일관되는가?
"""
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright
from frontend_helpers import select_first_project

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tk61_browser_page():
    launch_kwargs = {"headless": True}
    channel = os.environ.get("LV_TEST_BROWSER_CHANNEL")
    if channel:
        launch_kwargs["channel"] = channel

    project_data = {
        "id": "p1",
        "name": "TK-61 레이아웃 검증 프로젝트",
        "can_delete": True,
        "document_count": 1,
        "external_ai_policy": "MASKED",
        "scope_revision": 0,
        "requested_issues": ["손해배상 책임", "위약벌 적법성"],
    }

    run_data = {
        "id": "r1",
        "project_id": "p1",
        "state": "COMPLETED",
        "progress": 1,
        "stage_message": "",
        "document_ids": ["d1"],
        "scores": {},
        "unverified_items": [],
        "errors": [],
        "unavailable_sources": [],
        "input_snapshot": {"scope_revision": 0},
        "started_at": "2026-09-24T00:00:00",
    }

    # 긴 판정 문구를 가진 행위시법 finding 및 AI·보안 finding 구성
    synthetic_findings = [
        {
            "id": "f_temporal_long",
            "finding_type": "RETROACTIVE_APPLICATION_ERROR",
            "type": "RETROACTIVE_APPLICATION_ERROR",
            "severity": "HIGH",
            "title": "증액·개정 규정 소급 적용 오류 — 시행일 이전 행위에 개정 법률 적용",
            "detail": "행위 당시 법률 조항과 개정 시행 법률 조항의 불일치",
            "engine": "legal",
            "page": 1,
            "review_status": "NEEDS_REVIEW",
        },
        {
            "id": "f_ai_style",
            "finding_type": "STYLE_SHIFT",
            "type": "STYLE_SHIFT",
            "severity": "MEDIUM",
            "title": "문체 급변 감지 구간",
            "detail": "2쪽 3문단에서 AI 작성 의심 문체 급변 관찰",
            "engine": "ai",
            "page": 2,
            "review_status": "NEEDS_REVIEW",
        },
        {
            "id": "f_sec_info",
            "finding_type": "PROMPT_INJECTION",
            "type": "PROMPT_INJECTION",
            "severity": "HIGH",
            "title": "생성 소프트웨어 정보 및 시스템 프롬프트 노출 위험",
            "detail": "시스템 지시문 오버라이드 패턴 탐지",
            "engine": "security",
            "page": 3,
            "review_status": "NEEDS_REVIEW",
        },
    ]

    result_data = {
        "project_id": "p1",
        "documents": [
            {
                "document_id": "d1",
                "filename": "sample_brief.pdf",
                "findings": synthetic_findings,
                "review_items": [
                    {
                        "item_id": "d1_CITATION_c1",
                        "kind": "CITATION",
                        "citation_id": "c1",
                        "finding_ids": ["f_temporal_long"],
                        "document_id": "d1",
                        "page": 1,
                        "location_label": "sample_brief.pdf 1쪽",
                        "claim_or_target": "부정경쟁방지법 제14조의2 제6항 5배 손해배상 청구",
                        "verdict_label": "증액·개정 규정 소급 적용 오류 — 시행일 이전 행위에 개정 법률 적용 (RETROACTIVE_APPLICATION_ERROR)",
                        "reason_text": "행위 당시 시행본은 3배 한도 규정이며 5배 규정은 행위일 이후 개정 시행되었습니다.",
                        "severity": "HIGH",
                        "official_status": "CONFIRMED",
                        "reference_status": "NOT_CHECKED",
                        "review_status": "NEEDS_REVIEW",
                        "source_badge": "판례 인용",
                    }
                ],
                "ai_detector_result": {
                    "verdict": "AI_SUSPECTED",
                    "score": 0.88,
                    "reasons": ["문체 급변 구간 감지"],
                },
                "ai_hallucination_table": [],
            }
        ],
    }

    static_dir = ROOT / "apps/web/static"
    files = {f"/static/{p.relative_to(static_dir).as_posix()}": p for p in static_dir.rglob("*") if p.is_file()}
    files["/"] = ROOT / "apps/web/index.html"

    def route_handler(route):
        path = urlsplit(route.request.url).path

        if path in files:
            route.fulfill(path=str(files[path]))
            return
        if path == "/api/health":
            route.fulfill(json={"status": "ok", "version": "0.10.0"})
            return
        if path in ("/api/auth/me", "/api/identity/me"):
            route.fulfill(json={"user_id": "u", "email": "tester@example.com", "display_name": "검토자", "role": "ADMIN", "authentication": "local"})
            return
        if path == "/api/verification-runs":
            route.fulfill(json={"active_count": 0, "runs": []})
            return
        if path == "/api/projects":
            route.fulfill(json=[project_data])
            return
        if path == "/api/projects/p1":
            route.fulfill(json=project_data)
            return
        if path == "/api/projects/p1/documents":
            route.fulfill(json=[{"id": "d1", "filename": "sample_brief.pdf", "included_in_verification": True}])
            return
        if path == "/api/projects/p1/runs":
            route.fulfill(json=[run_data])
            return
        if path == "/api/projects/p1/findings":
            route.fulfill(json=synthetic_findings)
            return
        if path.endswith("/result") or path.endswith("/results"):
            route.fulfill(json=result_data)
            return
        if path == "/api/projects/p1/audit":
            route.fulfill(json={"events": []})
            return
        if path == "/api/privacy-notice":
            route.fulfill(json={"version": "v1.0", "bullets": [], "ack_label": "", "report_header": ""})
            return
        if path.endswith("/findings/workflows"):
            route.fulfill(json=[])
            return
        if path.endswith("/reviews"):
            route.fulfill(json=[])
            return
        if path.endswith("/case-matrix"):
            route.fulfill(body="null", content_type="application/json")
            return
        if path == "/api/finding-categories":
            from packages.common.finding_category_map import CATEGORY_TO_TAB, FINDING_CATEGORY_MAP, get_category_counts
            route.fulfill(json={
                "categories": {ft.value: cat.value for ft, cat in FINDING_CATEGORY_MAP.items()},
                "tabs": {ft.value: CATEGORY_TO_TAB[cat].value for ft, cat in FINDING_CATEGORY_MAP.items()},
                "counts": get_category_counts(),
            })
            return

        route.fulfill(status=200, json=[])

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.route("**/*", route_handler)
        yield page
        browser.close()


def test_tk61_review_table_fixed_layout_and_column_widths(tk61_browser_page):
    """긴 판정 문구가 있어도 table-layout: fixed에 의해 열 너비가 머리글 지정 비율(10%, 25%, 25%, 40%)의 ±5%p 이내로 유지되어야 합니다."""
    page = tk61_browser_page
    page.goto("http://localhost/")
    select_first_project(page)

    page.get_by_role("button", name="검증·검토", exact=True).click()
    page.locator('.tabs button[data-tab="review"]').click()

    panel = page.locator('section[data-panel="review"]')
    table = panel.locator("#reviewTable")
    expect(table).to_be_visible()

    # 1. table-layout 스타일이 fixed인지 확인
    layout_style = table.evaluate("el => window.getComputedStyle(el).tableLayout")
    assert layout_style == "fixed", f"기대: fixed, 실제: {layout_style}"

    # 2. 열 너비 측정 (1열~4열)
    headers = table.locator("thead th")
    expect(headers).to_have_count(4)

    total_table_width = table.evaluate("el => el.getBoundingClientRect().width")
    assert total_table_width > 0, "표 너비가 0보다 커야 합니다."

    col_widths = []
    for i in range(4):
        w = headers.nth(i).evaluate("el => el.getBoundingClientRect().width")
        col_widths.append(w)

    ratios = [w / total_table_width for w in col_widths]

    # 머리글 기준 비율: 10%, 25%, 25%, 40% (허용 오차: ±5%p = ±0.05)
    expected_ratios = [0.10, 0.25, 0.25, 0.40]
    for i, (actual, expected) in enumerate(zip(ratios, expected_ratios)):
        assert abs(actual - expected) <= 0.05, (
            f"{i+1}번째 열 너비 비율 오류: 실제 {actual*100:.1f}%, 기대 {expected*100:.1f}% (±5%p 초과)"
        )

    # 3. 3열의 판정 배지(.validity-verdict)가 긴 문구에도 비정상적으로 팽창하지 않고 줄바꿈 허용되는지 확인
    verdict_badge = panel.locator("#aiVerificationRows tr .validity-verdict").first
    expect(verdict_badge).to_be_visible()
    badge_width = verdict_badge.evaluate("el => el.getBoundingClientRect().width")
    assert badge_width <= col_widths[2], (
        f"판정 배지 너비({badge_width}px)가 3열 너비({col_widths[2]}px)보다 작거나 같아야 합니다."
    )


def test_tk61_security_finding_items_vertical_layout(tk61_browser_page):
    """AI 작성·보안 진단 탭의 세부 항목이 위·아래 배치(제목 상단, 설명 하단)로 렌더링되어야 합니다."""
    page = tk61_browser_page
    page.goto("http://localhost/")
    select_first_project(page)

    page.get_by_role("button", name="검증·검토", exact=True).click()
    page.locator('.tabs button[data-tab="ai-verification"]').click()

    panel = page.locator('section[data-panel="ai-verification"]')
    items = panel.locator(".security-finding-item")
    expect(items.first).to_be_visible()

    count = items.count()
    assert count >= 1, "세부 항목이 1개 이상 존재해야 합니다."

    for i in range(count):
        item = items.nth(i)
        btn = item.locator("> .link-button")
        desc = item.locator("> small")

        expect(btn).to_be_visible()
        expect(desc).to_be_visible()

        btn_box = btn.bounding_box()
        desc_box = desc.bounding_box()

        assert btn_box is not None and desc_box is not None

        # 1. 제목 버튼 아래에 설명이 위치하는 상하 수직 배치 (btn.y + btn.height <= desc.y)
        assert desc_box["y"] >= btn_box["y"] + btn_box["height"] - 2, (
            f"항목 {i}: 설명 y({desc_box['y']})가 버튼 하단({btn_box['y'] + btn_box['height']})보다 아래에 있어야 합니다."
        )

        # 2. 제목 버튼과 설명의 좌측 정렬 (x좌표 일치 여부)
        assert abs(btn_box["x"] - desc_box["x"]) <= 4, (
            f"항목 {i}: 버튼 x({btn_box['x']})와 설명 x({desc_box['x']})의 좌측 정렬이 일치해야 합니다."
        )
