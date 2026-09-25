"""보고서 공통 JSON 직렬화(v4 P8).

- to_jsonable: 열거형·날짜·Decimal·집합·dataclass·to_dict 객체를 JSON 값으로 바꾼다. 예전의
  json.loads(json.dumps(..., default=str)) 왕복과 같은 결과를 한 번의 순회로 만든다.
- 값 하나를 바꾸지 못해도 보고서 전체를 버리지 않는다. 그 자리에 오류 표시를 두고 경로를 errors에 남긴다.
- 바이트 값은 본문 대신 길이와 SHA-256만 싣는다(보고서에 원본 바이트를 넣지 않는다).
- write_json: 큰 결과(기본 100MB 초과)는 메모리에 한 덩어리로 만들지 않고 파일로 흘려 쓰며 SHA-256을 함께 계산한다.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

LARGE_JSON_BYTES = 100 * 1024 * 1024
ERROR_KEY = "$serialization_error"


def to_jsonable(value: Any, errors: Optional[List[Dict[str, str]]] = None, path: str = "$") -> Any:
    errors = errors if errors is not None else []
    try:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, Enum):
            return str(value)
        if isinstance(value, dict):
            return {str(k): to_jsonable(v, errors, f"{path}.{k}") for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [to_jsonable(v, errors, f"{path}[{i}]") for i, v in enumerate(value)]
        if isinstance(value, (set, frozenset)):
            return [to_jsonable(v, errors, f"{path}[{i}]") for i, v in enumerate(sorted(value, key=str))]
        if isinstance(value, (bytes, bytearray)):
            return {"$bytes": len(value), "sha256": hashlib.sha256(bytes(value)).hexdigest()}
        if isinstance(value, (Decimal, Path)):
            return str(value)
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return {f.name: to_jsonable(getattr(value, f.name), errors, f"{path}.{f.name}")
                    for f in dataclasses.fields(value)}
        if hasattr(value, "to_dict") and callable(value.to_dict):
            return to_jsonable(value.to_dict(), errors, path)
        return str(value)  # 날짜·시각 등. json.dumps(default=str)와 같은 표기
    except Exception as exc:  # 값 하나의 실패가 보고서 전체를 막지 않게 한다
        errors.append({"path": path, "error": f"{type(exc).__name__}: {exc}"})
        return {ERROR_KEY: f"{type(exc).__name__}"}


def jsonable_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """보고서 페이로드를 JSON 값으로 바꾸고, 바꾸지 못한 항목이 있으면 serialization_errors에 경로를 남긴다."""
    errors: List[Dict[str, str]] = []
    result = to_jsonable(payload, errors)
    if errors:
        result["serialization_errors"] = errors
    return result


def dumps(payload: Any, *, indent: Optional[int] = None) -> str:
    value = jsonable_payload(payload) if isinstance(payload, dict) else to_jsonable(payload)
    return json.dumps(value, ensure_ascii=False, indent=indent)


def write_json(path: Path, payload: Any, *, limit: int = LARGE_JSON_BYTES) -> Dict[str, Any]:
    """파일로 흘려 쓰고 크기·SHA-256을 돌려준다. limit을 넘으면 over_limit=True.
    
    Windows/Linux 등 OS 개행 차이(CRLF/LF)로 인한 해시 불일치를 방지하기 위해
    바이너리 모드('wb')로 정확한 바이트 스트림을 기록한다.
    """
    value = jsonable_payload(payload) if isinstance(payload, dict) else to_jsonable(payload)
    digest, size = hashlib.sha256(), 0
    # 바이너리 모드로 저장하여 플랫폼 독립적인 정확한 바이트 및 SHA-256 해시 보장
    with open(path, "wb") as fh:
        for chunk in json.JSONEncoder(ensure_ascii=False, indent=2).iterencode(value):
            data = chunk.encode("utf-8")
            digest.update(data)
            size += len(data)
            fh.write(data)
    return {"path": str(path), "bytes": size, "sha256": digest.hexdigest(), "over_limit": size > limit}
