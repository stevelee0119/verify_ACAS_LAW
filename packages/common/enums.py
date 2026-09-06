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


class CitationType(StrEnum):
    CASE = "CASE"
    STATUTE = "STATUTE"
    CONSTITUTIONAL = "CONSTITUTIONAL"
    INTERPRETATION = "INTERPRETATION"
    ADMIN_APPEAL = "ADMIN_APPEAL"
    ACADEMIC = "ACADEMIC"


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
}
