"""정답지(Ground Truth) 배제 및 입력 거부 모듈.

검증 파이프라인과 CLI에서 정답지(00_GroundTruth.pdf 등)를 입력 대상에서 원천 배제하고,
파일명이나 본문 내용에 'ground truth'·'정답지'가 포함된 경우 입력을 명시적으로 거부한다.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

# 파일명 정규화용 패턴 (특수기호 및 공백 제거)
_CLEAN_FILENAME_RE = re.compile(r"[\s_\-]+")

# 내용 내 정답지 표기 패턴 (문서 서두 또는 주요 헤더에 등장하는 ground truth / 정답지 / 정답명세서)
_GROUND_TRUTH_CONTENT_RE = re.compile(
    r"(?i)\bground\s*truth\b|정\s*답\s*(?:지|명세|표)"
)


def is_ground_truth_filename(path_or_name: str | Path) -> bool:
    """파일명에 'ground truth', '정답지', '정답명세' 등이 포함되어 있는지 확인한다."""
    name = Path(path_or_name).name.lower()
    norm = _CLEAN_FILENAME_RE.sub("", name)
    if "groundtruth" in norm or "정답지" in name or "정답명세" in name:
        return True
    return False


def is_ground_truth_content(text: str) -> bool:
    """문서 내용에 'ground truth' 또는 '정답지' 표제가 포함되어 있는지 확인한다.
    
    문서 첫 부분(2000자 이내) 또는 헤더/제목 영역에서 정답지 표기가 발견되면 True를 반환한다.
    """
    if not text:
        return False
    head = text[:3000]
    return bool(_GROUND_TRUTH_CONTENT_RE.search(head))


def check_and_reject_ground_truth(filename: str, content_text: Optional[str] = None) -> None:
    """정답지 파일명 또는 내용이 감지되면 ValueError를 발생시켜 입력을 거부한다."""
    if is_ground_truth_filename(filename):
        raise ValueError(f"정답지(Ground Truth) 파일은 검증 입력으로 사용할 수 없습니다: {filename}")
    if content_text and is_ground_truth_content(content_text):
        raise ValueError(f"정답지(Ground Truth) 내용이 포함된 문서는 검증 입력으로 사용할 수 없습니다: {filename}")
