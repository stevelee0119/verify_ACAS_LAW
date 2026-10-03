# 8차 보완(8B) 작업 지시서 — TK-52 수정 + PR #5 갱신 절차 (구현 담당 에이전트)

작성: 평가 에이전트(claude-code) 2026-10-03 · 시작 커밋: `antigravity/round8-privacy-boundary` @ 44e73f9(PR #5 head)
근거(모두 `Steve_ACASiaLAW`에 있다): 티켓 [TK-52](TK-52_round8_stem_leak_and_overblocking.md), [f1_gate_verdict.md '8차 1차 판정'](../scorecards/f1_gate_verdict.md), [HISTORY 17절](../scorecards/HISTORY.md). [8차 지시서](PROMPT_FOR_ROUND8_PRIVACY_BOUNDARY.md)의 0절(운영 원칙·정책)·0.2(보고 규칙)·R8-A·R8-B 수용 기준은 **그대로 유효**하다. 아래 전체를 붙여 넣어 쓴다.

작업 브랜치는 44e73f9에서 시작하므로 위 문서가 그 브랜치에는 없다. 다음처럼 읽는다(작업 브랜치에 `Steve_ACASiaLAW`를 병합하지 않는다):

```
git fetch origin Steve_ACASiaLAW
git show origin/Steve_ACASiaLAW:docs/handoff/TK-52_round8_stem_leak_and_overblocking.md
git show origin/Steve_ACASiaLAW:docs/scorecards/f1_gate_verdict.md
```

## 0. 시작점·범위·금지
1. **시작:** 44e73f9 위에 쌓는다. rebase·amend·강제 푸시 금지(fast-forward 관계 유지가 PR #5 갱신의 전제다).
2. **바꿀 수 있는 제품 파일:** `packages/pii_engine/**`, `packages/llm_router/privacy.py`, `packages/llm_router/router.py`의 검사 시점 부분. 그 밖은 먼저 `docs/handoff/requests/`로 사유를 올린다.
3. **시험:** 새 시험은 추가만 한다(새 파일 또는 구현 측이 만든 `tests/regression/test_r8a_structured_privacy.py`에 함수 추가). 기존 시험 함수 삭제·수정, skip/xfail 추가 금지. strict xfail 표시 제거는 평가 측 소관이다.
4. **어휘 출처:** 불용어·규칙을 보호 시험이나 평가 측 입력에서 뽑지 않는다. 평가 측은 보호 시험과 다른 비공개 입력으로 잰다(건수만 공개).
5. **되돌림:** 어느 묶음이 44e73f9 대비 개선 없이 다른 지표를 깨면 그 묶음을 되돌리고 한계로 보고한다.

## 1. 수정 묶음
순서대로 진행하고, 묶음마다 커밋하고, 커밋마다 `pytest -q tests/regression`을 돌린다.

### 8B-1 (P1, 먼저) 조사 재귀 분리로 실명이 빠지는 문제 — TK-52 1절
- **원인:** `detect()`가 꼬리 조사를 `for _ in range(3)`로 반복해 떼며 매번 불용어와 대조한다. 다음 조건이 겹치면 두 번째 분리에서 불용어에 걸려 PERSON 전체가 빠진다.
  - 이름 끝 음절이 조사처럼 보인다(은·는·이·가·도 등).
  - 앞 두 음절이 불용어다.
  - 그 실명 뒤에 조사가 붙는다.
- **측정:** 평가 측 비공개 명시 성명 stem 계열 16/16 → 9/16. 빠진 7건은 모두 `{당사자 라벨} {이름}{조사}` 형식이다.
- **요구:**
  1. 조사 분리는 한 번만 하거나, 분리 전 후보 전체가 이름 구조(성씨+이름 음절 수)를 만족하면 불용어 배제를 적용하지 않는다. 판단이 서지 않으면 마스킹한다(유출 0 하한).
  2. 새 시험(입력은 새로 짓는다): 불용어와 같은 글자로 시작하고 끝 음절이 조사형인 실명을 조사 유무와 여러 당사자 라벨에 걸쳐 넣는다. 모두 PERSON이어야 한다. TK-46·R7-07 계열은 유지한다.
- **수용:** stem 16/16, 이름 330/330·60/60, 라벨+실명 누락 0/180.

### 8B-2 (P2) 문맥 결합으로 정상 구조화 요청이 차단되는 문제 — TK-52 2절
- **원인:** `_collect_texts_from_value`가 모든 키의 `키: 값`, 형제 값 결합, 배열 이웃 결합을 `detect()`에 넘긴다. 그래서 라벨 뒤 일반 명사 과탐지가 요청 전체 차단(NOT_SENT)으로 번진다.
- **측정:** 사람 이름 없는 정상 구조화 요청 대조에서 차단 6/28 → 14/28. 차단 유형:
  - 라벨 키 값이 장소·직무 명사로 시작
  - 법인 표지(사단법인 등)로 시작
  - 라벨 낱말만 나열한 배열(이웃 결합이 두 라벨을 4음절 이름으로 읽음)
  - '○○ 측' 같은 지칭
- **요구:**
  1. 형제·이웃 결합은 '라벨 값 다음에 이름 구조 값이 올 때만' 문맥을 만들거나, 결합 문맥의 탐지 결과를 라벨 직후 후보로 한정한다. 결합 경계를 가로지르는 이름 후보(앞 값 끝 음절 + 뒤 값 첫 음절)는 만들지 않는다.
  2. `CONTEXT_LABEL_KEYS`는 실제 판정에 쓰거나 지운다. 보고서의 '단일 출처' 서술을 코드와 일치시킨다.
  3. fail-closed(검사 예외·판정 불가 시 미전송)와 등록 system/schema 정적 규칙은 유지한다.
  4. 새 대조 시험(실제 `LLMRouter.run` + 가짜 공급자):
     - **전송되어야 한다:** 비인명 당사자 값(법인·기관·지자체·'○○ 측'), 장소·직무 명사 값, 라벨만 나열한 배열, 사건 서술 값.
     - **미전송을 유지해야 한다:** 역할/이름 형제 쌍, 배열 쌍, 문자열 속 JSON의 실명.
- **수용:** 과차단 대조 ≤ 6/28, 구조화 도달 0/324·0/216, 평문 도달 0/240·0/108.

### 8B-3 과마스킹 축소의 일반화 — TK-52 3절
- **원인:** 추가 불용어 80개가 보호 시험 R7-02·R7-10의 첫 낱말 6개를 모두 포함하지만, 처음 보는 명사에서는 거의 줄지 않았다.
- **측정:** 비공개 새 세트에서 새 라벨 70→60/140, 기존 라벨 48→48/112.
- **요구:**
  1. 범주별로 공신력 있는 어휘 출처(법령 용어, 법원 서식 등)를 정해 범주를 실제로 넓힌다. 범주 정의·출처·반영 범위를 목록 머리 주석에 적는다.
  2. `계정`·`지시`·`의견`은 붙인 범주에 맞는 근거를 적거나, 맞는 범주로 옮기거나, 뺀다. 빼서 보호 시험이 다시 실패하면 그대로 보고한다(표시 변경 금지).
  3. 불용어 외 구조 신호를 써도 된다. 형태소 분석기 등 새 의존성은 오프라인 동작·용량·라이선스를 적어 `requests/`로 먼저 제안하고, 승인 뒤에 쓴다.
  4. 불용어 확대가 실명을 지우지 않는지 8B-1 시험과 함께 확인한다.
- **수용:**
  - 새 라벨 ≤ 14/140, 기존 라벨 ≤ 11/112
  - 정상 문장 PERSON 오탐 ≤ 6/35(44e73f9는 4)
  - R7-02 12·R7-10 24·TK-51 4 통과 유지
  - R7-11·R7-12·R6-01·R7-09·R7-07 유지
- 기준에 못 미치면 수치를 꾸미지 말고 달성치와 한계를 보고한다.

## 2. 공통 완료 조건(로컬)
- **시험:**
  - `pytest -q tests/regression` 전부 통과(+ `test_tk41` xfail 유지)
  - 전체 시험 새 실패 0, 브라우저 시험 197
  - `tests/acceptance` 실제 실패 0. strict XPASS(R7-02·TK-51)는 예상된 것으로 둔다.
- **점수:** 고정 dev ≥ 81.7·holdout ≥ 79.2·오탐 0.
- **점검 도구:** 아래가 모두 종료 코드 0이어야 한다. 새 브랜치 푸시 때 CI는 마지막 커밋 하나만 보므로(`BASE=HEAD~1`) 반드시 로컬에서 기준 81cdcc4로 돌린다.
  ```
  python scripts/regression_gate.py --base 81cdcc4
  python scripts/check_hardcoding_diff.py --base 81cdcc4
  python scripts/check_test_edits.py --base 81cdcc4
  python scripts/check_version_policy.py --base 81cdcc4
  ```
- `POLICY_VERSION`을 바꾸면 보고서에 사유를 적는다. 새 `rule_id` 0.

## 3. 보고서: `docs/handoff/requests/28_round8b_completion.md`
1. `git diff 44e73f9 HEAD --stat` 출력 그대로(전체와 `-- tests/`)
2. 불용어 증감 표(낱말 수·범주·출처), 보호 시험 입력과 겹치는 낱말과 그 이유
3. 8B-1·8B-2의 판정 경로 변경 요약(어느 문맥을 언제 만들고 무엇을 차단하는지, fail-closed 경로)
4. 2절 명령들의 마지막 줄 그대로
5. 새 브랜치 CI의 단계별 결과(실행 링크)
6. 못 푼 것

## 4. 푸시 절차 — 규칙상 PR #5 브랜치에는 직접 푸시할 수 없다
- **규칙:** 저장소 규칙(ruleset)은 모든 브랜치에 필수 확인 3개를 요구한다(점수 하락 게이트·테스트·Docker OCR readiness). 이미 있는 브랜치는 그 3개를 통과한 커밋으로만 갱신된다(브랜치 생성은 예외).
- **결과:** 보완 커밋은 strict XPASS 때문에 `점수 하락 게이트`가 반드시 실패하므로, `antigravity/round8-privacy-boundary`로의 푸시는 거부된다.
- **우회 금지:** 강제 푸시·브랜치 삭제·표시 수정·워크플로 수정은 하지 않는다.

```
git fetch origin antigravity/round8-privacy-boundary
git checkout -b antigravity/round8b-tk52 origin/antigravity/round8-privacy-boundary   # 44e73f9에서 시작
# 8B-1, 8B-2, 8B-3, 보고서를 각각 커밋(커밋 메시지 끝에 'Agent: implementer')
git push -u origin antigravity/round8b-tk52                                        # 새 브랜치라 허용
```

- **CI 기대 결과:** 그 밖의 실패가 있으면 고친 뒤 다시 푸시한다.

  | 확인 | 기대 결과 |
  |---|---|
  | 테스트 job | 실패 목록이 strict XPASS뿐 |
  | Docker OCR readiness | 성공 |
  | 점수 하락 게이트 | '수용 시험' 단계만 실패(strict XPASS), 다른 단계는 모두 성공 |

- **재보완:** 같은 브랜치에 추가 푸시하면 거부된다. 직전 브랜치 위에 쌓아 새 이름으로 푸시한다(`antigravity/round8b-tk52-r2`, `-r3` …).
- **알림:** PR은 새로 열지 않는다. PR #5에 코멘트로 새 브랜치명과 head SHA를 남기고, 사용자에게 "브랜치 `antigravity/round8b-tk52`, 최종 SHA `<sha>`, 보고서 28번"을 알린다.

## 5. 그 뒤 평가 측이 하는 일(구현 측은 하지 않는다)
1. 그 SHA로 비공개 세트를 재측정하고, 판정을 `f1_gate_verdict.md`·HISTORY에 기록한다.
2. **불승인이면:** TK-52를 갱신한다. 구현 측은 4절의 `-r2` 브랜치로 다시 올린다.
3. **승인이면:**
   - 평가 측이 그 SHA 위에 표시 제거 커밋(R7-02·TK-51 strict, R7-10 non-strict)을 쌓아 `evaluator/round8-promotion`으로 푸시하고, 필수 확인 3개가 모두 성공하는지 확인한다.
   - 그 초록 SHA로 `antigravity/round8-privacy-boundary`를 fast-forward한다(평가 측이 구현 측 브랜치에 푸시한다 — **사용자 승인 2026-10-03**). 그러면 PR #5 head가 갱신되어 병합 가능 상태가 된다.
   - 병합은 사용자 승인 뒤에 한다.
4. 8차 완료는 F1 착수 승인이 아니다. 다음 순서:
   1. '행위시법 검토 보강'(요청 16 + TK-34)
   2. F1 직전 재측정·독립 감사
   3. 사용자 승인
