"""실연동 통합 테스트 실행기(v4 P0 감사의 '미확인' 항목 확인용).

CI에서 국가법령정보 OC·모델 API 키가 주입된 상태로 tests/live를 돌리고, 항목별 결과를
docs/live_integration_results.json에 쓴다. 키가 없거나 실패한 항목은 통과로 기록되지 않는다.

사용: python scripts/live_integration.py [--out docs/live_integration_results.json]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "docs" / "live_integration_results.json"))
    args = parser.parse_args()
    env = {**os.environ, "LV_LIVE_TESTS": "1", "LV_LIVE_RESULTS_OUT": args.out, "LV_ALLOW_NETWORK": "1"}
    result = subprocess.run([sys.executable, "-m", "pytest", "-o", "addopts=", "-q", "tests/live"], cwd=ROOT, env=env)
    print(f"결과 파일: {args.out}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
