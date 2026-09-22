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
