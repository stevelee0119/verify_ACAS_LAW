"""TK-04: 처분시법주의 시점 검토 보강 단위 테스트.

양성(처분일보다 뒤에 개정·공포된 법령을 적용 주장 → 탐지) 3건 이상,
대조군(개정일이 처분일보다 앞인 경우, 단순 참고 언급 등 → 미탐지) 3건 이상.
"""
from __future__ import annotations

import pytest

from packages.legal_engine.temporal_review import (
    _format_article,
    declared_amendments,
    review_declared_amendments,
    DISPOSITION_TIME_BASIS,
)


# ── 전처리 함수 테스트 ──────────────────────────────────────────────────

class TestFormatArticle:
    """_format_article 조문 번호 포매팅 테스트."""

    def test_simple(self):
        """일반 조문: 12 → 제12조."""
        assert _format_article("12") == "제12조"

    def test_with_sub(self):
        """가지조문: 57의3 → 제57조의3."""
        assert _format_article("57의3") == "제57조의3"

    def test_empty(self):
        """빈 문자열 → 빈 문자열."""
        assert _format_article("") == ""

    def test_none(self):
        """None → 빈 문자열."""
        assert _format_article(None) == ""


# ── 양성: 단일 날짜 개정 이력 추출 ────────────────────────────────────

class TestDeclaredAmendmentsPositive:
    """단일 날짜 패턴('개정·공포된')에서 개정 이력이 추출되는지 확인."""

    def test_single_date_amendment(self):
        """'2025년 3월 1일 대통령령 제35800호로 개정·공포된 「군인 징계령」 제12조' → 추출."""
        text = "2025년 3월 1일 대통령령 제35800호로 개정·공포된 「군인 징계령」 제12조 제2항 단서에 따르면"
        amendments = declared_amendments(text)
        assert len(amendments) >= 1, f"개정 이력이 추출되지 않음: {amendments}"
        a = amendments[0]
        assert "징계령" in a["law_name"]
        assert a["article"] == "12"
        assert a["promulgated"] == "2025-03-01"
        # 시행일이 없으므로 공포일이 fallback으로 사용
        assert a["effective"] == "2025-03-01"

    def test_single_date_enacted(self):
        """'2024. 12. 24. 대통령령 제12345호로 개정된 「국방 조달 관리법」 제5조' → 추출."""
        text = "2024. 12. 24. 대통령령 제12345호로 개정된 「국방 조달 관리법」 제5조 제1항에 위반된다."
        amendments = declared_amendments(text)
        assert len(amendments) >= 1, f"개정 이력이 추출되지 않음: {amendments}"
        a = amendments[0]
        assert a["promulgated"] == "2024-12-24"
        assert a["effective"] == "2024-12-24"

    def test_single_date_promulgated(self):
        """'2025. 6. 15. 법률 제20000호로 공포된 「행정 절차법」 제10조' → 추출."""
        text = "2025. 6. 15. 법률 제20000호로 공포된 「행정 절차법」 제10조에 적용하여야 한다."
        amendments = declared_amendments(text)
        assert len(amendments) >= 1, f"개정 이력이 추출되지 않음: {amendments}"


# ── 양성: review_declared_amendments에서 TEMPORAL_LAW_MISMATCH 생성 ────

class TestReviewPositive:
    """처분일보다 뒤에 개정된 법령 적용 주장 → TEMPORAL_LAW_MISMATCH 생성."""

    def test_disposition_after_amendment(self):
        """처분일 2024-02-20, 개정 공포일 2025-03-01 → 탐지."""
        text = ("해당 처분은 부당하며, 2025년 3월 1일 대통령령 제35800호로 개정·공포된 "
                "「군인 징계령」 제12조 제2항 단서에 따르면 적용하여야 한다.")
        reference = {"date": "2024-02-20", "kind": "DISPOSITION", "basis": "DOCUMENT_INFERRED",
                     "note": "문서에서 처분일로 추정한 2024-02-20을 기준일로 썼다"}
        findings = review_declared_amendments(text, reference, criminal=False)
        assert len(findings) >= 1, f"TEMPORAL_LAW_MISMATCH finding이 생성되지 않음"
        f = findings[0]
        assert f.type.name == "TEMPORAL_LAW_MISMATCH"
        # 처분시법주의 법적 근거가 포함되어야 함
        assert "처분시법주의" in f.detail or "92누19033" in f.detail

    def test_civil_law_amendment(self):
        """민사 사건에서 행위 후 시행 조항 적용 주장."""
        text = ("2025. 1. 15. 법률 제19999호로 개정된 「민법」 제750조에 따르면 적용되어 "
                "피고에게 책임이 있다.")
        reference = {"date": "2024-06-01", "kind": "TORT", "basis": "DOCUMENT_INFERRED"}
        findings = review_declared_amendments(text, reference, criminal=False)
        assert len(findings) >= 1

    def test_criminal_amendment(self):
        """형사 사건에서 행위 후 시행 조항 적용 주장."""
        text = ("2025. 4. 1. 법률 제20100호로 개정된 「형법」 제250조 제1항의 신법이 적용되어 "
                "피고인은 무죄이다.")
        reference = {"date": "2024-01-01", "kind": "OFFENSE", "basis": "DOCUMENT_INFERRED"}
        findings = review_declared_amendments(text, reference, criminal=True)
        assert len(findings) >= 1
        # 형사 사건이므로 형법 제1조 근거가 포함
        assert "형법 제1조" in findings[0].detail


# ── 대조군: 탐지되지 않아야 하는 경우 ─────────────────────────────────

class TestReviewNegative:
    """탐지되면 안 되는 경우들."""

    def test_amendment_before_disposition(self):
        """개정일이 처분일보다 앞 → 미탐지."""
        text = ("2023년 1월 1일 대통령령 제33000호로 개정·공포된 「군인 징계령」 제12조 제2항에 "
                "따르면 적용하여야 한다.")
        reference = {"date": "2024-02-20", "kind": "DISPOSITION"}
        findings = review_declared_amendments(text, reference, criminal=False)
        assert len(findings) == 0, f"개정일이 처분일보다 앞인데 탐지됨: {findings}"

    def test_no_reliance_claim(self):
        """단순 참고 언급(적용 주장 없음) → 미탐지."""
        text = ("참고로 2025년 3월 1일 대통령령 제35800호로 개정·공포된 「군인 징계령」 제12조 "
                "제2항은 다음과 같이 규정하고 있다.")
        reference = {"date": "2024-02-20", "kind": "DISPOSITION"}
        findings = review_declared_amendments(text, reference, criminal=False)
        assert len(findings) == 0, f"단순 참고 언급인데 탐지됨: {findings}"

    def test_act_time_law_discussion(self):
        """행위시법 논의 → 미탐지."""
        text = ("2025년 3월 1일 대통령령 제35800호로 개정·공포된 「군인 징계령」 제12조 제2항과 "
                "관련하여, 행위 당시의 법령에 의하면 개정 전의 규정이 적용된다.")
        reference = {"date": "2024-02-20", "kind": "DISPOSITION"}
        findings = review_declared_amendments(text, reference, criminal=False)
        assert len(findings) == 0, f"행위시법 논의인데 탐지됨: {findings}"

    def test_no_reference_date(self):
        """기준일이 없으면 탐지하지 않음."""
        text = ("2025년 3월 1일 대통령령 제35800호로 개정·공포된 「군인 징계령」 제12조 제2항 "
                "단서에 따르면 적용하여야 한다.")
        reference = {"date": None, "kind": "DISPOSITION"}
        findings = review_declared_amendments(text, reference, criminal=False)
        assert len(findings) == 0, f"기준일 없는데 탐지됨: {findings}"

    def test_old_law_affirmative_application(self):
        """행위 당시의 법률에 의하여 판단하여야 하므로 구법이 적용된다 → 정상적 구법 변론이므로 미탐지."""
        text = ("2025년 3월 1일 대통령령 제35800호로 개정·공포된 「군인 징계령」 제12조와 관련하여, "
                "행위 당시의 법률에 의하여 구법이 적용되어야 한다.")
        reference = {"date": "2024-02-20", "kind": "DISPOSITION"}
        findings = review_declared_amendments(text, reference, criminal=False)
        assert len(findings) == 0, f"구법 적용 변론인데 탐지됨: {findings}"

    def test_prior_provision_governs(self):
        """개정 전의 규정에 의거하여 처분되었으므로 정당하다 → 미탐지."""
        text = ("2025. 1. 1. 법률 제20000호로 개정된 「국가재정법」 제10조에도 불구하고, "
                "개정 전의 규정에 의거 판단하여야 하므로 위법이 없다.")
        reference = {"date": "2024-01-01", "kind": "DISPOSITION"}
        findings = review_declared_amendments(text, reference, criminal=False)
        assert len(findings) == 0

    def test_old_statute_applied(self):
        """행위 시의 법령에 따라 구법 조항을 적용한다 → 미탐지."""
        text = ("2025년 개정된 규정이 있으나 행위 시의 법령에 따라 구법을 적용하여야 마땅하다.")
        reference = {"date": "2024-01-01", "kind": "DISPOSITION"}
        findings = review_declared_amendments(text, reference, criminal=False)
        assert len(findings) == 0


class TestComparativeOldLawPositive:
    """구법을 비교 대상으로 언급하며 사후 개정 신법 적용을 주장하는 경우 (양성)."""

    def test_comparative_better_new_law(self):
        """'행위 당시 구법보다 유리하게 개정된 최신 규정 적용' → 소급 적용 오류 탐지."""
        text = ("피고의 처분은 부당하며, 2025년 3월 1일 대통령령 제35800호로 개정·공포된 "
                "「군인 징계령」 제12조 제2항 단서에 따르면 적용하여야 합니다. "
                "행위 당시 구법보다 징계 대상자에게 유리하게 개정된 최신 법령의 감경 규정을 적용하여야 합니다.")
        reference = {"date": "2024-02-20", "kind": "DISPOSITION"}
        findings = review_declared_amendments(text, reference, criminal=False)
        assert len(findings) >= 1, f"비교 구법 언급 신법 적용 주장이 탐지되지 않음: {findings}"
        assert findings[0].type.name == "TEMPORAL_LAW_MISMATCH"

    def test_old_law_superseded(self):
        """'구법 대신 개정 신법 적용' → 소급 적용 오류 탐지."""
        text = ("2025. 5. 1. 대통령령 제36000호로 개정된 「공무원 징계령」 제5조에 따라, "
                "구법 대신 신법 규정을 적용하여 처분하여야 합니다.")
        reference = {"date": "2024-05-01", "kind": "DISPOSITION"}
        findings = review_declared_amendments(text, reference, criminal=False)
        assert len(findings) >= 1

    def test_old_law_notwithstanding(self):
        """'구법에 불구하고 개정 신법에 따라 면책' → 소급 적용 오류 탐지."""
        text = ("2025. 6. 1. 법률 제21000호로 개정된 「도로교통법」 제44조의 신법 취지에 비추어, "
                "구법에 불구하고 개정 조항에 따라 피고인은 면책되어야 합니다.")
        reference = {"date": "2024-01-01", "kind": "OFFENSE"}
        findings = review_declared_amendments(text, reference, criminal=True)
        assert len(findings) >= 1
