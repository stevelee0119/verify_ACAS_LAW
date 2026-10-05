"""[평가 에이전트 소관] F1 화면 보호 시험 — T2r 화면 도달, T6a 배정표 API 권한 (2026-10-04, F1 독립 감사 G8 결함 반영).

T1~T5(test_f1_protected.py)는 데이터 수준만 본다. 독립 감사(Codex, d73a8ea)에서
- P1: AI 진단 유형(STYLE_SHIFT 등) finding이 AI 탭에도 '확인할 항목'에도 제목이 보이지 않는 정보 손실
- P2: 다중 사용자 모드에서 /api/finding-categories가 로그인한 사용자에게 403
이 재현됐는데 T1~T5가 잡지 못했다. 이 파일이 그 두 가지를 고정한다.

- T2r: AI·보안 탭의 세 범주(AI 진단·인젝션·보안)와 검토 범주 finding을 하나씩 공급했을 때, 모든 finding의 제목이
  'AI 작성·보안 진단' 탭이나 '확인할 항목' 탭 중 한 곳에 보인다(정보 손실 0). 입력은 지어낸 합성 값이다.
- T6a: 다중 사용자 모드에서 관리자·구성원·열람자가 배정표 API를 읽을 수 있고(200), 비로그인은 막힌다(401).
배정표 모듈이 없는 커밋(F1 이전)에서는 건너뛴다.
"""
from __future__ import annotations

import importlib
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))


def _category_map():
    try:
        return importlib.import_module("packages.common.finding_category_map")
    except ModuleNotFoundError:
        pytest.skip("F1 배정표 모듈이 없는 커밋(F1 이전)")


# --------------------------------------------------------------------------- T2r ---
SYNTHETIC = [
    # (finding_type, 제목) — 범주마다 하나. 제목은 화면에서 찾을 고유 문자열이다.
    ("STYLE_SHIFT", "합성 문체 급변 신호 표시 확인", "MEDIUM"),
    ("PROMPT_INJECTION_SUSPECTED", "합성 인젝션 의심 표시 확인", "HIGH"),
    ("AUTHORSHIP_METADATA_LEAK", "합성 메타데이터 노출 표시 확인", "MEDIUM"),
    ("CASE_NOT_FOUND", "합성 판례 미발견 표시 확인", "HIGH"),
]


def _findings():
    out = []
    for i, (ftype, title, severity) in enumerate(SYNTHETIC):
        out.append({"id": f"f{i}", "finding_id": f"f{i}", "finding_type": ftype, "type": ftype, "title": title,
                    "detail": "합성 시험 입력", "severity": severity, "status": "FLAGGED",
                    "review_status": "NEEDS_REVIEW", "document_id": "d1", "page": 1, "engine": "synthetic"})
    return out


def test_t2r_every_finding_title_is_visible_in_ai_tab_or_review_tab():
    mod = _category_map()
    sync_api = pytest.importorskip("playwright.sync_api")
    from frontend_helpers import privacy_notice_mock_payload, select_first_project

    categories = {ft.value: cat.value for ft, cat in mod.FINDING_CATEGORY_MAP.items()}
    tabs = {ft.value: mod.CATEGORY_TO_TAB[cat].value for ft, cat in mod.FINDING_CATEGORY_MAP.items()}
    # 입력이 실제로 세 AI·보안 범주와 검토 탭을 모두 덮는지 먼저 확인한다(배정이 바뀌면 시험 입력을 다시 고른다).
    assert {categories[t] for t, _, _ in SYNTHETIC[:3]} == {"AI_DIAGNOSIS", "INJECTION_DEFENSE", "SECURITY_CARD"}
    assert tabs[SYNTHETIC[3][0]] == "REVIEW_ITEMS"

    project = {"id": "p1", "name": "화면 도달 시험", "can_delete": True, "document_count": 1,
               "external_ai_policy": "MASKED", "scope_revision": 0, "requested_issues": []}
    run = {"id": "r1", "project_id": "p1", "state": "COMPLETED", "progress": 1, "stage_message": "",
           "document_ids": ["d1"], "scores": {}, "unverified_items": [], "errors": [], "unavailable_sources": [],
           "input_snapshot": {"scope_revision": 0}, "started_at": "2026-10-04T00:00:00"}
    result = {"status": "COMPLETED", "documents": [{"id": "d1", "document_id": "d1", "filename": "합성.pdf",
              "quarantined": False, "findings": _findings(), "ai_hallucination_table": [],
              "ai_detector_result": {"verdict": "UNCERTAIN", "score": 0.5, "reasons": []}}]}
    static_dir = ROOT / "apps/web/static"
    files = {f"/static/{p.relative_to(static_dir).as_posix()}": p for p in static_dir.rglob("*") if p.is_file()}
    files["/"] = ROOT / "apps/web/index.html"

    def handler(route):
        path = urlsplit(route.request.url).path
        if path in files:
            return route.fulfill(path=str(files[path]))
        replies = {
            "/api/health": {"status": "ok"},
            "/api/auth/me": {"user_id": "u", "email": "t@example.com", "display_name": "검토자", "role": "ADMIN",
                             "authentication": "local"},
            "/api/identity/me": {"user_id": "u", "email": "t@example.com", "display_name": "검토자", "role": "ADMIN",
                                 "authentication": "local"},
            "/api/verification-runs": {"active_count": 0, "runs": []},
            "/api/projects": [project], "/api/projects/p1": project,
            "/api/projects/p1/documents": [{"id": "d1", "filename": "합성.pdf", "included_in_verification": True}],
            "/api/projects/p1/runs": [run], "/api/projects/p1/findings": _findings(),
            "/api/projects/p1/audit": {"events": []}, "/api/privacy-notice": privacy_notice_mock_payload(),
            "/api/finding-categories": {"categories": categories, "tabs": tabs, "counts": {}},
        }
        if path in replies:
            return route.fulfill(json=replies[path])
        if path.endswith(("/result", "/results")):
            return route.fulfill(json=result)
        if path.endswith("/case-matrix"):
            return route.fulfill(body="null", content_type="application/json")
        return route.fulfill(status=200, json=[])

    launch = {"headless": True}
    if os.environ.get("LV_TEST_BROWSER_CHANNEL"):
        launch["channel"] = os.environ["LV_TEST_BROWSER_CHANNEL"]
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(**launch)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.route("**/*", handler)
        page.goto("http://reach.test/")
        select_first_project(page)
        page.wait_for_function("state.findings && state.findings.length === %d" % len(SYNTHETIC))
        page.wait_for_function("state.findingCategories && !state.findingCategories.error")

        def unseen():
            out = []
            for _, title, _ in SYNTHETIC:
                seen = False
                for tab in ("ai-verification", "review"):
                    page.evaluate(f"switchTab('{tab}')")
                    if page.locator(f"[data-panel='{tab}']").get_by_text(title).count() > 0:
                        seen = True
                        break
                if not seen:
                    out.append(title)
            return out

        # state가 채워진 뒤에도 화면 그리기는 다른 요청(/issues 등)을 기다린 다음에 일어난다(loadResults).
        # 그 사이에 한 번만 세면 느린 실행 환경에서 거짓 실패가 난다(2026-10-04 CI, 응답 지연으로 재현).
        # 단언은 그대로 두고, 제한 시간 안에서 다시 센다.
        deadline = time.monotonic() + 15
        missing = unseen()
        while missing and time.monotonic() < deadline:
            page.wait_for_timeout(250)
            missing = unseen()
        browser.close()
    assert not missing, f"어느 탭에도 제목이 보이지 않는 finding(정보 손실): {missing}"


# --------------------------------------------------------------------------- T6a ---
@pytest.fixture()
def multi_user_client(tmp_path, monkeypatch):
    _category_map()
    from fastapi.testclient import TestClient
    from apps.api import db
    from packages.common.config import reset_settings

    monkeypatch.setenv("LV_DATABASE_URL", "sqlite:///" + str(tmp_path / "t6a.db"))
    monkeypatch.setenv("LV_AUTH_MODE", "multi-user")
    monkeypatch.setenv("LV_PSEUDONYM_SECRET", "test-secret")
    for name in ("LV_ACCESS_TOKEN", "LV_BOOTSTRAP_ADMIN_EMAIL", "LV_BOOTSTRAP_ADMIN_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    reset_settings()
    db.reset_engine()
    db.init_db()
    from apps.api.main import create_app
    yield TestClient(create_app(), base_url="https://testserver")
    db.get_engine().dispose()
    db.reset_engine()
    reset_settings()


def test_t6a_finding_categories_readable_by_every_signed_in_role(multi_user_client):
    from apps.api.auth import ROLE_ADMIN, ROLE_MEMBER, ROLE_VIEWER, hash_password, issue_session
    from apps.api.db import Organization, User, get_session_factory

    session = get_session_factory()()
    org = Organization(name="합성 기관")
    session.add(org)
    session.flush()
    tokens = {}
    for role in (ROLE_ADMIN, ROLE_MEMBER, ROLE_VIEWER):
        user = User(email=f"{role.lower()}-{uuid.uuid4().hex[:8]}@example.com", display_name=role, role=role,
                    organization_id=org.id, password_hash=hash_password("test-password-1234"))
        session.add(user)
        session.flush()
        tokens[role] = issue_session(session, user)
    session.commit()
    session.close()

    assert multi_user_client.get("/api/finding-categories").status_code == 401
    for role, token in tokens.items():
        response = multi_user_client.get("/api/finding-categories", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200, (role, response.status_code, response.text[:200])
        body = response.json()
        assert len(body["tabs"]) == len(body["categories"]) == len(_category_map().FINDING_CATEGORY_MAP)
