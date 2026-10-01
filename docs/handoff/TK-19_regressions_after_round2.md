# TK-19 2차 구현(de243cc)이 기존 시험 4건과 기준일 추출을 깨뜨림
- 유형: 회귀 · 기준 커밋: de243cc · 작성: evaluator 2026-10-01
- 2차 지시서 4절은 `pytest -q --ignore=tests/acceptance` 실패를 환경 사유 1건(+P6 전 TK-12 2건)으로 제한했다. de243cc의 전체 시험은 8건 실패이고, 이 중 **새로 생긴 것이 4건**이다. main `CI`의 `테스트` 작업도 같은 이유로 실패했다([실행 기록](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/36823899014)).
- 커밋별 이분 탐색(평가 측, 같은 5개 시험을 커밋마다 실행): 6a3c848(TK-15 복구)에서는 5건 모두 통과했고, 아래 커밋에서 하나씩 깨졌다. 각 커밋 메시지에는 "게이트 통과"만 있고 전체 시험 결과는 없다.

## 1. 6e5cd78 (P5-b): 날짜 뒤 '횡령'·'방법'을 법령명으로 읽어 기준일 후보가 사라진다 — 판정에 영향
`temporal_review.py`의 `LAW_DATE_AFTER_RE`에 새로 들어간 `[「『]?\s*[가-힣]+(?:법률|법|령|규칙)` 가지가 날짜 바로 뒤의 낱말 `횡령`(…령), `방법`, `위법`을 법령명으로 읽는다. 그 날짜는 "법령 개정일"로 분류되어 기준일 후보에서 빠진다.
```
피고인은 2021. 6. 1. 횡령하였다.                    cf7c739: ['2021-06-01']  de243cc: []  (기준일 MISSING)
피고인은 2021. 6. 1. 위법한 방법으로 회사 자금을 횡령하였다.   cf7c739: ['2021-06-01']  de243cc: []
피고인은 2021. 6. 1. 업무상 횡령하였다.                de243cc: ['2021-06-01']  (낱말이 '업무상'이라 우연히 통과)
```
횡령·배임 사건의 가장 흔한 문장 모양이라 **행위시법 검토가 조용히 꺼진다**. 기존 시험 `tests/test_v4_review_temporal.py::test_unknown_reference_date_is_a_temporal_review_warning_with_candidates`가 이로 인해 실패한다(범행일 후보 2개 중 1개만 남아 '기준일 불명'이 아니라 단일 날짜 판정으로 넘어감).
- 요구: 법령 개정·시행 표지는 **구조적 신호**(공포·시행·개정 동사, 법령번호 `제N호`, 「」로 싼 이름, 조문 번호와의 결합)로 잡고, 날짜 뒤의 임의 한글 낱말 끝음절(법·령·규칙)로 법령명을 판정하지 않는다.
- 수용: `tests/acceptance/test_variant_generalization.py::test_reference_date_candidate_is_kept` 4건 중 xfail 2건(`embezzle-verb`, `unlawful-method`)이 XPASS, 위 v4 시험 통과.

## 2. 703dba5 (P2-4): 시점 라벨을 낱말 목록으로 비교해 진짜 불일치를 놓친다
`exhibit_facts._check_vital_measurements`에 시점 낱말 목록(`초진·내원·이송·도착·수술…`)을 두고, 양쪽 라벨 집합이 겹치지 않으면(한쪽에만 있어도) 불일치를 내지 않게 했다. `내원 당시`와 `초진 기록`은 같은 시점(처음 진료받은 때)인데 서로 다른 시점으로 취급된다.
- 실패 시험: `tests/test_exhibit_facts_generic.py::test_vital_measurements_positive`, `tests/test_case5_medical_malpractice_complaint.py::test_case5_rag_exhibit_facts_contradiction_detection`(소장 `내원 당시 혈압 210/120` ↔ 의무기록 `초진 활력징후 135/85` — 정답지가 잡으라는 수치 모순 3건 중 1건이 사라짐).
- **평가 측 지시 문구의 모호함도 원인이다.** 2차 지시서 P2-4의 "서로 다른 시점 표기가 한쪽에만 있으면 CONTRADICTS를 내지 않는다"를 구현이 글자 그대로 따랐다. 같은 시점을 가리키는 표현(초진·내원·도착)을 한 군으로 보라는 말을 빼먹었다. 아래로 바로잡는다.
- 요구: (a) 시점이 **명시적으로 다르다고 판단되는 경우**(예: 이송 중 ↔ 내원 시)만 배제한다. 같은 군이거나 판단 불가면 배제하지 말고 INFO 참고 의견으로 낸다(P2-4가 허용한 대안). (b) 시점 낱말 목록을 늘리는 방식이 아니라 같은 대상·시점 확인 구조로 설계하고, 불가피하면 어휘를 `config/`로 뺀다. (c) 두 시험을 통과시키되 P2 재현 입력(`이송 도중 90/60` ↔ `내원 시 135/85`, 일반 정의 문장)은 계속 관찰되지 않아야 한다.

## 3. 7ff5da6 (P3): 옛 규칙 시험을 갱신하지 않음
`tests/test_v2_root_causes.py::test_r10_axis_uses_the_same_verdict_as_the_document_result`는 "흔적 0건이면 UNCERTAIN"을 기대한다. TK-18로 규칙이 바뀌었으므로 시험이 틀린 것이다. 앞선 두 시험(`test_evidence_rag_review`·`test_review_hardening`)은 갱신했으면서 이것만 빠뜨렸다. 요구: 새 규칙(다수결 판정 유지, `involvement`는 별도 항목)에 맞게 갱신하고 `grep -rn "objective_traces" tests/ packages/`로 같은 옛 기대가 더 없는지 확인한다.

## 4. ad8ffaa (P4): 사업자등록번호 — 구 시험과 정책이 충돌(사용자 결정 필요)
`tests/test_procurement_claim_efficacy.py::test_sec01_identifier_preservation`은 `사업자등록번호 123-45-67890`이 **마스킹되지 않기를** 기대한다(사건 식별자 과잉 마스킹 방지, 1차 구현 때 작성). 서면8 정답지는 피고 법인의 인적사항 8개 항목에 사업자등록번호를 넣어 **마스킹하라고** 한다(TK-17). 두 기대가 반대다.
- 구현 에이전트는 구 시험을 갱신하지도, `requests/`에 충돌을 알리지도 않고 TK-17만 이행했다. 정책 충돌은 구현 에이전트가 정하지 않는다. 사용자 결정 대기: **사업자등록번호를 마스킹할 것인가**(법인 식별자인가 개인정보인가; 개인사업자는 등록번호가 곧 개인 식별자일 수 있다). 결정 전에는 `requests/`에 충돌 사실을 적고 시험은 그대로 둔다.

## 수용 기준
- `python -m pytest -q --ignore=tests/acceptance` 실패가 환경 사유 1건(`test_v5_ocr_dates::test_rotated_…`)과 TK-12 2건(자료 반영 전)뿐이다. 4절은 사용자 결정 전까지 예외.
- 푸시 전 위 명령을 **실제로 돌린 결과**를 커밋 메시지에 적는다(통과·실패 개수).
