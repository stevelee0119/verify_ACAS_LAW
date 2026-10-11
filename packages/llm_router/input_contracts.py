"""Closed first-party input envelopes; free-text evidence retains its contract.

These shapes are separate from output schemas and confer no privacy exemption.
Legacy requests without a contract keep their existing behavior, including
unknown role-key and encoded-evidence residuals.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType


@dataclass(frozen=True)
class _Object:
    fields: tuple
    required: frozenset


@dataclass(frozen=True)
class _Array:
    item: object


@dataclass(frozen=True)
class _Literal:
    choices: tuple


def _object(fields, *, optional=()):
    return _Object(tuple(fields.items()), frozenset(fields) - frozenset(optional))


_REVIEW_CONTEXT = _object({
    "jurisdiction": _Literal(("대한민국",)),
    "reference_date": (str, type(None)),
    "reference_date_status": _Literal(("EXPLICIT", "UNSPECIFIED")),
})
_COVERAGE = _object({
    "total_chars": int, "inspected_chars": int,
    "sampling_mode": _Literal(("full_text", "head_middle_tail")),
    "is_full_coverage": bool, "omitted_chars": int, "char_limit": int,
    "quote_masked_chars": int,
    "scope": _Literal(("BODY_WITH_QUOTES_AND_INSTRUCTIONS_EXCLUDED",)),
    "requested_chars": int, "model_executed": bool,
})
_REFERENCE = _object({"source_id": str, "title": str, "text": str, "page": (int, type(None))})
_CLAIM_REFERENCE = _object({"source_id": str, "text": str, "page": int}, optional=("source_id", "page"))
_ARGUMENT_ITEM = _object({
    "item_id": int, "page": int, "cited_case": str, "확인 상태": str,
    "surrounding_context_and_claim": str, "원문 대조(어절 단위, 원문 기준)": str,
}, optional=("원문 대조(어절 단위, 원문 기준)",))
_SHAPES = MappingProxyType({
    "ai_document_v1": _object({
        "document_filename": str, "metadata_ai_hint": bool,
        "document_sample_text": str, "document_coverage": _COVERAGE,
    }),
    "reference_review_v1": _object({
        "document": str, "untrusted_references": _Array(_REFERENCE),
        "system_instructions": _REVIEW_CONTEXT,
    }, optional=("system_instructions",)),
    "claim_review_v1": _object({
        "claim_id": str, "claim_text": str, "reference_sources": _Array(_CLAIM_REFERENCE),
        "system_instructions": _REVIEW_CONTEXT,
    }, optional=("system_instructions",)),
    "argument_review_v1": _object({"items": _Array(_ARGUMENT_ITEM)}),
})


def _matches_shape(value, shape):
    if isinstance(shape, _Object):
        if type(value) is not dict:
            return False
        fields = dict(shape.fields)
        return (shape.required <= value.keys() <= fields.keys()
                and all(_matches_shape(item, fields[key]) for key, item in value.items()))
    if isinstance(shape, _Array):
        return type(value) is list and all(_matches_shape(item, shape.item) for item in value)
    if isinstance(shape, _Literal):
        return any(type(value) is type(choice) and value == choice for choice in shape.choices)
    types = shape if isinstance(shape, tuple) else (shape,)
    return type(value) in types


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate input key")
        result[key] = value
    return result


def _consumer_binding(contract):
    # Imports stay lazy: these consumers themselves construct LLMRequest.
    if contract == "ai_document_v1":
        from packages.verification_engine.ai_document_detector import AI_DETECTOR_SYSTEM_PROMPT, _DETECTOR_SCHEMA
        return (AI_DETECTOR_SYSTEM_PROMPT,), _DETECTOR_SCHEMA
    if contract in {"reference_review_v1", "claim_review_v1"}:
        from packages.rag_engine.review import ENVELOPE_SCHEMA, KOREAN_RAG_REVIEW_SYSTEM_PROMPT, RAG_REVIEW_SYSTEM_PROMPT
        return (RAG_REVIEW_SYSTEM_PROMPT, KOREAN_RAG_REVIEW_SYSTEM_PROMPT), ENVELOPE_SCHEMA
    if contract == "argument_review_v1":
        from packages.legal_engine.argument_validity_verifier import _OPINION_SCHEMA, _OPINION_SYSTEM
        return (_OPINION_SYSTEM,), _OPINION_SCHEMA
    raise ValueError("Unknown input contract")


def valid_input_contract(request, *, original_system=None):
    """Validate declared structure only; the privacy walker still scans all text."""
    contract = request.input_contract
    if contract is None:
        return True
    if type(contract) is not str or contract not in _SHAPES:
        return False
    try:
        systems, output_schema = _consumer_binding(contract)
        system = request.system if original_system is None else original_system
        if system not in systems or request.schema != output_schema:
            return False
        payload = json.loads(request.user, object_pairs_hook=_unique_object)
        if not _matches_shape(payload, _SHAPES[contract]):
            return False
        context = payload.get("system_instructions")
        if context:
            reference_date = context["reference_date"]
            if reference_date is not None:
                if date.fromisoformat(reference_date).isoformat() != reference_date:
                    return False
            if context["reference_date_status"] != ("EXPLICIT" if reference_date else "UNSPECIFIED"):
                return False
        if contract == "claim_review_v1":
            from packages.rag_engine.review import validate_claim_request_payload
            return validate_claim_request_payload(payload)
        return True
    except (TypeError, ValueError, KeyError, RecursionError):
        return False
