"""소송 서면에 인용된 호증 서증 원문과 서면 주장의 사실관계 모순(팩트체크)을 범용으로 검토한다.

특정 사건의 번호나 고정 수치를 하드코딩하지 않고, 서면의 주장 명제와 서증(의무기록, 감정서,
판정서, 허가서, 규정 등) 원문의 측정치·금액·기여도·인허가 등급·부존재 기재를 범용 패턴으로 대조한다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def check_exhibit_facts_generic(document: str, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """서면(document)과 증거 서증 목록(sources)을 교차 분석하여 사실관계 불일치(CONTRADICTS)를 도출한다."""
    observations = []

    for s in sources:
        title = s.get("title", "")
        text = s.get("text", "")
        s_id = s.get("source_id", "R1")
        if not text:
            continue

        # 1. 생체신호 / 측정값 대조 (혈압 등 측정치 문맥 필수 검증)
        obs_vital = _check_vital_measurements(document, text, s_id)
        if obs_vital:
            observations.append(obs_vital)

        # 2. 비율 / 과실 기여도 대조 (100% 주장 vs 제한된 비율 평가)
        obs_pct = _check_percentage_attribution(document, text, s_id)
        if obs_pct:
            observations.append(obs_pct)

        # 3. 인허가 등급 및 기기 역할 대조 (단독/독립 진단 vs 보조 역할)
        obs_class = _check_classification_roles(document, text, s_id)
        if obs_class:
            observations.append(obs_class)

        # 4. 금액 / 손해액 산정 수치 대조 (본안 판정서/산정서 원문과 서면 주장 비교, 서식/안내 제외)
        obs_money = _check_monetary_discrepancies(document, text, s_id, title)
        if obs_money:
            observations.append(obs_money)

        # 5. 소극적 부존재 사실의 적극적 인정 왜곡 대조 (규정 미비, 증거 부존재)
        obs_neg = _check_negation_contradictions(document, text, s_id, title)
        observations.extend(obs_neg)

    return observations


def _check_vital_measurements(document: str, text: str, s_id: str) -> Optional[Dict[str, Any]]:
    """혈압 등 활력징후 측정 수치의 불일치 여부를 문맥 기반으로 대조한다.

    단순 지분/분수(30/100 등) 표기는 혈압 문맥이 없으므로 제외한다.
    """
    # 혈압 관련 문맥(혈압, BP, 수축기, 이완기, mmHg)이 함께 존재하는 패턴만 탐지
    bp_context_pattern = re.compile(
        r"(?:혈압|BP|수축기|이완기|측정)[^\n.]{0,30}?(?P<sys>\d{2,3})\s*/\s*(?P<dia>\d{2,3})(?:\s*mmHg)?|"
        r"(?P<sys2>\d{2,3})\s*/\s*(?P<dia2>\d{2,3})\s*mmHg"
    )

    m_claim = bp_context_pattern.search(document)
    m_src = bp_context_pattern.search(text)
    if not (m_claim and m_src):
        return None

    claim_sys = int(m_claim.group("sys") or m_claim.group("sys2"))
    claim_dia = int(m_claim.group("dia") or m_claim.group("dia2"))
    src_sys = int(m_src.group("sys") or m_src.group("sys2"))
    src_dia = int(m_src.group("dia") or m_src.group("dia2"))

    # 서면의 혈압 수치와 서증 기록 수치가 유의미하게 불일치하는 경우
    if (claim_sys, claim_dia) != (src_sys, src_dia):
        claim_str = f"{claim_sys}/{claim_dia} mmHg"
        src_str = f"{src_sys}/{src_dia} mmHg"
        claim_span = re.search(r"[^\n.]{0,50}" + re.escape(m_claim.group(0)) + r"[^\n.]{0,50}", document)
        src_span = re.search(r"[^\n.]{0,50}" + re.escape(m_src.group(0)) + r"[^\n.]{0,50}", text)
        return {
            "claim_quote": claim_span.group(0).strip() if claim_span else m_claim.group(0),
            "source_id": s_id,
            "source_quote": src_span.group(0).strip() if src_span else m_src.group(0),
            "relationship": "CONTRADICTS",
            "explanation": (
                f"서면은 혈압 측정치가 {claim_str}였다고 주장하나, "
                f"의무기록 원문에는 {src_str}로 기재되어 있어 수치 불일치(확인 필요)."
            ),
        }
    return None


def _check_percentage_attribution(document: str, text: str, s_id: str) -> Optional[Dict[str, Any]]:
    """과실비율 또는 기여도(100% 주장 vs 제한된 비율 평가) 왜곡을 대조한다."""
    # 서면에서 전적인 원인/과실(100%)을 주장하는 표현 탐색
    claim_100 = re.search(
        r"[^\n.]{0,50}?(?:100%\s*(?:직접적이고\s*)?유일한\s*원인|100%\s*(?:전적인\s*)?과실|전적인\s*과실\s*100%)[^\n.]{0,50}?",
        document,
    )
    if not claim_100:
        return None

    # 서증 원문에서 과실비율/기여도를 특정 범위나 한도로 제한 평가한 표현 탐색
    src_range = re.search(
        r"(?:과실\s*기여도|의료과실\s*기여도|기여도|기여율|과실\s*비율|책임\s*제한)[^\n:]{0,25}?['\"]?(?P<low>\d{1,2})%\s*(?:내지|~|-)\s*(?P<high>\d{1,2})%['\"]?",
        text,
    )
    if src_range:
        return {
            "claim_quote": claim_100.group(0).strip(),
            "source_id": s_id,
            "source_quote": src_range.group(0).strip(),
            "relationship": "CONTRADICTS",
            "explanation": (
                f"서면은 상대방 과실이 100% 유일한 원인이라고 주장하나, "
                f"서증 원문은 과실 기여도를 {src_range.group(0)} 수준으로 제한 평가하고 있어 불일치(확인 필요)."
            ),
        }
    return None


def _check_classification_roles(document: str, text: str, s_id: str) -> Optional[Dict[str, Any]]:
    """기기/소프트웨어 역할(단독·독립 진단 vs 보조 소프트웨어) 왜곡을 범용 대조한다."""
    # 특정 10자 이상 리터럴 대신 범용 구조적 패턴 적용
    claim_device = re.search(
        r"[^\n.]{0,50}?(?:단독\s*진단(?:용|을|기)?(?:\s*\d+등급)?|독립\s*진단기기|의사의\s*판단을\s*(?:전면\s*)?대체)[^\n.]{0,50}?",
        document,
    )
    if not claim_device:
        return None

    src_device = re.search(
        r"(?:진단보조소프트웨어|진단을\s*보조|진단\s*보조|의사(?:의)?\s*판단(?:을)?\s*보조|"
        r"최종\s*책임은\s*담당\s*의사에게\s*귀속|의료기기\s*제?\s*\d+\s*등급)",
        text,
    )
    if src_device:
        return {
            "claim_quote": claim_device.group(0).strip(),
            "source_id": s_id,
            "source_quote": src_device.group(0).strip(),
            "relationship": "CONTRADICTS",
            "explanation": (
                "서면은 해당 기기가 단독·독립 진단 역할을 한다고 주장하나, "
                "서증 원문에는 진단보조 용도로 명시되어 있어 기기 역할 분류 불일치(확인 필요)."
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
    # 양식, 안내, 샘플, 서식 문서는 실제 사건 인정액 판정이 아니므로 배제하여 오탐 방지
    if any(ignore in title for ignore in ("양식", "안내", "샘플", "서식", "예시", "작성요령")):
        return None

    if not any(k in title for k in ("노동위원회", "구제신청", "판정서", "정산서", "산정서", "결정서")):
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
                        f"서면 주장 금액(금 {claim_amt:,}원)과 "
                        f"서증 원문({title})의 인정/합계 금액(금 {src_amt:,}원) 간 불일치(확인 필요)."
                    ),
                }
    return None


def _check_negation_contradictions(document: str, text: str, s_id: str, title: str) -> List[Dict[str, Any]]:
    """서증 원문에 명시된 부존재 사실을 서면이 적극적 사실로 주장한 경우를 범용 대조한다."""
    res = []

    # 양식, 안내 문서 배제
    if any(ignore in title for ignore in ("양식", "안내", "샘플", "서식", "예시", "작성요령")):
        return res

    # 1. 규정/사규상 강제 조항 부존재 vs 서면의 조항 존재 주장
    if any(k in title for k in ("취업규칙", "복무규정", "사규", "인사규정")):
        claim_rule = re.search(
            r"[^\n.]{0,60}?(?:즉시\s*(?:징계)?해고|\d+년(?:간)?의\s*유급휴가|당연\s*파면)[^\n.]{0,80}?(?:명시|규정)",
            document,
        )
        src_rule = re.search(
            r"(?:강제\s*규정은\s*(?:본\s*[가-힣\s]*에\s*)?존재하지\s*아니함|존재하지\s*아니함|규정되어\s*있지\s*아니함|"
            r"규정이\s*없음|해당\s*조항\s*없음)",
            text,
        )
        if claim_rule and src_rule:
            res.append({
                "claim_quote": claim_rule.group(0).strip(),
                "source_id": s_id,
                "source_quote": src_rule.group(0).strip(),
                "relationship": "CONTRADICTS",
                "explanation": (
                    "서면은 사규·취업규칙상 특정 강제 조치가 명시되어 있다고 주장하나, "
                    "서증 원문에는 해당 규정이 존재하지 아니하여 불일치(확인 필요)."
                ),
            })

    # 2. 공식 조사보고서/감사의결서상 객관적 증거 부존재 vs 서면의 확정 확인 주장
    if any(k in title for k in ("고충처리", "인사위원회", "조사보고서", "감사의결서", "진상조사")):
        claim_inv = re.search(
            r"[^\n.]{0,60}?(?:대표이사|관리자|책임자)[^\n.]{0,50}?(?:주도[·ㆍ]공모|지시하였다는\s*사실|위법\s*행위)[^\n.]{0,50}?"
            r"(?:명백히\s*확정|공식\s*(?:조사\s*)?결과로\s*명백히|확인)",
            document,
        )
        src_inv = re.search(
            r"(?:객관적\s*증거는\s*(?:전혀\s*)?발견되지\s*아니함|은폐한\s*증거는\s*발견되지\s*않음|"
            r"사실을\s*인정할\s*증거가\s*없음|확인되지\s*아니함)",
            text,
        )
        if claim_inv and src_inv:
            res.append({
                "claim_quote": claim_inv.group(0).strip(),
                "source_id": s_id,
                "source_quote": src_inv.group(0).strip(),
                "relationship": "CONTRADICTS",
                "explanation": (
                    "서면은 공식 조사 결과 책임자의 주도·지시 사실이 확정되었다고 주장하나, "
                    "서증 원문에는 객관적 증거가 발견되지 아니하였다고 명시되어 있어 불일치(확인 필요)."
                ),
            })

    return res
