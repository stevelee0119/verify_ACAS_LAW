# -*- coding: utf-8 -*-
"""날짜·요일 일치성 및 달력 유효성 검증 엔진 (DATE-WEEKDAY, DATE-INVALID, DAYS).

서면에 기재된 날짜(연·월·일)와 괄호 표기 요일(월~일)의 역법상 일치 여부,
평년 2월 29일이나 30일 등 달력상 존재하지 않는 날짜,
그리고 두 날짜 사이의 일수(경과일) 계산 오류를 검증한다.
"""
from __future__ import annotations

import calendar
import datetime
import re
from typing import Any, Dict, List, Optional, Tuple

from packages.common.confidence import score as confidence_score
from packages.common.enums import EvidenceGrade, FindingType, ForensicLevel, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding, NormalizedDocument

ENGINE_NAME = "claim_engine.date_verifier"

# 요일 매핑 (0: 월요일, 6: 일요일)
KOREAN_WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
WEEKDAY_MAP = {name: idx for idx, name in enumerate(KOREAN_WEEKDAYS)}

# 날짜 + 요일 병기 패턴: 예) 2026. 3. 20.(목), 2026년 3월 20일(목요일)
DATE_WEEKDAY_RE = re.compile(
    r"(?P<year>\d{4})[.\s년/-]+(?P<month>\d{1,2})[.\s월/-]+(?P<day>\d{1,2})(?:일)?[\s.]*"
    r"(?:\((?P<weekday>[월화수목금토일])(?:요일)?\)|(?P<weekday_word>[월화수목금토일])요일(?![가-힣]))"
)

# 일반 날짜 패턴: 예) 2026. 2. 29., 2026년 2월 29일
DATE_GENERAL_RE = re.compile(
    r"(?P<year>\d{4})[.\s년/-]+(?P<month>\d{1,2})[.\s월/-]+(?P<day>\d{1,2})[일]?"
)

# 일수 경과 패턴: 예) "해고일로부터 76일이 지난 2026. 6. 25.", "2026. 3. 31.로부터 76일이 지난 2026. 6. 25."
DAYS_ELAPSED_RE = re.compile(
    r"(?:(?:(?P<from_y>\d{4})[.\s년/-]+(?P<from_m>\d{1,2})[.\s월/-]+(?P<from_d>\d{1,2})[일\s.]*)|(?:해고일|퇴사일|처분일|작성일|통지일))(?:로부터|부터|에서|이후|후)\s*"
    r"(?P<days>\d{1,4})\s*(?:일|日)(?:이\s*지난|경과한|후의?|째\s*되는)?\s*"
    r"(?P<to_y>\d{4})[.\s년/-]+(?P<to_m>\d{1,2})[.\s월/-]+(?P<to_d>\d{1,2})[일\s.]*"
)


def _parse_valid_date(year: int, month: int, day: int) -> Optional[datetime.date]:
    """유효한 날짜인지 검사하고 date 객체를 반환한다. 유효하지 않으면 None."""
    try:
        return datetime.date(year, month, day)
    except (ValueError, OverflowError):
        return None


def verify_dates_in_document(doc: NormalizedDocument) -> List[Finding]:
    """문서 내 모든 텍스트 블록에서 날짜 유효성, 요일 정합성, 경과일수를 검증한다."""
    findings: List[Finding] = []

    # 서면의 기준 해고일/처분일 등 추출 시도 (문맥용)
    context_incident_date: Optional[datetime.date] = None
    for block in doc.body_blocks():
        t = block.text
        m_inc = re.search(r"(?:해고일|처분일|통지일)은?\s*(?:은|는|이|가)?\s*(\d{4})[.\s년/-]+(\d{1,2})[.\s월/-]+(\d{1,2})", t)
        if m_inc:
            y, m, d = int(m_inc.group(1)), int(m_inc.group(2)), int(m_inc.group(3))
            d_obj = _parse_valid_date(y, m, d)
            if d_obj:
                context_incident_date = d_obj
                break

    for block in doc.body_blocks():
        text = block.text
        if not text:
            continue

        # 1. 날짜 + 요일 불일치 검증 (DATE-WEEKDAY)
        for m in DATE_WEEKDAY_RE.finditer(text):
            y = int(m.group("year"))
            month = int(m.group("month"))
            day = int(m.group("day"))
            weekday_str = m.group("weekday") or m.group("weekday_word")

            d_obj = _parse_valid_date(y, month, day)
            if d_obj is not None:
                actual_weekday_idx = d_obj.weekday()
                actual_weekday_str = KOREAN_WEEKDAYS[actual_weekday_idx]

                if weekday_str != actual_weekday_str:
                    matched_str = m.group(0)
                    features = {
                        "deterministic_rule": True,
                        "stated_date": f"{y}. {month}. {day}.",
                        "stated_weekday": weekday_str,
                        "actual_weekday": actual_weekday_str,
                        "rule_id": "claim_engine.date_verifier:DATE_WEEKDAY_MISMATCH",
                    }
                    findings.append(
                        Finding.create(
                            type=FindingType.TIMELINE_CONTRADICTION,
                            status=VerificationStatus.CONTRADICTED,
                            severity=Severity.MEDIUM,
                            evidence_grade=EvidenceGrade.A,
                            title=f"날짜와 요일 불일치: {y}. {month}. {day}.({weekday_str}) → 실제 {actual_weekday_str}요일",
                            detail=(
                                f"본문에 기재된 '{matched_str}'의 요일 표기가 달력과 일치하지 않는다. "
                                f"{y}년 {month}월 {day}일은 {actual_weekday_str}요일이나 본문에는 {weekday_str}요일로 기재되었다."
                            ),
                            confidence=1.0,
                            confidence_features=features,
                            document_id=doc.document_id,
                            block_id=block.block_id,
                            page=block.page,
                            engine=ENGINE_NAME,
                            tags=["TIMELINE", "DATE-WEEKDAY", "CALENDAR"],
                            evidence=[
                                Evidence.create(
                                    description="달력 역법상 요일 불일치",
                                    grade=EvidenceGrade.A,
                                    document_id=doc.document_id,
                                    block_id=block.block_id,
                                    page=block.page,
                                    excerpt=matched_str,
                                    supports=True,
                                )
                            ],
                        )
                    )

        # 2. 존재하지 않는 날짜 검증 (DATE-INVALID)
        # 예: 2026. 2. 29. (2026년은 평년) 또는 "2026. 2." 아래 "2. 29." / "2월 29일"
        # 1) YYYY. MM. DD. 직접 매칭
        for m in DATE_GENERAL_RE.finditer(text):
            y = int(m.group("year"))
            month = int(m.group("month"))
            day = int(m.group("day"))

            if 1 <= month <= 12 and 1 <= day <= 31:
                if _parse_valid_date(y, month, day) is None:
                    matched_str = m.group(0)
                    is_leap = calendar.isleap(y)
                    features = {
                        "deterministic_rule": True,
                        "year": y,
                        "month": month,
                        "day": day,
                        "is_leap_year": is_leap,
                        "rule_id": "claim_engine.date_verifier:DATE_INVALID",
                    }
                    findings.append(
                        Finding.create(
                            type=FindingType.EVIDENCE_DATE_INVALID,
                            status=VerificationStatus.CONTRADICTED,
                            severity=Severity.HIGH,
                            evidence_grade=EvidenceGrade.A,
                            title=f"달력상 존재하지 않는 날짜 기재: {matched_str}",
                            detail=(
                                f"{y}년 {month}월에는 {day}일이 존재하지 않는다"
                                + (f" ({y}년은 평년으로 2월 28일까지 존재)." if month == 2 and not is_leap else ".")
                            ),
                            confidence=1.0,
                            confidence_features=features,
                            document_id=doc.document_id,
                            block_id=block.block_id,
                            page=block.page,
                            engine=ENGINE_NAME,
                            tags=["TIMELINE", "DATE-INVALID", "CALENDAR"],
                            evidence=[
                                Evidence.create(
                                    description="존재하지 않는 날짜 표기",
                                    grade=EvidenceGrade.A,
                                    document_id=doc.document_id,
                                    block_id=block.block_id,
                                    page=block.page,
                                    excerpt=matched_str,
                                    supports=True,
                                )
                            ],
                        )
                    )

        # 2) 블록 내 선행 연도(예: 2026.) 아래 "2. 29." 또는 "2월 29일" 매칭
        m_feb29 = re.search(r"(?<!\d)(?:2|02)(?:\s*월\s*|[./-]\s*)29(?:일|(?=\D|$))", text)
        years = list(re.finditer(r"(?<!\d)([12]\d{3})(?:년|\s*\.)", text[:m_feb29.start()])) if m_feb29 else []
        block_year = int(years[-1].group(1)) if years else None
        if block_year is not None and not calendar.isleap(block_year):
            # 평년인데 2. 29. 또는 2월 29일이 있는 경우
            if m_feb29 and not any(m.start() <= m_feb29.start() < m.end() for m in DATE_GENERAL_RE.finditer(text)):
                # 이미 1)에서 찾은 것이 아닌 경우
                if not any(f.type == FindingType.EVIDENCE_DATE_INVALID and "29" in f.title for f in findings if f.block_id == block.block_id):
                    matched_str = m_feb29.group(0)
                    features = {
                        "deterministic_rule": True,
                        "year": block_year,
                        "month": 2,
                        "day": 29,
                        "is_leap_year": False,
                        "rule_id": "claim_engine.date_verifier:DATE_INVALID_FEB29",
                    }
                    findings.append(
                        Finding.create(
                            type=FindingType.EVIDENCE_DATE_INVALID,
                            status=VerificationStatus.CONTRADICTED,
                            severity=Severity.HIGH,
                            evidence_grade=EvidenceGrade.A,
                            title=f"달력상 존재하지 않는 날짜 기재: {block_year}년 2월 29일 ({matched_str})",
                            detail=(
                                f"{block_year}년은 평년으로 2월 28일까지 존재하므로 2월 29일은 달력에 존재하지 않는다."
                            ),
                            confidence=1.0,
                            confidence_features=features,
                            document_id=doc.document_id,
                            block_id=block.block_id,
                            page=block.page,
                            engine=ENGINE_NAME,
                            tags=["TIMELINE", "DATE-INVALID", "CALENDAR"],
                            evidence=[
                                Evidence.create(
                                    description="존재하지 않는 평년 2월 29일 표기",
                                    grade=EvidenceGrade.A,
                                    document_id=doc.document_id,
                                    block_id=block.block_id,
                                    page=block.page,
                                    excerpt=matched_str,
                                    supports=True,
                                )
                            ],
                        )
                    )

        # 3. 경과 일수 계산 검증 (DAYS)
        # 예: "해고일로부터 76일이 지난 2026. 6. 25." -> 2026.3.31~6.25는 86일
        for m in DAYS_ELAPSED_RE.finditer(text):
            stated_days = int(m.group("days"))
            to_y = int(m.group("to_y"))
            to_m = int(m.group("to_m"))
            to_d = int(m.group("to_d"))
            to_date = _parse_valid_date(to_y, to_m, to_d)

            from_date = None
            if m.group("from_y"):
                from_date = _parse_valid_date(int(m.group("from_y")), int(m.group("from_m")), int(m.group("from_d")))
            elif context_incident_date:
                from_date = context_incident_date

            if from_date and to_date:
                actual_days = (to_date - from_date).days
                if actual_days > 0 and actual_days != stated_days:
                    matched_str = m.group(0)
                    features = {
                        "deterministic_rule": True,
                        "from_date": str(from_date),
                        "to_date": str(to_date),
                        "stated_days": stated_days,
                        "actual_days": actual_days,
                        "difference": actual_days - stated_days,
                        "rule_id": "claim_engine.date_verifier:DAYS_ELAPSED_MISMATCH",
                    }
                    findings.append(
                        Finding.create(
                            type=FindingType.TIMELINE_CONTRADICTION,
                            status=VerificationStatus.CONTRADICTED,
                            severity=Severity.MEDIUM,
                            evidence_grade=EvidenceGrade.A,
                            title=f"경과 일수 계산 오류: 기재 {stated_days}일 → 실제 {actual_days}일",
                            detail=(
                                f"{from_date}부터 {to_date}까지의 실제 경과 일수는 {actual_days}일이나, "
                                f"본문에는 {stated_days}일로 기재되어 차이({abs(actual_days - stated_days)}일)가 발생한다."
                            ),
                            confidence=1.0,
                            confidence_features=features,
                            document_id=doc.document_id,
                            block_id=block.block_id,
                            page=block.page,
                            engine=ENGINE_NAME,
                            tags=["TIMELINE", "DAYS", "CALCULATION"],
                            evidence=[
                                Evidence.create(
                                    description="일수 경과 계산 불일치",
                                    grade=EvidenceGrade.A,
                                    document_id=doc.document_id,
                                    block_id=block.block_id,
                                    page=block.page,
                                    excerpt=matched_str,
                                    supports=True,
                                )
                            ],
                        )
                    )

    # 4. 문서/통지 발송일시와 본문 과거 의결/사유일 선후 역전 검증 (DATE-INVERSION / TEMPORAL)
    # 예: 발송일시 2026. 3. 18.인데 본문에서 "2026. 3. 20. 개최된 징계위원회의 의결에 따라" 통지하는 모순
    SEND_HEADER_RE = re.compile(
        r"(?:발송일시|발신일시|통지일시|작성일시|발송일|통지일|작성일)\s*[:\s]?\s*(?P<year>\d{4})[.\s년/-]+(?P<month>\d{1,2})[.\s월/-]+(?P<day>\d{1,2})"
    )
    PAST_EVENT_RE = re.compile(
        r"(?P<year>\d{4})[.\s년/-]+(?P<month>\d{1,2})[.\s월/-]+(?P<day>\d{1,2})[일\s.]*(?:개최된|열린|이루어진|의결에\s*따라|결의에\s*따라|처분에\s*따라|결정에\s*따라|실시된|자인한)"
    )

    for page in doc.pages:
        blocks = [b for b in page.blocks if b.visible and b.text.strip()]
        # 단일 블록 또는 인접 블록 결합 검사
        for i in range(len(blocks)):
            # 윈도우 텍스트 (현재 블록 + 다음 블록 최대 2개)
            window_blocks = blocks[i:min(i + 3, len(blocks))]
            window_text = " ".join(b.text for b in window_blocks)

            m_send = SEND_HEADER_RE.search(window_text)
            if m_send:
                sy, sm, sd = int(m_send.group("year")), int(m_send.group("month")), int(m_send.group("day"))
                send_date = _parse_valid_date(sy, sm, sd)

                if send_date:
                    for m_evt in PAST_EVENT_RE.finditer(window_text):
                        ey, em, ed = int(m_evt.group("year")), int(m_evt.group("month")), int(m_evt.group("day"))
                        evt_date = _parse_valid_date(ey, em, ed)

                        if evt_date and evt_date > send_date:
                            matched_send = m_send.group(0)
                            matched_evt = m_evt.group(0)
                            features = {
                                "deterministic_rule": True,
                                "send_date": str(send_date),
                                "event_date": str(evt_date),
                                "rule_id": "claim_engine.date_verifier:DATE_INVERSION_EVENT_AFTER_SEND",
                            }
                            # 중복 방지
                            if not any(f.title.startswith("발송/통지일 선후 역전") and f.page == window_blocks[0].page for f in findings):
                                findings.append(
                                    Finding.create(
                                        type=FindingType.TIMELINE_CONTRADICTION,
                                        status=VerificationStatus.CONTRADICTED,
                                        severity=Severity.HIGH,
                                        evidence_grade=EvidenceGrade.A,
                                        title=f"발송/통지일 선후 역전: 발송일({send_date})보다 미래의 사유·의결({evt_date})을 과거 사실로 인용",
                                        detail=(
                                            f"발송/통지일시({send_date}) 시점에 아직 발생하지 않은 미래 일자({evt_date})를 "
                                            f"'{matched_evt}'와 같이 과거 완료된 사유로 인용하여 인과적 선후 관계가 모순된다."
                                        ),
                                        confidence=1.0,
                                        confidence_features=features,
                                        document_id=doc.document_id,
                                        block_id=window_blocks[0].block_id,
                                        page=window_blocks[0].page,
                                        engine=ENGINE_NAME,
                                        tags=["TIMELINE", "DATE-INVERSION", "TEMPORAL"],
                                        evidence=[
                                            Evidence.create(
                                                description="발송일시 및 미래 의결 인용 선후 역전 구간",
                                                grade=EvidenceGrade.A,
                                                document_id=doc.document_id,
                                                block_id=window_blocks[0].block_id,
                                                page=window_blocks[0].page,
                                                excerpt=f"{matched_send} <-> {matched_evt}",
                                                supports=True,
                                            )
                                        ],
                                    )
                                )

    return findings
