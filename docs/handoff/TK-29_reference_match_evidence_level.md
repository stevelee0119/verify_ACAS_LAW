# TK-29 참고자료(Drive) 일치 판정: 제목 부분 일치·미독 파일만으로 부존재 판정을 낮춘다 (4차 S3 신규 회귀)
- 유형: 불확실성 단조 위반(회귀) · 기준 커밋: super_cosmos_surges_19h47 e6b58fd(S3 0123213) · 작성: evaluator 2026-10-01
- 출처: 독립 감사(Astra 4차)가 보고, **평가 측이 4차 코드에서 재현**했다(재현 코드는 `tests/acceptance/test_reference_match_guard.py`).

## 증상(평가 측 재현, 참고자료 라이브러리 대역으로 `_law_absent` 직접 호출)
| 입력 | 4차 결과 | 기대 |
|---|---|---|
| 내부 규정 인용 + **읽기에 실패한(HTTP 403) 파일**의 제목이 같음 | `PARTIALLY_VERIFIED`, "참고자료 「…」에서 확인되었다" | 확인으로 보지 않는다(읽지 못했다) |
| **가공 법률명**(`국가배상 특례법`) + 읽은 해설서 제목 `국가배상 특례법 비판 해설.pdf` | `PARTIALLY_VERIFIED`, **CRITICAL 소멸** | CRITICAL 유지(해설서 제목에 이름이 있어도 그 법률이 존재하지 않는다) |
| 짧은 법령명 `행정법` + 제목 `행정법 표준판례.pdf` | `PARTIALLY_VERIFIED`, CRITICAL 소멸 | CRITICAL 유지 |
| 가공 내부 규정 형태 `국가배상 중상해 특례 규정` + 참고자료 없음 | LOW(HIGH 미만) | 정책 결정 사안(TK-23 B 인접) — 이 티켓 범위 아님 |
정상 동작(대조군): 본문을 읽은 참고자료와 제목이 일치하는 내부 규정은 CRITICAL 없이 참고자료 대조로 넘어간다.

## 원인
`source_review._find_matching_user_reference`가 (a) `lib.summary["inventory"]`(목록에 보인 모든 파일 — 항목마다 `status`·`reason`이 있고 초기값이 `SELECTED_PENDING`/`NOT_PROCESSED`)의 이름까지 후보로 삼고 (b) `target in cand or cand in target` 양방향 부분 문자열로 비교하며 (c) 인용 규범이 법령 형태여도 적용한다. 일치하면 `verdict.status = PARTIALLY_VERIFIED`로 올리고 finding을 하나도 내지 않는다.
정답지 2영역(가공 법령·판례 탐지)을 파일 하나의 제목으로 무력화할 수 있고, 읽지 못한 자료로 확정도가 오르므로 3차 Q1·4차 R3(불확실성 단조)를 어긴다. 요청 14는 "참고자료 본문이 있는 경우"를 전제했으나 코드가 본문 유무를 보지 않는다.

## 요구
1. 후보는 **본문을 읽은 참고자료**(`summary["sources"]`/`eligible`)만. 읽지 못한·미처리 항목(`status`가 읽음이 아닌 것)은 이름이 같아도 확인으로 보지 않는다.
2. 이름 비교는 **정규화한 제목의 일치**(확장자·`[RAG참고자료]` 같은 접두 태그·괄호·공백 제거 후 동일)로 한다. 부분 문자열 포함은 일치가 아니다.
3. **법령 형태 인용**(법·법률·시행령·시행규칙·대통령령·부령·총리령·조례)에는 참고자료 일치로 CRITICAL을 낮추지 않는다. 참고자료는 법령의 존재 근거가 아니다.
4. 참고자료와 일치하더라도 finding 없이 조용히 넘기지 말고 "참고자료 대조 대상"임을 INFO로 남긴다(대조가 실제로 이뤄졌는지 보고서에서 추적 가능해야 한다).
5. 상태(`PARTIALLY_VERIFIED`)를 올리는 조건과 근거를 한 함수의 한 곳에 두고 단위 시험으로 고정한다.

## 수용 기준
- `python -m pytest tests/acceptance/test_reference_match_guard.py -rxX`: 3건 XPASS(대조군 3건 계속 통과).
- 서면8·9의 내부 규정(특수조건·육군 규정) 처리 유지, `regression_gate.py` 회귀 없음.
- 구현 측 새 시험: 읽기 성공·실패, 제목 일치·부분 일치, 법령·내부 규정 형태의 조합(양성·대조군 각 3건 이상, 시험 입력과 다른 이름으로).
