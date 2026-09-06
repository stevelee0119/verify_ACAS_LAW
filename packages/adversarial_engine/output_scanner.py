"""제7.8장 Output 검사.

LLM 출력에서 갑작스러운 Task 변경, System Prompt 노출, 증거와 무관한 Tool 요청,
비정상 외부 URL, Secret 노출이 탐지되면 MODEL_OUTPUT_QUARANTINED로 처리하고
최종 Finding에 사용하지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

from .tool_firewall import ALLOWED_HOSTS, URL_RE

SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9]{16,}|sk-ant-[A-Za-z0-9_\-]{16,}|AIza[0-9A-Za-z_\-]{20,}|"
    r"ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
SYSTEM_PROMPT_LEAK_RE = re.compile(
    r"(system\s*prompt\s*[:：]|나의\s*시스템\s*지침(은|는)|내\s*지침(은|는)\s*다음|"
    r"you\s+are\s+a\s+legal\s+document\s+verification)",
    re.IGNORECASE,
)
TOOL_REQUEST_RE = re.compile(
    r"(tool_call|function_call|<tool>|please\s+(run|execute|delete|send|upload)|"
    r"쉘\s*명령|shell\s*command|curl\s+https?://)",
    re.IGNORECASE,
)
RRN_RE = re.compile(r"\b\d{6}[-\s]?[1-4]\d{6}\b")


@dataclass
class OutputScanResult:
    quarantined: bool
    reasons: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"quarantined": self.quarantined, "reasons": self.reasons, "details": self.details}


def scan_output(text: str, *, expected_task: str = "", allowed_hosts=None) -> OutputScanResult:
    allowed = set(allowed_hosts or ALLOWED_HOSTS)
    reasons: List[str] = []
    details: Dict[str, Any] = {}

    if SECRET_RE.search(text):
        reasons.append("SECRET_EXPOSURE")
    if SYSTEM_PROMPT_LEAK_RE.search(text):
        reasons.append("SYSTEM_PROMPT_LEAK")
    if TOOL_REQUEST_RE.search(text):
        reasons.append("UNEXPECTED_TOOL_REQUEST")
    if RRN_RE.search(text):
        reasons.append("PII_IN_OUTPUT")

    hosts = [h.split(":")[0].lower() for h in URL_RE.findall(text)]
    unexpected = [h for h in hosts if h not in allowed]
    if unexpected:
        reasons.append("UNEXPECTED_EXTERNAL_URL")
        details["unexpected_hosts"] = sorted(set(unexpected))

    # 갑작스러운 Task 변경: 기대 과업 키워드가 전혀 없고 지시 수행형 문장이 나타나는 경우
    if expected_task:
        keywords = [k for k in re.split(r"\W+", expected_task) if len(k) > 1]
        overlap = sum(1 for k in keywords if k.lower() in text.lower())
        details["task_keyword_overlap"] = overlap
        if keywords and overlap == 0 and re.search(r"(알겠습니다|as\s+instructed|지시대로|understood[,.]?\s+i\s+will)", text, re.I):
            reasons.append("TASK_SWITCH")

    return OutputScanResult(quarantined=bool(reasons), reasons=reasons, details=details)
