"""내부 법령·판례 Mirror (제23장 LocalLegalMirror).

폐쇄망 배포 및 오프라인 테스트에서 공식 Source를 대체한다.
데이터는 config/legal_mirror/*.json 에 두며, 없으면 조용히 비활성 상태가 된다.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

from packages.common.config import CONFIG_DIR
from .legal_history import legal_date


def _canon(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


class LocalLegalMirror:
    source_url = "local://legal_mirror"

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root or CONFIG_DIR / "legal_mirror")
        self._cases: Dict[str, Dict[str, Any]] = {}
        self._laws: List[Dict[str, Any]] = []
        self._load()

    @property
    def available(self) -> bool:
        return bool(self._cases or self._laws)

    def _load(self) -> None:
        if not self.root.exists():
            return
        cases_file = self.root / "cases.json"
        laws_file = self.root / "laws.json"
        if cases_file.exists():
            try:
                for item in json.loads(cases_file.read_text(encoding="utf-8")):
                    key = _canon(item.get("case_number", ""))
                    if key:
                        self._cases[key] = item
            except Exception:
                pass
        if laws_file.exists():
            try:
                self._laws = json.loads(laws_file.read_text(encoding="utf-8"))
            except Exception:
                self._laws = []

    def find_case(self, case_number: str) -> Optional[Dict[str, Any]]:
        return self._cases.get(_canon(case_number))

    def find_law(
        self, law_name: str, *, article: Optional[str] = None, as_of: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        target = _canon(law_name)
        candidates = [law for law in self._laws if _canon(law.get("law_name", "")) == target]
        if article:
            candidates = [law for law in candidates if str(law.get("article")) == str(article)]
        if not candidates:
            return None
        candidates = deepcopy(candidates)
        if as_of is not None:
            when = legal_date(as_of)
            dated = all(legal_date(law.get("effective_from")) and
                        (law.get("effective_to") is None or legal_date(law.get("effective_to")))
                        for law in candidates)
            matches = [law for law in candidates if when and dated and
                       law["effective_from"] <= when and
                       (law.get("effective_to") is None or when <= law["effective_to"])]
            if not when or not dated or len(matches) > 1:
                return {**candidates[-1], "temporal_scope": "UNRESOLVED_MIRROR",
                        "as_of_match": None, "requested_as_of": as_of}
            if len(matches) == 1:
                return {**matches[0], "as_of_match": True if matches[0].get("effective_to") else None,
                        "requested_as_of": as_of}
            # 시점에 맞는 version이 없으면 현행본을 돌려주되 표시를 남긴다
            current = sorted(candidates, key=lambda x: x.get("effective_from") or "")[-1]
            return {**current, "as_of_match": False, "requested_as_of": as_of}
        return sorted(candidates, key=lambda x: x.get("effective_from") or "")[-1]

    def all_versions(self, law_name: str, article: Optional[str] = None) -> List[Dict[str, Any]]:
        target = _canon(law_name)
        out = [law for law in self._laws if _canon(law.get("law_name", "")) == target]
        if article:
            out = [law for law in out if str(law.get("article")) == str(article)]
        return sorted(out, key=lambda x: x.get("effective_from") or "")
