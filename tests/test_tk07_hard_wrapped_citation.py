"""TK-07: 줄바꿈으로 갈라진 법령 인용 결합 단위 테스트.

양성(줄바꿈이 있어도 추출되어야 함) 3건 이상,
대조군(별도 인용이 오합되지 않아야 함) 3건 이상.
"""
from __future__ import annotations

import pytest

from packages.legal_engine.citation_extractor import (
    _join_hard_wrapped_citations,
    extract_from_text,
)

# ── 양성 예시: 줄바꿈이 있어도 같은 인용으로 추출 ──────────────────────

class TestPositive:
    """줄바꿈으로 갈라진 법령 인용이 추출되는지 확인."""

    def test_bracket_newline_simple(self):
        """「군인\\n징계령」 제12조 → 군인징계령 제12조 추출."""
        text = "해당 처분은 「군인\n징계령」 제12조 제2항에 따른 것이다."
        citations = extract_from_text(text)
        # 법령 인용이 최소 1건 추출되어야 함
        laws = [c for c in citations if c.law_name]
        assert len(laws) >= 1, f"법령 인용이 추출되지 않음: {citations}"
        # 법령명에 '징계령'이 포함되어야 함
        assert any("징계령" in (c.law_name or "") for c in laws), \
            f"징계령 인용이 없음: {[c.law_name for c in laws]}"

    def test_bracket_newline_long_name(self):
        """「육군 군인·군무원 징계업무\\n처리 훈령」 제15조 → 추출."""
        text = "또한 「육군 군인·군무원 징계업무\n처리 훈령」 제15조 제3항에서 규정하고 있다."
        citations = extract_from_text(text)
        laws = [c for c in citations if c.law_name]
        assert len(laws) >= 1, f"법령 인용이 추출되지 않음: {citations}"
        # '처리 훈령' 또는 '훈령' 포함
        assert any("훈령" in (c.law_name or "") for c in laws), \
            f"훈령 인용이 없음: {[c.law_name for c in laws]}"

    def test_presuffix_newline_without_bracket(self):
        """낫표 없이 '군인사\n법 제57조' → 군인사법 제57조 추출."""
        text = "군인사\n법 제57조 제1항에 의하면"
        citations = extract_from_text(text)
        laws = [c for c in citations if c.law_name]
        assert len(laws) >= 1, f"법령 인용이 추출되지 않음: {citations}"
        assert any("군인사법" in (c.law_name or "").replace(" ", "") for c in laws), \
            f"군인사법 인용이 없음: {[c.law_name for c in laws]}"

    def test_double_space_in_bracket(self):
        """「군인  징계령」 제12조 (여러 공백) → 추출."""
        text = "「군인  징계령」 제12조에 따르면"
        citations = extract_from_text(text)
        laws = [c for c in citations if c.law_name]
        assert len(laws) >= 1, f"법령 인용이 추출되지 않음: {citations}"


# ── 대조군: 별도 문장의 줄바꿈이 오합되지 않아야 함 ────────────────────

class TestNegative:
    """줄바꿈이 별도 문장을 구분할 때 오결합하지 않는지 확인."""

    def test_separate_sentences_not_joined(self):
        """별도 문장의 줄바꿈이 법령명으로 결합되면 안 됨."""
        text = "원고의 주장은 이유 없다.\n형법 제250조 제1항에 해당한다."
        citations = extract_from_text(text)
        # 형법 제250조 인용은 정상 추출
        laws = [c for c in citations if c.law_name and "형법" in c.law_name]
        assert len(laws) >= 1
        # "이유 없다" 부분이 법령명에 결합되면 안 됨
        for c in laws:
            assert "이유" not in (c.law_name or ""), \
                f"별도 문장이 법령명에 결합됨: {c.law_name}"

    def test_unrelated_bracket_content_not_joined(self):
        """닫는 낫표와 여는 낫표가 다른 인용인 경우 결합되면 안 됨."""
        text = "「군인사법」 제57조와\n「군인징계령」 제12조는 다르다."
        citations = extract_from_text(text)
        # 두 개의 별도 인용이 추출되어야 함
        law_names = [c.law_name for c in citations if c.law_name]
        assert len(law_names) >= 2, f"두 인용이 추출되어야 함: {law_names}"

    def test_paragraph_break_not_joined(self):
        """빈 줄(문단 경계)로 나뉜 텍스트가 법령명으로 결합되면 안 됨."""
        text = "이 사건에서 적용되는\n\n국가배상법 제2조 제1항에 따르면"
        citations = extract_from_text(text)
        # 줄바꿈이 두 개(빈 줄)이므로 결합하지 않음
        laws = [c for c in citations if c.law_name]
        # 국가배상법이 추출되든 안 되든, "적용되는" 이 법령명에 들어가면 안 됨
        for c in laws:
            assert "적용" not in (c.law_name or ""), \
                f"문단 경계가 법령명에 결합됨: {c.law_name}"

    def test_long_gap_not_joined(self):
        """문단 경계 뒤에 법령 인용이 나올 때 앞 문장과 결합하면 안 됨."""
        text = "이 사건에서 원고의 주장은 이유 없다.\n\n군인사법 제57조에 의하면"
        # 빈 줄(문단 경계)은 결합하지 않아야 함
        preprocessed = _join_hard_wrapped_citations(text)
        # 빈 줄이 그대로 남아 있어야 함
        assert "\n\n" in preprocessed


# ── 전처리 함수 직접 검증 ──────────────────────────────────────────────

class TestPreprocessor:
    """_join_hard_wrapped_citations 전처리 함수의 단위 테스트."""

    def test_bracket_join(self):
        """낫표 안 줄바꿈이 공백으로 치환."""
        text = "「군인\n징계령」"
        assert _join_hard_wrapped_citations(text) == "「군인 징계령」"

    def test_presuffix_join(self):
        """법령명 접미사 직전 줄바꿈이 공백으로 치환."""
        text = "군인사\n법 제1조"
        result = _join_hard_wrapped_citations(text)
        assert "\n" not in result
        assert "군인사 법" in result or "군인사법" in result

    def test_no_change_normal_text(self):
        """법령과 무관한 일반 줄바꿈은 그대로 유지."""
        text = "원고는 주장하였다.\n피고는 반박하였다."
        result = _join_hard_wrapped_citations(text)
        assert result == text  # 변경 없음

    def test_length_preserved(self):
        """치환 후 문자열 길이가 보존됨."""
        text = "「군인\n징계령」 제12조"
        result = _join_hard_wrapped_citations(text)
        assert len(result) == len(text)
