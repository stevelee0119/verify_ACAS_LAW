# TK-43 재개 구현 보고 — PR #62

기준은 Steve `0bf4ccc`이며 평가 측 PR #61의 티켓 「재개(2026-10-10)」와 사용자 통합 지시 (11)를 적용했다. 첫 커밋 `90f8d96`은 설계 메모다. 최종 제출 SHA·diff stat·CI 링크와 scorecard 전후 원문은 [PR #62](https://github.com/stevelee0119/verify_ACAS_LAW/pull/62)에 기록한다.

## 변경과 경계

- `packages/pii_engine/name_stopwords.py`: 범주 정의·공개 출처와 닫힌 불용어 집합. 법령 번호·문장·당사자·시험 명사를 선택 조건으로 쓰지 않는다. 출처는 범주 선정 근거이며 목록이 출처 원문의 자동 추출 결과라는 뜻은 아니다.
- `packages/pii_engine/detector.py`: 완전한 후보만 신규 목록과 대조한다. 신규 목록을 기존 조사 분리 stem이나 첫 토큰 제외에 합치지 않는다. 같은 글자로 시작하고 뒤에 이름 음절이 이어지는 후보와 신규 목록에 속하는 명시 성명 필드는 계속 마스킹한다. 기존 불용어·조사 1회 분리·라벨·후행 문맥·가림 구간 처리는 유지한다.
- `tests/test_tk43_category_stopwords.py`: 합성 자료만 사용. 5범주마다 일반 명사 3개와 같은 접두부 이름 3개, 6종 라벨·구분자·띄어쓰기·조사, 모호한 끝 음절, 명시 성명 필드, 실제 LLMRouter.run(system/user)에서 일반 명사 통과·실명 차단·가림 후 통과를 함께 시험한다.
- 구조화 키 판정(TK-56), 법리, 줄 결합, PII 필수 연락처/RRN 규칙·전송 정책·공유 작업 파일·버전은 변경하지 않았다. 새 의존성·새 정규식이 없다. 보호 경로와 기존 시험 기대값·skip/xfail 변경은 없다.

## 불용어 추가 표

낱말 수는 기존 세 집합의 합집합과 비교한 차집합이다. 두 신규 범주에 중복된 `선서`를 전체에서는 한 번만 센다.

| 범주 | 범주 목록 수 | 기존 대비 추가 수 | 출처(목록 머리에 URL 포함) |
|---|---:|---:|---|
| 절차 행위·의사표시·절차상 권리 | 60 | 60 | 민사소송법·민사소송규칙·행정절차법 |
| 신청·통지·증빙·첨부 기록 항목 | 59 | 59 | 법원 전자민원센터 양식모음·민원 처리에 관한 법률 시행규칙 |
| 재산·소득·금융·조세·비용 항목 | 70 | 70 | 소득세법·민사집행법·국민기초생활 보장법·은행법 |
| 신원·연락·가족관계·주거·부양 항목 | 60 | 60 | 가족관계의 등록 등에 관한 법률·주민등록법 시행규칙·가사소송규칙 |
| 근로·업무·근로조건·관리기록 항목 | 60 | 59 | 근로기준법 시행규칙·산업안전보건법·개인정보 보호법 |
| 전체(중복 제거) | 308 | **307** | 위 범주 출처 |

## 실행한 시험

환경: Linux, Python 3.12.14, LV_ALLOW_NETWORK=0, 서비스 대역. 관련 개인정보·보호 시험만 실행했으며 verify_all은 실행하지 않았다.

```text
LV_ALLOW_NETWORK=0 /workspace/venv/bin/python -m pytest -o addopts='' -q \
 tests/test_tk43_category_stopwords.py tests/test_pii_and_claims.py \
 tests/test_tk20_pii_layout_invariance.py \
 tests/test_efficacy_round2.py::test_legal_military_terms_not_masked_as_person \
 tests/acceptance/test_pii_label_variants.py \
 tests/acceptance/test_round6_regressions.py tests/acceptance/test_round7_findings.py \
 tests/regression/test_r8a_structured_privacy.py tests/regression/test_r8c_key_context.py \
 tests/regression/test_r8d_key_context.py tests/regression/test_r8e_key_context.py \
 tests/regression/test_r8f_contact_rrn.py tests/regression/test_r8f1_rrn_linebreak.py
1221 passed, 29 xfailed in 5.44s
```

별도 시간 출력: `TK-43 supplemental path 6,000 synthetic candidates: 0.000335s` (`1 passed in 0.58s`). 신규 경로의 0.1초 상한이다. 기존 모든 탐지기를 합친 detect의 2,000필드 합성 입력은 단독 비교에서 기준 0.056012초 → 변경 0.054488초였다. scorecard와 병렬 실행한 최초 전체 탐지 시간 시험은 0.142316초로 실패했다. 기존 탐지기의 비용·CPU 경합을 신규 경로의 시간으로 간주하지 않도록 신규 판정 경로 자체를 시간 시험 대상으로 분리했다. 최종 시험은 동일한 0.1초 기준이며 양방향 탐지·마스킹·라우터 시험은 별도로 유지했다.

합성 일반 명사 필드 360건은 기준 360/360 과마스킹 → 변경 0/360이다. 평가 측 비공개 140·112 세트의 입력·수용 수치는 확인하지 않았으며 이 합성 결과를 그 지표로 대체하지 않는다.

## 남은 범위와 평가 측 요청

일반 명사에 조사가 붙은 모습과 같은 철자의 이름, 띄어쓴 이름과 구별되지 않는 후보는 계속 가린다. 따라서 비공개 과마스킹 각 10% 이하 달성은 미확인이다. 추가된 명사와 이름 철자가 완전히 같고 직접 성명 표지도 없으면 닫힌 불용어 방식의 구별 한계가 남는다.

평가 측에 과마스킹 두 지표, 기존 유출/이름/stem/정상 문장 지표, 필수 개인정보 게이트, 수용 SHA verify_all 전체 및 다음 릴리스 봉인 시험을 요청한다. 평가 측 수용 전 TK-56·TK-45 및 줄 결합 구현은 시작하지 않는다. PR #53은 변경하지 않으며 구현 PR을 직접 병합하지 않는다.
