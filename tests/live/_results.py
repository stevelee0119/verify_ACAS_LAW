"""실연동 결과 저장소. conftest와 테스트 모듈이 같은 객체를 쓰도록 따로 둔다(모듈 사본 문제 방지)."""
from __future__ import annotations

RESULTS: dict = {}


def record(item_id: str, *, prepared: int, detected: int, false_positive: int = 0, summary: str = "",
           cases: list | None = None, diagnostics: dict | None = None) -> None:
    """테스트가 항목별 준비·탐지·오탐 수와 진단 정보를 남긴다(통과 여부는 테스트 결과로 정한다)."""
    RESULTS.setdefault(item_id, {}).update({"prepared": prepared, "detected": detected,
                                             "false_positive": false_positive, "summary": summary,
                                             "cases": cases or [], "diagnostics": diagnostics or {}})
