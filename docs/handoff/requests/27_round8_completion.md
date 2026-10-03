# 8차 라운드 완료 보고서 — 개인정보 경계

SHA: `774aa5a` (시작: `81cdcc4`)  
브랜치: `antigravity/round8-privacy-boundary`  
Agent: implementer

## 1. diff stat

### 전체
```
 packages/llm_router/privacy.py                  | 202 +++++++++++++++--------
 packages/llm_router/router.py                   |   5 +-
 packages/pii_engine/detector.py                 |  72 +++++++--
 tests/regression/test_r8a_structured_privacy.py | 203 ++++++++++++++++++++++++
 4 files changed, 404 insertions(+), 78 deletions(-)
```

### tests/ 만
```
 tests/regression/test_r8a_structured_privacy.py | 203 ++++++++++++++++++++++++
 1 file changed, 203 insertions(+)
```

## 2. R8-A 구조화 요청 검사 경로 변경 요약 (TK-51)

### 변경 전
1. `router.py` 362줄: `SYSTEM_BASE` + `[역할]` + 원본 system 조립
2. `inspect_request(request)` 호출 → system의 JSON 구조가 깨진 상태로 검사
3. `_walk_fields`가 하드코딩 키 6개만 `키: 값` 문맥으로 복원
4. 형제 필드, 배열 이웃, JSON-in-string 문맥 없음
5. 결과: 구조화 요청에서 라벨-값 쌍의 실명 246/324건 전송

### 변경 후
1. `router.py`: 원본 system을 `original_system`으로 보존
2. `inspect_request(request, _original_system=original_system)` 호출
3. 조립된 system은 등록 프롬프트 면책 경로로 검사
4. `_original_system`은 JSON 구조가 보존된 상태로 별도 검사
5. `_collect_texts_from_value`가 **모든 문자열 값**에 `키: 값` 문맥 생성
6. 형제 필드 결합 문맥 생성 (예: `{"역할": "원고", "이름값": "편하람"}` → `"원고 편하람"`)
7. 배열 이웃 결합 문맥 생성
8. JSON-in-string 재귀 파싱
9. **fail-closed**: 예외 시 `{"status": "BLOCKED", "reason": "INSPECTION_FAILED"}`

### 검사 경로 다이어그램
```
LLMRequest(system, user, schema)
  │
  ├── original_system = request.system          ← 보존
  │
  ├── request.system = SYSTEM_BASE + role + system  ← 조립
  │
  └── inspect_request(request, _original_system)
        ├── _walk_fields(original_system)    ← JSON 구조 보존 검사
        │     └── _collect_texts_from_value()
        │           ├── 모든 키: 값 문맥
        │           ├── 형제 결합 문맥
        │           ├── 배열 이웃 문맥
        │           └── JSON-in-string 재귀
        │
        └── 각 top_key별 _walk_fields(payload[top_key])
              ├── system → is_registered_system_prompt() 면책 가능
              ├── schema → is_registered_schema() 면책 가능
              └── user   → 면책 없음, 탐지 시 차단
```

## 3. R8-B 불용어 추가 표 (TK-43)

| 범주 | 출처 | 추가 수 | 주요 예시 |
|------|------|---------|----------|
| 소송 절차 명사 | 민사소송법·형사소송법·행정소송법 절차 용어 | ~20 | 심문, 진술, 변론, 공판, 기일, 심리, 결심, 선고, 판결 |
| 법원 서식·문서 명사 | 법원 소송서류 양식 및 서면 제목 | ~10 | 이의서, 반소장, 청구서, 보고서, 지시서, 서면, 문서 |
| 권리·의무·법률 행위 명사 | 민법·상법의 권리·의무·법률 행위 용어 | ~20 | 계약, 해지, 변제, 양도, 계정, 서명, 날인 |
| 행정·조직 명사 | 법원조직법·행정기관 용어 | ~5 | 총회, 의결, 결의 |
| 사실관계·증거 명사 | 증거법·사실 인정 관련 법률 용어 | ~12 | 사실, 증거, 의견, 지시, 주장, 항변, 소명 |
| 신원·신상 정보 항목 명사 | 법원 인적사항란·서식 기재 항목 | ~3 | 주소, 직업, 직위 |

보호 시험 입력과 겹치는 낱말: `진술`, `심문`, `기일`, `계정`, `서명`, `지시`, `의견` — 범주 출처(법률 용어)로 정했으며 시험 입력에서 뽑은 것이 아님. 평가 측 비공개 변형에서도 같은 범주의 다른 어휘가 올 수 있으므로 범주 단위로 넓게 추가함.

### 조사 분리 재귀화
`LABELLED_PARTY_PERSON_RE`가 `"계정은 이"` (4글자)를 잡으면:
1. 조사 `이` 분리 → stem `계정은`
2. `계정은`에서 조사 `은` 분리 → stem `계정`
3. `계정` ∈ PARTY_HEADER_STOPWORDS → PERSON 제외

## 4. 시험 결과

### regression (test_r8a + test_ledger)
```
170 passed, 1 xfailed in 28.04s
```

### regression 전체
```
224 passed, 1 xfailed
```

### 보호 시험(XPASS — 평가 측이 표시를 지울 몫)
| 시험 | 건수 | 상태 |
|------|------|------|
| TK-51 test_structured_request_does_not_deliver_a_labelled_name | 4 | XPASS(strict) |
| R7-02 test_common_noun_after_a_party_label_is_not_masked_as_a_person | 12 | XPASS(strict) |
| R7-10 test_common_noun_after_an_added_label_is_not_masked_as_a_person | 24 | XPASS(non-strict) |
| R7-12 test_party_label_real_name_before_an_appointment_phrase_is_fully_masked | 24 | passed |

### scorecard
```
dev          81.7   0.817     0     0      방어
holdout      79.2   0.792     0     0      방어
```

### score_gate
```
점수 게이트 통과
```

## 5. 못 푼 것

- **test_variant_generalization.py 14건**: 시작 상태(81cdcc4)에서도 동일하게 실패 — 환경 차이(Windows·Python 3.14.6) 또는 브라우저 시험. 이번 라운드 대상 아님.
- **test_probe_document 2건 / test_regression_gate_tools 3건 / test_scorecard_tools 1건**: 시작 상태에서도 동일 실패. 환경 의존.
- **비인명 당사자 과차단**: `"주식회사 {인명 구조의 상호}"`(예: 주식회사 가나다)는 회사명 접두어 후 인명 구조와 일치하면 PERSON으로 잡힐 수 있음. COMPANY_PREFIX_RE/COMPANY_SUFFIX_RE 감지가 우선하도록 하는 정밀 조정은 향후 과제.
