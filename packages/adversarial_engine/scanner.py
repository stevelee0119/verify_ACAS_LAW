"""제7장 Adversarial Content & Prompt Injection Forensics Engine.

모든 LLM 호출보다 먼저 실행한다(제7장 서문, 제24.3장 Release Gate).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from packages.common.confidence import score as confidence_score
from packages.common.enums import (
    AdversarialClass,
    EvidenceGrade,
    FindingType,
    ForensicLevel,
    MetaMessageType,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import BODY_LAYERS, BBox, Block, EngineResult, Evidence, Finding, NormalizedDocument
from packages.document_engine.reading_text import build_reading_text, join_separator, sentence_bounds

from .classifier import Classification, classify, severity_for
from .cross_layer import compare_layers
from .encoding_scan import decode_candidates
from .normalize import KIND_LABELS, normalize_for_classification
from .unicode_scan import scan_unicode
from .patterns import AI_ADDRESSING_RE

ENGINE_NAME = "adversarial_engine"

MAX_EXCERPT = 300
# 줄 끝에서 끊긴 Base64·16진 토큰(앞 조각 16자 이상)
WRAPPED_TOKEN_RE = re.compile(r"([A-Za-z0-9+/]{16,})[ \t]*\r?\n[ \t]*([A-Za-z0-9+/]+={0,2})(?=\s|$)")


# 지시문이 숨겨진 경로. 경로마다 따로 보고해야 한 경로만 막고 끝내지 않는다.
PATH_LABELS = {
    "VISIBLE_TEXT": "보이는 본문", "WHITE_ON_WHITE": "흰 글자(배경과 같은 색)", "TINY_FONT": "아주 작은 글자",
    "OFF_PAGE": "페이지 밖 좌표", "INVISIBLE_RENDER_MODE": "보이지 않는 렌더모드(Tr 3)",
    "COVERED_BY_SHAPE": "흰 도형으로 덮은 글자", "COVERED_BY_IMAGE": "이미지로 덮은 글자",
    "TRANSPARENT_FILL": "투명 글자(채움 투명도 0)", "LOW_CONTRAST": "배경과 대비가 거의 없는 글자",
    "CLIPPED_OUT": "클리핑 영역 밖 글자", "PAGE_LABEL": "쪽 번호 표시(PageLabels)",
    "OCR_LAYER": "OCR 글자층", "ANNOTATION": "주석",
    "METADATA": "문서 속성(메타데이터)", "ATTACHMENT": "첨부파일 내용", "RUNNING_HEAD": "머리글·바닥글", "OTHER_HIDDEN": "기타 숨김 레이어",
    "OUTLINE": "북마크(개요)", "FORM_FIELD": "양식 필드 값", "ACTUAL_TEXT": "표시 대체 문자열(ActualText)",
    "ENCODED": "인코딩 문자열", **KIND_LABELS,
}


def _path_label(*keys: str) -> str:
    return " · ".join(PATH_LABELS.get(k, k) for k in keys if k)


def _injection_path(block: Block) -> str:
    reason = str(block.attributes.get("hidden_reason") or "")
    for key in ("CLIPPED_OUT", "WHITE_ON_WHITE", "TINY_FONT", "OFF_PAGE", "INVISIBLE_RENDER_MODE", "COVERED_BY_SHAPE",
                "COVERED_BY_IMAGE", "TRANSPARENT_FILL", "LOW_CONTRAST"):
        if reason.startswith(key):
            return key
    if block.source_layer == "ocr_layer":
        return "OCR_LAYER"
    if block.block_type == "comment" or block.source_layer == "annotation":
        return "ANNOTATION"
    if block.block_type == "running_head":
        return "RUNNING_HEAD"
    if block.visible and block.source_layer == "visible_text":
        return "VISIBLE_TEXT"
    return "OTHER_HIDDEN"


def _union_bbox(blocks: List[Block]) -> Optional[BBox]:
    boxes = [b.bbox for b in blocks if b.bbox is not None]
    if not boxes:
        return None
    return BBox(min(b.x0 for b in boxes), min(b.y0 for b in boxes), max(b.x1 for b in boxes), max(b.y1 for b in boxes))


def _passages(doc: NormalizedDocument) -> List[Tuple[str, List[Block]]]:
    """검사 단위. 한 지시문이 여러 줄에 걸쳐도 한 번에 읽는다.

    - 보이는 본문(머리글·바닥글, 표의 줄 포함)은 읽기 본문의 문장 단위
    - 숨은 레이어는 같은 쪽·같은 숨김 경로로 이어진 줄 묶음 단위
    - 표 블록·주석 등 나머지는 블록 단위
    """
    out: List[Tuple[str, List[Block]]] = []
    run: List[Block] = []

    def flush() -> None:
        if run:
            text = ""
            for block in run:
                piece = block.text.strip()
                text = (text + join_separator(text, piece) + piece) if text else piece
            out.append((text, list(run)))
            run.clear()

    visible: List[Block] = []
    for block in doc.blocks:
        if not (block.text or "").strip():
            continue
        if block.visible and block.source_layer in BODY_LAYERS and block.block_type != "table":
            flush()
            visible.append(block)
            continue
        if block.visible or block.block_type in ("table", "comment"):
            flush()
            out.append((block.text, [block]))
            continue
        key = (block.page, block.source_layer, block.attributes.get("hidden_reason"))
        if run and key != (run[-1].page, run[-1].source_layer, run[-1].attributes.get("hidden_reason")):
            flush()
        run.append(block)
    flush()
    reading = build_reading_text(doc, visible)
    for start, end in sentence_bounds(reading.text):
        text = reading.text[start:end].strip()
        if text:
            out.append((text, reading.blocks_between(start, end) or [reading.locate(start)[0]]))
    return out


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
        structural = self._scan_structure(doc)
        findings.extend(structural)
        findings.extend(self._scan_unicode(doc, actual_text_flagged=any(
            f.confidence_features.get("injection_path") == "ACTUAL_TEXT" for f in structural)))
        findings.extend(self._scan_encoding(doc))
        findings.extend(self._scan_cross_layer(doc))
        findings.extend(self._scan_multimodal(doc))
        findings.extend(self._scan_attachments(doc))

        result.findings = findings
        result.data["adversarial_risk"] = self.risk_level(findings)
        paths = self.scanned_paths(doc)
        result.data["scanned_layers"] = sorted(paths)
        result.data["scanned_paths"] = paths
        result.data["injection_candidate_count"] = len(findings)
        return result

    @staticmethod
    def scanned_paths(doc: NormalizedDocument) -> Dict[str, int]:
        """실제로 분류기에 넣은 경로와 그 건수. 비어 있는 경로는 적지 않는다(검사했다고 오해하지 않도록)."""
        paths: Dict[str, int] = {}
        for block in doc.blocks:
            if (block.text or "").strip():
                paths[block.source_layer] = paths.get(block.source_layer, 0) + 1
        structure = doc.structure
        extra = {
            "metadata": sum(1 for v in doc.metadata.values() if str(v).strip()),
            "outline": len(structure.get("outline") or []),
            "page_labels": len(structure.get("page_labels") or []),
            "form_field": len(structure.get("form_fields") or []),
            "attachment": sum(1 for e in structure.get("embedded_files") or [] if (e.get("text") or "").strip()),
            "actual_text": len(structure.get("actual_text_strings") or []),
            "image_ocr": sum(1 for b in doc.blocks if b.source_layer == "ocr_layer")
                         + (1 if (doc.raw_layers.get("independent_ocr") or "").strip() else 0),
            "encoded_text": sum(1 for t in doc.raw_layers.values() if t),
        }
        paths.update({k: v for k, v in extra.items() if v})
        return paths
    # -- 레이어별 검사 ----------------------------------------------------
    def _scan_blocks(self, doc: NormalizedDocument) -> List[Finding]:
        out: List[Finding] = []
        for text, blocks in _passages(doc):
            block = blocks[0]
            # 전각·폭 0·자모 분리로 숨긴 지시문은 되돌린 글자로 분류한다. 원문은 그대로 남긴다.
            normalized, kinds = normalize_for_classification(text)
            classification = classify(
                normalized,
                source_layer=block.source_layer,
                visible=block.visible,
                hidden_reason=block.attributes.get("hidden_reason"),
                block_type=block.block_type,
            )
            if classification.label == AdversarialClass.BENIGN_CONTENT:
                continue
            in_ocr = block.source_layer == "ocr_layer"
            descriptive = bool(classification.features.get("descriptive_mention"))
            finding_type = self._finding_type_for_block(block, classification)
            severity = severity_for(classification, in_ocr_layer=in_ocr)
            bbox = _union_bbox(blocks)
            # 보이는 본문이라도 AI·검토 도구를 수신자로 검증 생략·결과 조작·보고 억제를 요구하면 B 이상(v3 D9)
            machine_directed = (block.visible and not descriptive and bool(AI_ADDRESSING_RE.search(text))
                                and bool({str(i) for i in classification.intents}
                                         & {"VERIFICATION_SUPPRESSION", "OUTPUT_MANIPULATION"}))
            grade = EvidenceGrade.A if not block.visible else EvidenceGrade.B if machine_directed else EvidenceGrade.C
            features = {
                "deterministic_rule": True,
                "cross_layer_mismatch": not block.visible,
                "forensic_signal": classification.features.get("corroborating_signals", 0),
                **classification.features,
                # 원문(OCR 포함)과 위치를 그대로 남긴다. 요약 발췌만으로는 판단을 되짚을 수 없다.
                "observed_text": text[:2000],
                "block_ids": [b.block_id for b in blocks],
                "hidden_reason": block.attributes.get("hidden_reason"),
                "injection_path": kinds[0] if kinds else _injection_path(block),
                "physical_path": _injection_path(block),
                "obfuscation": kinds,
                "normalized_text": normalized[:2000] if kinds else None,
                "bbox": bbox.as_tuple() if bbox else None,
                "machine_directed_suppression": machine_directed,
            }
            out.append(
                Finding.create(
                    type=finding_type,
                    status=VerificationStatus.SUSPICIOUS,
                    severity=severity,
                    evidence_grade=grade,
                    title=("지시문을 주제로 설명·언급하는 문구 (명령 아님)" if descriptive
                           else self._title_for(finding_type, classification, block, kinds)),
                    detail=self._detail_for(block, classification),
                    advisory_only=descriptive,
                    confidence=confidence_score(features),
                    confidence_features=features,
                    document_id=doc.document_id,
                    block_id=block.block_id,
                    page=block.page,
                    bbox=bbox,
                    engine=ENGINE_NAME,
                    meta_message_type=MetaMessageType.MM1_MACHINE_INSTRUCTION,
                    adversarial_class=classification.label,
                    forensic_level=self._forensic_level(classification),
                    tags=[str(i) for i in classification.intents] + [_injection_path(block)] + kinds,
                    evidence=[
                        Evidence.create(
                            description=f"{block.source_layer} 레이어에서 관찰된 지시형 문자열",
                            grade=grade,
                            document_id=doc.document_id,
                            block_id=block.block_id,
                            page=block.page,
                            excerpt=_excerpt(text),
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
    def _title_for(finding_type: FindingType, classification: Classification, block: Optional[Block] = None,
                   kinds: Optional[List[str]] = None) -> str:
        intents = ", ".join(str(i) for i in classification.intents) or "UNSPECIFIED"
        if kinds:  # 은닉 방법이 경로다. 화면에 보이는 글자라도 '보이는 본문'과 따로 센다.
            path = _path_label(*kinds) + (" · 화면 표시 글자" if block is not None and block.visible else "")
        else:
            path = PATH_LABELS.get(_injection_path(block)) if block is not None else None
        return f"{finding_type} 후보: {intents}" + (f" — 경로: {path}" if path else "")

    @staticmethod
    def _detail_for(block: Block, classification: Classification) -> str:
        reason = block.attributes.get("hidden_reason")
        where = f"{block.source_layer}" + (f"/{reason}" if reason else "")
        if classification.features.get("descriptive_mention"):
            return (
                f"{where} 위치의 문구가 지시형 낱말을 포함하지만 명령형 어미 없이 표제·명사구·설명 문맥으로 "
                "쓰였다. 지시문이나 공격 기법을 설명하는 문구로 보고 참고 표시만 한다. "
                "본 문자열은 자료로만 취급되며 시스템 지침이나 Tool 권한을 변경하지 않는다."
            )
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
            normalized, kinds = normalize_for_classification(text)
            classification = classify(normalized, source_layer="metadata", visible=False, block_type="metadata")
            if classification.label in (AdversarialClass.BENIGN_CONTENT, AdversarialClass.INSTRUCTION_LIKE):
                continue
            features = {"deterministic_rule": True, "cross_layer_mismatch": True, **classification.features,
                        "injection_path": "METADATA", "metadata_key": key, "obfuscation": kinds}
            out.append(
                Finding.create(
                    type=FindingType.METADATA_INJECTION,
                    status=VerificationStatus.SUSPICIOUS,
                    severity=severity_for(classification),
                    evidence_grade=EvidenceGrade.A,
                    title=f"문서 속성 '{key}'에 지시형 문자열이 있다 — 경로: {_path_label('METADATA', *kinds)}",
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
                    tags=[str(i) for i in classification.intents] + ["METADATA"] + kinds,
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

    def _scan_structure(self, doc: NormalizedDocument) -> List[Finding]:
        """북마크·양식 필드·ActualText. 화면 본문에 없지만 추출기·모델이 읽는 글자다(v4 P7)."""
        out: List[Finding] = []
        titles = [str(o.get("title") or "") for o in doc.structure.get("outline") or []]
        entries = [("OUTLINE", "outline", title, None) for title in titles]
        if len(titles) > 1:
            # 지시문을 여러 북마크 제목에 나눠 넣어도 뷰어·추출기는 이어서 읽는다(v5 3-7). 이어 붙인 글도 분류기에 넣는다.
            entries.append(("OUTLINE", "outline", " ".join(t.strip() for t in titles if t.strip()), "북마크 제목 이어 읽기"))
        entries += [("PAGE_LABEL", "page_label", str(t), None) for t in doc.structure.get("page_labels") or []]
        entries += [("FORM_FIELD", "form_field", str(f.get("value") or ""), f.get("name"))
                    for f in doc.structure.get("form_fields") or []]
        entries += [("ACTUAL_TEXT", "actual_text", str(t), None) for t in doc.structure.get("actual_text_strings") or []]
        flagged_paths: set = set()
        for path, layer, text, name in entries:
            if len(text.strip()) < 6:
                continue
            if name == "북마크 제목 이어 읽기" and "OUTLINE" in flagged_paths:
                continue  # 제목 하나로 이미 보고했다
            normalized, kinds = normalize_for_classification(text)
            classification = classify(normalized, source_layer=layer, visible=False, block_type="metadata")
            if classification.label in (AdversarialClass.BENIGN_CONTENT, AdversarialClass.INSTRUCTION_LIKE):
                continue
            flagged_paths.add(path)
            label = _path_label(path, *kinds)
            features = {"deterministic_rule": True, "cross_layer_mismatch": True, **classification.features,
                        "observed_text": text[:2000], "normalized_text": normalized[:2000] if kinds else None,
                        "injection_path": path, "obfuscation": kinds, "field_name": name}
            out.append(Finding.create(
                type=FindingType.HIDDEN_INSTRUCTION, status=VerificationStatus.SUSPICIOUS,
                severity=severity_for(classification), evidence_grade=EvidenceGrade.A,
                title=(f"HIDDEN_INSTRUCTION 후보: {', '.join(str(i) for i in classification.intents) or 'UNSPECIFIED'}"
                       f" — 경로: {label}"),
                detail=(f"{label}{f' ({name})' if name else ''}에서 지시형 문자열이 관찰되었다. 이 글자는 화면 본문에 "
                        f"나타나지 않지만 텍스트 추출기와 모델 입력에 들어갈 수 있다. 분류={classification.label}. "
                        "본 문자열은 자료로만 취급되며 시스템 지침이나 Tool 권한을 변경하지 않는다."),
                confidence=confidence_score(features), confidence_features=features,
                document_id=doc.document_id, engine=ENGINE_NAME,
                meta_message_type=MetaMessageType.MM1_MACHINE_INSTRUCTION,
                adversarial_class=classification.label, forensic_level=self._forensic_level(classification),
                tags=[str(i) for i in classification.intents] + [path] + kinds,
                evidence=[Evidence.create(description=label, grade=EvidenceGrade.A,
                                          document_id=doc.document_id, excerpt=_excerpt(text))],
            ))
        return out

    def _scan_unicode(self, doc: NormalizedDocument, actual_text_flagged: bool = False) -> List[Finding]:
        out: List[Finding] = []
        hidden_marks = doc.structure.get("actual_text_zero_width") or {}
        if hidden_marks and not actual_text_flagged:  # 지시문으로 이미 보고했으면 신호만 따로 세지 않는다
            listed = ", ".join(f"{k} {v}회" for k, v in hidden_marks.items())
            features = {"deterministic_rule": True, "forensic_signal": 1, "unicode_kind": "ZERO_WIDTH",
                        "layer": "actual_text", "code_points": hidden_marks, "injection_path": "ZERO_WIDTH"}
            out.append(Finding.create(
                type=FindingType.UNICODE_SMUGGLING, status=VerificationStatus.SUSPICIOUS, severity=Severity.MEDIUM,
                evidence_grade=EvidenceGrade.A,
                title=f"Unicode 은닉 신호: 폭 0 문자(zero-width) — {listed}",
                detail=("PDF의 표시 대체 문자열(ActualText)에 화면에 보이지 않는 폭 0 문자가 들어 있다. 글자 사이에 넣어 "
                        "지시문을 키워드 검사에서 숨기는 데 쓰인다. 본 문자열은 자료로만 취급된다."),
                confidence=0.85, confidence_features=features, document_id=doc.document_id, engine=ENGINE_NAME,
                meta_message_type=MetaMessageType.MM1_MACHINE_INSTRUCTION, forensic_level=ForensicLevel.NOTABLE,
                tags=["ZERO_WIDTH"]))
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
                        title=f"Unicode 은닉 신호: {signal.kind}" + (f" — {signal.detail}" if signal.kind == "ZERO_WIDTH" else ""),
                        detail=f"{layer_name} 레이어. {signal.detail}"
                        + (" 복원된 문자열에 지시형 표현이 있다." if hidden_instruction else ""),
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
            # 줄바꿈으로 끊긴 인코딩 문자열도 이어서 디코드한다(끊긴 그대로도 따로 본다).
            joined = WRAPPED_TOKEN_RE.sub(r"\1\2", text)
            segments = decode_candidates(text) + (decode_candidates(joined) if joined != text else [])
            for segment in segments:
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
                    "injection_path": "ENCODED",
                    "layer": layer_name,
                }
                out.append(
                    Finding.create(
                        type=FindingType.ENCODED_INSTRUCTION,
                        status=VerificationStatus.SUSPICIOUS,
                        severity=Severity.HIGH
                        if classification.label == AdversarialClass.PROMPT_INJECTION_LIKELY
                        else Severity.MEDIUM,
                        evidence_grade=EvidenceGrade.A,
                        title=f"{segment.encoding} 인코딩된 지시형 문자열 — 경로: {_path_label('ENCODED')}({segment.encoding})",
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
    def _scan_attachments(self, doc: NormalizedDocument) -> List[Finding]:
        """첨부파일(글자 파일) 내용의 지시문. 본문에 보이지 않으므로 숨은 레이어로 본다."""
        out: List[Finding] = []
        for entry in doc.structure.get("embedded_files") or []:
            text = entry.get("text") or ""
            if not text.strip():
                continue
            classification = classify(text, source_layer="attachment", visible=False, block_type="attachment")
            if classification.label == AdversarialClass.BENIGN_CONTENT:
                continue
            features = {"deterministic_rule": True, "cross_layer_mismatch": True, **classification.features,
                        "observed_text": text[:2000], "attachment_name": entry.get("name"),
                        "attachment_sha256": entry.get("sha256"), "injection_path": "ATTACHMENT"}
            out.append(Finding.create(
                type=FindingType.HIDDEN_INSTRUCTION, status=VerificationStatus.SUSPICIOUS,
                severity=severity_for(classification), evidence_grade=EvidenceGrade.A,
                title=f"첨부파일 '{entry.get('name')}' 안에 지시형 문자열이 있다 — 경로: 첨부파일 내용",
                detail=("본문에 보이지 않는 첨부파일 내용에서 지시형 문자열이 관찰되었다. "
                        f"분류={classification.label}. 본 문자열은 자료로만 취급되며 시스템 지침이나 Tool 권한을 변경하지 않는다."),
                confidence=confidence_score(features), confidence_features=features,
                document_id=doc.document_id, engine=ENGINE_NAME,
                meta_message_type=MetaMessageType.MM1_MACHINE_INSTRUCTION,
                adversarial_class=classification.label, forensic_level=self._forensic_level(classification),
                tags=[str(i) for i in classification.intents] + ["ATTACHMENT"],
                evidence=[Evidence.create(description=f"첨부파일 {entry.get('name')} 내용", grade=EvidenceGrade.A,
                                          document_id=doc.document_id, excerpt=_excerpt(text))],
            ))
        return out

    @staticmethod
    def risk_level(findings: List[Finding]) -> str:
        """제19.1장 Adversarial Manipulation Risk."""
        # 지시문을 설명하는 문구(참고 표시)는 공격 위험 수준에 넣지 않는다.
        findings = [f for f in findings if not (f.advisory_only and f.severity == Severity.INFO)]
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
