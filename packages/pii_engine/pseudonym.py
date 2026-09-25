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
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from filelock import FileLock

from packages.common.config import data_dir
from .key_provider import KeyProvider, EnvKeyProvider, default_key_provider

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


@dataclass
class PseudonymStore:
    """실명-가명 매핑. 본문 DB와 분리된 파일/저장소에 암호화 보관한다."""

    project_id: str
    key_provider: KeyProvider = field(default_factory=default_key_provider)
    root: Path = field(default_factory=lambda: data_dir() / "pii_vault")
    _mapping: Dict[str, str] = field(default_factory=dict, init=False)
    _originals: Dict[str, str] = field(default_factory=dict, init=False)
    _counters: Dict[str, int] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.project_id):
            raise ValueError("Invalid project identifier")
        self.root.mkdir(parents=True, exist_ok=True)
        self._load()

    # The old stream cipher is retained only to read authenticated legacy vaults.
    def _keystream(self, length: int, nonce: bytes, key: bytes) -> bytes:
        out = bytearray()
        counter = 0
        while len(out) < length:
            out.extend(hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
            counter += 1
        return bytes(out[:length])

    def _encrypt(self, plaintext: bytes) -> bytes:
        nonce = os.urandom(12)
        material = self.key_provider.encryption_key(self.project_id)
        body = AESGCM(material.key).encrypt(nonce, plaintext, self._aad(material.metadata))
        envelope = {"version": 3, "key": material.metadata,
                    "nonce": base64.b64encode(nonce).decode("ascii"),
                    "ciphertext": base64.b64encode(body).decode("ascii")}
        # Retain the AES vault family prefix, with an unambiguous envelope marker.
        return b"ACAS2:K3:" + base64.b64encode(json.dumps(envelope, sort_keys=True).encode("utf-8"))

    def _aad(self, metadata: dict) -> bytes:
        return json.dumps({"version": 3, "project_id": self.project_id, "key": metadata},
                          sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _decrypt(self, blob: bytes) -> bytes:
        if blob.startswith(b"ACAS2:K3:"):
            envelope = json.loads(base64.b64decode(blob[9:], validate=True))
            if set(envelope) != {"version", "key", "nonce", "ciphertext"} or envelope["version"] != 3:
                raise ValueError("Invalid vault envelope")
            nonce = base64.b64decode(envelope["nonce"], validate=True)
            if len(nonce) != 12:
                raise ValueError("Invalid vault nonce")
            key = self.key_provider.decryption_key(envelope["key"], self.project_id)
            return AESGCM(key).decrypt(nonce, base64.b64decode(envelope["ciphertext"], validate=True), self._aad(envelope["key"]))
        if blob.startswith(b"ACAS2:"):
            raw = base64.b64decode(blob[6:], validate=True)
            for legacy in self.key_provider.legacy_keys():
                try:
                    return AESGCM(hashlib.sha256(legacy).digest()).decrypt(raw[:12], raw[12:], self.project_id.encode())
                except Exception:
                    continue
            raise ValueError("No matching legacy vault key")
        raw = base64.b64decode(blob, validate=True)
        if len(raw) < 48:
            raise ValueError("Invalid legacy vault")
        nonce, tag, body = raw[:16], raw[16:48], raw[48:]
        for legacy in self.key_provider.legacy_keys():
            expected = hmac.new(legacy, nonce + body, hashlib.sha256).digest()
            if hmac.compare_digest(tag, expected):
                stream = self._keystream(len(body), nonce, legacy)
                return bytes(a ^ b for a, b in zip(body, stream))
        raise ValueError("PII vault 무결성 검증 실패")

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
            raise ValueError("PII vault 무결성 검증 실패: 원본을 보존하고 처리를 중단합니다") from None

    def save(self) -> None:
        with FileLock(str(self._path) + ".lock"):
            self._load()
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        payload = json.dumps(
            {"mapping": self._mapping, "counters": self._counters, "originals": self._originals},
            ensure_ascii=False,
        ).encode("utf-8")
        fd, temporary = tempfile.mkstemp(dir=self.root, suffix=".vault.tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(self._encrypt(payload))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    # -- 매핑 -------------------------------------------------------------
    @staticmethod
    def _norm(kind: str, value: str) -> str:
        return f"{kind}:{' '.join(value.split()).lower()}"

    def pseudonym_for(self, kind: str, value: str) -> str:
        with FileLock(str(self._path) + ".lock"):
            self._load()
            return self._pseudonym_for_unlocked(kind, value)

    def _pseudonym_for_unlocked(self, kind: str, value: str) -> str:
        key = self._norm(kind, value)
        if key in self._mapping:
            return self._mapping[key]
        prefix = KIND_PREFIX.get(kind, kind)
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        token = f"{prefix}_{self._counters[prefix]:03d}"
        self._mapping[key] = token
        self._originals[token] = value
        self._save_unlocked()
        return token

    def original_for(self, token: str) -> Optional[str]:
        return self._originals.get(token)

    @property
    def size(self) -> int:
        return len(self._mapping)
