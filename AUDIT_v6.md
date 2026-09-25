# AUDIT_v6: 하드코딩 감사 (v6 지시서 P0-3)

감사일: 2026-09-26 · 기준 커밋: `196f17f`(0.9.2)

## 점검 기준

| 기준 | 판단 방법 |
|---|---|
| 테스트 문서 리터럴 의존 | 특정 당사자명·사건번호·금액·날짜·문구·기관명에 반응하는 조건이 있는지, 규칙이 그런 값 없이도 성립하는지 |
| 일반화 테스트 | 값·문장 구조가 다른 합성 입력 3건 이상(양성)과 반응하면 안 되는 대조군이 있는지 |

## 1. 정답키 접근 금지(P0-1) 점검

| 항목 | 결과 | 조치 |
|---|---|---|
| 저장소 코드의 정답키 경로 참조 | 이전 채점기(v1, 8f3bad6)가 사용자 PC의 eval_v4 정답키 경로를 하드코딩했다 | 0.9.1에서 제거했다. 채점기 v2는 사람이 `--answer-key`로 넘길 때만 읽고, 개발 루프에서는 쓰지 않는다 |
| 저장소에 있는 블라인드 산출물 | `reports/verification_v088_blind_v2.json`, `reports/verification_v088_blind_v3.json`, `reports/verification_v090_eval_v4.json`(블라인드 문서의 검증 결과, 문서 발췌 포함), `reports/diff_*blind*`, `reports/eval_v4_evaluation_summary.json`(정답키에서 나온 문서별·태그별 적중 수) | 이번 작업에서 열지 않았다. 사용자 결정 필요: 저장소에서 제거할지(git 이력에는 남음) |
| 정답키 파생 정보를 이미 사용한 이력 | 0.9.1 채점기 v2를 만들 때 `reports/eval_v4_evaluation_summary.json`의 **태그 이름 목록**(예: CIT-DATE, ARITH, XDOC)을 읽어 태그→finding 유형 대응표를 만들었다. 문서별 정답 내용은 읽지 않았다 | 채점기에만 쓰였고 탐지 규칙에는 쓰이지 않았다. 알림으로 기록한다 |
| 개발용 정답지 | `tests/fixtures/legal_verifier_testset/ground_truth.json`, `tests/fixtures/holdout/ground_truth.json`, `00_GroundTruth.pdf`는 개발 테스트셋 v1과 자체 제작 홀드아웃의 정답지로, CI 평가 하네스가 읽는다 | 블라인드 정답키가 아니다. v6 P0-1 문구(`ground_truth*`)에 해당하는지 사용자 확인이 필요하다 |

## 2. 규칙별 감사 결과(P0-3)

| 규칙(파일) | 도입 | 리터럴 의존 | 일반화 테스트(전) | 조치 | 일반화 테스트(후) |
|---|---|---|---|---|---|
| 표결 인원 산술 `claim_engine.vote_verifier:VOTE_COUNT_EXCEEDED` | 8f3bad6 | 없음. 재적·찬성·반대·기권 일반 문형이다 | **0건** | 유지. 설명을 '표결 합계 > 재적만 검사, 정족수 충족·근거 규정은 미검사'로 정정(0.9.1) | 양성 3 · 대조군 3 |
| 문서 간 엔티티 `claim_engine.cross_document_entities` | 8f3bad6, 0.9.1 재작성 | **있음**: 판정일 패턴에 지역명 `서울\|경기` 나열 | 5건 | 기관명을 `…위원회` 일반형으로 교체. 판정일은 기관 결합 전까지 승격하지 않음 | 기존 16 + 기관명 변형 3 |
| 조문 표기 형식 `legal_engine.provision_form` | 0.9.1 | 없음. 법령명 일반형과 번호 규칙(제0조, 항·목 가지번호)이다 | 11건 | 유지 | 11건 |
| 날짜 `claim_engine.date_verifier` 신규 분기(요일, 달력 불가, 연도 없는 2월 29일, 경과 일수, 발송 선후 역전) | 8f3bad6 | 규칙은 일반형. 주석 예시 값(특정 일자·일수)이 평가 문서에서 온 것으로 보임 | 3건 | 주석 예시를 중립 표현으로 교체. 경과 일수 정규식 결함 수정('45일 후의'처럼 공백이 있으면 놓침). 1일 차이는 초일 산입 여부(민법 제157조)로 달라질 수 있어 판정하지 않음 | 양성 12 · 대조군 5 |
| 판례 취지·법조문 인용문 대조 `legal_engine.precedent_verifier` | 8f3bad6 | **있음**: 사건번호 3건 전용 왜곡 패턴, 조문 원문 사본 5개(출처·버전 없음) | 특정 사건번호 시험뿐 | **모듈 삭제**. 조문 인용문은 공식 원문 대조(`source_review.verify_statute_source`, 조항호목 원문과 비교)가 이미 맡고 있고, 판례 인용문은 MODIFIED_QUOTE(공식 판결 원문)가 맡는다 | 삭제 확인 1 + 기존 공식 원문 대조 시험(`test_quote_compared_only_with_selected_subitem` 등) |
| `rules.json` `LABOR.STATUTE_ARTICLE_MISQUOTE_26_27` | 8f3bad6 | **있음**: 특정 조문 번호 쌍(제26조·제27조)과 문구 | 0건 | **삭제**. 조문 내용 대조는 공식 원문 경로(P6)가 맡는다 | 삭제 확인 1 |
| `rules.json` `LABOR.RELIEF_INCOMPATIBLE_DISMISSAL_RETIREMENT` | 8f3bad6 | 단일 대립쌍. 근거(basis)가 비어 있는데 CONTRADICTED/B 확정 판정 | 0건 | 삭제 후 전제 대립쌍 데이터 파일(`config/legal_rules/pleading_premise_pairs.yaml`, 4쌍)과 `PLEADING_STRUCTURE_REVIEW`(SUSPICIOUS/C, 법률가 확인)로 이관 | 쌍마다 양성 3(총 12) · 대조군 5 |
| 업무 지시 서술 필터 `adversarial_engine.classifier`(WORKPLACE_SUPERVISOR_RE) | 8f3bad6 | 대조군 오탐을 없애려고 넣은 필터가 실제 인젝션 2종을 가렸다 | 0건 | 0.9.1에서 수정: 같은 문장에 명령 어미나 AI 호명이 있으면 거르지 않음 | 인젝션 3 · 업무 서술 3 |
| 조문 상한 참고표 `legal_engine.statute_ranges` | 8f3bad6, 0.9.1 | 특정 문서가 아니라 주요 법률 목록이지만, 값이 공식 원문과 대조되지 않았다 | 기존 | 판정에 쓰지 않고 참고 메모로만 쓴다. P6에서 공식 조문 목록 기반 판정(`STATUTE_ARTICLE_NONEXISTENT`)으로 대체 예정 | 기존 |

## 3. 남은 확인 사항

- 1장의 블라인드 산출물을 저장소에서 제거할지, `tests/fixtures`의 개발용 정답지를 P0-1 대상으로 볼지는 사용자가 정한다.
- 이번 감사는 규칙 코드와 시험을 점검한 것이다. 삭제한 규칙이 평가 점수에 미치는 영향은 새 블라인드(v5)로 사람이 채점해야 알 수 있다.
