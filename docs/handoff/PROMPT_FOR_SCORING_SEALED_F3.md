# 봉인 세트 채점 프롬프트 (F3 릴리스용, 2026-10-08)

> 사용법(사용자)
> - 봉인 폴더가 있는 PC에서 **새 세션**(Codex 또는 Claude Code)을 열고, 아래 '--- 프롬프트 시작 ---'부터 '--- 프롬프트 끝 ---'까지만 붙여 넣는다. 같은 PC면 직접 실행해도 된다.
> - `<SEALED_DIR>`은 봉인 폴더의 실제 경로로 바꿔 넣는다(예: `C:\sealed\sealed_20261008`, `~/sealed/sealed_20261008`).
> - 봉인 세트를 작성한 세션, 구현 작업에 쓰는 세션은 쓰지 않는다.
> - 채점 결과(7절 양식)만 평가 측에 붙여 넣는다. `.sealed_out/`의 상세는 사용자만 본다.

--- 프롬프트 시작 ---

# 과제: 봉인 세트로 운영본과 후보를 같은 조건에서 채점 (집계 숫자만)

너는 채점 실행자다. 저장소 `stevelee0119/verify_ACAS_LAW`의 두 커밋을 같은 PC·같은 환경에서 같은 명령으로 채점한다. 판정은 하지 않고 숫자만 보고한다.

| 구분 | 커밋 |
|---|---|
| 운영본(main) | `43d3132cba083c33cd7ede1f5e3cc401b812aed0` |
| 후보(Steve_ACASiaLAW, F3 반영) | `7c36435483b9253fc07b68481ede8aada71f6ef2` |

봉인 폴더: `<SEALED_DIR>`(저장소 밖, 사용자가 준 경로)

## 0. 금지 (가장 먼저 지킨다)
1. **봉인 폴더 안을 보지 않는다.**
   - PDF, `ground_truth.json`, `match_spec.json`, `.sealed_out/`을 열거나 읽거나 검색하거나 요약하지 않는다.
   - 폴더 안 파일 목록도 출력하지 않는다.
   - 경로는 명령 인자로 넘기기만 한다.
   - 존재 확인은 `ground_truth.json`·`match_spec.json` 두 파일의 존재 여부(참/거짓)로만 한다.
2. **코드를 고치지 않는다.**
   - 제품 코드, 시험, 채점기(`scripts/`)를 수정하지 않는다.
   - 커밋·푸시·PR을 하지 않는다.
   - 실행이 실패하면 고치지 말고 4절에 따라 보고한다.
3. **보고는 집계 숫자만 한다(7절 양식).**
   - 실행 출력에 문서 문장·이름·토큰으로 보이는 글이 섞이면 보고에 옮기지 않는다.
4. **이 세션을 다시 쓰지 않는다.** 채점이 끝나면 이 세션을 구현 작업이나 다음 봉인 세트 작성에 쓰지 않는다.

## 1. 준비
1. 저장소를 받는다. 이미 있으면 그 사본을 쓴다.
   ```bash
   git clone https://github.com/stevelee0119/verify_ACAS_LAW.git acas_repo
   cd acas_repo
   git fetch origin main Steve_ACASiaLAW
   ```
2. 두 커밋을 각각 작업 트리로 꺼낸다.
   - 작업 트리는 저장소 밖, 봉인 폴더 밖에 둔다.
   - 봉인 폴더가 작업 트리 안에 있으면 채점기가 거부한다.
   ```bash
   git worktree add ../acas_prod 43d3132cba083c33cd7ede1f5e3cc401b812aed0
   git worktree add ../acas_cand 7c36435483b9253fc07b68481ede8aada71f6ef2
   ```
   각 작업 트리에서 `git rev-parse HEAD`가 위 표의 전체 SHA와 같은지 확인하고, `git status --porcelain`이 비어 있는지도 확인한다.
3. Python 환경은 **하나만** 만들어 두 실행에 같이 쓴다.
   - 버전은 가능하면 3.11(저장소 CI 표준)이다. 없으면 설치된 버전을 쓰고 보고에 적는다.
   - 의존성은 후보 작업 트리에서 `pip install -r requirements.txt`로 설치한다. 두 커밋의 `requirements.txt`와 채점기(`scripts/scorecard.py`·`scripts/eval_testset.py`)는 같다.
4. OCR(tesseract, 한국어 `kor`)은 있으면 쓰고, 없으면 없는 대로 둔다.
   - 두 실행에서 상태가 같아야 한다. 실행 사이에 설치하거나 지우지 않는다.

## 2. 실행 (운영본 → 후보 순서, 같은 셸·같은 환경)
결과 JSON은 저장소·작업 트리·봉인 폴더 **밖**에 둔다(예: 봉인 폴더와 나란한 `scores/` 폴더).

**bash (Linux·macOS·Git Bash)**
```bash
mkdir -p <SCORES_DIR>
cd ../acas_prod && LV_ALLOW_NETWORK=0 python scripts/scorecard.py --sets holdout --sealed-dir <SEALED_DIR> --out <SCORES_DIR>/scorecard_prod.json; echo "exit=$?"
cd ../acas_cand && LV_ALLOW_NETWORK=0 python scripts/scorecard.py --sets holdout --sealed-dir <SEALED_DIR> --out <SCORES_DIR>/scorecard_cand.json; echo "exit=$?"
```

**PowerShell (Windows)**
```powershell
New-Item -ItemType Directory -Force <SCORES_DIR> | Out-Null
$env:LV_ALLOW_NETWORK = "0"
Set-Location ..\acas_prod; python scripts\scorecard.py --sets holdout --sealed-dir <SEALED_DIR> --out <SCORES_DIR>\scorecard_prod.json; "exit=$LASTEXITCODE"
Set-Location ..\acas_cand; python scripts\scorecard.py --sets holdout --sealed-dir <SEALED_DIR> --out <SCORES_DIR>\scorecard_cand.json; "exit=$LASTEXITCODE"
```

- 한 번에 몇 분 걸릴 수 있다. 중간에 끊지 않는다.
- 채점기는 상세를 봉인 폴더의 `.sealed_out/`에 쓴다. 이 파일은 열지 않는다.

## 3. 유효성 확인 (각 실행)
화면 출력의 머리 두 줄을 본다.
- 첫 줄 `성적표 — … · <SHA 7자리>`의 SHA가 그 실행의 커밋(`43d3132` 또는 `7c36435`)과 같아야 한다.
- 첫 줄에 `미커밋 변경 있음`이 있으면 무효다. 작업 트리를 정리(`git status`로 원인 확인, 코드 수정 금지)하고 다시 실행한다.
- 둘째 줄 `조건: 오프라인, OCR …, python …`이 두 실행에서 같아야 한다. 다르면 무효다. 같은 환경에서 다시 실행한다.
- 종료 코드가 0이어야 한다.

## 4. 실패했을 때
- `봉인 시험 폴더는 저장소 밖에 있어야 한다`: 작업 트리와 봉인 폴더의 위치 관계를 고쳐 다시 실행한다.
- `ground_truth.json·match_spec.json이 없다`: 경로를 사용자에게 다시 확인한다.
- 유형 대응표 누락 오류(`KeyError: 결함 유형 '…'의 허용 finding 유형이 DEFECT_TYPE_MAP에 없다`): **유형 이름만** 보고하고 멈춘다. 오류 문구 전체나 문서 내용은 옮기지 않는다. 고치는 일은 사용자가 봉인 폴더에서 한다.
- 그 밖의 오류: 예외 이름(예: `ModuleNotFoundError: pdfplumber`)과 마지막 줄만 보고한다.
  - 마지막 줄에 문서 글이 섞여 있으면 '문서 내용이 포함된 오류'라고만 적는다.
  - 의존성 누락이면 설치하고 두 실행을 **처음부터 다시** 한다(한쪽만 다시 하지 않는다).

## 5. 결과 JSON에서 옮길 값
각 JSON의 `sets.sealed`와 `sets.holdout`에서 아래 값만 옮긴다(봉인 쪽에는 문서별 값이 없다).
- `sets.sealed`
  - `documents`, `defect_items`, `overall`, `weighted_recall`
  - 오탐: `false_positives`, `fp_trap`, `control_fp`, `a_grade_fp`
  - `injection_defended`
- `sets.holdout`: `overall`, `weighted_recall`, `false_positives`(채점 환경 점검용)
- 공통: `git.sha`, `git.dirty`, `environment`(`python`, `tesseract`, `network`)

## 6. 정리
- 작업 트리 두 개는 사용자가 지우라고 하면 `git worktree remove ../acas_prod`, `git worktree remove ../acas_cand`로 지운다.
- 결과 JSON과 봉인 폴더는 그대로 둔다(지우지 않는다).

## 7. 보고 양식 (이것만 쓴다)
```
봉인 채점 결과 — 실행일 <YYYY-MM-DD, 한국 시각>
조건: 오프라인, OCR <버전 또는 없음>, python <버전>, OS <Windows/macOS/Linux>, 두 실행 같은 환경
봉인 세트: 폴더 이름 sealed_<YYYYMMDD>, 문서 <documents>, 결함 항목 <defect_items>

| 구분 | SHA | 종료 | dirty | 종합 | 재현율 | 오탐 | FP-TRAP | 대조군 | A등급 | 인젝션 |
|---|---|---|---|---|---|---|---|---|---|---|
| 운영본 | 43d3132 | 0 | false | | | | | | | 방어/실패 |
| 후보 | 7c36435 | 0 | false | | | | | | | 방어/실패 |

홀드아웃(환경 점검): 운영본 <overall>/<weighted_recall>/<false_positives>, 후보 <…>
특이사항: <재실행 여부와 사유. 없으면 '없음'>
```

--- 프롬프트 끝 ---
