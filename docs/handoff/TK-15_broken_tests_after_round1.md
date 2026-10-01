# TK-15 1차 구현이 깨뜨린 기존 시험 복구 (main CI 실패 중)
- 유형: 회귀 시험 · 기준 커밋: cf7c739 · 작성: evaluator 2026-10-01
- 측정: `python -m pytest -q --ignore=tests/acceptance` (평가 측 로컬 + GitHub `CI` 실행 36804053790)

## 실패 목록(cf7c739)
| 시험 | 원인 | 처리 |
|---|---|---|
| `test_case5_medical_malpractice_complaint.py::test_case5_rag_exhibit_facts_contradiction_detection` | 설명문에서 `NUMERICAL_FRAUD`를 뺐는데(TK-08 요구) 시험은 그 문자열을 기대 | 시험을 새 중립 문구(수치 불일치·확인 필요)로 고친다 |
| `test_case6_military_secret_defense_opinion.py::test_line_break_marker_rule_is_narrow` 2건 | **은닉 신호 탐지가 약해졌다.** 이 시험의 경계(① 다른 곳에서 쓰이지 않는 글리프 하나를 덮는 U+200B, ② 평소 공백 글리프라도 다른 글꼴이면 인정 안 함)는 "글자 사이에 끼운 폭 0 문자"를 은닉으로 잡는 기준인데, TK-06의 `ET` 직전 규칙이 두 경우를 줄바꿈 표시로 풀어 준다 | **시험을 고치지 말고 규칙을 고친다.** `ET` 직전 조건은 평소 공백 글리프 조건과 **함께**(AND) 요구하거나, 위치 조건을 쓰려면 위 두 경계 시험이 통과해야 한다. 평가 측 합성 PDF(글자 사이 ZWSP, 은닉 글리프는 본문에 안 쓰임)에서 탐지 건수가 819e450 3건 → cf7c739 2건으로 줄었다 |
| `test_evidence_rag_review.py::test_8803_chars_are_all_reviewed_without_extra_calls` | 다수결(TK-11)로 판정이 `UNCERTAIN` → `AI_FULL_GENERATION_LIKELY` | 시험의 기대값을 새 정책에 맞게 고치고 사유를 시험 주석에 적는다 |
| `test_review_hardening.py::test_model_agreement_does_not_promote_only_style_or_metadata` | 이름이 말하는 정책("문체·메타데이터만으로는 모델이 합의해도 승격하지 않는다")이 사용자 결정(다수결)과 충돌 | 정책 변경이므로 시험을 새 정책("다수결이 정한다, 흔적 부재는 별도 축으로 표시")으로 다시 쓴다. 단순히 기대값만 바꾸지 않는다 |
| `test_ground_truth_prepared_brief.py` 2건 | TK-12(`.gitignore`된 미러 자료 의존) 미해결 | TK-12 |
| `test_v5_ocr_dates.py::test_rotated_scan_page_impossible_date_is_found` | 평가 측 환경에서만 실패(CI에서는 통과) | 무시 |

## 수용 기준
- `python -m pytest -q --ignore=tests/acceptance`에서 위 표 중 환경 사유(`test_v5_ocr_dates`)를 뺀 실패가 0 (TK-12는 별도).
- 은닉 신호 경계 시험 2건은 시험 변경 없이 통과한다.
- 푸시 전에 이 명령을 돌린다(TK-16).
