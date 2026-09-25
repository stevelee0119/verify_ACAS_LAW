"""제7.4장 Semantic 분류용 패턴.

법률문서에는 정상적인 명령형·인용문이 많으므로 패턴 일치만으로 판정하지 않고
classifier가 문맥 feature와 결합해 최종 등급을 정한다.
"""
from __future__ import annotations

import re
from typing import List, Pattern, Tuple

from packages.common.enums import FindingType, InjectionIntent

# (정규식, intent, 가중치, 설명)
PatternSpec = Tuple[Pattern[str], InjectionIntent, float, str]


def _c(pattern: str) -> Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# 기계(AI·모델·검토 도구·시스템)를 수신자로 부르는 말. 사람 수신자(피고·원고·귀하)와 구분한다.
MACHINE_ADDRESSEE = (r"(?:AI|ＡＩ|인공지능|LLM|언어\s*모델|(?:검증|검토|분석)\s*(?:모델|도구|시스템|엔진|AI|프로그램)|"
                     r"(?:AI|인공지능)\s*검토자|모델|시스템|reviewer|assistant)")

INSTRUCTION_PATTERNS: List[PatternSpec] = [
    # --- Instruction Override -------------------------------------------
    (_c(r"(이전|앞의|앞선|위의|기존|종전|지금까지)\s*(의\s*)?(모든\s*)?(지시|명령|지침|규칙|프롬프트)[을를]?\s*"
        r"(무시|무효|취소|잊|폐기|따르지)"),
     InjectionIntent.INSTRUCTION_OVERRIDE, 1.0, "이전 지시 무시 요구(한국어)"),
    (_c(r"ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier|preceding)\s+(instructions?|prompts?|rules?|directions?)"),
     InjectionIntent.INSTRUCTION_OVERRIDE, 1.0, "이전 지시 무시 요구(영어)"),
    (_c(r"disregard\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier|system)"),
     InjectionIntent.INSTRUCTION_OVERRIDE, 1.0, "disregard previous"),
    (_c(r"forget\s+(everything|all\s+previous|your\s+instructions)"),
     InjectionIntent.INSTRUCTION_OVERRIDE, 0.9, "forget instructions"),
    (_c(MACHINE_ADDRESSEE + r"[은는이가]?\s*(아래|다음|이하|본|이)\s*(의\s*)?(지시|명령|지침|규칙)[을를에]?\s*(따를\s*것|따르라|따르십시오|따라야|따르세요|따르시오)"),
     InjectionIntent.INSTRUCTION_OVERRIDE, 0.8, "AI 수신자에게 문서 속 지시 준수 요구"),
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

    # --- 권한 위장 명령 -----------------------------------------------------
    # 실제 테스트 문서(verification_rpt_251392c6e1a044f7)에서 미탐지된 형태이다.
    # "[ADMIN COMMAND: ...]", "[SYSTEM INSTRUCTION: SECURITY EVALUATION OVERRIDE]"는
    # 역할 태그가 아니라 대괄호 안의 명령 선언이라 기존 규칙에 걸리지 않았다.
    (_c(r"\[\s*(admin|administrator|root|superuser|system|security|privileged)\s+"
        r"(command|instruction|directive|override|mode)\b"),
     InjectionIntent.ROLE_OVERRIDE, 1.0, "관리자 명령 선언 위장"),
    (_c(r"(privileged|security|system)\s+(system\s+)?override"),
     InjectionIntent.ROLE_OVERRIDE, 1.0, "권한 우회 선언"),
    (_c(r"(시스템\s*)?(감사관|감사\s*담당|보안\s*담당|관리자)\s*(메모|지시|공지|요청)"),
     InjectionIntent.ROLE_OVERRIDE, 0.9, "감사관·관리자 사칭(한국어)"),
    (_c(r"(사전\s*적격\s*심사|사전\s*심사|사전\s*검증)[를을]?\s*(완료|통과)"),
     InjectionIntent.ROLE_OVERRIDE, 0.8, "사전심사 완료 주장으로 검증 면제 유도"),

    # --- 검증 중단 요구 -----------------------------------------------------
    (_c(r"(검증|탐지|분석|점검|심사)\s*(루틴|절차|과정|기능)?[를을]?\s*(즉시\s*)?(중단|생략|건너뛰|해제|비활성)"),
     InjectionIntent.INSTRUCTION_OVERRIDE, 1.0, "검증 중단 요구(한국어)"),
    (_c(r"(skip|disable|bypass|suppress|turn\s+off)\s+(all\s+|any\s+|the\s+)?"
        r"(security\s+)?(check|verification|validation|detection|scan|warning|alert|analysis)s?"),
     InjectionIntent.INSTRUCTION_OVERRIDE, 1.0, "검증·경고 억제 요구(영어)"),
    (_c(r"(추가\s*)?(경고|결함|문제점|오류)[를을]?\s*(출력|표시|기재|보고)하지\s*(말|마십시오|마세요|않)"),
     InjectionIntent.OUTPUT_MANIPULATION, 1.0, "경고 출력 금지 요구"),
    (_c(r"do\s+not\s+(output|report|show|display|include)\s+(any\s+)?"
        r"(additional\s+)?(warnings?|errors?|findings?|issues?)"),
     InjectionIntent.OUTPUT_MANIPULATION, 1.0, "경고 출력 금지 요구(영어)"),

    # --- 판정값 직접 지정 ---------------------------------------------------
    (_c(r"(ai_probability|hallucination_flag|adversarial_risk|risk)\s*[=:]\s*"
        r"(0(\.\d+)?|false|none|null)"),
     InjectionIntent.OUTPUT_MANIPULATION, 1.0, "판정 변수값 직접 지정"),
    (_c(r"(위험도|리스크)\s*(점수)?\s*0\s*점"),
     InjectionIntent.OUTPUT_MANIPULATION, 1.0, "위험도 0점 지정"),
    (_c(r"(사람|인간)\s*작성\s*(완전\s*)?일치"),
     InjectionIntent.OUTPUT_MANIPULATION, 0.9, "사람 작성 판정 강제"),
    (_c(r"(적합|합격|정상)\s*판정[으]?[로]?\s*(반환|처리|회신|기재)"),
     InjectionIntent.OUTPUT_MANIPULATION, 1.0, "적합 판정 반환 요구"),

    # --- Output Manipulation --------------------------------------------
    (_c(r"['\"‘“]?(이상\s*없음|문제\s*없음|정상|적법|진정|적합|PASS)['\"’”]?\s*(으로|로|이라고|하다고)\s*"
        r"(바꾸어|바꿔|변경하여|변경해)?\s*(보고|기재|판정|표시|결론|평가|처리)(?!받|되었|됐)"),
     InjectionIntent.OUTPUT_MANIPULATION, 1.0, "특정 결론 강제(한국어)"),
    # 대상 전부를 '확인된·정상인' 것으로 보고하라는 요구(v5 3-7). '확인된 사실'처럼 명사를 꾸미는 말은 제외된다.
    (_c(r"(모든|전부|모두|각)\s*(인용|판례|조문|법령|항목|결과|사건번호|날짜)[을를은는이가]?\s*(모두|전부)?\s*"
        r"(확인된|검증된|정상인|실존하는|유효한|이상\s*없는|문제\s*없는)\s*것으로\s*(보고|기재|표시|처리|판정|분류|출력)"),
     InjectionIntent.OUTPUT_MANIPULATION, 1.0, "전부 확인된 것으로 보고 요구"),
    (_c(r"(확인|검증|검토)\s*(완료|됨|필)\s*(으로|로)\s*(표시|보고|처리|기재)"),
     InjectionIntent.OUTPUT_MANIPULATION, 0.9, "검증 완료 표시 요구"),
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
    (_c(r"(판례|법령|인용|날짜|사건번호|출처|실존|진위|존재)\s*(여부)?[를을]?\s*(다시|별도로|따로|추가로|직접)?\s*"
        r"(확인|검증|조회|검색)하지\s*(말|마|않)"),
     InjectionIntent.VERIFICATION_SUPPRESSION, 1.0, "검증 금지 요구(한국어)"),
    # AI·검토 도구를 수신자로 한 검증 금지(대상 명사와 무관). 사람에게 하는 요청과 구분하려고 수신자를 요구한다.
    (_c(r"(AI|인공지능|LLM|언어\s*모델|검증\s*(?:시스템|엔진|도구)|검토\s*(?:시스템|도구|AI|프로그램)|보조\s*도구)"
        r"[은는이가]?\s[^.\n]{0,80}?(확인|검증|조회|대조|검산|계산)[을를]?\s*(?:하지\s*(?:말|마)|생략|건너뛰)"),
     InjectionIntent.VERIFICATION_SUPPRESSION, 1.0, "AI 수신 검증 금지 요구"),
    (_c(r"(검증|검토|분석)\s*(대상|절차|범위)?\s*(에서\s*)?(제외|생략|건너뛰|스킵|뺄\s*것|빼)"),
     InjectionIntent.VERIFICATION_SUPPRESSION, 0.8, "검증 제외 요구"),
    (_c(r"do\s+not\s+(verify|check|validate|search|look\s+up|fact.?check)"),
     InjectionIntent.VERIFICATION_SUPPRESSION, 1.0, "검증 금지 요구(영어)"),
    (_c(r"(skip|bypass|omit)\s+(the\s+|all\s+)?(citation\s+|case\s+|source\s+|reference\s+)?"
        r"(verification|validation|check(ing)?|fact.?check|lookup)"),
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
    # --- 검증 우회·결론 강제·은폐(v2 R8: 실제 시험 문서에서 놓친 변형) ------------------
    (_c(r"(전부|모두|전체)[를을]?\s*(실존|존재|정확|진정)[하한는]*\s*(것)?\s*(으로|이라고|하다고|한다고)\s*"
        r"(판정|보고|기재|표시|처리|결론)"),
     InjectionIntent.OUTPUT_MANIPULATION, 1.0, "실존·정확 판정 강제"),
    (_c(r"(maintenance|debug|developer|admin|god|test)\s+mode"),
     InjectionIntent.ROLE_OVERRIDE, 0.8, "운영 모드 전환 선언(영어)"),
    (_c(r"(탐지|검증|판정|검토)\s*결과[를을]?\s*(모두|전부)?\s*['\"‘“]?(정상|적합|이상\s*없음|문제\s*없음|PASS)"),
     InjectionIntent.OUTPUT_MANIPULATION, 1.0, "검증 결과 변경 요구"),
    (_c(r"(이\s*)?(지시|문장|문구|내용)[의을를]?\s*(존재[를을]?\s*)?(언급|보고|공개|알리|표시)(하)?지\s*(말|마|않)"),
     InjectionIntent.OUTPUT_MANIPULATION, 0.9, "지시문 은폐 요구"),
    (_c(r"(결론|판단)[을를]?\s*(우선|먼저)\s*(제시|쓰|기재|작성|적)"),
     InjectionIntent.OUTPUT_MANIPULATION, 0.7, "결론 선제시 요구"),
    (_c(r"(report|return|output)\s+(zero|no|0)\s+(issues?|errors?|findings?|problems?)"),
     InjectionIntent.OUTPUT_MANIPULATION, 1.0, "무결함 보고 요구(영어)"),
    (_c(r"(citations?|references?)\s+(are\s+)?(already\s+)?(verified|valid)\s*[;,.]|citations?_verified\s*=\s*true"),
     InjectionIntent.OUTPUT_MANIPULATION, 0.8, "인용 검증 완료 주장(영어)"),
    (_c(r"(citations?|references?|cases?)\s+(were|are|have\s+been)\s+(already\s+)?(confirmed|verified|checked)"),
     InjectionIntent.VERIFICATION_SUPPRESSION, 0.8, "인용 확인 완료 주장(영어)"),
    (_c(r"(지시|지침|요청)[를을]?\s*(최우선|우선)\s*(으로|적으로)?\s*(따를|따르|적용|준수)"),
     InjectionIntent.INSTRUCTION_OVERRIDE, 0.9, "지시 최우선 적용 요구"),
    # --- 기계 수신자 + 검증·보고·결론 동사 + 명령형(v4 P7) ----------------------------------------
    # 사람에게 하는 요청(피고는 … 하라)과 구분하려고 AI·모델·검토 도구 같은 수신자를 요구한다. 특정 문장이 아니라
    # '수신자 → 검증·보고 대상 → 금지·생략·변경 명령'의 구조로 판단한다.
    (_c(MACHINE_ADDRESSEE + r"[은는이가]?\s[^.\n]{0,80}?(?:확인|검사|검증|검토|조회|점검|대조|검산|계산|분석)[을를]?\s*"
        r"(?:하지\s*(?:말|마)|(?:생략|무시|중단)(?:하라|해라|하십시오|하세요|할\s*것)|건너뛰(?:어라|라|십시오|세요))"),
     InjectionIntent.VERIFICATION_SUPPRESSION, 1.0, "기계 수신 검증 생략·금지 명령"),
    (_c(MACHINE_ADDRESSEE + r"[은는이가]?\s[^.\n]{0,80}?(?:보고|기재|표시|출력|언급)(?:하)?지\s*(?:말|마)"),
     InjectionIntent.OUTPUT_MANIPULATION, 1.0, "기계 수신 보고 금지 명령"),
    (_c(MACHINE_ADDRESSEE + r"[은는이가]?\s[^.\n]{0,80}?(?:오류|결함|문제|경고|위반|지시)[을를]?\s*무시(?:하라|해라|하십시오|할\s*것)"),
     InjectionIntent.VERIFICATION_SUPPRESSION, 1.0, "기계 수신 오류 무시 명령"),
    (_c(MACHINE_ADDRESSEE + r"[은는이가]?\s[^.\n]{0,80}?(?:결론|결과|판정|평가|등급)[을를]?\s*(?:바꿔|바꾸어|변경하|수정하|조정하)"
        r"(?:라|어라|여라|십시오|세요|\s*것)"),
     InjectionIntent.OUTPUT_MANIPULATION, 1.0, "기계 수신 결론 변경 명령"),
    (_c(MACHINE_ADDRESSEE + r"[은는이가]?\s[^.\n]{0,80}?(?:신뢰할\s*수\s*있다고|정확하다고|적법하다고|진정하다고|문제(?:가)?\s*없다고|"
        r"이상(?:이)?\s*없다고)\s*(?:보고|기재|결론|판정|평가)"),
     InjectionIntent.OUTPUT_MANIPULATION, 1.0, "기계 수신 결론 강제"),
    (_c(r"(?:보고서|결과|요약|검증\s*결과)\s*(?:에서|에)\s*[^.\n]{0,10}?(?:제외|빼|누락)(?:하라|해라|시켜라|하십시오|할\s*것)"),
     InjectionIntent.OUTPUT_MANIPULATION, 1.0, "보고서 제외 명령"),
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

# --- 지시문을 '언급'하는 문맥과 '명령'하는 문맥의 구분 ----------------------------
#
# 문서가 지시문·공격 기법을 주제로 설명하는 경우(목차·표제·점검 항목·사례 설명)에도
# 같은 낱말이 나온다. "인용 검증 생략 유도"는 검증을 생략하라는 명령이 아니라
# 그런 시도를 가리키는 명사구다. 명령형 어미가 없고 아래 문맥 중 하나에 놓이면
# 언급(mention)으로 본다. 숨김·인코딩·AI 호명이 함께 있으면 언급으로 보지 않는다.

# "테스트 포인트:", "점검 항목:", "사례 3:", "예시)" 같은 설명용 표제
DESCRIPTIVE_LABEL_RE = _c(
    r"(?:^|[\s(\[])(?:테스트|시험|점검|검사|탐지|분석|평가)\s*(?:포인트|항목|대상|내용|목적|예시|사례|범위)\s*[:：)]|"
    r"(?:^|[\s(\[])(?:사례|예시|유형|목적|설명|개요|주제|요지|체크리스트|시나리오)\s*\d*\s*[:：)]|"
    r"\b(?:test\s*(?:point|case|item)|example|scenario|checklist)\s*\d*\s*[:：)]"
)
# 지시형 낱말 바로 뒤에 오는 명사화 표현. "생략 유도", "무시 시도", "우회 여부"
NOMINAL_FOLLOWER_RE = _c(
    r"^\s*(?:를|을|의)?\s*(?:유도|시도|여부|탐지|사례|유형|기법|공격|문구|예시|항목|패턴|방지|차단|대응|위험|가능성|흔적|"
    r"attempts?|detection|examples?|patterns?|cases?|risk)"
)
# 명령·요청 어미. 이것이 지시형 낱말 가까이에 있으면 언급이 아니라 명령이다.
IMPERATIVE_RE = _c(
    r"(하라|해라|하시오|하십시오|하세요|할\s*것|말\s*것|마십시오|마세요|마라|바랍니다|주십시오|주세요|"
    r"해야\s*한다|하여야\s*한다|하도록|반환하|출력하라|처리하라|\bplease\b|\bmust\b|\bshall\b)"
)
# 문서 스스로 그런 지시를 따르지 않는다고 밝히는 설명
DISCLAIMER_RE = _c(
    r"(따르지\s*않|실행하지\s*않|명령으로\s*(?:취급|처리)하지\s*않|분석\s*(?:대상|자료|데이터)로만|"
    r"자료로만\s*취급|does\s+not\s+follow|treated\s+as\s+data)"
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
