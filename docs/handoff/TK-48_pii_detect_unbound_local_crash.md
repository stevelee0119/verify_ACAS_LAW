# TK-48 PII 탐지기가 `성명 불상의`·`성명: 미상` 같은 흔한 문구에서 예외로 끝남 (7차 보완 9506481이 만든 P1 회귀)
- 유형: 회귀(개인정보·가용성, **P1**) · 기준: 7차 보완 9506481(7adf43f·4da3910에서는 정상) · 작성: evaluator 2026-10-03 · 근거: 평가 측 독립 측정([HISTORY 13절](../scorecards/HISTORY.md))

## 증상·증거
- `packages/pii_engine/detector.py`의 `detect()`가 `UnboundLocalError: cannot access local variable 'josa_match'`로 끝난다. 9506481이 `josa_match`를 `if not is_name_label:` 블록 안에서만 만들고, 아래의 `if josa_match and len(clean_name) >= 3:`는 **무조건** 읽는다. 라벨이 성명 표지(`성명`·`이름`·`서명자`·`명의인`)이거나 콜론이 있고 **후보 전체가 이름 구조가 아닐 때**(`full_is_valid`가 거짓) 예외가 난다.
- 평가 측 재현(시작 0/13 예외 → 9506481 **9/13 예외**): `성명 불상의 직원이 현장에 있었다고 주장한다.`, `성명 미상의 자가 문서를 작성하였다.`, `성명: 불상`, `성명: 미상 피해자`, `이름: 확인 불가`, `원고 성명 불상`, `피고 서명자는 불명이다.`, `성명 불상의 자`, `성명 표시 생략`. 비공개 입력 441개 중 **서로 다른 14개**가 예외(`성명 {이름}은/에 대한/의 …` 9·`이름 {이름}은 …` 3·`성명 불상의 자가 …`·`성명 미상 피해자에 관한 …`). 독립 감사 Sol이 추가로 `성명: 김도현은 출석하였다.`·`성명: 가나다`·`담당자: 박민수는 기록을 확인했다.`와 기존 보호 시험·원장의 `피청구인: 각하한다`에서 같은 예외를 재현했다(평가 측도 재현: 시작·4da3910은 `['김도현']` 등 정상). **서면 한 줄이 검증 전체를 멈출 수 있다.**
- 구현 측 자신의 시험도 이를 잡았다: `tests/acceptance/test_round5_regressions.py::test_ordinary_sentences_are_not_treated_as_person_names[unknown-name]`·`[privacy-instruction]`, `tests/regression/test_ledger.py::test_r1_tk30_ordinary_sentence_no_false_positive_control`·`test_tk28_pii_label_delimiter_control[피청구인: 각하한다]`. 보고서는 "새 실패 0건"이라 적었다.

## 요구
1. 예외를 없앤다(`josa_match`를 분기 밖에서 정의하거나 분기마다 일관되게 처리). 같은 구조의 다른 미정의 지역 변수가 없는지 `detect()` 전체를 점검한다.
2. 시험: 성명·이름·서명자 라벨 뒤에 이름이 아닌 말이 오는 문구 묶음(보호 시험 8개와 **다른** 입력을 구현 측이 새로 짓는다)에서 `detect()`가 예외 없이 끝나고 오탐이 없다. 모든 명령 실행 전에 전체 시험을 돌린다.

## 수용
`tests/acceptance/test_round7_findings.py::test_pii_detection_does_not_raise_on_ordinary_text_after_a_name_label`(15건: 최초 8 + Sol 독립 예시 반영 7)·`test_explicit_name_label_keeps_the_name_and_drops_the_particle`(2건) 통과, 5차 보호 시험 `test_ordinary_sentences_are_not_treated_as_person_names` 전부 통과, 고정 점수 유지.

호출부에서 예외를 삼켜 통과시키지 않는다(탐지 실패는 개인정보 누락 — fail-open). 원인만 고친다. 독립 감사 Sol B7-01(P1)과 같은 결함이다.
