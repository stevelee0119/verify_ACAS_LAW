"""The progress screen distinguishes slow work from a lost polling connection."""
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def test_progress_staleness_reconnect_and_layout(tmp_path):
    static = ROOT / "apps/web/static"
    files = {f"/static/{path.relative_to(static).as_posix()}": path for path in static.rglob("*") if path.is_file()}
    files["/"] = ROOT / "apps/web/index.html"
    disconnected = [True]
    protection_requests = []
    run = {"id": "run", "state": "VERIFYING", "stage_message": "검토의견서.docx 법률 인용 확인 12/46건",
           "progress": 0.52, "document_ids": [], "started_at": "2026-09-21T00:00:00"}

    def respond(route):
        path = urlsplit(route.request.url).path
        if path in files:
            route.fulfill(path=str(files[path]))
        elif path == "/api/health":
            route.fulfill(json={"status": "ok", "version": "0.5.0"})
        elif path == "/api/verification-runs/run":
            if disconnected[0]:
                route.abort("failed")
            else:
                route.fulfill(json=run)
        elif path == "/api/verification-runs/run/session":
            protection_requests.append(route.request.method)
            route.fulfill(json={"protected": True})
        else:
            route.fulfill(status=401, json={"detail": "Login required"})

    with sync_playwright() as playwright:
        options = {"headless": True}
        if os.getenv("LV_TEST_BROWSER_CHANNEL"):
            options["channel"] = os.environ["LV_TEST_BROWSER_CHANNEL"]
        browser = playwright.chromium.launch(**options)
        try:
            for width, height in ((1440, 960), (390, 844)):
                protection_requests.clear()
                page = browser.new_page(viewport={"width": width, "height": height})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/*", respond)
                page.goto("http://progress.test/")
                expect(page.get_by_role("dialog", name="작업 공간 로그인")).to_be_visible()
                page.keyboard.press("Escape")
                page.evaluate("""run => {
                    state.project = {id:'project', name:'진행 상태 검토', external_ai_policy:'LOCAL_ONLY'};
                    state.run = run;
                    document.getElementById('emptyState').hidden = true;
                    document.getElementById('projectView').hidden = false;
                    renderProject();
                }""", run)
                notice = page.locator("#progressNotice")
                expect(notice).to_be_hidden()
                # 화면 진입 직후 걸린 조회가 실패하면 그 오류 문구가 먼저 뜬다.
                # 여기서 보려는 것은 "진행 정보가 멈춰 있을 때의 안내"이므로
                # 조회 상태를 비우고 검사한다. 조회 실패 문구는 아래에서 따로 본다.
                # generation을 올려야 이미 날아간 조회의 응답도 무시된다.
                # clearTimeout은 다음 예약만 취소하고 진행 중인 요청은 못 막는다.
                page.evaluate("state.generation += 1; clearTimeout(state.timer); "
                              "state.pollError = null; state.progressSeen.at -= 65000; "
                              "renderProgressNotice()")
                expect(notice).to_contain_text("변경되지 않았습니다")
                disconnected[0] = True
                page.evaluate("pollRun(state.generation)")
                expect(notice).to_contain_text("자동으로 다시 연결", timeout=5000)
                assert notice.evaluate("el => el.scrollWidth <= el.clientWidth")
                page.screenshot(path=str(tmp_path / f"progress-reconnect-{width}.png"), full_page=True)
                disconnected[0] = False
                expect(notice).to_contain_text("서버 응답은 정상", timeout=5000)
                assert protection_requests == ["POST"]
                page.evaluate("pollRun(state.generation, 0)")
                page.wait_for_timeout(250)
                assert protection_requests == ["POST"]
                page.evaluate("state.run.progress = .6; renderProject(); clearTimeout(state.timer)")
                expect(notice).to_be_hidden()
                expect(page.locator("#progressPercent")).to_have_text("60%")
                expect(page.get_by_role("button", name="검증 취소", exact=True)).to_be_enabled()
                page.evaluate("""() => {
                    state.run.stage_message = '검토의견서.docx 법률 인용 확인 46/46건 · 지연된 인용 다시 확인 12/18건';
                    renderProject();
                }""")
                expect(page.locator("#progressText")).to_contain_text("지연된 인용 다시 확인")
                assert page.locator("#progress").evaluate("el => el.scrollWidth <= el.clientWidth")
                page.screenshot(path=str(tmp_path / f"progress-source-recovery-{width}.png"), full_page=True)
                assert not errors
                page.close()
        finally:
            browser.close()


def test_expired_poll_pauses_and_explicit_login_resumes_same_results(tmp_path):
    static = ROOT / "apps/web/static"
    files = {f"/static/{path.relative_to(static).as_posix()}": path for path in static.rglob("*") if path.is_file()}
    files["/"] = ROOT / "apps/web/index.html"
    run = {"id": "run", "state": "COMPLETED", "stage_message": "검증 완료", "progress": 1,
           "document_ids": [], "unverified_items": [], "started_at": "2026-09-21T00:00:00"}

    with sync_playwright() as playwright:
        options = {"headless": True}
        if os.getenv("LV_TEST_BROWSER_CHANNEL"):
            options["channel"] = os.environ["LV_TEST_BROWSER_CHANNEL"]
        browser = playwright.chromium.launch(**options)
        try:
            for width, height in ((1440, 960), (390, 844)):
                for expiry_stage in ("status", "result"):
                    expired, requests, errors = [True], [], []

                    def respond(route):
                        path = urlsplit(route.request.url).path
                        requests.append((route.request.method, path))
                        if path in files:
                            route.fulfill(path=str(files[path]))
                        elif path == "/api/health":
                            route.fulfill(json={"status": "ok", "version": "0.5.0"})
                        elif path == "/api/auth/login":
                            expired[0] = False
                            route.fulfill(json={"user": {"id": "member"}})
                        elif path == "/api/verification-runs/run" and expiry_stage == "result":
                            route.fulfill(json=run)
                        elif expired[0]:
                            route.fulfill(status=401, json={"detail": "Session expired"})
                        elif path == "/api/identity/me":
                            route.fulfill(json={"user_id": "member", "role": "MEMBER", "authentication": "password"})
                        elif path == "/api/verification-runs/run":
                            route.fulfill(json=run)
                        elif path == "/api/verification-runs/run/result":
                            route.fulfill(json={"test_marker": "same-run", "documents": []})
                        elif "/case-matrix" in path:
                            route.fulfill(body="null", content_type="application/json")
                        else:
                            route.fulfill(json=[])

                    page = browser.new_page(viewport={"width": width, "height": height})
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.route("**/*", respond)
                    page.goto("http://progress.test/")
                    login = page.get_by_role("dialog", name="작업 공간 로그인")
                    expect(login).to_be_visible()
                    page.keyboard.press("Escape")
                    page.evaluate("""run => {
                        state.project = {id:'project', name:'장시간 분석', external_ai_policy:'LOCAL_ONLY'};
                        state.run = {...run, state:'VERIFYING', progress:.57};
                        document.getElementById('emptyState').hidden = true;
                        document.getElementById('projectView').hidden = false;
                        renderProject(); pollRun(state.generation);
                    }""", run)
                    notice = page.locator("#progressNotice")
                    expect(notice).to_contain_text("결과 조회를 잠시 멈췄습니다", timeout=7000)
                    # 고정 문구만 보이면 원인이 만료인지 쿠키 문제인지 알 수 없다.
                    # 모바일에서는 개발자도구로 응답을 볼 수 없으므로 서버 사유를 함께 보인다.
                    expect(notice).to_contain_text("Session expired")
                    expect(login).to_have_count(0)
                    count = len(requests)
                    page.wait_for_timeout(3200)
                    assert len(requests) == count
                    assert notice.evaluate("el => el.scrollWidth <= el.clientWidth")
                    page.screenshot(path=str(tmp_path / f"session-paused-{expiry_stage}-{width}.png"), full_page=True)
                    await_login = page.get_by_role("button", name="다시 로그인", exact=True)
                    await_login.click()
                    expect(login).to_be_visible()
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(1800)
                    expect(login).to_have_count(0)
                    expect(await_login).to_be_visible()
                    await_login.click()
                    login.locator('input[name="email"]').fill("member@example.invalid")
                    login.locator('input[name="password"]').fill("synthetic-password")
                    login.get_by_role("button", name="로그인", exact=True).click()
                    expect(login).to_have_count(0)
                    page.wait_for_function("state.result.test_marker === 'same-run' && !state.pollError")
                    expect(page.locator("#progress")).to_be_hidden()
                    assert page.evaluate("state.run.id") == "run"
                    assert page.evaluate("state.project.id") == "project"
                    assert [path for method, path in requests if method == "POST"] == ["/api/auth/login"]
                    assert not errors
                    page.close()
        finally:
            browser.close()
