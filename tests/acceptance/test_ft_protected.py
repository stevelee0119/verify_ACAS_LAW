"""[평가 에이전트 소관] FT(행위시법 검토 보강) 보호 시험 — T10 목 단위 신설·이동, T11 동일 시행일 복수 버전 (2026-10-05).

근거: `docs/handoff/PROMPT_FOR_FEATURE_ROUND_F1.md` 1절 FT, `docs/handoff/TK-34_item_level_temporal_review.md`,
요청 16(사용자 결정 2026-10-02 '두 버전 병기·대조').

입력
- 조문 본문은 모두 `tests/fixtures/prepared_brief_mirror`(국가법령정보센터 공식 원문, 출처는 SOURCES.md)에서 가져온다.
- `claim_text`는 평가 측이 공식 원문을 요약해 지은 것이다(서면·정답지 문구가 아니다).
- T11의 '같은 시행일 두 버전' 배열은 구조 시험을 위해 평가 측이 꾸민 연혁이다(본문은 공식 원문, 시행일·버전 번호 배열만 합성).
  이 세션에서 국가법령정보센터에 접속할 수 없어 실제 동일 시행일 사례(예: 국가재정법 제96조)의 원문을 확보하지 못했다.

표시
- (승격 2026-10-06) FT(PR #27 ed8d7d1)에서 XPASS가 되어 평가 측이 strict xfail 표시를 지웠다. 이제 모두 통과해야 하는 시험이다.
- 표시 없는 시험 = 지금도 통과하고 FT 뒤에도 통과해야 하는 오탐 대조·기존 동작.
- T10의 양성 사례(신설 카목을 2020년 행위에 인용)는 (승격된) 시험
  `tests/acceptance/test_prepared_brief_mirror_official.py::test_new_data_ka_cited_for_2020_act_is_flagged`가 맡는다.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import httpx
import pytest

from packages.common.enums import AdapterStatus, Severity, VerificationStatus
from packages.common.schemas import Citation, CitationType
from packages.legal_engine.temporal_review import official_versions, paragraph_text, review_temporal_application
from packages.source_adapters.law_go_kr import LawGoKrAdapter
from packages.source_adapters.local_mirror import LocalLegalMirror

MIRROR = Path(__file__).resolve().parents[1] / "fixtures" / "prepared_brief_mirror"
LAW = "부정경쟁방지 및 영업비밀보호에 관한 법률"
# 공식 원문 요약(평가 측 작성)
PERFORMANCE = "타인의 상당한 투자나 노력으로 만들어진 성과를 무단으로 사용하여 이익을 침해"
DATA_MISUSE = "전자적 방법으로 상당량 축적ㆍ관리되는 데이터를 접근권한 없이 부정하게 취득하여 사용하는 행위에 해당한다"
FIVE_TIMES = "손해액의 5배를 넘지 아니하는 범위에서 징벌적 배상책임이 인정된다"


def _mirror() -> LocalLegalMirror:
    return LocalLegalMirror(root=MIRROR)


def _is_retroactive_error(finding) -> bool:
    return finding is not None and finding.severity == Severity.HIGH and "RETROACTIVE_APPLICATION_ERROR" in finding.tags


# --------------------------------------------------------------------------- T10 ---
# 미러의 제2조: 2019-07-09~2022-04-19(카목 = 성과 도용), 2025-10-01~현행(카목 = 데이터 부정사용, 파목 = 성과 도용).
# 2021. 12. 7. 개정(법률 제18548호)이 "카목을 파목으로 하고 카목·타목을 신설"했다(SOURCES.md).

def _article2_item_citation(item_letter: str, claim: str) -> Citation:
    return Citation(
        citation_id="t10", document_id="doc1", block_id="b1", page=1, span=(0, 30),
        raw_text=f"부정경쟁방지법 제2조 제1호 {item_letter}목", type=CitationType.STATUTE, law_name="부정경쟁방지법",
        article="2", item="1", attributes={"claim_text": claim})


def _review_article2(item_letter: str, claim: str, when: str):
    return review_temporal_application(
        _article2_item_citation(item_letter, claim), _mirror().all_versions(LAW, "2"), {"date": when, "basis": "FACT_DATE"})


def test_t10_renumbered_item_cited_by_new_letter_for_old_act_is_not_retroactive_error():
    """번호만 바뀐 개정(내용 불변)의 오탐 대조: 성과 도용은 2020년에 카목으로 시행 중이었다.
    지금 번호(파목)로 인용해도 행위 당시 같은 내용이 시행 중이었으므로 소급 적용 오류가 아니다."""
    assert not _is_retroactive_error(_review_article2("파", PERFORMANCE, "2020-05-12"))


def test_t10_moved_item_cited_by_current_letter_for_current_act_is_not_flagged():
    assert not _is_retroactive_error(_review_article2("파", PERFORMANCE, "2026-01-01"))


def test_t10_new_item_cited_for_act_after_its_commencement_is_not_flagged():
    """신설 카목(데이터 부정사용)을 신설 뒤 행위에 인용하는 것은 맞다."""
    assert not _is_retroactive_error(_review_article2("카", DATA_MISUSE, "2026-01-01"))


def test_t10_old_letter_with_old_content_for_old_act_is_not_flagged():
    """성과 도용을 그 당시 번호(카목)로 2020년 행위에 인용 — 기존 시험과 같은 대조를 T10 묶음에도 둔다."""
    assert not _is_retroactive_error(_review_article2("카", PERFORMANCE, "2020-05-12"))


# --------------------------------------------------------------------------- T11 ---
# 제14조의2 제6항: 2019-07-09본은 3배, 2024-08-21본은 5배(공식 원문). 이 두 본문으로 연혁을 꾸며
# '같은 시행일 두 버전'을 만든다. 공식 연혁 조회(LawGoKrAdapter)는 HTTP만 가로챈다.

def _versions_14_2():
    versions = _mirror().all_versions(LAW, "14의2")
    three, five = versions[0]["text"], versions[-1]["text"]
    assert "3배" in paragraph_text(three, "6") and "5배" in paragraph_text(five, "6")
    return three, five


def _history_row(mst: str, effective: str, promulgated: str) -> dict:
    return {"법령명한글": LAW, "법령ID": "000308", "법령일련번호": mst, "공포일자": promulgated,
            "시행일자": effective, "공포번호": mst, "제개정구분명": "일부개정"}


def _law_body(row: dict, text: str) -> dict:
    return {"법령": {
        "기본정보": {"법령ID": "000308", "법령일련번호": row["법령일련번호"], "법령명_한글": LAW,
                 "시행일자": row["시행일자"], "공포일자": row["공포일자"], "공포번호": row["공포번호"]},
        "조문": {"조문단위": [{"조문번호": "14", "조문가지번호": "2", "조문여부": "조문",
                           "조문시행일자": row["시행일자"], "조문내용": text}]}}}


@pytest.fixture
def history_adapter(monkeypatch):
    def build(rows: list, texts: dict) -> LawGoKrAdapter:
        adapter = LawGoKrAdapter(mirror=LocalLegalMirror(Path(tempfile.mkdtemp(prefix="ft_empty_"))))
        monkeypatch.setattr(adapter, "status", lambda: AdapterStatus.READY)
        monkeypatch.setattr(LawGoKrAdapter, "api_key", property(lambda self: "TEST_ONLY_KEY"))

        def request(url, *, params):
            if "MST" in params:
                row = next(r for r in rows if r["법령일련번호"] == params["MST"] and r["시행일자"] == params["efYd"])
                payload = _law_body(row, texts[row["법령일련번호"]])
            else:
                payload = {"LawSearch": {"totalCnt": len(rows), "page": 1, "law": rows}}
            return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

        monkeypatch.setattr(adapter, "_http_get", request)
        return adapter
    return build


def _citation_14_2_6(claim: str) -> Citation:
    return Citation(
        citation_id="t11", document_id="doc1", block_id="b1", page=1, span=(0, 30),
        raw_text="부정경쟁방지법 제14조의2 제6항", type=CitationType.STATUTE, law_name=LAW,
        article="14의2", paragraph="6", attributes={"claim_text": claim})


def _same_day_rows(order: str = "forward") -> list:
    rows = [_history_row("100", "20190709", "20190108"),
            _history_row("200", "20240821", "20240220"),
            _history_row("201", "20240821", "20240220")]
    return rows if order == "forward" else [rows[0], rows[2], rows[1]]


def _run(adapter, claim: str, when: str):
    citation = _citation_14_2_6(claim)
    fetched = official_versions(adapter, citation, when, "2026-01-01")
    finding = (review_temporal_application(citation, fetched["versions"], {"date": when, "basis": "FACT_DATE"})
               if fetched["status"] == "READY" else None)
    return fetched, finding


def test_t11_fixture_plumbing_distinct_dates_still_flags_current_only_match(history_adapter):
    """구조 확인(표시 없음): 시행일이 서로 다른 연혁에서는 지금도 3배→5배 소급 적용을 잡는다. FT 뒤에도 유지."""
    three, five = _versions_14_2()
    adapter = history_adapter(_same_day_rows()[:2], {"100": three, "200": five})
    fetched, finding = _run(adapter, FIVE_TIMES, "2020-05-12")
    assert fetched["status"] == "READY", fetched.get("reason")
    assert [v["effective_from"] for v in fetched["versions"]] == ["2019-07-09", "2024-08-21"]
    assert _is_retroactive_error(finding)


def test_t11_same_day_versions_disagree_both_shown_and_left_for_review(history_adapter):
    """같은 시행일 두 버전의 대조 결과가 갈리면(5배본 일치, 3배본 불일치) 하나로 확정하지 않고 확인 요청으로 둔다."""
    three, five = _versions_14_2()
    adapter = history_adapter(_same_day_rows(), {"100": three, "200": five, "201": three})
    fetched, finding = _run(adapter, FIVE_TIMES, "2025-01-01")
    assert fetched["status"] == "READY", fetched.get("reason")
    same_day = [v for v in fetched["versions"] if v["effective_from"] == "2024-08-21"]
    assert len(same_day) == 2, "같은 시행일의 두 버전을 모두 실어야 한다(병기)"
    assert finding is not None
    assert finding.status == VerificationStatus.UNVERIFIED and finding.severity != Severity.HIGH
    assert "RETROACTIVE_APPLICATION_ERROR" not in finding.tags
    assert finding.confidence_features.get("human_review") is True
    shown = [v for v in finding.confidence_features.get("versions", []) if v.get("effective_from") == "2024-08-21"]
    assert len(shown) == 2 and {v.get("status") for v in shown} == {"VERIFIED", "CONTRADICTED"}


def test_t11_same_day_versions_agree_is_not_left_unverified(history_adapter):
    """같은 시행일 두 버전이 모두 주장과 맞으면 확인 요청으로 남기지 않는다(오류도 아니다)."""
    three, five = _versions_14_2()
    adapter = history_adapter(_same_day_rows(), {"100": three, "200": five, "201": five})
    fetched, finding = _run(adapter, FIVE_TIMES, "2025-01-01")
    assert fetched["status"] == "READY", fetched.get("reason")
    assert len([v for v in fetched["versions"] if v["effective_from"] == "2024-08-21"]) == 2
    assert finding is None or (finding.status == VerificationStatus.VERIFIED and not _is_retroactive_error(finding))


def test_t11_result_does_not_depend_on_version_order(history_adapter):
    """한 버전을 골라 확정하지 않는다(공포일·개정 번호·응답 순서 우선 금지): 연혁 순서를 바꿔도 결과가 같다."""
    three, five = _versions_14_2()
    texts = {"100": three, "200": five, "201": three}
    results = []
    for order in ("forward", "reverse"):
        fetched, finding = _run(history_adapter(_same_day_rows(order), texts), FIVE_TIMES, "2025-01-01")
        assert fetched["status"] == "READY", fetched.get("reason")
        assert finding is not None
        results.append((finding.status, finding.severity, finding.confidence_features.get("rule_id")))
    assert results[0] == results[1]
