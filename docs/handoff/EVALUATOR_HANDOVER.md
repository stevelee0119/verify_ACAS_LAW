# 평가 에이전트 인계 (claude-code → Codex 평가 세션, 2026-10-10)

사용자 지시(2026-10-10): "Codex가 TK-71 구현 후에는 평가 에이전트로 전환(claude-code 토큰 소진)". 사용자 재확인: 평가 담당이 Codex로 전환됐으므로 기존 claude-code의 평가 역할 전체를 Codex 평가 세션이 수행한다. 이 문서는 새 평가 세션이 처음 읽는 문서다.

## 1. 새 평가 세션의 시작
- Codex는 기본으로 `AGENTS.md`(구현 지침)를 읽는다. 평가 세션은 **`CLAUDE.md`와 `docs/AGENT_ROLES.md`를 자기 지침으로** 삼는다(아래 시작 문구를 첫 메시지로 준다).
- 작업 브랜치: `evaluator/round8-promotion`(평가 측 PR은 이 브랜치 → `Steve_ACASiaLAW`). 커밋 메시지 끝에 `Agent: evaluator`(보호 경로 자동 점검이 이 표지를 본다).
- 시작 문구(사용자가 Codex 평가 세션에 붙인다):
  > 너는 이 저장소의 평가 에이전트다. `CLAUDE.md`·`docs/AGENT_ROLES.md`·`docs/handoff/EVALUATOR_HANDOVER.md`를 먼저 읽고 그 규칙을 따른다. `AGENTS.md`의 구현 지침은 너에게 적용되지 않는다. 제품 코드(`packages/`, `apps/`, `workers/`, `config/`, `migrations/`, `docker/`)를 고치지 않는다. 작업 브랜치는 `evaluator/round8-promotion`, 커밋 끝에 `Agent: evaluator`.

## 2. 독립성과 담당 범위(사용자 결정 완료)
- 구현 세션과 평가 세션은 분리한다. Codex 구현 세션은 제품 구현을 계속하고 **별도 Codex 평가 세션**이 기존 claude-code의 평가 업무 전체를 승계한다.
- 평가 담당 범위: 비공개 측정·판정·PR 회신·게이트·시험 자산·티켓·전달문 관리, 수용된 구현 SHA의 평가 브랜치 통합, 통합 검증, 평가 PR 작성·갱신·CI 확인, 버전 판정·릴리스 준비와 배포 후 평가.
- 수용된 구현 SHA를 병합 커밋으로 통합하는 것은 허용한다. 평가 세션이 제품 결함을 직접 고치지는 않는다.
- 최종 병합·배포 승인, 봉인 자료 보관·실행은 사용자가 맡는다. 별도 모델 계열의 독립 감사 역할도 유지한다.
- 같은 계열 Codex 구현·평가에는 판정서에 '구현·평가 같은 계열(별도 세션)'을 적고 릴리스 전 새 봉인 시험을 유지한다. 비공개 자료는 구현 세션에 주지 않는다.
- '판정은 Codex, 통합은 claude-code' 분담은 종료됐다. 과거 claude-code의 실제 측정·통합 기록은 출처로 보존하며 현재 담당 표기와 구분한다.
- 평가 측 비공개 세트는 구현을 함께 하는 세션에 주지 않는다. Codex 평가 세션이 구현을 더 하지 않는 경우에만 받는다.
- 봉인 세트 작성은 지금처럼 **저장소를 연결하지 않은 별도 격리 세션**이 한다. 작성·자체 점검·채점은 서로 다른 세션이다.

## 3. 비공개 자료(저장소 밖)
- `evaluator_private_sets_2026-10-10.tar.gz`(SHA-256 앞 16자 `00fe78da42fbf3cd`) — 사용자에게 전달했다. 내용: 개인정보 경계·연락처·법리·줄 결합 비공개 세트, D4 비공개 온라인 측정 세트(2판), 실행 스크립트, 과거 측정 결과. 안의 `README.md`에 실행법과 지표가 있다.
- 사용자 Drive 표준판례 xlsx는 저장소에 넣지 않는다.
- 판정·티켓·PR에는 건수와 유형만 적는다.

## 4. 현재 상태(2026-10-10)
- 운영: `main` 9c1b218 = 0.12.0(태그 `v.0.12.0`). 배포 확인(health 9c1b218·db ok). 배포 직후 온라인 서면9 21/23(규칙 2판, 처음 보는 실패 0).
- 고정 81.7/79.2/0. 은퇴 세트 4종(통합 head): 19.0/0 · 29.6/0.296/0 · 36.2/0.362/0 · 15.2/0.302/3(A 3).
- TK-24 #53·TK-69 #56 통합 PR #67은 Steve 03fdcdb에 병합 완료. TK-43 #62 e4867e7 수용·평가 측 통합(deed155), 통합 검증은 과거 claude-code 재실행 full 종료 0. 열린 평가 통합 PR #69에 TK-70 수용 SHA db21f19도 병합 커밋 b92100d로 추가했다. 현재 통합·검증·CI 확인은 Codex 평가 세션 담당.
- 측정 조건 기본값: 오프라인(`LV_ALLOW_NETWORK=0`), Linux, Python 3.11.15, tesseract 5.3.4 kor. 다른 조건의 점수를 증감으로 비교하지 않는다.

## 5. 남은 평가 측 일(순서대로)
1. TK-43·TK-70 통합 PR #69: Codex 통합 e10a335의 full 원본 종료 1(도구 환경 실패 1, 환경 보완 별도 2 passed), 고정 81.7/79.2/0·비공개 보호 유지. 검증 SHA e10a335 필수 CI 모두 성공. 제품·시험 실행 코드가 같은 최종 기록 커밋의 CI는 PR #69 체크 상태로 확인하고 성공 뒤 사용자 병합 승인 단계로 넘긴다. PR #67 병합 선행요건이 충족되어 Antigravity TK-72 착수 가능.
2. **TK-73 사전 점검**(티켓 5절): 임시 패치로 은퇴 세트 4종·고정 시험을 잰 뒤 배정 결정을 사용자에게 받는다.
3. **TK-44·49 조건 2**: R7-05 5건·R6-03 3건을 boundary_signal 계약 시험으로 고치고, 합성 PDF 글자 좌표 → parse_document 보호 시험(strict xfail)을 신설한다. 비공개 hidden_join은 오염돼 수용 전 새로 짓는다.
4. 완료한 판정: TK-43 e4867e7 내용 수용, TK-70 db21f19 내용 수용, TK-74 c6d0f19 설계 조건부 승인(구현 착수 가능). 판정 원문은 f1_gate_verdict.md와 해당 PR 회신. 구현 세션에는 비공개 입력을 전달하지 않는다.
5. 다음 릴리스에는 TK-24·TK-69·TK-43 등 오프라인 엔진 변경이 포함되므로 새 봉인 시험이 필요하다. 별도 격리 작성 세션·사용자 실행 절차를 유지한다. TK-70 단독 RAG 변경에는 봉인이 없지만 묶음 릴리스 요건을 면제하지 않는다.
6. 배포 후 비공개 온라인 세트 v2·서면9를 여러 실행으로 점검한다. 실제 사용자 Drive 표는 저장소 밖에서 TK-74 수용 때 실제 선별 동기화 경로로 평가한다.

## 5-1. 추가 운영 항목(2026-10-10 사용자 지시)
- **한국 법률 기준서면 30건:** [KR_LEGAL_BRIEFS_REFERENCE](../scorecards/KR_LEGAL_BRIEFS_REFERENCE.md). 업로드 합성 서면을 검토 대기 평가 자료로 등록했고 해시/구성/Word 읽기 검사 통과. 실제 독립 한국 변호사 검토 0명·법률 적용/정답 미확정·프로그램 미측정. 원문/정답은 저장소 밖, 검토자는 1명. 고정 벤치마크·새 봉인·TK-75 기존 사전등록 입력을 대체하지 않는다. Claude 실측은 사용자 최신 방침에 따라 릴리스 후, PR #74 기본 OFF 포함은 같은 SHA CI 성공·기술 수용 뒤 검토한다.
- **고정 비공개 벤치마크:** [FIXED_BENCHMARK](../scorecards/FIXED_BENCHMARK.md). 작성 프롬프트 [PROMPT_FOR_CODEX_FIXED_BENCHMARK](PROMPT_FOR_CODEX_FIXED_BENCHMARK.md)(격리 세션). 측정 `scripts/fixed_benchmark.py`, 기록 `docs/scorecards/fixed_benchmark_log.jsonl`. 결과로 티켓을 만들지 않는다.
- **티켓 지표:** 판정·병합·배포·닫힘 때마다 `docs/scorecards/ticket_registry.json`의 상태와 날짜를 갱신하고 `python scripts/ticket_metrics.py`로 [TICKET_METRICS](../scorecards/TICKET_METRICS.md)를 다시 만든다. 새 티켓을 만들면 등록부에 넣는다(`--check`가 빠진 티켓을 잡는다). 재발은 `recurrence_of`로 잇는다.

## 6. 보고 규칙(사용자 지시, CLAUDE.md 요약)
- 평가 결과마다 `docs/scorecards/DAILY_TREND.md` 갱신, 최근 행 제시.
- 구현 측 전달문은 `NEXT_FOR_ANTIGRAVITY.md`·`NEXT_FOR_CODEX.md`를 통째로 갱신하고 그 내용을 보인다.
- '사용자께 남은 일'은 항목마다 지금 가능 여부와 선행요건 충족 여부를 적는다.
- 판정서에 'CI 결과 인용'인지 '평가 측 재실행'인지 적는다. 기준선은 사용자 승인 없이 낮추지 않는다.
