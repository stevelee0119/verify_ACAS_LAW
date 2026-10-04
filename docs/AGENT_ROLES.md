# 개발 에이전트 역할 분리

시행: 2026-09-30. 개정: 2026-10-03(사용자 결정 '1~5 추천대로', 근거 [process_review_2026-10-03](scorecards/process_review_2026-10-03.md) 5·6절). 근거: 9/6~9/30 커밋 251건을 일자별로 다시 채점한 결과(고정 시험 점수는 9/26부터 정체, 처음 보는 서면은 수정 전 4/19),
그리고 정답지·시험문서가 저장소 안에 있어 구현자가 읽고 맞춰 고칠 수 있었던 구조. 구현과 평가를 다른 에이전트가 맡아 같은 손이 문제를 내고 푸는 일을 막는다.

## 1. 역할

| 역할 | 담당 | 하는 일 | 하지 않는 일 |
|---|---|---|---|
| 구현 | **Codex(주력, 2026-10-03부터 2개 증분 시험 전환)** · Antigravity(화면·브라우저 작업, 사용자 PC(Windows) 재현) | 제품 코드 수정(`packages/`, `apps/`, `workers/`, `config/`, `migrations/`, `docker/`) | 보호 경로(아래) 수정, 정답지·기준선 변경, 평가 측 비공개 수치 추정 기재 |
| 감사 | 구현·평가와 다른 모델 계열(예: Antigravity의 다른 모델, Astra·Sol) | 라운드 첫 완료 시점과 F1 착수 전 독립 감사. 측정 재현과 함께 **평가 측 시험·비공개 세트가 목표를 제대로 재는지** 점검 | 보완 증분마다의 재측정 감사(새 정보가 적었다) |
| 평가 | claude-code | 측정·감사·게이트·시험 자산 관리, 결함을 원인 유형별 인계 티켓(`docs/handoff/`)으로 정리 | 제품 코드 수정 |
| 승인 | 사용자(변호사) | 봉인 시험문서 보관, 기준선 변경 승인, 병합 승인 | — |

### 보호 경로(구현 에이전트는 수정하지 않는다. `.github/CODEOWNERS`가 사용자 검토를 요구한다)
- `tests/acceptance/**`, `tests/fixtures/**`
- `scripts/verify_all.py`, `scripts/eval_testset.py`, `scripts/scorecard.py`, `scripts/score_gate.py`, `scripts/probe_document.py`, `scripts/score_report.py`, `scripts/check_case_literals.py`, `scripts/check_version_policy.py`, `scripts/review_feedback_report.py`
- `docs/scorecards/**`, `.github/workflows/score-gate.yml`
- `docs/AGENT_ROLES.md`, `AGENTS.md`, `CLAUDE.md`, `.github/CODEOWNERS`

구현 에이전트가 보호 경로의 변경이 필요하다고 판단하면 `docs/handoff/`에 요청 티켓을 남긴다. 평가 에이전트가 검토해 반영한다.

## 2. 작업 순환(서면 한 건이 아니라 원인 유형 한 묶음 단위)
1. **평가 — 첫 점수 기록.** 새 서면은 고치기 전 코드로 먼저 측정하고 `docs/scorecards/first_touch_log.jsonl`에 남긴다(`scripts/probe_document.py record`). 고친 뒤의 점수는 일반화 근거가 아니다.
2. **평가 — 인계 티켓.** 실패를 서면 번호가 아니라 근본 원인 유형(입력 단계, 규칙 부족, 오탐 등)으로 묶어 `docs/handoff/`에 적는다. 수용 기준은 측정 도구의 출력으로 쓴다.
3. **구현 — 원인 유형 단위 수정.** 사건 고유 값(당사자명·사건번호·금액·수치)을 코드에 넣지 않는다. 새 규칙은 값·문장이 다른 양성 3건 이상과 대조군 3건 이상의 시험을 함께 낸다(`AUDIT_v6.md`).
4. **평가 — 게이트.** `python scripts/verify_all.py --base <라운드 시작 SHA>`(구현 측도 보고 전에 같은 명령을 돌린다). `scorecard.py` → `score_gate.py`는 그 안의 한 단계다. 고정 시험 점수 하락·오탐 증가·사건 값 게이트 위반, 그 밖의 실패 단계가 있으면 병합하지 않는다.
5. **주 1회 릴리스.** 릴리스 노트에 성적표를 붙이고 `docs/scorecards/HISTORY.md`를 갱신한다. 하루 수십 건 단위의 개별 커밋은 검증 속도를 넘는다.

### 2.1 반복 운영 규칙(2026-10-03 개정)
- **설계 메모 먼저:** 검출 휴리스틱(개인정보·법리 규칙)을 바꾸는 작업은 구현 측이 1쪽 이내 설계 메모(방법, 일반화 근거, 유출·과탐 위험, 시험 계획)를 `docs/handoff/requests/`에 첫 커밋으로 낸다. 평가 측은 비공개 범주에 비춰 '통하지 않을 이유'만 회신한다(입력은 공개하지 않는다).
- **멈춤 규칙:** 같은 지표가 같은 접근으로 두 번 실패하면 세 번째 시도 전에 설계 메모를 필수로 다시 낸다(예: 과마스킹 낱말 목록 — 8차·8B).
- **단일 점검:** 구현 보고 전 `python scripts/verify_all.py --base <라운드 시작 SHA>`를 CI와 같은 환경(Linux·Python 3.11·tesseract 5.3.4)에서 돌리고 콘솔 출력을 보고서에 그대로 붙인다. 평가 측은 같은 명령으로 다시 잰다.
- **자동 재측정:** 구현 PR이 열리면 평가 측이 구독해 비공개 세트를 돌리고 PR에 **건수만** 코멘트한다. 사용자의 전달은 지시서 전달과 병합 승인으로 줄인다.
- **평가 측 지시서 범위:** 원인·실패 시험·수용 기준·제약까지 쓴다. 구현 방법은 구현 측이 설계 메모로 정한다.
- **기록은 한 곳에:** 라운드 판정은 `docs/scorecards/f1_gate_verdict.md`에 표 하나로, HISTORY에는 측정값만, `docs/handoff/README.md`에는 결정만 남긴다.
- **일자별 추이표(2026-10-04 사용자 지시):** 평가 측은 측정일마다 `docs/scorecards/DAILY_TREND.md`에 한 행(성능 점수·주요 기능·개선·회귀·평가 개요)을 남기고, 평가 결과를 제시할 때 그 최근 행을 함께 낸다. 이 표는 HISTORY·판정서의 요약이며 새 수치를 이 표에만 적지 않는다.

## 3. 완료의 정의
- 고정 시험(개발·홀드아웃) 점수가 기준선 이하로 내려가지 않고 오탐이 늘지 않는다.
- `tests/acceptance/`가 통과한다(알려진 미해결은 strict xfail로 기록되어 있어야 하며, 해결되면 xfail을 지운다).
- 봉인 시험 점수가 기준선 이하로 내려가지 않는다(사용자가 실행).

## 4. 봉인 시험
- 문서와 정답은 **저장소 밖**(사용자 PC 또는 비공개 저장소)에 둔다. 저장소에 올리거나 에이전트에게 열어 주지 않는다. 에이전트는 점수(종합·재현율·오탐 수)만 본다.
- 실행: `python scripts/scorecard.py --sealed-dir <경로>`. 봉인 세트는 개발 시험과 같은 형식(`ground_truth.json`, `match_spec.json`, PDF)이며, 출력은 집계 숫자뿐이다. 문서별·항목별 상세는 봉인 폴더 안 `.sealed_out/`에만 쓴다.
- 점수를 확인한 문서는 개발용으로 옮기고, 새 문서로 봉인 세트를 교체한다. 같은 문서를 두 번 시험 삼지 않는다.

## 5. 커밋·병합 규칙
- **버전은 성능 기준으로만 올린다**(사용자 지시 2026-10-02). 구현 커밋은 프로그램 버전을 바꾸지 않는다. 평가 에이전트가 같은 조건에서 잰 성능으로 상향 자리(정수 급격·소수점 첫째 자리 일부·둘째 자리 미세)를 판정서(`docs/scorecards/version_verdicts.json`)로 정하고, 구현 에이전트는 판정서대로 버전 커밋 1개만 만든다. 자세한 기준·절차: `docs/scorecards/VERSION_POLICY.md`, 점검: `scripts/check_version_policy.py`.
- 커밋 메시지 끝에 `Agent: implementer` 또는 `Agent: evaluator`를 적는다. 구현 커밋에는 게이트 출력의 점수 변화를 함께 적는다.
- 기준선(`docs/scorecards/baseline.json`)은 낮추지 않는다. 낮춰야 하면 사유를 티켓으로 남기고 사용자가 승인한다.
- **릴리스(2026-10-04 사용자 결정):** `main` 병합이 곧 배포다(Render가 `main` 푸시 시 자동 재배포). 배포는 평가 통과·봉인 시험·열린 P1 회귀 0·사용자 승인으로 하고, **버전 상향과는 분리한다**(상향 요건을 못 채우면 버전 유지로 배포). 평가 측이 `Steve_ACASiaLAW` → `main` 릴리스 PR을 열고, 사용자가 병합하며, 배포 직후 사용자가 온라인 점검 1회를 실행해 결과 JSON을 평가 측에 준다. 첫 릴리스는 8C 수용 뒤. 절차: `docs/scorecards/RELEASE_PROCEDURE.md`.
- GitHub 설정(사용자가 직접): 기본 브랜치 보호 규칙에서 `score-gate`·`CI` 상태 확인 필수, Code Owners 검토 필수를 켠다. 이 저장소의 워크플로 파일만으로는 병합을 막지 못한다.
