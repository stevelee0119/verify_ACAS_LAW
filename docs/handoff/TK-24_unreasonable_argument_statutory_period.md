# TK-24 무리한 주장: 법정 기간(소멸시효 등) 적용을 정의·유추로 일체 배제한다는 주장 미탐
- 유형: 규칙 부족(일반화) · 기준 커밋: main 9933548 · 작성: evaluator 2026-10-01
- 근거 서면: 서면9(2026가합61942) 정답지 4영역 — 시효 배제 주장과 징벌적 손해배상 50억 청구, 두 가지를 모두 무리한 주장으로 본다.

## 증상(오프라인 docx·텍스트, 온라인 모두 LEG-2 실패)
서면 문장: "피고의 본건 위법행위는 형법상 살인미수 및 국가기관에 의한 반인도적 중대 범죄에 **준하므로**, 민법 제766조 및 국가재정법 제96조의 소멸시효 규정은 **자연법적 정의에 반하여 일체 적용이 배제**되어야 합니다."
- 같은 문단의 징벌적 손해배상 50억 청구는 `NO_BASIS_REMEDY`로 `LEGAL_ARGUMENT_INVALID` MEDIUM이 올랐다(통과). 시효 배제는 별도 finding이 없다. 소제목에 `소멸시효`가 들어 있어 finding 본문에 그 낱말이 보이지만 소제목 인용일 뿐이다(평가 명세 LEG-2는 본문 쟁점어로 판정한다).
- 3차 구현(Q7)의 4단 구조(기초 사실 비다툼 + 면책·효력 부정 법리 군집 + 범주적 결론 + 요건 논의 부재)가 이 문장을 잡지 못했다. 군집에 **법정 기간·요건의 적용 배제**와 **정의·유추·준용을 근거로 드는 서술**이 없다.

## 요구(구조 일반화, 이 서면의 낱말을 키로 쓰지 않는다)
1. 적용 배제 대상을 닫힌 집합으로: 법정 기간·요건·면책 규정(소멸시효·제척기간·제소기간·불변기간, 법률이 정한 성립 요건, 면책·한도 규정 등). 조문 번호 열거 금지.
2. 배제 근거 유형: 정의·형평·자연법·인도주의, 다른 법률의 **유추·준용**(`…에 준하므로`), 상위 규범 원용.
3. 범주적 표현(일체·전면·무조건·어떠한)과 **요건 논의 부재**(법이 정한 배제 사유·예외·판례 인용 없음).
4. 판례·법령이 정한 예외를 정확히 인용해 배제를 주장하는 서면(예: 법이 명시한 시효 중단·정지 사유 원용)은 알리지 않는다(대조군).

## 수용 기준
- `python -m pytest tests/acceptance/test_case9_state_compensation.py -rxX`: `test_case9_check[docx-LEG-2]`, `[text-LEG-2]` XPASS.
- 구현 측 새 시험: 대상(소멸시효·제척기간·제소기간 등)·근거(정의·유추·인도주의)를 바꾼 양성 5건, 법정 예외를 정확히 원용한 대조군 3건. 변형 1·2·서면6~8의 무리한 주장 항목과 대조군 유지, 고정 시험 오탐 0.

## 개정 1 — 재점검과 Codex 인계(2026-10-09, 사용자 결정 '장기 미해결 과제는 Codex에 전달')
- 재점검(평가 측, Steve 114f8b3 = 운영 `main` a8b2a7e 탐지 코드, 오프라인, Python 3.11.15)
  - `tests/acceptance/test_case9_state_compensation.py`: `[docx-LEG-2]`·`[text-LEG-2]`가 여전히 strict xfail이다(61 passed, 2 xfailed).
  - 온라인 서면9 점검에서도 LEG-2는 10-01부터 0.11.0까지 9회 모두 실패했다(`first_touch_log.jsonl`).
- 관련 시험 기준값(구현 전, 같은 SHA)
  - `test_tk20_unreasonable_argument_cluster`·`test_v4_g4_reasoning_axis`·`test_verification_regressions`·`test_v2_phase1_verdicts`·`test_efficacy_round2`·`test_v5_claim_polarity`·`test_ground_truth_prepared_brief`와 `tests/acceptance/`의 `test_generalization_guards`·`test_round5_regressions`·`test_variant_generalization`·`test_case9_state_compensation`: **310 passed, 2 xfailed**
  - `tests/acceptance/test_round7_findings.py`: **105 passed, 5 xfailed**
  - 구현 뒤 이 값에서 LEG-2 2건만 XPASS로 바뀌어야 한다. strict XPASS 실패는 예정된 것이고, 표시는 평가 측이 지운다.
- 절차
  - 법리 탐지 휴리스틱 변경이므로 **설계 메모를 첫 커밋**으로 `docs/handoff/requests/`에 낸다(AGENT_ROLES 2.1). 평가 측 회신 뒤 구현한다.
  - 기존 무리한 주장 규칙(`packages/legal_engine/claim_review.py`의 `NO_BASIS_REMEDY` 등, TK-20 군집)과 같은 틀에 넣되, 정상 항변 오탐 0을 지킨 TK-45의 원칙을 따른다: 낱말 위치 일치 금지, 절·극성 구조로 판정.
- 수용(원 수용 기준에 더함)
  - 고정 81.7/79.2/0 같음, 은퇴 세트 3개 점수 하락 없음
  - 수용 SHA에서 평가 측이 `verify_all` 전체 모드를 돌린다. 릴리스 전 봉인 시험은 새 세트로 한다.
