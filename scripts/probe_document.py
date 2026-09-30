"""문서 점검(probe): 명세(JSON)에 적은 정답 항목을 현재 코드가 얼마나 잡는지 센다(평가 에이전트 소관, 보호 경로).

새 서면을 받으면 **고치기 전 코드로** 먼저 `record`를 실행해 첫 점수(first-touch)를 남긴다.
고친 뒤의 점수는 일반화 근거가 아니다. 첫 점수의 추이가 '처음 보는 문서에서도 나아지는가'에 대한 답이다.

    python scripts/probe_document.py run    --spec tests/fixtures/probes/case6_military_secret.json
    python scripts/probe_document.py run    --spec ... --text            # PDF 파서를 거치지 않는 텍스트 입력(원문 텍스트를 spec.text_input에서 읽음)
    python scripts/probe_document.py record --spec ... --note "서면6 수신 직후"      # docs/scorecards/first_touch_log.jsonl에 한 줄 추가
    python scripts/probe_document.py record --spec ... --sha aa93276 --note "수정 전 상태로 소급 측정"

명세 항목(kind)
- text_contains : 읽은 본문(공백 제거)에 value가 있다
- citation      : 인용 추출 결과에 있다(case_number | law_contains + article | raw_contains)
- masked        : 개인정보 마스킹 뒤 본문(공백 제거)에 value가 남아 있지 않다
- finding       : 조건에 맞는 finding이 있다(types, min_severity, statuses, text_all[정규식 목록, 모두], text_any)
- no_finding    : 조건에 맞는 finding이 없다(오탐 점검)

측정 조건은 오프라인(네트워크 끔)이다. AI 작성 판별·공식 DB 대조·Drive 대조는 재지 못한다.
"""
from __future__ import annotations

import argparse
import dataclasses
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "docs" / "scorecards" / "first_touch_log.jsonl"
KINDS = {"text_contains", "citation", "masked", "finding", "no_finding"}
SEVERITY = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
PRODUCT_PATHS = ("packages", "apps", "workers", "config")


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def load_spec(path: Path) -> Dict[str, Any]:
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    ids = [c["id"] for c in spec["checks"]]
    if len(ids) != len(set(ids)):
        raise ValueError("명세의 항목 id가 겹친다")
    for check in spec["checks"]:
        if check["kind"] not in KINDS:
            raise ValueError(f"알 수 없는 kind: {check['kind']}")
    return spec


def _enum(value: Any) -> str:
    return str(getattr(value, "value", value))


def observe(tree: Path, document: Path, mime: str) -> Dict[str, Any]:
    """`tree`(저장소 루트 또는 과거 커밋의 작업 폴더)의 코드로 문서를 처리해 점검에 필요한 관찰값을 모은다."""
    os.environ["LV_ALLOW_NETWORK"] = "0"
    os.environ.setdefault("LV_DATA_DIR", tempfile.mkdtemp(prefix="probe_"))
    sys.path.insert(0, str(tree))
    obs: Dict[str, Any] = {"errors": []}
    doc = None
    try:
        from packages.document_engine.registry import parse_document
        doc = parse_document(str(document), document_id="probe", filename=document.name, mime_type=mime, sha256="x")
        obs["text"] = "\n".join(b.text for p in doc.pages for b in p.blocks)
    except Exception as exc:  # 과거 커밋은 API가 다를 수 있다. 실패는 점검 실패로 센다.
        obs["errors"].append(f"parse: {exc!r}"[:200])
        obs["text"] = ""
    try:
        from packages.legal_engine.citation_extractor import extract_citations
        obs["citations"] = [{"raw": str(getattr(c, "raw_text", "") or ""), "law": str(getattr(c, "law_name", "") or ""),
                             "article": str(getattr(c, "article", "") or "")} for c in extract_citations(doc)]
    except Exception as exc:
        obs["errors"].append(f"citations: {exc!r}"[:200])
        obs["citations"] = []
    try:
        from packages.pii_engine import PIIEngine, PseudonymStore
        store = PseudonymStore("probe", root=Path(tempfile.mkdtemp(prefix="probe_pii_")))
        masked = PIIEngine(store).mask_document(doc)
        obs["masked_text"] = "\n".join(b["text"] for b in masked.blocks)
    except Exception as exc:
        obs["errors"].append(f"pii: {exc!r}"[:200])
        obs["masked_text"] = obs["text"]      # 마스킹하지 못했으면 원문이 그대로 남은 것으로 본다
    try:
        from packages.common.storage import sha256_file
        from packages.verification_engine import DocumentInput, ProjectContext, VerificationPipeline
        try:
            from packages.audit_engine import AuditChain
        except Exception:
            AuditChain = None
        params = set(inspect.signature(DocumentInput).parameters)
        raw = dict(document_id="probe", path=str(document), filename=document.name, mime_type=mime,
                   sha256=sha256_file(document))
        item = DocumentInput(**{k: v for k, v in raw.items() if k in params})
        init = set(inspect.signature(VerificationPipeline.__init__).parameters)
        pipeline = VerificationPipeline(**({"audit": AuditChain()} if ("audit" in init and AuditChain) else {}))
        result = pipeline.run("probe_" + datetime.now(timezone.utc).strftime("%H%M%S%f"),
                              ProjectContext(project_id="probe"), [item])
        findings = []
        for f in result.documents[0].findings:
            row = f.to_dict() if hasattr(f, "to_dict") else json.loads(json.dumps(dataclasses.asdict(f), default=str))
            findings.append({"type": _enum(row.get("type")), "severity": _enum(row.get("severity")),
                             "status": _enum(row.get("status")), "text": json.dumps(row, ensure_ascii=False, default=str)})
        obs["findings"] = findings
    except Exception as exc:
        obs["errors"].append(f"pipeline: {exc!r}"[:200])
        obs["findings"] = []
    return obs


def _finding_matches(finding: Dict[str, str], check: Dict[str, Any]) -> bool:
    if check.get("types") and finding["type"] not in check["types"]:
        return False
    if check.get("statuses") and finding["status"] not in check["statuses"]:
        return False
    minimum = check.get("min_severity")
    if minimum and SEVERITY.index(finding["severity"]) < SEVERITY.index(minimum):
        return False
    text = finding["text"]
    if any(not re.search(pattern, text) for pattern in check.get("text_all", [])):
        return False
    any_of = check.get("text_any")
    return not any_of or any(re.search(pattern, text) for pattern in any_of)


def evaluate(spec: Dict[str, Any], obs: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    text, masked = compact(obs.get("text", "")), compact(obs.get("masked_text", ""))
    for check in spec["checks"]:
        kind = check["kind"]
        if kind == "text_contains":
            passed = compact(check["value"]) in text
        elif kind == "masked":
            passed = bool(text) and compact(check["value"]) not in masked
        elif kind == "citation":
            passed = any(
                (check.get("case_number") and compact(check["case_number"]) in compact(c["raw"]))
                or (check.get("raw_contains") and check["raw_contains"] in c["raw"])
                or (check.get("law_contains") and check["law_contains"] in (c["law"] + c["raw"])
                    and (not check.get("article") or c["article"] == check["article"]))
                for c in obs.get("citations", []))
        elif kind == "finding":
            passed = any(_finding_matches(f, check) for f in obs.get("findings", []))
        else:  # no_finding
            passed = not any(_finding_matches(f, check) for f in obs.get("findings", []))
        rows.append({"id": check["id"], "label": check.get("label", check["id"]), "passed": bool(passed)})
    return rows


def run_in_tree(spec: Dict[str, Any], tree: Path, *, text_input: bool, spec_dir: Path) -> Dict[str, Any]:
    source = spec["text_input"] if text_input else spec["input"]
    document = (spec_dir / source).resolve() if not Path(source).is_absolute() else Path(source)
    mime = "text/plain" if document.suffix.lower() == ".txt" else "application/pdf"
    if not document.is_file():
        raise FileNotFoundError(document)
    obs = observe(tree, document, mime)
    rows = evaluate(spec, obs)
    return {"spec": spec["name"], "input": "text" if text_input else "pdf", "passed": sum(r["passed"] for r in rows),
            "total": len(rows), "failed": [r["id"] for r in rows if not r["passed"]], "rows": rows,
            "errors": obs["errors"]}


def git(*args: str, cwd: Path = ROOT) -> str:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def measure(spec_path: Path, *, text_input: bool, sha: Optional[str]) -> Dict[str, Any]:
    """현재 트리 또는 `sha` 커밋의 코드로 점검한다(과거 커밋은 임시 작업 폴더에서 하위 프로세스로 실행)."""
    spec = load_spec(spec_path)
    if not sha:
        return run_in_tree(spec, ROOT, text_input=text_input, spec_dir=ROOT)
    tree = Path(tempfile.mkdtemp(prefix="probe_tree_"))
    shutil.rmtree(tree)
    subprocess.run(["git", "worktree", "add", "--detach", "-q", str(tree), sha], cwd=ROOT, check=True)
    try:
        cmd = [sys.executable, str(Path(__file__).resolve()), "run", "--spec", str(spec_path.resolve()), "--tree", str(tree),
               "--json"] + (["--text"] if text_input else [])
        proc = subprocess.run(cmd, cwd=tree, capture_output=True, text=True, timeout=900,
                              env={**os.environ, "PYTHONPATH": str(tree), "PROBE_DOC_ROOT": str(ROOT)})
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[-400:])
        return json.loads(proc.stdout.strip().splitlines()[-1])
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=ROOT, capture_output=True)
        subprocess.run(["git", "worktree", "prune"], cwd=ROOT, capture_output=True)


def render(result: Dict[str, Any]) -> str:
    lines = [f"{result['spec']} — {result['input']} 입력: {result['passed']}/{result['total']}"]
    lines += [f"  {'통과' if r['passed'] else '실패'}  {r['id']:<8} {r['label']}" for r in result["rows"]]
    if result["errors"]:
        lines.append("  처리 중 오류: " + "; ".join(result["errors"]))
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["run", "record"])
    parser.add_argument("--spec", required=True)
    parser.add_argument("--text", action="store_true", help="텍스트 입력(PDF 파서를 거치지 않음)")
    parser.add_argument("--sha", help="record: 이 커밋의 코드로 소급 측정")
    parser.add_argument("--note", default="")
    parser.add_argument("--log", default=str(LOG))
    parser.add_argument("--allow-dirty", action="store_true", help="record: 제품 코드에 미커밋 변경이 있어도 기록")
    parser.add_argument("--tree", help="(내부) 코드를 읽을 작업 폴더")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    spec_path = Path(args.spec)
    try:
        if args.command == "run" and args.tree:
            # 과거 커밋의 작업 폴더에서 실행된 하위 프로세스. 문서는 현재 저장소의 것을 쓴다.
            doc_root = Path(os.environ.get("PROBE_DOC_ROOT", ROOT))
            result = run_in_tree(load_spec(spec_path), Path(args.tree), text_input=args.text, spec_dir=doc_root)
        elif args.command == "run":
            result = measure(spec_path, text_input=args.text, sha=None)
        else:
            if not args.sha and not args.allow_dirty and git("status", "--porcelain", "--", *PRODUCT_PATHS):
                print("제품 코드(packages/ apps/ workers/ config/)에 미커밋 변경이 있다. 첫 점수는 고치기 전 코드로 잰다. "
                      "이미 고친 뒤라면 --sha <고치기 전 커밋>으로 소급 측정하거나 --allow-dirty를 준다.", file=sys.stderr)
                return 2
            result = measure(spec_path, text_input=args.text, sha=args.sha)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"점검하지 못했다: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 0
    print(render(result))
    if args.command == "record":
        sha = args.sha or git("rev-parse", "HEAD")
        entry = {"recorded": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sha": (sha or "")[:12],
                 "measured_commit": git("rev-parse", "--short", sha) if args.sha else git("rev-parse", "--short", "HEAD"),
                 "backfilled": bool(args.sha), "spec": result["spec"], "input": result["input"],
                 "passed": result["passed"], "total": result["total"], "failed": result["failed"], "note": args.note,
                 "condition": "offline; AI 작성·공식 DB·Drive 대조 제외"}
        log = Path(args.log)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"기록: {log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
