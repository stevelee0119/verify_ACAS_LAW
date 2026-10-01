# 인계 티켓(평가 → 구현)

평가 에이전트(claude-code)가 측정에서 나온 결함을 **원인 유형별**로 적는다. 구현 에이전트(Antigravity)는 티켓 단위로 고친다.
서면 한 건에 맞춘 수정은 하지 않는다(AGENTS.md). 수용 기준은 측정 도구의 출력이다. 기준 커밋은 측정한 코드다.

| 티켓 | 유형 | 제목 | 수용 기준(측정) | 상태 |
|---|---|---|---|---|
| [TK-01](TK-01_input_private_use_glyphs.md) | 입력 단계 | 글꼴 구두점 글리프가 사용자 영역 문자로 읽힘 | 서면7 pdf TEXT-1~3, PII-2·7·9·10 | 해결(cf7c739) |
| [TK-02](TK-02_pii_address_detail.md) | 개인정보 | 당사자 세부 주소는 마스킹, 소송대리인·법원 주소는 마스킹 안 함(정책 확정) | 서면7 PII-5·6·11 (pdf·text) | 해결(cf7c739) · 후속 TK-17 |
| [TK-03](TK-03_injection_audit_stamp.md) | 인젝션 | 감사·권한 표지 미탐지(문구 하나에 맞춘 패턴) | 서면7 INJ-1 (pdf·text) | 해결(de243cc) · 일반화 → TK-20 |
| [TK-04](TK-04_temporal_internal_contradiction.md) | 규칙 부족 | 처분일보다 뒤의 개정을 그 처분에 적용하라는 주장 | 서면7 TMP-1 (pdf·text) | 해결(de243cc) · 후속 TK-19(기준일 후보 누락) |
| [TK-05](TK-05_unreasonable_argument.md) | 규칙 부족 | 공금 유용에 사무관리·정당행위 원용 | 서면7 LEG-1·2 (pdf·text) | 해결(de243cc) · 일반화 → TK-20 |
| [TK-06](TK-06_false_positive_actualtext_zwsp.md) | 오탐 | Google Docs 줄바꿈 표시를 은닉 신호로 알림(재발) | 서면7 pdf FA-1 | 해결(cf7c739) · 은닉 탐지 약화 → TK-15 |
| [TK-07](TK-07_hard_wrapped_citation.md) | 입력 단계 | 줄바꿈으로 갈라진 「법령명」 인용 | 서면7 text CIT-3·6 | 해결(cf7c739) |
| [TK-08](TK-08_exhibit_facts_overfit.md) | 하드코딩 | `exhibit_facts.py`의 사건 문구 의존·오탐 | 문구 부채 0, 변형 시험 | 부채 0 · 오탐 후속 → TK-14 |
| [TK-09](TK-09_llm_role_redesign.md) | 설계(명세만) | 모델 의견을 판정에 쓰는 구조 | 온라인 채점 도구로 확인 | 승인 전 구현됨 → TK-14 |
| [TK-10](TK-10_local_mirror_invented_fields.md) | 증거 계층 | 로컬 미러 자동 보강이 시행일을 지어내고 가지조문을 뭉갬 | 미러 시험(가지조문·항·시행일 null) | 해결(cf7c739) |
| [TK-11](TK-11_ai_verdict_majority_vote.md) | 정책 변경 | AI 작성 판정을 만장일치가 아니라 다수결로 | `tests/acceptance/test_ai_majority_rule.py` | 해결(cf7c739) · 후속 TK-18 |
| [TK-12](TK-12_ci_red_gitignored_mirror_data.md) | 시험 설계 | main CI 실패: 두 시험이 .gitignore된 미러 데이터에 의존 | CI `pytest -q` 통과 | 열림(요청 06 미반영, TK-21) |
| [TK-13](TK-13_generalization_gaps_round1.md) | 일반화 | 인젝션 표지·처분시법 표현·무리한 주장 주제 — 변형과 서면8에서 재발 | `test_variant_generalization.py`·`test_case8_delay_penalty.py` | 해결(de243cc, 개발 자료 기준) · 미공개 변형 2에서 4건 재발 → TK-20 |
| [TK-14](TK-14_tk09_unapproved_and_logic_defects.md) | 절차·논리 | TK-09를 승인 없이 구현, 날짜 재계산이 항상 참, 인용문 일치만으로 HIGH 승격 | 재현 3건 대조군 | 해결(de243cc): 기본 꺼짐·MEDIUM·재현 5건 · 켤지는 사용자 결정 |
| [TK-15](TK-15_broken_tests_after_round1.md) | 회귀 시험 | 1차 구현이 깨뜨린 기존 시험, 은닉 ZWSP 탐지 약화 | `pytest -q` 실패 0 | 복구(6a3c848) 뒤 재발 → TK-19 |
| [TK-16](TK-16_process_and_hygiene.md) | 절차·위생 | 게이트·전체 시험 미실행, 점수 표기 불일치, CRLF 혼입 | 푸시 전 검증 명령 | CRLF·메모·경고 해결(de243cc) · 점수 표기·시험 미실행 재발 → TK-21 |
| [TK-17](TK-17_pii_representative_and_business_number.md) | 개인정보 | 대표이사의 띄어쓴 성명·사업자등록번호 미마스킹 | 서면8 PII-1·7 | 해결(de243cc) · 구 시험과 정책 충돌 → TK-19 4절(사용자 결정) |
| [TK-18](TK-18_ai_axis_not_following_majority.md) | 정책 이행 | 보고서 머리의 AI 판정이 다수결을 따르지 않음 | `test_axis_follows_majority…` | 해결(de243cc) · 옛 규칙 시험 1건 미갱신 → TK-19 |
| [TK-19](TK-19_regressions_after_round2.md) | 회귀 | 2차 구현이 기존 시험 4건과 기준일 추출을 깨뜨림(횡령 사건 기준일 소실 포함) | `pytest -q --ignore=tests/acceptance` 실패 0, `test_reference_date_candidate_is_kept` | 열림 |
| [TK-20](TK-20_generalization_gaps_round2.md) | 일반화 | 변형 2 첫 점수 16/20: 주소 꼬리·변호사 주소·변호사 성명·`@@` 표지·무리한 주장, 조문 단위 열거 규칙 | `test_variant2_check`·`test_case8_check[text-LEG-1]` | 열림 |
| [TK-21](TK-21_process_round2.md) | 절차·증거 | 출처 없는 시험 자료 작성(요청 06), 점수 표기, 은닉 탐지 시험 약화 | 다음 커밋 메시지 | 열림 |
| [TK-22](TK-22_input_paragraph_reconstruction.md) | 입력 단계 | 물리적 줄을 문단으로 복원하지 않아 주장이 토막 나 Drive 대조 누락, 줄바꿈에 따라 인젝션 표지 미탐 | `test_case9…`의 배치 불변 4건 | 열림 |
| [TK-23](TK-23_evidence_severity_internal_regulation.md) | 오탐 + 정책 | Drive에 있는 내부 규정을 CRITICAL '존재하지 않는 법령'으로, 증거가 강한 쪽이 더 낮은 심각도 | 단위 시험, 온라인 FP-1·EX-2s | 열림(B는 사용자 결정) |
| [TK-24](TK-24_unreasonable_argument_statutory_period.md) | 규칙 부족 | 소멸시효 등 법정 기간을 정의·유추로 일체 배제한다는 주장 미탐 | `test_case9_check[*-LEG-2]` | 열림 |
| [TK-25](TK-25_report_scope_and_coverage_notes.md) | 정책 이행 잔여 | AI 판정 축 `scope`가 흔적 0건이면 NOT_APPLICABLE, 커버리지·모델 실패 관찰 | 단위 시험 | 열림 |
| [TK-26](TK-26_hardcoding_moved_to_config.md) | 하드코딩·일반화 불일치 | '법리 군집' 설정을 읽는 코드가 없고, 규칙은 시험 낱말만 담아 처음 보는 법리 7건 미탐, 시험 서면 문장이 설정에 복사됨 | `test_generalization_guards.py`, 리터럴 부채 감소 | 열림 |

**구현 에이전트 작업 지시서(붙여 넣기용):** [1차](PROMPT_FOR_ANTIGRAVITY.md) · [2차](PROMPT_FOR_ANTIGRAVITY_ROUND2.md) · [3차](PROMPT_FOR_ANTIGRAVITY_ROUND3.md) · 구현→평가 요청은 [requests/](requests/README.md)

## 측정 명령
```
python scripts/regression_gate.py --base HEAD~1                   # 기준 커밋 대비 항목 단위 회귀(푸시 전에 항상). --pytest를 주면 전체 시험의 새 실패까지
python scripts/check_hardcoding_diff.py --base HEAD~1            # 이번 변경의 추가된 줄에 시험 입력의 값·조문 번호가 들어갔는지
python scripts/probe_document.py run --spec tests/fixtures/probes/case7_suspension.json [--text]
python scripts/score_report.py --report <온라인 보고서.json> --spec tests/fixtures/probes/case7_suspension_online.json
python -m pytest tests/acceptance -q -rxX
python scripts/check_case_literals.py
python scripts/scorecard.py && python scripts/score_gate.py
```
서면7 항목 시험은 미해결을 strict xfail로 두었다. 고쳐서 XPASS(strict)로 시험이 실패하면 평가 에이전트에게 알려 xfail 표시를 지우게 한다.

## 사용자 결정(2026-09-30 반영됨)
- 소송대리인·법원 주소는 마스킹하지 않는다(TK-02).
- AI 작성 판정은 다수결로 정한다(TK-11). 평가 에이전트의 해석(흔적 부재가 판정을 막지 않음)은 사용자 확인 대상이다.

## 아직 사용자가 정할 것
- **사업자등록번호를 마스킹할 것인가**(TK-19 4절): 서면8 정답지는 마스킹, 1차 구현 때의 시험은 보존을 기대한다.
- **미러 시험 자료(TK-12)**: 로컬 `config/legal_mirror/*.json` 제공 또는 평가 에이전트의 공식 원문 구성 허락. 판례 2018도15313의 실재 확인이 필요하다.
- **TK-09 후보 승격을 켤지**: 기본 꺼짐(de243cc).
- 기준선(`baseline.json`)은 올리지 않았다. 4ad64a7의 81.7/79.2는 미러 자료 효과(TK-10)라서다. 올릴지는 TK-10 처리 뒤에 정한다.
