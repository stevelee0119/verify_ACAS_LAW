"""문서 검증 CLI.

서버 없이 파이프라인을 실행하고 보고서를 생성한다.
CI 실행과 폐쇄망 일괄 처리에 사용한다(제23장).

    python scripts/verify_cli.py --input samples --out out \
        --project-name "손해배상 사건" --case-number 2026가합1234 --incident-date 2015-06-01
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.audit_engine import AuditChain  # noqa: E402
from packages.common.config import get_settings  # noqa: E402
from packages.common.enums import ExternalAIPolicy, Severity, VerificationProfile  # noqa: E402
from packages.common.storage import sha256_file  # noqa: E402
from packages.document_engine import ALLOWED_EXTENSIONS  # noqa: E402
from packages.report_engine import (  # noqa: E402
    build_highlight_pdf,
    build_report_pdf,
    to_csv,
    to_json,
    to_manifest,
    to_xlsx,
)
from packages.verification_engine import (  # noqa: E402
    DocumentInput,
    ProjectContext,
    VerificationPipeline,
)

FORMATS = ("pdf", "highlight", "xlsx", "csv", "json", "manifest")


def collect_documents(input_dir: Path) -> List[Path]:
    files = [
        p for p in sorted(input_dir.rglob("*"))
        if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS
    ]
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="법률문서 검증 CLI")
    parser.add_argument("--input", required=True, help="검증할 문서가 있는 디렉터리")
    parser.add_argument("--out", default="out", help="보고서 출력 디렉터리")
    parser.add_argument("--project-name", default="CLI 검증")
    parser.add_argument("--case-number", default=None)
    parser.add_argument("--court", default=None)
    parser.add_argument("--incident-date", default=None, help="사건 발생일 YYYY-MM-DD. 시행법 기준일이 된다")
    parser.add_argument("--profile", default="STANDARD", choices=[p.value for p in VerificationProfile])
    parser.add_argument("--ai-policy", default="MASKED", choices=[p.value for p in ExternalAIPolicy])
    parser.add_argument("--formats", default="pdf,xlsx,csv,json,manifest",
                        help=f"쉼표 구분. 가능: {','.join(FORMATS)}")
    parser.add_argument("--own-documents", action="store_true",
                        help="자기 측 문서로 취급한다(특권 게이트 봉인 경고를 적용하지 않는다)")
    parser.add_argument("--fail-on", default="", choices=["", "CRITICAL", "HIGH", "MEDIUM"],
                        help="이 등급 이상 Finding이 있으면 종료코드 1")
    args = parser.parse_args()

    input_dir = Path(args.input)
    if not input_dir.is_dir():
        print(f"입력 디렉터리가 없다: {input_dir}", file=sys.stderr)
        return 2
    files = collect_documents(input_dir)
    if not files:
        print(f"검증 대상 문서가 없다: {input_dir} (지원 형식 {', '.join(ALLOWED_EXTENSIONS)})", file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    settings = get_settings()

    audit = AuditChain()
    pipeline = VerificationPipeline(audit=audit)
    context = ProjectContext(
        project_id="cli",
        case_number=args.case_number,
        court=args.court,
        case_date=args.incident_date,
        external_ai_policy=ExternalAIPolicy(args.ai_policy),
        profile=VerificationProfile(args.profile),
        counterparty_document=not args.own_documents,
    )
    documents = [
        DocumentInput(
            document_id=f"D{index}",
            path=str(path),
            filename=path.name,
            mime_type="",
            sha256=sha256_file(path),
        )
        for index, path in enumerate(files, start=1)
    ]

    print(f"대상 문서 {len(documents)}건 / 프로파일 {args.profile} / 외부 AI 정책 {args.ai_policy}")
    for document in documents:
        print(f"  - {document.filename}  SHA-256 {document.sha256[:16]}…")

    def progress(state, message, ratio):
        print(f"  [{ratio * 100:5.1f}%] {state} {message}")

    run_id = f"cli_{datetime.utcnow():%Y%m%d%H%M%S}"
    result = pipeline.run(run_id, context, documents, progress=progress)

    # --- 보고서 -----------------------------------------------------------
    manifest = audit.manifest(project_id="cli")
    project = {"name": args.project_name, "case_number": args.case_number, "court": args.court}
    requested = [f.strip() for f in args.formats.split(",") if f.strip()]
    written: Dict[str, str] = {}
    for fmt in requested:
        try:
            if fmt == "json":
                data = to_json(result)
            elif fmt == "csv":
                data = to_csv(result.all_findings)
            elif fmt == "xlsx":
                data = to_xlsx(result)
            elif fmt == "manifest":
                data = to_manifest(audit, "cli", result)
            elif fmt == "pdf":
                data = build_report_pdf(result, project=project, manifest=manifest)
            elif fmt == "highlight":
                source = next((p for p in files if p.suffix.lower() == ".pdf"), None)
                if source is None:
                    continue
                target = next((d for d in result.documents if d.filename == source.name), None)
                data = build_highlight_pdf(source.read_bytes(), target.findings if target else [])
            else:
                print(f"  알 수 없는 형식은 건너뛴다: {fmt}", file=sys.stderr)
                continue
        except Exception as exc:  # 한 형식 실패가 전체를 실패시키지 않는다
            print(f"  {fmt} 생성 실패: {exc}", file=sys.stderr)
            continue
        suffix = {"manifest": "manifest.json", "highlight": "highlight.pdf"}.get(fmt, fmt)
        path = out_dir / f"report.{suffix}"
        path.write_bytes(data)
        written[fmt] = str(path)

    # --- 요약 -------------------------------------------------------------
    counts = result.scores.get("severity_counts", {})
    summary_lines = [
        "",
        f"상태: {result.state}",
        f"Finding: {len(result.all_findings)}건 "
        f"(CRITICAL {counts.get('CRITICAL', 0)} / HIGH {counts.get('HIGH', 0)} / "
        f"MEDIUM {counts.get('MEDIUM', 0)} / LOW {counts.get('LOW', 0)} / INFO {counts.get('INFO', 0)})",
        f"미검증 항목: {len(result.unverified_items)}건",
        f"사용 불가 Source: {', '.join(s['name'] for s in result.unavailable_sources) or '없음'}",
        f"감사추적: {manifest['event_count']}건, 체인 유효={manifest['chain_valid']}",
        "",
        "축별 위험도(하나로 합산하지 않는다):",
    ]
    for axis, value in (result.scores.get("axes") or {}).items():
        summary_lines.append(f"  {axis:32s} {json.dumps(value, ensure_ascii=False)[:110]}")
    summary_lines += ["", "주요 Finding (CRITICAL·HIGH):"]
    severe = [f for f in result.all_findings if f.severity.rank >= Severity.HIGH.rank]
    for finding in sorted(severe, key=lambda f: -f.severity.rank)[:20]:
        summary_lines.append(
            f"  {str(finding.severity):9s} {str(finding.type):28s} "
            f"[{finding.evidence_grade}] {finding.title[:60]}"
        )
    if not severe:
        summary_lines.append("  없음")
    summary_lines += ["", "생성된 보고서:"]
    for fmt, path in written.items():
        summary_lines.append(f"  {fmt:10s} {path} ({Path(path).stat().st_size:,} bytes)")
    summary_lines += [
        "",
        "본 결과는 검증 보조자료이다. 진정성립·위조·고의에 관한 최종 판단은 사용자에게 있다.",
    ]
    summary = "\n".join(summary_lines)
    print(summary)
    (out_dir / "summary.txt").write_text(summary, encoding="utf-8")

    if args.fail_on:
        threshold = Severity(args.fail_on).rank
        hits = [f for f in result.all_findings if f.severity.rank >= threshold]
        if hits:
            print(f"\n{args.fail_on} 이상 Finding {len(hits)}건으로 실패 처리한다.", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
