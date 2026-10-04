# 8차 보완 3(8C) 작업 지시서 — TK-53 이름 키 정규화와 키 문맥 축소 (구현: Codex)

작성: 평가 에이전트(claude-code) 2026-10-03
근거(모두 `Steve_ACASiaLAW`에 있다):
- [TK-53](TK-53_round8b_key_context_leak_and_lexicon_failure.md)
- [f1_gate_verdict '8차 2차 판정'](../scorecards/f1_gate_verdict.md)
- [process_review_2026-10-03](../scorecards/process_review_2026-10-03.md)
- [8차 지시서](PROMPT_FOR_ROUND8_PRIVACY_BOUNDARY.md) 0절(유출 0 하한, fail-closed)은 그대로 유효하다.

사용자 결정(2026-10-03, '1~5 추천대로'):
1. 과마스킹(TK-43)은 8차 수용 기준에서 분리한다. **이번 범위가 아니다.**
2. 8C 구현은 Codex가 맡는다.
3. 검출 휴리스틱을 바꾸면 설계 메모를 먼저 낸다.
4. 평가 측이 PR을 자동 재측정한다.

아래 전체를 Codex 작업 설명에 붙여 넣는다. 저장소 루트의 `AGENTS.md`도 함께 따른다.

## 0. 환경·시작점
1. **실행 환경을 CI와 맞춘다.** CI는 Linux, Python 3.11, tesseract 5.3.4(kor·eng)다. Codex 환경 설정(setup script)에 다음을 넣는다.
   ```
   sudo apt-get update -qq && sudo apt-get install -y -qq tesseract-ocr tesseract-ocr-kor tesseract-ocr-eng fonts-nanum
   python -m pip install --upgrade pip && pip install -r requirements-test.txt
   python -m playwright install --with-deps chromium   # 브라우저 시험용
   ```
   - 보고서에 `python --version`과 `tesseract --version` 첫 줄을 적는다.
   - 설치하지 못한 것은 못 했다고 적는다.
2. **시작 커밋:** `evaluator/round8-promotion` 최신(78c38dc 이후, 정정 2026-10-03 — 처음 지시는 d20cde2)
   - d20cde2는 8B(170c647) 위에 평가 측이 보호 시험 표시를 승격한 커밋이다. e349fad는 그 위에 `Steve_ACASiaLAW`(a04826f)를 병합해 `scripts/verify_all.py`·이 지시서·TK-53을 넣은 것이다. 제품 코드는 d20cde2와 같다.
   - **정정 사유:** d20cde2에는 `scripts/verify_all.py`가 없어 3절 점검 명령을 실행할 수 없었다(평가 측 지시 오류).
   - 이미 d20cde2에서 시작했다면 `git fetch origin evaluator/round8-promotion && git merge origin/evaluator/round8-promotion`으로 병합 커밋 하나를 더한다(리베이스·강제 푸시 금지). 충돌은 없다(제품 코드 변경 없음).
   - 점검 기준(`--base`)은 그대로 d20cde2다. 평가 측이 e349fad에서 `verify_all.py --base d20cde2` 전체 모드를 돌려 종료 0을 확인했다(Linux·Python 3.11.15·tesseract 5.3.4, 브라우저 197 통과).
   - 보고서의 diff 기준은 78c38dc다(4절). d20cde2로 잡으면 평가 측이 병합한 문서가 섞인다.
   - 이 위에서는 수용 시험에 strict XPASS가 없다. 그래서 너의 커밋도 CI 필수 확인 3개(점수 하락 게이트·테스트·Docker OCR readiness)를 모두 통과할 수 있고, 통과해야 한다.
3. **작업 브랜치와 푸시:** 저장소 규칙(ruleset)은 `main`과 `Steve_ACASiaLAW`에 걸려 있다. 작업 브랜치는 제약 없이 푸시할 수 있다.
   - 새 브랜치 `codex/round8c-key-context`를 만들어 푸시한다. 그다음 `Steve_ACASiaLAW` 대상 PR을 연다. 제목은 `8C: TK-53 이름 키 정규화 + 키 문맥 축소`로 한다.
   - 보완 커밋은 같은 브랜치에 이어서 푸시한다. 푸시마다 CI가 돈다.
   - 강제 푸시와 `Steve_ACASiaLAW` 직접 푸시는 하지 않는다. 병합은 평가 측 판정과 사용자 승인 뒤에 한다.
   - 평가 측은 이 PR을 구독해 비공개 세트를 자동으로 재측정하고 **건수만** PR에 코멘트한다.
4. **바꿀 수 있는 파일:**
   - `packages/llm_router/privacy.py`
   - 라벨 어휘를 한 곳에서 내주는 데 필요한 `packages/pii_engine/detector.py`의 해당 부분
   - 새 시험 파일 `tests/regression/test_r8c_key_context.py`
   - `docs/handoff/requests/` 아래 메모·보고서
5. **하지 않는 것:**
   - 불용어 목록 변경(과마스킹은 별도 트랙)
   - 기존 시험의 삭제·수정, skip/xfail 추가
   - 보호 경로(`AGENTS.md` 참조), 법리·줄 결합 코드, 강제 푸시
   - 평가 측 비공개 수치를 보고서에 추정해 적는 것

## 1. 설계 메모(첫 커밋)
`docs/handoff/requests/30_round8c_design.md`에 1쪽 이내로 쓴다.
- (a) **사람 이름 키 판정 규칙:** 라벨 토큰 포함, '명'·'이름'·'성명' 접미, 괄호·공백 변형, 영문 이름 키. 출처는 detector 라벨 어휘 하나로 둔다.
- (b) **비인명 '-명' 키를 빼는 규칙:** 사건명·법원명·회사명처럼 사람 라벨 머리가 없는 키.
- (c) **'이름 꼴 값' 판정 규칙:** 성씨로 시작하는 2~4음절 단일 토큰, 호칭·괄호 덧붙임 등.
- (d) **판단이 서지 않을 때의 처리:** 막는다.
- (e) 예상되는 유출·과차단 위험과 시험 계획.

평가 측은 PR에서 메모를 보고 '통하지 않을 이유'만 회신한다(비공개 입력은 공개하지 않는다). 회신을 기다리지 말고 구현을 계속하되, 회신이 오면 반영한다.

## 2. 작업
1. **(P1) 이름 키 정규화** — TK-53 1절. 실명 키는 문맥을 붙여 검사하고, 판단이 서지 않으면 막는다.
2. **(P2) 키 문맥은 이름 꼴 값에만** — TK-53 2절. 그 밖의 값은 원래 값만 검사한다.
3. **시험** — 입력은 새로 짓는다. 보호 시험·평가 측 입력·TK 문서 예시는 쓰지 않는다. 다음 네 가지를 함께 넣는다.
   - 미전송: 복합·접미·괄호·공백·영문 이름 키 아래의 실명
   - 전송: 비인명 '-명' 키, 장소·직무 명사 값, 법인·기관 값
   - 차단: 검사 예외
   - 유지: 형제·배열 쌍의 실명이 미전송인 것

## 3. 점검(보고 전 필수)
```
python scripts/verify_all.py --base d20cde2
```
- 종료 코드 0이어야 한다. 실패 단계가 있으면 고친 뒤 다시 돌린다.
- 환경 차이로 실패한 단계는 그 사실을 적는다.
- `--quick`은 중간 확인용이며 보고서에는 쓰지 않는다.

## 4. 보고서: `docs/handoff/requests/31_round8c_completion.md`
1. `git diff 78c38dc HEAD --stat` 출력 그대로(전체와 `-- tests/`). 78c38dc가 조상이 아니면(평가 측 브랜치를 병합하지 않았으면) 그 사실을 적는다
2. 설계 메모 링크, 메모와 달라진 점
3. `verify_all.py` 콘솔 출력 그대로(HEAD SHA가 찍힌 것)
4. 같은 SHA의 CI 실행 링크와 단계별 결과
5. 못 푼 것

## 5. 수용(평가 측이 잰다)
- 평가 측 즉석 키 점검: 0
- 비공개 구조화: 0/324(metadata 포함 0/432)·0/216
- 평문: 0/240·0/108
- 라벨+실명: 0/180
- stem: 16/16
- 정상 구조화 요청 과차단: ≤ 6/28
- 이름: 330/330·60/60, `detect()` 예외 0
- 보호 시험: 모두 통과
- 점검 도구: `verify_all` 종료 0, 같은 SHA의 CI 필수 확인 3개 성공

## 6. 수용 뒤 절차(평가 측)
1. 판정을 기록한다.
2. 사용자 승인을 받아 PR #5 브랜치(`antigravity/round8-privacy-boundary`)를 너의 최종 초록 SHA로 fast-forward하고, 사용자가 병합한다. 그러면 네 PR도 병합된 것으로 표시된다.
3. 불승인이면 TK-53을 갱신하고 PR에 남은 항목을 코멘트한다. 너는 같은 브랜치에 보완 커밋을 이어서 푸시한다.
