"""Fail-closed inspection of assembled model input, without recording raw PII.

R8-A (TK-51): 구조화(JSON) 요청에서 라벨-값 쌍, 형제 필드 쌍, 배열 이웃 등
              복합 문맥을 복원하여 전송 전 개인정보를 탐지한다.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Set, Tuple

from packages.common.enums import LLMRole
from packages.legal_engine.argument_validity_verifier import _OPINION_SCHEMA, _OPINION_SYSTEM
from packages.llm_router.router import SYSTEM_BASE, _VERDICT_SCHEMA
from packages.pii_engine.detector import (
    DOUBLE_SURNAMES,
    PARTY_AND_TITLE_LABELS,
    STRUCTURED_PERSON_KEY_LABELS,
    detect,
    is_valid_korean_name_structure,
)
from packages.rag_engine.review import ENVELOPE_SCHEMA, ITEM_SCHEMA, RAG_REVIEW_SYSTEM_PROMPT, SCHEMA
from packages.verification_engine.ai_document_detector import AI_DETECTOR_SYSTEM_PROMPT, _DETECTOR_SCHEMA

POLICY_VERSION = "payload-pii-v3"

# ===========================================================================
# 라벨 키 집합: detector.py의 PARTY_AND_TITLE_LABELS에서 단일 출처로 구성 (TK-51, TK-52 2절)
# 개인정보 종류 키(주민등록번호, 연락처, 이메일)도 포함
# ===========================================================================
_PII_TYPE_KEYS = {"주민등록번호", "주민번호", "연락처", "전화번호", "휴대전화", "이메일", "생년월일"}
# 라벨 어휘 + 개인정보 종류 키를 합쳐서 키: 값 문맥 복원 및 형제/이웃 결합 판정에 사용
CONTEXT_LABEL_KEYS: frozenset = frozenset(
    set(PARTY_AND_TITLE_LABELS) | set(STRUCTURED_PERSON_KEY_LABELS) | _PII_TYPE_KEYS
)

_NON_PERSON_NAME_KEY_HEADS = (
    "사건", "법원", "회사", "법인", "기관", "장소", "지명", "부서", "직무",
    "직책", "직위", "문서", "서류", "파일", "자료", "사업", "서비스",
)
_NON_PERSON_ENGLISH_KEY_HEADS = {
    "case", "court", "company", "corporation", "organization", "place", "location",
    "institution", "university", "school", "department", "team", "job", "position", "office", "document", "file", "event",
    "business", "service", "product", "site", "subject",
}
_ENGLISH_PERSON_KEY_LABELS = frozenset(
    label.casefold()
    for label in STRUCTURED_PERSON_KEY_LABELS
    if isinstance(label, str) and label.isascii() and label.strip()
)
_KOREAN_PERSON_FIELD_SUFFIXES = (
    "이름", "성명", "성함", "존함", "명의자", "명의인", "보유자", "소유자", "직원", "계좌주",
)
_ENGLISH_PERSON_FIELD_SUFFIXES = (
    "name", "surname", "forename", "alias", "holder", "owner", "signatory", "payee",
    "fname", "lname", "pname", "nm",
)
_NAME_VALUE_RE = re.compile(r"^(?P<name>[가-힣]{2,4})")
def _normalise_korean_key(key: str) -> str:
    """공백·괄호·구두점 표기가 달라도 키의 한글 라벨을 비교한다."""
    text = unicodedata.normalize("NFKC", key)
    return re.sub(r"[^가-힣0-9a-z]", "", text.casefold())


def _person_label_for_key(key: Any) -> str | None:
    """사람 이름 필드 키면 문맥 라벨을, 아니면 None을 반환한다."""
    if not isinstance(key, str) or not key.strip():
        return None

    normalized = unicodedata.normalize("NFKC", key)
    korean_key = _normalise_korean_key(normalized)
    if korean_key:
        # 기존의 구체적인 사람 라벨 신호를 먼저 본다. 키 앞의 분류어가 이를 지우지 않는다.
        korean_labels = {
            _normalise_korean_key(label)
            for label in PARTY_AND_TITLE_LABELS
            if isinstance(label, str)
            and re.search(r"[가-힣]", label)
            and _normalise_korean_key(label) not in {"이름", "성명"}
        }
        for label in sorted(korean_labels, key=len, reverse=True):
            if label and label in korean_key:
                return next(
                    original for original in PARTY_AND_TITLE_LABELS
                    if _normalise_korean_key(original) == label
                )

        # 기존 비인명 분류어는 구체적인 사람 라벨이 없을 때만 우선한다.
        if any(korean_key.startswith(_normalise_korean_key(head)) for head in _NON_PERSON_NAME_KEY_HEADS):
            return None

        # 이름·성명 표지와 그 외 필드 형태는 나머지 키에서만 사람 문맥 신호로 쓴다.
        if korean_key.endswith("명"):
            return "명"
        for suffix in _KOREAN_PERSON_FIELD_SUFFIXES:
            normalized_suffix = _normalise_korean_key(suffix)
            if normalized_suffix and korean_key.endswith(normalized_suffix):
                return suffix

    # camelCase, snake_case, 괄호·공백 변형을 동일한 영어 토큰으로 처리한다.
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", normalized)
    english_key = re.sub(r"[^a-z0-9]+", " ", separated.casefold()).strip()
    if not english_key:
        return None
    words = english_key.split()
    label_phrases = {tuple(label.split()) for label in _ENGLISH_PERSON_KEY_LABELS}
    strong_label_phrases = label_phrases - {("name",), ("full", "name"), ("contact", "name")}
    for phrase in sorted(strong_label_phrases, key=len, reverse=True):
        if len(phrase) == 1 and phrase[0] in words:
            return " ".join(phrase)
        if len(phrase) > 1 and any(tuple(words[i:i + len(phrase)]) == phrase for i in range(len(words) - len(phrase) + 1)):
            return " ".join(phrase)

    if any(word in _NON_PERSON_ENGLISH_KEY_HEADS for word in words):
        return None

    for phrase in label_phrases:
        if len(phrase) == 1 and phrase[0] in words:
            return " ".join(phrase)
        if len(phrase) > 1 and any(tuple(words[i:i + len(phrase)]) == phrase for i in range(len(words) - len(phrase) + 1)):
            return " ".join(phrase)

    compact_key = re.sub(r"[^a-z0-9]", "", english_key)
    if any(
        compact_key.endswith(suffix) and len(compact_key) > len(suffix)
        for suffix in _ENGLISH_PERSON_FIELD_SUFFIXES
    ):
        return "name"
    return None


def _is_person_name_key(key: Any) -> bool:
    """detector 라벨 어휘를 바탕으로 키가 사람 이름 필드인지 판정한다."""
    return _person_label_for_key(key) is not None


def _is_explicit_person_name_field_key(key: Any) -> bool:
    """이름 필드 표지가 있는 키인지 판정한다. 역할 라벨만으로는 값을 강제 차단하지 않는다."""
    if not isinstance(key, str) or _person_label_for_key(key) is None:
        return False
    normalized = unicodedata.normalize("NFKC", key)
    korean_key = _normalise_korean_key(normalized)
    if korean_key.endswith("명"):
        return True
    if korean_key.endswith("이름") or korean_key.endswith("성명") or korean_key.endswith("성함") or korean_key.endswith("존함"):
        return True
    if korean_key.endswith(("명의자", "명의인", "보유자", "소유자", "계좌주")):
        return True

    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", normalized)
    english_key = re.sub(r"[^a-z0-9]+", " ", separated.casefold()).strip()
    compact_key = re.sub(r"[^a-z0-9]", "", english_key)
    if compact_key == "name":
        return False
    return any(
        compact_key.endswith(suffix) and len(compact_key) > len(suffix)
        for suffix in _ENGLISH_PERSON_FIELD_SUFFIXES
    )


def _name_context_candidate(value: str) -> str | None:
    """역할 라벨 문맥에 붙일 짧은 이름 후보만 고른다; 다중 토큰 값은 원문 검사에 둔다."""
    if not isinstance(value, str):
        return None
    candidate = unicodedata.normalize("NFKC", value).strip()
    if re.search(r"\s", candidate):
        return None
    compact = re.sub(r"[^가-힣]", "", candidate)
    if not 2 <= len(compact) <= 4:
        return None
    return _name_like_value(candidate)


def _name_like_value(value: str) -> str | None:
    """값 첫머리의 이름 후보를 찾고 뒤의 수식·조사로 후보를 버리지 않는다."""
    candidate = unicodedata.normalize("NFKC", value).lstrip()
    compact = re.sub(r"[ \t\u3000]+", "", candidate)
    match = _NAME_VALUE_RE.match(compact)
    if not match:
        return None
    hangul_prefix = match.group("name")
    sizes = list(range(min(3, len(hangul_prefix)), 1, -1))
    if len(hangul_prefix) >= 4 and hangul_prefix[:2] in DOUBLE_SURNAMES:
        sizes.insert(0, 4)
    elif len(hangul_prefix) >= 4:
        sizes.append(4)
    for size in sizes:
        possible = hangul_prefix[:size]
        if is_valid_korean_name_structure(possible, is_explicit_label=True):
            return possible
    return None


def _person_name_value_paths(value: Any, path: str = "") -> Set[str]:
    """명시적인 사람 이름 필드 아래 비어 있지 않은 값을 fail-closed 대상으로 수집한다."""
    blocked: Set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            current_path = f"{path}.{key}" if path else str(key)
            generic_name_value = (
                isinstance(key, str)
                and unicodedata.normalize("NFKC", key).casefold().strip() == "name"
                and _name_context_candidate(item) is not None
            )
            if (
                (_is_explicit_person_name_field_key(key) or generic_name_value)
                and not (item is None or isinstance(item, str) and not item.strip())
            ):
                blocked.add(current_path)
            if isinstance(item, str):
                decoded = _try_json_parse(item)
                if decoded is not None:
                    blocked.update(_person_name_value_paths(decoded, current_path))
            else:
                blocked.update(_person_name_value_paths(item, current_path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            current_path = f"{path}[{index}]"
            if isinstance(item, str):
                decoded = _try_json_parse(item)
                if decoded is not None:
                    blocked.update(_person_name_value_paths(decoded, current_path))
            else:
                    blocked.update(_person_name_value_paths(item, current_path))
    elif isinstance(value, str):
        decoded = _try_json_parse(value)
        if decoded is not None:
            blocked.update(_person_name_value_paths(decoded, path))
    return blocked


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
# R8-A / 8B-2 (TK-51, TK-52 2절): 구조화 JSON 값에서 문맥을 복원하여 문자열 추출
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

    사전:
      - 원본 문자열 값은 항상 검사.
      - 개인정보 종류 키는 항상 '키: 값' 문맥을 합성한다.
      - 사람 이름 키는 값 후보 문맥을 합성한다. 이름 아님이 입증되지 않은 값은 별도 fail-closed 경로에서 차단한다.
      - 형제 결합: 선행 값이 라벨이고 후행 값이 라벨이 아니며 유효한 이름 구조일 때만 결합 문맥 합성 (역할/이름 쌍 지원).
    배열:
      - 선행 원소가 라벨이고 후행 원소가 라벨이 아니며 유효한 이름 구조일 때만 결합 문맥 합성 (라벨 나열 배열 과차단 방지).
    JSON 문자열:
      - 재귀적으로 파싱하여 같은 규칙 적용.
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
        # 각 키-값 쌍을 검사
        str_items: List[Tuple[str, str]] = []  # 형제 문자열 (key, value) 수집용
        for key, item in value.items():
            current_path = f"{path}.{key}" if path else str(key)

            if isinstance(item, str):
                decoded = _try_json_parse(item)
                if decoded is not None:
                    # JSON 문자열이면 파싱하여 재귀 검사
                    results.extend(_collect_texts_from_value(decoded, current_path))
                else:
                    # 원본 값 검사
                    results.append((current_path, item))
                    # 식별번호 종류 키의 기존 문맥은 유지한다. 사람 이름 키는 이름 꼴 값에만
                    # 문맥을 붙여 장소·직무·법인 값의 차단을 늘리지 않는다.
                    if key in _PII_TYPE_KEYS:
                        results.append((current_path, f"{key}: {item}"))
                    else:
                        label = _person_label_for_key(key)
                        name = _name_context_candidate(item)
                        if label and name:
                            detector_label = label if re.search(r"[가-힣]", label) else "이름"
                            results.append((current_path, f"{detector_label}: {name}"))
                    str_items.append((key, item))
            else:
                # 비문자열 값은 재귀
                results.extend(_collect_texts_from_value(item, current_path))

        # 형제 문자열 결합:
        # '라벨 값 다음에 이름 구조 값이 올 때만' 결합 문맥을 생성한다 (TK-52 2절)
        # 예: {"역할": "원고", "이름값": "편하람"} -> "원고 편하람"
        for i in range(len(str_items) - 1):
            (k1, v1), (k2, v2) = str_items[i], str_items[i + 1]
            if v1 in CONTEXT_LABEL_KEYS and v2 not in CONTEXT_LABEL_KEYS and is_valid_korean_name_structure(v2):
                sibling_path = f"{path}.__siblings__[{i}]" if path else f"__siblings__[{i}]"
                results.append((sibling_path, f"{v1} {v2}"))

    elif isinstance(value, (list, tuple)):
        # 각 원소를 개별 검사
        str_elements: List[str] = []  # 이웃 원소 결합용
        for idx, item in enumerate(value):
            current_path = f"{path}[{idx}]"
            if isinstance(item, str):
                decoded = _try_json_parse(item)
                if decoded is not None:
                    results.extend(_collect_texts_from_value(decoded, current_path))
                else:
                    results.append((current_path, item))
                    str_elements.append(item)
            else:
                results.extend(_collect_texts_from_value(item, current_path))

        # 배열 이웃 결합:
        # '선행 원소가 라벨이고 후행 원소가 이름 구조일 때만' 결합 문맥을 생성한다 (TK-52 2절)
        # 예: ["원고", "편하람"] -> 결합 / ["원고", "피고", "증인"] -> 결합 안 함
        for i in range(len(str_elements) - 1):
            w1, w2 = str_elements[i], str_elements[i + 1]
            if w1 in CONTEXT_LABEL_KEYS and w2 not in CONTEXT_LABEL_KEYS and is_valid_korean_name_structure(w2):
                neighbor_path = f"{path}.__neighbors__[{i}]" if path else f"__neighbors__[{i}]"
                results.append((neighbor_path, f"{w1} {w2}"))

    return results


def _walk_fields(value, path=""):
    """원문 문자열과 제한된 구조 문맥을 필드 경로와 함께 추출한다.

    개인정보 종류 키와 사람 이름 키의 문맥, 이름 구조를 확인한 형제·배열 쌍을 추가한다.
    이름 키의 불확실 값은 별도 경로 판정으로 fail-closed 차단한다.
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
        is_dynamic_system = top_key == "system" and not is_registered_system_prompt(request.system)
        fail_closed_name_paths = set()
        if top_key == "user" or is_dynamic_system:
            fail_closed_name_paths = _person_name_value_paths(top_value, top_key)
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

        # detector가 이름 값을 자체 인식하지 못해도 민감 키의 미분류 문자열은 통과시키지 않는다.
        for path in fail_closed_name_paths:
            kinds["PERSON"] += 1
            blocked_kinds["PERSON"] += 1
            detected_paths.add(path)

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
