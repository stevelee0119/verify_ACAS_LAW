"""평가 도구 `scripts/probe_regex_complexity.py`가 알려진 지수 증가 정규식을 잡고 선형 정규식은 통과시키는지 시험(평가 에이전트).

알려진 두 사례는 CodeQL `py/redos`가 가리킨 곳이다(TK-38). 제품 코드를 고치면 그 정규식이 더 이상 지수가 아니게 되므로
이 시험은 **도구가 지수 증가를 알아본다**는 것만 고정하는 합성 정규식으로 한다. 제품 정규식의 시간 예산 시험은
TK-38 착수 시 평가 측이 별도로 둔다.
"""
from __future__ import annotations

import importlib.util
import re
import signal
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "probe_regex_complexity", Path(__file__).resolve().parents[1] / "scripts" / "probe_regex_complexity.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def _arm():
    signal.signal(signal.SIGALRM, probe._on_alarm)


def test_alternation_pumps_for_str_and_bytes():
    assert [f(1) for f in probe.alternation_pumps(r"(?:ab|a|b)+$")] == ["abab" + "X", "1 ab  1 a  1 b  X"]
    byte_pumps = [f(1) for f in probe.alternation_pumps(rb"(?:Tm|Td)\s*")]
    assert byte_pumps == [b"TmTdX", b"1 Tm  1 Td  X"]


def test_ambiguous_alternation_repeat_is_flagged_as_exponential():
    _arm()
    pattern = r"(?:ab|a|b)+$"  # 'ab'을 'a'+'b'로도 읽을 수 있어 실패할 때 모든 분할을 되짚는다(합성 사례)
    assert probe.exponential_hit(re.compile(pattern), pattern) is not None


def test_overlapping_whitespace_in_bytes_pattern_is_flagged():
    _arm()
    pattern = rb"^\s*(?:[-\d.\s]+(?:Tm|Td)\s*)*Z"  # 반복 끝의 \s*와 다음 반복 앞의 [\s]+가 같은 공백을 나눠 갖는다(합성 사례)
    assert probe.exponential_hit(re.compile(pattern), pattern) is not None


def test_linear_equivalent_is_not_flagged():
    _arm()
    pattern = r"[ab]+$"
    assert probe.exponential_hit(re.compile(pattern), pattern) is None
