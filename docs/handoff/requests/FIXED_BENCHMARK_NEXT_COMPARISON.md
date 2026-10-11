# 고정 벤치마크 다음 후보 비교 전달문

현재 최종8TK 후보의 측정은 미완료다. 기존20.5/27.5%/오탐12는운영9c1b218과이전ad25f51의사용자제공결과이며 이번후보로재사용하지않는다. 세트가연결되지않으면미측정으로보고하며새봉인필수요건과구분한다.

봉인 채점과 같은 분리 runner에서 사용자 보관 `fixed_bench_20261010`을 그대로 사용한다. 원문/정답/사례별 `.sealed_out`을 열거나 공개하지 않는다. 코드/정답/기준을 수정하지 않는다. 확정 후보 전체 SHA는 평가 측 최종 실행 전달문에서 받는다. 운영본은 `9c1b21848110a8df6ba0e6308b49e6947c0d6feb`이다.

- 동일 환경·동일 세트로 두 clean checkout을 준비한다. 이전 지문 `9de8ab2dbe9439c2`, Python3.12.14/pdfplumber0.11.9/Linux 자체 점검 환경은 사용자보고다. 이번 실제 환경은 별도로 기록하고 서로 같을 때만 두 점수를 대조한다.
- 운영9c1b218에는 후속 `scripts/fixed_benchmark.py`가 없다. 후보의 같은 측정 도구를 아래 외부 실행기로 로드하고 `ROOT`만 대상 checkout으로 지정한다. 채점기는 각 대상의 scorecard/eval_testset을 그대로 로드한다. 실행 전 도구hash·ROOT·실제HEAD·dirty 및 채점규칙동일성을 확인한다. 원본 실패를 고치거나 운영제품을 후보코드로 대체하지 않는다. `--record`는 쓰지 않고 평가 측이 집계 원장을 반영한다.
- 도구 경로/ROOT 설정을 안전하게 확인할 수 없으면 임의 수정 실행하지 않고 BLOCKED를 보고한다. 최신 두 후보에 도구가 모두 있는 상황과 다르므로 단순checkout명령만으로 운영본을 재었다고 주장하지 않는다.
- 보고: 운영/후보 전체SHA, dirty false, 실제Python/pdfplumber/tesseract/OS·OCR언어, 지문, 묶음/문서/결함 수, 종합점수·가중재현율·FP/대조FP/AFP·인젝션방어, 각exit코드, 같은조건여부. 집계만 평가 측에 전달하고 원장은 평가 측이 출처와 함께 반영한다.

이는 실행 준비 문서다. 실제 비교 결과 또는 변호사 품질 채점 완료를 뜻하지 않는다.

저장소·벤치마크 밖에 `run_fixed_pair.py`를 저장한다. 제품/채점기를 수정하는 대신 동일 집계 도구의 실행 대상만 선택한다.

```python
import importlib.util
import os
from pathlib import Path
import sys

tool, checkout, benchmark, role = sys.argv[1:]
os.environ["LV_ALLOW_NETWORK"] = "0"
target = Path(checkout).resolve()
os.chdir(target)
sys.path.insert(0, str(target))
spec = importlib.util.spec_from_file_location("fixed_pair_tool", tool)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.ROOT = target
module.LOG = target / "docs/scorecards/fixed_benchmark_log.jsonl"
raise SystemExit(module.main(["--bench-dir", benchmark, "--role", role]))
```

같은 Python으로 `python run_fixed_pair.py <후보/scripts/fixed_benchmark.py> <운영checkout> <BENCH_DIR> 운영본` 및 마지막 대상/역할을 `<후보checkout> ... 후보`로 바꾼 명령을 순서대로 실행한다. 두 checkout 사이에 환경/세트를 바꾸지 않는다. 키/API는 쓰지 않는다.
