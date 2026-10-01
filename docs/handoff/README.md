# 인계 티켓(평가 → 구현)

평가 에이전트(claude-code)가 측정에서 나온 결함을 **원인 유형별**로 적는다. 구현 에이전트(Antigravity)는 티켓 단위로 고친다.
서면 한 건에 맞춘 수정은 하지 않는다(AGENTS.md). 수용 기준은 측정 도구의 출력이다. 기준 커밋은 측정한 코드다.

| 티켓 | 유형 | 제목 | 수용 기준(측정) | 상태 |
|---|---|---|---|---|
| [TK-01](TK-01_input_private_use_glyphs.md) | 입력 단계 | 글꼴 구두점 글리프가 사용자 영역 문자로 읽힘 | 서면7 pdf TEXT-1~3, PII-2·7·9·10 | 해결(cf7c739) |
| [TK-02](TK-02_pii_address_detail.md) | 개인정보 | 당사자 세부 주소는 마스킹, 소송대리인·법원 주소는 마스킹 안 함(정책 확정) | 서면7 PII-5·6·11 (pdf·text) | 해결(cf7c739) · 후속 TK-17 |
| [TK-03](TK-03_injection_audit_stamp.md) | 인젝션 | 감사·권한 표지 미탐지(문구 하나에 맞춘 패턴) | 서면7 INJ-1 (pdf·text) | 부분 해결 → TK-13 |
| [TK-04](TK-04_temporal_internal_contradiction.md) | 규칙 부족 | 처분일보다 뒤의 개정을 그 처분에 적용하라는 주장 | 서면7 TMP-1 (pdf·text) | 부분 해결 → TK-13 |
| [TK-05](TK-05_unreasonable_argument.md) | 규칙 부족 | 공금 유용에 사무관리·정당행위 원용 | 서면7 LEG-1·2 (pdf·text) | 부분 해결 → TK-13 |
| [TK-06](TK-06_false_positive_actualtext_zwsp.md) | 오탐 | Google Docs 줄바꿈 표시를 은닉 신호로 알림(재발) | 서면7 pdf FA-1 | 해결(cf7c739) · 은닉 탐지 약화 → TK-15 |
| [TK-07](TK-07_hard_wrapped_citation.md) | 입력 단계 | 줄바꿈으로 갈라진 「법령명」 인용 | 서면7 text CIT-3·6 | 해결(cf7c739) |
| [TK-08](TK-08_exhibit_facts_overfit.md) | 하드코딩 | `exhibit_facts.py`의 사건 문구 의존·오탐 | 문구 부채 0, 변형 시험 | 부채 0 · 오탐 후속 → TK-14 |
| [TK-09](TK-09_llm_role_redesign.md) | 설계(명세만) | 모델 의견을 판정에 쓰는 구조 | 온라인 채점 도구로 확인 | 승인 전 구현됨 → TK-14 |
| [TK-10](TK-10_local_mirror_invented_fields.md) | 증거 계층 | 로컬 미러 자동 보강이 시행일을 지어내고 가지조문을 뭉갬 | 미러 시험(가지조문·항·시행일 null) | 해결(cf7c739) |
| [TK-11](TK-11_ai_verdict_majority_vote.md) | 정책 변경 | AI 작성 판정을 만장일치가 아니라 다수결로 | `tests/acceptance/test_ai_majority_rule.py` | 해결(cf7c739) · 후속 TK-18 |
| [TK-12](TK-12_ci_red_gitignored_mirror_data.md) | 시험 설계 | main CI 실패: 두 시험이 .gitignore된 미러 데이터에 의존 | CI `pytest -q` 통과 | 열림 |
| [TK-13](TK-13_generalization_gaps_round1.md) | 일반화 | 인젝션 표지·처분시법 표현·무리한 주장 주제 — 변형과 서면8에서 재발 | `test_variant_generalization.py`·`test_case8_delay_penalty.py` | 열림 |
| [TK-14](TK-14_tk09_unapproved_and_logic_defects.md) | 절차·논리 | TK-09를 승인 없이 구현, 날짜 재계산이 항상 참, 인용문 일치만으로 HIGH 승격 | 재현 3건 대조군 | 열림 |
| [TK-15](TK-15_broken_tests_after_round1.md) | 회귀 시험 | 1차 구현이 깨뜨린 기존 시험, 은닉 ZWSP 탐지 약화 | `pytest -q` 실패 0 | 열림 |
| [TK-16](TK-16_process_and_hygiene.md) | 절차·위생 | 게이트·전체 시험 미실행, 점수 표기 불일치, CRLF 혼입 | 푸시 전 검증 명령 | 열림 |
| [TK-17](TK-17_pii_representative_and_business_number.md) | 개인정보 | 대표이사의 띄어쓴 성명·사업자등록번호 미마스킹 | 서면8 PII-1·7 | 열림 |
| [TK-18](TK-18_ai_axis_not_following_majority.md) | 정책 이행 | 보고서 머리의 AI 판정이 다수결을 따르지 않음 | `test_axis_follows_majority…` | 열림 |

**구현 에이전트 작업 지시서(붙여 넣기용):** [PROMPT_FOR_ANTIGRAVITY.md](PROMPT_FOR_ANTIGRAVITY.md) · 구현→평가 요청은 [requests/](requests/README.md)

## 측정 명령
```
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
- 기준선(`baseline.json`)은 올리지 않았다. 4ad64a7의 81.7/79.2는 미러 자료 효과(TK-10)라서다. 올릴지는 TK-10 처리 뒤에 정한다.
