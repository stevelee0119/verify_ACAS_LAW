# PR #73 / #74 독립 릴리스 감사

작성: 2026-10-10 UTC(태스크 기준일). 감사 역할: 별도 세션, 생성 시 `gpt-6-astra` 지정(주 에이전트가 전달한 실행 설정). 구현·평가 세션과 분리했으나 벤더 전체의 독립성까지 입증한 것은 아니다.

## 판정

**검토한 범위에서 새 P1 회귀는 발견하지 못했다. PR #73 최종 SHA와 PR #74 최종 SHA의 기술 수용·다음 릴리스 후보 통합을 권고한다. TK-75는 기본 OFF를 유지한다.** 이는 두 PR을 합친 최종 SHA의 CI/릴리스 게이트 또는 실제 법률 품질 향상을 확인했다는 판정은 아니다.

확인한 비차단 P2는 **기존 TK-75 평가 티켓과 #73 PR 본문에 남은 폐기된 사전 A/B 수용 조건**이다. 평가 측이 최신 결정으로 정리하면 된다. 실제 A/B 미실시를 이유로 기술 수용을 보류하거나 대규모 사전 통계 게이트를 되살릴 근거는 없다.

## 범위·접근 경계

- 기준 Steve: `ad25f513fff0891d8f7459caacb6c94d496bc8fc`.
- #73: `46774df238c6c67a34d2ffead38f1df55f7ceabe`, TK-56/74/72 통합. TK-72 최종 구현 `f18425386165e3267c3fcd9fe4f4a9905e6828ef`와 통합 `c26afede1bd99a4ef7238efcb6a14016ceac3df9`의 결과를 포함한다.
- #74: `3805e9495985626224c8c28ab06811a8068fb034`, TK-75.
- `/workspace/evaluator-record/AGENTS.md`, `docs/AGENT_ROLES.md`를 읽고 감사 역할의 공개 코드·시험 타당성·주장 표본 재현 범위를 적용했다. 클라우드 환경 런타임 skill로 실행 환경 상태를 확인했다.
- GitHub 공개 코드/PR/CI 및 새로 만든 합성 입력만 사용했다. private/scratch 평가 폴더, attachments, 사용자 첨부, 봉인/정답/원문 corpus, 다른 세션의 dirty 평가 기록은 읽지 않았다. 제품·시험·게이트와 GitHub를 변경하지 않았고 `verify_all`을 실행하지 않았다. 산출물은 `/workspace/artifacts/`에만 작성했다.

## 독립 조회·실측과 제출 주장 구분

### 같은 SHA CI: 독립 조회, 재실행 아님

GitHub의 commit→workflow 및 workflow→jobs/steps를 직접 조회했다. 아래 네 run은 모두 `completed/success`다.

| 대상 | CI | 점수 게이트 |
|---|---|---|
| #73 `46774df` | [38094778368](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/38094778368) | [38094778357](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/38094778357) |
| #74 `3805e94` | [38094767858](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/38094767858) | [38094767864](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/38094767864) |

각 CI의 SQLite, PostgreSQL/Celery, 통합 상태 job, Docker OCR readiness가 성공했다. 점수 게이트의 성적표·수용 시험·원장·회귀·하드코딩·시험 약화·보호 경로·버전 단계도 성공했다. 이 감사에서는 CI 원문 로그의 모든 개별 시험과 수치까지 다시 검증하지 않았다.

### 감사가 직접 실행한 공개 합성 표본

TK-72는 GitHub exact SHA의 필요한 공개 모듈만 artifact 폴더에 받아 독립 로딩했다. Python **3.12.14**, 네트워크/모델 호출 없는 표본이다. CI의 Linux/Python 3.11 환경과 다르다. 뒤이어 제공된 exact Git 복원 환경에서는 별도 Python **3.11.15** venv로 TK-75와 통합 보호 시험을 실행했다.

| 점검 | 결과 | 범위·한계 |
|---|---|---|
| 법령 앵커 매처 10,000개 + 학술 매처 10,000개 | 차이 **0**, 총 0.8278초 | 새 seed `817031`; 기존 regex의 span/groups/groupdict와 비교. 전체 문서 출력 시험은 아님 |
| base `ad25f51` vs head `46774df` 전체 인용 필드 | 새 합성 500문장 × 직접/문서 경로 = **1,000 비교, 차이 0**, 0.8613초 | seed `614871`; 양쪽 각 reading_text를 사용. CIT UUID와 이를 참조하는 ID만 정규화. 블록 반복·조문/학술/판례/해석례/인용문/참조 혼합 |
| 기존 32,000회 반복 실제 `extract_citations` | 992,000자, **0.295740초**, 반환 1개, GC ON | 같은 블록의 동일 인용 중복 제거 계약에 따른 1개. 단회 로컬 측정이며 CI SLA 대체 불가 |
| 별도 고유 조문 2,000→8,000개 | 반환 2,000→8,000개; **0.038941→0.170614초**, 약 **4.38배** | 반복 동일값에만 빠른지 확인하는 별도 표본. 전체 입력군의 점근 복잡도 증명은 아님 |

추가 감사 실측: #74 exact `3805e949`에서 공개 합성 `tests/korean_law_profile/test_review_path.py` **70건 통과(exit 0)**. 통합 후보 `2eb56ec324e9e1c2908ac45a9fcb87fb580685e9`(부모 `46774df` + `3805e949`)에서는 `test_review_document_real_router_path`, `test_input_output_budget_timeout_policy_guards`, `test_failure_and_truncation_keep_original_fallback_contract`, `test_snapshot_preserves_switch_and_rejects_drift`의 파라미터 포함 **25 passed in 2.05s**. 양쪽 실행 후 Git 작업 트리가 clean임을 확인했다.

재현 자료: `audit_public_grammar_probe.py/.json`, `audit_public_document_probe.py/.json`, `audit_public_runtime_probe.json`, `audit_public_modules/`, `audit_citation_exact_source.py`(모두 이 보고서와 같은 artifact 폴더).

### 직접 재측정하지 않은 수치

#73 제출의 **942 합성 비교 차이 0, 0.289014초**, 공개 점수 **81.7/79.2/FP 0**, #74의 기존 **70 passed (2.96s)**는 제출/평가 보고 수치다(감사는 같은 70건을 별도 환경에서 통과 확인했으며 2.96초를 재측정한 것은 아니다). 위 감사 실측과 합산하거나 같은 실행으로 표현하지 않는다. 과거 1.2964초·중간 1.0752초·학술 증가비 실패는 삭제하지 않으며, 최종 SHA의 성공이 당시 실패 사실을 바꾸지 않는다. 실제 Claude 법률 품질·과금·지연은 여전히 **미측정**이다.

## 발견과 근거

### P1: 확인된 새 회귀 없음

이 결론은 공개 코드·CI 상태·표본 범위에 한정된다. 비공개 평가나 봉인 점수를 추정하지 않았다.

### P2: 오래된 사전 A/B 조건이 현재 문서와 충돌함 — 비차단 정리 권고

[#73 TK-75 티켓](https://github.com/stevelee0119/verify_ACAS_LAW/blob/46774df238c6c67a34d2ffead38f1df55f7ceabe/docs/handoff/TK-75_claude_legal_korean_workflow.md)의 4절 및 7절은 온라인 평가 전 제품 개선 수용/통합 금지를 현재형으로 남긴다. [#73 PR](https://github.com/stevelee0119/verify_ACAS_LAW/pull/73) Release boundary도 TK-75 actual-model A/B를 다음 선행 작업처럼 기술한다. 반면 [#74 평가 인계](https://github.com/stevelee0119/verify_ACAS_LAW/blob/3805e9495985626224c8c28ab06811a8068fb034/docs/handoff/requests/korean_law_review_evaluation_handoff.md)는 최신 사용자 결정대로 기본 OFF 기술 릴리스 후 온라인 비교로 명확히 대체한다.

과거 실패·판정 이력은 유지하되 기존 조건에 superseded 표기와 최신 적용 조건을 연결해야 한다. 제품 코드 결함이 아니고, 사전 A/B를 요구해 통합을 보류할 사유도 아니다. 주 에이전트의 평가 기록 정리 대상이다.

### TK-72 출력·일반화·원장 계약 검토

- 법령 필수 조문 위치에서 시작하는 탐색 창은 기존 법령명 문법의 최대 길이에서 유도된다. 학술 저자 수를 10명/600자처럼 새로 잘라내는 제한이 없다. 독립 20,000 문법 표본에서 기존 Match 계약과 차이가 없었다.
- SpanTracker는 미봉합 구간도 질의하고 비단조 구간은 AVL로 전환한다. 인용 순서/겹침 규칙을 단순 삭제로 우회하지 않는다.
- 실제 문서 경로의 중복 위치는 배열로 유지한다. 반환되는 인용에만 상세 파생값/UUID를 확정하면서도 후속 참조·quote 대상·claim 경계에는 모든 발생 위치를 사용한다. 1,000 전체 필드 비교와 별도 고유 조문 표본에서 계약 회귀를 발견하지 못했다.
- 동일 인용 32k 시험만으로 고유 인용/다양한 문서 전체의 성능을 입증할 수는 없다. 기존 시험의 `len >= 1`은 중복 제거 경로를 재는 성격이다. 추가된 직접 경로 count, 필드 해시·참조·quote·블록/표 시험과 이 감사의 고유 조문 표본이 이를 보완한다. 성능 개선만으로 검출 정확도 또는 버전 상승을 주장하면 안 된다.
- 두 자리 연도 헌재 분류는 순수 무변경 예외이므로 사용자 승인 예외로 남겨야 한다. 감사의 기준 비교 표본에는 이 알려진 예외를 넣어 무차이라고 위장하지 않았다.

### 시험 약화·하드코딩

- #73의 r8d/r8e 변경은 기존 strict xfail의 제거다. 실패를 숨기는 xfail 추가가 아니다.
- TK-74의 `chunk_count==0` 구 시험 한 건 교체는 `approved_test_marks.json`에 평가 승인과 이유가 특정돼 있다. 캐시 보존과 현재 eligible 격리/재선별을 동시에 검사하는 교체 방향은 제품 목표와 맞는다. 그 밖 기존 시간 상한·입력 크기를 낮춘 변경은 확인하지 못했다.
- 공개 코드 diff에서 사건별 입력 식별자/정답을 분기하는 새 하드코딩은 확인하지 못했다. 법령/학술 문법, 상수 프롬프트, 구조화 키 문법에 근거한다. 통과한 자동 하드코딩 게이트만으로 모든 과적합이 배제됐다고 주장하지 않는다.

### #73/#74 통합 호환성 및 보호 기능

두 PR은 동일 base를 사용한다. 겹치는 제품 파일은 `packages/llm_router/privacy.py`, `packages/rag_engine/review.py`다. #73의 TK-56 동적 값 검사·policy v4와 TK-74 표 상태/조회 기능에 #74가 정적 prompt 등록 및 request marker를 추가한다. diff 수준에서 기능을 서로 교체하거나 삭제해야 할 충돌은 보이지 않는다.

TK-75는 공급자 선택 후, 개인정보 검사·예산 예약·시간 제한 전에 Anthropic/PRIMARY_REASONER/허용 stage/원래 schema·prompt가 모두 맞을 때 적용된다. OFF 기본값, 다른 provider/fallback 원래 요청, marker 제거, 정적 prompt만 등록, 새 context의 동적 검사를 확인했다. 기존 공식 판정/Finding 승격은 추가하지 않는다. 설정 snapshot과 `+kr2` 캐시 분리도 코드와 공개 시험에 있다.

**통합 후보 `2eb56ec`의 겹침 diff에서 두 변경의 보존을 확인하고, 교차 경로 25건을 직접 실행해 통과했다.** 최초 기본 Python의 pytest·SQLAlchemy 부재는 이후 제공된 Python 3.11.15 venv로 해결했다. 전체 suite/`verify_all` 및 통합 후보 CI는 감사가 재실행하지 않았고 주 평가 에이전트의 최종 릴리스 검증 범위로 남긴다. 두 개별 PR의 green 또는 이 25건을 통합 SHA 전체 CI의 green으로 표기해서는 안 된다.

## 평가시험의 양방향 타당성

TK-56은 실제 인명/불확실 값 차단과 비인명 값 정상 전송의 양쪽을, TK-74는 색인 성공과 일반 표/실패/부분/격리/캐시 재선별을, TK-72는 양성/음성 문법과 위치·필드 보존을 함께 다룬다. TK-75의 합성 provider/HTTP adapter 시험은 경로·OFF/ON·다른 공급자·fallback·PII·예산·timeout·schema·근거 인용 거부를 검사한다. **이 시험들은 한국법 법률 판단의 정확성을 측정하지 않는다.** mocked 성공 응답이나 정적 지침이 존재한다는 사실에서 품질 개선을 추론하지 않았다.

최신 승인된 온라인 비교는 같은 릴리스·서면·Claude 모델·자료 snapshot·명시 기준일의 OFF/ON 실행을 짝지으며 한국 변호사 1명이 조건가림 채점한다. 중대한 오류/근거 없는 인용과 누락·오탐·부적절한 단정/과도한 유보를 양쪽 모두 기록해야 한다. 실패/재시도/fallback도 포함하고 fallback은 실제 Claude 결과와 구별한다. 한 채점자의 불확실 항목은 미결로 남기며 제3판정은 요구하지 않는다.

실제 OFF에는 새 jurisdiction/reference_date context가 없고 ON에는 생긴다. 따라서 실제 스위치 비교는 **지침과 context를 포함한 전체 기능 효과**이며 순수 system 지침 효과라고 부르면 안 된다. #74 문서는 이를 구분하며 양쪽 context를 같게 만드는 별도 builder는 선택 사항으로 둔다. 이 차이를 숨기지 않는 현재 계획은 사용자가 요청한 실제 프로그램 비교 목적에 맞는다.

평균 비용/p95 +20%는 참고 목표다. 작은 표본의 p95는 참고값으로만 보고하고 대규모 반복·통계 통과조건을 사전 게이트로 요구하지 않는다. 지출은 USD 40 또는 더 낮은 잔여/기존 한도를 유지한다. 중대한 법률 오류·허위 인용·보호 회귀는 중단/복귀 판단 대상으로 남긴다.

## 수용·보류 권고

- **수용/통합 권고:** 위 exact #73/#74, TK-75 기본 OFF, 실제 개선 미확인 표시.
- **평가 문서 정리:** 낡은 TK-75 사전 A/B 조건을 최신 사용자 결정으로 대체하고 과거 판정은 이력으로 보존.
- **최종 릴리스 판정은 별도:** 통합 candidate exact SHA의 필수 CI·기존 릴리스 게이트, 탐지/개인정보 변경 묶음에 적용되는 사용자 봉인 절차 및 사용자 승인 상태를 평가 측이 확인한다. 이 감사는 그 결과를 대신하지 않는다.
- **배포 후:** 승인된 간단한 OFF/ON 온라인 결과·비용·지연·실패/보호 비교를 한 보고서로 제출하고 계속 사용/보완/복귀를 권고한다. 지금 기본 ON 또는 품질 개선 입증을 권고하지 않는다.
