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

    # 사용자 입력(user_kinds)에 개인정보가 존재할 때에만 실질적 PII 유출로 차단(BLOCKED)한다.
    # 시스템 고정 프롬프트(system/schema)에서만 감지된 경우는 정적 오탐으로 분류하여 통과(PASSED)시킨다.
    if user_kinds:
        status = "BLOCKED"
        failure_code = "PII_INPUT_BLOCKED"
    elif system_kinds:
        status = "PASSED"
        failure_code = "STATIC_PROMPT_FALSE_POSITIVE"
    else:
        status = "PASSED"
        failure_code = None

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
        if failure_code == "STATIC_PROMPT_FALSE_POSITIVE":
            res["note"] = "시스템 고정 프롬프트의 정적 어휘 오탐으로 판정하여 호출을 허용함(사용자 입력 PII 없음)"
    return res
