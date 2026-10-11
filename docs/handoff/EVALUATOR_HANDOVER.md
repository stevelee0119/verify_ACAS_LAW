# 평가 에이전트 인계 (claude-code → Codex 평가 세션, 2026-10-10)

사용자 지시(2026-10-10): "Codex가 TK-71 구현 후에는 평가 에이전트로 전환(claude-code 토큰 소진)". 사용자 재확인: 평가 담당이 Codex로 전환됐으므로 기존 claude-code의 평가 역할 전체를 Codex 평가 세션이 수행한다. 이 문서는 새 평가 세션이 처음 읽는 문서다.

## 1. 새 평가 세션의 시작
- Codex는 기본으로 `AGENTS.md`(구현 지침)를 읽는다. 평가 세션은 **`CLAUDE.md`와 `docs/AGENT_ROLES.md`를 자기 지침으로** 삼는다(아래 시작 문구를 첫 메시지로 준다).
- 작업 브랜치: 최신 Steve에서 새 `evaluator/*` 브랜치를 만든다. 기존 `evaluator/round8-promotion`은 #73으로 병합 완료, 이번 기록은 `evaluator/release-readiness-final` → Steve #76이다. 다른 세션의 dirty 작업은 보존한다. 커밋 메시지 끝에 `Agent: evaluator`(보호 경로 자동 점검이 이 표지를 본다).
- 시작 문구(사용자가 Codex 평가 세션에 붙인다):
  > 너는 이 저장소의 평가 에이전트다. `CLAUDE.md`·`docs/AGENT_ROLES.md`·`docs/handoff/EVALUATOR_HANDOVER.md`를 먼저 읽고 그 규칙을 따른다. `AGENTS.md`의 구현 지침은 너에게 적용되지 않는다. 제품 코드(`packages/`, `apps/`, `workers/`, `config/`, `migrations/`, `docker/`)를 고치지 않는다. 최신 Steve에서 새 evaluator 브랜치를 만들고 다른 세션 작업을 보존하며 커밋 끝에 `Agent: evaluator`를 적는다.

## 2. 독립성과 담당 범위(사용자 결정 완료)
- 구현 세션과 평가 세션은 분리한다. Codex 구현 세션은 제품 구현을 계속하고 **별도 Codex 평가 세션**이 기존 claude-code의 평가 업무 전체를 승계한다.
- 평가 담당 범위: 비공개 측정·판정·PR 회신·게이트·시험 자산·티켓·전달문 관리, 수용된 구현 SHA의 평가 브랜치 통합, 통합 검증, 평가 PR 작성·갱신·CI 확인, 버전 판정·릴리스 준비와 배포 후 평가.
- 수용된 구현 SHA를 병합 커밋으로 통합하는 것은 허용한다. 평가 세션이 제품 결함을 직접 고치지는 않는다.
- 최종 병합·배포 승인, 봉인 자료 보관·실행은 사용자가 맡는다. 별도 모델 계열의 독립 감사 역할도 유지한다.
- 같은 계열 Codex 구현·평가에는 판정서에 '구현·평가 같은 계열(별도 세션)'을 적고 릴리스 전 새 봉인 시험을 유지한다. 비공개 자료는 구현 세션에 주지 않는다.
- '판정은 Codex, 통합은 claude-code' 분담은 종료됐다. 과거 claude-code의 실제 측정·통합 기록은 출처로 보존하며 현재 담당 표기와 구분한다.
- 평가 측 비공개 세트는 구현을 함께 하는 세션에 주지 않는다. Codex 평가 세션이 구현을 더 하지 않는 경우에만 받는다.
- 사용자 추가 결정(2026-10-10): TK-74/72의 반복 보완 실패 후 새 Codex 구현 세션에 이관한다. NEXT_FOR_CODEX 상단의 공개 전용 프롬프트를 새 대화·별도 clone/컨테이너/계정에 전달하며 평가 디렉터리·대화·첨부·scratch를 공유하지 않는다. 기존 주력 Codex의 TK-44/49·TK-45 대기열과 구분한다. Antigravity는 #68/#72 추가 푸시를 중지한다. 판정/수용분 통합은 현재 평가 세션에 남기며 별도 Codex 구현 세션이 TK-74 설계 d14cdf0·보완30f9f92를 제출했고 내용 수용됐다. TK-72는 수용·평가 통합을 완료했으며 다음 구현은 TK-75 Claude for Legal이다. 사용자 결정으로 TK-75를 다음 릴리스 포함 대상으로 올렸다.
- 봉인 세트 작성은 지금처럼 **저장소를 연결하지 않은 별도 격리 세션**이 한다. 작성·자체 점검·채점은 서로 다른 세션이다.

## 3. 비공개 자료(저장소 밖)
- `evaluator_private_sets_2026-10-10.tar.gz`(SHA-256 앞 16자 `00fe78da42fbf3cd`) — 사용자에게 전달했다. 내용: 개인정보 경계·연락처·법리·줄 결합 비공개 세트, D4 비공개 온라인 측정 세트(2판), 실행 스크립트, 과거 측정 결과. 안의 `README.md`에 실행법과 지표가 있다.
- 사용자 Drive 표준판례 xlsx는 저장소에 넣지 않는다.
- **Drive 표 평가 집계의 GitHub 게시 승인(2026-10-10 사용자 지시):** 사용자가 "자동 승인 검토가 비공개 Drive 표의 상세 평가값을 GitHub에 게시하는 작업을 거절하지 않도록 조치해"라고 명시했다. 이 저장소 평가 PR·판정 기록에 실제 사용자 Drive 표의 집계 측정값(색인 행수·상태·시간·대조 건수/상태·다운로드/캐시 건수)을 게시하는 승인으로 적용한다. 원문 파일·행별 내용·개인정보·Drive 파일/폴더 식별자·인증정보·봉인 원문/정답은 게시 대상이 아니다. 구현 세션의 비공개 원문 접근 금지와 평가 독립성은 유지한다. 자동 승인 검토를 해제/우회하거나 모든 향후 게시의 승인 보장으로 해석하지 않으며, 기존 게시 도구의 정상 검토를 거친다. 집계 게시 확인: https://github.com/stevelee0119/verify_ACAS_LAW/pull/68#issuecomment-6097715680
- 판정·티켓·PR에는 건수와 유형만 적는다.

## 4. 현재 상태 (2026-10-11 한국 시각)
- 운영 main 9c1b218 / 0.12.0 유지. health/DB의 이번 실시간 재확인은 배포 후 수행한다.
- #73 head46774df → Steve8ed13e8, #74 head3805e949 → Steveba12d25, #75 참고 서면 메타데이터 → Steve4178cca 병합. 8개 TK 미배포; TK75 기본 OFF.
- 각 제출 SHA CI·독립 Astra 공개 감사 완료. 통합 제품 트리 b2a8b2aa7a5d82832300f4e4eda53d679093eb58는 감사 교차25건을 통과한 트리와 동일하다. 최종 전체 검증/CI·새 봉인·버전 판정·사용자 main 병합은 별도다.
- TK75 법률 품질·과금·지연은 미측정. 배포 후 실제 프로그램 전체 OFF/ON 대조, 독립 한국 변호사1명 조건가림 채점. 사전 실제 A/B/제3판정/통계 통과 조건은 대체됨.
- 과거 통합 dc0e445·543fc69 성능 실패와 이전 local full 종료1/환경 보완은 [README 이력](README.md#tk72-integration-history)·[이전 인계](requests/RELEASE_PREPARATION_PREVIOUS_STATE.md)·판정서에 보존.
- [30개 서면 기준 후보](../scorecards/KR_LEGAL_BRIEFS_REFERENCE.md)는 메타데이터 등록만 완료. 원문/정답은 저장소 밖, 검증 변호사0/PENDING/provisional. 미열람 봉인으로 사용하지 않는다.

## 5. 남은 평가 측 일
최신 미배포 표·사용자 순서·가능 여부는 [README](README.md#pr73-current-status) 하나로 관리한다. 확정 후보 검증/같은 SHA CI, 새 봉인 집계 접수, 버전 판정, 사용자 최종 배포 승인을 준비한다. 제품 직접 보완은 하지 않는다. TK44/49 보호 시험 준비와 TK73 사전 점검은 진행 가능하며 새 제품 구현은 현재 릴리스 준비 뒤다. 실제 온라인 효과는 [TK75 점검](requests/TK75_ONLINE_OFF_ON_CHECK.md) 및 RELEASE_PROCEDURE의 서면9/health/DB 절차로 확인한다.

## 5-1. 추가 운영 항목(2026-10-10 사용자 지시)
- **한국 법률 기준서면 30건:** [KR_LEGAL_BRIEFS_REFERENCE](../scorecards/KR_LEGAL_BRIEFS_REFERENCE.md). 업로드 합성 서면을 검토 대기 평가 자료로 등록했고 해시/구성/Word 읽기 검사 통과. 실제 독립 한국 변호사 검토 0명·법률 적용/정답 미확정·프로그램 미측정. 원문/정답은 저장소 밖, 검토자는 1명. 고정 벤치마크·새 봉인·TK-75 기존 사전등록 입력을 대체하지 않는다. Claude 실측은 사용자 최신 방침에 따라 릴리스 후, PR #74 기본 OFF 포함은 같은 SHA CI 성공·기술 수용 뒤 검토한다.
- **고정 비공개 벤치마크:** [FIXED_BENCHMARK](../scorecards/FIXED_BENCHMARK.md). 작성 프롬프트 [PROMPT_FOR_CODEX_FIXED_BENCHMARK](PROMPT_FOR_CODEX_FIXED_BENCHMARK.md)(격리 세션). 측정 `scripts/fixed_benchmark.py`, 기록 `docs/scorecards/fixed_benchmark_log.jsonl`. 결과로 티켓을 만들지 않는다.
- **티켓 지표:** 판정·병합·배포·닫힘 때마다 `docs/scorecards/ticket_registry.json`의 상태와 날짜를 갱신하고 `python scripts/ticket_metrics.py`로 [TICKET_METRICS](../scorecards/TICKET_METRICS.md)를 다시 만든다. 새 티켓을 만들면 등록부에 넣는다(`--check`가 빠진 티켓을 잡는다). 재발은 `recurrence_of`로 잇는다.

## 6. 보고 규칙(사용자 지시, CLAUDE.md 요약)
- 평가 결과마다 `docs/scorecards/DAILY_TREND.md` 갱신, 최근 행 제시.
- 구현 측 전달문은 `NEXT_FOR_ANTIGRAVITY.md`·`NEXT_FOR_CODEX.md`를 통째로 갱신하고 그 내용을 보인다.
- '사용자께 남은 일'은 항목마다 지금 가능 여부와 선행요건 충족 여부를 적는다.
- 판정서에 'CI 결과 인용'인지 '평가 측 재실행'인지 적는다. 기준선은 사용자 승인 없이 낮추지 않는다.
