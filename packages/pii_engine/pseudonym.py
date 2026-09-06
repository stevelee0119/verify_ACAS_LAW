"""제8장 Project-stable Pseudonym.

동일 프로젝트에서는 모든 문서에서 동일 pseudonym을 유지한다.
실명-가명 Mapping Table은 본문 DB와 분리해 암호화 저장하며,
기관형에서는 KMS/HSM/Vault 계열과 연계 가능하도록 인터페이스를 분리한다.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from packages.common.config import DATA_DIR, get_settings

KIND_PREFIX = {
    "PERSON": "PERSON",
    "COMPANY": "COMPANY",
    "RRN": "RRN",
    "PHONE": "PHONE",
    "EMAIL": "EMAIL",
    "ADDRESS": "ADDRESS",
    "ACCOUNT": "ACCOUNT",
    "MILITARY_ID": "MILID",
    "PASSPORT": "PASSPORT",
    "DOB": "DOB",
}


class KeyProvider(ABC):
    """운영환경에서는 Secrets Manager·Vault·KMS 구현으로 교체한다(제21.2장)."""

    @abstractmethod
    def get_key(self) -> bytes: ...


class EnvKeyProvider(KeyProvider):
    def get_key(self) -> bytes:
        return get_settings().pseudonym_secret.encode("utf-8")


@dataclass
class PseudonymStore:
    """실명-가명 매핑. 본문 DB와 분리된 파일/저장소에 암호화 보관한다."""

    project_id: str
    key_provider: KeyProvider = field(default_factory=EnvKeyProvider)
    root: Path = field(default_factory=lambda: DATA_DIR / "pii_vault")
    _mapping: Dict[str, str] = field(default_factory=dict, init=False)
    _originals: Dict[str, str] = field(default_factory=dict, init=False)
    _counters: Dict[str, int] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._load()

    # -- 암호화 (XOR-with-HMAC-keystream; 운영에서는 KMS/AES-GCM으로 교체) ----
    def _keystream(self, length: int, nonce: bytes) -> bytes:
        key = self.key_provider.get_key()
        out = bytearray()
        counter = 0
        while len(out) < length:
            out.extend(hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
            counter += 1
        return bytes(out[:length])

    def _encrypt(self, plaintext: bytes) -> bytes:
        nonce = os.urandom(16)
        stream = self._keystream(len(plaintext), nonce)
        body = bytes(a ^ b for a, b in zip(plaintext, stream))
        tag = hmac.new(self.key_provider.get_key(), nonce + body, hashlib.sha256).digest()
        return base64.b64encode(nonce + tag + body)

    def _decrypt(self, blob: bytes) -> bytes:
        raw = base64.b64decode(blob)
        nonce, tag, body = raw[:16], raw[16:48], raw[48:]
        expected = hmac.new(self.key_provider.get_key(), nonce + body, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ValueError("PII vault 무결성 검증 실패")
        stream = self._keystream(len(body), nonce)
        return bytes(a ^ b for a, b in zip(body, stream))

    @property
    def _path(self) -> Path:
        return self.root / f"{self.project_id}.vault"

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._decrypt(self._path.read_bytes()).decode("utf-8"))
            self._mapping = data.get("mapping", {})
            self._counters = data.get("counters", {})
            self._originals = data.get("originals", {})
        except Exception:
            # 손상된 vault는 덮어쓰지 않고 빈 상태로 시작한다
            self._mapping, self._counters, self._originals = {}, {}, {}

    def save(self) -> None:
        payload = json.dumps(
            {"mapping": self._mapping, "counters": self._counters, "originals": self._originals},
            ensure_ascii=False,
        ).encode("utf-8")
        self._path.write_bytes(self._encrypt(payload))

    # -- 매핑 -------------------------------------------------------------
    @staticmethod
    def _norm(kind: str, value: str) -> str:
        return f"{kind}:{' '.join(value.split()).lower()}"

    def pseudonym_for(self, kind: str, value: str) -> str:
        key = self._norm(kind, value)
        if key in self._mapping:
            return self._mapping[key]
        prefix = KIND_PREFIX.get(kind, kind)
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        token = f"{prefix}_{self._counters[prefix]:03d}"
        self._mapping[key] = token
        self._originals[token] = value
        return token

    def original_for(self, token: str) -> Optional[str]:
        return self._originals.get(token)

    @property
    def size(self) -> int:
        return len(self._mapping)

    def as_table(self) -> Dict[str, str]:
        """감사·사용자 확인용 매핑 표. 접근 통제 하에서만 노출한다."""
        return dict(self._originals)
