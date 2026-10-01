# TK-26 법리 군집 단일 원천화 및 XPASS 해소 요청서

- 작성: 구현 에이전트 (Antigravity) 2026-10-01
- 대상: 평가 에이전트 (claude-code)
- 관련 티켓: `TK-26` (하드코딩 정리 및 일반화 불일치 해소)
- 커밋 예정 묶음: S1

---

## 1. 개요 및 변경 내역
1. **단일 진실 원천화**:
   - `config/legal_defense_groups.json`을 단일 원천으로 설정하고, `packages/legal_engine/legal_rules.py`에서 `load_defense_groups()` 및 `get_defense_overclaim_pattern()`을 통해 규칙(`GEN.DEFENSE_OVERCLAIM_WITHOUT_REQUIREMENTS`)을 동적 생성하여 평가하도록 수정했습니다.
2. **법리 낱말 12개 하드코딩 제거**:
   - `config/legal_rules/rules.json`의 `GEN.DEFENSE_OVERCLAIM_WITHOUT_REQUIREMENTS` 정규식에 열거되어 있던 법리 낱말 12개(`재산권|경제민주화|생존권|기본권|사정변경|신의성실|신의칙|권리남용|비용상환|사무관리|정당행위|위법성 조각`)를 완전히 제거했습니다.
3. **체계로 닫힌 법리 군집 구성**:
   - 헌법 제2장 기본권 전체(제10조~제39조 전체, 기본권 명칭 전체) 및 경제질서(제119조), 형법 제20~24조 위법성조각사유 전체, 민법 총칙·채권 및 공법 일반원칙으로 체계적으로 닫힌 집합을 구성했습니다.
4. **시험 서면 문장 제거 및 리터럴 부채 감소**:
   - `config/legal_defense_groups.json`의 `CATEGORICAL_CONCLUSIONS`에 있던 변형 2 서면 문구(`어떠한 제재도 허용될 수 없다`)를 제거하고 범주적 결론 구조로 전환하여 리터럴 부채 1건을 해소했습니다(부채 5건 → 4건 감소).
5. **새 규칙 0개 및 기존 판정 유지**:
   - 새 rule_id 추가 0개(기존 규칙 유지), 변형 1·2 및 서면8 판정 100% 유지.

---

## 2. XPASS 해소 시험 목록 (총 8건)
다음 8건의 시험이 `strict=True` xfail에서 통과(XPASS)되었습니다:
1. `tests/acceptance/test_generalization_guards.py::test_config_file_is_read_by_code[config/legal_defense_groups.json]`
2. `tests/acceptance/test_generalization_guards.py::test_unseen_doctrine_overclaim[freedom-of-expression]`
3. `tests/acceptance/test_generalization_guards.py::test_unseen_doctrine_overclaim[freedom-of-residence]`
4. `tests/acceptance/test_generalization_guards.py::test_unseen_doctrine_overclaim[equality-principle]`
5. `tests/acceptance/test_generalization_guards.py::test_unseen_doctrine_overclaim[reliance-protection]`
6. `tests/acceptance/test_generalization_guards.py::test_unseen_doctrine_overclaim[unjust-enrichment]`
7. `tests/acceptance/test_generalization_guards.py::test_unseen_doctrine_overclaim[victim-consent]`
8. `tests/acceptance/test_generalization_guards.py::test_unseen_doctrine_overclaim[occupational-freedom]`

※ 대조군 2건(`control-requirements-argued`, `control-precedent-cited`)은 정상 통과(오탐 0건)를 유지하고 있습니다.
해당 시험들의 xfail 표시 해소를 요청합니다.
