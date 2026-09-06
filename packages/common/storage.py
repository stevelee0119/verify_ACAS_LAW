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
        _storage = LocalObjectStorage()
    return _storage


def reset_storage() -> None:  # 테스트용
    global _storage
    _storage = None
