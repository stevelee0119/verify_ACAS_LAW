"""Provider·Source 설정 엔드포인트 (제18.1장, 제21.2장).

API Key 값 자체는 어떤 응답에도 포함하지 않는다. 보유 여부만 노출한다.
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from packages.common.config import get_settings
from packages.llm_router import LLMRouter

from ..schemas import ProviderOut, ProviderPatch
from ..services import get_registry

router = APIRouter(tags=["settings"])


@router.get("/settings/providers", response_model=List[ProviderOut])
def list_providers() -> List[ProviderOut]:
    settings = get_settings()
    return [
        ProviderOut(
            name=name,
            enabled=config.enabled,
            kind=config.kind,
            model=config.model,
            has_key=config.has_key,
            key_env=config.api_key_env,
        )
        for name, config in settings.providers.items()
    ]


@router.patch("/settings/providers/{name}", response_model=ProviderOut)
def patch_provider(name: str, payload: ProviderPatch) -> ProviderOut:
    settings = get_settings()
    config = settings.providers.get(name)
    if config is None:
        raise HTTPException(404, "Provider를 찾을 수 없다")
    if payload.enabled is not None:
        config.enabled = payload.enabled
    if payload.model is not None:
        config.model = payload.model
    return ProviderOut(
        name=name, enabled=config.enabled, kind=config.kind, model=config.model,
        has_key=config.has_key, key_env=config.api_key_env,
    )


@router.get("/settings/sources")
def list_sources() -> Dict[str, Any]:
    registry = get_registry()
    return {
        "adapters": [s.to_dict() for s in registry.states()],
        "local_mirror_available": registry.mirror.available,
        "notice": "Key 미설정·장애 Source는 전체 검증을 중단시키지 않고 해당 항목만 UNVERIFIED로 표시한다.",
    }


@router.get("/settings/runtime")
def runtime_info() -> Dict[str, Any]:
    settings = get_settings()
    router_instance = LLMRouter()
    return {
        "app_name": settings.app_name,
        "version": settings.version,
        "rule_version": settings.rule_version,
        "prompt_version": settings.prompt_version,
        "model_config_version": settings.model_config_version(),
        "default_external_ai_policy": settings.default_external_ai_policy,
        "default_profile": settings.default_profile,
        "allow_network": settings.allow_network,
        "allow_sealed_reveal": settings.allow_sealed_reveal,
        "available_providers": router_instance.available_providers(),
        "max_upload_mb": settings.max_upload_mb,
        "monthly_budget_usd": settings.monthly_budget_usd,
    }
