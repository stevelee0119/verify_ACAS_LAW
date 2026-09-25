"""v4 검토 4항: 적용 기준일 후보 자동 추정, 공식 연혁(eflaw) 구법·현행법 대조, 기준일 불명 경고.

법령·조문·개정 연혁은 모두 가상(합성)이다. 실존 법령의 연혁을 지어내지 않는다. 공식 연혁 조회는 어댑터를
흉내 낸 가짜 객체로 시험한다(응답 형식은 official_legal.search_law_history·fetch_law_version과 같다).
"""
from __future__ import annotations

from types import SimpleNamespace

from packages.common.enums import AdapterStatus, CitationType, VerificationStatus
from packages.common.schemas import Citation
from packages.legal_engine.temporal_review import (inferred_reference, official_versions, reference_candidates,
                                                   reference_for, review_temporal_application)


def cite(law, article, claim, paragraph=None):
    return Citation.create(type=CitationType.STATUTE, raw_text=f"{law} 제{article}조", document_id="d",
                           law_name=law, article=article, paragraph=paragraph, attributes={"claim_text": claim})


def version(text, start, end=None):
    return {"text": text, "effective_from": start, "effective_to": end}


# --- 기준일 후보 추출(분야별) ---------------------------------------------------------------
def test_candidates_cover_offense_disposition_tort_and_lower_judgment():
    text = ("피고인은 2021. 6. 1. 회사 자금을 횡령하였다. "
            "피고는 2022. 3. 10. 원고에게 영업정지 처분을 하였다. "
            "원고는 2020. 5. 20. 교통사고로 상해를 입었다. "
            "원심은 2023. 4. 7. 선고한 판결에서 청구를 기각하였다.")
    found = {(c["kind"], c["date"]) for c in reference_candidates(text)}
    assert ("OFFENSE", "2021-06-01") in found
    assert ("DISPOSITION", "2022-03-10") in found
    assert ("TORT", "2020-05-20") in found
    assert ("LOWER_JUDGMENT", "2023-04-07") in found


def test_criminal_substantive_law_uses_the_offense_date():
    text = "피고인은 2021. 6. 1. 회사 자금을 횡령하였다. 원심은 2023. 4. 7. 선고하였다."
    ref = inferred_reference(cite("가상형사법", "5", "…"), text, criminal=True)
    assert ref["date"] == "2021-06-01" and ref["basis"] == "DOCUMENT_INFERRED" and ref["kind"] == "OFFENSE"


def test_procedural_law_uses_the_lower_judgment_date():
    text = "피고인은 2021. 6. 1. 회사 자금을 횡령하였다. 원심은 2023. 4. 7. 선고한 판결로 유죄를 인정하였다."
    ref = inferred_reference(cite("가상형사소송법", "30", "…"), text, criminal=True)
    assert ref["date"] == "2023-04-07" and ref["kind"] == "LOWER_JUDGMENT"


def test_administrative_and_civil_documents_use_disposition_or_tort_date():
    admin = inferred_reference(cite("가상행정법", "20", "…"), "피고는 2022. 3. 10. 원고에게 영업정지 처분을 하였다.", criminal=False)
    civil = inferred_reference(cite("가상손해배상법", "10", "…"), "원고는 2020. 5. 20. 교통사고로 상해를 입었다.", criminal=False)
    assert (admin["kind"], admin["date"]) == ("DISPOSITION", "2022-03-10")
    assert (civil["kind"], civil["date"]) == ("TORT", "2020-05-20")


def test_two_offense_dates_leave_the_reference_ambiguous():
    text = "피고인은 2021. 6. 1. 회사 자금을 횡령하였다. 피고인은 2022. 2. 3. 다시 회사 자금을 횡령하였다."
    ref = reference_for(cite("가상형사법", "5", "…"), "", text, None, criminal=True)
    assert ref["date"] is None and ref["basis"] == "AMBIGUOUS" and "2개" in ref["note"]


def test_explicit_review_date_still_wins_over_inference():
    ref = reference_for(cite("가상형사법", "5", "…"), "", "피고인은 2021. 6. 1. 횡령하였다.", "2020-01-01", criminal=True)
    assert ref == {"date": "2020-01-01", "basis": "EXPLICIT_REVIEW_DATE"}


# --- 판정 -------------------------------------------------------------------------------------
VERSIONS = [version("제5조 업무상 횡령은 5년 이하의 징역에 처한다.", "2010-01-01", "2021-12-31"),
            version("제5조 업무상 횡령은 7년 이하의 징역에 처한다.", "2022-01-01")]


def test_inferred_old_date_with_current_value_is_a_warning():
    text = "피고인은 2021. 6. 1. 회사 자금을 횡령하였다."
    c = cite("가상형사법", "5", "는 업무상 횡령을 7년 이하의 징역에 처한다")
    f = review_temporal_application(c, VERSIONS, reference_for(c, "", text, None, criminal=True), criminal=True)
    assert f.confidence_features["rule_id"] == "TEMPORAL.CURRENT_ONLY_MATCH" and f.status == VerificationStatus.SUSPICIOUS
    assert f.confidence_features["reference_basis"] == "DOCUMENT_INFERRED" and "추정" in f.detail


def test_unknown_reference_date_is_a_temporal_review_warning_with_candidates():
    c = cite("가상형사법", "5", "는 업무상 횡령을 7년 이하의 징역에 처한다")
    text = "피고인은 2021. 6. 1. 횡령하였다. 피고인은 2022. 2. 3. 다시 횡령하였다."
    f = review_temporal_application(c, VERSIONS, reference_for(c, "", text, None, criminal=True), criminal=True)
    assert f.confidence_features["defect_code"] == "TEMPORAL_REVIEW" and f.status == VerificationStatus.UNVERIFIED
    assert "기준일 불명" in f.title and "범행일 2021-06-01" in f.title


def test_claim_true_in_every_version_is_not_flagged_even_without_a_date():
    both = [version("제10조 ① 10년이 지나면 소멸한다.", "2010-01-01", "2020-06-30"),
            version("제10조 ① 10년이 지나면 소멸한다. ② 신설", "2020-07-01")]
    c = cite("가상손해배상법", "10", "은 10년이 지나면 소멸한다고 정한다", paragraph="1")
    f = review_temporal_application(c, both, {"date": None, "basis": "MISSING"})
    assert f is None or (f.confidence_features["rule_id"] == "TEMPORAL.ALL_VERSIONS_MATCH" and f.advisory_only)


# --- 공식 연혁 조회 ---------------------------------------------------------------------------
def history_row(mst, start, promulgated):
    return {"law_id": "900001", "version_id": mst, "effective_from": start, "promulgation_date": promulgated,
            "law_name": "가상형사법"}


class FakeOfficial:
    """search_law_history·fetch_law_version을 흉내 낸 공식 연혁 어댑터(시행본 3개)."""

    def __init__(self, *, fail_history=False, fail_detail=False):
        self.fail_history, self.fail_detail, self.fetched = fail_history, fail_detail, []
        self.bodies = {"100": "제5조 업무상 횡령은 3년 이하의 징역에 처한다.",
                       "200": "제5조 업무상 횡령은 5년 이하의 징역에 처한다.",
                       "300": "제5조 업무상 횡령은 7년 이하의 징역에 처한다."}

    def status(self):
        return AdapterStatus.READY

    def search_law_history(self, law_name):
        if self.fail_history:
            return SimpleNamespace(ok=False, complete=False, records=[], message="TIMEOUT", status=AdapterStatus.TIMEOUT)
        rows = [history_row("100", "2005-01-01", "2004-12-01"), history_row("200", "2015-01-01", "2014-12-01"),
                history_row("300", "2022-01-01", "2021-12-01")]
        return SimpleNamespace(ok=True, complete=True, records=rows, message="")

    def fetch_law_version(self, selected):
        mst = selected["version_id"]
        self.fetched.append(mst)
        if self.fail_detail:
            return SimpleNamespace(ok=False, records=[], message="HTTP 500", source_record=None)
        body = {"provisions": [{"number": "5", "text": self.bodies[mst], "paragraphs": []}]}
        return SimpleNamespace(ok=True, records=[body], message="",
                               source_record=SimpleNamespace(url=f"https://www.law.go.kr/eflaw?MST={mst}"))


def test_official_history_fetches_the_reference_version_and_the_current_version():
    adapter = FakeOfficial()
    got = official_versions(adapter, cite("가상형사법", "5", "…"), "2016-03-01", "2026-09-25")
    assert got["status"] == "READY" and adapter.fetched == ["200", "300"]
    assert [(v["effective_from"], v["effective_to"]) for v in got["versions"]] == [("2015-01-01", "2021-12-31"),
                                                                                   ("2022-01-01", None)]
    assert all(v["source"] == "OFFICIAL_HISTORY" and v["source_url"] for v in got["versions"])


def test_without_a_reference_date_the_previous_and_current_versions_are_compared():
    adapter = FakeOfficial()
    got = official_versions(adapter, cite("가상형사법", "5", "…"), None, "2026-09-25")
    assert adapter.fetched == ["200", "300"] and len(got["versions"]) == 2


def test_history_or_body_failure_is_unavailable_with_a_reason_not_a_verdict():
    history = official_versions(FakeOfficial(fail_history=True), cite("가상형사법", "5", "…"), None, "2026-09-25")
    body = official_versions(FakeOfficial(fail_detail=True), cite("가상형사법", "5", "…"), None, "2026-09-25")
    assert history["status"] == "UNAVAILABLE" and "연혁" in history["reason"] and history["versions"] == []
    assert body["status"] == "UNAVAILABLE" and "본문" in body["reason"]


def test_pipeline_uses_official_history_when_the_mirror_has_no_versions():
    from packages.common.schemas import NormalizedDocument, Page, Block, BBox
    from packages.verification_engine.pipeline import ProjectContext, VerificationPipeline

    pipeline = object.__new__(VerificationPipeline)
    pipeline.registry = SimpleNamespace(law=FakeOfficial())
    page = Page(page_number=1, width=595, height=842)
    page.blocks.append(Block(block_id="b1", page=1, bbox=BBox(60, 80, 535, 92),
                             text="피고인은 2016. 3. 1. 회사 자금을 횡령하였다. 가상형사법 제5조는 업무상 횡령을 7년 이하의 징역에 처한다."))
    doc = NormalizedDocument(document_id="d", filename="x.pdf", mime_type="application/pdf", sha256="0", pages=[page])
    c = cite("가상형사법", "5", "는 업무상 횡령을 7년 이하의 징역에 처한다")
    c.block_id = "b1"
    found = pipeline._temporal_reviews(doc, [c], ProjectContext("p"))
    assert found["reviewed"] == 1 and not found["unavailable"]
    rule = found["findings"][0].confidence_features
    assert rule["rule_id"] == "TEMPORAL.CURRENT_ONLY_MATCH" and rule["version_source"] == "OFFICIAL_HISTORY"
    assert rule["reference_date"] == "2016-03-01"
