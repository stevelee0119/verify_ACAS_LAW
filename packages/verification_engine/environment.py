"""실행 환경 사전 점검(preflight)과 환경 지문(v5 2-1).

같은 문서라도 법령 DB 키·AI 공급자·한국어 OCR·네트워크 유무에 따라 결과가 달라진다. 두 실행을 비교해 '회귀 0건'이라고
말하려면 두 실행의 환경이 같아야 한다. 이 모듈은 실행 환경을 점검해 run_manifest.environment에 남기고,
비교에 쓰는 환경 지문(fingerprint)을 만든다.

- 비밀값(API 키)은 기록하지 않는다. 있는지 여부만 기록한다.
- 환경 지문에는 프로그램·규칙 버전을 넣지 않는다(코드 변화와 환경 변화를 구분하기 위해). 모델 ID는 결과를 바꾸므로 넣는다.
- 필수 자원: 법령 DB(국가법령정보 키 + 네트워크), AI 공급자 3종, 한국어 OCR(tesseract kor). 하나라도 없으면
  '불완전 환경'이고, 없는 자원이 좌우하는 영역을 '비교 불가 영역'으로 적는다.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional

AI_PROVIDERS = ("anthropic", "openai", "gemini")

# 없는 자원 → 그 자원 없이는 평가할 수 없는 영역
AREAS = {
    "law_db": ["판례·법령 공식 DB 대조(존재·서지·인용문·취지)", "조문 수치·부존재 조문", "행위시법 공식 연혁 대조"],
    "ai_models": ["판례 의미·적용 검토(semantic_review)", "모델 지적 모순 재검증(model_fact_reconcile)",
                  "AI 작성 판별의 모델 의견"],
    "korean_ocr": ["스캔·이미지 문서 본문 검사", "독립 OCR 레이어 대조"],
}


def _ocr_state(lang: str) -> Dict[str, Any]:
    try:
        from packages.document_engine.ocr_readiness import probe_tesseract

        probe = probe_tesseract(lang)
    except Exception as exc:  # noqa: BLE001 - 점검 실패 자체를 기록한다
        return {"status": f"PROBE_FAILED:{type(exc).__name__}", "version": "", "kor": False, "osd": False}
    languages = set(probe.get("languages") or [])
    return {"status": probe.get("status"), "version": probe.get("version", ""),
            "kor": "kor" in languages, "osd": "osd" in languages}


def preflight(settings: Any = None, registry: Any = None, router: Any = None) -> Dict[str, Any]:
    """현재 프로세스의 실행 환경을 점검한다. registry·router를 주면 그 상태(출처 어댑터·공급자)를 그대로 쓴다."""
    from packages.common.config import get_settings

    settings = settings or get_settings()
    network = os.getenv("LV_ALLOW_NETWORK", "1") != "0"
    law_key = bool(os.getenv("LV_LAW_GO_KR_OC"))
    sources: Dict[str, str] = {}
    if registry is not None:
        try:
            sources = {state.name: str(getattr(state.status, "value", state.status)) for state in registry.states()}
        except Exception as exc:  # noqa: BLE001
            sources = {"error": type(exc).__name__}
    providers: Dict[str, Dict[str, Any]] = {}
    for name in AI_PROVIDERS:
        config = (getattr(settings, "providers", {}) or {}).get(name)
        providers[name] = {"key": bool(config and config.has_key), "enabled": bool(config and config.enabled),
                           "model": getattr(config, "model", "") if config else ""}
    usable: Optional[List[str]] = None
    if router is not None:
        try:
            usable = sorted(router.available_providers())
        except Exception:  # noqa: BLE001
            usable = None
    ai_ready = [n for n, p in providers.items() if p["key"] and p["enabled"] and network
                and (usable is None or n in usable)]
    ocr = _ocr_state(getattr(settings, "ocr_lang", None) or "kor+eng")
    resources = {
        "law_db": law_key and network and sources.get("law_go_kr", "READY") == "READY",
        "ai_models": len(ai_ready) == len(AI_PROVIDERS),
        "korean_ocr": bool(ocr.get("kor")) and ocr.get("status") == "READY",
    }
    missing = [name for name, ok in resources.items() if not ok]
    environment = {
        "network": network,
        "law_db": {"key": law_key, "status": sources.get("law_go_kr") or ("READY" if law_key and network else
                                                                          "MISSING_KEY" if not law_key else "NETWORK_DISABLED")},
        "ai_providers": providers,
        "ai_providers_ready": ai_ready,
        "sources": sources,
        "ocr": ocr,
        "resources": resources,
        "complete": not missing,
        "missing_required": missing,
        "incomparable_areas": [area for name in missing for area in AREAS[name]],
    }
    environment["fingerprint"] = fingerprint(environment)
    return environment


def fingerprint(environment: Dict[str, Any]) -> str:
    """환경 지문: 결과에 영향을 주는 환경 요소만 정규화해 해시한다(비밀값·코드 버전 제외)."""
    ocr = environment.get("ocr") or {}
    basis = {
        "network": bool(environment.get("network")),
        "law_db": (environment.get("law_db") or {}).get("status"),
        "ai": sorted(f"{name}:{(environment.get('ai_providers') or {}).get(name, {}).get('model', '')}"
                     for name in environment.get("ai_providers_ready") or []),
        "sources": dict(sorted((environment.get("sources") or {}).items())),
        "ocr": [ocr.get("status"), (ocr.get("version") or "").split()[-1:] or "", bool(ocr.get("kor")),
                bool(ocr.get("osd"))],
    }
    digest = hashlib.sha256(json.dumps(basis, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return digest[:16]


def incomplete_banner(environment: Optional[Dict[str, Any]]) -> Optional[str]:
    """불완전 환경이면 보고서 맨 앞에 둘 문구. 환경 기록이 없으면 그 사실을 알린다."""
    if not environment:
        return "환경 기록 없음 — 이 실행의 환경을 알 수 없어 다른 실행과 비교할 수 없다"
    if environment.get("complete"):
        return None
    return ("불완전 환경 — 없는 필수 자원: " + ", ".join(environment.get("missing_required") or []) +
            ". 비교 불가 영역: " + "; ".join(environment.get("incomparable_areas") or []))


def comparability(before: Optional[Dict[str, Any]], after: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """두 실행의 환경 비교. 지문이 같을 때만 '회귀 0건' 같은 결론을 쓸 수 있다."""
    b, a = before or {}, after or {}
    same = bool(b.get("fingerprint")) and b.get("fingerprint") == a.get("fingerprint")
    areas: List[str] = []
    if not same:
        for name, labels in AREAS.items():
            rb, ra = (b.get("resources") or {}).get(name), (a.get("resources") or {}).get(name)
            if not (rb and ra):
                areas += [f"{label} ({name}: 이전 {'있음' if rb else '없음' if rb is False else '미기록'}, "
                          f"현재 {'있음' if ra else '없음' if ra is False else '미기록'})" for label in labels]
        if not areas:
            areas.append("필수 자원은 양쪽에 있으나 세부 환경(모델 ID·출처 상태·OCR 버전)이 다름")
    return {"same_environment": same, "fingerprints": [b.get("fingerprint"), a.get("fingerprint")],
            "incomparable_areas": areas}
