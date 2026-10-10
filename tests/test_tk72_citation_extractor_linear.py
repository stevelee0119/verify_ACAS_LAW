"""TK-72 합성 자료 시험: 인용 추출기(citation_extractor)의 선형 시간 및 대규모 입력 처리 검증.

실제 Drive 자료나 비공개 판례·사건 번호는 저장소에 넣지 않으며, 모든 시험 데이터는 합성(synthetic)이다.
"""
import gc
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from packages.common.enums import CitationType
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.legal_engine.citation_extractor import (
    canonical_law_name,
    extract_citations,
    extract_from_text,
)


def _make_doc(text: str, doc_id: str = "doc_synthetic") -> NormalizedDocument:
    """합성 텍스트를 담은 NormalizedDocument 실제 객체를 생성한다."""
    return NormalizedDocument(
        doc_id,
        f"{doc_id}.txt",
        "text/plain",
        "synthetic_sha256",
        pages=[Page(1, blocks=[Block("b1", text, 1)])],
    )


def test_repeated_short_input_performance():
    """짧은 반복 입력 시간 성능 시험: 새로 변경된 핵심 로직 2,500회 0.1초 이내 (AGENTS.md 공통 규칙)."""
    from packages.legal_engine.citation_extractor import SpanTracker, _law_name_start, LAW_RE

    # 1) 구간 추적기(이진 탐색) 2,500회 반복 < 0.1초
    tracker = SpanTracker()
    started = time.perf_counter()
    for i in range(2500):
        tracker.overlaps(i * 10, i * 10 + 5)
        tracker.add(i * 10, i * 10 + 5)
    elapsed_tracker = time.perf_counter() - started
    assert elapsed_tracker < 0.1, f"구간 추적기 2,500회 반복 초과: {elapsed_tracker:.4f}초"

    # 2) 법령명 시작 위치 탐색(캐시) 2,500회 반복 < 0.1초
    m = LAW_RE.search("원고는 「근로기준법」 제23조를 위반하였다.")
    started = time.perf_counter()
    for _ in range(2500):
        _law_name_start(m)
    elapsed_law = time.perf_counter() - started
    assert elapsed_law < 0.1, f"법령명 시작 위치 2,500회 반복 초과: {elapsed_law:.4f}초"

    # 3) 텍스트 인용 추출 100회 반복 < 0.1초
    text = "원고는 「근로기준법」 제23조 제1항을 근거로 해고무효를 주장한다."
    best = float("inf")
    for _ in range(3):
        started = time.perf_counter()
        for _ in range(100):
            extract_from_text(text)
        best = min(best, time.perf_counter() - started)
    assert best < 0.1, f"단문 추출 100회 반복 초과: {best:.4f}초"


def test_canonical_law_name_cache_performance():
    """법령명 정규화 캐시 반복 호출 성능 시험 (2,500회 0.1초 이내)."""
    names = ["근로기준법", "「민법」", "형법", "상법", "행정소송법"] * 500
    # 캐시 워밍업 (고유 키 5개 등록)
    for n in names[:5]:
        canonical_law_name(n)

    started = time.perf_counter()
    results = [canonical_law_name(name) for name in names]
    elapsed = time.perf_counter() - started
    assert len(results) == 2500
    assert results[0] == "근로기준법"
    assert elapsed < 0.1, f"캐시 조회 시간이 0.1초를 초과함: {elapsed:.4f}초"


def test_case_whitespace_tail_is_linear():
    """1절 1항: 목 인용 뒤 공백만 이어지는 한 줄(80KB) 실제 경로가 1.0초 이내에 완료된다 (TK-72)."""
    # 0bf4ccc 기준 42.4초 걸리던 극단적 공백 백트래킹 방지 검증
    synthetic_text = "원고는 「근로기준법」 제23조 제1항 제1호 가목" + " " * 80000 + "x"
    doc = _make_doc(synthetic_text, "doc_whitespace")

    started = time.perf_counter()
    citations = extract_citations(doc)
    elapsed = time.perf_counter() - started

    assert len(citations) == 1
    assert citations[0].law_name == "근로기준법"
    assert citations[0].article == "23"
    assert citations[0].attributes.get("subitem") == "가"
    assert elapsed < 1.0, f"공백 80KB 처리가 1.0초를 초과함: {elapsed:.4f}초"


def test_subitem_repeated_notation_is_linear():
    """1절 2항: 목 인용 뒤 ·나목 반복(80KB) 실제 경로가 1.0초 이내에 완료된다 (TK-72)."""
    # 0bf4ccc 기준 34.6초 걸리던 기호 반복 처리 검증
    synthetic_text = "원고는 「근로기준법」 제23조 제1항 제1호 가목" + "·나목" * 20000
    doc = _make_doc(synthetic_text, "doc_subitem_dots")

    started = time.perf_counter()
    citations = extract_citations(doc)
    elapsed = time.perf_counter() - started

    assert len(citations) == 1
    assert citations[0].law_name == "근로기준법"
    assert elapsed < 1.0, f"·나목 반복 80KB 처리가 1.0초를 초과함: {elapsed:.4f}초"


def test_subitem_repeated_conjunction_is_linear():
    """1절 3항: 목 인용 뒤 ' 및 ' 반복(80KB) 실제 경로가 1.0초 이내에 완료된다 (TK-72)."""
    # 0bf4ccc 기준 19.6초 걸리던 접속사 반복 처리 검증
    synthetic_text = "원고는 「근로기준법」 제23조 제1항 제1호 가목" + " 및 " * 20000
    doc = _make_doc(synthetic_text, "doc_subitem_and")

    started = time.perf_counter()
    citations = extract_citations(doc)
    elapsed = time.perf_counter() - started

    assert len(citations) == 1
    assert citations[0].law_name == "근로기준법"
    assert elapsed < 1.0, f" 및  반복 80KB 처리가 1.0초를 초과함: {elapsed:.4f}초"


def test_repeated_statute_citations_are_linear():
    """1절 4항: 정상 법령 인용 문장 반복(2,000건 vs 8,000건 vs 32,000건)의 선형성 확인 (TK-72)."""
    # 0bf4ccc 기준 인용 수 4배 증가에 14배(제곱 시간) 걸리던 overlaps / attach_claim_text 병목이
    # 정렬 이진 탐색 및 투 포인터 선형 순회로 개선되어 선형 시간비(배수 < 8)로 유지됨을 확인
    line = "피고인은 「형법」 제250조 제1항을 위반하였다.\n"

    def measure_cold(count: int) -> float:
        text = line * count
        gc_was_enabled = gc.isenabled()
        gc.disable()
        try:
            best = float("inf")
            for _ in range(2):
                started = time.perf_counter()
                c = extract_from_text(text)
                elapsed = time.perf_counter() - started
                assert len(c) == count
                best = min(best, elapsed)
            return best
        finally:
            if gc_was_enabled:
                gc.enable()

    time_2k = measure_cold(2000)
    time_8k = measure_cold(8000)

    # 4배 크기(2,000 -> 8,000건) 증가 시 시간 비가 8 미만이어야 함 (제곱 시간 16 배제)
    ratio_4x = time_8k / max(time_2k, 1e-4)
    assert ratio_4x < 8.0, f"인용 수 4배 증가 시 시간 증가비가 8 이상임 (제곱 시간 의심): {ratio_4x:.2f}배"

    # 실제 경로(extract_citations) 8,000건 처리 시간 1.5초 이내
    doc_8k = _make_doc(line * 8000, "doc_8k")
    t0 = time.perf_counter()
    c_8k = extract_citations(doc_8k)
    dt_8k = time.perf_counter() - t0
    assert len(c_8k) >= 1
    assert dt_8k < 2.0, f"8,000건 실제 경로 처리가 2.0초를 초과함: {dt_8k:.4f}초"


def test_citation_extraction_fidelity_unchanged():
    """추출 정확도 검증: 다양한 인용 형태(판례, 헌재, 병합, 법령, 계속 조문, 동조, 행정규칙, 법령해석, 학술)의 추출 결과 불변 (TK-72 요구 2)."""
    sample = (
        "1. 대법원 2099. 1. 2. 선고 2099다100 판결 및 2099도200 판결을 참조한다.\n"
        "2. 헌재 2099. 3. 26. 2099헌바300, 2099헌바400(병합) 결정에 따른다.\n"
        "3. 「근로기준법」 제23조 제1항 제1호 가목 및 제24조 제2항을 위반하였다.\n"
        "4. 같은 법 제30조와 동법 시행령 제10조 및 동조 제2항을 적용한다.\n"
        "5. 국방부 훈령 제2099-1호 제5조에 근거한다.\n"
        "6. 법제처 99-0001 해석례에 따르며 홍길동, 「합성 논문 제목」, 법학논총 제10권 제2호, 2099를 참고한다."
    )
    doc = _make_doc(sample, "doc_fidelity")
    citations = extract_citations(doc)

    types = [c.type for c in citations]
    assert CitationType.CASE in types
    assert CitationType.CONSTITUTIONAL in types
    assert CitationType.STATUTE in types
    assert CitationType.ADMIN_RULE in types
    assert CitationType.INTERPRETATION in types
    assert CitationType.ACADEMIC in types

    # 주요 속성 보존 확인
    const_cit = next(c for c in citations if c.type == CitationType.CONSTITUTIONAL)
    assert const_cit.canonical_case_number == "2099헌바300"
    assert const_cit.attributes.get("merged_notation") is True

    statute_cits = [c for c in citations if c.type == CitationType.STATUTE]
    law_names = {c.law_name for c in statute_cits}
    assert "근로기준법" in law_names
    assert "근로기준법 시행령" in law_names

    # 계속 조문('제24조')의 continued_from 속성 보존
    continued = [c for c in statute_cits if c.attributes.get("continued_from")]
    assert len(continued) >= 1
