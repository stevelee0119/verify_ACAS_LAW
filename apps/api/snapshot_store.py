"""보고서 고정본(스냅샷)의 큰 부분을 DB 밖에 내용 주소로 보관한다.

보고서마다 검증 결과 전체(engine_result)와 사전 점검(preflight)을 고정본에 복사해 DB에 두었다.
6개 문서 사건에서 보고서 한 건이 약 2.3MB(압축 저장 약 0.48MB)였고, 검증 결과 자체(0.25MB)보다
컸다. 초안을 여러 번 만들거나 확정하면 같은 검증 결과가 그만큼 반복 저장되어 DB 저장 공간이 먼저 찼다.

- 큰 부분은 gzip으로 압축해 파일 저장소(영구 디스크)의 `derivatives/{project}/snapshots/{sha256}.json.gz`에
  둔다. 이름이 내용 해시이므로 같은 내용은 한 번만 저장된다(초안·확정본이 같은 검증 결과를 공유).
- DB에는 `{"$snapshot_blob": 저장 키, "sha256": 해시}` 참조만 남긴다.
- 읽을 때 해시를 다시 확인한다. 무결성 해시(snapshot_hash)는 예전처럼 펼친 전체 고정본에 대해 계산한다.
- 영구 삭제는 프로젝트 파일 폴더를 지우므로 함께 지워진다. 예전 형식(전부 DB에 있는 고정본)도 그대로 읽는다.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from typing import Any, Dict


BLOB_KEYS = ("engine_result", "preflight")
MARKER = "$snapshot_blob"


class SnapshotBlobMissing(LookupError):
    """참조한 고정본 파일이 없거나 내용이 해시와 다르다."""


def _canonical(value: Any) -> bytes:
    # packages.report_engine.snapshot.canonical_hash와 같은 직렬화라 해시가 일치한다.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def pack(storage, project_id: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """DB에 저장할 형태. 큰 부분은 파일로 옮기고 참조로 바꾼다."""
    stored = dict(snapshot)
    for key in BLOB_KEYS:
        if key not in snapshot:
            continue
        data = _canonical(snapshot[key])
        digest = hashlib.sha256(data).hexdigest()
        target = f"derivatives/{project_id}/snapshots/{digest}.json.gz"
        if not storage.exists(target):
            storage.put_derivative(f"{project_id}/snapshots/{digest}.json.gz", gzip.compress(data, compresslevel=6))
        stored[key] = {MARKER: target, "sha256": digest}
    return stored


def unpack(storage, stored: Dict[str, Any]) -> Dict[str, Any]:
    """참조를 펼친 전체 고정본."""
    snapshot = dict(stored or {})
    for key in BLOB_KEYS:
        ref = snapshot.get(key)
        if not (isinstance(ref, dict) and MARKER in ref):
            continue
        try:
            data = gzip.decompress(storage.get(ref[MARKER]))
        except Exception as exc:  # 없음·손상·복호화 실패(암호화 저장소)를 모두 '확인 불가'로 본다
            raise SnapshotBlobMissing(key) from exc
        if hashlib.sha256(data).hexdigest() != ref.get("sha256"):
            raise SnapshotBlobMissing(key)
        snapshot[key] = json.loads(data)
    return snapshot
