# -*- coding: utf-8 -*-
"""v0.9.0 eval_v4 평가 데이터셋 정답 매칭 및 정밀 채점 스크립트.

정답지(ground_truth_blind_v4.json)의 결함 항목들과
ACASia_LAW 0.9.0 실행 결과(verification_v090_eval_v4.json)를
다차원 규칙 매칭(태그, 사건번호, 법조문, 날짜, 금액, 텍스트 키워드)으로 대조하여
정확한 적발률, 대조군(D-05) 무결점 여부 및 100점 만점 종합 점수를 산출한다.
"""
from __future__ import annotations

import io
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Windows 콘솔 출력 UTF-8 설정
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def evaluate():
    gt_path = Path(r"C:\Users\mrlee\Downloads\eval_v4\answerkey\ground_truth_blind_v4.json")
    report_path = Path("reports/verification_v090_eval_v4.json")

    if not gt_path.exists():
        print(f"정답지 파일이 존재하지 않습니다: {gt_path}")
        return

    if not report_path.exists():
        print(f"검증 결과 파일이 존재하지 않습니다: {report_path}")
        return

    with open(gt_path, encoding="utf-8") as f:
        gt = json.load(f)

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    print("=" * 75)
    print("ACASia_LAW 0.9.0 (규칙: 2026.09.26.1) eval_v4 정밀 평가 분석")
    print("=" * 75)

    # 1. 문서별 findings 수집
    doc_findings = defaultdict(list)
    for doc in report.get("documents", []):
        doc_id = doc.get("document_id") or ""
        fn = doc.get("filename", "")
        # D-01, D-02 등 prefix 추출
        prefix = doc_id.split("_")[0] if "_" in doc_id else doc_id.split(".")[0]
        if not prefix and fn:
            prefix = fn.split("_")[0] if "_" in fn else fn.split(".")[0]
        for fd in doc.get("findings", []):
            doc_findings[prefix].append(fd)
            if doc_id:
                doc_findings[doc_id].append(fd)

    for fd in report.get("project_findings", []):
        doc_findings["(PROJECT)"].append(fd)

    all_findings_count = sum(len(d.get("findings", [])) for d in report.get("documents", [])) + len(report.get("project_findings", []))
    print(f"생성된 총 Finding 건수: {all_findings_count}건")

    # 2. 정답지 항목별 매칭 평가
    total_gt_items = 0
    hit_items = 0
    miss_items = 0

    eval_details = []
    doc_scores = defaultdict(lambda: {"total": 0, "hit": 0, "miss": 0, "fp": 0})
    tag_stats = defaultdict(lambda: {"hit": 0, "total": 0})

    for doc in gt.get("documents", []):
        doc_id = doc.get("id")
        doc_file = doc.get("file")
        doc_title = doc.get("title")
        items = doc.get("items", [])

        findings = doc_findings.get(doc_id, []) + doc_findings.get("(PROJECT)", [])

        for item in items:
            tag = item[0]
            loc = item[1]
            target_str = item[2]
            desc = item[3]

            # FP-TRAP (오탐 유도 대조군 항목)은 정답지 결함이 아니므로 적발 모수에 포함하지 않음
            if tag == "FP-TRAP":
                continue

            total_gt_items += 1
            doc_scores[doc_id]["total"] += 1
            tag_stats[tag]["total"] += 1

            matched_findings: List[Tuple[int, Dict[str, Any]]] = []

            # 1) 사건번호, 날짜, 금액 등 정규화 패턴
            num_patterns = re.findall(r"\d{2,4}[가-힣]{1,3}\s*\d+|\d{1,3}(?:,\d{3})+|\d{4}\.\s*\d{1,2}\.\s*\d{1,2}", target_str)
            text_keywords = [w for w in re.findall(r"[가-힣A-Za-z0-9_]{2,}", target_str + " " + desc) if len(w) >= 2]

            for f in findings:
                f_type = str(f.get("type", ""))
                f_title = str(f.get("title", ""))
                f_desc = str(f.get("detail", "") or f.get("description", ""))
                f_rule = str(f.get("rule_id", ""))
                f_tags = [str(t) for t in f.get("tags", [])]
                f_snippet = str([e.get("excerpt") for e in f.get("evidence", [])])
                f_full = f"{f_type} {f_title} {f_desc} {f_rule} {' '.join(f_tags)} {f_snippet}".lower()

                match_score = 0

                # A. 태그 / 유형 기반 매칭 점수
                if tag in ["CIT-DATE", "CIT-NO", "CIT-MIS", "CIT-MIS/OVR", "CIT-REV-TIME", "CIT-PRE-EXIST", "CIT-NX"]:
                    if any(k in f_type.lower() for k in ["case", "citation", "court", "not_found", "date", "statute", "holding"]):
                        match_score += 2
                elif tag in ["LAW-MIS", "LAW-NONEXIST", "LAW-SCOPE", "LAW-NX"]:
                    if any(k in f_type.lower() for k in ["law", "provision", "legal_argument", "statute", "nonexistent"]):
                        match_score += 2
                elif tag in ["ARITH", "ARITH-SUM", "AMOUNT-WORDS"]:
                    if any(k in f_type.lower() for k in ["arithmetic", "calculation", "amount_words", "amount", "digit"]):
                        match_score += 3
                elif tag in ["DATE-WEEKDAY", "DAYS", "DATE-INVALID", "DATE-INVERSION", "TEMPORAL"]:
                    if any(k in f_type.lower() for k in ["timeline", "date", "calendar", "weekday", "temporal", "inversion"]):
                        match_score += 2
                elif tag in ["XDOC", "XDOC-DATE", "XDOC-NUM"]:
                    if any(k in f_type.lower() for k in ["cross", "contradiction", "inconsistency", "xdoc"]):
                        match_score += 3
                elif tag.startswith("INJ-") or tag in ["INJECT-PROMPT", "INJECT-WHITE", "ADV-INJ", "ADV-HIDDEN"]:
                    if any(k in f_type.lower() for k in ["instruction", "hidden", "meta", "homoglyph", "white", "clipping", "pdf", "prompt", "injection", "unicode"]):
                        match_score += 3
                elif tag.startswith("AI-") or tag in ["AUTH-AI"]:
                    if any(k in f_type.lower() for k in ["ai", "draft", "residue", "artifact", "author", "generalization"]):
                        match_score += 2
                elif tag.startswith("EVID-") or tag in ["EVID-MIS", "EVID-MISSING", "EVID-NUM-GAP"]:
                    if any(k in f_type.lower() for k in ["evidence", "attachment", "gap", "missing"]):
                        match_score += 2
                elif tag in ["LOGIC", "OVR", "QUOTE-MOD"]:
                    if any(k in f_type.lower() for k in ["legal_argument", "contradiction", "overclaim", "statute_text", "holding", "unsupported_generalization"]):
                        match_score += 2
                elif tag in ["COUNT", "VOTE"]:
                    if any(k in f_type.lower() for k in ["fact_contradiction", "contradiction", "count", "vote", "arithmetic"]):
                        match_score += 3

                # B. 식별자 일치 (사건번호, 날짜, 금액)
                for np in num_patterns:
                    np_clean = re.sub(r"\s+", "", np).lower()
                    if np_clean and np_clean in re.sub(r"\s+", "", f_full):
                        match_score += 4
                        break

                # C. 텍스트 키워드 매칭
                matched_kws = [kw for kw in text_keywords if kw.lower() in f_full]
                if len(matched_kws) >= 2:
                    match_score += 3
                elif len(matched_kws) == 1 and len(matched_kws[0]) >= 3:
                    match_score += 2

                if match_score >= 4:
                    matched_findings.append((match_score, f))

            if matched_findings:
                matched_findings.sort(key=lambda x: x[0], reverse=True)
                best_f = matched_findings[0][1]
                hit_items += 1
                doc_scores[doc_id]["hit"] += 1
                tag_stats[tag]["hit"] += 1
                eval_details.append({
                    "doc": doc_id, "tag": tag, "status": "HIT", "target": target_str, "desc": desc,
                    "finding": best_f
                })
            else:
                miss_items += 1
                doc_scores[doc_id]["miss"] += 1
                eval_details.append({
                    "doc": doc_id, "tag": tag, "status": "MISS", "target": target_str, "desc": desc,
                    "finding": None
                })

    # 3. 대조군 (D-05) 오탐 분석
    d05_findings = doc_findings.get("D-05", [])
    d05_fp = [f for f in d05_findings if f.get("severity") in ["MEDIUM", "HIGH", "CRITICAL"] and not f.get("advisory_only") and f.get("status") in ["CONTRADICTED", "SUSPICIOUS"]]
    doc_scores["D-05"]["fp"] = len(d05_fp)

    # 4. 문서별 결과 출력
    for doc_id in sorted(doc_scores.keys()):
        sc = doc_scores[doc_id]
        if doc_id == "D-05":
            print("-" * 75)
            print(f"[{doc_id} 대조군] 오탐(FP): {sc['fp']}건 -> {'[PASS] 무결점 클린 통과' if sc['fp'] == 0 else '[FAIL] 오탐 발생'}")
            continue
        pct = (sc["hit"] / max(1, sc["total"])) * 100
        print("-" * 75)
        print(f"[{doc_id}] 결함 적발률: {sc['hit']} / {sc['total']} ({pct:.1f}%)")
        doc_details = [d for d in eval_details if d["doc"] == doc_id]
        for d in doc_details:
            st = "[V] 적발" if d["status"] == "HIT" else "[X] 누락"
            target_disp = d["target"][:28] if len(d["target"]) > 28 else d["target"]
            desc_disp = d["desc"][:40] if len(d["desc"]) > 40 else d["desc"]
            print(f"  {st} | [{d['tag']:<12}] {target_disp:<30} -> {desc_disp}")
            if d["finding"]:
                f = d["finding"]
                print(f"        -> Finding: [{f.get('type')}] {f.get('title')[:55]}")

    print("=" * 75)
    recall = (hit_items / max(1, total_gt_items)) * 100
    print(f"전체 정답지 결함 적발률: {hit_items} / {total_gt_items} ({recall:.1f}%)")
    print(f"대조군(D-05) 치명/고위험 오탐: {len(d05_fp)}건")
    print("=" * 75)

    # 5. 100점 만점 종합 채점
    # 결함 적발 점수(최대 85점) + 대조군 무결점 보너스(15점)
    detection_score = (hit_items / max(1, total_gt_items)) * 85.0
    control_score = 15.0 if len(d05_fp) == 0 else 0.0
    final_score = detection_score + control_score

    print("【 최종 종합 평가 결과 】")
    print(f"  1. 결함 적발 정확도 (Detection Accuracy): {detection_score:.1f} / 85.0 점")
    print(f"  2. 정상 대조군 무결점성 (Control Specificity): {control_score:.1f} / 15.0 점")
    print(f"  ★ 종합 점수: {final_score:.1f} / 100.0 점")
    print("=" * 75)

    # 결과 JSON 저장
    out_path = Path("reports/eval_v4_evaluation_summary.json")
    out_data = {
        "version": gt.get("version"),
        "total_gt_items": total_gt_items,
        "hit_items": hit_items,
        "miss_items": miss_items,
        "recall_rate": recall,
        "d05_fp_count": len(d05_fp),
        "final_score": final_score,
        "doc_scores": doc_scores,
        "tag_stats": tag_stats,
    }
    out_path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"평가 요약 리포트 저장 완료: {out_path}")


if __name__ == "__main__":
    evaluate()
