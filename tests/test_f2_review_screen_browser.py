"""F2 통합 '검토 항목' 탭 화면 브라우저 시험.

수용 기준 검증:
1. 4열 통합 표(위치 / 문서 주장·인용 내용 / 근거 확인 결과 / 법리 타당성·반박·대응) 렌더링
2. 행 안 검토 상태 조작 (실제 계약 workflow_state, decision, revision, priority, assignee, note 보존):
   - 단일 finding 연결 행: PUT /api/findings/{id}/workflow 호출
   - 복수 finding 연결 행: POST /api/projects/{id}/reviews 호출
   - 순수 인용 행: 저장 불가 안내(정보 전용) 표시
3. 검색어, 심각도, 검토 상태, 진행 상태, 담당자 필터 동작 및 행 수 검증
4. 행 체크박스, 전체 선택 체크박스, 일괄 검토(batchReview) 동작 검증
5. 복수 finding 연결 행의 파생 항목 묶음(.derived-findings) 노출 검증
6. RAG 참고문헌 및 추가 관련 법조문, 미확인 범위 섹션 하단 표시 (정보 손실 0)
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
        # 행 1에 연결된 법리 finding 1 (CRITICAL)
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
            "priority": 2,
            "assignee": "변호사A",
            "document_id": "d1",
            "page": 3,
            "citation_id": "cit_1",
        },
        # 행 1에 함께 연결된 법리 finding 2 (HIGH - 복수 finding 묶음)
        {
            "id": "f_cit_2",
            "finding_id": "f_cit_2",
            "finding_type": "CASE_HOLDING_DISTORTION",
            "type": "CASE_HOLDING_DISTORTION",
            "title": "판시사항 왜곡 의심",
            "detail": "판시사항의 핵심 요지가 원문과 상이합니다.",
            "severity": "HIGH",
            "status": "UNCONFIRMED",
            "review_status": "NEEDS_REVIEW",
            "priority": 2,
            "assignee": "변호사A",
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
            "priority": 1,
            "assignee": "홍길동",
            "document_id": "d1",
            "page": 5,
        },
    ]

    # F2 단일 판정 review_items
    synthetic_review_items = [
        # 행 1: 복수 finding(f_cit_1, f_cit_2)이 연결된 인용 행
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
            "finding_ids": ["f_cit_1", "f_cit_2"],
            "citation_id": "cit_1",
            "reasoning_sections": {
                "review": "타당성 검토 결과: 해당 판례 미존재",
                "ai_label": "3개 모델 일치",
                "opinions": [],
            },
            "counteraction": "원문 확인 요청",
        },
        # 행 2: 단일 finding(f_fact_1)이 연결된 사실관계 행
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

    workflow_store = {
        "f_cit_1": {
            "finding_id": "f_cit_1",
            "revision": 1,
            "workflow_state": "NOT_STARTED",
            "decision": "UNDECIDED",
            "priority": 2,
            "assignee": "변호사A",
            "note": "초기메모",
        },
        "f_cit_2": {
            "finding_id": "f_cit_2",
            "revision": 1,
            "workflow_state": "NOT_STARTED",
            "decision": "UNDECIDED",
            "priority": 2,
            "assignee": "변호사A",
            "note": "초기메모",
        },
        "f_fact_1": {
            "finding_id": "f_fact_1",
            "revision": 1,
            "workflow_state": "COMPLETED",
            "decision": "AGREED",
            "priority": 1,
            "assignee": "홍길동",
            "note": "초기메모",
        },
    }

    static_dir = ROOT / "apps/web/static"
    files = {f"/static/{p.relative_to(static_dir).as_posix()}": p for p in static_dir.rglob("*") if p.is_file()}
    files["/"] = ROOT / "apps/web/index.html"

    workflow_put_calls = []
    bulk_review_calls = []

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
        if path.startswith("/api/findings/") and path.endswith("/workflow"):
            fid = path.split("/")[3]
            if req.method == "GET":
                data = workflow_store.get(fid, {
                    "finding_id": fid, "revision": 1, "workflow_state": "NOT_STARTED",
                    "decision": "UNDECIDED", "priority": 2, "assignee": "변호사A", "note": "초기메모",
                })
                route.fulfill(json=data)
                return
            if req.method == "PUT":
                payload = json.loads(req.post_data)
                workflow_put_calls.append({"path": path, "payload": payload})
                updated = {
                    "finding_id": fid,
                    "revision": payload.get("revision", 0) + 1,
                    "workflow_state": payload.get("workflow_state", "NOT_STARTED"),
                    "decision": payload.get("decision", "UNDECIDED"),
                    "priority": payload.get("priority", 2),
                    "assignee": payload.get("assignee", ""),
                    "note": payload.get("note", ""),
                }
                workflow_store[fid] = updated
                route.fulfill(json=updated)
                return
        if path == "/api/projects/p1/reviews" and req.method == "POST":
            payload = json.loads(req.post_data)
            bulk_review_calls.append({"path": path, "payload": payload})
            results = []
            vals = payload.get("values", {})
            for fid in payload.get("finding_ids", []):
                rev = payload.get("expected_revisions", {}).get(fid, 0) + 1
                item_res = {
                    "finding_id": fid,
                    "revision": rev,
                    "workflow_state": vals.get("workflow_state", "NOT_STARTED"),
                    "decision": vals.get("decision", "UNDECIDED"),
                    "priority": vals.get("priority", 2),
                    "assignee": vals.get("assignee", ""),
                    "note": vals.get("note", ""),
                }
                workflow_store[fid] = item_res
                results.append(item_res)
            route.fulfill(json=results)
            return
        if path == "/api/projects/p1/review-workflows":
            route.fulfill(json=list(workflow_store.values()))
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
        page._bulk_review_calls = bulk_review_calls
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
    """단일 finding 연결 행은 인라인 select 조작 시 실제 계약(workflow_state, decision, revision 등)으로 PUT 저장되어야 합니다."""
    page = f2_browser_page
    page.goto("http://localhost/")
    select_first_project(page)

    page.get_by_role("button", name="검증·검토", exact=True).click()
    page.locator('.tabs button[data-tab="review"]').click()

    panel = page.locator('section[data-panel="review"]')
    rows = panel.locator("#aiVerificationRows tr")

    # 1번째 행 (단일 finding 연결 행: f_fact_1, 우선순위 1로 상단 정렬, 초기상태 ACCEPTED)
    row_single = rows.nth(0)
    select_single = row_single.locator(".inline-workflow-select")
    expect(select_single).to_be_visible()
    expect(select_single).to_have_value("ACCEPTED")

    # 오탐(FALSE_POSITIVE)으로 상태 변경
    select_single.select_option("FALSE_POSITIVE")

    # 저장이 완료되어 토스트가 뜰 때까지 대기
    expect(page.locator("#toast")).to_contain_text("검토 상태가 저장되었습니다.")

    # 실제 계약 필드 단언 (workflow_state: COMPLETED, decision: FALSE_POSITIVE, revision: 1, 담당자·우선순위·메모 보존)
    assert len(page._workflow_put_calls) == 1
    call = page._workflow_put_calls[0]
    assert "f_fact_1" in call["path"]
    assert call["payload"]["workflow_state"] == "COMPLETED"
    assert call["payload"]["decision"] == "FALSE_POSITIVE"
    assert call["payload"]["revision"] == 1
    assert call["payload"]["priority"] == 1
    assert call["payload"]["assignee"] == "홍길동"
    assert call["payload"]["note"] == "초기메모"

    # 3번째 행 (순수 인용 행): 저장 불가 안내 확인
    row_pure = rows.nth(2)
    expect(row_pure.locator(".inline-workflow-note")).to_contain_text("검토 상태: 저장 불가 (정보 전용)")
    expect(row_pure.locator(".inline-workflow-select")).to_have_count(0)


def test_f2_inline_workflow_agreed_manipulation(f2_browser_page):
    """행 안에서 확인 전(NEEDS_REVIEW) 선택 시 workflow_state=NOT_STARTED, decision=UNDECIDED로 저장되어야 합니다."""
    page = f2_browser_page
    page.goto("http://localhost/")
    select_first_project(page)

    page.get_by_role("button", name="검증·검토", exact=True).click()
    page.locator('.tabs button[data-tab="review"]').click()

    panel = page.locator('section[data-panel="review"]')
    rows = panel.locator("#aiVerificationRows tr")

    # 1번째 행 (단일 finding: f_fact_1, 초기상태 ACCEPTED)에서 확인 전으로 변경
    row_single = rows.nth(0)
    select_single = row_single.locator(".inline-workflow-select")
    select_single.select_option("NEEDS_REVIEW")

    expect(page.locator("#toast")).to_contain_text("검토 상태가 저장되었습니다.")
    assert len(page._workflow_put_calls) == 1
    call = page._workflow_put_calls[0]
    assert call["payload"]["workflow_state"] == "NOT_STARTED"
    assert call["payload"]["decision"] == "UNDECIDED"


def test_f2_filters_search_severity_review_status(f2_browser_page):
    """검색어, 중요도, 검토 상태, 진행 상태, 담당자 필터 동작 시 표시 행 수가 올바르게 갱신되어야 합니다."""
    page = f2_browser_page
    page.goto("http://localhost/")
    select_first_project(page)

    page.get_by_role("button", name="검증·검토", exact=True).click()
    page.locator('.tabs button[data-tab="review"]').click()

    panel = page.locator('section[data-panel="review"]')
    rows = panel.locator("#aiVerificationRows tr")
    expect(rows).to_have_count(3)

    # 1. 중요도 필터: CRITICAL 선택 -> 1개 행 노출
    sev_select = panel.locator("#severityFilter")
    sev_select.select_option("CRITICAL")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("대법원 2022다99999 판결")
    sev_select.select_option("")
    expect(rows).to_have_count(3)

    # 2. 진행 상태 필터: NOT_STARTED 선택 -> 행 1, 행 3(순수 인용) 총 2개 행 노출
    wf_select = panel.locator("#workflowFilter")
    wf_select.select_option("NOT_STARTED")
    expect(rows).to_have_count(2)

    # 진행 상태 필터: COMPLETED 선택 -> 행 2(1개 행) 노출
    wf_select.select_option("COMPLETED")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("일자 선후 모순")
    wf_select.select_option("")
    expect(rows).to_have_count(3)

    # 3. 담당자 필터: '홍길동' 입력 -> 1개 행 노출
    ass_input = panel.locator("#assigneeFilter")
    ass_input.fill("홍길동")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("일자 선후 모순")

    ass_input.fill("변호사A")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("대법원 2022다99999 판결")
    ass_input.fill("")
    expect(rows).to_have_count(3)

    # 4. 검토 상태 필터: 'ACCEPTED' 선택 -> 1개 행 노출
    rev_select = panel.locator("#reviewFilter")
    rev_select.select_option("ACCEPTED")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("일자 선후 모순")
    rev_select.select_option("")
    expect(rows).to_have_count(3)

    # 5. 검색어 필터: '선후 모순' 검색 -> 1개 행 노출
    search_input = panel.locator("#findingSearch")
    search_input.fill("선후 모순")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("일자 선후 모순")
    search_input.fill("")
    expect(rows).to_have_count(3)


def test_f2_checkboxes_and_batch_review(f2_browser_page):
    """행 체크박스 및 전체 선택 체크박스 조작 시 선택 수가 동기화되고 일괄 검토가 동작해야 합니다."""
    page = f2_browser_page
    page.goto("http://localhost/")
    select_first_project(page)

    page.get_by_role("button", name="검증·검토", exact=True).click()
    page.locator('.tabs button[data-tab="review"]').click()

    panel = page.locator('section[data-panel="review"]')
    batch_btn = panel.locator("#batchReview")
    expect(batch_btn).to_have_text("선택 항목 검토 (0)")

    # 1. 1번째 행(f_fact_1, 1건) 체크박스 클릭 -> 1개 선택
    row_checks = panel.locator(".row-checkbox")
    expect(row_checks).to_have_count(2)  # finding_ids가 있는 2개 행에만 체크박스 존재
    row_checks.nth(0).check()
    expect(batch_btn).to_have_text("선택 항목 검토 (1)")

    # 2. 전체 선택 체크박스 클릭 -> 3개 finding 전체 선택 (f_cit_1, f_cit_2, f_fact_1)
    select_all = panel.locator("#selectAllFindings")
    select_all.check()
    expect(batch_btn).to_have_text("선택 항목 검토 (3)")

    # 3. 일괄 검토 버튼 클릭 -> 모달 오픈
    batch_btn.click()
    dialog = page.locator("dialog.workflow-dialog")
    expect(dialog).to_be_visible()

    # 모달 내 검토 저장 클릭
    dialog.locator("button[type='submit']").click()
    expect(page.locator("#toast")).to_contain_text("선택 항목을 저장했습니다.")

    # POST /api/projects/p1/reviews 벌크 호출 검증
    assert len(page._bulk_review_calls) == 1
    call = page._bulk_review_calls[0]
    assert set(call["payload"]["finding_ids"]) == {"f_cit_1", "f_cit_2", "f_fact_1"}


def test_f2_derived_findings_bundle_and_multi_save(f2_browser_page):
    """복수 finding이 연결된 행은 파생 항목 묶음(.derived-findings)이 노출되고, 행 안 검토 상태 조작 시 각 finding별 개별 PUT으로 전부에 적용되어야 합니다."""
    page = f2_browser_page
    page.goto("http://localhost/")
    select_first_project(page)

    page.get_by_role("button", name="검증·검토", exact=True).click()
    page.locator('.tabs button[data-tab="review"]').click()

    panel = page.locator('section[data-panel="review"]')
    rows = panel.locator("#aiVerificationRows tr")

    # 2번째 행: 복수 finding (f_cit_1, f_cit_2) 연결 행
    row_multi = rows.nth(1)

    # 2열 파생 항목 묶음 details 확인
    derived = row_multi.locator(".derived-findings")
    expect(derived).to_be_visible()
    expect(derived.locator("summary")).to_contain_text("같은 인용에서 파생된 항목 1건")

    # 행 안 워크플로우 조작: 지적 수용(ACCEPTED) 선택
    select_multi = row_multi.locator(".inline-workflow-select")
    select_multi.select_option("ACCEPTED")

    expect(page.locator("#toast")).to_contain_text("검토 상태가 저장되었습니다.")

    # 복수 finding 행이므로 각 finding별 개별 PUT /findings/{id}/workflow가 호출되어 메타데이터가 각자 보존되어야 함 (TK-60 7절)
    put_fids = [call["path"].split("/")[3] for call in page._workflow_put_calls]
    assert "f_cit_1" in put_fids
    assert "f_cit_2" in put_fids
    for call in page._workflow_put_calls:
        if "f_cit_1" in call["path"] or "f_cit_2" in call["path"]:
            assert call["payload"]["workflow_state"] == "COMPLETED"
            assert call["payload"]["decision"] == "AGREED"


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
