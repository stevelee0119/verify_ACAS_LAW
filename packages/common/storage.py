"""Object Storage Adapter (제3.2/제23장).

MVP는 Local Filesystem Adapter를 사용하고, S3/MinIO는 동일 인터페이스로 교체한다.
제15.1장에 따라 원본은 Immutable Original 영역에 저장하며 덮어쓰지 않는다.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Optional

from .config import get_settings


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ObjectStorage(ABC):
    @abstractmethod
    def put_original(self, key: str, data: bytes) -> str: ...

    @abstractmethod
    def put_derivative(self, key: str, data: bytes) -> str: ...

    @abstractmethod
    def get(self, storage_key: str) -> bytes: ...

    @abstractmethod
    def path(self, storage_key: str) -> Path: ...

    @abstractmethod
    def exists(self, storage_key: str) -> bool: ...


class LocalObjectStorage(ObjectStorage):
    """originals/ 는 쓰기 후 읽기 전용(0o444)으로 고정한다."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root or get_settings().storage_root)
        (self.root / "originals").mkdir(parents=True, exist_ok=True)
        (self.root / "derivatives").mkdir(parents=True, exist_ok=True)

    # -- 내부 -------------------------------------------------------------
    def _abs(self, storage_key: str) -> Path:
        p = (self.root / storage_key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("path traversal detected")  # 제21.1장
        return p

    # -- 인터페이스 -------------------------------------------------------
    def put_original(self, key: str, data: bytes) -> str:
        storage_key = f"originals/{key}"
        p = self._abs(storage_key)
        if p.exists():
            # 제15.1장 Immutable Original: 동일 키 재기록 금지
            return storage_key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        try:
            os.chmod(p, 0o444)
        except OSError:  # pragma: no cover - 플랫폼 의존
            pass
        return storage_key

    def put_derivative(self, key: str, data: bytes) -> str:
        storage_key = f"derivatives/{key}"
        p = self._abs(storage_key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return storage_key

    def get(self, storage_key: str) -> bytes:
        return self._abs(storage_key).read_bytes()

    def path(self, storage_key: str) -> Path:
        return self._abs(storage_key)

    def exists(self, storage_key: str) -> bool:
        return self._abs(storage_key).exists()

    def copy_to_temp(self, storage_key: str, suffix: str = "") -> Path:
        """파서가 파일 경로를 요구할 때 원본을 건드리지 않도록 사본을 만든다."""
        src = self._abs(storage_key)
        tmp_dir = self.root / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        dst = tmp_dir / f"{Path(storage_key).name}{suffix}"
        shutil.copyfile(src, dst)
        return dst


_storage: Optional[ObjectStorage] = None


def get_storage() -> ObjectStorage:
    global _storage
    if _storage is None:
        base: ObjectStorage = LocalObjectStorage()
        # 암호화는 저장 계층을 감싼다. 상위 코드는 차이를 알 필요가 없다.
        _storage = EncryptedObjectStorage(base) if storage_encryption_enabled() else base
    return _storage


def reset_storage() -> None:  # 테스트용
    global _storage
    _storage = None


# ---------------------------------------------------------------------------
# 저장 시 암호화
# ---------------------------------------------------------------------------
STORAGE_CONTEXT = "storage"
PLAINTEXT_CACHE = "plaintext-cache"


class StorageKeyConfigurationError(RuntimeError):
    """저장소 암호화 키 설정이 잘못되었다.

    ValueError로 두면 상위의 포괄적 예외 처리가 이것을 인증 오류로 바꿔
    표시한다. 실제로 그런 일이 있었고, 사용자는 키 설정이 아니라 로그인을
    들여다보게 된다. 원인을 가리키는 고유한 예외로 분리한다.
    """


class EncryptedObjectStorage(ObjectStorage):
    """원본과 파생물을 봉투 암호화해 보관한다(제23장).

    디스크 스냅샷·백업본이 유출되어도 키가 없으면 사건자료를 읽을 수 없게 한다.
    키는 환경변수 또는 KMS에서 오며 자료 디스크에 두지 않는다.

    한계를 분명히 해 둔다. 파서는 파일 경로를 요구하므로 path()는 평문을
    임시 디렉터리에 풀어 놓는다. 처리 중에는 평문이 디스크에 존재하며,
    이 구간은 암호화로 가려지지 않는다. purge_plaintext_cache()로 지운다.

    암호화를 켜기 전에 저장된 평문 객체도 계속 읽을 수 있다. 봉투 표지가
    없으면 평문으로 취급한다.
    """

    def __init__(self, base: ObjectStorage, *, key_provider=None,
                 cache_root: Optional[Path] = None) -> None:
        self.base = base
        if key_provider is None:
            from packages.pii_engine.key_provider import default_key_provider

            try:
                key_provider = default_key_provider()
            except Exception as exc:
                raise StorageKeyConfigurationError(
                    "저장 시 암호화가 켜져 있으나 키 설정이 올바르지 않습니다. "
                    "LV_VAULT_KEY_PROVIDER=env이면 LV_VAULT_KEYS(키 ID -> base64 32바이트 JSON)와 "
                    "LV_VAULT_ACTIVE_KEY_ID가 함께 있어야 합니다. 키를 확인할 수 없으면 "
                    "LV_STORAGE_ENCRYPTION을 끄십시오. 이미 암호화된 자료는 올바른 키가 있어야 읽힙니다. "
                    f"({type(exc).__name__}: {exc})"
                ) from exc
        self.key_provider = key_provider
        root = cache_root or (Path(get_settings().storage_root) / PLAINTEXT_CACHE)
        self.cache_root = Path(root)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.cache_root, 0o700)

    # -- 내부 -------------------------------------------------------------
    @staticmethod
    def _project_of(storage_key: str) -> str:
        """originals/{project_id}/... 에서 사건 식별자를 뽑는다.

        사건마다 다른 키를 쓰기 위한 것이다. 형식이 다르면 빈 값으로 두고
        전역 키를 쓴다. 키를 못 고르느니 덜 세분화된 키가 낫다.
        """
        parts = [p for p in storage_key.split("/") if p]
        return parts[1] if len(parts) >= 3 else ""

    def _seal(self, storage_key: str, data: bytes) -> bytes:
        from .envelope import seal

        return seal(data, key_provider=self.key_provider,
                    project_id=self._project_of(storage_key), context=STORAGE_CONTEXT)

    def _unseal(self, storage_key: str, data: bytes) -> bytes:
        from .envelope import unseal

        return unseal(data, key_provider=self.key_provider,
                      project_id=self._project_of(storage_key), context=STORAGE_CONTEXT)

    # -- 인터페이스 -------------------------------------------------------
    def put_original(self, key: str, data: bytes) -> str:
        storage_key = f"originals/{key}"
        if self.base.exists(storage_key):
            return storage_key  # 제15.1장 Immutable Original
        return self.base.put_original(key, self._seal(storage_key, data))

    def put_derivative(self, key: str, data: bytes) -> str:
        return self.base.put_derivative(key, self._seal(f"derivatives/{key}", data))

    def get(self, storage_key: str) -> bytes:
        return self._unseal(storage_key, self.base.get(storage_key))

    def exists(self, storage_key: str) -> bool:
        return self.base.exists(storage_key)

    def path(self, storage_key: str) -> Path:
        """파서가 요구하는 지역 경로. 평문을 임시로 풀어 놓는다."""
        target = (self.cache_root / storage_key).resolve()
        if not str(target).startswith(str(self.cache_root.resolve())):
            raise ValueError("path traversal detected")
        if target.exists():
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        partial.write_bytes(self.get(storage_key))
        os.chmod(partial, 0o600)
        partial.replace(target)  # 덜 풀린 파일을 원본으로 읽지 않게 한다
        return target

    def copy_to_temp(self, storage_key: str, suffix: str = "") -> Path:
        source = self.path(storage_key)
        tmp_dir = self.cache_root / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        destination = tmp_dir / f"{Path(storage_key).name}{suffix}"
        shutil.copyfile(source, destination)
        os.chmod(destination, 0o600)
        return destination

    def purge_plaintext_cache(self) -> int:
        """풀어 둔 평문을 지운다. 처리 후 호출한다."""
        removed = 0
        for item in sorted(self.cache_root.rglob("*"), reverse=True):
            try:
                if item.is_file():
                    item.unlink()
                    removed += 1
                elif item.is_dir():
                    item.rmdir()
            except OSError:  # pragma: no cover - 사용 중인 파일
                continue
        return removed


def storage_encryption_enabled() -> bool:
    """LV_STORAGE_ENCRYPTION. 기본값은 꺼짐이다.

    켜 두고 키를 잃으면 자료를 복구할 수 없으므로 기본으로 켜지 않는다.
    실제 사건자료를 다루는 배포는 명시적으로 켜고 키를 따로 보관해야 한다.
    """
    return (os.getenv("LV_STORAGE_ENCRYPTION") or "").strip().lower() in ("1", "true", "yes", "on")


def verify_storage_encryption_config() -> None:
    """기동 시 암호화 키 설정을 확인한다.

    첫 업로드 때 실패하면 원인이 화면에 드러나지 않는다. 배포 직후 로그에서
    바로 보이도록 기동 시점에 확인한다.
    """
    if not storage_encryption_enabled():
        return
    from packages.pii_engine.key_provider import default_key_provider

    try:
        default_key_provider()
    except Exception as exc:
        raise StorageKeyConfigurationError(
            "저장 시 암호화가 켜져 있으나 키 공급자를 만들 수 없습니다. "
            f"({type(exc).__name__}: {exc})"
        ) from exc
