# 개발 에이전트 역할 분리

시행: 2026-09-30. 근거: 9/6~9/30 커밋 251건을 일자별로 다시 채점한 결과(고정 시험 점수는 9/26부터 정체, 처음 보는 서면은 수정 전 4/19),
그리고 정답지·시험문서가 저장소 안에 있어 구현자가 읽고 맞춰 고칠 수 있었던 구조. 구현과 평가를 다른 에이전트가 맡아 같은 손이 문제를 내고 푸는 일을 막는다.

## 1. 역할

| 역할 | 담당 | 하는 일 | 하지 않는 일 |
|---|---|---|---|
| 구현 | Antigravity | 제품 코드 수정(`packages/`, `apps/`, `workers/`, `config/`, `migrations/`, `docker/`) | 보호 경로(아래) 수정, 정답지·기준선 변경 |
| 평가 | claude-code | 측정·감사·게이트·시험 자산 관리, 결함을 원인 유형별 인계 티켓(`docs/handoff/`)으로 정리 | 제품 코드 수정 |
| 승인 | 사용자(변호사) | 봉인 시험문서 보관, 기준선 변경 승인, 병합 승인 | — |

### 보호 경로(구현 에이전트는 수정하지 않는다. `.github/CODEOWNERS`가 사용자 검토를 요구한다)
- `tests/acceptance/**`, `tests/fixtures/**`
- `scripts/eval_testset.py`, `scripts/scorecard.py`, `scripts/score_gate.py`, `scripts/probe_document.py`, `scripts/score_report.py`, `scripts/check_case_literals.py`, `scripts/check_version_policy.py`, `scripts/review_feedback_report.py`
- `docs/scorecards/**`, `.github/workflows/score-gate.yml`
- `docs/AGENT_ROLES.md`, `AGENTS.md`, `CLAUDE.md`, `.github/CODEOWNERS`

구현 에이전트가 보호 경로의 변경이 필요하다고 판단하면 `docs/handoff/`에 요청 티켓을 남긴다. 평가 에이전트가 검토해 반영한다.

## 2. 작업 순환(서면 한 건이 아니라 원인 유형 한 묶음 단위)
1. **평가 — 첫 점수 기록.** 새 서면은 고치기 전 코드로 먼저 측정하고 `docs/scorecards/first_touch_log.jsonl`에 남긴다(`scripts/probe_document.py record`). 고친 뒤의 점수는 일반화 근거가 아니다.
2. **평가 — 인계 티켓.** 실패를 서면 번호가 아니라 근본 원인 유형(입력 단계, 규칙 부족, 오탐 등)으로 묶어 `docs/handoff/`에 적는다. 수용 기준은 측정 도구의 출력으로 쓴다.
3. **구현 — 원인 유형 단위 수정.** 사건 고유 값(당사자명·사건번호·금액·수치)을 코드에 넣지 않는다. 새 규칙은 값·문장이 다른 양성 3건 이상과 대조군 3건 이상의 시험을 함께 낸다(`AUDIT_v6.md`).
4. **평가 — 게이트.** `python scripts/scorecard.py` → `python scripts/score_gate.py`. 고정 시험 점수 하락·오탐 증가·사건 값 게이트 위반이면 병합하지 않는다.
5. **주 1회 릴리스.** 릴리스 노트에 성적표를 붙이고 `docs/scorecards/HISTORY.md`를 갱신한다. 하루 수십 건 단위의 개별 커밋은 검증 속도를 넘는다.

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
- GitHub 설정(사용자가 직접): 기본 브랜치 보호 규칙에서 `score-gate`·`CI` 상태 확인 필수, Code Owners 검토 필수를 켠다. 이 저장소의 워크플로 파일만으로는 병합을 막지 못한다.
