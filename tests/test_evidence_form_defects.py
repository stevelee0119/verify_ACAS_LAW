"""서증 형식 결함(EVI-FORM) 검출 및 오탐 방지 시험.

민사소송법 제277조, 제355조 제1항, 제358조 및 민사소송규칙 제121·122조에 따른
서증 형식 요건 흠결(외국어 원본 미첨부, 사문서 서명란 공란, 음성 녹음 데이터 흠결,
사본 중요부분 잘림, 미제출 서증 참조)에 대한 진입점 및 단위 검증을 수행한다.
"""
import timeit
import gc
import pytest
from pathlib import Path

from packages.common.enums import FindingType, VerificationStatus, EvidenceGrade
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.claim_engine.evidence_consistency import (
    check_evidence_form_defects,
    EVI_FORM_TRANSLATION_RE,
    EVI_FORM_SIGNATURE_RE,
    EVI_FORM_AUDIO_RE,
    EVI_FORM_TRUNCATION_RE,
    EVI_FORM_MISSING_REF_RE,
)
from packages.verification_engine.pipeline import (
    DocumentInput,
    ProjectContext,
    VerificationPipeline,
)
from packages.pii_engine import PseudonymStore


def _make_doc(text_paragraphs, doc_id="TEST-FORM-01"):
    """시험용 NormalizedDocument 생성 헬퍼."""
    blocks = []
    for idx, text in enumerate(text_paragraphs):
        blocks.append(Block(
            block_id=f"b_{idx}",
            page=1,
            block_type="paragraph",
            text=text,
            source_layer="visible_text",
            visible=True,
        ))
    return NormalizedDocument(
        document_id=doc_id,
        filename=f"{doc_id}.pdf",
        mime_type="application/pdf",
        sha256="0" * 64,
        pages=[Page(page_number=1, blocks=blocks)],
    )


# === 1. 실제 파이프라인 진입점 시험 ===
def test_pipeline_entrypoint_evidence_form_defects(monkeypatch, tmp_path):
    """실제 VerificationPipeline 진입점을 통한 서증 형식 결함 검출 검증 (점검표 1항)."""
    from packages.verification_engine import pipeline as pipeline_module

    doc = _make_doc([
        "준비서면",
        "5. 물품대금 정산 및 확인",
        "갑 제101호증 물품대금 1차 번역문만 제출한다.",
        "외국어 원본은 첨부하지 않았다.",
        "6. 물품대금 자료 검토",
        "갑 제102호증 물품대금 2차 확인서 서명 누락 상태이나 서명된 것으로 제출한다.",
        "내용: 봉투 수령. 작성자: (공란). 서명: (공란).",
    ], doc_id="entry_form_doc")

    monkeypatch.setattr(pipeline_module, "parse_document", lambda path, **kw: doc)
    monkeypatch.setattr(pipeline_module, "PseudonymStore", lambda project_id, **kw: PseudonymStore(project_id, root=tmp_path))

    pipeline = VerificationPipeline()
    result = pipeline.run(
        "run-entry-form-test",
        ProjectContext("proj-form-test"),
        [DocumentInput("entry_form_doc", "dummy.pdf", "dummy.pdf")],
    )

    doc_result = result.documents[0]
    form_findings = [f for f in doc_result.findings if f.type == FindingType.EVIDENCE_FORM_DEFECT.value]

    # 두 결함 모두 검출되어야 함
    assert len(form_findings) == 2, f"기대 2건, 실측 {len(form_findings)}건"

    # 1) 번역문 단독 제출 결함 확인
    f1 = next((f for f in form_findings if "번역문" in f.title), None)
    assert f1 is not None
    assert f1.status == VerificationStatus.CONTRADICTED.value
    assert f1.evidence_grade == EvidenceGrade.B.value
    assert "갑 제101호증" in f1.title
    assert "물품대금 1차" in f1.evidence[0].excerpt

    # 2) 사문서 서명 공란 결함 확인
    f2 = next((f for f in form_findings if "서명" in f.title), None)
    assert f2 is not None
    assert f2.status == VerificationStatus.CONTRADICTED.value
    assert f2.evidence_grade == EvidenceGrade.B.value
    assert "갑 제102호증" in f2.title
    assert "물품대금 2차" in f2.evidence[0].excerpt


# === 2. 양성 예시 3건 시험 ===
def test_positive_translation_defect():
    """양성 1: 외국어 번역문 단독 제출 및 원본 미첨부 흠결 검출."""
    doc = _make_doc([
        "5. 계약체결 정산 및 확인",
        "갑 제201호증 계약체결 1차 번역문만 제출한다.",
        "이 자료는 외국어 계약서이나 외국어 원본은 첨부하지 아니하였다.",
    ])
    findings = check_evidence_form_defects(doc)
    assert len(findings) == 1
    assert findings[0].type == FindingType.EVIDENCE_FORM_DEFECT
    assert findings[0].status == VerificationStatus.CONTRADICTED
    assert "외국어 원본 미첨부" in findings[0].title
    assert "갑 제201호증" in findings[0].title


def test_positive_signature_blank_defect():
    """양성 2: 확인서 사문서 서명 및 작성자 공란 누락 흠결 검출."""
    doc = _make_doc([
        "5. 배송확인 정산 및 확인",
        "갑 제202호증 배송확인 1차 확인서 사본을 제출한다.",
        "확인서 본문 내용: 물품 인수 완료. 작성자: (공란). 서명: (공란). 서명 누락 상태이다.",
    ])
    findings = check_evidence_form_defects(doc)
    assert len(findings) == 1
    assert findings[0].type == FindingType.EVIDENCE_FORM_DEFECT
    assert findings[0].status == VerificationStatus.CONTRADICTED
    assert "서명 누락" in findings[0].title or "서명" in findings[0].title


def test_positive_truncation_and_audio_defects():
    """양성 3: 사본 하단 잘림 및 음성 소리데이터 미제출 흠결 검출."""
    doc = _make_doc([
        "5. 영수증 정산 및 확인",
        "갑 제203호증 영수증 1차 사본을 제출한다.",
        "복사 범위: 상호, 일자. 사본의 하단이 잘려 합계 및 발행인 부분은 복사 범위 밖이다.",
        "6. 녹음자료 자료 검토",
        "갑 제204호증 통화녹음 2차 녹음원본을 제출한다.",
        "포함 자료: 이 요약문 1매뿐 소리 데이터나 녹취 전문은 포함하지 않았다.",
    ])
    findings = check_evidence_form_defects(doc)
    assert len(findings) == 2
    titles = [f.title for f in findings]
    assert any("사본 중요 기재사항" in t for t in titles)
    assert any("소리데이터 및 녹취록 미제출" in t for t in titles)


# === 3. 대조군 3건 시험 (오탐 방지) ===
def test_control_normal_exhibits_with_originals():
    """대조군 1: 외국어 원본과 번역문이 모두 정상 제출된 경우 오탐 0건."""
    doc = _make_doc([
        "5. 해외계약 정산 및 확인",
        "갑 제301호증 해외계약 1차 원본 및 번역문을 첨부하여 제출한다.",
        "영문 원본 1부와 공증된 한국어 번역문 1부를 모두 제출 완료하였습니다.",
    ])
    findings = check_evidence_form_defects(doc)
    assert len(findings) == 0


def test_control_signed_statement():
    """대조군 2: 작성자와 서명이 온전히 완료된 진술서 오탐 0건."""
    doc = _make_doc([
        "5. 현장확인 정산 및 확인",
        "갑 제302호증 현장확인 1차 확인서를 제출한다.",
        "작성자 김철수가 본인의 서명 날인을 마친 온전한 원본입니다.",
    ])
    findings = check_evidence_form_defects(doc)
    assert len(findings) == 0


def test_control_pleading_electronic_signature_omitted():
    """대조군 3: 본안 소송서류 말미의 전자소송 서명 생략 문맥 오탐 0건."""
    doc = _make_doc([
        "이 사건 청구원인에 관하여 위와 같이 변론합니다.",
        "2026. 1. 15.",
        "원고 여도겸 (서명 생략)",
        "해솔지방법원 귀중",
    ])
    findings = check_evidence_form_defects(doc)
    assert len(findings) == 0


# === 4. 정규식 성능비 검증 시험 (점검표 2항) ===
@pytest.mark.parametrize("name,pattern", [
    ("TRANSLATION", EVI_FORM_TRANSLATION_RE),
    ("SIGNATURE", EVI_FORM_SIGNATURE_RE),
    ("AUDIO", EVI_FORM_AUDIO_RE),
    ("TRUNCATION", EVI_FORM_TRUNCATION_RE),
    ("MISSING_REF", EVI_FORM_MISSING_REF_RE),
])
def test_regex_performance_ratios(name, pattern):
    """정규식 성능비 (< 8.0, 4배 < 1.0초) 검증."""
    base_text = (
        "갑 제101호증에 관하여 번역문만 단독 제출하고 외국어 원본은 첨부하지 않았다.\n"
        "확인서 작성자: (공란). 서명: (공란) 누락 상태이다.\n"
        "포함 자료: 이 요약문 1매뿐 소리 데이터나 녹취 전문은 포함하지 않았다.\n"
        "영수증 사본의 하단이 잘려 합계 및 발행인은 복사 범위 밖이다.\n"
        "완결 제출목록: 갑 제1호증. 이 둘 외에는 자료를 제출하지 않았다.\n"
    ) * 10

    text_1x = base_text
    text_4x = base_text * 4

    gc_was_enabled = gc.isenabled()
    try:
        gc.disable()
        t1_raw = min(timeit.repeat(lambda: list(pattern.finditer(text_1x)), number=100, repeat=3)) / 100
        t4_raw = min(timeit.repeat(lambda: list(pattern.finditer(text_4x)), number=100, repeat=3)) / 100
    finally:
        if gc_was_enabled:
            gc.enable()

    t1_adj = max(t1_raw, 0.0001)
    ratio = t4_raw / t1_adj

    assert ratio < 8.0, f"정규식 {name} 성능비 {ratio:.2f} >= 8.0"
    assert t4_raw < 1.0, f"정규식 {name} 4배 시간 {t4_raw:.4f}s >= 1.0s"
