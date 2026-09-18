"""Versioned AES keys and optional AWS KMS envelope encryption.

No network or credential discovery occurs unless aws-kms is explicitly selected.
Only key identifiers and wrapped data keys belong in vault metadata.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from filelock import FileLock

from packages.common.config import data_dir


def _decode(value: str) -> bytes:
    try:
        key = base64.b64decode(value, validate=True)
        if len(key) != 32:
            raise ValueError()
        return key
    except Exception:
        raise ValueError("Vault keys must be base64-encoded 256-bit keys") from None


def _keyring(raw: dict) -> tuple[str, dict[str, bytes]]:
    try:
        active = raw["active"]
        keys = {key_id: _decode(value) for key_id, value in raw["keys"].items()}
        if not keys or active not in keys or any(not isinstance(k, str) or not k or len(k) > 200 for k in keys):
            raise ValueError()
        return active, keys
    except Exception:
        raise ValueError("Invalid vault keyring") from None


@dataclass(frozen=True)
class KeyMaterial:
    key: bytes = field(repr=False)
    metadata: dict


class KeyProvider(ABC):
    """get_key compatibility supports existing custom providers and legacy vaults."""

    @abstractmethod
    def get_key(self) -> bytes: ...

    def encryption_key(self, project_id: str) -> KeyMaterial:
        return KeyMaterial(hashlib.sha256(self.get_key()).digest(), {"provider": "legacy", "key_id": "legacy"})

    def decryption_key(self, metadata: dict, project_id: str) -> bytes:
        if metadata != {"provider": "legacy", "key_id": "legacy"}:
            raise ValueError("Unknown vault key")
        return hashlib.sha256(self.get_key()).digest()

    def legacy_keys(self) -> tuple[bytes, ...]:
        return (self.get_key(),)


class EnvKeyProvider(KeyProvider):
    def __init__(self, keys: dict[str, bytes] | None = None, active: str | None = None):
        self._legacy = ()
        if keys is None:
            encoded = os.getenv("LV_VAULT_KEYS")
            secret = os.getenv("LV_PSEUDONYM_SECRET")
            if encoded:
                try:
                    active, keys = _keyring({"active": os.environ["LV_VAULT_ACTIVE_KEY_ID"], "keys": json.loads(encoded)})
                except Exception:
                    raise ValueError("Invalid environment vault key configuration") from None
            elif secret:
                if secret == "dev-only-not-for-production":
                    raise ValueError("The public development vault secret is not a valid encryption key")
                self._legacy = (secret.encode(),)
                active, keys = "legacy-env", {"legacy-env": hashlib.sha256(secret.encode()).digest()}
            else:
                raise ValueError("Environment vault keys are not configured")
        if not active or active not in keys or any(len(key) != 32 for key in keys.values()):
            raise ValueError("Invalid environment vault keyring")
        self._active, self._keys = active, dict(keys)

    def get_key(self) -> bytes:
        return self._legacy[0] if self._legacy else self._keys[self._active]

    def encryption_key(self, project_id: str) -> KeyMaterial:
        return KeyMaterial(self._keys[self._active], {"provider": "env", "key_id": self._active})

    def decryption_key(self, metadata: dict, project_id: str) -> bytes:
        if set(metadata) != {"provider", "key_id"} or metadata["provider"] != "env" or metadata["key_id"] not in self._keys:
            raise ValueError("Unknown vault key")
        return self._keys[metadata["key_id"]]

    def legacy_keys(self) -> tuple[bytes, ...]:
        explicit = os.getenv("LV_VAULT_LEGACY_SECRET")
        return self._legacy + tuple(self._keys.values()) + ((explicit.encode(),) if explicit else ())


class FileKeyProvider(KeyProvider):
    def __init__(self, path: Path, *, create: bool = False):
        self.path = Path(path)
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with FileLock(str(self.path) + ".lock"):
                if not self.path.exists():
                    key_id = "key_" + secrets.token_hex(8)
                    self._write({"active": key_id, "keys": {key_id: base64.b64encode(os.urandom(32)).decode("ascii")}})
        self._read()

    def _read(self):
        try:
            if os.name != "nt" and self.path.stat().st_mode & 0o077:
                raise ValueError()
            return _keyring(json.loads(self.path.read_text(encoding="utf-8")))
        except Exception:
            raise ValueError("Vault key file is missing, invalid, or not private") from None

    def _write(self, raw):
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, suffix=".key.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(raw, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def rotate(self) -> str:
        """Retain old decrypt keys. Re-save each vault before retiring any key."""
        with FileLock(str(self.path) + ".lock"):
            _, keys = self._read()
            key_id = "key_" + secrets.token_hex(8)
            keys[key_id] = os.urandom(32)
            self._write({"active": key_id, "keys": {k: base64.b64encode(v).decode("ascii") for k, v in keys.items()}})
            return key_id

    def get_key(self) -> bytes:
        active, keys = self._read()
        return keys[active]

    def encryption_key(self, project_id: str) -> KeyMaterial:
        active, keys = self._read()
        return KeyMaterial(keys[active], {"provider": "file", "key_id": active})

    def decryption_key(self, metadata: dict, project_id: str) -> bytes:
        _, keys = self._read()
        if set(metadata) != {"provider", "key_id"} or metadata["provider"] != "file" or metadata["key_id"] not in keys:
            raise ValueError("Unknown vault key")
        return keys[metadata["key_id"]]

    def legacy_keys(self) -> tuple[bytes, ...]:
        secret = os.getenv("LV_VAULT_LEGACY_SECRET")
        return (secret.encode(),) if secret else ()


class AWSKMSKeyProvider(KeyProvider):
    def __init__(self, key_id: str, *, decrypt_key_ids=(), region: str | None = None, client=None):
        self.key_id = key_id
        self.allowed = frozenset({key_id, *decrypt_key_ids})
        if any(not key.startswith("arn:") or ":kms:" not in key or ":key/" not in key for key in self.allowed):
            raise ValueError("KMS keys must be explicit key ARNs (not aliases)")
        self.region, self._client = region, client

    @property
    def client(self):
        if self._client is None:
            try:
                import boto3
                from botocore.config import Config
                self._client = boto3.client("kms", region_name=self.region, config=Config(
                    connect_timeout=5, read_timeout=10, retries={"max_attempts": 2}))
            except Exception:
                raise ValueError("AWS KMS provider is unavailable; install/configure optional boto3") from None
        return self._client

    @staticmethod
    def _context(project_id):
        return {"application": "ACAS_LAW", "purpose": "pseudonym-vault", "project_id": project_id}

    def get_key(self) -> bytes:
        raise ValueError("KMS requires a project-bound envelope")

    def encryption_key(self, project_id: str) -> KeyMaterial:
        try:
            result = self.client.generate_data_key(KeyId=self.key_id, KeySpec="AES_256", EncryptionContext=self._context(project_id))
            if result["KeyId"] != self.key_id or len(result["Plaintext"]) != 32:
                raise ValueError()
            return KeyMaterial(result["Plaintext"], {"provider": "aws-kms", "key_id": result["KeyId"],
                "wrapped_key": base64.b64encode(result["CiphertextBlob"]).decode("ascii")})
        except Exception:
            raise ValueError("KMS data-key generation failed") from None

    def decryption_key(self, metadata: dict, project_id: str) -> bytes:
        try:
            if set(metadata) != {"provider", "key_id", "wrapped_key"} or metadata["provider"] != "aws-kms" or metadata["key_id"] not in self.allowed:
                raise ValueError()
            blob = base64.b64decode(metadata["wrapped_key"], validate=True)
            if not blob or len(blob) > 6144:
                raise ValueError()
            result = self.client.decrypt(KeyId=metadata["key_id"], CiphertextBlob=blob,
                EncryptionAlgorithm="SYMMETRIC_DEFAULT", EncryptionContext=self._context(project_id))
            if result["KeyId"] != metadata["key_id"] or len(result["Plaintext"]) != 32:
                raise ValueError()
            return result["Plaintext"]
        except Exception:
            raise ValueError("KMS data-key decryption failed") from None

    def legacy_keys(self) -> tuple[bytes, ...]:
        secret = os.getenv("LV_VAULT_LEGACY_SECRET")
        return (secret.encode(),) if secret else ()


def default_key_provider() -> KeyProvider:
    explicit = os.getenv("LV_VAULT_KEY_PROVIDER")
    provider = explicit or ("env" if os.getenv("LV_VAULT_KEYS") or os.getenv("LV_PSEUDONYM_SECRET") else "file")
    if provider == "env":
        return EnvKeyProvider()
    if provider == "file":
        path = os.getenv("LV_VAULT_KEY_FILE")
        return FileKeyProvider(Path(path) if path else data_dir() / "secrets" / "vault-keys.json", create=not path)
    if provider == "aws-kms":
        return AWSKMSKeyProvider(os.getenv("LV_VAULT_KMS_KEY_ID", ""),
            decrypt_key_ids=tuple(k.strip() for k in os.getenv("LV_VAULT_KMS_DECRYPT_KEY_IDS", "").split(",") if k.strip()),
            region=os.getenv("LV_VAULT_KMS_REGION"))
    raise ValueError("Unknown vault key provider")
