"""설정 로딩. 제21.2장에 따라 API Key는 코드/DB 평문에 두지 않고 환경변수·Secret에서 읽는다."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
DATA_DIR = Path(os.getenv("LV_DATA_DIR", REPO_ROOT / "data"))


def _load_json(path: Path) -> Dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


@dataclass
class ProviderConfig:
    name: str
    enabled: bool = False
    api_key_env: str = ""
    model: str = ""
    base_url: str = ""
    kind: str = "cloud"  # cloud | local

    @property
    def api_key(self) -> Optional[str]:
        return os.getenv(self.api_key_env) if self.api_key_env else None

    @property
    def has_key(self) -> bool:
        if self.kind == "local":
            return True
        return bool(self.api_key)


@dataclass
class Settings:
    app_name: str = "Legal Document Verification Platform"
    version: str = "0.2.0"
    database_url: str = field(default_factory=lambda: os.getenv("LV_DATABASE_URL", f"sqlite:///{DATA_DIR}/legal_verifier.db"))
    storage_root: Path = field(default_factory=lambda: Path(os.getenv("LV_STORAGE_ROOT", str(DATA_DIR / "storage"))))
    max_upload_mb: int = int(os.getenv("LV_MAX_UPLOAD_MB", "80"))
    default_external_ai_policy: str = os.getenv("LV_DEFAULT_AI_POLICY", "MASKED")
    default_profile: str = os.getenv("LV_DEFAULT_PROFILE", "STANDARD")
    pseudonym_secret: str = os.getenv("LV_PSEUDONYM_SECRET", "dev-only-not-for-production")
    allow_network: bool = os.getenv("LV_ALLOW_NETWORK", "1") not in ("0", "false", "False")
    http_timeout: float = float(os.getenv("LV_HTTP_TIMEOUT", "12"))
    law_go_kr_oc: Optional[str] = os.getenv("LV_LAW_GO_KR_OC")
    kci_key: Optional[str] = os.getenv("LV_KCI_KEY")
    semantic_scholar_key: Optional[str] = os.getenv("LV_SEMANTIC_SCHOLAR_KEY")
    crossref_mailto: Optional[str] = os.getenv("LV_CROSSREF_MAILTO")
    monthly_budget_usd: float = float(os.getenv("LV_MONTHLY_BUDGET_USD", "0"))
    # --- OCR (제3.2장 교체 가능한 OCR Adapter) ---
    ocr_lang: str = os.getenv("LV_OCR_LANG", "kor+eng")
    ocr_psm: int = int(os.getenv("LV_OCR_PSM", "6"))
    ocr_dpi: int = int(os.getenv("LV_OCR_DPI", "200"))
    ocr_min_confidence: float = float(os.getenv("LV_OCR_MIN_CONFIDENCE", "0.55"))
    ocr_max_pages: int = int(os.getenv("LV_OCR_MAX_PAGES", "20"))
    independent_ocr_pages: int = int(os.getenv("LV_INDEPENDENT_OCR_PAGES", "3"))
    independent_ocr_mode: str = os.getenv("LV_INDEPENDENT_OCR", "auto")
    """auto: 위험 신호가 있는 문서에만 수행 / always / off (제7.3장 독립 OCR)."""
    # --- Worker (제3.1장) ---
    celery_broker: str = os.getenv("LV_CELERY_BROKER", "")
    celery_backend: str = os.getenv("LV_CELERY_BACKEND", "")
    worker_mode: str = os.getenv("LV_WORKER_MODE", "auto")
    """auto: 브로커가 설정되면 Celery, 아니면 인프로세스 / celery / inprocess."""
    rule_version: str = "2026.08.25"
    prompt_version: str = "v0.2"
    seal_meta_message_content: bool = os.getenv("LV_SEAL_META", "1") not in ("0", "false")
    allow_sealed_reveal: bool = os.getenv("LV_ALLOW_SEALED_REVEAL", "1") not in ("0", "false")
    providers: Dict[str, ProviderConfig] = field(default_factory=dict)
    pricing: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        if not self.providers:
            self.providers = _default_providers()
        if not self.pricing:
            self.pricing = _load_json(CONFIG_DIR / "pricing.json")

    def model_config_version(self) -> str:
        active = sorted(p.name + ":" + p.model for p in self.providers.values() if p.enabled and p.has_key)
        return "|".join(active) or "none"


def _default_providers() -> Dict[str, ProviderConfig]:
    raw = _load_json(CONFIG_DIR / "providers.json")
    out: Dict[str, ProviderConfig] = {}
    for name, cfg in raw.items():
        out[name] = ProviderConfig(name=name, **cfg)
    return out


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:  # 테스트용
    global _settings
    _settings = None
