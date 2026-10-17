"""Task-based cost controls. Source text never selects a model or skips legal review."""
from __future__ import annotations

import hashlib
import json
from copy import copy
from dataclasses import replace

from packages.common.enums import LLMRole


def sampled(request, percent):
    """Stable sampling, independent of a model's confidence or reported verdict."""
    digest = hashlib.sha256((request.system + "\0" + request.user).encode()).digest()
    return int.from_bytes(digest[:4], "big") % 100 < percent


def task_provider(provider, role, request, settings):
    from .providers import PROVIDER_CLASSES

    if not getattr(settings, "llm_efficient_routing", False):
        return provider
    # Custom adapters/test doubles retain their own model and mutable state.
    if type(provider) not in PROVIDER_CLASSES.values():
        return provider
    purpose = ""
    if provider.name == "anthropic" and request.model_tier == "escalation":
        purpose = "anthropic_escalation"
    elif provider.name == "openai":
        purpose = ("openai_extraction" if role == LLMRole.LOW_COST_EXTRACTOR
                   or request.input_contract == "ai_document_v1" else "openai_review")
    model = getattr(settings, "llm_routing", {}).get(purpose)
    overrides = getattr(settings, "llm_model_overrides", {})
    explicit_task_model = overrides.get(purpose)
    if purpose and not explicit_task_model:
        default_model = getattr(settings, "llm_default_models", {}).get(provider.name)
        if (overrides.get(provider.name)
                or provider.config.model != default_model):
            return provider  # Explicit operator/API model choices are authoritative.
    if not model or model == provider.config.model:
        return provider
    selected = copy(provider)
    selected.config = replace(provider.config, model=model)
    return selected


def request_key(request, provider, role, policy, expected_task):
    # The cache is scoped to a single pipeline run and never persisted.
    payload = [provider.name, provider.config.model, str(role), str(policy), expected_task,
               request.system, request.user, request.schema, request.max_tokens,
               request.temperature, request.input_contract, request.model_tier, request.metadata]
    try:
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    except (TypeError, ValueError):
        return None  # Opaque metadata is never a cache identity.
    return hashlib.sha256(encoded).hexdigest()


def needs_additional_review(answer):
    if not answer.used or answer.quarantined or not isinstance(answer.parsed, dict):
        return True
    verdict = answer.parsed.get("verdict")
    # Authorship is advisory. Any affirmative claim receives a second opinion.
    return verdict not in {"UNCERTAIN", "HUMAN_AUTHORED_LIKELY"}


def conflicting(answers):
    signatures = []
    for answer in answers:
        if not answer.used or not isinstance(answer.parsed, dict):
            continue
        value = answer.parsed
        if "rows" in value:
            signatures.append(tuple(sorted((str(r.get("item_id")), r.get("validity_verdict"))
                                           for r in value["rows"])))
        else:
            signatures.append(value.get("status") or value.get("verdict"))
    return len(set(signatures)) > 1


def complete_argument_reviews(request, answers):
    """Two empty/partial envelopes do not satisfy item-level independent review."""
    try:
        expected = {str(item["item_id"]) for item in json.loads(request.user)["items"]}
    except (KeyError, ValueError, TypeError):
        return False
    if not expected:
        return False
    for item_id in expected:
        families = {answer.executions[-1].provider for answer in answers if answer.used
                    and answer.executions and isinstance(answer.parsed, dict)
                    and any(str(row.get("item_id")) == item_id
                            for row in answer.parsed.get("rows", []))}
        if len(families) < 2:
            return False
    return True
