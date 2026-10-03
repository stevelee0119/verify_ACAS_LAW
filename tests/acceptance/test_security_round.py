"""보안 보강 라운드(7차 R4) 보호 시험 — CodeQL 경고 분류에서 확인한 실제 결함(TK-35·36·37·38)을 고정한다(평가 에이전트).

원칙: 미해결은 strict xfail로, **고쳐도 지켜야 하는 동작(의미 불변)** 은 일반 시험(통과)으로 둔다. 구현 중 XPASS가 나면 평가 측이 표시를 지운다.
시간 예산 시험은 **별도 프로세스 + 제한 시간**으로 돌려 Windows에서도 쓸 수 있다(SIGALRM을 쓰지 않는다).
입력은 평가 측이 지은 합성값이며 사건 값이 아니다. 자세한 근거: docs/handoff/TK-35~38, GITHUB_ACCESS.md 6·8절.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _finishes_within(code: str, seconds: float) -> bool:
    try:
        subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, '.')\n" + code], cwd=REPO,
                       timeout=seconds, check=True, capture_output=True)
        return True
    except subprocess.TimeoutExpired:
        return False


# ------------------------------------------------------------------ TK-38 A: PDF 정규식 지수 증가 ---
@pytest.mark.xfail(strict=True, reason="TK-38 A: SINGLE_GLYPH_SHOW_RE가 위치 지정 연산자 사이 공백에서 지수 증가 — 조작된 PDF 105바이트가 20초 넘게 처리를 멈춘다(CodeQL py/redos)")
@pytest.mark.parametrize("repeats", [14, 18, 24])
def test_pdf_zero_width_marker_check_finishes_quickly_on_adversarial_content(repeats):
    code = ("from packages.document_engine.pdf_parser import _is_line_break_marker\n"
            f"data = b'>> BDC' + b' 0 Tm  ' * {repeats} + b'X'\n"
            "_is_line_break_marker('\\u200b', data, 0)\n")
    assert _finishes_within(code, 10), f"위치 지정 {repeats}회 입력이 10초 안에 끝나지 않았다"


def test_single_glyph_show_pattern_keeps_its_meaning():
    """의미 불변 대조: 한 글리프 표시 뒤 EMC이면 맞고, 아니면 맞지 않는다(고쳐도 같아야 한다)."""
    from packages.document_engine.pdf_parser import SINGLE_GLYPH_SHOW_RE as pattern
    hit = pattern.match(b" /F4 12 Tf 1 0 0 1 10 20 Tm <0003> Tj EMC")
    assert hit is not None and hit.group("hex") == b"0003"
    assert pattern.match(b" /F4 12 Tf 1 0 0 1 10 20 Tm <0003><0004> Tj EMC") is None
    assert pattern.match(b" 1 0 0 1 10 20 Tm (a) Tj ET") is None


# ------------------------------------------------------------------ TK-38 B: 금액 정규식 ---
@pytest.mark.xfail(strict=True, reason="TK-38 B: (?:원정|원|정)+$가 지수 증가('원정'*24 4초 이상). 현재 호출부는 도달하지 않으나 패턴 자체가 위험")
def test_korean_amount_suffix_strip_is_linear():
    code = ("from packages.claim_engine.korean_amount import parse_korean_amount\n"
            "parse_korean_amount('이억' + '원정' * 26 + '만')\n")
    assert _finishes_within(code, 5)


def test_korean_amount_parse_keeps_its_meaning():
    from packages.claim_engine.korean_amount import parse_korean_amount
    assert parse_korean_amount("일금 오백만원정") == Decimal(5_000_000)
    assert parse_korean_amount("삼억 오천만 원") == Decimal(350_000_000)
    assert parse_korean_amount("원정") is None


# ------------------------------------------------------------------ TK-35: 저장소 경로·권한 ---
def _store(tmp_path):
    from packages.common.storage import LocalObjectStorage
    (tmp_path / "storage2").mkdir()
    return LocalObjectStorage(tmp_path / "storage")


@pytest.mark.xfail(strict=True, reason="TK-35: _abs가 경로를 접두 문자열로 비교해 형제 디렉터리(storage2)를 막지 못한다(CodeQL py/path-injection)")
@pytest.mark.parametrize("key", ["../storage2/secret.txt", "originals/../../storage2/secret.txt"])
def test_storage_rejects_a_sibling_directory_sharing_the_root_prefix(tmp_path, key):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.path(key)


def test_storage_still_rejects_plain_traversal_and_accepts_normal_keys(tmp_path):
    """의미 불변 대조: 루트 밖 일반 이탈은 막고 정상 키는 루트 안으로 해석한다."""
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.path("../outside.txt")
    assert (tmp_path / "storage").resolve() in store.path("originals/p1/a.pdf").parents


@pytest.mark.xfail(strict=True, reason="TK-35: PROJECT_ID_RE.match+$가 끝 줄바꿈이 든 프로젝트 ID를 통과시킨다(fullmatch여야 함, py/log-injection 3건과 같은 원인)")
def test_project_id_with_trailing_newline_is_rejected(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.delete_project_files("abc\n")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 파일 권한 시험")
@pytest.mark.xfail(strict=True, reason="TK-35: 원본을 0o444(모든 사용자 읽기)로 고정한다 — 소유자만 읽는 0o400이어야 한다(CodeQL py/overly-permissive-file)")
def test_stored_original_is_not_readable_by_other_users(tmp_path):
    store = _store(tmp_path)
    key = store.put_original("p1/abc.pdf", b"%PDF-1.4 synthetic")
    mode = stat.S_IMODE(os.stat(store.path(key)).st_mode)
    assert mode & 0o077 == 0, f"그룹·다른 사용자 권한이 남아 있다: {oct(mode)}"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 파일 권한 시험")
def test_stored_original_stays_write_protected(tmp_path):
    """의미 불변 대조: 권한을 줄여도 원본은 쓰기 금지(불변)여야 한다."""
    store = _store(tmp_path)
    key = store.put_original("p1/abc.pdf", b"%PDF-1.4 synthetic")
    assert stat.S_IMODE(os.stat(store.path(key)).st_mode) & 0o222 == 0


# ------------------------------------------------------------------ TK-36: 예외 문구 응답 ---
@pytest.mark.xfail(strict=True, reason="TK-36: 키 설정 오류 예외 문구(환경변수 이름 포함)가 503 본문에 그대로 실린다(CodeQL py/stack-trace-exposure)")
def test_storage_key_error_response_does_not_echo_configuration_details(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from apps.api import access
    from packages.common.storage import StorageKeyConfigurationError

    for name in ("LV_ACCESS_TOKEN", "LV_OIDC_ISSUER", "LV_OIDC_AUDIENCE", "LV_OIDC_JWKS_URL", "LV_OIDC_ALGORITHMS",
                 "LV_PUBLIC_ORIGIN", "LV_TRUSTED_PROXY_IPS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LV_AUTH_MODE", "multi-user")

    def boom(_request):
        raise StorageKeyConfigurationError("LV_VAULT_KEYS와 LV_VAULT_ACTIVE_KEY_ID가 필요하다 (ValueError: Invalid vault keyring)")

    monkeypatch.setattr(access, "_authenticate", boom)
    app = FastAPI()
    app.middleware("http")(access.workspace_access)
    app.add_api_route("/api/anything", lambda: {"ok": True}, methods=["GET"])
    with TestClient(app, base_url="https://testserver") as client:
        response = client.get("/api/anything")
    assert response.status_code == 503
    assert "LV_" not in response.text and "Invalid vault keyring" not in response.text


# ------------------------------------------------------------------ TK-37: 관리자 화면 탭 검증 ---
ADMIN_JS = (REPO / "apps" / "web" / "static" / "admin.js").read_text(encoding="utf-8")


@pytest.mark.xfail(strict=True, reason="TK-37: 탭 이름을 `tabs[next] ?`(참 판정)로 검증해 #admin/__proto__ 같은 해시가 통과한다(CodeQL js/prototype-polluting-assignment 13건). 정적 점검 — 브라우저 동작 시험은 착수 시 평가 측이 둔다")
def test_admin_tab_lookup_ignores_prototype_keys():
    assert not re.search(r"tabs\[next\]\s*\?", ADMIN_JS), "객체 리터럴의 참 판정으로 탭 이름을 검증한다"
    assert re.search(r"Object\.hasOwn\(tabs|hasOwnProperty\.call\(tabs|new Map\(", ADMIN_JS), "자기 속성 검사나 Map을 쓰지 않는다"


@pytest.mark.xfail(strict=True, reason="TK-37: CSV 내려받기 주소의 year에 숫자 변환이 없다(js/xss-through-dom 경미 하드닝)")
def test_admin_csv_download_url_coerces_year_to_a_number():
    assert "Number(year)" in ADMIN_JS
