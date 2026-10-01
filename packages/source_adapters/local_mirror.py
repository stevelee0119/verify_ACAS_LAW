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


def _canon_article(value: Optional[str]) -> str:
    """조문 번호를 '202' 또는 '202의2' 형식으로 정규화한다."""
    if not value:
        return ""
    s = re.sub(r"\s+", "", str(value))
    m = re.match(r"^(?:제)?(\d+)(?:조)?(?:의(\d+))?", s)
    if m:
        main, sub = m.group(1), m.group(2)
        return f"{main}의{sub}" if sub else main
    return s


def _is_official_law_url(url: str) -> bool:
    """공식 법령 조문 링크 여부를 확인한다. 판례나 헌재 결정례 링크는 제외한다."""
    if not url:
        return False
    u = url.lower()
    # 판례 / 결정례 링크는 조문 미러 등록에서 배제
    if any(p in u for p in ["precinfo", "target=prec", "/판례/", "target=detc", "detcinfo"]):
        return False
    # 공식 법령 조문 링크 패턴 확인
    return any(p in u for p in ["/법령/", "doccls=jo", "target=eflaw", "lslink", "lsinfo", "lssideinfo"])


def _extract_effective_date(version_text: str) -> Optional[str]:
    """버전 문구에서 명시된 'YYYY-MM-DD 시행' 형태의 날짜를 추출한다. 지어낸 날짜는 반환하지 않는다."""
    if not version_text:
        return None
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*시행", version_text)
    return m.group(1) if m else None


_LAW_KEY_PATTERN = re.compile(
    r"^(?P<law>[가-힣A-Za-z0-9\s·]+?)\s*제\s*(?P<art>\d+)\s*조(?:\s*의\s*(?P<art_sub>\d+))?(?:\s*제\s*(?P<para>\d+)\s*항)?"
)


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

        # config/legal_rules/rules.json에 수집된 공식 조문을 기본 오프라인 미러로 자동 보강
        rules_file = CONFIG_DIR / "legal_rules" / "rules.json"
        if rules_file.exists():
            try:
                rules_data = json.loads(rules_file.read_text(encoding="utf-8"))
                for key, val in rules_data.get("sources", {}).items():
                    url = val.get("url", "")
                    # 판례 링크 및 비공식 URL은 조문 미러에서 제외
                    if not _is_official_law_url(url):
                        continue

                    m_law = _LAW_KEY_PATTERN.match(key)
                    if m_law:
                        law_name = m_law.group("law").strip()
                        art = m_law.group("art")
                        art_sub = m_law.group("art_sub")
                        # 가지조문(예: 202조의2 -> 202의2) 보존
                        article = f"{art}의{art_sub}" if art_sub else art
                        # 항 번호 보존 (명시되지 않은 경우 임의 기본값 1이 아닌 None)
                        paragraph = m_law.group("para")

                        # 이미 등록된 조문인지 검사 (법률명, 조문번호, 항 일치 여부)
                        already_exists = any(
                            _canon(l.get("law_name", "")) == _canon(law_name)
                            and _canon_article(str(l.get("article") or "")) == _canon_article(article)
                            and (paragraph is None or str(l.get("paragraph") or "") == str(paragraph))
                            for l in self._laws
                        )
                        if not already_exists:
                            # 임의의 1980-01-01 대신 명시된 시행일만 파싱 (없으면 None)
                            effective_from = _extract_effective_date(val.get("version", ""))
                            self._laws.append({
                                "law_name": law_name,
                                "article": article,
                                "paragraph": paragraph,
                                "text": val.get("text", ""),
                                "effective_from": effective_from,
                                "effective_to": None,
                                "detail_link": url,
                                "authority": "USER_REFERENCE_NOT_OFFICIAL",
                            })
            except Exception:
                pass

    def find_case(self, case_number: str) -> Optional[Dict[str, Any]]:
        return self._cases.get(_canon(case_number))

    def find_law(
        self, law_name: str, *, article: Optional[str] = None, as_of: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        target = _canon(law_name)
        candidates = [law for law in self._laws if _canon(law.get("law_name", "")) == target]
        if article:
            target_art = _canon_article(article)
            candidates = [law for law in candidates if _canon_article(str(law.get("article") or "")) == target_art]
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
            # 시점에 맞는 version이 없는 경우:
            # 단일 버전 스냅샷이거나 비공식 참고 미러인 경우 이전 연혁 부재이므로 UNRESOLVED_MIRROR로 안전 처리 (오탐 방지)
            current = sorted(candidates, key=lambda x: x.get("effective_from") or "")[-1]
            if len(candidates) == 1 or current.get("authority") == "USER_REFERENCE_NOT_OFFICIAL":
                return {**current, "temporal_scope": "UNRESOLVED_MIRROR",
                        "as_of_match": None, "requested_as_of": as_of}
            return {**current, "as_of_match": False, "requested_as_of": as_of}
        return sorted(candidates, key=lambda x: x.get("effective_from") or "")[-1]

    def all_versions(self, law_name: str, article: Optional[str] = None) -> List[Dict[str, Any]]:
        target = _canon(law_name)
        out = [law for law in self._laws if _canon(law.get("law_name", "")) == target]
        if article:
            target_art = _canon_article(article)
            out = [law for law in out if _canon_article(str(law.get("article") or "")) == target_art]
        return sorted(out, key=lambda x: x.get("effective_from") or "")
