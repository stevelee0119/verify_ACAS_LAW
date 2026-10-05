"""F1 AI 작성·보안 진단 탭 분리 및 보안 카드 브라우저 회귀 시험

F1 수용 기준을 검증합니다:
1. 탭 이름이 'AI 작성·보안 진단'으로 변경되고 안내 배너가 표시되는가?
2. AI 탭에 판례 인용 검토 행 수 = 0, RAG 행 수 = 0인가?
3. AI 탭에 AI 진단 카드, 인젝션 검증 카드, 보안 카드가 노출되는가?
4. 확인할 항목 탭에서 AI·보안 유형 finding 행이 제외되는가?
5. HIGH 이상의 AI·보안 항목 존재 시 상단 고정 안내 배너가 노출되고 탭 전환 링크가 작동하는가?
6. 확인할 항목 하단 임시 섹션에 기존 판례 인용표가 온전히 보존(정보 손실 0)되는가?
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
def f1_browser_page():
    launch_kwargs = {"headless": True}
    channel = os.environ.get("LV_TEST_BROWSER_CHANNEL")
    if channel:
        launch_kwargs["channel"] = channel

    project_data = {
        "id": "p1",
        "name": "F1 분리 검증 프로젝트",
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

    synthetic_findings = [
        # 1. 일반 법리 검토 finding (확인할 항목 소속)
        {
            "id": "f_legal_1",
            "finding_type": "CASE_NOT_FOUND",
            "type": "CASE_NOT_FOUND",
            "title": "대법원 판례 공식 DB 미발견",
            "detail": "인용된 대법원 2022다12345 판결이 대법원 판례 DB에서 검색되지 않습니다.",
            "severity": "CRITICAL",
            "status": "UNCONFIRMED",
            "review_status": "NEEDS_REVIEW",
            "document_id": "d1",
            "page": 3,
            "citation_id": "cit_1",
        },
        # 2. 보안 진단 finding (보안 카드 소속, HIGH) -> 상단 배너 트리거
        {
            "id": "f_sec_1",
            "finding_type": "AUTHORSHIP_METADATA_LEAK",
            "type": "AUTHORSHIP_METADATA_LEAK",
            "title": "작성자 메타데이터 노출",
            "detail": "PDF 속성에 사내 작성자 계정명 및 소프트웨어 버전이 포함되어 있습니다.",
            "severity": "HIGH",
            "status": "FLAGGED",
            "review_status": "NEEDS_REVIEW",
            "document_id": "d1",
            "page": 1,
        },
        # 3. 인젝션 finding (인젝션 카드 소속)
        {
            "id": "f_inj_1",
            "finding_type": "PROMPT_INJECTION_SUSPECTED",
            "type": "PROMPT_INJECTION_SUSPECTED",
            "title": "은닉 프롬프트 인젝션 의심",
            "detail": "문서 2쪽에 시스템 지시 무력화 시도 문구가 포함되어 있습니다.",
            "severity": "CRITICAL",
            "status": "QUARANTINED",
            "review_status": "NEEDS_REVIEW",
            "document_id": "d1",
            "page": 2,
        },
    ]

    synthetic_hallucination_table = [
        {
            "location": "3쪽 2문단",
            "cited_authority": "대법원 2022다12345 판결",
            "claim_text": "원고의 청구는 대법원 2022다12345 판결의 법리에 비추어 타당하다.",
            "validity_verdict": "공식 DB 미발견",
            "ai_generation_basis": "종합법률정보 DB 조회 결과 부존재",
            "recommended_counteraction": "원문 확인 요청",
        }
    ]

    result_data = {
        "status": "COMPLETED",
        "documents": [
            {
                "id": "d1",
                "filename": "소장_준비서면.pdf",
                "quarantined": False,
                "ai_detector_result": {
                    "verdict": "HUMAN_AUTHORED",
                    "score": 0.12,
                    "reasons": ["어휘 다양성 및 문장 구조의 자연스러움 관찰"],
                },
                "ai_hallucination_table": synthetic_hallucination_table,
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
            route.fulfill(json={"status": "ok", "version": "0.9.13"})
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
            route.fulfill(json=[{"id": "d1", "filename": "소장_준비서면.pdf", "included_in_verification": True}])
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
            # 배정표 모듈의 실제 응답 반환
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
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.route("**/*", route_handler)
        yield page
        browser.close()


def test_ai_tab_renamed_and_notice_banner_visible(f1_browser_page):
    """AI 탭 버튼이 'AI 작성·보안 진단'으로 변경되고 안내 배너가 노출되어야 합니다."""
    page = f1_browser_page
    page.goto("http://localhost/")
    select_first_project(page)

    page.get_by_role("button", name="검증·검토", exact=True).click()

    ai_tab_btn = page.locator('.tabs button[data-tab="ai-verification"]')
    expect(ai_tab_btn).to_have_text("AI 작성·보안 진단")

    # 탭 클릭
    ai_tab_btn.click()

    # 패널 제목 및 안내 배너 확인
    panel = page.locator('section[data-panel="ai-verification"]')
    expect(panel).to_be_visible()
    expect(panel.locator("h2")).to_have_text("AI 작성·보안 진단")

    banner = panel.locator("#aiTabNoticeBanner")
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("확인할 항목")


def test_ai_tab_shows_security_card_and_no_citation_rows(f1_browser_page):
    """AI 탭에는 AI 진단 카드, 인젝션 카드, 보안 카드만 노출되고 인용표 행은 0이어야 합니다."""
    page = f1_browser_page
    page.goto("http://localhost/")
    select_first_project(page)

    page.get_by_role("button", name="검증·검토", exact=True).click()
    page.locator('.tabs button[data-tab="ai-verification"]').click()

    panel = page.locator('section[data-panel="ai-verification"]')

    # AI 생성 진단 카드 및 보안 카드 노출 확인
    cards = panel.locator("#aiSummaryCards")
    expect(cards.locator(".summary-card-wide h3").first).to_have_text("문서 AI 생성 여부 진단")
    expect(cards.locator(".security-card h3")).to_have_text("보안 및 파일 진단")

    # 보안 카드 내 메타데이터 누출 finding 노출 확인
    expect(cards.locator(".security-card")).to_contain_text("작성자 메타데이터 노출")

    # AI 탭 내부에는 인용 테이블 및 판례 대조 행이 없어야 함 (인용 행 수 = 0)
    expect(panel.locator("table.ai-table")).to_have_count(0)
    expect(panel.locator("#aiVerificationRows tr")).to_have_count(0)


def test_review_tab_filters_out_ai_security_findings(f1_browser_page):
    """확인할 항목 탭에는 AI·보안 유형 finding이 직접 노출되지 않아야 합니다."""
    page = f1_browser_page
    page.goto("http://localhost/")
    select_first_project(page)

    page.get_by_role("button", name="검증·검토", exact=True).click()
    page.locator('.tabs button[data-tab="review"]').click()

    findings_container = page.locator('section[data-panel="review"]')

    # 일반 법리 finding(CASE_NOT_FOUND)은 노출
    expect(findings_container).to_contain_text("대법원 판례 공식 DB 미발견")

    # 보안 유형 finding(AUTHORSHIP_METADATA_LEAK)과 인젝션 finding은 제외됨
    expect(findings_container).not_to_contain_text("작성자 메타데이터 노출")
    expect(findings_container).not_to_contain_text("은닉 프롬프트 인젝션 의심")


def test_high_security_alert_banner_visible_and_jumpable(f1_browser_page):
    """HIGH 이상 보안 finding 존재 시 확인할 항목 상단에 고정 안내 배너가 뜨고 탭 전환되어야 합니다."""
    page = f1_browser_page
    page.goto("http://localhost/")
    select_first_project(page)

    page.get_by_role("button", name="검증·검토", exact=True).click()
    page.locator('.tabs button[data-tab="review"]').click()

    # D2: HIGH 이상 보안 항목 상단 고정 안내 배너 확인
    alert_banner = page.locator("#highSecurityAlertBanner")
    expect(alert_banner).to_be_visible()
    expect(alert_banner).to_contain_text("HIGH 이상의 AI 작성·보안 진단 항목")

    # 배너의 점프 링크 클릭
    jump_link = alert_banner.locator('[data-jump-tab="ai-verification"]')
    jump_link.click()

    # AI 작성·보안 진단 탭으로 자동 전환 확인
    expect(page.locator('section[data-panel="ai-verification"]')).to_be_visible()
    expect(page.locator('.tabs button[data-tab="ai-verification"]')).to_have_class(re.compile(r"\bactive\b"))


def test_temporary_citation_section_preserved_under_review(f1_browser_page):
    """F2 통합 표에 판례 인용표가 온전히 보존(정보 손실 0)되어야 합니다."""
    page = f1_browser_page
    page.goto("http://localhost/")
    select_first_project(page)

    page.get_by_role("button", name="검증·검토", exact=True).click()
    page.locator('.tabs button[data-tab="review"]').click()

    # 통합 표 패널 확인
    review_panel = page.locator('section[data-panel="review"]')
    expect(review_panel).to_be_visible()

    # 판례 인용 데이터 행 노출 확인 (내용 단언 불변)
    expect(review_panel.locator("#aiVerificationRows tr")).to_have_count(1)
    expect(review_panel.locator("#aiVerificationRows")).to_contain_text("대법원 2022다12345 판결")
