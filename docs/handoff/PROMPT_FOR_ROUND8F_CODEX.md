# 8E 판정과 8F 작업 지시서 — 8C 수렴 + 연락처·주민등록번호 보장 (구현: Codex)

작성: 평가 에이전트(claude-code) 2026-10-04
근거:
- [TK-56](TK-56_round8e_structured_regression_and_convergence.md)(8E 판정·8C 수렴)
- [TK-57](TK-57_contact_rrn_notation_gaps.md)(연락처·주민등록번호 표기 변형)
- [f1_gate_verdict '8차 5차 판정'](../scorecards/f1_gate_verdict.md)

**사용자 결정(2026-10-04)**
1. 8C로 수렴한다.
2. 자동 마스킹 **보장 대상은 연락처·주민등록번호**다. 성명 등은 사용자가 업로드 전에 직접 처리하도록 안내·확인한다(화면 작업은 별도 지시서, 담당 Antigravity).
3. 성명 자동 마스킹은 **보조 기능으로 유지**하고 8C 수준에서 동결한다. 더 개선하지 않는다.

아래 전체를 Codex 작업 설명에 붙여 넣는다. 저장소 루트의 `AGENTS.md`도 함께 따른다.

## 1. 8E 판정: 불승인
측정: 3306895(제품 = 2c52653). 실제 라우터 경로, 오프라인, Linux, Python 3.11.15, tesseract 5.3.4.
- **회복된 것:** 과차단 6/28, 명시적 이름 필드 키 값 모양 0, 원본 system 경로 fail-closed, `verify_all` 종료 0
- **불승인 사유:**
  - 구조화 실명 도달 0 → **12/432**(P1 회귀, schema·metadata). '이름'·'성명'을 사람 라벨에서 빼 문맥 라벨이 `명`이 된 탓이다.
  - 키 변형 **6/120**
  - 역할 라벨·일반 name 키 값 모양이 8C 수준으로 재발(지시서 2절 3 불이행)
- 보고서·범위·평가 측 strict xfail 24건 유지는 사실과 맞다.

## 2. 8F 범위
### A. 성명: 8C 동작으로 수렴(작고 정확하게)
1. `packages/llm_router/privacy.py`를 **86bd035 판으로 되돌린 뒤** 다음 네 가지만 바꾼다.
   - (a) `detector.STRUCTURED_PERSON_KEY_LABELS`를 가져온다.
   - (b) 영문 사람 키 어휘(`_ENGLISH_PERSON_KEY_LABELS`)는 `STRUCTURED_PERSON_KEY_LABELS`에서 만든다.
   - (c) `CONTEXT_LABEL_KEYS`에 `STRUCTURED_PERSON_KEY_LABELS`를 더한다.
   - (d) 영문 키로 판정된 경우 합성 문맥의 라벨은 detector가 아는 한글 라벨(`이름`)로 쓴다. 평문 정규식에 영문 라벨이 없기 때문이다.
2. 영문 라벨 구를 맞추는 순서를 **결정적으로** 한다(긴 구 우선 정렬 등). 집합 순회 순서에 기대면 실행마다 판정이 달라질 수 있다.
3. `detector.py`의 영문 어휘 분리(8D)는 그대로 둔다. 평문 탐지 결과가 시작과 같아야 한다.
4. 평가 측이 scratch 작업 트리에서 위 1(a)~(d)를 적용해 본 결과, 세트 기준을 모두 충족했다. 다만 구현과 검증 책임은 구현 측에 있다.

### B. 연락처·주민등록번호 보장(TK-57)
1. 표기 변형(구분 기호의 유니코드 변형과 다른 기호, 문자폭, 줄바꿈·공백 삽입, 괄호 표기)을 **정규화로** 다룬다. 형태 목록을 늘리는 방식은 쓰지 않는다.
2. 정규화한 탐지 결과는 **원문 위치로 되돌려** 마스킹 구간을 정확히 표시한다.
3. 오탐(사건번호·날짜·금액·사업자번호·법인등록번호·법령 번호)을 늘리지 않는다.
4. 바꿀 수 있는 곳: `detector.py`의 연락처·주민등록번호 탐지 부분과, 그에 필요한 정규화 도우미

### C. 시험 표시(평가 측 결정 — 그대로 적용)
A로 8D·8E의 값 fail-closed 동작을 포기하므로, 그 동작을 검사하던 시험은 **알려진 미해결**이다. 아래 노드에만 `@pytest.mark.xfail(strict=True, reason="TK-56 알려진 미해결: 8C 수렴(사용자 결정 2026-10-04)")`를 붙인다.
- 매개변수 일부만 해당하면 `pytest.param(..., marks=...)`로 그 매개변수에만 붙인다.
- 그 밖의 시험은 바꾸지 않는다. 평가 측 scratch 확인 기준으로 21건이다.

| 파일 | 시험(매개변수) |
|---|---|
| test_r8d_key_context.py | `test_name_fields_outside_exact_label_vocabulary_fail_closed` [신청자 성함-배하린], [계약명의자-서이겸], [상담직원명-임다온], [delegateNm-오하윤] |
| 〃 | `test_name_key_values_with_spacing_lists_titles_or_particles_are_blocked` 전체 5건 |
| 〃 | `test_person_role_key_with_attached_particle_keeps_name_stem_context` |
| 〃 | `test_non_person_keys_keep_scanning_without_name_key_fail_closed` [institutionName-국립수로관측소] |
| 〃 | `test_uncertain_non_korean_or_non_string_name_field_values_are_blocked` 전체 3건 |
| test_r8e_key_context.py | `test_explicit_person_name_fields_keep_fail_closed_value_shapes` 전체 5건 |
| 〃 | `test_name_field_fail_closed_blocks_actual_router_send_in_both_positions` [user], [original_system] |

- 위 목록 밖에서 실패가 나면 표시하지 말고 원인을 고치거나 보고서에 적는다.
- `test_person_label_survives_a_preceding_nonperson_word`는 A-2(결정적 순서)로 통과해야 한다.

## 3. 브랜치·제약
- 같은 브랜치 `codex/round8c-key-context`, PR #10. 시작 전 `git merge origin/evaluator/round8-promotion`(병합 커밋, 리베이스·강제 푸시 금지)
- 바꿀 수 있는 파일
  - `packages/llm_router/privacy.py`
  - `packages/pii_engine/detector.py`: B와 정규화 도우미만. 성명 판정·불용어는 바꾸지 않는다
  - 2절 C의 표시
  - 새 시험 `tests/regression/test_r8f_contact_rrn.py`
  - `docs/handoff/requests/` 아래 메모·보고서
- 하지 않는 것
  - 성명 판정 개선
  - 불용어 변경
  - 2절 C 목록 밖의 시험 삭제·수정·표시
  - 보호 경로 변경
  - 평가 측 비공개 수치 추정
- 새 시험의 입력은 새로 짓는다. 다음을 넣는다.
  - 연락처·주민등록번호 표기 변형: 실제 `LLMRouter.run`(가짜 공급자)으로 user·system·구조화 값이 미전송인지
  - 오탐 대조: 전송·미탐지
  - 마스킹 구간이 원문 위치와 맞는지

## 4. 설계 메모 먼저(반 쪽)
`docs/handoff/requests/36_round8f_design.md`에 다음을 적는다.
- (a) B의 정규화 방식과 위치 되돌림
- (b) 오탐을 막는 근거
- (c) 시험 계획

A는 되돌림이라 메모를 적게 써도 된다.

## 5. 점검·보고
- `python scripts/verify_all.py --base d20cde2` 전체 모드, 종료 0. 환경을 적는다.
- 보고서 `docs/handoff/requests/37_round8f_completion.md`
  1. `git diff 3306895 HEAD --stat`(전체와 `-- packages/ tests/`)
  2. 메모 링크와 달라진 점
  3. `verify_all` 출력 그대로
  4. 같은 SHA의 CI 링크와 단계별 결과(완료된 것)
  5. 2절 C 표시 목록과 실제 표시가 같다는 확인
  6. 못 푼 것

## 6. 수용(평가 측이 실제 라우터 경로로 잰다)
- **연락처·주민등록번호(필수 게이트):** 평가 측 `contact_rrn` 세트와, 수용 시점에 새로 지은 세트에서 탐지 누락 0, 공급자 도달 0, 오탐 0
- **성명(동결 기준 — 8C 수준 유지):** 키 변형 0/120, 과차단 ≤ 6/28, 구조화 0/432·0/216, 평문 0/240·0/108, 라벨+실명 0/180, stem 16/16, 이름 330·60, `detect()` 예외 0, 평문 오탐 0. 값 모양·키 신호 없는 유형은 측정해 보고만 한다.
- 평가 측 strict xfail 24건 xfail 유지, 2절 C 표시가 목록과 일치, `verify_all` 종료 0, 같은 SHA CI 필수 3개 성공

## 7. 수용 뒤
1. 평가 측이 판정을 기록한다.
2. 사용자 승인으로 PR #5 브랜치를 최종 초록 SHA로 fast-forward하고, 사용자가 병합한다.
3. 업로드 안내 화면(Antigravity)이 합쳐지면 첫 릴리스를 [RELEASE_PROCEDURE](../scorecards/RELEASE_PROCEDURE.md)대로 진행한다.
