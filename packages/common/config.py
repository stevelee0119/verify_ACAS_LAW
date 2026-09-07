"""설정 로딩. 제21.2장에 따라 API Key는 코드/DB 평문에 두지 않고 환경변수·Secret에서 읽는다."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
def data_dir() -> Path:
    """LV_DATA_DIR을 매번 읽는다. 설정 초기화 후 변경이 반영되어야 한다."""
    return Path(os.getenv("LV_DATA_DIR") or (REPO_ROOT / "data"))


DATA_DIR = data_dir()


FALSE_VALUES = {"0", "false", "no", "off", ""}


def _flag(name: str, default: bool) -> bool:
    """환경변수를 불리언으로 읽는다. 미설정이면 default를 쓴다."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in FALSE_VALUES


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
    database_url: str = field(
        default_factory=lambda: os.getenv("LV_DATABASE_URL") or f"sqlite:///{data_dir()}/legal_verifier.db"
    )
    storage_root: Path = field(
        default_factory=lambda: Path(os.getenv("LV_STORAGE_ROOT") or str(data_dir() / "storage"))
    )
    max_upload_mb: int = field(default_factory=lambda: int(os.getenv("LV_MAX_UPLOAD_MB", "80")))
    default_external_ai_policy: str = field(default_factory=lambda: os.getenv("LV_DEFAULT_AI_POLICY", "MASKED"))
    default_profile: str = field(default_factory=lambda: os.getenv("LV_DEFAULT_PROFILE", "STANDARD"))
    pseudonym_secret: str = field(
        default_factory=lambda: os.getenv("LV_PSEUDONYM_SECRET", "dev-only-not-for-production")
    )
    allow_network: bool = field(default_factory=lambda: _flag("LV_ALLOW_NETWORK", True))
    http_timeout: float = field(default_factory=lambda: float(os.getenv("LV_HTTP_TIMEOUT", "12")))
    law_go_kr_oc: Optional[str] = field(default_factory=lambda: os.getenv("LV_LAW_GO_KR_OC"))
    kci_key: Optional[str] = field(default_factory=lambda: os.getenv("LV_KCI_KEY"))
    semantic_scholar_key: Optional[str] = field(default_factory=lambda: os.getenv("LV_SEMANTIC_SCHOLAR_KEY"))
    crossref_mailto: Optional[str] = field(default_factory=lambda: os.getenv("LV_CROSSREF_MAILTO"))
    monthly_budget_usd: float = field(default_factory=lambda: float(os.getenv("LV_MONTHLY_BUDGET_USD", "0")))
    # --- OCR (제3.2장 교체 가능한 OCR Adapter) ---
    ocr_lang: str = field(default_factory=lambda: os.getenv("LV_OCR_LANG", "kor+eng"))
    ocr_psm: int = field(default_factory=lambda: int(os.getenv("LV_OCR_PSM", "6")))
    ocr_dpi: int = field(default_factory=lambda: int(os.getenv("LV_OCR_DPI", "200")))
    ocr_min_confidence: float = field(default_factory=lambda: float(os.getenv("LV_OCR_MIN_CONFIDENCE", "0.55")))
    ocr_max_pages: int = field(default_factory=lambda: int(os.getenv("LV_OCR_MAX_PAGES", "20")))
    independent_ocr_pages: int = field(default_factory=lambda: int(os.getenv("LV_INDEPENDENT_OCR_PAGES", "3")))
    independent_ocr_mode: str = field(default_factory=lambda: os.getenv("LV_INDEPENDENT_OCR", "auto"))
    """auto: 위험 신호가 있는 문서에만 수행 / always / off (제7.3장 독립 OCR)."""
    # --- Worker (제3.1장) ---
    celery_broker: str = field(default_factory=lambda: os.getenv("LV_CELERY_BROKER", ""))
    celery_backend: str = field(default_factory=lambda: os.getenv("LV_CELERY_BACKEND", ""))
    worker_mode: str = field(default_factory=lambda: os.getenv("LV_WORKER_MODE", "auto"))
    """auto: 브로커가 설정되면 Celery, 아니면 인프로세스 / celery / inprocess."""
    rule_version: str = "2026.08.25"
    prompt_version: str = "v0.2"
    seal_meta_message_content: bool = field(default_factory=lambda: _flag("LV_SEAL_META", True))
    allow_sealed_reveal: bool = field(default_factory=lambda: _flag("LV_ALLOW_SEALED_REVEAL", True))
    providers: Dict[str, ProviderConfig] = field(default_factory=dict)
    pricing: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        data_dir().mkdir(parents=True, exist_ok=True)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        if not self.providers:
            self.providers = _default_providers()
        if not self.pricing:
            self.pricing = _load_json(CONFIG_DIR / "pricing.json")

    def model_config_version(self) -> str:
        active = sorted(p.name + ":" + p.model for p in self.providers.values() if p.enabled and p.has_key)
        return "|".join(active) or "none"


def _default_providers() -> Dict[str, ProviderConfig]:
    """providers.json을 읽고 LV_<PROVIDER>_MODEL 환경변수로 모델을 덮어쓴다.

    모델 ID는 공급자 사정으로 바뀌므로 배포본 수정 없이 교체할 수 있어야 한다.
    """
    raw = _load_json(CONFIG_DIR / "providers.json")
    out: Dict[str, ProviderConfig] = {}
    for name, cfg in raw.items():
        config = ProviderConfig(name=name, **cfg)
        override = os.getenv(f"LV_{name.upper()}_MODEL")
        if override:
            config.model = override
        out[name] = config
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
