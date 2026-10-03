"""Fail-closed inspection of assembled model input, without recording raw PII.

R8-A (TK-51): 구조화(JSON) 요청에서 라벨-값 쌍, 형제 필드 쌍, 배열 이웃 등
              복합 문맥을 복원하여 전송 전 개인정보를 탐지한다.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Set, Tuple

from packages.common.enums import LLMRole
from packages.legal_engine.argument_validity_verifier import _OPINION_SCHEMA, _OPINION_SYSTEM
from packages.llm_router.router import SYSTEM_BASE, _VERDICT_SCHEMA
from packages.pii_engine.detector import PARTY_AND_TITLE_LABELS, detect
from packages.rag_engine.review import ENVELOPE_SCHEMA, ITEM_SCHEMA, RAG_REVIEW_SYSTEM_PROMPT, SCHEMA
from packages.verification_engine.ai_document_detector import AI_DETECTOR_SYSTEM_PROMPT, _DETECTOR_SCHEMA

POLICY_VERSION = "payload-pii-v3"

# ===========================================================================
# 라벨 키 집합: detector.py의 PARTY_AND_TITLE_LABELS에서 단일 출처로 구성
# 개인정보 종류 키(주민등록번호, 연락처, 이메일)도 포함
# ===========================================================================
_PII_TYPE_KEYS = {"주민등록번호", "주민번호", "연락처", "전화번호", "휴대전화", "이메일", "생년월일"}
# 라벨 어휘 + 개인정보 종류 키를 합쳐서 문맥 복원에 사용
CONTEXT_LABEL_KEYS: frozenset = frozenset(
    set(PARTY_AND_TITLE_LABELS) | _PII_TYPE_KEYS
)


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


# ===========================================================================
# R8-A (TK-51): 구조화 JSON 값에서 문맥을 복원하여 문자열 추출
# ===========================================================================
def _try_json_parse(value: str):
    """문자열을 JSON으로 파싱 시도. 성공하면 파싱 결과, 실패하면 None 반환."""
    try:
        decoded = json.loads(value)
    except (ValueError, TypeError):
        return None
    if isinstance(decoded, (dict, list)):
        return decoded
    return None


def _collect_texts_from_value(value, path: str = "") -> List[Tuple[str, str]]:
    """값에서 (경로, 검사할 텍스트) 쌍을 수집한다.

    사전: 모든 문자열 값에 '키: 값' 문맥을 추가하고, 형제 문자열 값들을 이어붙인 문맥도 생성.
    배열: 이웃 문자열 원소를 이어붙인 문맥도 생성.
    JSON 문자열: 재귀적으로 파싱하여 같은 규칙 적용.
    """
    results: List[Tuple[str, str]] = []

    if isinstance(value, str):
        # JSON 문자열인지 시도
        decoded = _try_json_parse(value)
        if decoded is not None:
            results.extend(_collect_texts_from_value(decoded, path))
        else:
            # 일반 문자열 값
            results.append((path, value))

    elif isinstance(value, dict):
        # 각 키-값 쌍을 개별 검사
        str_values: List[str] = []  # 형제 문자열 값 수집용
        for key, item in value.items():
            current_path = f"{path}.{key}" if path else str(key)

            if isinstance(item, str):
                decoded = _try_json_parse(item)
                if decoded is not None:
                    # JSON 문자열이면 파싱하여 재귀 검사
                    results.extend(_collect_texts_from_value(decoded, current_path))
                else:
                    # 모든 키에 대해 '키: 값' 문맥을 생성 (TK-51 항목 2)
                    results.append((current_path, f"{key}: {item}"))
                    # 원본 값도 검사
                    results.append((current_path, item))
                    # 형제 값 결합용 수집
                    str_values.append(item)
            else:
                # 비문자열 값은 재귀
                results.extend(_collect_texts_from_value(item, current_path))

        # 형제 문자열 값들을 원래 순서로 이어붙인 문맥 (TK-51 항목 2)
        # 예: {"역할": "원고", "이름값": "편하람"} → "원고 편하람"
        if len(str_values) >= 2:
            sibling_text = " ".join(str_values)
            sibling_path = f"{path}.__siblings__" if path else "__siblings__"
            results.append((sibling_path, sibling_text))

    elif isinstance(value, (list, tuple)):
        # 각 원소를 개별 검사
        str_elements: List[str] = []  # 이웃 원소 결합용
        for idx, item in enumerate(value):
            current_path = f"{path}[{idx}]"
            results.extend(_collect_texts_from_value(item, current_path))
            # 문자열 원소 수집
            if isinstance(item, str):
                decoded = _try_json_parse(item)
                if decoded is None:
                    str_elements.append(item)

        # 이웃 문자열 원소를 이어붙인 문맥 (TK-51 항목 2)
        if len(str_elements) >= 2:
            neighbor_text = " ".join(str_elements)
            neighbor_path = f"{path}.__neighbors__" if path else "__neighbors__"
            results.append((neighbor_path, neighbor_text))

    return results


def _walk_fields(value, path=""):
    """필드 경로(path)와 함께 문자열 값들을 추출한다 (R8-A 강화 버전).

    TK-51: 모든 문자열 값에 '키: 값' 문맥, 형제 결합 문맥, 배열 이웃 문맥을 추가.
    라벨 키 정의는 detector.py의 PARTY_AND_TITLE_LABELS에서 단일 출처로 가져온다.
    """
    for collected_path, collected_text in _collect_texts_from_value(value, path):
        yield collected_path, collected_text


def inspect_request(request, *, _original_system: str = None):
    """조립된 LLM 요청의 개인정보 포함 여부를 감사한다. 원문 PII는 기록하지 않는다.

    TK-28 (U3):
    - 종류 목록 방식을 폐기하고 등록된 고정 상수 출처 확인 방식으로 전환.
    - system/schema가 등록된 고정 상수와 정확히 일치할 때만 그 안의 탐지를 정적 오탐으로 인정.
    - 등록되지 않은 system/schema(동적 값 섞임 포함) 및 user 영역에서의 탐지는 PII 종류와 무관하게 차단.

    R8-A (TK-51):
    - _original_system이 주어지면 조립 전 원본 system을 별도 검사한다.
    """
    payload = asdict(request)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)

    kinds = Counter()
    blocked_kinds = Counter()
    static_fp_kinds = Counter()
    detected_paths = set()

    # R8-A: 조립 전 원본 system이 있으면 별도 검사 (JSON 구조 보존)
    if _original_system is not None:
        for path, text in _walk_fields({"__original_system__": _original_system}):
            matches = [m for m in detect(text) if m.confidence >= 0.6]
            for m in matches:
                kinds[m.kind] += 1
                # 원본 system은 사용자 제공 동적 값이므로 등록 상수 면책 없음
                blocked_kinds[m.kind] += 1
                detected_paths.add(f"original_system.{path}")

    # 최상위 payload 필드를 개별 순회하여 경로 기반 등록 판정이 정확하게 동작하도록 함
    # (payload 전체를 _walk_fields에 넘기면 최상위 형제 결합이 경로 판정을 혼동시킴)
    for top_key, top_value in payload.items():
        for path, text in _walk_fields(top_value, top_key):
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
