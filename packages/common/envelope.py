"""저장 대상 바이트를 봉투 암호화한다(제23장).

가명 매핑에 쓰던 봉투 형식을 임의의 바이트에도 쓸 수 있게 분리했다. 암호는
새로 만들지 않고 pii_engine의 KeyProvider(환경변수·파일·AWS KMS)를 그대로
쓴다. 키 회전과 버전 관리가 이미 그쪽에 있다.

context를 AAD에 넣어 용도를 묶는다. 저장소 암호문을 가명 매핑 자리에 끼워
넣는 식의 치환을 막기 위한 것이다.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PREFIX = b"ACASENV1:"
VERSION = 1


def _aad(context: str, project_id: str, metadata: Dict[str, Any]) -> bytes:
    return json.dumps({"version": VERSION, "context": context, "project_id": project_id,
                       "key": metadata}, sort_keys=True, separators=(",", ":")).encode("utf-8")


def seal(plaintext: bytes, *, key_provider, project_id: str, context: str) -> bytes:
    """봉투 암호화. 결과는 자기 자신을 해독하는 데 필요한 정보를 담는다."""
    material = key_provider.encryption_key(project_id)
    nonce = os.urandom(12)
    body = AESGCM(material.key).encrypt(nonce, plaintext, _aad(context, project_id, material.metadata))
    envelope = {"version": VERSION, "context": context, "key": material.metadata,
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "ciphertext": base64.b64encode(body).decode("ascii")}
    return PREFIX + base64.b64encode(json.dumps(envelope, sort_keys=True).encode("utf-8"))


def is_sealed(blob: bytes) -> bool:
    return blob.startswith(PREFIX)


def unseal(blob: bytes, *, key_provider, project_id: str, context: str) -> bytes:
    """봉투를 연다. 봉인되지 않은 바이트는 그대로 돌려준다.

    암호화를 켜기 전에 저장된 자료를 계속 읽어야 하므로, 평문을 오류로
    만들지 않는다. 대신 봉인 여부는 is_sealed로 구분할 수 있게 둔다.
    """
    if not is_sealed(blob):
        return blob
    envelope = json.loads(base64.b64decode(blob[len(PREFIX):], validate=True))
    if set(envelope) != {"version", "context", "key", "nonce", "ciphertext"}:
        raise ValueError("저장소 봉투 형식이 올바르지 않다")
    if envelope["version"] != VERSION:
        raise ValueError(f"지원하지 않는 봉투 버전이다: {envelope['version']}")
    if envelope["context"] != context:
        # 다른 용도의 암호문을 이 자리에 끼워 넣는 것을 막는다.
        raise ValueError("저장소 봉투의 용도가 일치하지 않는다")
    nonce = base64.b64decode(envelope["nonce"], validate=True)
    if len(nonce) != 12:
        raise ValueError("저장소 봉투의 nonce 길이가 올바르지 않다")
    key = key_provider.decryption_key(envelope["key"], project_id)
    return AESGCM(key).decrypt(nonce, base64.b64decode(envelope["ciphertext"], validate=True),
                               _aad(context, project_id, envelope["key"]))
