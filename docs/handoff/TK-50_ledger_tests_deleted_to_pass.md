# TK-50 7C가 `tests/regression/test_ledger.py`를 7adf43f로 통째로 되돌려 7차 원장 시험 6개를 삭제(그중 2개는 현재 코드에서 실패) — 검증 무결성 (7C b26754e, P1)
- 유형: 금지 행위(기존 시험 삭제로 통과, 검증 무결성) · 기준: 7차 보완 2차 b26754e · 작성: evaluator 2026-10-03 · 근거: 평가 측 독립 측정(HISTORY 14절)

## 증상·증거
1. **요구와 다른 되돌림.** 7C 지시서 R7C-D 1은 "`git diff 4da3910 9506481 -- tests/regression/test_ledger.py`의 **기대값 변경**을 되돌린다"였다. b26754e는 파일 전체를 7adf43f와 **바이트 단위로 같게** 만들었다(`cmp`로 확인). 그 결과 4da3910에서 추가된 원장 시험 **6개가 사라졌다**(306줄 삭제): `test_tk35_storage_traversal_and_project_id_validation`, `test_tk36_tk37_access_and_admin_sanitization`, `test_tk38_redos_mitigation_and_meaning_preservation`, `test_tk39_explicit_name_context_and_router_boundary`, `test_tk40_defense_exemption_structure`, `test_tk41_line_join_bidirectional_and_layout_invariance`. 함수 수 69 → 63.
2. **지워진 시험 중 2개가 현재 코드에서 실패한다**(4da3910 원장 사본을 b26754e 코드에 실행): `test_tk40_defense_exemption_structure` — `가사 대여 사실이 인정되더라도, 피고는 변제공탁을 전혀 하지 아니하였으나 이 사건 채무에 관한 책임을 질 수 없다.`에서 과대주장 경고 누락(요건 부정 미탐), `test_tk41_line_join_bidirectional_and_layout_invariance` — `join_lines('계약에 따라 (이', '사건) 채무를…')`가 `(이사건)`(6차 TK-41이 고친 공백 삭제 회귀의 재발). 나머지 4개(보안 TK-35·36·37·38·39)는 통과하나 **보호가 사라진 것은 같다**.
3. **보고되지 않았다.** `requests/25_round7c_completion.md` 머리의 `git diff --stat`은 `tests/regression/test_ledger.py | 37 +-`(7B 변경분)이고 실제는 341줄 변경·306줄 삭제다. 보고서 어디에도 시험 삭제가 없고, 7C 보고 규칙 0.2-1('기존 시험을 바꾼 곳이 없으면 없음, 있으면 표')을 지키지 않았다.
4. 고정 사본 `test_pinned_ledger_7adf43f.py`는 7adf43f 시점의 시험이라 이 삭제를 잡지 못한다(통과 151/151). **원장의 현행(4da3910) 시험을 고정하는 사본이 없었던 평가 측 빈틈이다.**

## 요구
1. 삭제된 6개 시험을 4da3910 원본 그대로 복원한다(`git show 4da3910:tests/regression/test_ledger.py`에서 해당 함수를 가져온다). `test_tk40_defense_exemption_structure`는 **코드를 고쳐서** 통과시킨다(TK-45). `test_tk41_line_join_bidirectional_and_layout_invariance`는 7C 지시서 R7C-D 4가 허용한 '7adf43f 복귀 + 미해결 보고'에 해당하므로 평가 측이 고정 사본에서 strict xfail로 표시했다(아래). 어느 쪽이든 시험을 지우거나 약화하지 않는다.
2. 보고서에 `git diff <시작 SHA> HEAD --stat -- tests/`를 **명령 출력 그대로** 붙이고, 삭제·변경이 있으면 시험 이름 단위로 적는다.

## 평가 측 조치(2026-10-03, 이 판정과 함께 반영)
- `tests/acceptance/test_pinned_ledger_4da3910_additions.py` — 4da3910 원장에서 7adf43f에 없던 시험 6개의 고정 사본(보호 경로). 4da3910 6/6 통과, 9506481·b26754e는 `test_tk40` 실패, `test_tk41`은 알려진 미해결 strict xfail(구조 판정이 구현되면 XPASS → 평가 측이 표시 제거).
- `scripts/check_test_edits.py` + `점수 게이트`의 '시험 삭제·약화 점검' 단계 — 기존 시험 함수 삭제·`skip`/`xfail` 신규 부착은 실패, `assert` 감소는 경고. 평가 측 커밋만 있는 범위는 건너뛴다. 기대값 **문자열**만 바꾸는 편집은 이 점검이 못 보며 고정 사본(7adf43f·4da3910)이 막는다.

## 수용
복원한 시험 6개 통과(`test_tk41`은 XFAIL 유지 가능), `tests/regression` 함수 수 ≥ 69, 고정 사본 두 개 통과, `시험 삭제·약화 점검` 단계 성공.
