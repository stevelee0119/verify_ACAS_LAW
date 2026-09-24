"""저장 시 암호화 (제23장).

디스크 스냅샷·백업본이 유출되어도 키가 없으면 사건자료를 읽을 수 없어야 한다.
동시에 chain of custody(제15.1장)의 원본 불변성과 해시 의미는 그대로 유지한다.
"""
from __future__ import annotations

import pytest

from packages.common.envelope import is_sealed, seal, unseal
from packages.common.storage import (
    EncryptedObjectStorage,
    LocalObjectStorage,
    sha256_bytes,
    sha256_file,
    storage_encryption_enabled,
)

CASE = b"%PDF-1.7 \xec\x9b\x90\xea\xb3\xa0\xeb\x8a\x94 2024. 3. 15. \xea\xb3\x84\xec\x95\xbd\xec\x9d\x84 \xec\xb2\xb4\xea\xb2\xb0\xed\x96\x88\xeb\x8b\xa4"


@pytest.fixture()
def keys(monkeypatch):
    from packages.pii_engine.key_provider import default_key_provider

    monkeypatch.setenv("LV_VAULT_KEY_PROVIDER", "env")
    monkeypatch.setenv("LV_PSEUDONYM_SECRET", "test-vault-secret-for-storage")
    return default_key_provider()


@pytest.fixture()
def storage(tmp_path, keys):
    base = LocalObjectStorage(root=tmp_path / "store")
    return EncryptedObjectStorage(base, key_provider=keys, cache_root=tmp_path / "cache")


def test_original_is_unreadable_on_disk(storage):
    """디스크에 남는 것은 암호문이어야 한다."""
    key = storage.put_original("prj_1/abc.pdf", CASE)
    on_disk = storage.base.path(key).read_bytes()
    assert is_sealed(on_disk)
    assert b"%PDF" not in on_disk
    assert b"\xea\xb3\x84\xec\x95\xbd" not in on_disk  # '계약'


def test_round_trip_returns_the_exact_bytes(storage):
    key = storage.put_original("prj_1/abc.pdf", CASE)
    assert storage.get(key) == CASE


def test_chain_of_custody_hash_is_the_plaintext_hash(storage):
    """제15.1장. 원본 해시의 의미가 암호화로 달라지면 안 된다."""
    key = storage.put_original("prj_1/abc.pdf", CASE)
    assert sha256_file(storage.path(key)) == sha256_bytes(CASE)


def test_original_is_still_immutable(storage):
    """같은 키에 다시 써도 처음 원본이 유지된다."""
    key = storage.put_original("prj_1/abc.pdf", CASE)
    storage.put_original("prj_1/abc.pdf", b"replaced")
    assert storage.get(key) == CASE


def test_objects_written_before_encryption_stay_readable(tmp_path, keys):
    """암호화를 켜기 전 자료를 못 읽게 되면 켤 수 없다."""
    base = LocalObjectStorage(root=tmp_path / "store")
    plain_key = base.put_original("prj_1/old.pdf", CASE)
    storage = EncryptedObjectStorage(base, key_provider=keys, cache_root=tmp_path / "cache")
    assert storage.get(plain_key) == CASE
    assert sha256_file(storage.path(plain_key)) == sha256_bytes(CASE)


def test_another_case_key_cannot_open_the_file(storage, keys):
    """사건별로 다른 키를 쓴다. 한 사건의 키로 다른 사건을 열 수 없다."""
    key = storage.put_original("prj_1/abc.pdf", CASE)
    sealed = storage.base.path(key).read_bytes()
    with pytest.raises(Exception):
        unseal(sealed, key_provider=keys, project_id="prj_2", context="storage")


def test_a_pseudonym_ciphertext_cannot_be_swapped_in(storage, keys):
    """용도가 다른 암호문을 저장소 자리에 끼워 넣지 못한다."""
    other = seal(CASE, key_provider=keys, project_id="prj_1", context="pseudonym")
    with pytest.raises(ValueError):
        unseal(other, key_provider=keys, project_id="prj_1", context="storage")


@pytest.mark.parametrize("key", ["originals/../../etc/passwd", "../escape"])
def test_path_traversal_is_rejected(storage, key):
    with pytest.raises(ValueError):
        storage.path(key)


def test_plaintext_cache_is_private_and_purgeable(storage):
    """처리 중 풀어 둔 평문은 지울 수 있어야 한다."""
    key = storage.put_original("prj_1/abc.pdf", CASE)
    path = storage.path(key)
    assert path.read_bytes() == CASE
    assert path.stat().st_mode & 0o077 == 0, "평문 사본이 다른 사용자에게 열려 있다"
    assert storage.purge_plaintext_cache() >= 1
    assert not path.exists()


def test_derivatives_are_encrypted_too(storage):
    """보고서 산출물에도 사건 내용이 담긴다."""
    key = storage.put_derivative("prj_1/rpt_1/abc.json", CASE)
    assert is_sealed(storage.base.path(key).read_bytes())
    assert storage.get(key) == CASE


# --- 기본값과 진단 -----------------------------------------------------------
def test_encryption_is_off_unless_explicitly_enabled(monkeypatch):
    """켜 두고 키를 잃으면 자료를 복구할 수 없다. 기본으로 켜지 않는다."""
    monkeypatch.delenv("LV_STORAGE_ENCRYPTION", raising=False)
    assert storage_encryption_enabled() is False
    monkeypatch.setenv("LV_STORAGE_ENCRYPTION", "on")
    assert storage_encryption_enabled() is True


def test_get_storage_wraps_only_when_enabled(monkeypatch, tmp_path):
    from packages.common import storage as module
    from packages.common.config import reset_settings

    monkeypatch.setenv("LV_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LV_PSEUDONYM_SECRET", "test-vault-secret-for-storage")
    monkeypatch.delenv("LV_STORAGE_ENCRYPTION", raising=False)
    reset_settings()
    module.reset_storage()
    assert isinstance(module.get_storage(), LocalObjectStorage)

    monkeypatch.setenv("LV_STORAGE_ENCRYPTION", "on")
    reset_settings()
    module.reset_storage()
    assert isinstance(module.get_storage(), EncryptedObjectStorage)
    module.reset_storage()
    reset_settings()


# --- 설정 오류를 인증 오류로 표시하지 않는다 ---------------------------------
@pytest.fixture()
def broken_vault(monkeypatch, tmp_path):
    from packages.common import storage as module
    from packages.common.config import reset_settings

    monkeypatch.setenv("LV_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LV_STORAGE_ENCRYPTION", "on")
    monkeypatch.setenv("LV_VAULT_KEY_PROVIDER", "env")
    monkeypatch.setenv("LV_VAULT_KEYS", '{"k1":"not-a-valid-key"}')
    monkeypatch.delenv("LV_VAULT_ACTIVE_KEY_ID", raising=False)
    reset_settings()
    module.reset_storage()
    yield module
    module.reset_storage()
    reset_settings()


def test_bad_vault_configuration_names_the_real_cause(broken_vault):
    """종전에는 이 오류가 "Invalid authentication configuration"으로 표시됐다.

    원인은 저장소 키인데 사용자는 로그인을 들여다보게 된다. 실제로 그렇게
    시간을 썼다. 예외를 분리해 원인을 가리키게 한다.
    """
    from packages.common.storage import StorageKeyConfigurationError

    with pytest.raises(StorageKeyConfigurationError) as excinfo:
        broken_vault.get_storage()
    message = str(excinfo.value)
    assert "LV_VAULT_ACTIVE_KEY_ID" in message
    assert "LV_STORAGE_ENCRYPTION" in message, "끄는 방법을 알려야 한다"
    assert "authentication" not in message.lower()


def test_bad_vault_configuration_is_not_a_value_error(broken_vault):
    """ValueError로 두면 상위의 포괄적 처리가 인증 오류로 바꿔 버린다."""
    from packages.common.storage import StorageKeyConfigurationError

    assert not issubclass(StorageKeyConfigurationError, ValueError)


def test_startup_check_fails_before_the_first_upload(broken_vault):
    """첫 업로드 때가 아니라 기동 시점에 드러나야 한다."""
    from packages.common.storage import StorageKeyConfigurationError, verify_storage_encryption_config

    with pytest.raises(StorageKeyConfigurationError):
        verify_storage_encryption_config()


def test_startup_check_is_silent_when_encryption_is_off(monkeypatch, tmp_path):
    from packages.common.config import reset_settings
    from packages.common.storage import verify_storage_encryption_config

    monkeypatch.delenv("LV_STORAGE_ENCRYPTION", raising=False)
    monkeypatch.setenv("LV_DATA_DIR", str(tmp_path))
    reset_settings()
    verify_storage_encryption_config()
    reset_settings()


def test_bad_key_configuration_does_not_prevent_the_service_from_starting(monkeypatch, tmp_path):
    """설정 오류가 서비스 전체를 내리면 보고하려던 문제보다 나쁘다.

    실제로 그렇게 배포되어 502가 났다. 기동을 막으면 로그인도, 기존 사건자료
    조회도, 원인을 알려 줄 진단 화면도 함께 막힌다. 크게 남기고 진단에 실어
    알리되 서비스는 떠 있어야 한다. 자료를 다루는 경로는 계속 거부한다.
    """
    import apps.api.db as db
    from apps.api.capabilities import runtime_capabilities
    from apps.api.main import create_app
    from packages.common.storage import (StorageKeyConfigurationError, get_storage,
                                          reset_storage)

    monkeypatch.setenv("LV_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LV_DATABASE_URL", f"sqlite:///{tmp_path}/boot.db")
    monkeypatch.setenv("LV_STORAGE_ENCRYPTION", "on")
    monkeypatch.setenv("LV_VAULT_KEY_PROVIDER", "env")
    # 꺾쇠를 포함한 값. 사용자가 실제로 입력했던 형태다.
    monkeypatch.setenv("LV_VAULT_KEYS", '{"k1":"<' + "A" * 43 + '=>"}')
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_SessionLocal", None)
    reset_storage()
    try:
        app = create_app()
        assert app.routes, "설정 오류로 기동이 막히면 안 된다"

        state = runtime_capabilities()["storage_encryption"]
        assert state["configured"] is False
        assert "LV_VAULT_KEYS" in state["note"], "무엇을 고쳐야 하는지 화면이 말해야 한다"
        assert "authentication" not in state["note"].lower()

        # 자료를 다루는 경로는 계속 거부한다. 평문으로 조용히 되돌아가면 안 된다.
        with pytest.raises(StorageKeyConfigurationError):
            get_storage()
    finally:
        db._engine = db._SessionLocal = None
        reset_storage()


def test_project_purge_removes_sealed_objects_and_plaintext_copies_of_one_project(storage):
    """영구 삭제는 그 프로젝트의 봉인 원본·파생물·평문 사본만 지우고 다른 프로젝트는 건드리지 않는다."""
    key = storage.put_original("prj_a/aaaa.pdf", b"case A")
    storage.put_derivative("prj_a/report/r.json", b"{}")
    other = storage.put_original("prj_b/bbbb.pdf", b"case B")
    plaintext = storage.path(key)  # 파서용으로 풀어 둔 평문 사본
    assert plaintext.exists()
    assert storage.delete_project_files("prj_a") == 2
    assert not storage.exists(key) and not plaintext.exists()
    assert storage.get(other) == b"case B"
    for bad in ("../prj_b", "prj_a/../prj_b", ""):
        with pytest.raises(ValueError):
            storage.delete_project_files(bad)
    assert storage.exists(other)
