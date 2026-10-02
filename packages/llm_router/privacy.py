"""Fail-closed inspection of assembled model input, without recording raw PII."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Dict, Set

from packages.common.enums import LLMRole
from packages.legal_engine.argument_validity_verifier import _OPINION_SCHEMA, _OPINION_SYSTEM
from packages.llm_router.router import SYSTEM_BASE, _VERDICT_SCHEMA
from packages.pii_engine.detector import detect
from packages.rag_engine.review import ENVELOPE_SCHEMA, ITEM_SCHEMA, RAG_REVIEW_SYSTEM_PROMPT, SCHEMA
from packages.verification_engine.ai_document_detector import AI_DETECTOR_SYSTEM_PROMPT, _DETECTOR_SCHEMA

POLICY_VERSION = "payload-pii-v2"


# ===========================================================================
# TK-28 (U3): 출처가 확인된 고정 시스템 프롬프트 및 스키마 등록소
# ===========================================================================
def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_schema(schema: Any) -> str:
    serialized = json.dumps(schema, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# 1. 등록 고정 시스템 프롬프트 목록
REGISTERED_SYSTEM_PROMPT_CONSTANTS: Dict[str, str] = {
    "SYS_AI_DOCUMENT_DETECTOR": AI_DETECTOR_SYSTEM_PROMPT,
    "SYS_RAG_REVIEW": RAG_REVIEW_SYSTEM_PROMPT,
    "SYS_ARGUMENT_OPINION": _OPINION_SYSTEM,
    "SYS_ROUTER_BASE": SYSTEM_BASE,
    "SYS_EMPTY": "",
}

REGISTERED_SYSTEM_HASHES: Set[str] = {
    _hash_text(prompt) for prompt in REGISTERED_SYSTEM_PROMPT_CONSTANTS.values()
}

# 2. 등록 고정 스키마 목록
REGISTERED_SCHEMA_CONSTANTS: Dict[str, Any] = {
    "SCHEMA_AI_DETECTOR": _DETECTOR_SCHEMA,
    "SCHEMA_RAG_ENVELOPE": ENVELOPE_SCHEMA,
    "SCHEMA_RAG_FULL": SCHEMA,
    "SCHEMA_RAG_ITEM": ITEM_SCHEMA,
    "SCHEMA_ARGUMENT_OPINION": _OPINION_SCHEMA,
    "SCHEMA_ROUTER_VERDICT": _VERDICT_SCHEMA,
}

REGISTERED_SCHEMA_HASHES: Set[str] = {
    _hash_schema(schema) for schema in REGISTERED_SCHEMA_CONSTANTS.values()
}


def is_registered_system_prompt(text: str) -> bool:
    """system 필드의 문자열이 출처가 확인된 등록 고정 상수인지 검증한다 (TK-28).
    
    1. 등록된 시스템 프롬프트 상수와 완전 일치
    2. router에서 SYSTEM_BASE + [역할] role + 등록 프롬프트로 조립된 고정 문자열과 완전 일치
    """
    if not isinstance(text, str):
        return False
    # 기본 등록 프롬프트와 완전 일치
    if _hash_text(text) in REGISTERED_SYSTEM_HASHES:
        return True
    # router의 고정 조립 패턴 확인: f"{SYSTEM_BASE}\n[역할] {role}\n{sub_prompt}"
    prefix = f"{SYSTEM_BASE}\n[역할] "
    if text.startswith(prefix):
        rest = text[len(prefix):]
        parts = rest.split("\n", 1)
        role_str = parts[0]
        sub_prompt = parts[1] if len(parts) > 1 else ""
        valid_roles = {str(r) for r in LLMRole} | {r.value for r in LLMRole}
        if role_str in valid_roles:
            return _hash_text(sub_prompt) in REGISTERED_SYSTEM_HASHES
    return False


def is_registered_schema(schema: Any) -> bool:
    """schema 필드가 출처가 확인된 등록 고정 스키마 상수인지 검증한다 (TK-28)."""
    if not isinstance(schema, (dict, list)):
        return False
    try:
        return _hash_schema(schema) in REGISTERED_SCHEMA_HASHES
    except Exception:
        return False


def _strings(value):
    if isinstance(value, str):
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
    """조립된 LLM 요청의 개인정보 포함 여부를 감사한다. 원문 PII는 기록하지 않는다.
    
    TK-28 (U3):
    - 종류 목록 방식을 폐기하고 등록된 고정 상수 출처 확인 방식으로 전환.
    - system/schema가 등록된 고정 상수와 정확히 일치할 때만 그 안의 탐지를 정적 오탐으로 인정.
    - 등록되지 않은 system/schema(동적 값 섞임 포함) 및 user 영역에서의 탐지는 PII 종류와 무관하게 차단.
    """
    payload = asdict(request)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    
    kinds = Counter()
    blocked_kinds = Counter()
    static_fp_kinds = Counter()
    detected_paths = set()

    for path, text in _walk_fields(payload):
        matches = [m for m in detect(text) if m.confidence >= 0.6]
        if not matches:
            continue
        detected_paths.add(path)
        for m in matches:
            kinds[m.kind] += 1
            is_system_path = path.startswith("system")
            is_schema_path = path.startswith("schema")

            is_verified_static_source = False
            if is_system_path:
                is_verified_static_source = is_registered_system_prompt(request.system)
            elif is_schema_path:
                is_verified_static_source = is_registered_schema(request.schema)

            if is_verified_static_source:
                # 출처가 확인된 등록 고정 상수 내에서의 탐지는 정적 안내문 오탐으로 면책
                static_fp_kinds[m.kind] += 1
            else:
                # 등록되지 않은 영역(사용자 입력 또는 동적 값이 혼입된 시스템 프롬프트)에서의 탐지는
                # PII 종류(PERSON, DOB, PHONE, EMAIL 등)와 무관하게 차단
                blocked_kinds[m.kind] += 1

    if blocked_kinds:
        status = "BLOCKED"
        failure_code = "PII_INPUT_BLOCKED"
    elif static_fp_kinds:
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
            res["note"] = "출처가 확인된 등록 고정 상수의 정적 어휘 오탐으로 판정하여 호출을 허용함(동적 PII 없음)"
    return res
