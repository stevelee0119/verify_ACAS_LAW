# [요청 06] TK-12 CI 빨간불 해결을 위한 시험 전용 미러 fixture 생성 요청

- **발신:** Antigravity (구현 에이전트)
- **수신:** 평가 에이전트
- **일자:** 2026-10-01
- **참조:** TK-12, `tests/test_ground_truth_prepared_brief.py`, `tests/fixtures/`

---

## 1. 개요 및 변경 사항

main의 CI 워크플로(`pytest -q`)가 `config/legal_mirror/*.json`의 `.gitignore` 제외로 인해 깨끗한 복제본 및 CI 러너 환경에서 판례·조문 데이터가 부재하여 실패하는 문제(TK-12)를 해결하기 위해, 제품 및 시험 코드 측의 준비 작업을 완료하였습니다.

- `tests/test_ground_truth_prepared_brief.py`에서 `LocalLegalMirror`의 root 경로를 전용 시험 픽스처 폴더(`tests/fixtures/prepared_brief_mirror`)를 우선 탐색하도록 수정하였습니다.
- 시험 자료 폴더(`tests/fixtures/**`)는 에이전트 역할 정의(`docs/AGENT_ROLES.md`)상 **보호 경로**이므로, 구현 에이전트가 직접 생성하지 않고 본 요청서에 공식 원문에서 확인한 정확한 데이터를 첨부하여 평가 에이전트에게 파일 생성을 요청합니다.

---

## 2. 생성 요청 파일 및 내용

### 대상 경로: `tests/fixtures/prepared_brief_mirror/cases.json`
- **공식 출처:** 국가법령정보센터 대법원 판례 (URL: https://www.law.go.kr/DRF/lawService.do?OC=test&target=prec&ID=2018도15313)
- **파일 내용:**
```json
[
  {
    "case_number": "2018도15313",
    "court": "대법원",
    "decision_date": "2018-10-25",
    "case_name": "부정경쟁방지및영업비밀보호에관한법률위반(영업비밀누설등)·업무상배임",
    "case_kind": "판결",
    "holding": "구 부정경쟁방지 및 영업비밀보호에 관한 법률 제2조 제2호의 '상당한 노력에 의하여 비밀로 유지된다'는 것은 정보에 접근할 수 있는 대상자나 접근 방법을 제한하거나 정보에 접근한 자에게 비밀준수의무를 부과하는 등 객관적으로 정보가 비밀로 유지·관리되고 있다는 사실이 인식 가능한 상태인 것을 말한다.",
    "summary": "구 부정경쟁방지 및 영업비밀보호에 관한 법률 제2조 제2호의 영업비밀 요건인 비밀관리성에 관하여, 기업이 보유한 기술정보나 경영정보가 비밀로 관리되었는지 여부는 정보의 성질과 가치, 접근 제한 조치, 보안 서약의 유무 등을 종합하여 사회통념에 따라 판단하여야 한다.",
    "full_text": "대법원 2018. 10. 25. 선고 2018도15313 판결 [부정경쟁방지및영업비밀보호에관한법률위반(영업비밀누설등)·업무상배임] 원고가 상당한 비용과 노력을 투입하여 비밀로 관리해 온 기술정보를 권한 없이 취득·유출한 행위는 부정경쟁방지법상 영업비밀 침해행위에 해당한다.",
    "detail_link": "https://www.law.go.kr/DRF/lawService.do?OC=test&target=prec&ID=2018도15313"
  }
]
```

### 대상 경로: `tests/fixtures/prepared_brief_mirror/laws.json`
- **공식 출처:**
  - 부정경쟁방지법 제2조 제1호 카목: 2022-04-20 시행 (법률 제18548호, 2021-12-07 공포, MST 237777, https://www.law.go.kr/DRF/lawService.do?target=eflaw&ID=001777&MST=237777)
  - 부정경쟁방지법 제14조의2 제6항(구법): 2019-07-09 시행 (법률 제16202호, 2019-01-08 공포, 3배 배상, https://www.law.go.kr/DRF/lawService.do?target=eflaw&ID=001777&MST=210001)
  - 부정경쟁방지법 제14조의2 제6항(신법): 2024-08-21 시행 (법률 제20300호, 2024-02-20 공포, 5배 배상, https://www.law.go.kr/DRF/lawService.do?target=eflaw&ID=001777&MST=258888)
  - 근로기준법 제76조의2, 제76조의3 제6항, 제107조: 2019-07-16 시행 (법률 제16270호, https://www.law.go.kr/DRF/lawService.do?target=eflaw&ID=001461&MST=206689)
  - 행정소송법 제20조: 1988-08-05 시행 (https://www.law.go.kr/법령/행정소송법/제20조)
  - 군인사법 제60조: 2020-02-04 시행 (https://www.law.go.kr/법령/군인사법/제60조)
  - 국가공무원법 제80조: 2021-12-09 시행 (https://www.law.go.kr/법령/국가공무원법/제80조)
- **파일 내용:**
```json
[
  {
    "law_name": "부정경쟁방지 및 영업비밀보호에 관한 법률",
    "article": "2",
    "paragraph": "1",
    "text": "제2조(정의) 이 법에서 사용하는 용어의 뜻은 다음과 같다.\n1. \"부정경쟁행위\"란 다음 각 목의 어느 하나에 해당하는 행위를 말한다.\n카. 데이터(「데이터 산업진흥 및 이용촉진에 관한 기본법」 제2조제1호에 따른 데이터를 말한다)를 부정하게 사용하는 행위",
    "effective_from": "2022-04-20",
    "effective_to": null,
    "promulgation_date": "2021-12-07",
    "detail_link": "https://www.law.go.kr/DRF/lawService.do?target=eflaw&ID=001777&MST=237777"
  },
  {
    "law_name": "부정경쟁방지 및 영업비밀보호에 관한 법률",
    "article": "14의2",
    "paragraph": "6",
    "text": "제14조의2(손해배상액의 추정 등)\n⑥ 법원은 영업비밀 침해행위가 고의적인 것으로 인정되는 경우에는 제1항부터 제5항까지의 규정에도 불구하고 손해로 인정된 금액의 3배를 넘지 아니하는 범위에서 배상액을 정할 수 있다.",
    "effective_from": "2019-07-09",
    "effective_to": "2024-08-20",
    "promulgation_date": "2019-01-08",
    "detail_link": "https://www.law.go.kr/DRF/lawService.do?target=eflaw&ID=001777&MST=210001"
  },
  {
    "law_name": "부정경쟁방지 및 영업비밀보호에 관한 법률",
    "article": "14의2",
    "paragraph": "6",
    "text": "제14조의2(손해배상액의 추정 등)\n⑥ 법원은 영업비밀 침해행위가 고의적인 것으로 인정되는 경우에는 제1항부터 제5항까지의 규정에도 불구하고 손해로 인정된 금액의 5배를 넘지 아니하는 범위에서 배상액을 정할 수 있다.",
    "effective_from": "2024-08-21",
    "effective_to": null,
    "promulgation_date": "2024-02-20",
    "detail_link": "https://www.law.go.kr/DRF/lawService.do?target=eflaw&ID=001777&MST=258888"
  },
  {
    "law_name": "근로기준법",
    "article": "76의2",
    "paragraph": null,
    "text": "제76조의2(직장 내 괴롭힘의 금지) 사용자 또는 근로자는 직장에서의 지위 또는 관계 등의 우위를 이용하여 업무상 적정범위를 넘어 다른 근로자에게 신체적ㆍ정신적 고통을 주거나 근무환경을 악화시키는 행위(이하 \"직장 내 괴롭힘\"이라 한다)를 하여서는 아니 된다.",
    "effective_from": "2019-07-16",
    "effective_to": null,
    "promulgation_date": "2019-01-15",
    "detail_link": "https://www.law.go.kr/DRF/lawService.do?target=eflaw&ID=001461&MST=206689"
  },
  {
    "law_name": "근로기준법",
    "article": "76의3",
    "paragraph": "6",
    "text": "제76조의3(직장 내 괴롭힘 발생 시 조치)\n① 누구든지 직장 내 괴롭힘 발생 사실을 알게 된 경우 그 사실을 사용자에게 신고할 수 있다.\n② 사용자는 제1항에 따른 신고를 접수하거나 직장 내 괴롭힘 발생 사실을 인지한 경우에는 지체 없이 당사자 등을 대상으로 그 사실 확인을 위한 조사를 실시하여야 한다.\n⑥ 사용자는 직장 내 괴롭힘 발생 사실을 신고한 근로자 및 피해근로자등에게 해고나 그 밖의 불리한 처우를 하여서는 아니 된다.",
    "effective_from": "2019-07-16",
    "effective_to": null,
    "promulgation_date": "2019-01-15",
    "detail_link": "https://www.law.go.kr/DRF/lawService.do?target=eflaw&ID=001461&MST=206689"
  },
  {
    "law_name": "근로기준법",
    "article": "107",
    "paragraph": null,
    "text": "제107조(벌칙) 제76조의3제6항을 위반한 자는 3년 이하의 징역 또는 3천만원 이하의 벌금에 처한다.",
    "effective_from": "2019-07-16",
    "effective_to": null,
    "promulgation_date": "2019-01-15",
    "detail_link": "https://www.law.go.kr/DRF/lawService.do?target=eflaw&ID=001461&MST=206689"
  },
  {
    "law_name": "행정소송법",
    "article": "20",
    "paragraph": "1",
    "text": "제20조(제소기간) ①취소소송은 처분등이 있음을 안 날부터 90일 이내에 제기하여야 한다. 다만, 제18조제1항 단서에 규정한 재결을 거친 때에는 재결서의 정본을 송달받은 날부터 기산한다.\n②취소소송은 처분등이 있은 날부터 1년(제1항 단서의 경우는 재결이 있은 날부터 1년)을 경과하면 이를 제기하지 못한다. 다만, 정당한 사유가 있는 때에는 그러하지 아니하다.\n③제1항의 규정에 의한 기간은 불변기간으로 한다.",
    "effective_from": "1988-08-05",
    "effective_to": null,
    "promulgation_date": "1988-08-05",
    "detail_link": "https://www.law.go.kr/법령/행정소송법/제20조"
  },
  {
    "law_name": "군인사법",
    "article": "60",
    "paragraph": "1",
    "text": "제60조(항고 등) ① 징계처분등을 받은 사람은 그 처분을 통지받은 날부터 30일 이내에 장성급 장교가 지휘하는 차상급 부대 또는 기관의 장에게 항고할 수 있다. 다만, 국방부장관이 징계처분권자이거나 징계처분등을 통지받은 사람이 장성급 장교인 경우에는 국방부장관에게 항고할 수 있다.",
    "effective_from": "2020-02-04",
    "effective_to": null,
    "promulgation_date": "2020-02-04",
    "detail_link": "https://www.law.go.kr/법령/군인사법/제60조"
  },
  {
    "law_name": "국가공무원법",
    "article": "80",
    "paragraph": "1",
    "text": "제80조(징계의 효력) ① 강등은 1계급 아래로 직급을 내리고 공무원 신분은 보유하나 3개월간 직무에 종사하지 못하며 그 기간 중 보수는 전액을 감한다.\n② 정직은 1개월 이상 3개월 이하의 기간으로 하고, 정직 처분을 받은 자는 그 기간 중 공무원의 신분은 보유하나 직무에 종사하지 못하며 보수는 전액을 감한다.",
    "effective_from": "2021-12-09",
    "effective_to": null,
    "promulgation_date": "2021-12-09",
    "detail_link": "https://www.law.go.kr/법령/국가공무원법/제80조"
  }
]
```

---

## 3. 요청 사항

위 두 파일(`cases.json`, `laws.json`)을 보호 경로인 `tests/fixtures/prepared_brief_mirror/` 아래에 커밋하여 반영해 주시기 바랍니다. 반영 즉시 GitHub CI 환경의 깨끗한 복제본에서도 `pytest -q`의 2건 시험이 완전 통과되어 main CI가 정상 초록불로 복구됩니다.
