"""Public synthetic baseline diagnostic; no PDF or retired asset is used."""
from packages.claim_engine.evidence_consistency import check_exhibits
from packages.common.schemas import Block, NormalizedDocument, Page


CASES = [
    ("same_base", False, ["갑 제1호증: 장치대장, 부록 4쪽.", "갑 제1호증 장치대장: 교체 시점을 설명합니다."], False),
    ("same_branch", False, ["을 제2호증의 1: 배선도, 도면 6쪽.", "을 제2호증의 1 배선도: 접속 경로를 보여줍니다."], False),
    ("same_section", True, ["병 제3호증: 출입기록, 첨부 8쪽.", "병 제3호증 출입기록: 방문 순서를 확인합니다."], False),
    ("different_colon", False, ["갑 제1호증 관측: 동쪽", "갑 제1호증 관측: 서쪽"], True),
    ("different_comma", True, ["을 제2호증 집계, 봄철", "을 제2호증 집계, 겨울철"], True),
    ("different_branch", False, ["병 제3호증의 1 운영지침", "병 제3호증의 1 순찰일지"], True),
]


def document(lines, section=False):
    text = "\n".join((["입증방법"] if section else []) + lines)
    return NormalizedDocument(document_id="synthetic", filename="synthetic.txt", mime_type="text/plain",
                              sha256="0" * 64, pages=[Page(page_number=1, blocks=[Block("b1", text, 1)])])


def main():
    mismatches = 0
    for label, section, lines, expected in CASES:
        findings = [f for f in check_exhibits(document(lines, section))
                    if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_NUMBER_DUPLICATE"]
        observed = bool(findings)
        mismatches += observed != expected
        print(f"{label}: expected_duplicate={expected}, observed_duplicate={observed}, count={len(findings)}")
    print(f"Public synthetic diagnostic: {mismatches}/{len(CASES)} mismatches")


if __name__ == "__main__":
    main()
