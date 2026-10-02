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
| [TK-12](TK-12_ci_red_gitignored_mirror_data.md) | 시험 설계 | main CI 실패: 두 시험이 .gitignore된 미러 데이터에 의존 | CI `pytest -q` 통과 | **해소(2026-10-03)**: 로컬 전체 시험 실패 3→1건(환경), `CI` 초록 확인([run 263](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/37074643039), `workflow_dispatch`, 커밋 f82e679, 두 job 모두 success): 공식 원문 미러, 2018도15313→대법원 2020다268807, 카목 전제 정정 |
| [TK-13](TK-13_generalization_gaps_round1.md) | 일반화 | 인젝션 표지·처분시법 표현·무리한 주장 주제 — 변형과 서면8에서 재발 | `test_variant_generalization.py`·`test_case8_delay_penalty.py` | 해결(de243cc, 개발 자료 기준) · 미공개 변형 2에서 4건 재발 → TK-20 |
| [TK-14](TK-14_tk09_unapproved_and_logic_defects.md) | 절차·논리 | TK-09를 승인 없이 구현, 날짜 재계산이 항상 참, 인용문 일치만으로 HIGH 승격 | 재현 3건 대조군 | 해결(de243cc): 기본 꺼짐·MEDIUM·재현 5건 · 켤지는 사용자 결정 |
| [TK-15](TK-15_broken_tests_after_round1.md) | 회귀 시험 | 1차 구현이 깨뜨린 기존 시험, 은닉 ZWSP 탐지 약화 | `pytest -q` 실패 0 | 복구(6a3c848) 뒤 재발 → TK-19 |
| [TK-16](TK-16_process_and_hygiene.md) | 절차·위생 | 게이트·전체 시험 미실행, 점수 표기 불일치, CRLF 혼입 | 푸시 전 검증 명령 | CRLF·메모·경고 해결(de243cc) · 점수 표기·시험 미실행 재발 → TK-21 |
| [TK-17](TK-17_pii_representative_and_business_number.md) | 개인정보 | 대표이사의 띄어쓴 성명·사업자등록번호 미마스킹 | 서면8 PII-1·7 | 해결(de243cc) · 구 시험과 정책 충돌 → TK-19 4절(사용자 결정) |
| [TK-18](TK-18_ai_axis_not_following_majority.md) | 정책 이행 | 보고서 머리의 AI 판정이 다수결을 따르지 않음 | `test_axis_follows_majority…` | 해결(de243cc) · 옛 규칙 시험 1건 미갱신 → TK-19 |
| [TK-19](TK-19_regressions_after_round2.md) | 회귀 | 2차 구현이 기존 시험 4건과 기준일 추출을 깨뜨림(횡령 사건 기준일 소실 포함) | `pytest -q --ignore=tests/acceptance` 실패 0, `test_reference_date_candidate_is_kept` | 열림 |
| [TK-20](TK-20_generalization_gaps_round2.md) | 일반화 | 변형 2 첫 점수 16/20: 주소 꼬리·변호사 주소·변호사 성명·`@@` 표지·무리한 주장, 조문 단위 열거 규칙 | `test_variant2_check`·`test_case8_check[text-LEG-1]` | 열림 |
| [TK-21](TK-21_process_round2.md) | 절차·증거 | 출처 없는 시험 자료 작성(요청 06), 점수 표기, 은닉 탐지 시험 약화 | 다음 커밋 메시지 | 열림 |
| [TK-22](TK-22_input_paragraph_reconstruction.md) | 입력 단계 | 물리적 줄을 문단으로 복원하지 않아 주장이 토막 나 Drive 대조 누락, 줄바꿈에 따라 인젝션 표지 미탐 | `test_layout_invariance_pdf.py`, `test_case9…`, `test_case9_real_pdf.py` | 텍스트 해결(e6b58fd) · PDF 부분 해결(5차: 실제 PDF 청구 70→47·제22조 문장 복원, 폭 40 INJ-1 잔여 1건) · **어절 중간 공백 회귀 → TK-31** |
| [TK-23](TK-23_evidence_severity_internal_regulation.md) | 오탐 + 정책 | Drive에 있는 내부 규정을 CRITICAL '존재하지 않는 법령'으로, 증거가 강한 쪽이 더 낮은 심각도 | 단위 시험, 온라인 FP-1·EX-2s | A 해결(e6b58fd) · TK-29 해결(5차) · B HIGH 반영(5차 U9-1, 사용자 결정 — Astra 확인, 평가 측은 U9-2 INFO 분리만 재현) |
| [TK-24](TK-24_unreasonable_argument_statutory_period.md) | 규칙 부족 | 소멸시효 등 법정 기간을 정의·유추로 일체 배제한다는 주장 미탐 | `test_case9_check[*-LEG-2]` | 열림(4차 제외) |
| [TK-25](TK-25_report_scope_and_coverage_notes.md) | 정책 이행 잔여 | AI 판정 축 `scope`가 흔적 0건이면 NOT_APPLICABLE, 커버리지·모델 실패 관찰 | 단위 시험 | scope 해결(e6b58fd) · 제안은 사용자 결정 |
| [TK-26](TK-26_hardcoding_moved_to_config.md) | 하드코딩·일반화 불일치 | '법리 군집' 설정을 읽는 코드가 없고, 규칙은 시험 낱말만 담아 처음 보는 법리 7건 미탐, 시험 서면 문장이 설정에 복사됨 | `test_generalization_guards.py`, 리터럴 부채 감소 | 해결(5차 U5: 민법 편·장·절 범위, 양성 5건 해소) · **정상 항변 오탐·장 이름 오류 → TK-32** · 전형계약(도급 등) 법리는 군집 밖 |
| [TK-27](TK-27_reference_date_arbitrary_pick.md) | 불확실성 보존 | 기준일 후보가 여럿이면 계약은 늦은 날짜·처분은 이른 날짜를 임의로 고름 | `test_reference_date_is_not_picked_arbitrarily…` | 해결(e6b58fd) |
| [TK-28](TK-28_pii_label_punctuation_and_audit_findings.md) | 개인정보 + 감사 지적 | 당사자 라벨 뒤 구분자가 공백이 아니면 이름 미마스킹(16변형 중 13), system/schema 예외, 입원↔퇴원 혈압 모순, 참고자료 승격·PDF 연결(미재현) | `test_pii_label_variants.py` | 5차 부분 해결(라벨 구분자 13건·system 등록 상수·입원/퇴원) · **이름 회귀·미해결 잔여 → TK-30** |
| [TK-29](TK-29_reference_match_evidence_level.md) | 불확실성 단조 회귀 | 참고자료 제목 부분 일치·미독 파일만으로 부존재 판정을 낮추고 PARTIALLY_VERIFIED로 올림(4차 S3 신규) | `test_reference_match_guard.py` | **해결(5차 c6a9dc0)** — 평가 측 보호 시험 3건 XPASS, 독립 감사 18/18 |
| [TK-30](TK-30_pii_name_regression_round5.md) | 회귀(개인정보) | 5차 이름 개선과 함께 4차에 마스킹되던 이름이 노출(`성명: 김민기`)·마지막 글자 잔존(`원고 김하은`), 라벨 칸이 여럿인 `원  고   윤하기` 노출, 정상 안내문 PERSON 오탐 | `test_round5_regressions.py` | 열림 |
| [TK-31](TK-31_pdf_join_midword_space.md) | 회귀(입력 단계) | 줄 결합이 어절 한가운데에 공백(`(대 법원`)을 넣어 TC-06 법원명·선고일 손실, dev 81.7→81.2. PDF 폭 40 INJ-1 잔여 1건 | `test_round5_regressions.py`, `test_layout_invariance_pdf.py` | 열림 |
| [TK-32](TK-32_civil_cluster_false_positive_and_names.md) | 오탐 + 설정 정확성 | 민법 군집 확장으로 요건을 제시한 정상 항변을 과대주장으로 표시, 설정의 장 이름 오류(사무관리·부당이득·불법행위) | `test_round5_regressions.py` | 열림 |
| [TK-33](TK-33_evaluation_marker_and_report_accuracy.md) | 절차·하드코딩 | 문단 복원기에 평가 자료 표식 분기(`HO-\d+\|TC-\d+\|홀드아웃용…`), 완료 보고의 비교 기준·성공 단계만 적은 CI 결과·"10건 전수 해소" 오기 | `check_hardcoding_diff.py`의 `eval_marker` | 열림 |
| [TK-34](TK-34_item_level_temporal_review.md) | 탐지 공백(새 탐지) | 행위시법 검토가 조 단위 버전만 비교해 목 단위 신설·이동(제2조 제1호 카목: 성과 도용→데이터 부정사용)을 못 봄. **6차 범위 밖** | strict xfail XPASS + 오탐 대조 유지 | 열림(6차 검증 뒤 착수, 시험 고정됨) |

**구현 에이전트 작업 지시서(붙여 넣기용):** [1차](PROMPT_FOR_ANTIGRAVITY.md) · [2차](PROMPT_FOR_ANTIGRAVITY_ROUND2.md) · [3차](PROMPT_FOR_ANTIGRAVITY_ROUND3.md) · [4차 안정화](PROMPT_FOR_STABILIZATION_ROUND4.md) · [5차 안정화](PROMPT_FOR_STABILIZATION_ROUND5.md) · [6차 안정화(5차 회귀 보완)](PROMPT_FOR_STABILIZATION_ROUND6.md) · 구현→평가 요청은 [requests/](requests/README.md)

**기능 개선 요청(결함 티켓과 별도):** [FR-01 검토 화면 중복 해소·참고자료(RAG) 활용 — 타당성 검토](FR-01_review_screen_and_reference_integration.md) · [F1 라운드 작업 지시서](PROMPT_FOR_FEATURE_ROUND_F1.md)(5차 검증 뒤 착수)

**독립 감사(Astra, 읽기 전용) 의뢰서:** [4차](PROMPT_FOR_ASTRA_AUDIT_ROUND4.md) · [5차](PROMPT_FOR_ASTRA_AUDIT_ROUND5.md)(기능 라운드 F1 포함 여부 점검 V13·사용자 결정 이행 V14 포함) · [6차](PROMPT_FOR_ASTRA_AUDIT_ROUND6.md)(5차 회귀 보완 점검: 이름 행렬 회귀 0·글자/어절 줄바꿈 양방향 불변·정상 항변 오탐·보고 정확성 V15·TK-12 자료 독립 확인 V16, F1은 범위 밖이라 기본 "미포함")

## 측정 명령
```
python scripts/regression_gate.py --base HEAD~1                   # 기준 커밋 대비 항목 단위 회귀(푸시 전에 항상). --pytest를 주면 전체 시험의 새 실패까지
python scripts/check_hardcoding_diff.py --base HEAD~1            # 이번 변경의 추가된 줄에 시험 입력의 값·조문 번호가 들어갔는지
python scripts/probe_document.py run --spec tests/fixtures/probes/case7_suspension.json [--text]
python scripts/probe_document.py run --spec tests/fixtures/probes/case9_state_compensation.json --input tests/fixtures/case9_state_compensation_google_docs.pdf   # 같은 정답 항목, 입력만 실제 PDF
python scripts/score_report.py --report <온라인 보고서.json> --spec tests/fixtures/probes/case7_suspension_online.json
python -m pytest tests/acceptance -q -rxX
python scripts/check_case_literals.py
python scripts/scorecard.py && python scripts/score_gate.py
```
서면7 항목 시험은 미해결을 strict xfail로 두었다. 고쳐서 XPASS(strict)로 시험이 실패하면 평가 에이전트에게 알려 xfail 표시를 지우게 한다.

## 사용자 결정(2026-09-30 반영됨)
- 소송대리인·법원 주소는 마스킹하지 않는다(TK-02).
- AI 작성 판정은 다수결로 정한다(TK-11). 평가 에이전트의 해석(흔적 부재가 판정을 막지 않음)은 사용자 확인 대상이다.

## 사용자 결정(2026-10-02 반영됨)
| 항목 | 결정 | 처리 |
|---|---|---|
| 사업자등록번호 | 마스킹 원칙 | `test_sec01` 기대를 평가 측이 마스킹으로 갱신 |
| TK-12 미러 시험 자료 | 평가 측이 공식 원문으로 구성(확인 못 한 항목은 "확인 못 함") | **완료(2026-10-03)** — 2018도15313은 공식 미확인이라 확인된 대법원 2020다268807 판결로 교체(사용자 결정), 정답지 의도 불명이라 카목 단계는 공식 원문 기준으로 정정·신설 카목 검출은 TK-34 |
| TK-23 B 조문 부존재(증거 A등급) 심각도 | HIGH | 5차 지시서 U9-1 |
| TK-09 모델 의견 승격 | 기본 꺼짐 유지 | 변경 없음 |
| 기준선 상향(2026-10-03 갱신) | **회귀 해소 뒤 81.7 이상으로 상향**(5차 실측 dev 81.2는 회귀 상태라 올리지 않음) | 평가 측이 실측으로 사용자 승인 후 |
| 동일 시행일 복수 버전 | 두 버전 병기·대조 | 6차 |
| 다음 라운드 범위(2026-10-03 갱신) | **5차 회귀 보완(TK-30~33)만**, 요청 16(병기·모델 응답 안정화)·F1·TK-24는 그 검증 뒤 | [6차 지시서](PROMPT_FOR_STABILIZATION_ROUND6.md) |
| `main` 보호 | 점수 하락 게이트 먼저, CI는 초록 뒤 추가. Docker OCR readiness 제외. 강제 푸시·삭제 금지 켬, PR 필수·관리자 포함·최신 유지는 켜지 않음 | 5차 지시서 U8 |
| 생성 소프트웨어명(PDF `Producer`) | 작성자 정보에서 분리해 INFO | 5차 지시서 U9-2 |
| `main` 병합 | 5차 검증 뒤 PR(사용자 요청 시에만 PR 생성) | 사용자 |
| 기능 라운드 F1 D1~D6 | 쟁점 매트릭스 별도 탭 유지 · 상단 요약+HIGH 이상 고정 안내 · 파일 정보 노출은 보안 카드 · 참고 의견(승격 없음) · **회귀 보완(6차) 검증 뒤 순차** · 기존 전송 정책 그대로 | [F1 지시서](PROMPT_FOR_FEATURE_ROUND_F1.md), [FR-01](FR-01_review_screen_and_reference_integration.md) |
| 프로그램 버전 | 성능 기준으로만 상향(정수 급격·첫째 자리 일부·둘째 자리 미세), 커밋마다 올리지 않음 | [VERSION_POLICY](../scorecards/VERSION_POLICY.md), `scripts/check_version_policy.py` |

## 아직 사용자가 정할 것
- 버전 등급 임계값(VERSION_POLICY 5절, 평가 측 제안·잠정)의 확정 또는 조정, 정수 상향 승인(해당 판정이 생길 때).
- CI를 `main`의 필수 확인에 추가하는 시점(평가 측이 초록을 확인한 뒤 요청한다), Docker OCR readiness 추가 여부(연속 초록 확인 뒤).
- 서면9 같은 PDF의 온라인 재실행(5차 U4 이후) 결과 확인.
