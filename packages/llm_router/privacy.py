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
    PARTY_AND_TITLE_LABELS,
    STRUCTURED_PERSON_KEY_LABELS,
    DOUBLE_SURNAMES,
    JOSA,
    detect,
    is_valid_korean_name_structure,
)
from packages.rag_engine.review import ENVELOPE_SCHEMA, ITEM_SCHEMA, KOREAN_RAG_REVIEW_SYSTEM_PROMPT, RAG_REVIEW_SYSTEM_PROMPT, SCHEMA
from packages.verification_engine.ai_document_detector import AI_DETECTOR_SYSTEM_PROMPT, _DETECTOR_SCHEMA

POLICY_VERSION = "payload-pii-v4"

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
    "department", "team", "job", "position", "office", "document", "file", "event",
    "business", "service", "product", "site", "subject",
}
_ENGLISH_PERSON_KEY_LABELS = frozenset(
    label.casefold()
    for label in STRUCTURED_PERSON_KEY_LABELS
    if isinstance(label, str) and label.isascii() and label.strip()
)
_NAME_VALUE_RE = re.compile(
    r"^(?P<name>[가-힣]{2,4})"
    r"(?:\s*(?:님|씨|군|양|선생|변호사|변호인|사무관|검사|판사|대위|중위|소령|중령|대령|병장|상병|일병|이병))?"
    r"(?:\s*[（(][^()（）\r\n]{1,24}[)）])?$"
)
_KEY_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_KEY_ENGLISH_WORD_RE = re.compile(r"[a-z0-9]+")
_KEY_KOREAN_CLEAN_RE = re.compile(r"[^가-힣0-9a-z]")
_NAME_FIELD_SUFFIX_RE = re.compile(r"(?:성명|성함|이름|명의자|명)$")
_SPACED_NAME_PARTICLE_RE = re.compile(
    rf"^(?P<name>(?:[가-힣][ \t]?){{1,3}}[가-힣])(?:{JOSA})$"
)
_LEADING_NAME_VALUE_RE = re.compile(
    rf"^(?P<name>(?:[가-힣][ \t]?){{1,3}}[가-힣])(?:{JOSA}){{0,2}}(?=\s)"
)
_COMPOSITE_NAME_PARTICLE_RE = re.compile(
    rf"^(?P<name>(?:[가-힣][ \t]?){{1,3}}[가-힣])(?:{JOSA}){{1,2}}$"
)
# Same token grammar as PseudonymStore, never a prefix-only exemption.
_MASKED_NAME_VALUE_RE = re.compile(
    rf"[ \t]*(?:\[?(?:PERSON|COMPANY)_[0-9]{{3,}}\]?(?:{JOSA})?)"
    rf"(?:[ \t,;/]+\[?(?:PERSON|COMPANY)_[0-9]{{3,}}\]?(?:{JOSA})?)*[ \t]*"
)


def _normalise_korean_key(key: str) -> str:
    """공백·괄호·구두점 표기가 달라도 키의 한글 라벨을 비교한다."""
    text = unicodedata.normalize("NFKC", key)
    return _KEY_KOREAN_CLEAN_RE.sub("", text.casefold())


# Fixed label grammar is computed once, not rebuilt for every field.
_KOREAN_KEY_LABELS = tuple(sorted(
    ((_normalise_korean_key(label), label) for label in PARTY_AND_TITLE_LABELS),
    key=lambda pair: (-len(pair[0]), pair[0]),
))
_ENGLISH_KEY_PHRASES = tuple(sorted(
    (tuple(label.split()) for label in _ENGLISH_PERSON_KEY_LABELS),
    key=lambda phrase: (-len(phrase), phrase),
))
_ENGLISH_ROLE_TERMS = frozenset(
    label for label in _ENGLISH_PERSON_KEY_LABELS
    if " " not in label and label != "name"
)
_KOREAN_NON_PERSON_KEYS = frozenset(
    f"{head}{suffix}" for head in _NON_PERSON_NAME_KEY_HEADS
    for suffix in ("명", "이름")
)


def _key_words(key: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", key)
    separated = _KEY_CAMEL_BOUNDARY_RE.sub(" ", normalized)
    return tuple(_KEY_ENGLISH_WORD_RE.findall(separated.casefold()))


def _has_name_field_marker(key: Any) -> bool:
    """An unknown subject plus a name suffix is a field signal, not a person type."""
    if not isinstance(key, str):
        return False
    korean = _normalise_korean_key(key)
    if korean in _KOREAN_NON_PERSON_KEYS:
        return False
    words = _key_words(key)
    if any(word in _NON_PERSON_ENGLISH_KEY_HEADS for word in words):
        # Existing explicit human roles still override a non-person prefix.
        if not any(word in _ENGLISH_ROLE_TERMS for word in words):
            return False
    return bool(_NAME_FIELD_SUFFIX_RE.search(korean)) or bool(
        words and words[-1] in {"name", "nm", "surname", "forename"}
    )


def _person_label_for_key(key: Any) -> str | None:
    """키에서 사람 이름 문맥을 구성할 detector 라벨 어휘를 반환한다."""
    if not isinstance(key, str) or not key.strip():
        return None

    normalized = unicodedata.normalize("NFKC", key)
    korean_key = _normalise_korean_key(normalized)
    if korean_key:
        # 단순히 '-명/이름'으로 끝나는 비인명 키에는 사람 문맥을 붙이지 않는다.
        if korean_key in _KOREAN_NON_PERSON_KEYS:
            return None
        for label, original in _KOREAN_KEY_LABELS:
            if label and label in korean_key:
                return original
        if _NAME_FIELD_SUFFIX_RE.search(korean_key):
            return "이름"

    # camelCase, snake_case, 괄호·공백 변형을 동일한 영어 토큰으로 처리한다.
    words = _key_words(normalized)
    if not words:
        return None
    if any(word in _NON_PERSON_ENGLISH_KEY_HEADS for word in words):
        # 명시적인 사람 역할 표지가 있으면 'company representative'처럼 사람 필드로 인정한다.
        if not any(label in words for label in _ENGLISH_ROLE_TERMS):
            return None
    # Constant-sized phrase grammar; one traversal per key.
    phrase_matches = [
        (phrase, position)
        for position in range(len(words))
        for phrase in _ENGLISH_KEY_PHRASES
        if words[position:position + len(phrase)] == phrase
        and not (phrase == ("name",) and position != 0)
    ]
    if phrase_matches:
        phrase, _ = min(phrase_matches, key=lambda item: (-len(item[0]), item[1], item[0]))
        if phrase[-1] == "name" and tuple(phrase[:-1]) in _ENGLISH_KEY_PHRASES:
            return " ".join(phrase[:-1])
        return " ".join(phrase)
    if words[-1] == "nm":
        return "이름"
    return None


def _is_person_name_key(key: Any) -> bool:
    """detector 라벨 어휘를 바탕으로 키가 사람 이름 필드인지 판정한다."""
    return _person_label_for_key(key) is not None


def _name_like_value(value: str) -> str | None:
    """키 문맥을 붙일 단일 한국어 이름 토큰만 반환한다."""
    candidate = unicodedata.normalize("NFKC", value).strip()
    particle_match = _SPACED_NAME_PARTICLE_RE.fullmatch(candidate)
    if particle_match:
        stem = re.sub(r"[ \t]", "", particle_match.group("name"))
        compact = re.sub(r"[ \t]", "", candidate)
        # Preserve three-syllable names and four-syllable double-surname names.
        if len(compact) > 3 and not (
            len(compact) == 4 and compact[:2] in DOUBLE_SURNAMES
        ):
            if is_valid_korean_name_structure(stem):
                return stem
    match = _NAME_VALUE_RE.fullmatch(candidate)
    if not match:
        return None
    name = match.group("name")
    return name if is_valid_korean_name_structure(name) else None


def _uncertain_person_value(value: Any, *, explicit_name: bool, name_field: bool = False) -> bool:
    """Decide send safety separately from extracting a single name token."""
    if not isinstance(value, str):
        return True
    text = unicodedata.normalize("NFKC", value).strip()
    if not text or _MASKED_NAME_VALUE_RE.fullmatch(text):
        return False
    if _name_like_value(text):
        # Single-name context is checked by the normal detector.
        return False
    if explicit_name or name_field:
        # A grammatical name suffix supplies context even when its subject is
        # unknown. Inspect only a bounded name window, not arbitrary titles or
        # an exception vocabulary. Role-only keys retain their existing contract.
        for pattern in (_LEADING_NAME_VALUE_RE, _COMPOSITE_NAME_PARTICLE_RE):
            match = pattern.match(text)
            if match and is_valid_korean_name_structure(match.group("name")):
                return True
    # Name markers do not change a clearly non-name Korean value into a person.
    # Keep the same value-shape boundary for roles and explicit name fields;
    # foreign scripts, punctuation and non-string values remain uncertain.
    # A name-shaped first word alone cannot establish the type of a multiword
    # organization. Raw text is still scanned, with no new noun exemptions.
    compact = []
    for char in text:
        if "가" <= char <= "힣":
            if len(compact) < 5:
                compact.append(char)
        elif not char.isspace():
            return True
    # A short explicit name can have an unfamiliar surname or be transliterated.
    # Failure of the surname grammar is not proof of a non-person value.
    return len(compact) <= 4 and (
        explicit_name or is_valid_korean_name_structure("".join(compact))
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
    "SYS_KOREAN_RAG_REVIEW": KOREAN_RAG_REVIEW_SYSTEM_PROMPT,
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


def _collect_texts_from_value(
    value, path: str = "", *, _uncertain_paths: List[str] | None = None,
) -> List[Tuple[str, str]]:
    """값에서 (경로, 검사할 텍스트) 쌍을 수집한다.

    사전:
      - 원본 문자열 값은 항상 검사.
      - 사람 표지 키의 단일 이름 꼴 값과 식별번호 종류 키에 문맥을 합성.
      - 불확실 성명 필드는 원문 없이 _uncertain_paths에 경로만 기록(TK-56).
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
            results.extend(_collect_texts_from_value(decoded, path, _uncertain_paths=_uncertain_paths))
        else:
            # 일반 문자열 값
            results.append((path, value))

    elif isinstance(value, dict):
        # 각 키-값 쌍을 검사
        str_items: List[Tuple[str, str]] = []  # 형제 문자열 (key, value) 수집용
        for key, item in value.items():
            current_path = f"{path}.{key}" if path else str(key)
            label = _person_label_for_key(key)
            marker = _has_name_field_marker(key)
            if (label or marker) and _uncertain_person_value(
                item, explicit_name=bool(label and marker), name_field=marker,
            ):
                if _uncertain_paths is not None:
                    _uncertain_paths.append(current_path)

            if isinstance(item, str):
                decoded = _try_json_parse(item)
                if decoded is not None:
                    # JSON 문자열이면 파싱하여 재귀 검사
                    results.extend(_collect_texts_from_value(
                        decoded, current_path, _uncertain_paths=_uncertain_paths,
                    ))
                else:
                    # 원본 값 검사
                    results.append((current_path, item))
                    # 식별번호 종류 키의 기존 문맥은 유지한다. 사람 이름 키는 이름 꼴 값에만
                    # 문맥을 붙여 장소·직무·법인 값의 차단을 늘리지 않는다.
                    if key in _PII_TYPE_KEYS:
                        results.append((current_path, f"{key}: {item}"))
                    else:
                        name = _name_like_value(item)
                        if (label or marker) and name:
                            label = label or "이름"
                            detector_label = "이름" if label.isascii() else label
                            results.append((current_path, f"{detector_label}: {name}"))
                    str_items.append((key, item))
            else:
                # 비문자열 값은 재귀
                results.extend(_collect_texts_from_value(
                    item, current_path, _uncertain_paths=_uncertain_paths,
                ))

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
                    results.extend(_collect_texts_from_value(
                        decoded, current_path, _uncertain_paths=_uncertain_paths,
                    ))
                else:
                    results.append((current_path, item))
                    str_elements.append(item)
            else:
                results.extend(_collect_texts_from_value(
                    item, current_path, _uncertain_paths=_uncertain_paths,
                ))

        # 배열 이웃 결합:
        # '선행 원소가 라벨이고 후행 원소가 이름 구조일 때만' 결합 문맥을 생성한다 (TK-52 2절)
        # 예: ["원고", "편하람"] -> 결합 / ["원고", "피고", "증인"] -> 결합 안 함
        for i in range(len(str_elements) - 1):
            w1, w2 = str_elements[i], str_elements[i + 1]
            if w1 in CONTEXT_LABEL_KEYS and w2 not in CONTEXT_LABEL_KEYS and is_valid_korean_name_structure(w2):
                neighbor_path = f"{path}.__neighbors__[{i}]" if path else f"__neighbors__[{i}]"
                results.append((neighbor_path, f"{w1} {w2}"))

    return results


def _walk_fields(value, path="", *, _uncertain_paths=None):
    """필드 경로(path)와 함께 문자열 값들을 추출한다 (R8-A 강화 버전).

    TK-51/TK-56: 원본 값과 유효한 이름 문맥, 형제/배열 문맥을 추출한다.
    라벨 키 정의는 detector.py의 PARTY_AND_TITLE_LABELS에서 단일 출처로 가져온다.
    """
    for collected_path, collected_text in _collect_texts_from_value(
        value, path, _uncertain_paths=_uncertain_paths,
    ):
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
        uncertain_paths = []
        for path, text in _walk_fields(
            {"__original_system__": _original_system}, _uncertain_paths=uncertain_paths,
        ):
            matches = [m for m in detect(text) if m.confidence >= 0.6]
            for m in matches:
                kinds[m.kind] += 1
                # 원본 system은 사용자 제공 동적 값이므로 등록 상수 면책 없음
                blocked_kinds[m.kind] += 1
                detected_paths.add(f"original_system.{path}")
        if uncertain_paths:
            kinds["PERSON"] += len(uncertain_paths)
            blocked_kinds["PERSON"] += len(uncertain_paths)
            detected_paths.update(f"original_system.{path}" for path in uncertain_paths)

    # 최상위 payload 필드를 개별 순회하여 경로 기반 등록 판정이 정확하게 동작하도록 함
    # (payload 전체를 _walk_fields에 넘기면 최상위 형제 결합이 경로 판정을 혼동시킴)
    for top_key, top_value in payload.items():
        uncertain_paths = []
        for path, text in _walk_fields(top_value, top_key, _uncertain_paths=uncertain_paths):
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
        if uncertain_paths:
            kinds["PERSON"] += len(uncertain_paths)
            detected_paths.update(uncertain_paths)
            is_verified_static_source = (
                top_key == "system" and is_registered_system_prompt(request.system)
            ) or (top_key == "schema" and is_registered_schema(request.schema))
            target = static_fp_kinds if is_verified_static_source else blocked_kinds
            target["PERSON"] += len(uncertain_paths)

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
