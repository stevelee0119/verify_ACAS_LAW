# 내부 법령·판례 Mirror (LocalLegalMirror)

폐쇄망 배포(기술설계서 제23장)와 오프라인 검증에서 공식 Source를 대체하는 로컬 데이터 영역이다.
**본 디렉터리에는 어떠한 판례·법령 데이터도 기본 포함되어 있지 않다.**
실제 데이터는 국가법령정보 공동활용(https://open.law.go.kr/)에서 정식 절차로 내려받아 배치해야 한다.
검증 결과의 신뢰성이 데이터 출처에 직접 좌우되므로, 임의로 작성한 데이터를 넣지 않는다.

파일이 없으면 Mirror는 조용히 비활성 상태가 되고, 검증은 외부 공식 API를 사용하거나
해당 항목을 `UNVERIFIED`로 표시한다(제10장 Graceful Degradation).

## cases.json

```json
[
  {
    "case_number": "2023도12345",
    "court": "대법원",
    "decision_date": "2024-01-15",
    "case_name": "사건명",
    "case_kind": "판결",
    "holding": "판시사항 원문",
    "summary": "판결요지 원문",
    "detail_link": "https://www.law.go.kr/..."
  }
]
```

`case_number`는 공백을 제거한 canonical 형태로 저장한다(제9.3장).

## laws.json

조문 단위로 저장하며, 사건 당시 시행법 검증(제9.4장)을 위해 시행기간을 반드시 포함한다.

```json
[
  {
    "law_name": "형법",
    "article": "250",
    "paragraph": "1",
    "text": "조문 원문",
    "effective_from": "1953-10-03",
    "effective_to": null,
    "promulgation_date": "1953-09-18",
    "detail_link": "https://www.law.go.kr/..."
  }
]
```

`effective_to`가 `null`이면 현행 조문으로 본다. 동일 조문의 개정 이력은 여러 항목으로 나누어 적고,
검증 시 사건 발생일이 속하는 version을 선택한다. 해당 시점 version이 없으면 현행본을 반환하되
`as_of_match: false`로 표시하여 `TEMPORAL_LAW_MISMATCH` 판단 근거로 삼는다.
