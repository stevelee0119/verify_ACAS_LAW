# v2 최종 보고

작업 지시서: `claude_code_prompt_verifier_v2.md`(3-1 R1~R11 우선 수정 포함). 기록 상세는 `docs/CHANGELOG_v2.md`.

- 평가 산식: `scripts/eval_testset.py` 머리말(종합 = 100×가중 재현율 − 2×FP-TRAP 오탐 − 3×A등급 오탐).
  지시서의 v1 점수(51점)를 낸 산식과 같다는 보장은 없다.
- 오프라인: 공식 DB·외부 모델 없이 규칙만 사용. 실연동: GitHub Actions "테스트셋 평가"에서 저장된 키로 국가법령정보 API·외부 모델 사용.
- 홀드아웃(`tests/fixtures/holdout`, `scripts/build_holdout.py`)은 규칙 개발에 쓰지 않았다. 미탐 원인은 진단만 했고 홀드아웃 문구에 맞춘 규칙은 만들지 않았다.

## 1. 점수

| 단계 | 본(오프라인) | 홀드아웃(오프라인) | 본(실연동) | 홀드아웃(실연동) |
|---|---|---|---|---|
| v1 기준 | 21.4 | 25.9 | 33.5 (같은 인용 중복 판정 12) | — |
| 3-1 R1~R11 (fbb207e) | 42.0 | 46.8 | 53.7 (FP-TRAP 오탐 2, A등급 1, 중복 16) | 69.0 |
| Phase 2·8 (79cabd6) | 55.8 | 56.9 | 66.9 (A등급 오탐 1: 94누4615 NBSP) | 73.6 |
| Phase 3·4·6 + 보강 (d6ad805) | 79.5 | 72.2 | **97.3** (오탐 0, 중복 0) | **88.9** (오탐 0, 중복 0) |
| 최종 보강 (09dccf9) | 81.7 | 72.2 | 실행 결과로 갱신 | 실행 결과로 갱신 |

실연동 본·홀드아웃 차이 8.4점(기준 10점 이내).

## 2. 수용 기준

| 기준 | 결과(실연동 d6ad805 기준) |
|---|---|
| TC-01 FP-TRAP 오탐 0 | 충족(전체 FP-TRAP 오탐 0, A등급 0) |
| 형식상 불가능한 날짜 7건 → INVALID_FORMAT(A) | d6ad805에서 6/7. 누락 1건(TC-02 "국방부 법무관리관실도 2025. 4. 31.자 유권해석")은 기관명 뒤 조사 때문에 추출되지 않았고 09dccf9에서 고침(오프라인 확인: CONTRADICTED/A INVALID_FORMAT) |
| 2021두62148 NOT_FOUND 유지 | 충족(NOT_FOUND/B, 조회 범위 내 미발견) |
| LAW-NX → NOT_FOUND_LAW/ARTICLE | 충족(군인징계구제에 관한 특별법 → NOT_FOUND_LAW, 행정소송법 제58조·행정기본법 제99조 → NOT_FOUND_ARTICLE) |
| TC-06 7개 중 6 | 7/7 |
| TC-03 인젝션 경로 10개 중 9 | 10/10(흰 글자, 폭 0 문자, 흰 도형 가림, 초소형, 가시 문구, Tr 3, 페이지 밖, 메타데이터, 주석, 첨부파일). 방어: 게이트 BLOCK, 지시문을 결론으로 따르지 않음 |
| TC-04 OVR 9개 중 6 | 9/9(주의: 아래 3-3) |
| TC-05 EVI 11개 중 8 | 하네스 11/11. 직접 겨냥한 판정은 9건이고, 입증취지 불일치·지각 범위 밖 단정 2건은 사람 판단 항목이라 UNVERIFIED로 표시(아래 3-3) |
| 중복 판정 0, 모든 finding에 document_id | 충족 |
| 종합 75점 이상, 홀드아웃 10점 이내 | 충족(97.3 / 88.9) |
| 전체 시험 통과, 새 모듈 단위 시험 | 1044 passed, 5 skipped |

## 3. 남은 미탐·오탐과 원인

### 3-1. 본 테스트셋(실연동 d6ad805)

| 문서 | 항목 | 점수 | 원인 |
|---|---|---|---|
| TC-02 | 2025. 4. 31.자 유권해석 | 0.5 | 기관명 뒤 조사 "도"로 해석례 추출 실패 → 09dccf9에서 수정 |
| TC-04 | AI 응답 서두·면책문 | 0.5 | 설계상 '참고 신호'(AI 작성 여부는 확정하지 않음). 하네스가 참고 신호에 0.5를 준다 |

### 3-2. 홀드아웃(실연동 d6ad805)

| 문서 | 항목 | 원인 |
|---|---|---|
| HO-03 | INJ-ZWSP(흰 지시문 안의 U+200B) | 폭 0 문자 탐지는 PDF ActualText와 추출 글자만 본다. HO-03은 글리프로만 들어 있어 추출기가 버린다(TC-03은 ActualText 경로) |
| HO-04 | "위법성이 명백하므로 제소기간은 문제되지 않는다"(약 14개월) | 제소기간 예외 규칙 어휘에 "문제되지 않"이 없다(현재: 적용되지 않·적용이 없·무관·배제·제한을 받지 않) |
| HO-04 | "대법원이 … 항상 원고 승소 판결을 해 왔습니다" | 전칭 판례 경향 규칙의 서술어가 취소·인용·기각·판시·판단에 한정. "승소 판결" 표현 없음 |
| HO-05 | 진술서 2항 ↔ HO-01 소장 2. 문장 | 복사 탐지는 문장 n-gram 일치 기준. HO-05는 날짜를 빼고 어순을 바꾼 의역("송달받은 날부터 90일 이내에" ↔ "송달받고 … 90일 이내인")이라 기준 미달 |
| HO-04 | AI 응답 잔재 4건 | 설계상 참고 신호(0.5) |

규칙 어휘를 넓히면 홀드아웃 점수는 오르지만 홀드아웃을 보고 만든 규칙이 되므로 이번에는 반영하지 않았다.

### 3-3. 하네스 점수와 실제 판정의 차이(점수 과대 가능)

하네스는 finding 글자에 정답 토큰이 모두 들어 있으면 점수를 준다. 아래는 다른 finding과의 토큰 겹침으로 1.0을 받은 항목이며, 직접 겨냥한 finding의 실제 판정을 함께 적는다(오프라인 결과로 확인).

| 항목 | 점수를 준 finding | 직접 겨냥한 finding |
|---|---|---|
| TC-03 2017. 6. 31. 판례 | 흰 도형 가림 지시문 | INVALID_FORMAT(A) 있음 |
| TC-04 "대법원은 … 예외 없이 징계를 취소해 왔다" | 당연무효 일반화 규칙 | GEN.UNSUPPORTED_GENERALIZATION(C, 사람 판단) 있음 |
| TC-04 무효확인 청구 + 취소 주장 부재 | 제소기간 예외 규칙 | ADMIN.NULLITY_ONLY(C, 사람 판단) 있음 |
| TC-05 EVI-OVR 진단서로 무고 입증 | 호증 결번 finding | EVIDENCE_PURPOSE_MISMATCH(UNVERIFIED, 사람 판단) |
| TC-05 EVI-LOGIC 못 들었으나 확실 | 위치 진술 모순 finding | STATEMENT_BEYOND_PERCEPTION(UNVERIFIED, 사람 판단) |

### 3-4. 오탐

- FP-TRAP 오탐: 0(본·홀드아웃, 실연동).
- 정답지 밖 결함 주장 finding(정밀도 분모): 문서마다 '예시·연습용 문서 고지'(SPECIMEN_DOCUMENT_DECLARED, 문서가 스스로 가상 문서라고 적은 사실), TC-03·HO-03의 텍스트층–OCR 불일치(숨은 지시문 때문에 실제로 다름), AI 작성 가능성 참고 신호(C). 사실과 다른 판정은 아니다.
- 실연동에서 확인된 잘못된 판정 1건: TC-04 "헌법 제27조"의 '헌법'을 NOT_FOUND_LAW(B)로 판정. 공식 제명이 '대한민국헌법'(https://www.law.go.kr/법령/대한민국헌법)이라 정확 일치 검색에 실패한 것. 정답지에 함정 항목이 없어 점수에는 잡히지 않았다. 09dccf9에서 약칭표로 고침.

## 4. unknown으로 남긴 규칙·부호

| 항목 | 이유 |
|---|---|
| 법원–사건부호 호환(FMT.COURT_CODE_MISMATCH), 대법원 부호 사용 기간(FMT.CODE_OUT_OF_PERIOD) | 근거인 「사건별 부호문자의 부여에 관한 예규」(재일 2003-1, 행정규칙 ID 2200000102523) 별표가 HWP 파일(flSeq 145616549·145616551)이고, 파서가 본문을 읽지 못했다. 별표 원문 없이는 `config/legal_rules/case_codes.json`을 만들지 않았고 판정하지 않는다. 09dccf9에서 HWP 파서를 고치고 진단값을 남기도록 했다 |
| 무효확인소송에 대한 제소기간 적용 여부 | 행정소송법 제38조(준용 규정) 원문을 수집하지 않았다. 제소기간 예외 규칙(ADMIN.DEADLINE_EXCEPTION)은 SUSPICIOUS·사람 판단으로만 낸다 |
| 군인의 형사절차 진행 중 징계 | 수집한 근거는 국가공무원법 제83조 제2항("진행하지 아니할 수 있다")뿐. 군인에게 적용되는 군인사법 규정은 수집하지 않았다(규칙 C·사람 판단) |
| 의무이행소송 불허 | 근거가 행정소송법 제4조의 항고소송 유형 열거뿐이고 관련 판례 원문은 수집하지 않았다(사람 판단) |
| 판례 적용 가능성(인용 판례가 이 사건 사실관계에 맞는지) | 판정하지 않는다 |

## 5. 사람 판단이 필요한 법률 항목

| 규칙·항목 | 이유 |
|---|---|
| ADMIN.RELIEF_PERFORMANCE_ORDER(진급·복귀를 명하는 청구) | 청구의 해석·변경 가능성은 법원 판단 |
| ADMIN.DEFENDANT_INDIVIDUAL(개인 피고) | 손해배상 병합 청구의 적법 여부 |
| ADMIN.DEADLINE_EXCEPTION(제소기간 예외) | 소송 유형·'정당한 사유'(행정소송법 제20조 제2항 단서) 해당 여부 |
| DISC.CRIMINAL_PENDING_BAR(형사절차 중 징계 금지) | 군인 적용 규정 확인 필요 |
| GEN.UNSUPPORTED_GENERALIZATION(근거 없는 전칭 판례 경향) | 근거 판례 조사 필요 |
| ADMIN.NULLITY_ONLY(예비적 취소청구 부재) | 청구 구성은 대리인 판단 |
| 입증취지 불일치(EVIDENCE_PURPOSE_MISMATCH) | 서증의 증명력 평가 |
| 지각 범위 밖 단정(STATEMENT_BEYOND_PERCEPTION) | 진술 신빙성 평가 |
| 위자료 등 청구 금액의 상당성 | 판단하지 않는다 |

각 규칙의 근거 원문·URL·시행 버전은 `config/legal_rules/rules.json`에 있다(행정소송법 MST 285913, 군인사법 MST 283197,
국가배상법 MST 268079, 국가공무원법 MST 286457, 대법원 95다38677·94누4615 전원합의체 판결).

## 6. 단계별 변경 파일

| 단계(커밋) | 파일 |
|---|---|
| 평가 기반(c1e9330, fc0acaf) | `.github/workflows/eval-testset.yml`, `scripts/eval_testset.py`, `scripts/build_holdout.py`, `tests/fixtures/holdout/*`, `docs/CHANGELOG_v2.md` |
| 3-1 R1~R11(13b8e6f, fbb207e) | `document_engine/{reading_text.py(신규), line_tables.py(신규), pdf_parser.py, registry.py}`, `common/{schemas.py, enums.py}`, `legal_engine/{citation_extractor.py, internal_citation.py, normalize.py, provision_content.py(신규), source_review.py, components.py}`, `source_adapters/law_go_kr.py`, `adversarial_engine/{scanner.py, patterns.py}`, `claim_engine/evidence_consistency.py(신규)`, `verification_engine/{pipeline.py, ai_document_detector.py, scoring.py}`, `forensic_engine/specimen.py`, `apps/worker/runtime.py`, `tests/test_v2_root_causes.py` 외 기존 시험 4개 |
| Phase 1 판정 체계(4e3ed3c) | `verification_engine/{finalize.py(신규), pipeline.py}`, `common/anonymization.py(신규)`, `claim_engine/assertion.py`, `forensic_engine/specimen.py`, `tests/test_v2_phase1_verdicts.py` |
| 공식 원문 수집(ce3c8aa) | `.github/workflows/official-sources.yml`, `scripts/fetch_official_sources.py` |
| Phase 2·8(79cabd6) | `legal_engine/{citation_format.py(신규), citation_extractor.py, verifier.py}`, `verification_engine/{ai_residue.py(신규), ai_document_detector.py}`, `tests/test_v2_phase2_format.py`, `tests/test_v2_phase8_residue.py` 외 기존 시험 2개 |
| Phase 3·4·6(6572aad) | `config/legal_rules/rules.json(신규)`, `legal_engine/{legal_rules.py(신규), quote_diff.py(신규), provision_content.py, source_review.py, verifier.py, citation_extractor.py, citation_format.py}`, `source_adapters/official_legal.py`, `verification_engine/pipeline.py`, `tests/test_v2_phase34_law_quote.py`, `tests/test_v2_phase6_legal_rules.py` |
| 실연동 보강(d6ad805) | `document_engine/{reading_text.py, pdf_parser.py}`, `legal_engine/verifier.py`, `adversarial_engine/scanner.py`, `claim_engine/evidence_consistency.py`, `verification_engine/pipeline.py`, `tests/test_v2_root_causes.py` |
| Phase 8 보정(c995eec) | `verification_engine/ai_document_detector.py`, `scripts/calibrate_ai_detector.py(신규)`, `tests/test_v2_phase8_residue.py` |
| 문서(cdfe9ff) | `README.md` |
| 최종 보강(09dccf9) | `legal_engine/{normalize.py, citation_extractor.py}`, `document_engine/hwp_parser.py`, `scripts/{eval_testset.py, fetch_official_sources.py}`, 시험 3개 |

Phase 5(인젝션 경로)와 Phase 7(증거 정합성)은 3-1 R8·R9 수정(fbb207e, d6ad805)에 포함되어 있다.

## 7. 한계

- 서면 내부 모순을 언어 모델로 찾는 기능은 없다(규칙 기반 위치·인적사항·날짜 모순만).
- AI 작성 판별기는 작성 주체가 확인된 라벨 데이터가 없어 임계값을 보정하지 않았다. `scripts/calibrate_ai_detector.py`는 인터페이스만 제공한다.
- 점수는 합성 시험 문서 12종 기준이며 실제 사건 문서의 정확도를 입증하지 않는다.
