"""하드코딩 변경분 점검(평가 에이전트 소관, 보호 경로). 이번 변경에서 **새로 추가된 줄**에 시험 입력의 값·낱말·조문 번호가 들어갔는지 본다.

`check_case_literals.py`는 제품 코드·설정 전체에서 사건 값(사건번호·금액·식별자·열 글자 이상의 문구)의 존재를 센다. 이 도구는 그것이 못 잡는 것을
변경분(diff) 단위로 잡는다. 점수를 올리려고 시험 정답 낱말·조문 번호를 규칙 키로 새로 넣는 수정이 대상이다.

    python scripts/check_hardcoding_diff.py --base HEAD~1        # 직전 커밋 대비 추가분 (푸시 전에 항상)
    python scripts/check_hardcoding_diff.py --base origin/main --json

시험 입력에서 뽑는 토큰(tests/fixtures/probes/*.json·*.txt): 명세의 정답 낱말(value·text_any·text_all·case_number), 서면의 사건번호·금액·대문자 식별자, 서면의 조문 번호.
변경분은 `packages/`·`apps/`·`workers/`·`config/`의 추가된 줄이다(주석 줄 제외). 기준 커밋에 이미 있던 토큰은 새 것이 아니므로 센다.
- 강한 신호(종료 코드 1, 평가 에이전트 승인 필요): 새 사건번호·금액·대문자 식별자, **설정 규칙의 판정 필드(pattern·context·unless·articles)에 새로 들어온 시험 서면의 조문 번호**.
- 약한 신호(검토 목록, 종료 코드 0): 새로 들어온 명세 낱말(네 글자 이상), 새 규칙(rule_id). 일반 법률 용어일 수 있어 평가 에이전트가 사유를 본다.
  새 규칙은 안정화 라운드의 '새 규칙 0개' 기준을 위해 항상 센다.
승인된 항목은 tests/acceptance/hardcoding_allow.json에 사유와 함께 올린다(평가 에이전트만). 체계적으로 닫힌 집합(예: 헌법 제2장 전체)은 승인 대상이 될 수 있지만
시험에 나온 조문 몇 개만 고른 집합은 승인하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
PROBES = ROOT / "tests" / "fixtures" / "probes"
ALLOW = ROOT / "tests" / "acceptance" / "hardcoding_allow.json"
PRODUCT = ("packages", "apps", "workers", "config")
DECISION_KEYS = ("pattern", "context", "unless", "absent_pattern", "articles")
JSON_SKIP_KEYS = {"url", "version", "text", "explanation", "title", "detail", "description", "note", "verdict", "label",
                  "name", "law_name", "source", "basis", "default"}
CASE_NUMBER = re.compile(r"(?<!\d)(?:19|20)\d{2}[가-힣]{1,3}\d{2,6}(?!\d)")
AMOUNT = re.compile(r"(?<![\d,])\d{1,3}(?:,\d{3}){2,}(?![\d,])")
IDENT = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9]{2,}(?:[_-][A-Z0-9]+){1,}(?![A-Za-z0-9])")
ARTICLE = re.compile(r"제\s*(\d{1,4})\s*조(?:\s*의\s*(\d{1,2}))?")
HANGUL4 = re.compile(r"[가-힣]{4,}")
# 어느 서면에나 나오는 일반 낱말은 약한 신호에서 뺀다(조문 번호·식별자는 그대로 본다).
GENERIC = {"위반하", "청구취지", "손해배상", "인정되", "판결", "판례", "법률", "규정", "조항", "원고", "피고", "주장", "서면"}


def article_numbers(text: str) -> Set[str]:
    """`제203조`·`제14조의2`는 '203'·'14의2'. 정규식 조각(`203\\s*조`, `제\\s*119\\s*조`)도 읽는다."""
    flat = re.sub(r"\\+s[*+?]?|\[ \\+t\][*+?]?|\s+", "", text)
    out = set()
    for m in re.finditer(r"(?:제)?(\d{1,4})조(?:의(\d{1,2}))?", flat):
        out.add(m.group(1) + (f"의{m.group(2)}" if m.group(2) else ""))
    for m in re.finditer(r"제\(\?:([0-9|]+)\)조", flat):                     # 제(?:119|34)조 같은 선택 조문
        out.update(x for x in m.group(1).split("|") if x)
    return out


def spec_terms(spec: Dict) -> Set[str]:
    terms: Set[str] = set()
    for check in spec.get("checks", []):
        for key in ("value", "case_number", "text", "law_contains", "raw_contains"):
            if isinstance(check.get(key), str):
                terms.add(check[key])
        for key in ("text_any", "text_all"):
            terms.update(x for x in check.get(key, []) if isinstance(x, str))
    return {re.sub(r"\\s[*+?]?|\\", "", t).strip() for t in terms if t}


def fixture_tokens(root: Path = ROOT) -> Dict[str, Dict[str, str]]:
    """{종류: {토큰: 출처 파일}}. 종류: identifier·case_number·amount·article·spec_term"""
    out: Dict[str, Dict[str, str]] = {k: {} for k in ("identifier", "case_number", "amount", "article", "spec_term")}
    probes = root / "tests" / "fixtures" / "probes"
    for path in sorted(probes.glob("*.txt")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.relative_to(root).as_posix()
        for tok in IDENT.findall(text):
            if len(tok) >= 8:
                out["identifier"].setdefault(tok.replace("-", "_"), rel)
        for tok in CASE_NUMBER.findall(text):
            out["case_number"].setdefault(tok, rel)
        for tok in AMOUNT.findall(text):
            out["amount"].setdefault(tok, rel)
        for tok in article_numbers(text):
            out["article"].setdefault(tok, rel)
    for path in sorted(probes.glob("*.json")):
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        rel = path.relative_to(root).as_posix()
        for term in spec_terms(spec):
            if CASE_NUMBER.fullmatch(term):
                out["case_number"].setdefault(term, rel)
            elif IDENT.fullmatch(term) and len(term) >= 8:
                out["identifier"].setdefault(term.replace("-", "_"), rel)
            elif HANGUL4.search(term) and term not in GENERIC:
                out["spec_term"].setdefault(term, rel)
    return out


def added_lines(diff: str) -> List[Tuple[str, int, str]]:
    """unified diff(-U0)에서 (파일, 줄 번호, 추가된 줄). 주석 줄(`#`)은 뺀다."""
    out: List[Tuple[str, int, str]] = []
    path, line_no = "", 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else raw[4:]
            continue
        m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", raw)
        if m:
            line_no = int(m.group(1))
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            body = raw[1:]
            if not (path.endswith(".py") and body.lstrip().startswith("#")):
                out.append((path, line_no, body))
            line_no += 1
    return out


def load_allow() -> Dict[str, Dict[str, str]]:
    if not ALLOW.is_file():
        return {}
    return json.loads(ALLOW.read_text(encoding="utf-8")).get("allow", {})


def in_base(ref: str, token: str) -> bool:
    """기준 커밋의 제품 파일에 이 토큰이 이미 있었는가."""
    flat = subprocess.run(["git", "grep", "-F", "-q", "--", token, ref, "--", *PRODUCT], cwd=ROOT, capture_output=True)
    return flat.returncode == 0


def is_decision_line(line: str) -> bool:
    return any(re.match(rf'\s*"{k}"\s*:', line) for k in DECISION_KEYS)


def json_items(text: str) -> Set[Tuple[str, str]]:
    """설정 JSON의 (필드 이름, 문자열) 집합. 목록 안의 문자열은 목록의 필드 이름으로 센다."""
    out: Set[Tuple[str, str]] = set()

    def walk(obj, key=""):
        if isinstance(obj, str):
            out.add((key, obj))
        elif isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, k)
        elif isinstance(obj, list):
            for v in obj:
                walk(v, key)

    try:
        walk(json.loads(text))
    except ValueError:
        pass
    return out


def git_show(ref: str, path: str) -> str:
    proc = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=ROOT, capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else ""


def changed_json(base: str, root: Path) -> List[str]:
    out = subprocess.run(["git", "diff", "--name-only", base, "--", "config"], cwd=root, capture_output=True, text=True,
                         check=True).stdout.split()
    return [p for p in out if p.endswith(".json")]


def scan(base: str, root: Path = ROOT) -> Dict[str, List[Dict[str, object]]]:
    diff = subprocess.run(["git", "diff", "-U0", base, "--", *PRODUCT], cwd=root, capture_output=True, text=True,
                          check=True).stdout
    lines = [row for row in added_lines(diff) if not row[0].endswith(".json")]      # JSON은 구조로 비교한다
    tokens = fixture_tokens(root)
    allow = load_allow()
    hard: List[Dict[str, object]] = []
    soft: List[Dict[str, object]] = []
    seen: Set[Tuple[str, str]] = set()

    def record(bucket, kind: str, token: str, path: str, line_no: int, body: str, source: str):
        key = (path, token)
        if key in seen or token in allow.get(path, {}):
            return
        seen.add(key)
        bucket.append({"kind": kind, "token": token, "file": path, "line": line_no, "source": source,
                       "excerpt": body.strip()[:140]})

    def check_text(path: str, line_no: int, body: str, decision_field: bool, bare_numbers: bool):
        flat_body = body.replace("-", "_")
        for tok, src in tokens["identifier"].items():
            if tok in flat_body and not in_base(base, tok.replace("_", "-")) and not in_base(base, tok):
                record(hard, "identifier", tok, path, line_no, body, src)
        for kind in ("case_number", "amount"):
            for tok, src in tokens[kind].items():
                if tok in body and not in_base(base, tok):
                    record(hard, kind, tok, path, line_no, body, src)
        if path.startswith("config/") and decision_field:
            arts = article_numbers(body)
            if bare_numbers and re.fullmatch(r"\d{1,4}(?:의\d{1,2})?", body.strip()):
                arts.add(body.strip())
            for art in arts:
                if art in tokens["article"]:
                    record(hard, "article_key", f"제{art}조", path, line_no, body, tokens["article"][art])
        for tok, src in tokens["spec_term"].items():
            if tok in body and not in_base(base, tok):
                record(soft, "spec_term", tok, path, line_no, body, src)

    for path, line_no, body in lines:
        check_text(path, line_no, body, is_decision_line(body), False)
    for path in changed_json(base, root):
        old = json_items(git_show(base, path))
        new = json_items((root / path).read_text(encoding="utf-8")) if (root / path).is_file() else set()
        for key, value in sorted(new - old):
            if key == "rule_id":                                               # 안정화 라운드에서는 새 규칙을 세어 알린다
                record(soft, "new_rule", value, path, 0, f'"rule_id": "{value}"', "-")
                continue
            if key in JSON_SKIP_KEYS:
                continue
            check_text(path, 0, value, key in DECISION_KEYS, key == "articles")
    return {"hard": hard, "soft": soft, "added_lines": [len(lines)]}


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", required=True, help="비교 기준 커밋")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = scan(args.base)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"점검하지 못했다: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result["hard"] else 0
    print(f"하드코딩 변경분 점검 — 기준 {args.base}, 추가된 줄 {result['added_lines'][0]}개")
    for item in result["hard"]:
        print(f"  [강한 신호·승인 필요] {item['kind']} {item['token']} — {item['file']}:{item['line']} (시험 자료 {item['source']})")
        print(f"      {item['excerpt']}")
    for item in result["soft"]:
        if item["kind"] == "new_rule":
            print(f"  [검토] 새 규칙 {item['token']} — {item['file']} (안정화 라운드에는 새 규칙을 넣지 않는다)")
            continue
        print(f"  [검토] 명세 낱말 '{item['token']}' — {item['file']}:{item['line']} (시험 자료 {item['source']})")
    if not result["hard"] and not result["soft"]:
        print("  새로 추가된 줄에 시험 입력의 값·낱말·조문 번호 없음")
    return 1 if result["hard"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
