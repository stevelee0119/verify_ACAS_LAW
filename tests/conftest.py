"""테스트 공통 fixture.

외부 네트워크를 사용하지 않고 내부 Mirror만으로 결정론적 검증을 수행한다.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def isolated_environment():
    """테스트는 임시 데이터 디렉터리와 네트워크 비활성 상태로 실행한다."""
    tmp = tempfile.mkdtemp(prefix="lv-test-")
    os.environ["LV_DATA_DIR"] = tmp
    os.environ["LV_ALLOW_NETWORK"] = "0"
    # LV_TEST_DATABASE_URL이 있으면 그 DB로 테스트한다(PostgreSQL 검증용).
    os.environ["LV_DATABASE_URL"] = os.getenv("LV_TEST_DATABASE_URL") or f"sqlite:///{tmp}/test.db"
    os.environ["LV_STORAGE_ROOT"] = f"{tmp}/storage"
    os.environ["LV_PSEUDONYM_SECRET"] = "test-secret"
    os.environ.pop("LV_LAW_GO_KR_OC", None)
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("GEMINI_API_KEY", None)

    from packages.common import config, storage

    config.reset_settings()
    storage.reset_storage()
    yield tmp


@pytest.fixture()
def registry():
    """테스트용 내부 Mirror를 사용하는 Source Registry."""
    from packages.source_adapters import SourceRegistry
    from packages.source_adapters.local_mirror import LocalLegalMirror

    reg = SourceRegistry()
    reg.mirror = LocalLegalMirror(FIXTURE_DIR / "legal_mirror")
    reg.legal[0].mirror = reg.mirror
    return reg


@pytest.fixture()
def tmp_docs(tmp_path):
    return tmp_path
