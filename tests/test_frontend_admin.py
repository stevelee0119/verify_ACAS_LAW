"""Admin workspace regression tests. API fixtures are synthetic, not live SMTP evidence."""
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def admin_page():
    users = [
        {"id": f"u{i}", "email": f"reviewer{i:02}@example.test", "display_name": f"검토자 {i:02}",
         "role": "ADMIN" if i == 0 else "MEMBER", "affiliation": "법무 검토팀",
         "approval_status": "PENDING" if i >= 43 else "APPROVED", "enabled": i < 43,
         "registration_reason": "문서 검토", "created_at": "2026-09-27T00:00:00",
         "monthly_metrics": {"login_count": 2, "verification_count": 3, "storage_used_mb": 5,
                             "storage_quota_mb": None if i == 0 else 1024, "storage_unlimited": i == 0,
                             "compute_minutes": 4, "monthly_upload_mb": 6}}
        for i in range(45)
    ]
    control = {"role": "ADMIN", "users": users, "mutations": [], "metrics_error": False, "deferred": [],
               "hold_metrics": False, "hold_approval": False, "identity_error": False}
    mail = [{"id": f"m{i}", "user_id": "u1", "kind": "APPROVAL", "status": status,
             "attempts": 3 if i == 3 else 1, "created_at": "2026-09-27T09:00:00+09:00"}
            for i, status in enumerate(("SMTP_ACCEPTED", "FAILED", "UNKNOWN", "FAILED"))]

    def respond(route):
        request = route.request
        path = urlsplit(request.url).path
        if path == "/":
            route.fulfill(path=str(ROOT / "apps/web/index.html"))
            return
        if path.startswith("/static/"):
            file = ROOT / "apps/web" / path.lstrip("/")
            if file.is_file():
                route.fulfill(path=str(file))
            else:
                route.fulfill(status=404)
            return
        if request.method not in ("GET", "HEAD"):
            control["mutations"].append((path, request.post_data_json if request.post_data else None))
            if path.endswith("/approve"):
                if control["hold_approval"]:
                    control["deferred"].append(route)
                    return
                users[-2]["approval_status"] = "APPROVED"
                route.fulfill(json={"approved": True, "notification": {"status": "QUEUED"}})
            elif path.endswith("/reject"):
                users[-1]["approval_status"] = "REJECTED"
                route.fulfill(json={"rejected": True})
            elif path.endswith("/retry"):
                route.fulfill(json={"status": "QUEUED"})
            else:
                route.fulfill(json={})
            return
        if path == "/api/health":
            result = {"status": "ok", "version": "test"}
        elif path == "/api/identity/me":
            if control["identity_error"]:
                route.fulfill(status=503, json={"detail": "Unavailable"})
                return
            result = {"user_id": "u0", "role": control["role"], "organization_id": "org", "authentication": "password"}
        elif path == "/api/auth/me":
            result = users[0]
        elif path == "/api/projects":
            result = []
        elif path == "/api/verification-runs":
            result = {"runs": [], "active_count": 0}
        elif path in ("/api/auth/users", "/api/identity/users"):
            result = users
        elif path == "/api/admin/users":
            if control["hold_metrics"]:
                control["deferred"].append(route)
                return
            result = {} if control["metrics_error"] else users
        elif path == "/api/admin/pending-registrations":
            pending = [u for u in users if u["approval_status"] == "PENDING"]
            result = {"count": len(pending), "users": pending}
        elif path == "/api/admin/notifications":
            result = {"smtp": {"configured": True, "security": "STARTTLS", "port": 587}, "items": mail}
        elif path.endswith("/monthly-stats"):
            result = [{"year": 2026, "month": 9, **users[1]["monthly_metrics"]}]
        elif path.endswith("/tokens"):
            result = []
        else:
            route.fulfill(status=404, json={"detail": "Unexpected fixture endpoint"})
            return
        route.fulfill(json=result)

    with sync_playwright() as playwright:
        options = {"headless": True}
        if os.getenv("LV_TEST_BROWSER_CHANNEL"):
            options["channel"] = os.environ["LV_TEST_BROWSER_CHANNEL"]
        browser = playwright.chromium.launch(**options)
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", respond)
        try:
            page.goto("https://admin.test/")
            expect(page.locator("#adminNavigation")).to_be_visible()
            page.locator("#adminNavigation").click()
            expect(page.locator(".admin-table tbody tr")).to_have_count(20)
            yield page, control
            assert not errors
        finally:
            browser.close()


def select_tab(page, name):
    page.get_by_role("tab", name=name, exact=True).click()
    expect(page.locator("#adminPanel")).to_have_attribute("aria-busy", "false")


def test_storage_policy_is_explicit_in_usage_table_and_details(admin_page):
    page, _ = admin_page
    select_tab(page, "이용 통계")
    row = page.locator(".admin-table tbody tr").filter(has_text="reviewer00@example.test")
    expect(row).to_contain_text("5 / 제한 없음")
    expect(page.locator(".admin-table tbody tr").filter(has_text="reviewer01@example.test")).to_contain_text("5 / 1,024")
    row.get_by_role("button", name="상세 보기: 검토자 00").click()
    detail = page.get_by_role("dialog", name="검토자 00", exact=True)
    expect(detail).to_contain_text("제한 없음")
    expect(detail).to_contain_text("현재 원본 (휴지통 포함)")


def test_search_filters_pagination_and_workspace_context(admin_page):
    page, _ = admin_page
    page.get_by_role("button", name="다음 페이지", exact=True).click()
    expect(page.locator(".admin-pagination")).to_contain_text("2 / 3")
    page.get_by_label("사용자 검색", exact=True).fill("reviewer44")
    expect(page.locator(".admin-table tbody tr")).to_have_count(1)
    expect(page.locator(".admin-table")).to_contain_text("검토자 44")
    page.get_by_label("계정 상태", exact=True).select_option("ACTIVE")
    expect(page.locator(".admin-rows")).to_contain_text("검색 결과가 없습니다")
    page.get_by_role("button", name="필터 초기화").click()
    page.get_by_label("역할", exact=True).select_option("ADMIN")
    expect(page.locator(".admin-table tbody tr")).to_have_count(1)
    page.get_by_role("button", name="작업 공간", exact=True).click()
    expect(page.locator("#emptyState")).to_be_visible()
    page.locator("#adminNavigation").click()
    expect(page.get_by_label("역할", exact=True)).to_have_value("ADMIN")
    page.get_by_label("역할", exact=True).select_option("")
    page.get_by_label("페이지당", exact=True).select_option("50")
    expect(page.locator(".admin-table tbody tr")).to_have_count(45)


def test_keyboard_tabs_and_drawer_focus(admin_page):
    page, _ = admin_page
    page.get_by_role("tab", name="사용자", exact=True).press("ArrowRight")
    expect(page.get_by_role("tab", name="승인 대기", exact=True)).to_be_focused()
    expect(page.locator(".admin-table tbody tr")).to_have_count(2)
    opener = page.get_by_role("button", name="사용자 상세: 검토자 43", exact=True)
    opener.click()
    expect(page.get_by_role("dialog")).to_have_count(1)
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(opener).to_be_focused()
    page.get_by_role("tab", name="승인 대기", exact=True).press("End")
    expect(page.get_by_role("tab", name="메일 기록", exact=True)).to_be_focused()


def test_approval_and_rejection_are_distinct_and_never_nested(admin_page):
    page, control = admin_page
    select_tab(page, "승인 대기")
    page.get_by_role("button", name="사용자 상세: 검토자 43", exact=True).click()
    page.get_by_role("button", name="승인", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(1)
    page.get_by_role("button", name="승인 확정", exact=True).click()
    expect(page.locator(".admin-feedback")).to_contain_text("승인 완료 · 메일: 발송 대기")
    page.get_by_role("button", name="사용자 상세: 검토자 44", exact=True).click()
    page.get_by_role("button", name="반려", exact=True).click()
    expect(page.get_by_role("dialog")).to_contain_text("메일 발송 없음")
    page.get_by_role("button", name="반려 확정", exact=True).click()
    assert len(control["mutations"]) == 1
    page.get_by_label("반려 사유", exact=True).fill("소속 확인이 필요합니다.")
    page.get_by_role("button", name="반려 확정", exact=True).click()
    expect(page.locator(".admin-feedback")).to_contain_text("로그인 화면 안내")
    assert control["mutations"] == [
        ("/api/admin/users/u43/approve", None),
        ("/api/admin/users/u44/reject", {"reason": "소속 확인이 필요합니다."}),
    ]


@pytest.mark.parametrize("password", ["", "Synthetic-Only-927!"])
def test_provisioning_keeps_password_and_token_account_paths(admin_page, password):
    page, control = admin_page
    page.get_by_role("button", name="사용자 등록", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("이름", exact=True).fill("신규 검토자")
    dialog.get_by_label("이메일", exact=True).fill("new@example.test")
    dialog.get_by_label("초기 비밀번호 (선택, 10자 이상)", exact=True).fill(password)
    dialog.get_by_role("button", name="등록", exact=True).click()
    expect(page.locator(".admin-feedback")).to_contain_text("사용자 등록 완료")
    path, body = control["mutations"][0]
    assert path == ("/api/auth/users" if password else "/api/identity/users")
    assert body.get("password", "") == password
    expect(page.locator('input[type="password"]')).to_have_count(0)


def test_self_protection_and_nonowner_tokens_cannot_be_minted(admin_page):
    page, control = admin_page
    page.get_by_role("button", name="사용자 상세: 검토자 00", exact=True).click()
    expect(page.get_by_role("button", name="권한 수정", exact=True)).to_have_count(0)
    page.keyboard.press("Escape")
    page.get_by_role("button", name="사용자 상세: 검토자 01", exact=True).click()
    page.get_by_role("button", name="권한 수정", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("역할", exact=True).select_option("VIEWER")
    dialog.get_by_label("계정 활성", exact=True).uncheck()
    dialog.get_by_role("button", name="저장", exact=True).click()
    expect(page.locator(".admin-feedback")).to_contain_text("권한 변경 완료")
    assert control["mutations"][0] == ("/api/identity/users/u1", {"role": "VIEWER", "enabled": False})
    page.get_by_role("button", name="사용자 상세: 검토자 01", exact=True).click()
    page.get_by_role("button", name="접속 토큰", exact=True).click()
    expect(page.get_by_role("dialog", name="접속 토큰", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="새 토큰 발급", exact=True)).to_have_count(0)


def test_invalid_metrics_are_not_rendered_as_zero_and_retry_recovers(admin_page):
    page, control = admin_page
    control["metrics_error"] = True
    select_tab(page, "이용 통계")
    expect(page.locator(".admin-rows")).to_contain_text("통계 응답 형식")
    expect(page.locator(".admin-table")).to_have_count(0)
    control["metrics_error"] = False
    page.get_by_role("button", name="다시 불러오기", exact=True).click()
    expect(page.locator(".admin-table tbody tr")).to_have_count(20)
    page.get_by_role("button", name="사용자 상세: 검토자 01", exact=True).click()
    expect(page.get_by_role("dialog")).to_contain_text("대기 포함")
    page.get_by_role("button", name="월별 추이", exact=True).click()
    expect(page.get_by_role("dialog")).to_contain_text("2026-09")


def test_stale_response_and_identity_loss_clear_admin_content(admin_page):
    page, control = admin_page
    control["hold_metrics"] = True
    page.get_by_role("tab", name="이용 통계", exact=True).click()
    page.wait_for_function("document.querySelector('#adminPanel').getAttribute('aria-busy') === 'true'")
    # A subsequent request is a deterministic boundary for the held request handler.
    select_tab(page, "승인 대기")
    assert control["deferred"]
    control["deferred"].pop().fulfill(json=control["users"])
    expect(page.locator(".admin-table tbody tr")).to_have_count(2)
    control["role"] = "MEMBER"
    page.evaluate("operationsUI.refreshIdentity()")
    expect(page.locator("#adminView")).to_be_hidden()
    expect(page.locator("#adminNavigation")).to_be_hidden()
    assert page.locator(".admin-table").count() == 0
    page.reload()
    expect(page.locator("#accountButton")).to_have_attribute("aria-label", "내 계정 · 검토자")
    expect(page.locator("#adminView")).to_be_hidden()


def test_inflight_approval_is_submitted_once_and_cannot_be_dismissed(admin_page):
    page, control = admin_page
    select_tab(page, "승인 대기")
    page.get_by_role("button", name="사용자 상세: 검토자 43", exact=True).click()
    page.get_by_role("button", name="승인", exact=True).click()
    control["hold_approval"] = True
    page.get_by_role("button", name="승인 확정", exact=True).click()
    expect(page.get_by_role("button", name="승인 확정", exact=True)).to_be_disabled()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_be_visible()
    assert len(control["mutations"]) == 1
    control["deferred"].pop().fulfill(json={"notification": {"status": "QUEUED"}})
    expect(page.get_by_role("dialog")).to_have_count(0)


def test_mail_states_retry_limit_and_no_inbox_claim(admin_page):
    page, control = admin_page
    select_tab(page, "메일 기록")
    expect(page.locator(".admin-rows")).not_to_contain_text("Invalid Date")
    expect(page.locator(".admin-summary")).to_contain_text("최근 100건 범위")
    page.get_by_label("전송 상태", exact=True).select_option("SMTP_ACCEPTED")
    page.get_by_role("button", name="메일 상세: 검토자 01", exact=True).click()
    expect(page.get_by_role("dialog")).to_contain_text("수신함 도착")
    expect(page.get_by_role("dialog")).to_contain_text("확인되지 않음")
    expect(page.get_by_role("button", name="메일 발송 재시도", exact=True)).to_have_count(0)
    page.keyboard.press("Escape")
    page.get_by_label("전송 상태", exact=True).select_option("UNKNOWN")
    page.get_by_role("button", name="메일 상세: 검토자 01", exact=True).click()
    expect(page.get_by_role("button", name="메일 발송 재시도", exact=True)).to_have_count(0)
    page.keyboard.press("Escape")
    page.get_by_label("전송 상태", exact=True).select_option("FAILED")
    page.get_by_role("button", name="메일 상세: 검토자 01", exact=True).nth(1).click()
    expect(page.get_by_role("button", name="메일 발송 재시도", exact=True)).to_have_count(0)
    page.keyboard.press("Escape")
    page.get_by_role("button", name="메일 상세: 검토자 01", exact=True).nth(0).click()
    page.get_by_role("button", name="메일 발송 재시도", exact=True).click()
    expect(page.locator(".admin-feedback")).to_contain_text("메일 재시도 요청 · 발송 대기")
    assert control["mutations"] == [("/api/admin/notifications/m1/retry", None)]


def test_grouped_workbench_preserves_all_tools_and_selected_case(admin_page):
    page, _ = admin_page
    page.get_by_role("button", name="작업 공간", exact=True).click()
    page.evaluate("""() => {
        state.project = {id:'p', name:'합성 사건', external_ai_policy:'LOCAL_ONLY'};
        document.getElementById('emptyState').hidden = true;
        document.getElementById('projectView').hidden = false;
        renderProject();
        state.run = {id:'retained-run', state:'VERIFYING'};
    }""")
    groups = page.locator("#workspaceGroups")
    expect(groups.get_by_role("button")).to_have_count(3)
    for group, tools in (
        ("자료", ("documents", "compare")),
        ("검증·검토", ("ai-verification", "review", "issues", "timeline", "calculations", "search")),
        ("보고서", ("reports", "audit")),
    ):
        groups.get_by_role("button", name=group, exact=True).click()
        assert page.locator(".tabs [data-tab]:visible").count() == len(tools)
        for tab in tools:
            page.locator(f'.tabs [data-tab="{tab}"]').click()
            expect(page.locator(f'[data-panel="{tab}"]')).to_be_visible()
    groups.get_by_role("button", name="검증·검토", exact=True).click()
    expect(page.locator('[data-panel="search"]')).to_be_visible()
    page.locator("#adminNavigation").click()
    expect(page.locator("#projectView")).to_be_hidden()
    page.get_by_role("button", name="작업 공간", exact=True).click()
    expect(page.locator("#projectTitle")).to_have_text("합성 사건")
    expect(page.locator('[data-panel="search"]')).to_be_visible()
    assert page.evaluate("state.run.id") == "retained-run"
    page.set_viewport_size({"width": 390, "height": 844})
    assert groups.evaluate("el => el.scrollWidth <= el.clientWidth")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_readonly_account_dialog_says_close_not_cancel(admin_page):
    page, _ = admin_page
    page.locator("#accountButton").click()
    dialog = page.get_by_role("dialog", name="계정·접근 권한", exact=True)
    expect(dialog.get_by_role("button", name="취소", exact=True)).to_have_count(0)
    expect(dialog.locator(".dialog-footer").get_by_role("button", name="닫기", exact=True)).to_be_visible()


@pytest.mark.parametrize("width,height", [(1440, 960), (768, 1024), (390, 844), (320, 740)])
def test_responsive_tables_and_detail_panel(admin_page, tmp_path, width, height):
    page, _ = admin_page
    page.set_viewport_size({"width": width, "height": height})
    for name in ("사용자", "승인 대기", "이용 통계", "메일 기록"):
        select_tab(page, name)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.locator(".admin-table").evaluate("el => el.scrollWidth <= el.clientWidth")
    select_tab(page, "승인 대기")
    page.get_by_role("button", name="사용자 상세: 검토자 43", exact=True).click()
    dialog = page.get_by_role("dialog")
    assert dialog.evaluate("el => el.scrollWidth <= el.clientWidth && el.getBoundingClientRect().right <= innerWidth")
    page.screenshot(path=str(tmp_path / f"admin-detail-{width}.png"), full_page=True)
