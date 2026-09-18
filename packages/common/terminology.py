"""Versioned display meanings. Codes and quoted legal language are never rewritten."""
from copy import deepcopy

TERMINOLOGY_VERSION = "2"

# A completed human review is deliberately a different namespace from verification.
TERMINOLOGY = {
    "verification_status": {
        "VERIFIED": ("검사 범위 내 확인", "해당 검사와 근거 범위에서 확인됨. 문서 전체의 적법성이나 진정성립을 보증하지 않음."),
        "PARTIALLY_VERIFIED": ("일부 확인", "검사 대상 중 일부만 확인되어 나머지 확인이 필요함."),
        "CONTRADICTED": ("근거와 불일치", "비교한 근거와 불일치함. 허위나 고의의 법적 판단을 뜻하지 않음."),
        "NOT_FOUND": ("조회 범위에서 미발견", "조회한 자료에서 찾지 못함. 대상의 부존재를 뜻하지 않음."),
        "SUSPICIOUS": ("추가 확인 필요", "이상 징후가 있어 추가 확인이 필요함. 위조 판정이 아님."),
        "UNVERIFIED": ("미검증", "확인에 필요한 근거나 검사가 부족함. 사람의 검토 완료로 확인 상태가 바뀌지 않음."),
        "SKIPPED": ("검사 생략", "해당 검사를 수행하지 않음."),
        "ERROR": ("검사 오류", "오류로 검사를 완료하지 못함."),
    },
    "evidence_grade": {
        "A": ("공식 원문 또는 암호학적 확인", "해당 항목에 공식 원문 또는 암호학적 확인 근거가 있음."),
        "B": ("복수 신뢰 자료", "복수의 신뢰 가능한 자료에 의한 확인."),
        "C": ("기술적 문맥적 근거", "기술적 또는 문맥상 근거. 법적 증명력 등급이 아님."),
        "D": ("추정 근거", "AI, 통계 또는 휴리스틱 추정. 확정 사실이 아님."),
        "U": ("확인 근거 부족", "검증 가능한 근거가 부족함."),
    },
    "report_state": {
        "DRAFT": ("검토용 초안", "검토 완료 전 생성한 고정 사본."),
        "FINAL": ("검토 확정본", "사용자가 잔여 미검증과 공유 범위를 확인한 고정 사본. 시스템 판정을 변경하지 않음."),
    },
    "audience": {
        "INTERNAL": ("내부 검토용", "검토 메모를 포함할 수 있는 내부 검토 자료. 봉인 원문은 포함하지 않음."),
        "SHAREABLE": ("공유용", "내부 메모 제외 및 탐지 가능한 개인정보 마스킹을 적용한 자료. 외부 전달 전 사람이 내용을 확인해야 함."),
    },
    "workflow_state": {
        "NOT_STARTED": ("검토 전", "사람의 검토를 시작하지 않음."),
        "IN_PROGRESS": ("검토 중", "사람의 검토가 진행 중임."),
        "ACTION_REQUIRED": ("조치 필요", "추가 조치가 필요함."),
        "COMPLETED": ("검토 완료", "사람의 검토 절차 완료. 시스템 검증 결과와 별개임."),
        "DEFERRED": ("검토 보류", "검토가 보류됨. 완료로 취급하지 않음."),
    },
    "decision": {
        "UNDECIDED": ("의견 미정", "사람의 판단이 아직 기록되지 않음."),
        "AGREED": ("검사 의견 동의", "사람이 해당 검사 의견에 동의함."),
        "PARTLY_AGREED": ("검사 의견 일부 동의", "사람이 검사 의견 중 일부에 동의함."),
        "FALSE_POSITIVE": ("오탐 의견", "사람이 오탐으로 판단함. 원래 시스템 결과는 보존됨."),
    },
    "position": {
        "UNASSESSED": ("입장 미검토", "해당 주장에 대한 입장을 검토하지 않음."),
        "ASSERTED": ("주장", "당사자가 주장한 내용."),
        "ADMITTED": ("인정", "검토자가 기록한 인정 입장. 재판상 자백 성립 판단과 구별함."),
        "DENIED": ("부인", "해당 사실 주장에 대한 부인 입장."),
        "UNKNOWN": ("부지", "알지 못한다는 입장. 단순 부인과 구별함."),
        "CONDITIONAL": ("조건부 주장", "조건을 전제로 한 주장."),
        "ALTERNATIVE": ("예비적 주장", "주위적 주장과 구별되는 예비적 주장."),
    },
    "support_status": {
        "UNASSESSED": ("증거 검토 전", "주장과 증거의 관계를 검토하지 않음."),
        "SUPPORTED": ("뒷받침 의견", "검토자가 증거의 뒷받침을 기록함. 법원의 사실인정이 아님."),
        "PARTIAL": ("일부 뒷받침 의견", "주장의 일부만 뒷받침된다는 검토 의견."),
        "CONFLICTING": ("증거 충돌", "연결한 증거 사이에 충돌이 있다는 검토 의견."),
        "INSUFFICIENT": ("증거 부족", "추가 자료가 필요하다는 검토 의견."),
        "REVIEWED": ("증거 검토 완료", "증거 검토 절차 완료. 주장이 증명되었다는 의미가 아님."),
        "EVIDENCE_EXCLUDED": ("연결 증거 제외됨", "연결한 증거가 현재 검증 범위에서 제외되었거나 없어 재검토가 필요함."),
    },
}


def terminology_catalog():
    return {"version": TERMINOLOGY_VERSION, "groups": {
        group: {code: {"code": code, "label": value[0], "meaning": value[1]}
                for code, value in entries.items()}
        for group, entries in deepcopy(TERMINOLOGY).items()
    }}


def term_label(group, code):
    code = str(code)
    return TERMINOLOGY.get(group, {}).get(code, (code, ""))[0]


def report_label(state, audience):
    return f"{state} / {term_label('report_state', state)} / {term_label('audience', audience)}"


EDITABLE_COPY_NOTICE = (
    "편집 가능한 사본입니다. 편집 후 내용은 보관된 생성 산출물과 다를 수 있습니다. "
    "원본 실행 ID와 스냅샷 SHA-256으로 생성 시점의 자료를 확인하세요."
)
REVIEW_NOTICE = "검토 확정은 사람의 검토 기록을 고정하며 시스템의 미검증 결과를 VERIFIED로 바꾸지 않습니다."
