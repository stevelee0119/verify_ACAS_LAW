"""F2 통합 '검토 항목' 탭 화면 브라우저 시험.

수용 기준 검증:
1. 4열 통합 표(위치 / 문서 주장·인용 내용 / 근거 확인 결과 / 법리 타당성·반박·대응) 렌더링
2. 검색어, 심각도, 검토 상태 필터 동작
3. 행 안 검토 상태 조작:
   - finding 연결 행은 select 조작 시 /api/findings/{id}/workflow PUT 호출 및 저장 성공
   - 순수 인용 행은 저장 불가 안내(정보 전용) 표시
4. RAG 참고문헌 및 추가 관련 법조문 섹션 하단 표시 (정보 손실 0)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright
from frontend_helpers import select_first_project

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def f2_browser_page():
    launch_kwargs = {"headless": True}
    channel = os.environ.get("LV_TEST_BROWSER_CHANNEL")
    if channel:
        launch_kwargs["channel"] = channel

    project_data = {
        "id": "p1",
        "name": "F2 통합 검토 검증 프로젝트",
        "can_delete": True,
        "document_count": 1,
        "external_ai_policy": "MASKED",
        "scope_revision": 0,
        "requested_issues": ["손해배상"],
    }

    run_data = {
        "id": "r1",
        "project_id": "p1",
        "state": "COMPLETED",
        "progress": 1,
        "stage_message": "",
        "document_ids": ["d1"],
        "scores": {},
        "unverified_items": [
            {"document_id": "d1", "page": 2, "raw_text": "관련 별지 서증", "reason": "DOCUMENT_UNREADABLE"}
        ],
        "errors": [],
        "unavailable_sources": [],
        "input_snapshot": {"scope_revision": 0},
        "started_at": "2026-10-04T00:00:00",
    }

    synthetic_findings = [
        # 행 1에 연결된 법리 finding (CRITICAL)
        {
            "id": "f_cit_1",
            "finding_id": "f_cit_1",
            "finding_type": "CASE_NOT_FOUND",
            "type": "CASE_NOT_FOUND",
            "title": "공식 DB 미발견 판례",
            "detail": "합성 사건번호 판례가 공식 DB에 존재하지 않습니다.",
            "severity": "CRITICAL",
            "status": "UNCONFIRMED",
            "review_status": "NEEDS_REVIEW",
            "document_id": "d1",
            "page": 3,
            "citation_id": "cit_1",
        },
        # 행 2에 연결된 사실관계 finding (MEDIUM)
        {
            "id": "f_fact_1",
            "finding_id": "f_fact_1",
            "finding_type": "TIMELINE_ORDER_INCONSISTENCY",
            "type": "TIMELINE_ORDER_INCONSISTENCY",
            "title": "일자 선후 모순",
            "detail": "처분일자가 신청일자보다 앞서 기재되어 있습니다.",
            "severity": "MEDIUM",
            "status": "FLAGGED",
            "review_status": "ACCEPTED",
            "document_id": "d1",
            "page": 5,
        },
    ]

    # F2 단일 판정 review_items
    synthetic_review_items = [
        # 행 1: finding이 연결된 인용 행
        {
            "item_id": "d1_CITATION_cit_1",
            "kind": "CITATION",
            "document_id": "d1",
            "location": {"page": 3, "display": "3쪽 2문단"},
            "claim_text": "원고의 청구는 판례 법리에 부합함",
            "cited_authority": "대법원 2022다99999 판결",
            "official_status": "OFFICIAL_NOT_FOUND",
            "reference_status": "NOT_CHECKED",
            "verdict_label": "공식 DB 미확인",
            "severity": "CRITICAL",
            "finding_ids": ["f_cit_1"],
            "citation_id": "cit_1",
            "reasoning_sections": {
                "review": "타당성 검토 결과: 해당 판례 미존재",
                "ai_label": "3개 모델 일치",
                "opinions": [],
            },
            "counteraction": "원문 확인 요청",
        },
        # 행 2: finding이 연결된 사실관계 행
        {
            "item_id": "d1_FINDING_f_fact_1",
            "kind": "FACT",
            "document_id": "d1",
            "location": {"page": 5},
            "claim_text": "처분일자 2023.01.01에 따른 이행 청구",
            "cited_authority": None,
            "official_status": "NOT_ASSESSED",
            "reference_status": "NOT_CHECKED",
            "verdict_label": "일자 선후 모순",
            "severity": "MEDIUM",
            "finding_ids": ["f_fact_1"],
            "citation_id": None,
            "reasoning_sections": None,
            "counteraction": "입증서증 확인 필요",
        },
        # 행 3: finding이 연결되지 않은 순수 인용 행 (정보 전용)
        {
            "item_id": "d1_CITATION_cit_pure",
            "kind": "CITATION",
            "document_id": "d1",
            "location": {"page": 1, "display": "1쪽"},
            "claim_text": "헌법상 기본권에 근거한 정당한 주장",
            "cited_authority": "헌법 제10조",
            "official_status": "OFFICIAL_CONFIRMED",
            "reference_status": "NOT_CHECKED",
            "verdict_label": "공식 원문 일치",
            "severity": "INFO",
            "finding_ids": [],
            "citation_id": "cit_pure",
            "reasoning_sections": None,
            "counteraction": "적용 법리 타당성 직접 검토",
        },
    ]

    result_data = {
        "status": "COMPLETED",
        "run_manifest": {
            "reference_library": {
                "status": "READY",
                "files_indexed": 3,
                "files_seen": 3,
                "checked_at": "2026-10-04T12:00:00",
            }
        },
        "documents": [
            {
                "id": "d1",
                "filename": "통합검토서면.pdf",
                "quarantined": False,
                "findings": synthetic_findings,
                "review_items": synthetic_review_items,
                "ai_hallucination_table": [
                    {
                        "location": "3쪽 2문단",
                        "cited_authority": "대법원 2022다99999 판결",
                        "claim_text": "원고의 청구는 판례 법리에 부합함",
                        "validity_verdict": "공식 DB 미확인",
                        "ai_generation_basis": "공식 소스 미존재",
                        "recommended_counteraction": "원문 확인 요청",
                    }
                ],
                "engine_data": {
                    "related_authorities": {
                        "note": "추가 검토 필요",
                        "candidates": [{"raw_text": "민법 제750조", "citation_id": "cit_rel_1"}],
                        "verdicts": [{"citation_id": "cit_rel_1", "status": "CONFIRMED"}],
                    }
                },
            }
        ],
    }

    static_dir = ROOT / "apps/web/static"
    files = {f"/static/{p.relative_to(static_dir).as_posix()}": p for p in static_dir.rglob("*") if p.is_file()}
    files["/"] = ROOT / "apps/web/index.html"

    workflow_put_calls = []

    def route_handler(route):
        req = route.request
        path = urlsplit(req.url).path

        if path in files:
            route.fulfill(path=str(files[path]))
            return
        if path == "/api/health":
            route.fulfill(json={"status": "ok", "version": "0.10.0"})
            return
        if path in ("/api/auth/me", "/api/identity/me"):
            route.fulfill(json={"user_id": "u", "email": "t@example.com", "display_name": "검토자", "role": "ADMIN", "authentication": "local"})
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
            route.fulfill(json=[{"id": "d1", "filename": "통합검토서면.pdf", "included_in_verification": True}])
            return
        if path == "/api/projects/p1/runs":
            route.fulfill(json=[run_data])
            return
        if path == "/api/projects/p1/findings":
            route.fulfill(json=synthetic_findings)
            return
        if path.endswith(("/result", "/results")):
            route.fulfill(json=result_data)
            return
        if path == "/api/projects/p1/audit":
            route.fulfill(json={"events": []})
            return
        if path == "/api/privacy-notice":
            route.fulfill(json={"version": "v1.0", "bullets": [], "ack_label": "", "report_header": ""})
            return
        if path == "/api/finding-categories":
            from packages.common.finding_category_map import CATEGORY_TO_TAB, FINDING_CATEGORY_MAP, get_category_counts
            route.fulfill(json={
                "categories": {ft.value: cat.value for ft, cat in FINDING_CATEGORY_MAP.items()},
                "tabs": {ft.value: CATEGORY_TO_TAB[cat].value for ft, cat in FINDING_CATEGORY_MAP.items()},
                "counts": get_category_counts(),
            })
            return
        if "/workflow" in path and req.method == "PUT":
            payload = json.loads(req.post_data)
            workflow_put_calls.append({"path": path, "payload": payload})
            route.fulfill(json={"ok": True, "status": payload.get("review_status")})
            return
        if path.endswith("/case-matrix"):
            route.fulfill(body="null", content_type="application/json")
            return

        route.fulfill(status=200, json=[])

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.route("**/*", route_handler)
        page._workflow_put_calls = workflow_put_calls
        yield page
        browser.close()


def test_f2_review_table_renders_four_columns(f2_browser_page):
    """F2 확인할 항목 탭은 위치/문서 주장·인용 내용/근거 확인 결과/법리 타당성·반박·대응 4열 통합 표를 렌더링해야 합니다."""
    page = f2_browser_page
    page.goto("http://localhost/")
    select_first_project(page)

    page.get_by_role("button", name="검증·검토", exact=True).click()
    page.locator('.tabs button[data-tab="review"]').click()

    panel = page.locator('section[data-panel="review"]')
    expect(panel).to_be_visible()

    # 4열 헤더 검증
    headers = panel.locator(".review-items-table thead th")
    expect(headers).to_have_count(4)
    expect(headers.nth(0)).to_have_text("위치")
    expect(headers.nth(1)).to_have_text("문서 주장 및 인용 내용")
    expect(headers.nth(2)).to_have_text("인용 오류·미확인 근거 및 주장 평가 (작성 주체 판단에 쓰지 않음)")
    expect(headers.nth(3)).to_have_text("법리적 타당성 검토 및 반박 근거")

    # 3개 행 노출 확인
    rows = panel.locator("#aiVerificationRows tr")
    expect(rows).to_have_count(3)


def test_f2_inline_workflow_manipulation(f2_browser_page):
    """finding이 연결된 행은 인라인 select로 검토 상태를 변경할 수 있고, 순수 인용 행은 저장 불가 안내가 노출되어야 합니다."""
    page = f2_browser_page
    page.goto("http://localhost/")
    select_first_project(page)

    page.get_by_role("button", name="검증·검토", exact=True).click()
    page.locator('.tabs button[data-tab="review"]').click()

    panel = page.locator('section[data-panel="review"]')
    rows = panel.locator("#aiVerificationRows tr")

    # 1번째 행 (CRITICAL finding 연결 행): 인라인 select 조작
    row1 = rows.nth(0)
    select1 = row1.locator(".inline-workflow-select")
    expect(select1).to_be_visible()
    expect(select1).to_have_value("NEEDS_REVIEW")

    # 지적 수용(ACCEPTED)으로 상태 변경
    select1.select_option("ACCEPTED")

    # 저장이 완료되어 토스트가 뜰 때까지 대기
    expect(page.locator("#toast")).to_contain_text("검토 상태가 저장되었습니다.")

    # API PUT 호출 확인
    assert len(page._workflow_put_calls) == 1
    assert "f_cit_1" in page._workflow_put_calls[0]["path"]
    assert page._workflow_put_calls[0]["payload"]["review_status"] == "ACCEPTED"

    # 3번째 행 (순수 인용 행): 저장 불가 안내 확인
    row3 = rows.nth(2)
    expect(row3.locator(".inline-workflow-note")).to_contain_text("검토 상태: 저장 불가 (정보 전용)")
    expect(row3.locator(".inline-workflow-select")).to_have_count(0)


def test_f2_filters_search_severity_review_status(f2_browser_page):
    """검색어, 중요도, 검토 상태 필터가 통합 표에 정상 반영되어야 합니다."""
    page = f2_browser_page
    page.goto("http://localhost/")
    select_first_project(page)

    page.get_by_role("button", name="검증·검토", exact=True).click()
    page.locator('.tabs button[data-tab="review"]').click()

    panel = page.locator('section[data-panel="review"]')
    rows = panel.locator("#aiVerificationRows tr")
    expect(rows).to_have_count(3)

    # 1. 중요도 필터: CRITICAL 선택 -> 1개 행만 노출
    sev_select = panel.locator("#severityFilter")
    sev_select.select_option("CRITICAL")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("대법원 2022다99999 판결")

    # 중요도 필터 초기화
    sev_select.select_option("")
    expect(rows).to_have_count(3)

    # 2. 검색어 필터: '선후 모순' 검색 -> 1개 행 노출
    search_input = panel.locator("#findingSearch")
    search_input.fill("선후 모순")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("일자 선후 모순")

    # 검색어 초기화
    search_input.fill("")
    expect(rows).to_have_count(3)

    # 3. 검토 상태 필터: 'ACCEPTED' 선택 -> 1개 행 노출 (f_fact_1)
    rev_select = panel.locator("#reviewFilter")
    rev_select.select_option("ACCEPTED")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("일자 선후 모순")


def test_f2_references_and_unverified_scope_rendered(f2_browser_page):
    """RAG 주요 참고문헌 및 미확인 범위, 추가 법조문이 통합 탭 하단에 온전히 표시되어야 합니다 (정보 손실 0)."""
    page = f2_browser_page
    page.goto("http://localhost/")
    select_first_project(page)

    page.get_by_role("button", name="검증·검토", exact=True).click()
    page.locator('.tabs button[data-tab="review"]').click()

    panel = page.locator('section[data-panel="review"]')

    # 미확인 범위 확인
    unverified = panel.locator("#unverifiedScopeContainer")
    expect(unverified).to_contain_text("미확인 범위 1건")
    expect(unverified).to_contain_text("관련 별지 서증")

    # RAG 주요 참고문헌 및 관련 법조문 확인
    ref_container = panel.locator("#reviewReferencesContainer")
    expect(ref_container).to_contain_text("주요 참고문헌 검토 결과(RAG)")
    expect(ref_container).to_contain_text("추가 관련 법조문 검토")
    expect(ref_container).to_contain_text("민법 제750조")
