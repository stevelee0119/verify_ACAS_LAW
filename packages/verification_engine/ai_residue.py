"""AI 응답 잔재 신호(v2 Phase 8). 규칙 기반이며 모두 '참고용, 확정 불가'다.

생성형 AI의 답변을 서면에 옮기면 대화형 서두("물론입니다! … 작성해 드리겠습니다"), 마크다운 문법(###, **),
지식 기준일 언급, 면책 안내문("법률 자문을 대체하지 않습니다 … 말씀해 주세요!") 같은 잔재가 남는다. 이것들은
서면 작성 관행에 없는 표지이므로 '객관적 흔적'으로 센다. 상투적 연결어·영문 병기는 사람도 쓰므로 문체 신호로만
표시한다. 어느 것도 사람 작성/AI 작성을 단정하는 근거가 아니다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

# (범주, 설명, 객관적 흔적 여부, 패턴)
RESIDUE_RULES = [
    ("CHATBOT_PREFACE", "대화형 응답 서두", True, re.compile(
        r"(물론입니다|네[,!]?\s*알겠습니다|알겠습니다|좋습니다)\s*[!.]?[^\n]{0,80}?"
        r"(작성해\s*(?:드리겠|드릴게|보겠)습니다|정리해\s*드리겠습니다|도와\s*드리겠습니다|작성하겠습니다)")),
    ("DISCLAIMER", "AI 면책·안내문", True, re.compile(
        r"(법률\s*자문을\s*대체하지|법률\s*자문이\s*아닙니다|법률적\s*조언이\s*아니며|전문\s*변호사와\s*상담하시기|"
        r"(?:말씀|알려)\s*주세요\s*!|도움이\s*되었기를\s*바랍니다|추가적인\s*질문이\s*있으시면|언제든\s*문의해\s*주십시오)")),
    ("KNOWLEDGE_CUTOFF", "모델 지식 기준일 언급", True, re.compile(
        r"((?:제|저의)\s*(?:지식|학습\s*데이터)\s*(?:기준일?|기준으로|업데이트)|학습\s*데이터\s*기준|knowledge\s+cutoff|"
        r"AI\s*(?:어시스턴트|모델|언어\s*모델)로서|인공지능으로서)", re.IGNORECASE)),
    ("MARKDOWN", "마크다운 문법 잔재", True, re.compile(r"(?m)(^\s*#{1,6}\s+\S[^\n]{0,40}|\*\*[^*\n]{1,40}\*\*)")),
    # 기존 판정 기준(v1)에서 챗봇 답변 표지로 보던 요약·나열 도입구. 그대로 객관적 흔적으로 센다.
    ("CHATBOT_SUMMARY", "챗봇 답변식 요약·나열 도입구", True, re.compile(
        r"(요약하자면|종합하자면|결론적으로\s*말씀드리면|다음과\s*같은\s*(?:점|측면|이유|법리)(?:들)?이\s*있습니다)")),
    ("CLICHE", "AI 답변 상투 표현", False, re.compile(
        r"(결론적으로|종합적으로\s*볼\s*때|라고\s*할\s*수\s*있습니다|중요한\s*점은|핵심은|"
        r"단계적으로\s*살펴보겠습니다|살펴보겠습니다)")),
    ("ENGLISH_GLOSS", "한국어 법률 용어의 영문 병기", False, re.compile(
        r"[(（'‘\"“]\s*([a-z]+(?:\s+[a-z]+){1,4})\s*[)）'’\"”]")),
]
MIN_CLICHE_KINDS = 3  # 상투 표현은 서로 다른 표현이 3종 이상일 때만 신호로 본다


@dataclass
class Residue:
    category: str
    label: str
    objective: bool
    matches: List[str] = field(default_factory=list)


def scan_residue(text: str) -> List[Residue]:
    out: List[Residue] = []
    for category, label, objective, pattern in RESIDUE_RULES:
        found = []
        for m in pattern.finditer(text or ""):
            fragment = " ".join(m.group(0).split())
            if fragment not in found:
                found.append(fragment)
        if not found:
            continue
        if category == "CLICHE" and len({re.sub(r"\s+", "", f) for f in found}) < MIN_CLICHE_KINDS:
            continue
        out.append(Residue(category, label, objective, found[:8]))
    return out
