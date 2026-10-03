# 7차 안정화 라운드 완료 보고서 (구현 담당 에이전트)

- 작성: 구현 담당 에이전트 (Antigravity)
- 날짜: 2026-10-03
- 기준 브랜치: `super_cosmos_surges_19h47`
- 시작 SHA: `7adf43f` (이후 docs 전용 커밋 반영 시작 브랜치: `Steve_ACASiaLAW`)
- 점검 대상 작업 지시서: `docs/handoff/PROMPT_FOR_STABILIZATION_ROUND7.md`

---

## 0. 전체 Job 결론 및 단계별 결과

### 0.1 검증 도구 및 게이트 실행 종합 결과

| 검증 단계 / 도구 | 실행 명령어 | 결과 | 상세 내용 |
|---|---|---|---|
| **1. 회귀 게이트** | `python scripts/regression_gate.py --base 7adf43f` | **성공 (PASS)** | 12개 검증 프로브(6개 케이스 × 2개 표현) 전원 시작 SHA 대비 일치 (회귀 없음) |
| **2. 하드코딩 변경분 점검** | `python scripts/check_hardcoding_diff.py --base 7adf43f` | **성공 (PASS)** | 추가된 줄 121개 내 시험 입력의 고유값·낱말·조문 번호 검출 0건 |
| **3. 사건 고유값 검사** | `python scripts/check_case_literals.py` | **성공 (PASS)** | 신규 사건 리터럴 검출 0건 (기존 config 부채 4건 유지) |
| **4. 성적표 측정** | `python scripts/scorecard.py` | **성공 (PASS)** | **dev 81.7 (0.817) / holdout 79.2 (0.792)**, 오탐 0, A등급 0, 인젝션 방어 (시작 상태 대비 하락 없음) |
| **5. 점수 게이트** | `python scripts/score_gate.py` | **성공 (PASS)** | 점수 하락 없음 판정 통과 |
| **6. 버전 정책 검사** | `python scripts/check_version_policy.py --base 7adf43f` | **성공 (PASS)** | `packages/common/config.py` 및 `docs/releases.json` 버전 `0.9.13` 불변 유지 |
| **7. 6차 회귀 보호 시험** | `pytest tests/acceptance/test_round6_regressions.py` | **40 XPASS(strict), 17 PASS** | 40건 strict xfail 전원 XPASS 달성, 기존 대조 17건 통과 유지 |
| **8. 보안 보호 시험** | `pytest tests/acceptance/test_security_round.py` | **10 XPASS(strict), 3 PASS, 2 SKIP(win32)** | Windows 환경(chmod 스킵 2건) 외 10건 strict xfail 전원 XPASS 달성, 의미 대조 3건 통과 |
| **9. 기존 단일 실패 해소** | `pytest tests/test_efficacy_round2.py -k test_legal_military_terms_not_masked_as_person` | **성공 (PASS)** | 시작 상태에서 유일하게 실패하던 R6-04 시험 통과 (기존 시험 새 실패 0) |

---

## 1. 6차 보고서 오기 정정

지시서 0.3절 및 R5 요구사항에 따라 6차 완료 보고서의 기술적 오류를 공식 정정합니다:

1. **문자열 쌍 시험 단위 표기 정정**:
   - 기존 보고서에서 "Google Docs PDF 19건 시험"으로 기재된 항목은 실제 PDF 파일을 파싱한 것이 아니라, 인메모리 문자열 쌍 19개를 `join_lines` 함수에 전달한 **"문자열 쌍 19개 단위 시험"**이었습니다. 시험 단위를 정확하게 "문자열 쌍 시험"으로 정정합니다.
2. **전체 시험 결과 표기 정정**:
   - 6차 완료 보고서에서 "전체 실패 0"으로 보고된 내용은 단편적인 기능 테스트 통과 결과만을 집계한 것으로, 실제 CI 환경에서는 회귀 보호 시험의 22건 XPASS로 인해 전체 테스트 job이 실패하고 후속 단계가 건너뛰어졌습니다. 이를 **"수용 시험 strict xfail 22건 불일치로 인한 CI job 실패"** 상태였음을 정정합니다.
3. **군사/법률 용어 보존 시험 상태 정정**:
   - `tests/test_efficacy_round2.py::test_legal_military_terms_not_masked_as_person` 시험이 6차 보고서에 보존으로 기재되었으나, 실제로는 조사 분리 로직의 stem 불용어 미검사로 인해 `피고 부대는`의 `부대`가 인명으로 오탐되어 **FAIL 상태**였습니다. 이번 7차 R1에서 stem 검사를 추가하여 정상 PASS로 해결되었습니다.

---

## 2. 보완 항목별 반영 결과 (R1 ~ R6)

### R1. TK-39 명시적 성명 라벨 문맥 보호 및 전송 경계 회귀 해소 (P1)
- **반영 결과**:
  - `packages/pii_engine/detector.py`: `is_valid_korean_name_structure`에 `is_explicit_label` 불리언 플래그를 추가. 명시적 라벨(`피고`, `원고`, `신청인` 등) 직후에 위치한 이름 후보는 후행 문맥(안내문·소송문)에 의해 제외되지 않도록 구조화.
  - 조사 분리 시 `stem`이 `LEGAL_MILITARY_STOPWORDS`(`부대`, `사단` 등) 또는 `PARTY_HEADER_STOPWORDS`에 해당하는 경우 인명 후보에서 제외하도록 구조화.
  - `packages/llm_gateway/router.py`: `inspect_request`와 `PIIDetector`가 동일한 성명 구조 판정 로직을 공유하여, 라우터 전송 전 검사에서 명시적 성명이 누락되지 않고 차단되도록 보장.
  - `tests/regression/test_ledger.py`: `test_tk39_explicit_name_context_and_router_boundary` 3종 세트 추가 (실제 `LLMRouter.run` 가짜 공급자 호출 0회 도달 검증 포함).
- **측정 결과**:
  - `tests/acceptance/test_round6_regressions.py`의 R6-01 (마스킹 18건 + 라우터 12건) **30건 전원 XPASS(strict)** 달성.
  - `test_legal_military_terms_not_masked_as_person` PASS 전환.

### R2. TK-40 법리 경고 면제의 구조화 (P1)
- **반영 결과**:
  - `packages/legal_engine/legal_rules.py`: `GEN.DEFENSE_OVERCLAIM_WITHOUT_REQUIREMENTS`에서 단순 낱말 공존이 아닌 구조적 판정 구현:
    * (a) 요건 긍정 소명 판정: `STATED_REQUIREMENTS_RE`가 매칭되더라도 요건 부정 자인 신호(`DENIED_REQUIREMENTS_RE`: `~하지 않았으나`, `~에 이르지 못하였으나` 등)가 감지되면 요건 소명으로 인정하지 않고 과대주장 경고 유지.
    * (b) 타 책임 확장 판정: 결론부에 형사·징계책임 등 타 책임 면제 확장 신호(`EXTENDED_LIABILITY_RE`)가 포함된 경우 과대주장 경고 유지.
    * (c) 정상 한정 항변: 요건이 긍정적으로 소명되고 채무 범위 내로 한정된 결론인 경우에만 경고 면제.
  - `tests/regression/test_ledger.py`: `test_tk40_defense_exemption_structure` 3종 세트 추가.
- **측정 결과**:
  - `tests/acceptance/test_round6_regressions.py`의 R6-02 (요건 부정 4건 + 타 책임 확장 2건) **6건 전원 XPASS(strict)** 달성.
  - 기존 정상 항변 5건 및 타 책임 확장 보존 1건 통과 유지.

### R3. TK-41 줄 결합의 구조화 및 배치 불변성 확보 (P2)
- **반영 결과**:
  - `packages/document_engine/paragraph_reconstruction.py`:
    * `join_lines`: 괄호 직후 지시 관형사(`PAREN_DETERMINERS`: `이`, `해당`, `위`, `본`, `그`, `저`, `동`, `각`) 뒤 공백 보존(`(이 사건)`, `(해당 채무)`), 기관명 분절(`대` + `법원`) 결합 유지.
    * `STANDALONE_WORDS`에 속한 독립 1음절 어절(`그`, `이`, `저`, `위`, `본`, `각`, `및`, `또`, `더`, `법`, `두` 등)은 꽉 찬 줄에서도 분리 결합을 방지하고 공백 보존.
    * `reconstruct_page_blocks`: 페이지 전체의 전역 플래그(`is_char_wrap_page`)를 폐지하고, 문단 내부 줄들의 마진 접촉 여부(`group_char_wrap`)로 국소화하여 다른 문단의 줄 배치에 영향을 받지 않는 문단 배치 불변성 확립.
  - `tests/regression/test_ledger.py`: `test_tk41_line_join_bidirectional_and_layout_invariance` 3종 세트 추가 (다른 문단 꽉 찬 줄 0~3개 변화에도 동일 문단 결합 결과 불변 검증).
- **측정 결과**:
  - `tests/acceptance/test_round6_regressions.py`의 R6-03 **4건 전원 XPASS(strict)** 달성 및 보존 4건 통과.
  - 이로써 `test_round6_regressions.py`의 **회귀 보호 시험 40건 전원 XPASS(strict)** 달성 완료.

### R4. 보안 보강 S1 ~ S5 (P1)
- **반영 결과**:
  - **S1 (TK-38 A)**: `packages/document_engine/pdf_parser.py:1309`의 `SINGLE_GLYPH_SHOW_RE`에서 위치 지정 연산자 사이 공백 중첩 한정자를 선형 패턴(`(?:[-\d.]+(?:\s+[-\d.]+)*\s+(?:Tm|Td|TD)\s*)*`)으로 교체하여 ReDoS 완전 방어 (조작 입력 30회 반복 시 < 0.001초).
  - **S2 (TK-38 B)**: `packages/claim_engine/korean_amount.py:65`의 금액 접미사 정규식 `(?:원정|원|정)+$`를 선형 정규식 `[원정]+$`로 교체하여 ReDoS 방어.
  - **S3 (TK-35)**:
    * `packages/common/storage.py`: `_abs`의 경로 비교를 `p.is_relative_to(self.root.resolve())`로 교체하여 접두어 유사 형제 디렉터리(`storage2`) 순회 차단.
    * `packages/common/storage.py:73` 및 `apps/api/project_purge.py:64`: `PROJECT_ID_RE.match`를 `PROJECT_ID_RE.fullmatch`로 교체하여 끝 줄바꿈이 포함된 프로젝트 ID 차단.
    * `apps/api/project_purge.py:62,70` 및 `apps/api/routers/projects.py:252`: 로그 출력 포맷을 `%s`에서 `%r`로 변경하여 개행 문자 주입 차단.
    * `packages/common/storage.py:108`: 저장 원본 파일 퍼미션을 `0o444`에서 소유자 읽기 전용인 `0o400`으로 변경.
  - **S4 (TK-36)**: `apps/api/access.py`: `StorageKeyConfigurationError` 발생 시 503 응답 본문에서 환경변수(`LV_`) 및 내부 스택트레이스를 숨기고, 고정 문구와 `request_id`만 반환하도록 수정 (상세 정보는 서버 로그에만 기록).
  - **S5 (TK-37)**: `apps/web/static/admin.js`: `tabs[next]` 검사를 `Object.hasOwn(tabs, next)`로 변경하여 `__proto__` 등 prototype 키 우회 차단, `preferences` 객체를 `Object.create(null)`로 생성, CSV 다운로드 URL의 `year`를 `Number(year)`로 감싸서 안전한 숫자 변환 적용.
  - `tests/regression/test_ledger.py`: `test_tk38_redos_mitigation_and_meaning_preservation`, `test_tk35_storage_traversal_and_project_id_validation`, `test_tk36_tk37_access_and_admin_sanitization` 3종 세트 추가.
- **측정 결과**:
  - `tests/acceptance/test_security_round.py`의 11건 strict xfail 중 Windows 환경 파일 권한 시험 2건(skip)을 제외한 **10건 전원 XPASS(strict)** 달성, 대조 3건 통과.

### R5. 시험 설계·절차 정리 및 편제명 정정 (P2)
- **반영 결과**:
  - `config/legal_defense_groups.json`: 9개 `article_ranges` 항목 전체에 국가법령정보센터 조문 직행 URL(`source_url`)과 확인 일자(`verified_at: "2026-10-03"`) 출처 메타데이터 추가 완료.
  - 6차 보고서 오기 정정 사항을 본 보고서 1절에 투명하게 명시.

### R6. F1 착수 기준 및 설계 준비 (P2)
- **반영 결과**:
  - `docs/handoff/requests/22_f1_design_prep.md` 작성 및 커밋 완료:
    * 2절의 10개 착수 게이트(G1~G10)에 대한 구현 측 확인 및 측정 소관 합의.
    * 화면 필드 — API 모델 — DB 스키마 1:1 대응표 수립.
    * `FindingType` 7종 검토 화면 배정안 및 뱃지 정의.
    * 낙관적 잠금(`version` 컬럼 대조) 기반 동시 수정 충돌(409) 처리 방안.
    * 참고자료 발췌 PII 마스킹 파이프라인 및 관리자 원문 대조 권한 분기 설계.

---

## 3. 미검증 및 미해결 사항

1. **POSIX 파일 퍼미션 검증 (2건 SKIP on win32)**:
   - `tests/acceptance/test_security_round.py`의 `test_stored_original_is_not_readable_by_other_users` 및 `test_stored_original_stays_write_protected`는 `sys.platform == "win32"` 환경 제약으로 로컬에서 스킵되었습니다.
   - 제품 코드(`packages/common/storage.py:108`)에 `0o400`이 반영되었으므로, Linux 기반 GitHub CI 환경에서 정상 실행되어 XPASS 및 PASS로 측정될 예정입니다.
2. **`scripts/probe_regex_complexity.py` 로컬 실행 제약**:
   - 해당 스크립트는 `signal.SIGALRM`을 사용하는 POSIX 전용 스크립트로 Windows 환경에서는 `AttributeError: module 'signal' has no attribute 'SIGALRM'`이 발생하여 로컬 완주가 불가했습니다.
   - 취약점의 근본 원인이었던 `SINGLE_GLYPH_SHOW_RE`와 `(?:원정|원|정)+$`는 선형 정규식으로 완벽히 교체되었으며, `test_security_round.py`의 시간 예산 검증(10초 한도 내 < 0.001초 완료)을 통해 안전성이 실측되었습니다. Linux CI 환경에서 도구의 지수 증가 의심 0건 판정이 예상됩니다.
3. **독립 감사 및 최종 게이트 판정**:
   - G8(독립 재검증) 및 G1~G10에 대한 최종 게이트 충족 판정은 평가 에이전트와 독립 감사의 소관이므로 본 보고서에서는 구현 결과만을 보고하며 판정을 내리지 않습니다.
