"""v4 P1: 사실 저장소 교차검증(CROSS_DOC_INCONSISTENCY). 문서 간·문서 안·사건 묶기·자릿수 뒤바뀜."""
from __future__ import annotations

from packages.claim_engine.fact_store import case_groups, build_fact_store, cross_document_facts, digit_transposition
from tests.test_v3_g5_facts import doc


def rules(findings):
    return {(f.confidence_features["rule_id"], f.confidence_features["scope"]) for f in findings}


# --- 문서 안(본문 ↔ 첨부 사본) ------------------------------------------------------------------
def test_body_and_attached_copy_disagree_on_side_in_one_file():                     # 민사
    d = doc("원고는 2023. 3. 15. 사고로 좌측 슬관절 부상을 입었다.", "첨부 진단서(사본)",
            "상병명: 우측 슬관절 염좌", doc_id="A")
    found = cross_document_facts([d])
    assert ("FACT.INJURY_SIDE", "IN_DOCUMENT") in rules(found)
    assert found[0].confidence_features["defect_code"] == "CROSS_DOC_INCONSISTENCY"


def test_party_name_differs_inside_one_document():                                   # 가사
    d = doc("원고 박○○ / 피고 최○○", "원고 박○○과 피고 최○○은 혼인신고를 마쳤다.", "원고 이○○은 가사를 전담하였다.", doc_id="F")
    found = cross_document_facts([d])
    assert ("FACT.PARTY_NAME", "IN_DOCUMENT") in rules(found)
    assert "이○○ 1회" in found[0].title


def test_several_plaintiffs_are_not_a_name_error():                                   # 민사(공동원고)
    d = doc("원고 1. 김○○, 2. 이○○ / 피고 박○○", "원고들은 피고에게 손해배상을 구한다. 원고 김○○과 원고 이○○은 부부이다.")
    assert not [f for f in cross_document_facts([d]) if f.confidence_features["rule_id"] == "FACT.PARTY_NAME"]


def test_bilateral_injury_is_not_a_side_conflict():                                  # 형사(피해자 상해)
    d = doc("피해자는 2022. 1. 3. 폭행을 당하여 양측 좌·우 손목 골절을 입었다.", "피해자 좌측 손목, 우측 손목 모두 골절")
    assert not [f for f in cross_document_facts([d]) if f.confidence_features["rule_id"] == "FACT.INJURY_SIDE"]


# --- 문서 간 --------------------------------------------------------------------------------------
def test_claim_amount_digit_transposition_between_petition_and_answer():             # 가사
    petition = doc("원고 박○○ / 피고 최○○", "청구취지", "피고는 원고에게 재산분할로 금 205,000,000원을 지급하라.",
                   "청구원인", "원고 박○○과 피고 최○○은 이혼한다.", doc_id="P")
    answer = doc("원고 박○○과 피고 최○○은 혼인하였으나 원고의 청구금액 금 250,000,000원은 과다하다.", doc_id="Q")
    [f] = [f for f in cross_document_facts([petition, answer]) if f.confidence_features["rule_id"] == "FACT.CLAIM_AMOUNT"]
    assert f.confidence_features["digit_transposition"] and "자릿수 뒤바뀜" in f.title


def test_incident_date_ignores_limitation_dates_and_exhibit_names():                 # 민사
    brief = doc("원고 김○○ / 피고 ○○산업", "원고는 2023. 3. 15. 작업 중 사고로 부상을 입었다.",
                "사고일인 2023. 3. 15.부터 3년이 경과한 2026. 3. 15. 소멸한다.", "갑 제3호증 사고경위서 2023. 1. 10.", doc_id="B")
    store = build_fact_store([brief])
    assert {f["value"] for f in store if f["attribute"] == "incident_date"} == {"2023-03-15"}


def test_digit_transposition_helper():
    assert digit_transposition("205000000", "250000000")
    assert digit_transposition("12000000", "21000000")
    assert not digit_transposition("35000000", "30000000")
    assert not digit_transposition("1000", "10000")


# --- 사건 묶기 ----------------------------------------------------------------------------------
def test_documents_of_different_cases_are_not_compared():
    civil = doc("사건 2024가합10001 손해배상", "원고 김○○ / 피고 ○○산업", "청구취지", "금 35,000,000원을 지급하라.",
                "원고는 2023. 3. 15. 사고로 좌측 슬관절 부상을 입었다.", doc_id="C1")
    family = doc("소장 이혼 및 재산분할", "원고 박○○ / 피고 최○○", "원고와 피고는 이혼한다. 재산분할 청구", "청구취지",
                 "금 205,000,000원을 지급하라.", doc_id="F1")
    admin = doc("2024구합20002 영업정지처분취소", "행정청의 처분의 취소를 구한다.", doc_id="A1")
    criminal = doc("변론요지서 2023고합30003 업무상횡령", "피고인은 2021. 6. 1. 범행을 하였다는 공소사실로 기소되었다.",
                   "피해자는 우측 슬관절 부상을 입었다.", doc_id="K1")
    groups = case_groups([civil, family, admin, criminal], build_fact_store([civil, family, admin, criminal]))
    assert all(len(g) == 1 for g in groups)
    assert cross_document_facts([civil, family, admin, criminal]) == []


def test_evidence_document_joins_the_case_by_patient_name():                          # 민사 + 진단서
    brief = doc("사건 2024가합10001 손해배상", "원고 김○○ / 피고 ○○산업", "원고는 2023. 3. 15. 사고로 좌측 슬관절 부상을 입었다.",
                doc_id="C1")
    medical = doc("진 단 서", "위 환자는 2023. 3. 16. 작업장 사고로 우측 슬관절 부상을 입었다.",
                  tables=[[["환자 성명", "김○○"], ["상병명", "우측 슬관절 염좌"]]], doc_id="M1")
    family = doc("원고 박○○ / 피고 최○○", "원고와 피고는 이혼한다. 재산분할 청구. 혼인신고", doc_id="F1")
    found = rules(cross_document_facts([brief, medical, family]))
    assert {("FACT.INJURY_SIDE", "CROSS_DOCUMENT"), ("FACT.INCIDENT_DATE", "CROSS_DOCUMENT")} <= found
