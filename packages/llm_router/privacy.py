"""Fail-closed inspection of assembled model input, without recording raw PII."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict

from packages.pii_engine.detector import detect

POLICY_VERSION = "payload-pii-v1"


def _strings(value):
    if isinstance(value, str):
        # Decode serialized evidence before detection, including escaped Unicode.
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            decoded = None
        if isinstance(decoded, (dict, list)):
            yield from _strings(decoded)
        else:
            yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            if key in {"성명", "대표자", "대표이사", "주민등록번호", "연락처", "이메일"} and isinstance(item, str):
                yield f"{key}: {item}"
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _walk_fields(value, path=""):
    """필드 경로(path)와 함께 문자열 값들을 추출한다."""
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            decoded = None
        if isinstance(decoded, (dict, list)):
            yield from _walk_fields(decoded, path)
        else:
            yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            current_path = f"{path}.{key}" if path else str(key)
            if key in {"성명", "대표자", "대표이사", "주민등록번호", "연락처", "이메일"} and isinstance(item, str):
                yield current_path, f"{key}: {item}"
            yield from _walk_fields(item, current_path)
    elif isinstance(value, (list, tuple)):
        for idx, item in enumerate(value):
            current_path = f"{path}[{idx}]"
            yield from _walk_fields(item, current_path)


def inspect_request(request):
    """조립된 LLM 요청의 개인정보 포함 여부를 감사한다. 원문 PII는 기록하지 않는다."""
    payload = asdict(request)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    
    kinds = Counter()
    system_kinds = Counter()
    user_kinds = Counter()
    detected_paths = set()

    for path, text in _walk_fields(payload):
        matches = [m for m in detect(text) if m.confidence >= 0.6]
        if matches:
            detected_paths.add(path)
            for m in matches:
                kinds[m.kind] += 1
                if path.startswith("system") or path.startswith("schema"):
                    system_kinds[m.kind] += 1
                else:
                    user_kinds[m.kind] += 1

    status = "BLOCKED" if kinds else "PASSED"
    failure_code = None
    if status == "BLOCKED":
        # 시스템 고정 프롬프트에서만 잡힌 경우와 사용자 입력에서 잡힌 경우를 구분
        if system_kinds and not user_kinds:
            failure_code = "STATIC_PROMPT_FALSE_POSITIVE"
        else:
            failure_code = "PII_INPUT_BLOCKED"

    res = {
        "policy_version": POLICY_VERSION,
        "request_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "scope": "ASSEMBLED_LLM_REQUEST",
        "status": status,
        "detected_types": dict(kinds),
    }
    if failure_code:
        res["failure_code"] = failure_code
        res["detected_field_paths"] = sorted(detected_paths)
        res["retryable"] = failure_code == "STATIC_PROMPT_FALSE_POSITIVE"
    return res
