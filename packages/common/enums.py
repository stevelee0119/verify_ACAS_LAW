"""공통 열거형 정의.

기술설계서 제16장(Finding·Evidence·Risk Model), 제18.2장(Job State),
부록 A(주요 Finding Type)에 대응한다.
"""
from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """JSON 직렬화가 쉬운 문자열 Enum."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# ---------------------------------------------------------------------------
# 16.1 Verification Status
# ---------------------------------------------------------------------------
class VerificationStatus(StrEnum):
    VERIFIED = "VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    CONTRADICTED = "CONTRADICTED"
    NOT_FOUND = "NOT_FOUND"
    SUSPICIOUS = "SUSPICIOUS"
    UNVERIFIED = "UNVERIFIED"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


# ---------------------------------------------------------------------------
# 16.2 Evidence Grade
# ---------------------------------------------------------------------------
class EvidenceGrade(StrEnum):
    A = "A"  # 공식 원문 또는 암호학적으로 확인
    B = "B"  # 신뢰 가능한 복수 Source로 확인
    C = "C"  # 기술적·문맥상 강한 근거
    D = "D"  # AI·통계·휴리스틱 추정
    U = "U"  # 검증 불가


# ---------------------------------------------------------------------------
# 16.3 Severity
# ---------------------------------------------------------------------------
class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


def severity_max(a: "Severity", b: "Severity") -> "Severity":
    return a if a.rank >= b.rank else b


def severity_cap(value: "Severity", ceiling: "Severity") -> "Severity":
    """상한을 넘지 않도록 Severity를 제한한다(예: MM-4는 MEDIUM 상한)."""
    return value if value.rank <= ceiling.rank else ceiling


# ---------------------------------------------------------------------------
# 18.2 Job State
# ---------------------------------------------------------------------------
class JobState(StrEnum):
    QUEUED = "QUEUED"
    PARSING = "PARSING"
    ADVERSARIAL_SCANNING = "ADVERSARIAL_SCANNING"
    EXTRACTING = "EXTRACTING"
    PII_PROCESSING = "PII_PROCESSING"
    VERIFYING = "VERIFYING"
    CROSS_CHECKING = "CROSS_CHECKING"
    AGGREGATING = "AGGREGATING"
    COMPLETED = "COMPLETED"
    PARTIAL_COMPLETED = "PARTIAL_COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


JOB_PROGRESS_ORDER = [
    JobState.QUEUED,
    JobState.PARSING,
    JobState.ADVERSARIAL_SCANNING,
    JobState.EXTRACTING,
    JobState.PII_PROCESSING,
    JobState.VERIFYING,
    JobState.CROSS_CHECKING,
    JobState.AGGREGATING,
]


# ---------------------------------------------------------------------------
# 19.4 사용자 Review 상태
# ---------------------------------------------------------------------------
class ReviewStatus(StrEnum):
    NEEDS_REVIEW = "NEEDS_REVIEW"
    ACCEPTED = "ACCEPTED"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    RESOLVED = "RESOLVED"


# ---------------------------------------------------------------------------
# 7.4 Adversarial semantic 분류 / 7-A.8 오탐 억제 4단계
# ---------------------------------------------------------------------------
class AdversarialClass(StrEnum):
    BENIGN_CONTENT = "BENIGN_CONTENT"
    INSTRUCTION_LIKE = "INSTRUCTION_LIKE"
    SUSPICIOUS_META_INSTRUCTION = "SUSPICIOUS_META_INSTRUCTION"
    PROMPT_INJECTION_LIKELY = "PROMPT_INJECTION_LIKELY"


class InjectionIntent(StrEnum):
    INSTRUCTION_OVERRIDE = "INSTRUCTION_OVERRIDE"
    ROLE_OVERRIDE = "ROLE_OVERRIDE"
    OUTPUT_MANIPULATION = "OUTPUT_MANIPULATION"
    VERIFICATION_SUPPRESSION = "VERIFICATION_SUPPRESSION"
    SYSTEM_SECRET_EXTRACTION = "SYSTEM_SECRET_EXTRACTION"
    TOOL_MANIPULATION = "TOOL_MANIPULATION"
    PERSISTENT_INSTRUCTION = "PERSISTENT_INSTRUCTION"
    DATA_EXFILTRATION = "DATA_EXFILTRATION"


class ForensicLevel(StrEnum):
    """7-A.8 오탐 억제 4단계."""

    BENIGN = "BENIGN"
    NOTABLE = "NOTABLE"
    SUSPICIOUS = "SUSPICIOUS"
    CRITICAL = "CRITICAL"


class MetaMessageType(StrEnum):
    """7-A.1 은닉 메타메시지 유형."""

    MM1_MACHINE_INSTRUCTION = "MM-1"
    MM2_RESIDUAL = "MM-2"
    MM3_COVERT_CHANNEL = "MM-3"
    MM4_IMPLICIT = "MM-4"


# ---------------------------------------------------------------------------
# 10. Source Adapter 상태
# ---------------------------------------------------------------------------
class AdapterStatus(StrEnum):
    READY = "READY"
    MISSING_KEY = "MISSING_KEY"
    DISABLED = "DISABLED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


NON_FATAL_ADAPTER_STATUS = {
    AdapterStatus.MISSING_KEY,
    AdapterStatus.TIMEOUT,
    AdapterStatus.ERROR,
    AdapterStatus.DISABLED,
    AdapterStatus.RATE_LIMITED,
}


# ---------------------------------------------------------------------------
# 11.1 Claim Types
# ---------------------------------------------------------------------------
class ClaimType(StrEnum):
    FACT = "FACT"
    LEGAL_RULE = "LEGAL_RULE"
    CASE_HOLDING = "CASE_HOLDING"
    LEGAL_INTERPRETATION = "LEGAL_INTERPRETATION"
    DOCUMENT_EXISTENCE = "DOCUMENT_EXISTENCE"
    ACADEMIC_CITATION = "ACADEMIC_CITATION"
    CALCULATION = "CALCULATION"
    OPINION = "OPINION"
    # 당사자가 법적 평가를 주장하는 문장(위법하다·무효이다·취소되어야 한다).
    # 사실 주장과도, 법령 문언 인용과도, 단순 의견과도 검증 방법이 다르다.
    LEGAL_ARGUMENT = "LEGAL_ARGUMENT"
    # 제목·목차·작성 안내·시험 안내처럼 문서 자체를 설명하는 문구. 검증 대상 주장이 아니다.
    DOCUMENT_META = "DOCUMENT_META"
    # 문서 안에서 검증기·모델에 명령하려는 문구. 주장이 아니라 공격 탐지 대상이다.
    ADVERSARIAL_INSTRUCTION = "ADVERSARIAL_INSTRUCTION"


class CitationType(StrEnum):
    CASE = "CASE"
    STATUTE = "STATUTE"
    CONSTITUTIONAL = "CONSTITUTIONAL"
    INTERPRETATION = "INTERPRETATION"
    ADMIN_APPEAL = "ADMIN_APPEAL"
    ACADEMIC = "ACADEMIC"
    # 훈령·예규·고시·지침. 법령과 달리 원칙적으로 대외적 구속력이 없으므로 따로 검증한다.
    ADMIN_RULE = "ADMIN_RULE"


class EntityType(StrEnum):
    PERSON = "PERSON"
    COMPANY = "COMPANY"
    ORGANIZATION = "ORGANIZATION"
    COURT = "COURT"
    PLACE = "PLACE"
    CONTRACT = "CONTRACT"
    CASE = "CASE"
    STATUTE = "STATUTE"
    DATE = "DATE"
    MONEY = "MONEY"
    DOCUMENT = "DOCUMENT"


# ---------------------------------------------------------------------------
# 13. AI 작성 여부 / 모델 Attribution
# ---------------------------------------------------------------------------
class AuthorshipVerdict(StrEnum):
    AI_LIKELY = "AI_LIKELY"
    UNCERTAIN = "UNCERTAIN"
    HUMAN_LIKELY = "HUMAN_LIKELY"
    ABSTAIN = "ABSTAIN"


class AIInvolvementVerdict(StrEnum):
    """제8.1장 범위별 AI 관여 판정.

    AuthorshipVerdict(AI_LIKELY/HUMAN_LIKELY)와 달리 '누가 썼는가'를 맞히지 않는다.
    "확인 가능한 기록이 무엇을 말하는가"만 말한다. 흔적이 없다는 결과를
    사람이 작성했다는 증거로 바꾸지 않기 위해 HUMAN에 해당하는 값이 없다.
    """

    VERIFIED_AI_RECORD = "VERIFIED_AI_RECORD"          # 검증 게이트를 모두 통과한 AI 진술
    AI_INDICATION_UNVERIFIED = "AI_INDICATION_UNVERIFIED"  # 표기는 있으나 진위 미검증
    INCONCLUSIVE = "INCONCLUSIVE"                      # 정상 검사했으나 판단 불가
    UNAVAILABLE = "UNAVAILABLE"                        # 판단에 필요한 검사를 못 함


class ProvenanceScope(StrEnum):
    """제7.1장 근거가 적용되는 대상.

    범위를 섞지 않는 것이 이 모델의 요점이다. 삽입 이미지의 AI 생성 기록을
    문서 본문의 AI 작성 근거로 쓰지 않는다.
    """

    FILE_CONTAINER = "file_container"    # 파일을 만든 도구·패키지 수준
    DOCUMENT_TEXT = "document_text"      # 문서 본문
    TEXT_REGION = "text_region"          # 본문 일부 구간
    EMBEDDED_IMAGE = "embedded_image"    # 삽입 이미지
    ATTACHMENT = "attachment"            # 첨부 문서


class CheckStatus(StrEnum):
    """제9.1장 검사 수행 상태.

    unsupported를 not_found로 매핑하면 안 된다. '검사했는데 없었다'와
    '검사할 수 없었다'가 같은 값이 되면, 분석 실패가 무해한 결과로 둔갑한다.
    """

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    NOT_FOUND = "not_found"            # 검사 완료, 해당 정보 없음
    UNSUPPORTED = "unsupported"        # 검증기·파서 미구현
    BLOCKED = "blocked"                # 암호화·자원한도 등으로 차단
    FAILED = "failed"
    NOT_REQUESTED = "not_requested"
    NOT_APPLICABLE = "not_applicable"


class ProvenanceAction(StrEnum):
    """제8.3장 기록된 제작 행위. 생성과 수정을 합치지 않는다."""

    GENERATE = "generate"
    EDIT = "edit"
    FORMAT = "format"
    CONVERT = "convert"
    UNKNOWN = "unknown"


class AttributionLevel(StrEnum):
    PROVEN = "PROVEN"
    STRONG_INDICATION = "STRONG_INDICATION"
    WEAK_INDICATION = "WEAK_INDICATION"
    UNDETERMINED = "UNDETERMINED"


# ---------------------------------------------------------------------------
# 5.2 / 21.3 외부 AI 사용정책, 22.2 Verification Profile
# ---------------------------------------------------------------------------
class ExternalAIPolicy(StrEnum):
    ORIGINAL = "ORIGINAL"
    MASKED = "MASKED"
    LOCAL_ONLY = "LOCAL_ONLY"


class VerificationProfile(StrEnum):
    QUICK = "QUICK"
    STANDARD = "STANDARD"
    DEEP_VERIFY = "DEEP_VERIFY"


class LLMRole(StrEnum):
    PRIMARY_REASONER = "PRIMARY_REASONER"
    INDEPENDENT_CRITIC = "INDEPENDENT_CRITIC"
    WEB_GROUNDER = "WEB_GROUNDER"
    JUDGE = "JUDGE"
    LOW_COST_EXTRACTOR = "LOW_COST_EXTRACTOR"


# ---------------------------------------------------------------------------
# 15.2 Audit Event
# ---------------------------------------------------------------------------
class AuditEventType(StrEnum):
    UPLOAD = "UPLOAD"
    HASH_CREATED = "HASH_CREATED"
    OCR = "OCR"
    ADVERSARIAL_SCAN = "ADVERSARIAL_SCAN"
    PII_DETECTION = "PII_DETECTION"
    PII_MASKING = "PII_MASKING"
    AI_REQUEST = "AI_REQUEST"
    API_QUERY = "API_QUERY"
    SOURCE_RETRIEVED = "SOURCE_RETRIEVED"
    VERIFICATION = "VERIFICATION"
    USER_OVERRIDE = "USER_OVERRIDE"
    REPORT_GENERATED = "REPORT_GENERATED"
    EXPORT = "EXPORT"
    DELETE = "DELETE"
    SEALED_CONTENT_REVEALED = "SEALED_CONTENT_REVEALED"


# ---------------------------------------------------------------------------
# 부록 A. 주요 Finding Type
# ---------------------------------------------------------------------------
class FindingType(StrEnum):
    # LEGAL
    CASE_NOT_FOUND = "CASE_NOT_FOUND"
    CASE_METADATA_MISMATCH = "CASE_METADATA_MISMATCH"
    CASE_QUOTE_MISMATCH = "CASE_QUOTE_MISMATCH"
    CASE_HOLDING_DISTORTION = "CASE_HOLDING_DISTORTION"
    CASE_CITATION_ERROR = "CASE_CITATION_ERROR"
    LAW_CITATION_ERROR = "LAW_CITATION_ERROR"
    TEMPORAL_LAW_MISMATCH = "TEMPORAL_LAW_MISMATCH"
    ACADEMIC_CITATION_ERROR = "ACADEMIC_CITATION_ERROR"
    # FACT / LOGIC
    FACT_CONTRADICTION = "FACT_CONTRADICTION"
    CROSS_DOCUMENT_CONTRADICTION = "CROSS_DOCUMENT_CONTRADICTION"
    TIMELINE_CONTRADICTION = "TIMELINE_CONTRADICTION"
    ARITHMETIC_MISMATCH = "ARITHMETIC_MISMATCH"
    # FORENSIC
    METADATA_ANOMALY = "METADATA_ANOMALY"
    HIDDEN_TEXT_MISMATCH = "HIDDEN_TEXT_MISMATCH"
    OCR_LAYER_MISMATCH = "OCR_LAYER_MISMATCH"
    SIGNATURE_INVALID = "SIGNATURE_INVALID"
    MODIFIED_AFTER_SIGNATURE = "MODIFIED_AFTER_SIGNATURE"
    PAGE_STRUCTURE_OUTLIER = "PAGE_STRUCTURE_OUTLIER"
    # ADVERSARIAL (7.6)
    PROMPT_INJECTION_SUSPECTED = "PROMPT_INJECTION_SUSPECTED"
    HIDDEN_INSTRUCTION = "HIDDEN_INSTRUCTION"
    META_INSTRUCTION = "META_INSTRUCTION"
    SYSTEM_OVERRIDE_ATTEMPT = "SYSTEM_OVERRIDE_ATTEMPT"
    ROLE_OVERRIDE_ATTEMPT = "ROLE_OVERRIDE_ATTEMPT"
    VERIFICATION_SUPPRESSION = "VERIFICATION_SUPPRESSION"
    OUTPUT_MANIPULATION_ATTEMPT = "OUTPUT_MANIPULATION_ATTEMPT"
    ENCODED_INSTRUCTION = "ENCODED_INSTRUCTION"
    OBFUSCATED_INSTRUCTION = "OBFUSCATED_INSTRUCTION"
    UNICODE_SMUGGLING = "UNICODE_SMUGGLING"
    OCR_LAYER_INJECTION = "OCR_LAYER_INJECTION"
    METADATA_INJECTION = "METADATA_INJECTION"
    MULTIMODAL_INJECTION = "MULTIMODAL_INJECTION"
    RAG_POISONING_SIGNAL = "RAG_POISONING_SIGNAL"
    TOOL_MANIPULATION_ATTEMPT = "TOOL_MANIPULATION_ATTEMPT"
    DATA_EXFILTRATION_INSTRUCTION = "DATA_EXFILTRATION_INSTRUCTION"
    MODEL_OUTPUT_QUARANTINED = "MODEL_OUTPUT_QUARANTINED"
    # AUTHORSHIP
    AI_AUTHORSHIP_LIKELY = "AI_AUTHORSHIP_LIKELY"
    AI_FULL_GENERATION_SUSPECTED = "AI_FULL_GENERATION_SUSPECTED"  # 문서 전체 AI 임의 생성 의심
    AI_HALLUCINATED_CONTENT = "AI_HALLUCINATED_CONTENT"            # AI 임의 생성/환각 내용(가짜 판례·조문 기반 주장 등)
    LEGAL_ARGUMENT_INVALID = "LEGAL_ARGUMENT_INVALID"              # 법률적 주장 타당성 결여/결함
    STYLE_SHIFT = "STYLE_SHIFT"
    MODEL_ATTRIBUTION_SIGNAL = "MODEL_ATTRIBUTION_SIGNAL"
    # META-MESSAGE (7-A.9)
    RESIDUAL_TRACKED_CHANGE = "RESIDUAL_TRACKED_CHANGE"
    RESIDUAL_COMMENT = "RESIDUAL_COMMENT"
    DELETED_TEXT_RECOVERABLE = "DELETED_TEXT_RECOVERABLE"
    PRIOR_VERSION_RECOVERABLE = "PRIOR_VERSION_RECOVERABLE"
    REDACTION_FAILURE = "REDACTION_FAILURE"
    HIDDEN_SHEET_OR_ROW = "HIDDEN_SHEET_OR_ROW"
    CROPPED_IMAGE_RESIDUE = "CROPPED_IMAGE_RESIDUE"
    TEMPLATE_RESIDUE = "TEMPLATE_RESIDUE"
    # 가상·예시 문서 식별 (제11장 문서 진정성)
    SPECIMEN_DOCUMENT_DECLARED = "SPECIMEN_DOCUMENT_DECLARED"
    INVALID_IDENTIFIER = "INVALID_IDENTIFIER"
    PLACEHOLDER_IDENTIFIER = "PLACEHOLDER_IDENTIFIER"
    AUTHORSHIP_METADATA_LEAK = "AUTHORSHIP_METADATA_LEAK"
    GEOLOCATION_METADATA_LEAK = "GEOLOCATION_METADATA_LEAK"
    STEGANOGRAPHIC_PAYLOAD = "STEGANOGRAPHIC_PAYLOAD"
    TRACKING_CANARY_DETECTED = "TRACKING_CANARY_DETECTED"
    DOCUMENT_FINGERPRINT_SUSPECTED = "DOCUMENT_FINGERPRINT_SUSPECTED"
    COVERT_CHANNEL_SUSPECTED = "COVERT_CHANNEL_SUSPECTED"
    PRIVILEGE_EXPOSURE_RISK = "PRIVILEGE_EXPOSURE_RISK"
    OUTBOUND_LEAK_RISK = "OUTBOUND_LEAK_RISK"
    # MM-4 Advisory Signals
    ISSUE_EVASION_SIGNAL = "ISSUE_EVASION_SIGNAL"
    IMPLICIT_ADMISSION_SIGNAL = "IMPLICIT_ADMISSION_SIGNAL"
    LIABILITY_HEDGING_SIGNAL = "LIABILITY_HEDGING_SIGNAL"
    COERCIVE_LANGUAGE_SIGNAL = "COERCIVE_LANGUAGE_SIGNAL"
    SELECTIVE_QUOTATION_SIGNAL = "SELECTIVE_QUOTATION_SIGNAL"
    # 명세 v1.0 제1.2장. 위에 대응 항목이 없는 오류 유형만 새로 둔다.
    CASE_RELEVANCE_WEAK = "CASE_RELEVANCE_WEAK"
    STATUTE_NONEXISTENT = "STATUTE_NONEXISTENT"
    STATUTE_TEXT_MISMATCH = "STATUTE_TEXT_MISMATCH"
    INTERNAL_CITATION_ERROR = "INTERNAL_CITATION_ERROR"
    QUOTE_MISMATCH = "QUOTE_MISMATCH"
    FACT_UNSUPPORTED = "FACT_UNSUPPORTED"
    # 증거·첨부자료. 자료가 없다는 것은 '검증되지 않음'이지 허위·위조의 근거가 아니다.
    EVIDENCE_NOT_PROVIDED = "EVIDENCE_NOT_PROVIDED"          # 문서 스스로 미첨부를 밝힌 자료
    EVIDENCE_REFERENCE_MISSING = "EVIDENCE_REFERENCE_MISSING"  # 첨부·증거로 적혔으나 입력 파일에 없음
    HASH_FORMAT_INVALID = "HASH_FORMAT_INVALID"              # 기재 해시가 알고리즘 형식에 맞지 않음
    HASH_MISMATCH = "HASH_MISMATCH"                          # 입력 파일 바이트의 해시와 다름
    SOURCE_CONFLICT_IGNORED = "SOURCE_CONFLICT_IGNORED"
    CALCULATION_INVARIANT_VIOLATION = "CALCULATION_INVARIANT_VIOLATION"
    LEGAL_REQUIREMENT_OMITTED = "LEGAL_REQUIREMENT_OMITTED"
    OVERCLAIM = "OVERCLAIM"
    REASONING_GAP = "REASONING_GAP"
    AUTHORITY_RANK_ERROR = "AUTHORITY_RANK_ERROR"
    DRAFT_ARTIFACT = "DRAFT_ARTIFACT"
    UNCERTAINTY_NOT_DISCLOSED = "UNCERTAINTY_NOT_DISCLOSED"
    # 처리 상태
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    PARSE_ERROR = "PARSE_ERROR"


ADVERSARIAL_FINDING_TYPES = {
    FindingType.PROMPT_INJECTION_SUSPECTED,
    FindingType.HIDDEN_INSTRUCTION,
    FindingType.META_INSTRUCTION,
    FindingType.SYSTEM_OVERRIDE_ATTEMPT,
    FindingType.ROLE_OVERRIDE_ATTEMPT,
    FindingType.VERIFICATION_SUPPRESSION,
    FindingType.OUTPUT_MANIPULATION_ATTEMPT,
    FindingType.ENCODED_INSTRUCTION,
    FindingType.OBFUSCATED_INSTRUCTION,
    FindingType.UNICODE_SMUGGLING,
    FindingType.OCR_LAYER_INJECTION,
    FindingType.METADATA_INJECTION,
    FindingType.MULTIMODAL_INJECTION,
    FindingType.RAG_POISONING_SIGNAL,
    FindingType.TOOL_MANIPULATION_ATTEMPT,
    FindingType.DATA_EXFILTRATION_INSTRUCTION,
}

MM4_ADVISORY_TYPES = {
    FindingType.ISSUE_EVASION_SIGNAL,
    FindingType.IMPLICIT_ADMISSION_SIGNAL,
    FindingType.LIABILITY_HEDGING_SIGNAL,
    FindingType.COERCIVE_LANGUAGE_SIGNAL,
    FindingType.SELECTIVE_QUOTATION_SIGNAL,
}

LEGAL_FINDING_TYPES = {
    FindingType.CASE_NOT_FOUND,
    FindingType.CASE_METADATA_MISMATCH,
    FindingType.CASE_QUOTE_MISMATCH,
    FindingType.CASE_HOLDING_DISTORTION,
    FindingType.CASE_CITATION_ERROR,
    FindingType.LAW_CITATION_ERROR,
    FindingType.TEMPORAL_LAW_MISMATCH,
    FindingType.ACADEMIC_CITATION_ERROR,
    FindingType.LEGAL_ARGUMENT_INVALID,
}


# 명세 v1.0 제1.2장의 코드 이름과 이 시스템의 FindingType 이름이 다른 경우의 대응표.
# 같은 결함에 이름을 둘 두면 한쪽만 처리하는 코드가 생기므로, 새 멤버를 만들지 않고
# 보고서 출력 단계에서만 명세 코드명을 함께 싣는다.
SPEC_FINDING_CODE = {
    FindingType.CASE_NOT_FOUND: "CASE_NONEXISTENT",
    FindingType.CASE_HOLDING_DISTORTION: "CASE_HOLDING_MISMATCH",
    FindingType.TEMPORAL_LAW_MISMATCH: "STATUTE_VERSION_ERROR",
    FindingType.ARITHMETIC_MISMATCH: "CALCULATION_ERROR",
    FindingType.ACADEMIC_CITATION_ERROR: "SECONDARY_SOURCE_ERROR",
    FindingType.CASE_QUOTE_MISMATCH: "QUOTE_MISMATCH",
}


def spec_code(value: "FindingType") -> str:
    """명세 제1.2장의 코드명을 돌려준다. 대응표에 없으면 본래 이름이 곧 명세 코드다."""
    return SPEC_FINDING_CODE.get(value, str(value))


# 제1.2장의 심각도 기본값. 개별 검출기가 근거의 강도에 따라 내릴 수는 있으나
# 올리려면 그 이유가 Finding에 남아야 한다.
SPEC_DEFAULT_SEVERITY = {
    FindingType.CASE_NOT_FOUND: Severity.CRITICAL,
    FindingType.CASE_METADATA_MISMATCH: Severity.CRITICAL,
    FindingType.CASE_HOLDING_DISTORTION: Severity.CRITICAL,
    FindingType.CASE_RELEVANCE_WEAK: Severity.HIGH,
    FindingType.STATUTE_NONEXISTENT: Severity.CRITICAL,
    FindingType.TEMPORAL_LAW_MISMATCH: Severity.CRITICAL,
    FindingType.STATUTE_TEXT_MISMATCH: Severity.HIGH,
    FindingType.INTERNAL_CITATION_ERROR: Severity.HIGH,
    FindingType.QUOTE_MISMATCH: Severity.CRITICAL,
    FindingType.CASE_QUOTE_MISMATCH: Severity.CRITICAL,
    FindingType.FACT_UNSUPPORTED: Severity.HIGH,
    FindingType.FACT_CONTRADICTION: Severity.CRITICAL,
    FindingType.SOURCE_CONFLICT_IGNORED: Severity.HIGH,
    FindingType.ARITHMETIC_MISMATCH: Severity.HIGH,
    FindingType.CALCULATION_INVARIANT_VIOLATION: Severity.HIGH,
    FindingType.LEGAL_REQUIREMENT_OMITTED: Severity.HIGH,
    FindingType.OVERCLAIM: Severity.HIGH,
    FindingType.REASONING_GAP: Severity.HIGH,
    FindingType.AUTHORITY_RANK_ERROR: Severity.MEDIUM,
    FindingType.ACADEMIC_CITATION_ERROR: Severity.HIGH,
    FindingType.DRAFT_ARTIFACT: Severity.MEDIUM,
    FindingType.UNCERTAINTY_NOT_DISCLOSED: Severity.HIGH,
}


class ReleaseGate(StrEnum):
    """제9.2장 배포가능 상태."""

    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    BLOCK = "BLOCK"

    @property
    def rank(self) -> int:
        return {"PASS": 0, "PASS_WITH_WARNINGS": 1,
                "HUMAN_REVIEW_REQUIRED": 2, "BLOCK": 3}[self.value]


class SourceVerdict(StrEnum):
    """제4.1장 출처 대조 판정값. 조회 실패는 NOT_FOUND가 아니라 UNVERIFIABLE이다."""

    VERIFIED_EXACT = "VERIFIED_EXACT"
    VERIFIED_PARAPHRASE = "VERIFIED_PARAPHRASE"
    PARTIAL = "PARTIAL"
    WRONG_VERSION = "WRONG_VERSION"
    MISMATCH = "MISMATCH"
    NOT_FOUND = "NOT_FOUND"
    UNVERIFIABLE = "UNVERIFIABLE"


class SupportType(StrEnum):
    """제5.1장. 기록에 적힌 사실과 해석으로 도출한 사실을 섞지 않는다."""

    EXPLICIT = "EXPLICIT"
    INFERRED = "INFERRED"


class ConflictResolution(StrEnum):
    """제5.2장. 충돌을 무엇으로 풀었는지 남긴다."""

    UNRESOLVED = "UNRESOLVED"
    PRIORITY_RULE = "PRIORITY_RULE"
    INTERPRETATION = "INTERPRETATION"
    HUMAN_DECISION = "HUMAN_DECISION"
