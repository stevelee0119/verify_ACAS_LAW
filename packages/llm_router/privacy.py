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


def inspect_request(request):
    payload = asdict(request)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    kinds = Counter(m.kind for text in _strings(payload) for m in detect(text) if m.confidence >= 0.6)
    return {"policy_version": POLICY_VERSION,
            "request_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
            "scope": "ASSEMBLED_LLM_REQUEST", "status": "BLOCKED" if kinds else "PASSED",
            "detected_types": dict(kinds)}
