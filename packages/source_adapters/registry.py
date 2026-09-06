"""Source Adapter 레지스트리와 상태 보고 (제10장, 제20.3장 '사용하지 못한 Source')."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from packages.common.enums import AdapterStatus

from .academic import CrossrefAdapter, KCIAdapter, OpenAlexAdapter, SemanticScholarAdapter
from .base import AdapterResponse, SourceAdapter
from .law_go_kr import LawGoKrAdapter
from .local_mirror import LocalLegalMirror


@dataclass
class AdapterState:
    name: str
    kind: str
    status: AdapterStatus
    requires_key: bool
    key_env: str
    homepage: str
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "status": str(self.status),
            "requires_key": self.requires_key,
            "key_env": self.key_env,
            "homepage": self.homepage,
            "note": self.note,
        }


class SourceRegistry:
    def __init__(self, *, disabled: Optional[List[str]] = None) -> None:
        disabled = set(disabled or [])
        self.mirror = LocalLegalMirror()
        self.legal: List[SourceAdapter] = [
            LawGoKrAdapter(enabled="law_go_kr" not in disabled, mirror=self.mirror)
        ]
        self.academic: List[SourceAdapter] = [
            KCIAdapter(enabled="kci" not in disabled),
            OpenAlexAdapter(enabled="openalex" not in disabled),
            SemanticScholarAdapter(enabled="semantic_scholar" not in disabled),
            CrossrefAdapter(enabled="crossref" not in disabled),
        ]

    @property
    def all(self) -> List[SourceAdapter]:
        return self.legal + self.academic

    def get(self, name: str) -> Optional[SourceAdapter]:
        return next((a for a in self.all if a.name == name), None)

    @property
    def law(self) -> LawGoKrAdapter:
        return self.legal[0]  # type: ignore[return-value]

    def states(self) -> List[AdapterState]:
        out: List[AdapterState] = []
        for adapter in self.all:
            status = adapter.status()
            note = ""
            if adapter.name == "law_go_kr" and self.mirror.available:
                note = "내부 Mirror 사용 가능"
                if status != AdapterStatus.READY:
                    note += " (외부 API는 비활성이나 Mirror로 일부 검증 가능)"
            if status == AdapterStatus.MISSING_KEY:
                note = note or f"{adapter.key_env} 환경변수 필요. 해당 항목은 UNVERIFIED로 표시된다."
            out.append(
                AdapterState(
                    name=adapter.name,
                    kind=adapter.kind,
                    status=status,
                    requires_key=adapter.requires_key,
                    key_env=adapter.key_env,
                    homepage=adapter.homepage,
                    note=note,
                )
            )
        return out

    def unavailable(self) -> List[Dict[str, Any]]:
        return [s.to_dict() for s in self.states() if s.status != AdapterStatus.READY]

    # -- 학술 교차검증 ------------------------------------------------------
    def search_academic(self, title: str, *, doi: Optional[str] = None, prefer_korean: bool = True) -> List[AdapterResponse]:
        """국내 법률논문은 KCI를 우선하고 DOI·국제 문헌은 Crossref/OpenAlex를 보조로 쓴다."""
        order = list(self.academic)
        if not prefer_korean:
            order = order[1:] + order[:1]
        responses: List[AdapterResponse] = []
        for adapter in order:
            response = adapter.search(title, doi=doi)
            responses.append(response)
            if response.found and len(responses) >= 2:
                break
        return responses
