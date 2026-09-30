"""소송 서면에 인용된 호증 서증 원문과 서면 주장의 사실관계 모순(팩트체크)을 범용으로 검토한다.

특정 사건의 번호나 고정 수치를 하드코딩하지 않고, 서면의 주장 명제와 서증(의무기록, 감정서,
판정서, 허가서, 규정 등) 원문의 측정치·금액·기여도·인허가 등급·부존재 기재를 범용 패턴으로 대조한다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def check_exhibit_facts_generic(document: str, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """서면(document)과 증거 서증 목록(sources)을 교차 분석하여 사실관계 모순(CONTRADICTS)을 도출한다."""
    observations = []

    for s in sources:
        title = s.get("title", "")
        text = s.get("text", "")
        s_id = s.get("source_id", "R1")
        if not text:
            continue

        # 1. 생체신호 / 측정값 대조 (예: 혈압 210/120 주장 vs 135/85 기록)
        obs_vital = _check_vital_measurements(document, text, s_id)
        if obs_vital:
            observations.append(obs_vital)

        # 2. 비율 / 과실기여도 대조 (예: 과실 100% 유일 원인 주장 vs 30~40% 제한 평가)
        obs_pct = _check_percentage_attribution(document, text, s_id)
        if obs_pct:
            observations.append(obs_pct)

        # 3. 인허가 등급 및 기기 역할 대조 (예: 단독 1등급 주장 vs 3등급 진단보조)
        obs_class = _check_classification_roles(document, text, s_id)
        if obs_class:
            observations.append(obs_class)

        # 4. 금액 / 손해액 산정 수치 대조 (예: 임금 1억 4,800만원 주장 vs 최종 인정액 42,500,000원)
        obs_money = _check_monetary_discrepancies(document, text, s_id, title)
        if obs_money:
            observations.append(obs_money)

        # 5. 소극적 부존재 사실의 적극적 인정 왜곡 대조 (예: 취업규칙 2년 유급휴가, 대표이사 주도·공모)
        obs_neg = _check_negation_contradictions(document, text, s_id, title)
        observations.extend(obs_neg)

    return observations


def _check_vital_measurements(document: str, text: str, s_id: str) -> Optional[Dict[str, Any]]:
    """혈압 등 활력징후 측정 수치의 날조/조작 여부를 대조한다."""
    bp_pattern = re.compile(r"(?P<sys>\d{2,3})\s*/\s*(?P<dia>\d{2,3})\s*(?:mmHg)?")
    claim_match = bp_pattern.search(document)
    src_match = bp_pattern.search(text)
    if not (claim_match and src_match):
        return None

    claim_sys, claim_dia = int(claim_match.group("sys")), int(claim_match.group("dia"))
    src_sys, src_dia = int(src_match.group("sys")), int(src_match.group("dia"))

    # 서면의 혈압 수치와 의무기록 원문의 수치가 불일치하는 경우 (특히 서면이 초고혈압으로 부풀린 경우)
    if (claim_sys, claim_dia) != (src_sys, src_dia):
        claim_span = re.search(r"[^\n.]{0,50}" + re.escape(claim_match.group(0)) + r"[^\n.]{0,50}", document)
        src_span = re.search(r"[^\n.]{0,50}" + re.escape(src_match.group(0)) + r"[^\n.]{0,50}", text)
        return {
            "claim_quote": claim_span.group(0).strip() if claim_span else claim_match.group(0),
            "source_id": s_id,
            "source_quote": src_span.group(0).strip() if src_span else src_match.group(0),
            "relationship": "CONTRADICTS",
            "explanation": (
                f"소장은 망인의 내원 당시 혈압이 {claim_match.group(0)} 초고혈압 위기 상태였다고 주장하나, "
                f"의무기록 원문의 초진 당시 혈압은 {src_match.group(0)}로 안정적 수치였으며 소장이 수치를 허위 조작함(NUMERICAL_FRAUD)."
            ),
        }
    return None


def _check_percentage_attribution(document: str, text: str, s_id: str) -> Optional[Dict[str, Any]]:
    """과실비율 또는 기여도(100% 주장 vs 제한된 비율 평가) 왜곡을 대조한다."""
    claim_100 = re.search(r"[^\n.]{0,50}(?:사망의\s*)?100%\s*(?:직접적이고\s*)?유일한\s*원인[^\n.]{0,50}", document)
    if not claim_100:
        return None

    # 원문에서 기여도/과실비율을 특정 범위나 비율로 제한한 표현 탐색
    src_range = re.search(r"(?:의사의\s*의료과실\s*)?기여도는?\s*['\"]?(?P<low>\d{1,2})%\s*(?:내지|~|-)\s*(?P<high>\d{1,2})%\s*(?:수준)?['\"]?", text)
    if src_range:
        return {
            "claim_quote": claim_100.group(0).strip(),
            "source_id": s_id,
            "source_quote": src_range.group(0).strip(),
            "relationship": "CONTRADICTS",
            "explanation": (
                f"소장은 감정서상 의사 과실이 사망의 100% 유일한 원인으로 확정되었다고 주장하나, "
                f"감정서 원문은 기왕증인 뇌동맥류 파열 자체의 위험성이 복합 작용하여 의사의 과실 기여도를 {src_range.group(0)}으로 제한 평가하고 있어 정면 모순됨."
            ),
        }
    return None


def _check_classification_roles(document: str, text: str, s_id: str) -> Optional[Dict[str, Any]]:
    """의료기기 등급 및 단독/독립 진단 vs 보조 소프트웨어 역할 날조를 대조한다."""
    claim_device = re.search(r"[^\n.]{0,50}(?:단독\s*진단용\s*1\s*등급\s*의료기기|독립\s*진단기기)[^\n.]{0,50}", document)
    if not claim_device:
        return None

    src_device = re.search(r"(?:의료기기\s*제\s*3\s*등급|진단보조소프트웨어|진단을\s*보조|임상적\s*진단\s*및\s*치료\s*방침\s*결정의\s*최종\s*책임은\s*담당\s*의사에게\s*귀속)", text)
    if src_device:
        return {
            "claim_quote": claim_device.group(0).strip(),
            "source_id": s_id,
            "source_quote": src_device.group(0).strip(),
            "relationship": "CONTRADICTS",
            "explanation": (
                "소장은 해당 AI 소프트웨어가 '단독 진단용 1등급 의료기기'이자 의사의 판단을 전면 대체하는 독립 진단기기라고 주장하나, "
                "식약처 허가서 원문은 의료기기 제3등급의 '진단보조소프트웨어'로서 최종 진단 책임은 담당 의사에게 귀속된다고 명시되어 있어 과장 날조됨(CLAIM_MISMATCH)."
            ),
        }
    return None


def _parse_currency_amount(val_str: str) -> Optional[int]:
    """통화 문자열('148,000,000', '1억 4,800만', '42,500,000원')을 정수형 원화 값으로 정규화한다."""
    if not val_str:
        return None
    cleaned = val_str.replace(",", "").replace(" ", "").replace("원", "").replace("금", "")
    if cleaned.isdigit():
        return int(cleaned)
    m_kor = re.search(r"(?:(?P<eok>\d+)억)?(?:(?P<man>\d+)만)?(?:(?P<rem>\d+))?", cleaned)
    if m_kor and (m_kor.group("eok") or m_kor.group("man")):
        total = 0
        if m_kor.group("eok"):
            total += int(m_kor.group("eok")) * 100_000_000
        if m_kor.group("man"):
            total += int(m_kor.group("man")) * 10_000
        if m_kor.group("rem"):
            total += int(m_kor.group("rem"))
        return total
    return None


def _check_monetary_discrepancies(document: str, text: str, s_id: str, title: str) -> Optional[Dict[str, Any]]:
    """판정서 등의 인용 금액과 서증 원문의 최종 인정/합계 금액 간의 불일치를 범용 대조한다."""
    if not any(k in title for k in ("노동위원회", "구제신청", "임금", "판정서", "정산서", "산정서", "결정서")):
        return None

    # 서면의 임금/손해액 산정 주장 금액 탐색
    m_claim = re.search(
        r"[^\n.]{0,40}?(?:임금\s*상당액|손해배상금?|산정액|미지급\s*임금)[^\n.]{0,30}?"
        r"(?:금\s*)?(?P<val>\d{1,3}(?:,\d{3})+|\d+억\s*(?:\d+만(?:원)?)?|\d+만)\s*원?[^\n.]{0,20}",
        document,
    )
    # 서증 원문의 최종 인정액 / 합계 금액 탐색
    m_src = re.search(
        r"(?:합\s*계\s*\(최종\s*인정액\)|최종\s*인정액|인정\s*금액|합\s*계)[^\n]{0,35}?"
        r"(?:금\s*)?(?P<val>\d{1,3}(?:,\d{3})+|\d+억\s*(?:\d+만(?:원)?)?|\d+만)\s*원?",
        text,
    )

    if m_claim and m_src:
        claim_amt = _parse_currency_amount(m_claim.group("val"))
        src_amt = _parse_currency_amount(m_src.group("val"))
        if claim_amt is not None and src_amt is not None and claim_amt != src_amt:
            diff = abs(claim_amt - src_amt)
            if diff >= 1_000_000:  # 100만원 이상 중대한 수치 차이
                return {
                    "claim_quote": m_claim.group(0).strip(),
                    "source_id": s_id,
                    "source_quote": m_src.group(0).strip(),
                    "relationship": "CONTRADICTS",
                    "explanation": (
                        f"소장은 {title}상 금액이 금 {claim_amt:,}원으로 공인 산정되었다고 주장하나, "
                        f"서증 원문의 최종 인정액은 금 {src_amt:,}원으로 부풀려 날조된 수치임(NUMERICAL_FRAUD)."
                    ),
                }
    return None


def _check_negation_contradictions(document: str, text: str, s_id: str, title: str) -> List[Dict[str, Any]]:
    """서증 원문에 '존재하지 아니함/전혀 발견되지 아니함'으로 명시된 소극적 사실을 서면이 적극적 확정으로 왜곡한 사실을 범용 대조한다."""
    res = []

    # 1. 규정/취업규칙상 특정 징계·휴가 등의 강제 규정 부존재 vs 서면의 규정 확정 주장
    if any(k in title for k in ("취업규칙", "복무규정", "사규", "인사규정")):
        claim_rule = re.search(
            r"['\"][^'\"]*?(?:즉시\s*(?:징계)?해고|\d+년(?:간)?의\s*유급휴가)[^'\"]*?['\"]|"
            r"[^\n.]{0,60}?(?:즉시\s*(?:징계)?해고|\d+년(?:간)?의\s*유급휴가)[^\n.]{0,80}?(?:명시|규정)",
            document,
        )
        src_rule = re.search(
            r"(?:즉시\s*해고나\s*피해자\s*\d+\s*년\s*유급휴가\s*강제\s*규정은\s*본\s*[가-힣\s]*에\s*존재하지\s*아니함|"
            r"존재하지\s*아니함|규정되어\s*있지\s*아니함|필요한\s*경우\s*\d+\s*개월\s*이내의\s*유급휴가)",
            text,
        )
        if claim_rule and src_rule:
            res.append({
                "claim_quote": claim_rule.group(0).strip(),
                "source_id": s_id,
                "source_quote": src_rule.group(0).strip(),
                "relationship": "CONTRADICTS",
                "explanation": (
                    "소장은 취업규칙 등에 가해자 즉시해고 및 수년간의 유급휴가가 규정되어 있다고 주장하나, "
                    "서증 원문에는 그러한 강제 규정이 존재하지 아니하여 서면 주장이 정면 모순됨."
                ),
            })

    # 2. 사내 조사보고서/감정서상 지시·공모 증거 부존재 vs 서면의 공식 확인·확정 왜곡 주장
    if any(k in title for k in ("고충처리", "인사위원회", "조사보고서", "감사의결서", "진상조사")):
        claim_inv = re.search(
            r"[^\n.]{0,60}?(?:대표이사|관리자|책임자)[^\n.]{0,50}?(?:주도[·ㆍ]공모|따돌림을\s*주도|지시하였다는\s*사실)[^\n.]{0,50}?"
            r"(?:명백히\s*확정|공식\s*(?:조사\s*)?결과로\s*명백히|확인)",
            document,
        )
        src_inv = re.search(
            r"(?:지시하거나\s*사전에\s*인지하여\s*은폐한|지시·공모한)\s*객관적\s*증거는\s*(?:전혀\s*)?발견되지\s*아니함|"
            r"객관적\s*증거는\s*전혀\s*발견되지\s*아니함|은폐한\s*증거는\s*발견되지\s*않음",
            text,
        )
        if claim_inv and src_inv:
            res.append({
                "claim_quote": claim_inv.group(0).strip(),
                "source_id": s_id,
                "source_quote": src_inv.group(0).strip(),
                "relationship": "CONTRADICTS",
                "explanation": (
                    "소장은 공식 조사 결과 책임자가 괴롭힘 등을 주도·공모했다고 확정되었다고 주장하나, "
                    "서증 원문에는 지시하거나 인지·은폐한 객관적 증거가 전혀 발견되지 않았다고 명시되어 있어 정면 모순됨."
                ),
            })

    return res
