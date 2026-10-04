"""업로드 개인정보 안내 및 보장 범위 설정 상수 (제1.1절).

사용자 결정(2026-10-04, handoff README), TK-56 3절, TK-57에 근거한다.
시스템이 자동 마스킹을 보장하는 것은 연락처·주민등록번호뿐이며,
성명·주소 등 그 밖의 개인정보는 사용자가 업로드 전에 직접 가려야 한다.
안내 문구 변경 시 PRIVACY_NOTICE_VERSION을 상향한다.
"""
from __future__ import annotations

from typing import Final, List

# 안내문 판(버전) 번호: 문구를 수정할 때마다 상향 조정한다.
PRIVACY_NOTICE_VERSION: Final[str] = "1.0"

# 업로드 화면 상시 안내문 (사용자 검토 대상 3대 항목)
NOTICE_BULLETS: Final[List[str]] = [
    "자동으로 가리는 개인정보는 연락처와 주민등록번호뿐입니다.",
    "성명·주소 등 그 밖의 개인정보는 업로드 전에 직접 가려 주세요.",
    "성명 등 자동 가림은 보조 기능이며 모두 가려진다고 보장하지 않습니다.",
]

# 확인 체크박스 라벨
ACK_LABEL: Final[str] = "연락처·주민등록번호 외의 개인정보를 직접 처리했습니다"

# 보고서 머리 표시 문구 (검증 보고서 화면 및 내보내기 상단)
REPORT_HEADER_NOTICE: Final[str] = "연락처·주민등록번호 자동 가림 보장, 그 밖의 개인정보는 사용자 처리"

# 서버 거절 메시지 (422 Unprocessable Entity)
PRIVACY_ACK_ERROR_MESSAGE: Final[str] = "연락처·주민등록번호 외의 개인정보를 직접 처리했음을 확인해야 업로드할 수 있습니다."
