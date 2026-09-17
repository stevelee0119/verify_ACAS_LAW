"""제7장 Adversarial Content & Prompt Injection Forensics Engine.

모든 LLM 호출보다 먼저 실행한다(제7장 서문, 제24.3장 Release Gate).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from packages.common.confidence import score as confidence_score
from packages.common.enums import (
    AdversarialClass,
    EvidenceGrade,
    FindingType,
    ForensicLevel,
    InjectionIntent,
    MetaMessageType,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import Block, EngineResult, Evidence, Finding, NormalizedDocument

from .classifier import Classification, classify, severity_for
from .cross_layer import compare_layers
from .encoding_scan import decode_candidates
from .unicode_scan import scan_unicode

ENGINE_NAME = "adversarial_engine"

MAX_EXCERPT = 300


def _excerpt(text: str) -> str:
    t = " ".join(text.split())
    return t[:MAX_EXCERPT] + ("…" if len(t) > MAX_EXCERPT else "")


class AdversarialScanner:
    """문서를 UNTRUSTED EVIDENCE로 취급해 적대적 조작을 탐지한다."""

    def scan(self, doc: NormalizedDocument) -> EngineResult:
        result = EngineResult(engine=ENGINE_NAME)
        findings: List[Finding] = []

        findings.extend(self._scan_blocks(doc))
        findings.extend(self._scan_metadata(doc))
        findings.extend(self._scan_unicode(doc))
        findings.extend(self._scan_encoding(doc))
        findings.extend(self._scan_cross_layer(doc))
        findings.extend(self._scan_multimodal(doc))

        result.findings = findings
        result.data["adversarial_risk"] = self.risk_level(findings)
        result.data["scanned_layers"] = sorted(set(b.source_layer for b in doc.blocks))
        result.data["injection_candidate_count"] = len(findings)
        return result

    # -- 레이어별 검사 ----------------------------------------------------
    def _scan_blocks(self, doc: NormalizedDocument) -> List[Finding]:
        out: List[Finding] = []
        for block in doc.blocks:
            if not block.text.strip():
                continue
            classification = classify(
                block.text,
                source_layer=block.source_layer,
                visible=block.visible,
                hidden_reason=block.attributes.get("hidden_reason"),
                block_type=block.block_type,
            )
            if classification.label == AdversarialClass.BENIGN_CONTENT:
                continue
            in_ocr = block.source_layer == "ocr_layer"
            finding_type = self._finding_type_for_block(block, classification)
            severity = severity_for(classification, in_ocr_layer=in_ocr)
            features = {
                "deterministic_rule": True,
                "cross_layer_mismatch": not block.visible,
                "forensic_signal": classification.features.get("corroborating_signals", 0),
                **classification.features,
            }
            out.append(
                Finding.create(
                    type=finding_type,
                    status=VerificationStatus.SUSPICIOUS,
                    severity=severity,
                    evidence_grade=EvidenceGrade.A if not block.visible else EvidenceGrade.C,
                    title=self._title_for(finding_type, classification),
                    detail=self._detail_for(block, classification),
                    confidence=confidence_score(features),
                    confidence_features=features,
                    document_id=doc.document_id,
                    block_id=block.block_id,
                    page=block.page,
                    bbox=block.bbox,
                    engine=ENGINE_NAME,
                    meta_message_type=MetaMessageType.MM1_MACHINE_INSTRUCTION,
                    adversarial_class=classification.label,
                    forensic_level=self._forensic_level(classification),
                    tags=[str(i) for i in classification.intents],
                    evidence=[
                        Evidence.create(
                            description=f"{block.source_layer} 레이어에서 관찰된 지시형 문자열",
                            grade=EvidenceGrade.A if not block.visible else EvidenceGrade.C,
                            document_id=doc.document_id,
                            block_id=block.block_id,
                            page=block.page,
                            excerpt=_excerpt(block.text),
                        )
                    ],
                )
            )
        return out

    @staticmethod
    def _finding_type_for_block(block: Block, classification: Classification) -> FindingType:
        if block.source_layer == "ocr_layer" and not block.visible:
            return FindingType.OCR_LAYER_INJECTION
        if not block.visible and classification.label in (
            AdversarialClass.PROMPT_INJECTION_LIKELY,
            AdversarialClass.SUSPICIOUS_META_INSTRUCTION,
        ):
            return FindingType.HIDDEN_INSTRUCTION
        if classification.label == AdversarialClass.PROMPT_INJECTION_LIKELY:
            return classification.primary_finding_type
        if classification.label == AdversarialClass.SUSPICIOUS_META_INSTRUCTION:
            return FindingType.META_INSTRUCTION
        return FindingType.META_INSTRUCTION

    @staticmethod
    def _title_for(finding_type: FindingType, classification: Classification) -> str:
        intents = ", ".join(str(i) for i in classification.intents) or "UNSPECIFIED"
        return f"{finding_type} 후보: {intents}"

    @staticmethod
    def _detail_for(block: Block, classification: Classification) -> str:
        reason = block.attributes.get("hidden_reason")
        where = f"{block.source_layer}" + (f"/{reason}" if reason else "")
        return (
            f"{where} 위치에서 지시형 문자열이 관찰되었다. "
            f"분류={classification.label}, 점수={classification.score}, "
            f"보조신호={classification.features.get('corroborating_signals')}개. "
            "본 문자열은 자료로만 취급되며 시스템 지침이나 Tool 권한을 변경하지 않는다."
        )

    @staticmethod
    def _forensic_level(classification: Classification) -> ForensicLevel:
        return {
            AdversarialClass.PROMPT_INJECTION_LIKELY: ForensicLevel.CRITICAL,
            AdversarialClass.SUSPICIOUS_META_INSTRUCTION: ForensicLevel.SUSPICIOUS,
            AdversarialClass.INSTRUCTION_LIKE: ForensicLevel.NOTABLE,
            AdversarialClass.BENIGN_CONTENT: ForensicLevel.BENIGN,
        }[classification.label]

    def _scan_metadata(self, doc: NormalizedDocument) -> List[Finding]:
        out: List[Finding] = []
        for key, value in doc.metadata.items():
            text = str(value)
            if not text.strip() or len(text) < 8:
                continue
            classification = classify(text, source_layer="metadata", visible=False, block_type="metadata")
            if classification.label in (AdversarialClass.BENIGN_CONTENT, AdversarialClass.INSTRUCTION_LIKE):
                continue
            features = {"deterministic_rule": True, "cross_layer_mismatch": True, **classification.features}
            out.append(
                Finding.create(
                    type=FindingType.METADATA_INJECTION,
                    status=VerificationStatus.SUSPICIOUS,
                    severity=severity_for(classification),
                    evidence_grade=EvidenceGrade.A,
                    title=f"문서 메타데이터({key})에 지시형 문자열이 있다",
                    detail=(
                        f"메타데이터 필드 '{key}'는 사용자 화면에 표시되지 않으나 지시형 문자열을 포함한다. "
                        "메타데이터는 검증 지침이 될 수 없다."
                    ),
                    confidence=confidence_score(features),
                    confidence_features=features,
                    document_id=doc.document_id,
                    engine=ENGINE_NAME,
                    meta_message_type=MetaMessageType.MM1_MACHINE_INSTRUCTION,
                    adversarial_class=classification.label,
                    forensic_level=ForensicLevel.SUSPICIOUS,
                    evidence=[
                        Evidence.create(
                            description=f"metadata:{key}",
                            grade=EvidenceGrade.A,
                            document_id=doc.document_id,
                            excerpt=_excerpt(text),
                        )
                    ],
                )
            )
        return out

    def _scan_unicode(self, doc: NormalizedDocument) -> List[Finding]:
        out: List[Finding] = []
        for layer_name, text in doc.raw_layers.items():
            if not text:
                continue
            for signal in scan_unicode(text):
                recovered = signal.recovered_text
                hidden_instruction = False
                if recovered:
                    sub = classify(recovered, source_layer="hidden_text", visible=False)
                    hidden_instruction = sub.label != AdversarialClass.BENIGN_CONTENT
                severity = Severity.HIGH if hidden_instruction else Severity.MEDIUM
                if signal.kind in ("ZERO_WIDTH", "HOMOGLYPH") and not hidden_instruction:
                    severity = Severity.LOW
                features = {
                    "deterministic_rule": True,
                    "forensic_signal": 1,
                    "unicode_kind": signal.kind,
                    "layer": layer_name,
                    "recovered_instruction": hidden_instruction,
                }
                out.append(
                    Finding.create(
                        type=FindingType.UNICODE_SMUGGLING,
                        status=VerificationStatus.SUSPICIOUS,
                        severity=severity,
                        evidence_grade=EvidenceGrade.A,
                        title=f"Unicode 은닉 신호: {signal.kind}",
                        detail=f"{layer_name} 레이어. {signal.detail}"
                        + (f" 복원된 문자열에 지시형 표현이 있다." if hidden_instruction else ""),
                        confidence=confidence_score(features),
                        confidence_features=features,
                        document_id=doc.document_id,
                        engine=ENGINE_NAME,
                        meta_message_type=MetaMessageType.MM1_MACHINE_INSTRUCTION,
                        forensic_level=ForensicLevel.SUSPICIOUS if hidden_instruction else ForensicLevel.NOTABLE,
                        sealed_excerpt=recovered or signal.sample,
                        evidence=[
                            Evidence.create(
                                description=f"{layer_name} 레이어 Unicode 신호",
                                grade=EvidenceGrade.A,
                                document_id=doc.document_id,
                                excerpt=_excerpt(signal.sample),
                                sealed=True,
                            )
                        ],
                    )
                )
        return out

    def _scan_encoding(self, doc: NormalizedDocument) -> List[Finding]:
        out: List[Finding] = []
        seen: set[str] = set()
        for layer_name, text in doc.raw_layers.items():
            if not text:
                continue
            for segment in decode_candidates(text):
                classification = classify(segment.decoded, source_layer="hidden_text", visible=False)
                if classification.label == AdversarialClass.BENIGN_CONTENT:
                    continue
                key = segment.decoded[:80]
                if key in seen:
                    continue
                seen.add(key)
                features = {
                    "deterministic_rule": True,
                    "forensic_signal": 2,
                    "encoding": segment.encoding,
                    **classification.features,
                }
                out.append(
                    Finding.create(
                        type=FindingType.ENCODED_INSTRUCTION,
                        status=VerificationStatus.SUSPICIOUS,
                        severity=Severity.HIGH
                        if classification.label == AdversarialClass.PROMPT_INJECTION_LIKELY
                        else Severity.MEDIUM,
                        evidence_grade=EvidenceGrade.A,
                        title=f"{segment.encoding} 인코딩된 지시형 문자열",
                        detail=(
                            f"{layer_name} 레이어의 {segment.encoding} 문자열을 안전 디코드한 결과 지시형 표현이 확인되었다. "
                            "디코드는 표준 라이브러리로만 수행했고 어떤 실행·접속도 하지 않았다."
                        ),
                        confidence=confidence_score(features),
                        confidence_features=features,
                        document_id=doc.document_id,
                        engine=ENGINE_NAME,
                        meta_message_type=MetaMessageType.MM1_MACHINE_INSTRUCTION,
                        adversarial_class=classification.label,
                        forensic_level=ForensicLevel.SUSPICIOUS,
                        sealed_excerpt=segment.decoded[:1000],
                        evidence=[
                            Evidence.create(
                                description=f"{segment.encoding} 디코드 결과",
                                grade=EvidenceGrade.A,
                                document_id=doc.document_id,
                                excerpt=_excerpt(segment.decoded),
                                sealed=True,
                            )
                        ],
                    )
                )
        return out

    def _scan_cross_layer(self, doc: NormalizedDocument) -> List[Finding]:
        out: List[Finding] = []
        layers = dict(doc.raw_layers)
        stream_text = doc.structure.get("embedded_stream_text")
        if stream_text:
            layers["embedded_stream_text"] = stream_text

        for delta in compare_layers(layers):
            instruction_segments = []
            for segment in delta.only_in_right:
                classification = classify(segment, source_layer="hidden_text", visible=False)
                if classification.label != AdversarialClass.BENIGN_CONTENT:
                    instruction_segments.append((segment, classification))
            if not instruction_segments and delta.difference <= 0:
                continue

            ocr_layers = {"ocr_layer", "independent_ocr"}
            is_ocr = bool({delta.left_layer, delta.right_layer} & ocr_layers)
            finding_type = FindingType.OCR_LAYER_INJECTION if is_ocr and instruction_segments else (
                FindingType.OCR_LAYER_MISMATCH if is_ocr else FindingType.HIDDEN_TEXT_MISMATCH
            )
            severity = Severity.INFO
            if instruction_segments:
                severity = Severity.CRITICAL if is_ocr else Severity.HIGH
            elif not is_ocr and delta.difference > 40:
                severity = Severity.MEDIUM
            # OCR은 인식 오차가 있으므로 단순 분량 차이로는 Finding을 만들지 않는다.
            # 지시형 문자열이 한쪽 레이어에만 존재할 때만 보고한다.

            if severity == Severity.INFO:
                continue

            features = {
                "deterministic_rule": True,
                "cross_layer_mismatch": True,
                "forensic_signal": len(instruction_segments),
                "char_difference": delta.difference,
                "layer_similarity": delta.similarity,
            }
            detail = (
                f"{delta.left_layer}: {delta.left_chars}자, {delta.right_layer}: {delta.right_chars}자, "
                f"차이 {delta.difference}자."
            )
            if instruction_segments:
                detail += f" 표시되지 않는 구간 {len(instruction_segments)}건에 지시형 표현이 있다."
            if delta.left_layer == "independent_ocr":
                detail += (
                    " 독립 OCR로 화면을 다시 읽은 결과에는 없고 내장 텍스트 레이어에만 존재하는 문자열이다. "
                    "사람이 보는 화면과 모델이 읽는 텍스트가 다르다."
                )
            out.append(
                Finding.create(
                    type=finding_type,
                    status=VerificationStatus.SUSPICIOUS,
                    severity=severity,
                    evidence_grade=EvidenceGrade.A,
                    title=f"레이어 불일치: {delta.left_layer} vs {delta.right_layer}",
                    detail=detail,
                    confidence=confidence_score(features),
                    confidence_features=features,
                    document_id=doc.document_id,
                    engine=ENGINE_NAME,
                    meta_message_type=MetaMessageType.MM1_MACHINE_INSTRUCTION,
                    forensic_level=ForensicLevel.CRITICAL if instruction_segments else ForensicLevel.NOTABLE,
                    sealed_excerpt="\n".join(s for s, _ in instruction_segments)[:1000] or None,
                    evidence=[
                        Evidence.create(
                            description=f"{delta.right_layer}에만 존재하는 구간",
                            grade=EvidenceGrade.A,
                            document_id=doc.document_id,
                            excerpt=_excerpt(" / ".join(delta.only_in_right[:3])),
                            sealed=True,
                        )
                    ],
                )
            )
        return out

    def _scan_multimodal(self, doc: NormalizedDocument) -> List[Finding]:
        """이미지 OCR·PNG text chunk 등 비텍스트 경로의 지시문(제7.2장 Image 레이어)."""
        out: List[Finding] = []
        png_chunks = doc.structure.get("png_text_chunks") or {}
        for key, value in png_chunks.items():
            classification = classify(str(value), source_layer="metadata", visible=False)
            if classification.label == AdversarialClass.BENIGN_CONTENT:
                continue
            features = {"deterministic_rule": True, "forensic_signal": 1, **classification.features}
            out.append(
                Finding.create(
                    type=FindingType.MULTIMODAL_INJECTION,
                    status=VerificationStatus.SUSPICIOUS,
                    severity=Severity.HIGH,
                    evidence_grade=EvidenceGrade.A,
                    title=f"이미지 텍스트 청크({key})에 지시형 문자열이 있다",
                    detail="이미지 파일 내부 텍스트 청크는 화면에 표시되지 않으나 모델 입력에 포함될 수 있다.",
                    confidence=confidence_score(features),
                    confidence_features=features,
                    document_id=doc.document_id,
                    engine=ENGINE_NAME,
                    meta_message_type=MetaMessageType.MM1_MACHINE_INSTRUCTION,
                    adversarial_class=classification.label,
                    forensic_level=ForensicLevel.SUSPICIOUS,
                    sealed_excerpt=str(value)[:1000],
                )
            )

        for block in doc.blocks:
            if block.source_layer != "ocr_layer":
                continue
            classification = classify(block.text, source_layer="ocr_layer", visible=block.visible)
            if classification.label in (AdversarialClass.PROMPT_INJECTION_LIKELY,):
                features = {"deterministic_rule": True, "forensic_signal": 2, **classification.features}
                out.append(
                    Finding.create(
                        type=FindingType.MULTIMODAL_INJECTION,
                        status=VerificationStatus.SUSPICIOUS,
                        severity=Severity.HIGH,
                        evidence_grade=EvidenceGrade.B,
                        title="이미지 OCR 결과에 지시형 문자열이 있다",
                        detail="이미지에 삽입된 문자열이 모델 입력으로 유입될 수 있다.",
                        confidence=confidence_score(features),
                        confidence_features=features,
                        document_id=doc.document_id,
                        block_id=block.block_id,
                        page=block.page,
                        bbox=block.bbox,
                        engine=ENGINE_NAME,
                        meta_message_type=MetaMessageType.MM1_MACHINE_INSTRUCTION,
                        adversarial_class=classification.label,
                        forensic_level=ForensicLevel.SUSPICIOUS,
                    )
                )
        return out

    # -- 종합 --------------------------------------------------------------
    @staticmethod
    def risk_level(findings: List[Finding]) -> str:
        """제19.1장 Adversarial Manipulation Risk."""
        if any(f.severity == Severity.CRITICAL for f in findings):
            return "CRITICAL"
        if any(f.severity == Severity.HIGH for f in findings):
            return "HIGH"
        if any(f.severity == Severity.MEDIUM for f in findings):
            return "MEDIUM"
        if findings:
            return "LOW"
        return "NONE"


def scan_document(doc: NormalizedDocument) -> EngineResult:
    return AdversarialScanner().scan(doc)
