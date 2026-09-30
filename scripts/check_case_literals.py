"""사건 고유 값 하드코딩 점검(평가 에이전트 소관, 보호 경로).

사건별 시험(서면 한 건에 맞춘 시험)에 나오는 사건번호·금액·수치를 뽑아, 그 값이 제품 코드(`packages/**/*.py`)에
그대로 들어 있는지 찾는다. 사건 값이 코드에 있으면 그 서면만 통과하는 맞춤 수정이다(AUDIT_v6의 '리터럴 의존').

    python scripts/check_case_literals.py               # 위반 목록(기존 부채 표시)
    python scripts/check_case_literals.py --write-debt  # 현재 위반을 부채 목록(tests/acceptance/literal_debt.json)에 기록(평가 에이전트만)

부채 목록은 래칫이다. 목록에 없는 새 위반이 생기면 시험이 실패하고, 부채를 고치면(위반이 사라지면) 통과한다.
목록 정리는 평가 에이전트가 한다.

뽑는 값(사건 고유성이 큰 것만)
- 사건번호: 2021도14892, 2026가합534210 같은 `연도+사건부호+번호`
- 금액: 유효숫자 3자리 이상인 쉼표 금액(148,000,000 → 유효숫자 148). 1,000,000처럼 둥근 값은 뺀다
- 활력징후: 210/120 mmHg 같은 수치쌍

- 식별자 베끼기: 서면에 나오는 대문자 식별자(`LABOR_DISPUTE_AI_AUDITOR`, `ADMINISTRATIVE_AUDIT_PROTOCOL`)가 제품 코드의 정규식·목록에 그대로 들어 있는 경우
  (한글 문구 점검은 영문 식별자를 못 본다). 12자 이상, `_`·`-`로 이어진 대문자·숫자 토큰만 센다. `-`와 `_`는 같게 본다
- 문구 베끼기: 사건 서면 본문(사건별 시험의 긴 문자열 상수, 서면 원문 텍스트)에 나오는 열 글자 이상의 연속 문구가
  제품 코드의 정규식·메시지에 그대로 들어 있는 경우. 숫자를 빼고 사건 문구로 정규식을 짜도 잡는다(숫자만 보는 점검의 구멍)

코드 안에서는 주석·독스트링을 빼고 문자열 상수(정규식·메시지)만 본다. 법령·판례 원천을 근거로 인용하는 값은
`tests/acceptance/literal_allow.json`에 사유와 함께 올린다(평가 에이전트만).
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
DEBT = ROOT / "tests" / "acceptance" / "literal_debt.json"
ALLOW = ROOT / "tests" / "acceptance" / "literal_allow.json"
# 사건 한 건에 맞춘 시험과 그 서면의 텍스트. 새 사건별 시험 파일은 여기에 이름 규칙으로 잡힌다.
SOURCE_GLOBS = [
    "tests/test_case*.py",
    "tests/test_*_claim_efficacy.py",
    "tests/test_ground_truth_*.py",
    "tests/test_school_completeness.py",
    "tests/test_efficacy_*.py",
    "tests/fixtures/probes/*.txt",
]
SCAN_GLOB = "packages/**/*.py"
CASE_NUMBER = re.compile(r"(?<!\d)(?:19|20)\d{2}[가-힣]{1,3}\d{2,6}(?!\d)")
AMOUNT = re.compile(r"(?<![\d,])\d{1,3}(?:,\d{3}){2,}(?![\d,])")
VITALS = re.compile(r"(?<!\d)\d{2,3}\s*/\s*\d{2,3}(?=\s*mmHg)")
MIN_PHRASE = 10          # 글자·숫자만 이은 연속 문구의 최소 길이(공백·정규식 문법 제외). 한글이 이 길이 이상이어야 센다
MIN_DOCUMENT = 200       # 사건 서면 본문으로 보는 문자열 상수의 최소 길이
MIN_IDENT = 12           # 서면의 대문자 식별자(LABOR_DISPUTE_AI_AUDITOR 같은 것)를 코드에서 찾을 최소 길이
IDENT = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9]{1,}(?:[_-][A-Z0-9]+){1,}(?![A-Za-z0-9])")


def distinctive_amount(value: str) -> bool:
    digits = value.replace(",", "").rstrip("0")
    return len(digits) >= 3


def extract_literals(root: Path = ROOT) -> Dict[str, List[str]]:
    """{값: [그 값이 나오는 사건별 시험 파일]}"""
    found: Dict[str, set] = {}
    for pattern in SOURCE_GLOBS:
        for path in sorted(root.glob(pattern)):
            text = path.read_text(encoding="utf-8", errors="ignore")
            values = set(CASE_NUMBER.findall(text))
            values |= {v for v in AMOUNT.findall(text) if distinctive_amount(v)}
            values |= {re.sub(r"\s+", "", v) for v in VITALS.findall(text)}
            for value in values:
                found.setdefault(value, set()).add(str(path.relative_to(root)))
    return {value: sorted(files) for value, files in sorted(found.items())}


def literal_regex(value: str) -> re.Pattern:
    """코드 안에서는 정규식 조각(`210\\s*/\\s*120`)으로도 나온다. 슬래시 앞뒤 공백·`\\s*`를 허용한다."""
    return re.compile(re.escape(value).replace("/", r"(?:\\s\*|\s)*/(?:\\s\*|\s)*"))


def code_constants(source: str) -> List[str]:
    """주석과 독스트링을 뺀, 코드가 실제로 쓰는 문자열 상수(정규식·메시지·사전 값).

    주석·독스트링의 예시 숫자는 동작에 영향이 없으므로 사건 맞춤으로 보지 않는다. 구문 오류가 있으면 원문 전체를 쓴다.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [source]
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


def code_strings(source: str) -> str:
    return "\n".join(code_constants(source))


_KEEP = re.compile(r"[^0-9A-Za-z가-힣]")


def alnum(text: str) -> str:
    """공백·문장부호를 뺀 글자·숫자열(서면 본문과 코드 문구를 같은 모양으로 맞춘다)."""
    return _KEEP.sub("", text)


def literal_runs(constant: str) -> List[str]:
    """정규식·메시지 상수에서 글자·숫자만 이은 연속 문구를 뽑는다. `단독\\s*진단용`은 '단독진단용'으로 이어 본다."""
    text = re.sub(r"\\s[*+?]?|\[ \\t\][*+?]?|\s+", "", constant)          # 공백류는 이어 붙인다
    text = re.sub(r"\\[A-Za-z]", "|", text)                                # \d \w \b 같은 정규식 기호는 끊는다
    return [run for run in re.split(r"[^0-9A-Za-z가-힣]+", text)
            if len(re.findall(r"[가-힣]", run)) >= MIN_PHRASE]


def extract_documents(root: Path = ROOT) -> Dict[str, str]:
    """{사건 서면 본문(글자·숫자열): 출처 파일}. 원문 텍스트 파일과 사건별 시험의 긴 문자열 상수."""
    docs: Dict[str, str] = {}
    for pattern in SOURCE_GLOBS:
        for path in sorted(root.glob(pattern)):
            raw = path.read_text(encoding="utf-8", errors="ignore")
            rel = str(path.relative_to(root))
            if path.suffix == ".txt":
                docs[alnum(raw)] = rel
            else:
                for const in code_constants(raw):
                    if len(const) >= MIN_DOCUMENT:
                        docs.setdefault(alnum(const), rel)
    return docs


def norm_ident(token: str) -> str:
    return token.replace("-", "_")


def extract_identifiers(root: Path = ROOT) -> Dict[str, str]:
    """{서면의 대문자 식별자: 출처 파일}. 원문 텍스트 파일과 사건별 시험의 긴 문자열 상수에서 뽑는다."""
    found: Dict[str, str] = {}
    for pattern in SOURCE_GLOBS:
        for path in sorted(root.glob(pattern)):
            raw = path.read_text(encoding="utf-8", errors="ignore")
            rel = str(path.relative_to(root))
            texts = [raw] if path.suffix == ".txt" else [c for c in code_constants(raw) if len(c) >= MIN_DOCUMENT]
            for text in texts:
                for token in IDENT.findall(text):
                    if len(token) >= MIN_IDENT:
                        found.setdefault(norm_ident(token), rel)
    return found


def scan_identifiers(identifiers: Dict[str, str], root: Path = ROOT,
                     allow: Dict[str, Dict[str, str]] | None = None) -> Dict[str, List[str]]:
    """{제품 코드 파일: [서면에서 그대로 따온 식별자]}"""
    allow = load_allow() if allow is None else allow
    hits: Dict[str, List[str]] = {}
    for path in sorted(root.glob(SCAN_GLOB)):
        relative = str(path.relative_to(root))
        skip = set(allow.get(relative, {}))
        found = set()
        for const in code_constants(path.read_text(encoding="utf-8", errors="ignore")):
            for token in IDENT.findall(const):
                key = norm_ident(token)
                if len(token) >= MIN_IDENT and key in identifiers and key not in skip:
                    found.add(key)
        if found:
            hits[relative] = sorted(found)
    return hits


def scan_phrases(documents: Dict[str, str], root: Path = ROOT, allow: Dict[str, Dict[str, str]] | None = None
                 ) -> Dict[str, List[str]]:
    """{제품 코드 파일: [사건 서면에서 그대로 따온 문구]}"""
    allow = load_allow() if allow is None else allow
    bodies = list(documents)
    hits: Dict[str, List[str]] = {}
    for path in sorted(root.glob(SCAN_GLOB)):
        relative = str(path.relative_to(root))
        skip = set(allow.get(relative, {}))
        found = set()
        for const in code_constants(path.read_text(encoding="utf-8", errors="ignore")):
            for run in literal_runs(const):
                if run not in skip and any(run in body for body in bodies):
                    found.add(run)
        if found:
            hits[relative] = sorted(found)
    return hits


def load_allow() -> Dict[str, Dict[str, str]]:
    """{제품 코드 파일: {값: 허용 사유}}. 법령·판례 원천을 근거로 인용하는 경우처럼 사건 서면의 값이 아닌 것만 평가 에이전트가 올린다."""
    if not ALLOW.is_file():
        return {}
    return json.loads(ALLOW.read_text(encoding="utf-8")).get("allow", {})


def scan(literals: Dict[str, List[str]], root: Path = ROOT, allow: Dict[str, Dict[str, str]] | None = None
         ) -> Dict[str, List[str]]:
    """{제품 코드 파일: [들어 있는 사건 값]} — 주석·독스트링과 허용 목록은 제외한다."""
    allow = load_allow() if allow is None else allow
    patterns = {value: literal_regex(value) for value in literals}
    hits: Dict[str, List[str]] = {}
    for path in sorted(root.glob(SCAN_GLOB)):
        relative = str(path.relative_to(root))
        text = code_strings(path.read_text(encoding="utf-8", errors="ignore"))
        skip = set(allow.get(relative, {}))
        present = sorted(value for value, pattern in patterns.items() if value not in skip and pattern.search(text))
        if present:
            hits[relative] = present
    return hits


def load_debt() -> Dict[str, List[str]]:
    if not DEBT.is_file():
        return {}
    return json.loads(DEBT.read_text(encoding="utf-8")).get("debt", {})


def new_violations(hits: Dict[str, List[str]], debt: Dict[str, List[str]]) -> Dict[str, List[str]]:
    out = {}
    for path, values in hits.items():
        extra = sorted(set(values) - set(debt.get(path, [])))
        if extra:
            out[path] = extra
    return out


def stale_debt(hits: Dict[str, List[str]], debt: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """부채 목록에는 있으나 이제 코드에 없는 값(고쳐진 것). 목록에서 지워도 된다."""
    out = {}
    for path, values in debt.items():
        gone = sorted(set(values) - set(hits.get(path, [])))
        if gone:
            out[path] = gone
    return out


def merge(*parts: Dict[str, List[str]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for part in parts:
        for path, values in part.items():
            out[path] = sorted(set(out.get(path, [])) | set(values))
    return dict(sorted(out.items()))


def git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write-debt", action="store_true")
    args = parser.parse_args(argv)
    literals = extract_literals()
    documents = extract_documents()
    hits = merge(scan(literals), scan_phrases(documents), scan_identifiers(extract_identifiers()))
    if args.write_debt:
        payload = {"note": "제품 코드에 이미 들어 있는 사건 고유 값(부채). 구현 에이전트가 일반 규칙으로 바꾸면 위반이 사라진다. "
                           "새 값을 여기에 추가하지 않는다. 정리는 평가 에이전트만 한다.",
                   "measured_at": git_head(), "sources": SOURCE_GLOBS, "debt": hits}
        DEBT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"부채 목록 기록: {DEBT} ({sum(len(v) for v in hits.values())}건, 파일 {len(hits)}개)")
        return 0
    debt = load_debt()
    fresh = new_violations(hits, debt)
    print(f"사건별 시험에서 뽑은 사건 값 {len(literals)}개, 제품 코드에서 발견 {sum(len(v) for v in hits.values())}건")
    for path, values in hits.items():
        mark = "부채" if path in debt else "새 위반"
        print(f"  [{mark}] {path}: {', '.join(values)}")
    if fresh:
        print("\n새 위반(사건 고유 값을 코드에 넣지 않는다):")
        for path, values in fresh.items():
            print(f"  {path}: {', '.join(values)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
