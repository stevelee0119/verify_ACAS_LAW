"""제7.4장 Semantic 분류용 패턴.

법률문서에는 정상적인 명령형·인용문이 많으므로 패턴 일치만으로 판정하지 않고
classifier가 문맥 feature와 결합해 최종 등급을 정한다.
"""
from __future__ import annotations

import re
from typing import Dict, List, Pattern, Tuple

from packages.common.enums import FindingType, InjectionIntent

# (정규식, intent, 가중치, 설명)
PatternSpec = Tuple[Pattern[str], InjectionIntent, float, str]


def _c(pattern: str) -> Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


INSTRUCTION_PATTERNS: List[PatternSpec] = [
    # --- Instruction Override -------------------------------------------
    (_c(r"(이전|앞의|위의|기존)\s*(의\s*)?(모든\s*)?(지시|명령|지침|규칙|프롬프트)[을를]?\s*(무시|무효|취소|잊)"),
     InjectionIntent.INSTRUCTION_OVERRIDE, 1.0, "이전 지시 무시 요구(한국어)"),
    (_c(r"ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier|preceding)\s+(instructions?|prompts?|rules?|directions?)"),
     InjectionIntent.INSTRUCTION_OVERRIDE, 1.0, "이전 지시 무시 요구(영어)"),
    (_c(r"disregard\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier|system)"),
     InjectionIntent.INSTRUCTION_OVERRIDE, 1.0, "disregard previous"),
    (_c(r"forget\s+(everything|all\s+previous|your\s+instructions)"),
     InjectionIntent.INSTRUCTION_OVERRIDE, 0.9, "forget instructions"),
    (_c(r"(새로운|다음의)\s*(지시|지침|규칙)[을를]?\s*(따르|우선|적용)"),
     InjectionIntent.INSTRUCTION_OVERRIDE, 0.8, "새 지시 우선 적용 요구"),
    (_c(r"new\s+instructions?\s*[:：]"), InjectionIntent.INSTRUCTION_OVERRIDE, 0.7, "new instructions 선언"),
    (_c(r"override\s+(the\s+)?(system|previous|prior)\s+(prompt|instruction|message)"),
     InjectionIntent.INSTRUCTION_OVERRIDE, 1.0, "system prompt override"),

    # --- Role Override ---------------------------------------------------
    (_c(r"(너는|당신은|귀하는)\s*(이제|지금부터)\s*[^.\n]{0,30}(이다|입니다|역할|assistant|AI)"),
     InjectionIntent.ROLE_OVERRIDE, 0.8, "역할 재정의 시도(한국어)"),
    (_c(r"you\s+are\s+(now\s+)?(a|an|the)\s+[a-z\s]{2,30}(assistant|model|agent|system)"),
     InjectionIntent.ROLE_OVERRIDE, 0.8, "역할 재정의 시도(영어)"),
    (_c(r"(system|developer)\s*(prompt|message|instruction)\s*[:：]"),
     InjectionIntent.ROLE_OVERRIDE, 0.9, "system/developer 메시지 위장"),
    (_c(r"<\s*/?\s*(system|assistant|developer|instructions?)\s*>"),
     InjectionIntent.ROLE_OVERRIDE, 0.9, "역할 태그 위장"),
    (_c(r"\[\s*(system|assistant|developer)\s*\]"), InjectionIntent.ROLE_OVERRIDE, 0.7, "역할 브래킷 위장"),
    (_c(r"act\s+as\s+(a|an|the)\s+[a-z\s]{2,30}"), InjectionIntent.ROLE_OVERRIDE, 0.5, "act as 요구"),
    (_c(r"(개발자|관리자|시스템)\s*(모드|권한)[으로]?\s*(전환|변경|진입)"),
     InjectionIntent.ROLE_OVERRIDE, 0.9, "권한 모드 전환 요구"),

    # --- Output Manipulation --------------------------------------------
    (_c(r"(이상\s*없음|문제\s*없음|정상|적법|진정)(으로|이라고|하다고)\s*(보고|기재|판정|표시|결론|평가)"),
     InjectionIntent.OUTPUT_MANIPULATION, 1.0, "특정 결론 강제(한국어)"),
    (_c(r"(오류|문제|의심|위험)\s*(가|이|은|는)?\s*(없다고|없음으로)\s*(보고|기재|결론|판단)"),
     InjectionIntent.OUTPUT_MANIPULATION, 1.0, "무오류 결론 강제"),
    (_c(r"(report|conclude|state|say)\s+(that\s+)?(there\s+are\s+)?no\s+(issues?|errors?|problems?|findings?)"),
     InjectionIntent.OUTPUT_MANIPULATION, 1.0, "무오류 결론 강제(영어)"),
    (_c(r"(mark|classify|rate)\s+(this|the)\s+document\s+as\s+(authentic|valid|genuine|clean|safe)"),
     InjectionIntent.OUTPUT_MANIPULATION, 1.0, "진정성 강제 표시"),
    (_c(r"(신뢰도|점수|score)\s*[를을]?\s*(100|최고|최상)[%점]?\s*(로|으로)?\s*(부여|기재|설정)"),
     InjectionIntent.OUTPUT_MANIPULATION, 0.9, "점수 강제"),
    (_c(r"(보고서|결과)\s*에\s*[^.\n]{0,20}\s*(포함하지|기재하지|표시하지)\s*(말|마)"),
     InjectionIntent.OUTPUT_MANIPULATION, 1.0, "보고서 기재 배제 요구"),
    (_c(r"do\s+not\s+(include|mention|report|list)\s+[^.\n]{0,40}\s+in\s+(the\s+)?(report|output|summary)"),
     InjectionIntent.OUTPUT_MANIPULATION, 1.0, "보고서 기재 배제 요구(영어)"),

    # --- Verification Suppression ---------------------------------------
    (_c(r"(판례|법령|인용|날짜|사건번호|출처)[를을]?\s*(다시\s*)?(확인|검증|조회|검색)하지\s*(말|마|않)"),
     InjectionIntent.VERIFICATION_SUPPRESSION, 1.0, "검증 금지 요구(한국어)"),
    (_c(r"(검증|검토|분석)\s*(에서\s*)?(제외|생략|건너뛰|스킵)"),
     InjectionIntent.VERIFICATION_SUPPRESSION, 0.8, "검증 제외 요구"),
    (_c(r"do\s+not\s+(verify|check|validate|search|look\s+up|fact.?check)"),
     InjectionIntent.VERIFICATION_SUPPRESSION, 1.0, "검증 금지 요구(영어)"),
    (_c(r"(skip|bypass|omit)\s+(the\s+)?(verification|validation|citation\s+check|fact.?check)"),
     InjectionIntent.VERIFICATION_SUPPRESSION, 1.0, "검증 우회 요구"),
    (_c(r"이\s*(문서|서면|부분)[은는]?\s*(검증|검토)\s*(대상|절차)\s*에서\s*제외"),
     InjectionIntent.VERIFICATION_SUPPRESSION, 1.0, "문서 검증 대상 제외 선언"),
    (_c(r"(this\s+)?(document|section)\s+(is\s+)?(exempt|excluded)\s+from\s+(verification|review|analysis)"),
     InjectionIntent.VERIFICATION_SUPPRESSION, 1.0, "검증 대상 제외 선언(영어)"),

    # --- System / Secret Extraction --------------------------------------
    (_c(r"(시스템|System)\s*(프롬프트|prompt|지침)[을를]?\s*(출력|공개|보여|알려|말해)"),
     InjectionIntent.SYSTEM_SECRET_EXTRACTION, 1.0, "system prompt 노출 요구"),
    (_c(r"(reveal|print|show|output|repeat)\s+(your|the)\s+(system\s+)?(prompt|instructions?|rules?|configuration)"),
     InjectionIntent.SYSTEM_SECRET_EXTRACTION, 1.0, "system prompt 노출 요구(영어)"),
    (_c(r"(api\s*key|secret|token|credential|비밀번호|인증키)[를을]?\s*(출력|전송|공개|알려)"),
     InjectionIntent.SYSTEM_SECRET_EXTRACTION, 1.0, "비밀정보 노출 요구"),

    # --- Tool Manipulation / Exfiltration ---------------------------------
    (_c(r"(다음|아래)\s*(주소|url|링크|서버)로\s*(전송|전달|업로드|보내)"),
     InjectionIntent.DATA_EXFILTRATION, 1.0, "외부 전송 요구(한국어)"),
    (_c(r"(send|post|upload|exfiltrate|forward)\s+[^.\n]{0,40}\s+to\s+(https?://|[a-z0-9.-]+\.[a-z]{2,})"),
     InjectionIntent.DATA_EXFILTRATION, 1.0, "외부 전송 요구(영어)"),
    (_c(r"(파일|기록|로그|증거)[를을]?\s*(삭제|제거|폐기)(하라|해라|할\s*것)"),
     InjectionIntent.TOOL_MANIPULATION, 1.0, "삭제 요구"),
    (_c(r"(delete|remove|erase|wipe)\s+(the\s+)?(files?|logs?|records?|evidence|audit)"),
     InjectionIntent.TOOL_MANIPULATION, 1.0, "삭제 요구(영어)"),
    (_c(r"(execute|run)\s+(the\s+)?(following\s+)?(command|shell|script|code)"),
     InjectionIntent.TOOL_MANIPULATION, 1.0, "명령 실행 요구"),
    (_c(r"(권한|permission)[을를]?\s*(변경|상향|부여)"), InjectionIntent.TOOL_MANIPULATION, 0.8, "권한 변경 요구"),

    # --- Persistent Instruction -------------------------------------------
    (_c(r"(이후|앞으로|향후)\s*(의\s*)?(모든|전체)\s*(작업|분석|응답|검증)에\s*(도\s*)?(적용|유지|반영)"),
     InjectionIntent.PERSISTENT_INSTRUCTION, 0.9, "지속 적용 요구(한국어)"),
    (_c(r"(for\s+all\s+(future|subsequent)|from\s+now\s+on|always\s+remember)"),
     InjectionIntent.PERSISTENT_INSTRUCTION, 0.8, "지속 적용 요구(영어)"),
    (_c(r"(이\s*지시[는은])\s*[^.\n]{0,20}(유지|지속|계속)"), InjectionIntent.PERSISTENT_INSTRUCTION, 0.8, "지시 지속 선언"),
]

# LLM·검증 시스템을 명시적으로 호명하는 표현 (메타 지시어 강한 신호)
AI_ADDRESSING_RE = _c(
    r"(AI|인공지능|LLM|언어\s*모델|chatgpt|gpt|claude|gemini|copilot|검증\s*(시스템|엔진|도구)|"
    r"assistant|모델|reviewer|심사자|검토\s*시스템|automated\s+(system|reviewer|checker))"
)

# 정상 법률문서에서 흔한 표현 (오탐 억제)
BENIGN_CONTEXT_RE = _c(
    r"(주문|판시사항|판결요지|청구취지|청구원인|이유|별지|다음과\s*같이\s*(판결|결정|명령)|"
    r"피고는\s*원고에게|원고의\s*청구를|소송비용은|가집행할\s*수\s*있다|"
    r"제\s*\d+\s*조|법\s*제|형법|민법|상법|형사소송법|민사소송법)"
)

QUOTE_WRAPPERS = [("“", "”"), ("\"", "\""), ("‘", "’"), ("'", "'"), ("「", "」"), ("『", "』"), ("<", ">")]

INTENT_TO_FINDING = {
    InjectionIntent.INSTRUCTION_OVERRIDE: FindingType.SYSTEM_OVERRIDE_ATTEMPT,
    InjectionIntent.ROLE_OVERRIDE: FindingType.ROLE_OVERRIDE_ATTEMPT,
    InjectionIntent.OUTPUT_MANIPULATION: FindingType.OUTPUT_MANIPULATION_ATTEMPT,
    InjectionIntent.VERIFICATION_SUPPRESSION: FindingType.VERIFICATION_SUPPRESSION,
    InjectionIntent.SYSTEM_SECRET_EXTRACTION: FindingType.SYSTEM_OVERRIDE_ATTEMPT,
    InjectionIntent.TOOL_MANIPULATION: FindingType.TOOL_MANIPULATION_ATTEMPT,
    InjectionIntent.PERSISTENT_INSTRUCTION: FindingType.META_INSTRUCTION,
    InjectionIntent.DATA_EXFILTRATION: FindingType.DATA_EXFILTRATION_INSTRUCTION,
}
