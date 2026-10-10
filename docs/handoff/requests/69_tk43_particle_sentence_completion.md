# TK-43 개정 1 문장형 조사 보완 보고

PR #62의 같은 브랜치에 Steve `6323400`을 병합 커밋 `55829d0`으로 받아 보완했다. 설계 메모 첫 커밋은 `2ea2831`이며 최종 제출 SHA와 CI 링크·원문 출력은 PR 댓글에 기록한다. 이 보고의 시험 결과는 제출 코드와 동일한 트리에서 측정했다. 구현 PR은 직접 병합하지 않는다.

- 변경: `detector.py`는 라벨 뒤 원문 어절을 범주 명사 또는 범주 명사+조사 한 개로 비교한다. 단성 3음절/복성 4음절과 겹치는 한 음절 조사형, 명시 성명, 일부 띄어쓴 성명은 보호한다. 기존 `LABELLED_PARTY_PERSON_RE`의 고정 해시와 평문 라벨 어휘를 유지하며, 같은 접두부를 공유하는 유한 복합 조사 보조 패턴으로 성명+복합 조사도 탐지한다. 기존 문법 조사 집합은 추가하지 않았다.
- `name_stopwords.py`는 문서 설명만 갱신했다. 목록은 추가·삭제하지 않았다. 어휘는 완전 일치로만 확인하고 조사를 재귀적으로 떼거나 서술어 예외 목록을 쓰지 않는다. 마스킹과 실제 라우터 inspect_request가 같은 detect 결과를 사용한다. 구조화 키 정책은 변경하지 않았다.
- 새 `tests/test_tk43_particle_sentences.py`의 713건은 전부 합성이다. 구별 가능형 세 종류마다 서로 다른 3건, 구별 불가형·같은 접두 성명·조사형 끝 음절·명시 성명·전체/부분 띄어쓰기·조사 중복과 실제 LLMRouter.run(system/user)을 검사한다. 복성 가드의 시험 전용 합성 항목은 monkeypatch로만 주며 제품 목록에는 넣지 않았다. 기존 시험 기대값·skip/xfail·보호 파일은 수정하지 않았다.

| 범주 | 목록 수 | 이번 추가 | 출처 |
| --- | ---: | ---: | --- |
| 절차·행위·신청 | 60 | 0 | 민사소송법·민사소송규칙·행정절차법 |
| 서식·증빙·기록 | 60 | 0 | 법원 양식모음·민원 처리에 관한 법률 시행규칙 |
| 재산·금융·조세 | 70 | 0 | 소득세법·민사집행법·국민기초생활 보장법·은행법 |
| 신원·가족·생활 | 60 | 0 | 가족관계등록법·주민등록법 시행규칙·가사소송규칙 |
| 근로·업무·정보관리 | 60 | 0 | 근로기준법 시행규칙·산업안전보건법·개인정보 보호법 |
| 합집합 | 308 | 0 | 개별 목록 머리에 공개 URL, 종전 구현의 순증은 307 |

관련 시험 명령(네트워크 금지, 실제 외부 공급자는 합성 대역):

```sh
LV_ALLOW_NETWORK=0 /workspace/venv/bin/python -m pytest -o addopts='' -q \
 tests/test_tk43_category_stopwords.py tests/test_tk43_particle_sentences.py \
 tests/test_pii_and_claims.py tests/test_tk20_pii_layout_invariance.py \
 tests/test_efficacy_round2.py::test_legal_military_terms_not_masked_as_person \
 tests/acceptance/test_pii_label_variants.py tests/acceptance/test_round6_regressions.py \
 tests/acceptance/test_round7_findings.py tests/regression/test_r8a_structured_privacy.py \
 tests/regression/test_r8c_key_context.py tests/regression/test_r8d_key_context.py \
 tests/regression/test_r8e_key_context.py tests/regression/test_r8f_contact_rrn.py \
 tests/regression/test_r8f1_rrn_linebreak.py
```

```text
1934 passed, 29 xfailed in 7.90s
TK-43 sentence word path 6,000 calls: 0.004753s
.TK-43 label regex 2,000 sentences: 0.003880s
.
2 passed in 0.70s
```

동일한 합성 행렬을 종전 cceeb38 detector와 보완 detector로 비교했다. 성명 수치는 정상 어절/낱글자 띄어쓰기/부분 띄어쓰기에서 전체 합성 성명을 포함하는 PERSON 구간이 있는지 센 값이다. 라벨 9종을 사용했다.

```text
before cceeb38: noun sentences masked 162/243; complete synthetic names detected 143/243
after working tree: noun sentences masked 0/243; complete synthetic names detected 243/243
ambiguous synthetic category sentences: 2592, previously masked but now unmasked: 0
```

이 합성 비교는 비공개 수용 수치의 추정이 아니다. 평가 측은 개정된 구별 가능 과마스킹 각 10% 이하, 구별 불가 가림 수 시작 이상, 유출·이름·stem·필수 게이트 유지와 수용 SHA verify_all·릴리스 봉인을 별도로 판정한다. 고정 scorecard는 전후 dev 81.7·holdout 79.2·오탐 0이다. 최종 커밋 후 원문을 PR에 첨부한다. verify_all은 로컬에서 실행하지 않았다.

제한: 명사와 같은 철자의 이름 및 평가 측 정의 밖의 이름은 기존 휴리스틱의 한계다. 구별 불가형의 잔여 과마스킹을 유지하며 확정적 문맥을 새로 추정하지 않는다. 범주 목록·새 의존성·프로그램 버전·다른 담당의 파일은 수정하지 않았다. Tk-56, 줄 결합 2단계, TK-45는 선행 평가 수용 조건을 기다린다.
