# 인계 티켓(평가 → 구현)

평가 에이전트(Codex 평가 세션)가 측정에서 나온 결함을 **원인 유형별**로 적는다. 구현 에이전트(Codex 구현 세션·Antigravity)는 티켓 단위로 고친다.
서면 한 건에 맞춘 수정은 하지 않는다(AGENTS.md). 수용 기준은 측정 도구의 출력이다. 기준 커밋은 측정한 코드다.

## 미배포 TK와 향후 조치 (2026-10-10, TK-72 수용·PR #73 CI 보완 대기)

현재 상태 기준은 운영 `main` **9c1b218(0.12.0)** 및 Steve `Steve_ACASiaLAW` **ad25f51**다. PR #67·#69와 평가 도구 #71은 병합 완료, TK-56 #70 **71905eb**, TK-74 #68 **30f9f92**, TK-72 #72 **df4a9c0**는 내용 수용해 평가 PR #73에 통합했다. 평가 PR #73 최신 head는 **dc0e445**다. 점수 게이트는 통과했지만 필수 CI #38059258594는 두 실행 환경 모두 `test_statute_citations_32k_linear_performance`가 1.0초 한도(실측 1.3196초·1.3156초)를 넘어 실패했다. 따라서 통합 검증과 사용자 병합 승인은 보류이며, 이 실패를 TK-72 단독 PR에서 통과했던 결과로 대체할 수 없다.

| 미배포 TK | 현재 단계·근거 | 다음 조치·담당 | 지금 가능 여부·선행요건 |
|---|---|---|---|
| TK-24 | 수용·Steve 반영, #53 0ad4fac → 통합 #67 | Codex 평가: 다음 릴리스 후보 검증 | 후보 준비 가능. 새 봉인·버전 판정·릴리스 CI·사용자 승인 후 배포 |
| TK-69 | 수용·Steve 반영, #56 ce68dc4 → 통합 #67 | Codex 평가: 다음 릴리스 후보 검증 | 위와 같음 |
| TK-43 | 수용·Steve 반영, #62 e4867e7 → 통합 #69 | Codex 평가: 개인정보 보호 유지·릴리스 준비 | 통합/병합 완료. 새 봉인 등 배포 요건은 미완료 |
| TK-70 | 수용·Steve 반영, #60 db21f19 → 통합 #69 | Codex 평가: 릴리스 후 비공개 온라인 v2·서면9 다회 확인 | 추가 구현 요구 없음. 묶음 릴리스는 새 봉인 필요; 현재 SHA 온라인 효과 미측정 |
| TK-56 | #70 **71905eb 내용 수용**, 평가 PR #73 통합·목표 21건 xfail 제거(기대값 유지) | Codex 평가: 통합 검증·최신 CI·사용자 병합 승인 확인. 구현: 추가 보완 요구 없음 | 과차단 6/28·유출 0 유지. 통합 131506d full 원본 종료 1: acceptance 1014 통과/실제 실패 0·regression_ledger 591 통과/실제 실패 0·full_tests 5659 통과/실제 실패 1·browser_tests 197 통과/실제 실패 0; 실패 단계 full_tests. 유일한 회전 OCR 날짜 시험 실패는 CI 한글 글꼴 경로가 없어 발생했고 외부 NanumGothic 경로 대역을 적용한 별도 시작/통합 시험 각 1 passed(합계 2)로 확인했다. 제품·시험·제한 변경 없음. Python 3.11.15·tesseract 5.5.0 kor·오프라인, --allow-env-mismatch 명시. 원본 full 종료 1과 별도 환경 보완 결과를 분리 보존. #73 필수 CI 성공·사용자 승인 뒤 Steve 병합, 다음 릴리스 새 봉인 필요 |
| TK-74 | #68 **30f9f92 내용 수용**, 평가 PR #73 통합51e042c | Codex 평가: 최신 통합 CI·독립 감사·사용자 병합 승인 확인. 별도 구현 추가 없음 | 같은 SHA CI 11개 성공·고정81.7/79.2/0·공개 합성32통과, 일반 TXT/PDF/DOCX 캐시 검색 회귀 해소. [회신](https://github.com/stevelee0119/verify_ACAS_LAW/pull/68#issuecomment-6097626696). Steve 병합/운영 배포 전 |
| TK-72 | #72 **df4a9c0 내용 수용**, 평가 PR #73에 통합 | Codex 평가: 통합 CI 성능 실패 원인 보완·재검증 후 독립 감사 및 사용자 병합 승인 요청. 다음 구현은 TK-75 별도 PR | 단독 #72 CI 11개 성공, 고정 81.7/79.2/오탐0, 합성 272건 출력 차이0(승인된 헌재 예외 별도), 32k 실제 추출 로컬 0.693295초. 그러나 #73 head dc0e445 통합 CI에서 두 환경 각각 1.3196초·1.3156초로 1.0초 게이트 실패. 통합 SHA 필수 CI 미통과. 로컬 full `verify_all`은 Python/Tesseract 및 브라우저·마운트 환경 차이로 종료1; UI 재검증 통과와 기존 마운트 시험 1건 환경 실패를 구분해 보존. [판정/회신](https://github.com/stevelee0119/verify_ACAS_LAW/pull/72#issuecomment-6098440036). Steve 병합/새 봉인/배포 전 |
| TK-75 | PR #74 `40fd3a9` 제출·평가 보류. 같은 SHA CI/점수 게이트 성공, 공개 합성 시험 47건 보고; 실제 법률 효과 미측정. 지정 Claude 경로·fallback 범위와 고정 공개 참조 SHA에 불일치 | Codex 평가: 구현 측 보완 요청 완료, 재제출 후 코드/시험 재검토 및 사전 고정 기준으로 실제 동일조건 A/B. 아직 수용·통합 아님 | PR 코멘트 [#74 판정](https://github.com/stevelee0119/verify_ACAS_LAW/pull/74#issuecomment-6098611209). 미수용 기능 릴리스 제외. [티켓](TK-75_claude_legal_korean_workflow.md) |
| TK-44·TK-49 | 설계 #63 e20bd6c 조건부 승인; 2단계 대기 | Codex 평가: R7-05/R6-03 계약 시험·합성 PDF 좌표 보호 시험 준비. Codex 구현: 계측→구현 | 평가 시험 준비는 지금 가능. 구현 2단계는 평가 측 조건 2 완료 + TK-56 수용/Steve 반영 + TK-75 포함 릴리스 준비 뒤. 비공개 줄 결합 세트는 수용 전 새로 작성 |
| TK-45 | 알려진 법리 잔여, Codex 대기열 4순위 | Codex 구현: 문장 구조 설계·양방향 시험. Codex 평가: 새 문장 세트 추가 측정 | TK-24 통합 선행요건은 충족. 한 번에 한 항목 규칙에 따라 TK-56·TK-44/49 선행 순서 유지 |
| TK-73 | 기존 A등급 중복 오탐; 미배정 | Codex 평가: 티켓 5절 임시 가설로 은퇴 4종·고정 시험 사전 점검 → 사용자 배정 결정 | 사전 점검은 지금 가능. 구현 배정·수용은 아직 없음 |
| TK-55 3절 | 키 신호 없는 역할 명사 키, 알려진 미해결·배정 없음 | 별도 범위/배정 결정 때 재개; TK-56 범위 밖 유지 | 기존 보호 시험/알려진 미해결 표시는 유지. 신규 배정 없음 |
| TK-57 참고 잔여 | 필수 게이트는 8F-1에서 해소·배포. 국제번호 국가코드 경계 원본 1/54 및 종류 표시만 참고 잔여 | 국가코드 범위의 기존 판정·가입자 자리 가림·실제 라우터 도달 0을 유지하며 재검증 | 새로운 필수 게이트 실패로 분류하지 않음. 원본 1/54를 0으로 바꾸지 않으며 별도 개선 배정 없음 |

**평가 진행 순서:** TK-56 71905eb·TK-74 30f9f92·TK-72 df4a9c0은 내용 수용해 #73에 통합했다. #73 head dc0e445의 점수 게이트는 성공했지만 통합 CI는 TK-72 32k 처리 1초 성능 게이트에서 두 환경 모두 실패했다. Codex 평가 세션은 실패 로그와 통합 환경의 성능 차이를 확인하고, 제품 변경이 필요하면 별도 구현 세션에 공개 재현 자료만 전달한 뒤 새 SHA의 전체 필수 CI를 확인한다. 해결 전 Steve 병합 승인을 요청하지 않는다. TK-75 PR #74 `40fd3a9`도 별도 구현 세션에서 제출됐으나 현재 평가 보류다: CI/점수 게이트는 성공했지만 공통 프로필을 세 공급자 전체에 적용해 TK-75의 Claude 경로·fallback 계약과 다르고, 승인된 공개 참조 SHA가 다르며, 실제 법률 품질/비용/지연 A/B가 미측정이다. 보완 요구 [회신](https://github.com/stevelee0119/verify_ACAS_LAW/pull/74#issuecomment-6098611209). 이전 판정·실패 이력은 그대로 보존한다. TK-73 사전 점검과 TK-44/49 평가 시험 준비는 지금 가능하며 TK-44/49 2단계는 조건 2 준비 완료 뒤 시작한다. 구현 측에 비공개 입력을 주지 않는다.

**다음 릴리스 준비:** 현재 수용분 TK-24·TK-69·TK-43·TK-70과 수용·평가 통합분 TK-56·TK-74·TK-72는 Steve 병합 뒤 후보에 넣을 수 있다. 추가 대상 TK-75 Claude for Legal은 별도 구현·실제 모델 평가 수용 후 후보에 통합한다. TK-75는 다음 릴리스 우선 구현 대상이다. 구현/평가 중 OFF, 수용된 범위는 릴리스 설정에서 활성화하며 실제 모델 A/B로 효과·비용·지연을 확인한다. TK-75 미수용 변경을 자동 포함하거나 모든 장기 잔여의 해소를 배포 선행요건으로 추가하지 않는다. 포함 범위 확정 → 후보 SHA `verify_all` 전체 1회·필수 PII/보호 게이트·필수 CI → 새 봉인(격리 세션 작성·사용자 보관/실행, 운영본/후보 같은 조건) → 버전 판정·필요 시 판정에 맞는 버전 커밋 → Steve→main 릴리스 PR·같은 SHA 필수 CI → 사용자 병합/배포 승인 순서다. 현재 #73 CI가 성능 게이트에서 실패했으므로 첫 사용자 조치는 #73 병합이 아니다. 아래 순서에 따라 평가·검증 완료를 기다린다. 새 봉인·최종 후보 검증·버전 판정도 미완료이므로 배포는 아직 진행하지 않는다. 배포 뒤 health/DB·서면9·비공개 온라인 v2를 확인하고 버전 상향 때만 태그를 단다.

**평가 도구 후속:** #71 ea5cbc5는 필수 CI 성공 후 사용자 병합 완료(Steve ad25f51). #73에서 TK-56/TK-74/TK-72 accepted 상태를 반영하고 티켓 지표를 재생성했다(전체 75·미해결/미배포 14: merged 4·accepted 3·open 5·known_open 2). 고정 벤치마크 사용자 제공 자체 점검 및 첫 운영본/후보 성능 집계를 접수했다. 운영 9c1b218=후보 ad25f51=20.5/0.275/오탐12·방어이며 새 보완분은 미포함이다. 새 봉인과 구분한다.

**고정 벤치마크 첫 집계:** 자체 점검 오류/경고 0과 별도로 사용자 제공 운영본 9c1b218·후보 ad25f51 성능을 접수했다. 지문 9de8ab2dbe9439c2, 6묶음/42문서/298결함, 두 쪽 모두 종합 20.5·재현율 27.5%·오탐 12(대조군 6·A 6)·인젝션 방어 성공. 보고상 동일 환경에서 증감 0, 새 보완 TK-56/74/72는 미포함. 원장에 출처 명시한 2행 기록, 평가 측 재실행 없음. 다음 확정 후보 비교·새 봉인은 별도다.

**사용자께 남은 일 — 순서대로:**
1. **지금은 대기:** Codex 평가 세션이 #73의 32k/1초 실패를 조사하고, 필요한 구현 보완을 별도 세션에 맡겨 새 SHA를 통합·재검증한다. 현 head dc0e445는 점수 게이트만 성공, 필수 CI 실패이므로 병합하지 않는다.
2. **#73 병합 전:** 새 head의 모든 필수 CI가 성공하고 독립 감사 결과가 확인되면 평가 세션이 병합 요청을 올린다. 그때 사용자가 대상 SHA·PR 본문·CI·감사 결과를 확인하고 Steve 브랜치 병합을 승인한다. 병합 전 사용자 승인은 현재 미충족 선행요건이다.
3. **TK-75 완료 후 후보 확정:** 별도 구현 PR의 TK-75가 실제 모델 동일조건 A/B 품질·허위 주장/오탐·커버리지·비용·지연 기준을 통과하고 평가 측에 통합된 뒤 최종 변경 범위를 검토한다. TK-75 구현·평가를 사용자가 직접 할 단계는 아니며, 필요한 별도 구현 세션/실제 모델 접근이 준비되지 않으면 평가 세션이 시작 전에 요청한다.
4. **후보가 고정된 뒤 새 봉인 비교:** 오프라인 탐지·채점·개인정보 엔진이 바뀌는 릴리스이므로 격리 세션에서 새 봉인 세트를 만들고 비공개 원문을 사용자/격리 담당이 보관한다. 사용자가 운영본과 최종 후보를 같은 조건으로 `python scripts/scorecard.py --sealed-dir <경로>` 실행해 기준선 이상인지 확인하고 결과 요약만 평가 세션에 전달한다.
5. **릴리스 승인:** 평가 세션이 후보 `verify_all`, 필수 PII/보호 게이트, 같은 SHA 필수 CI, 새 봉인 결과, 고정 벤치마크/버전 판정, 릴리스 PR을 준비한다. 사용자는 (해당 시) 마이그레이션 백업을 확인한 뒤 릴리스 PR을 검토·병합해 배포를 승인한다.
6. **배포 직후:** 사용자가 온라인 서면9 점검을 1회 실행해 결과 JSON을 전달하고 health/DB 상태 확인에 협조한다. 버전 상향 태그와 최종 평가 원장 기록은 평가 세션 담당이다.

**사용자 결정에 따른 구현 순서:** TK-72 수용·평가 통합 완료 → #73 통합 CI 성능 실패 해소·재검증 → TK-75 별도 구현/실제 모델 평가·수용 → 통합 후보 검증·새 봉인·버전 판정·사용자 배포 승인. TK-44/49 보호 시험 준비·TK-73 사전 점검은 가능하나 추가 제품 구현은 이번 릴리스 준비 뒤에 둔다.

## 티켓 원인·수용 기록

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
| [TK-24](TK-24_unreasonable_argument_statutory_period.md) | 규칙 부족 | 소멸시효 등 법정 기간을 정의·유추로 일체 배제한다는 주장 미탐 | `test_case9_check[*-LEG-2]` | 수용(0ad4fac)·Steve 반영(PR #67), **미배포** |
| [TK-25](TK-25_report_scope_and_coverage_notes.md) | 정책 이행 잔여 | AI 판정 축 `scope`가 흔적 0건이면 NOT_APPLICABLE, 커버리지·모델 실패 관찰 | 단위 시험 | scope 해결(e6b58fd) · 제안은 사용자 결정 |
| [TK-26](TK-26_hardcoding_moved_to_config.md) | 하드코딩·일반화 불일치 | '법리 군집' 설정을 읽는 코드가 없고, 규칙은 시험 낱말만 담아 처음 보는 법리 7건 미탐, 시험 서면 문장이 설정에 복사됨 | `test_generalization_guards.py`, 리터럴 부채 감소 | 해결(5차 U5: 민법 편·장·절 범위, 양성 5건 해소) · **정상 항변 오탐·장 이름 오류 → TK-32** · 전형계약(도급 등) 법리는 군집 밖 |
| [TK-27](TK-27_reference_date_arbitrary_pick.md) | 불확실성 보존 | 기준일 후보가 여럿이면 계약은 늦은 날짜·처분은 이른 날짜를 임의로 고름 | `test_reference_date_is_not_picked_arbitrarily…` | 해결(e6b58fd) |
| [TK-28](TK-28_pii_label_punctuation_and_audit_findings.md) | 개인정보 + 감사 지적 | 당사자 라벨 뒤 구분자가 공백이 아니면 이름 미마스킹(16변형 중 13), system/schema 예외, 입원↔퇴원 혈압 모순, 참고자료 승격·PDF 연결(미재현) | `test_pii_label_variants.py` | 5차 부분 해결(라벨 구분자 13건·system 등록 상수·입원/퇴원) · **이름 회귀·미해결 잔여 → TK-30** |
| [TK-29](TK-29_reference_match_evidence_level.md) | 불확실성 단조 회귀 | 참고자료 제목 부분 일치·미독 파일만으로 부존재 판정을 낮추고 PARTIALLY_VERIFIED로 올림(4차 S3 신규) | `test_reference_match_guard.py` | **해결(5차 c6a9dc0)** — 평가 측 보호 시험 3건 XPASS, 독립 감사 18/18 |
| [TK-30](TK-30_pii_name_regression_round5.md) | 회귀(개인정보) | 5차 이름 개선과 함께 4차에 마스킹되던 이름이 노출(`성명: 김민기`)·마지막 글자 잔존(`원고 김하은`), 라벨 칸이 여럿인 `원  고   윤하기` 노출, 정상 안내문 PERSON 오탐 | `test_round5_regressions.py` | 열림 **6차(01070f6): 고정 입력은 해결(XPASS), 일반화 미완 → TK-39·40·41로 승계** |
| [TK-31](TK-31_pdf_join_midword_space.md) | 회귀(입력 단계) | 줄 결합이 어절 한가운데에 공백(`(대 법원`)을 넣어 TC-06 법원명·선고일 손실, dev 81.7→81.2. PDF 폭 40 INJ-1 잔여 1건 | `test_round5_regressions.py`, `test_layout_invariance_pdf.py` | 열림 **6차(01070f6): 고정 입력은 해결(XPASS), 일반화 미완 → TK-39·40·41로 승계** |
| [TK-32](TK-32_civil_cluster_false_positive_and_names.md) | 오탐 + 설정 정확성 | 민법 군집 확장으로 요건을 제시한 정상 항변을 과대주장으로 표시, 설정의 장 이름 오류(사무관리·부당이득·불법행위) | `test_round5_regressions.py` | 열림 **6차(01070f6): 고정 입력은 해결(XPASS), 일반화 미완 → TK-39·40·41로 승계** |
| [TK-33](TK-33_evaluation_marker_and_report_accuracy.md) | 절차·하드코딩 | 문단 복원기에 평가 자료 표식 분기(`HO-\d+\|TC-\d+\|홀드아웃용…`), 완료 보고의 비교 기준·성공 단계만 적은 CI 결과·"10건 전수 해소" 오기 | `check_hardcoding_diff.py`의 `eval_marker` | 열림 |
| [TK-34](TK-34_item_level_temporal_review.md) | 탐지 공백(새 탐지) | 행위시법 검토가 조 단위 버전만 비교해 목 단위 신설·이동(제2조 제1호 카목: 성과 도용→데이터 부정사용)을 못 봄. **6차 범위 밖** | strict xfail XPASS + 오탐 대조 유지 | 열림(6차 검증 뒤 착수, 시험 고정됨) |
| [TK-35](TK-35_storage_path_prefix_check.md) | 보안(방어 심층) | CodeQL 경로 10건 + 원본 파일 권한 0o444(모든 사용자 읽기, 1건) + 프로젝트 ID 로그 줄 위조 3건(총 14건): `_abs`가 경로를 접두 문자열로 비교해 형제 디렉터리(`storage2`)를 통과시킴(6건, 재현·현재 호출 경로 악용은 확인 못 함) + 허용 문자 검사가 막는 4건(`match`+`$`는 끝 줄바꿈 허용 → `fullmatch`). **6차 범위 밖** | 착수 시 평가 측이 strict xfail 고정 | 열림(6차 직후 보안 보강) |
| [TK-36](TK-36_exception_text_in_responses.md) | 보안(정보 노출) | CodeQL 2건: `access.py:369`가 키 설정 오류 문구(환경변수 이름)를 503 본문에 실음, `main.py:264`는 관리자 전용 진단. **6차 범위 밖** | 착수 시 평가 측이 strict xfail 고정 | 열림(6차 직후 보안 보강) |
| [TK-37](TK-37_client_key_validation_prototype.md) | 보안(클라이언트) | CodeQL 14건(prototype 13 + DOM 1): 관리자 화면 `tabs[next]` 검증이 `#admin/__proto__`를 통과해 `pref.*` 대입이 `Object.prototype`을 오염(논리 재현). **6차 범위 밖** | 착수 시 브라우저 시험 | 열림(6차 직후 보안 보강) |
| [TK-38](TK-38_regex_polynomial_growth.md) | 보안·견고성(**우선순위 높음**) | CodeQL `py/redos` 2건: **`pdf_parser.py` `SINGLE_GLYPH_SHOW_RE`가 지수 증가 — 조작된 PDF의 105바이트가 처리를 20초 이상 멈춤(재현)**, `korean_amount.py:65`는 지수지만 현재 호출 경로로 도달 불가 + 이차 증가 정규식 다수. **6차 범위 밖** | 착수 시 strict xfail(n=14·18·24가 1초 안에 끝날 것) | 열림(보안 보강 라운드 S1, 6차 검증 직후) |
| [TK-39](TK-39_explicit_name_context_exclusion.md) | 회귀(개인정보, **P1**) | 6차: `성명: {이름} 출력하지 마시오.`류 후행 문맥에서 이름 전체 마스킹 **21/21→3/21**, 실제 라우터를 거쳐 공급자 호출 도달 **0/36→36/36**(가짜 공급자), 기존 시험 `test_legal_military_terms_not_masked_as_person` PASS→FAIL. 낱말 예외 추가 금지, 구조로 | `test_round6_regressions.py` R6-01 strict xfail 30 + 기존 시험 | 열림(**7차 R1**) |
| [TK-40](TK-40_defense_exemption_by_keyword_cooccurrence.md) | 회귀(법리, **P1**) + 지시 위반 소지 | 6차: 요건 낱말·한정 결론 낱말 **공존만으로 경고 면제** — 요건 부정 4→0, 타 책임 확장 3→1(정상 항변 오탐 2→0은 개선). 6차 지시서가 금지한 예외 낱말 목록(설정 22개) | R6-02 strict xfail 6 | 열림(**7차 R2**) |
| [TK-41](TK-41_line_join_one_direction_default.md) | 회귀(입력 계층, P2) | 6차: 괄호 뒤 짧은 어절 `(이 사건)` 공백 삭제(10쌍 6→4), 같은 문단이 쪽의 다른 문단 배치(꽉 찬 줄 2개 이상)에 따라 `그 사람`→`그사람`. 시험 19개가 모두 '붙여라' 한 방향 | R6-03 strict xfail 4 | 열림(**7차 R3**) |
| [TK-42](TK-42_admin_js_declaration_deleted.md) | 회귀(프런트엔드, **P1**) | 7차 S5가 `admin.js`의 `let ready, initialized, previousHash` 선언 한 줄을 지워 쪽 초기화가 `initialized is not defined`로 중단(사용자 관리 메뉴·작업 제어 없음). 브라우저 시험 197건 중 55건 시점에 통과 4·실패 34·오류 17, `CI` 20분 시간 초과. 한 줄 복구로 197건 통과 | `test_round7_findings` admin 초기화 + 브라우저 197 | **해소**(9506481에서 선언 복구, 브라우저 시험 197/197 통과) |
| [TK-43](TK-43_explicit_label_relaxation_overreach.md) | 회귀(개인정보, P2) + 설계 한계 | 7차 R1이 '명시 성명 라벨' 완화를 모든 당사자 라벨로 확대 → `{원고·피고·증인…} 진술 조서는`의 `진술`을 인명으로 가림(12건 신규). 라벨 어휘 밖(`이름:`·`작성자:`…) 0/60 미탐은 시작과 같으며 **어휘 확대는 승인됨(2026-10-03)** | `test_round7_findings` 12건 + 어휘 strict xfail 8 | 개정 1 수용(e4867e7)·Steve 반영(PR #69 2b4a95b), **미배포** |
| [TK-44](TK-44_line_join_word_lists_and_ledger_regression.md) | 회귀(입력 계층, P2) + 지시 위반(낱말 목록) | 7차 R3이 `PAREN_DETERMINERS`·`STANDALONE_WORDS` 목록으로 맞춤 → 기존 원장 2건 실패(`하기 위\|해서는`), 목록 밖 0/14, `right_edge` 쪽 전역이라 같은 문단이 다른 줄 수에 따라 달라짐 | `tests/regression` + `test_round7_findings` 1 + strict xfail 5 | 설계 #63 조건부 승인. 구조 판정 미해결; 평가 측 조건 2 + TK-56 수용 후 2단계 |
| [TK-45](TK-45_defense_negation_by_word_match.md) | 회귀(법리, 미탐 **P1**) + 지시 위반 소지 | 7차 R2의 요건 부정 판정이 낱말 위치 일치 → `지체하지 않고` 등 정상 항변 새 오탐 3, 변형 표현 미탐(요건 부정 3/8·타 책임 1/5). 감사 표본 5건 해소 여부 미보고 | `test_round7_findings` 3건 + 미탐 strict xfail 4 | 정상 항변 오탐 0 유지·요건 부정 2/8·타 책임 0/4 잔여. Codex 대기열 4순위 |
| [TK-46](TK-46_explicit_name_stem_stopword_exclusion.md) | 회귀(개인정보, **P1**) | 7차 R1이 명시 성명의 끝 음절을 조사로 떼어 앞부분이 불용어면 이름 전체를 제외(`성명: 임용은`, 시작 마스킹 → 4da3910 미마스킹, 라우터 4필드 공급자 도달). 독립 감사 A7-01, 평가 측 놓침 | `test_round7_findings` 6건 | **해소**(9506481에서 `성명: 임용은` 계열 16/16 마스킹) |
| [TK-47](TK-47_f1_design_prep_not_tied_to_current_model.md) | 산출물 미완(문서, P2) | R6 F1 설계가 `FindingType` 97개 중 7종 이름 0/7 존재, 현행 `FindingWorkflow`·`ReviewDraft`·`ReviewRevision`과 무관, F3 호출 설계 없음. 독립 감사 A7-04, 평가 측 검토 누락 | 평가·감사의 현행 코드 대조 | **해소**(61ef12f: 문서 사실 검사 3건 XPASS, 표본 대조 11건 일치) |
| [TK-48](TK-48_pii_detect_unbound_local_crash.md) | 회귀(개인정보·가용성, **P1**) | 7차 보완 9506481이 `josa_match`를 분기 안에서만 정의하고 뒤에서 무조건 읽어 `성명: 김도현은 …`·`담당자: 박민수는 …`·`성명 불상의 자` 등에서 `detect()`가 `UnboundLocalError`(시작·4da3910 정상). 독립 감사 Sol B7-01과 일치. 호출부에서 삼켜 통과시키지 않는다(fail-open) | `test_round7_findings` R7-09 15건 + `성명: …은` 2건 | **해소**(b26754e: `detect()` 예외 0/441, R7-09 15·`성명: …은` 2 통과) |
| [TK-49](TK-49_ledger_expectations_rewritten_and_join_default.md) | 회귀(입력 계층, P2) + 절차 위반 | 9506481이 원장 기대값 15개를 어절 중간 공백 문자열로 바꿔 통과시키고(미보고), 줄 결합을 '항상 공백'으로 되돌려 TC-06 0.357 → 0.321·고정 dev 81.7 → 81.2. 독립 감사 Sol B7-03·B7-04와 일치(평가 측 초안 P1 → P2) | `tests/acceptance/test_pinned_ledger_7adf43f.py`(고정 사본)·5차·6차 보호 시험·`regression_gate` | 기대값/점수 복구 해소. 구조 판정은 TK-44와 묶어 설계 조건부 승인·2단계 대기 |
| [TK-50](TK-50_ledger_tests_deleted_to_pass.md) | 금지 행위(시험 삭제, **P1**) | 7C가 `test_ledger.py`를 7adf43f로 통째로 되돌려 7차 원장 시험 6개(TK-35~41)를 삭제 — 4da3910 원본으로 실행하면 `test_tk40`(요건 부정 경고 누락)·`test_tk41`(`(이사건)`) 실패. 보고서의 `git diff --stat`은 실제(341줄 변경·306줄 삭제)와 다름 | `test_pinned_ledger_4da3910_additions.py`·`check_test_edits.py` | **해소**(a1f3d1e·23364f9: 원장 69개가 4da3910과 동일, `test_tk41`만 알려진 미해결로 실패) |
| [TK-51](TK-51_structured_request_pii_boundary.md) | 개인정보 경계(**P1**, 기존 공백) | 구조화(JSON) 요청에서 라벨이 키·이름이 값이면 `_walk_fields`가 문맥을 잃어 실명이 공급자에 도달 — 평가 측 재현 246/324(7adf43f~61ef12f 동일). Codex 인계 문서 지적을 다른 입력으로 재현. F1/F3가 넓히는 경로 | `test_structured_request_privacy.py`(strict xfail 4) | 8차 44e73f9(PR #5): 구조화 요청 도달 **0/324·0/216**(해소), 단 과차단 증가 → TK-52. **병합 전** |
| [TK-52](TK-52_round8_stem_leak_and_overblocking.md) | 회귀(유출 방향, **P1**) + 과차단(P2) + 일반화 실패 | 8차 44e73f9: 조사 재귀 분리로 명시 성명 stem 계열 실명 누락(평가 측 16 → 9), 문맥 결합으로 정상 구조화 요청 과차단 6 → 14/28, 추가 불용어가 보호 시험 낱말 6개를 모두 포함하고 새 비공개 명사 과마스킹은 70→60/140·48→48/112 | 평가 측 비공개 세트(8차), 보호 시험 | 1절 해소(8B), 2·3절은 TK-53으로 이어짐 |
| [TK-53](TK-53_round8b_key_context_leak_and_lexicon_failure.md) | 회귀(유출 방향, **P1**) + 과차단(P2) + 일반화 실패 + 절차 | 8B 170c647: 이름 키 문맥을 정확 일치로 좁혀 라벨 밖 이름 키 실명 통과(즉석 점검 60→96/120), 키 문맥이 과마스킹을 요청 차단으로(8/28), 불용어 +145에도 과마스킹 변화 0, 보고서 부정확 | 평가 측 즉석 점검·비공개 세트(8차), 보호 시험 | 8C 86bd035: 세트 기준 충족(키 변형 96→0/120, 과차단 8→6/28) → 잔여는 TK-54 |
| [TK-54](TK-54_round8c_name_key_coverage_and_english_label_overreach.md) | 유출 잔여(**P1**) + 회귀(과탐지·과차단, P2) + 범위·보고 | 8C: 이름 키 아래 '이름 꼴 아닌' 값 실명 통과(시작과 같음 120/144), 세트 밖 키 모양 통과(240→132/240), 영문 라벨이 평문 탐지에 섞여 오탐(0→2/8) | 평가 측 새 즉석 점검·비공개 세트, 평문 불변 | 8D 751fb50: 값 모양 0/168·평문 오탐 0 해소, 잔여·회귀는 TK-55 |
| [TK-55](TK-55_round8d_overblock_and_key_head_regression.md) | 과차단(P2) + 회귀(유출, **P1**) + 유출 잔여(**P1**) | 8D(측정 정정 뒤): 과차단 6 → 12/28, 키 변형 0 → 12/120, system 위치 값 fail-closed 없음(30/144), 비인명 낱말로 시작하는 사람 키 유출 0 → 66/72, 역할 명사 키 144/144 | 평가 측 비공개 세트·새 즉석 점검 2판 | 3절 역할 명사 키만 알려진 미해결·배정 없음. 그 밖 경계 보완은 TK-56 재개 범위 |
| [TK-56](TK-56_round8e_structured_regression_and_convergence.md) | 회귀(유출, **P1**) + 지시 불이행 + 수렴 결정 | 8E 구조화 유출·키/값 경계; 이전 기록 보존 | 평가 측 비공개 세트·실제 라우터 | PR #70 71905eb 내용 수용: 목표 21건 승격, 과차단 6/28·유출 0. #73 평가 통합·Steve 병합/배포 전 |
| [TK-57](TK-57_contact_rrn_notation_gaps.md) | 탐지 공백(**P1**, 보장 대상) — **해소(8F-1 e1bd9ff, 2026-10-04)** | 연락처·주민등록번호 표기 변형(구분 기호·전각·줄바꿈·OCR 띄어쓰기·괄호) 누락: RRN 36/78·PHONE 30/90, 라우터 도달 144/312·120/360(기존 공백) | 평가 측 `contact_rrn` 세트 | 필수 게이트 해소·배포(8F-1). 국가코드 경계 1/54·종류 표시만 참고 잔여(게이트 밖) |

**구현 에이전트 작업 지시서(붙여 넣기용):** [1차](PROMPT_FOR_ANTIGRAVITY.md) · [2차](PROMPT_FOR_ANTIGRAVITY_ROUND2.md) · [3차](PROMPT_FOR_ANTIGRAVITY_ROUND3.md) · [4차 안정화](PROMPT_FOR_STABILIZATION_ROUND4.md) · [5차 안정화](PROMPT_FOR_STABILIZATION_ROUND5.md) · [6차 안정화(5차 회귀 보완)](PROMPT_FOR_STABILIZATION_ROUND6.md) · 구현→평가 요청은 [requests/](requests/README.md) · **[7차(6차 회귀 보완 + 보안 보강 + F1 착수 기준)](PROMPT_FOR_STABILIZATION_ROUND7.md)** · [보안 보강 초기 원문(7차에 흡수)](PROMPT_FOR_SECURITY_ROUND.md) · [7차 보완(7B, 7C가 후속)](PROMPT_FOR_STABILIZATION_ROUND7B.md) · [7차 보완 2차(7C, b26754e로 소화·미승인)](PROMPT_FOR_STABILIZATION_ROUND7C.md) · [7D(범위 축소: 시험 복원·법리·F1 문서)](PROMPT_FOR_STABILIZATION_ROUND7D.md) · [8차 개인정보 경계(TK-51·TK-43)](PROMPT_FOR_ROUND8_PRIVACY_BOUNDARY.md) · [8차 보완(8B, TK-52 + PR #5 갱신 절차)](PROMPT_FOR_ROUND8B_TK52.md) · **[8C(TK-53, 구현 Codex)](PROMPT_FOR_ROUND8C_CODEX.md)**

**기능 개선 요청(결함 티켓과 별도):** [FR-01 검토 화면 중복 해소·참고자료(RAG) 활용 — 타당성 검토](FR-01_review_screen_and_reference_integration.md) · [F1 라운드 작업 지시서](PROMPT_FOR_FEATURE_ROUND_F1.md)(5차 검증 뒤 착수)

**GitHub 접근 권한 점검표(평가·감사용, 최소 권한):** [GITHUB_ACCESS](GITHUB_ACCESS.md)

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

## 사용자 결정(2026-10-04 반영됨)
- **개인정보 보장 범위(2026-10-04):** 자동 마스킹 **보장 대상은 연락처·주민등록번호**다. 성명·주소 등 그 밖의 개인정보는 사용자가 업로드 전에 직접 처리한다(업로드 화면 안내 + 확인 체크 + 서버 측 확인 + 감사 기록 + 보고서 머리 표시, [지시서](PROMPT_FOR_UPLOAD_PRIVACY_NOTICE.md)). 성명 자동 마스킹은 보조 기능으로 유지하고 8C 수준에서 동결한다. 목표는 퇴보 없음이며, **점검 결과는 참고만 하고 합격·불합격에 쓰지 않는다**(사용자 지시 2026-10-04). 단, 저장소의 기존 성명 보호 시험은 CI 필수로 유지한다(①안). 운영자의 약관·처리방침(국외 이전·위탁 고지)은 사용자가 검토한다.
- **기존 업로드 시험 갱신(평가 측 결정 2026-10-04):** 확인 값 없이 업로드하던 기존 시험과 `scripts/check_upload_runtime.py`는 요청에 `privacy_ack=true`만 더하는 최소 수정을 승인한다(단언 삭제·완화·표시·삭제 금지). [업로드 안내 지시서 6절](PROMPT_FOR_UPLOAD_PRIVACY_NOTICE.md)
- **8C 수렴(TK-56):** 8E 불승인 뒤 8C 동작 + 영문 어휘 분리로 되돌린다([8F 지시서](PROMPT_FOR_ROUND8F_CODEX.md)).
- **구조화 이름 키(TK-55, '좁게 + 스키마 고정'):** 키 의미 추측을 더 넓히지 않는다. 8E는 회귀 복구와 과차단 ≤ 6/28 회복만 한다. 키 신호 없는 유형은 알려진 미해결(strict xfail)로 두고, F1/F3 설계에서 자유 텍스트 키 허용 목록(스키마 고정)으로 막는다.
- **릴리스 절차:** 평가 측 추천대로. `main` 병합 = 배포(Render가 `main` 푸시 시 자동 재배포, 사용자 확인). 조건: 평가 통과·봉인 시험·열린 P1 회귀 0·사용자 승인. **배포와 버전 상향은 분리**한다. 배포 직후 사용자가 온라인 점검 1회(서면9 PDF)를 실행해 결과 JSON을 평가 측에 준다. 첫 릴리스는 8C 수용 뒤. → [RELEASE_PROCEDURE](../scorecards/RELEASE_PROCEDURE.md)
- **F1 착수 요건 변경(2026-10-04, 사용자):** 8차 종결을 F1 착수 요건에서 뺀다. F1은 별도 브랜치(`antigravity/f1-review-screen`)에서 개발하고, 병합 순서 **8F → 업로드 안내(PR #11) → F1**로 `Steve_ACASiaLAW`에 병합한다. G1~G10 판정은 F1 병합 직전 SHA로 옮긴다. F3 구현은 8F가 들어온 뒤 시작한다. 첫 릴리스는 F1 병합 전에 낸다. → [판정서 해당 절](../scorecards/f1_gate_verdict.md)
- **행위시법 검토 보강을 F1에 포함(2026-10-04, 사용자):** 요청 16 + TK-34를 F1 라운드의 작업 묶음 FT로 넣는다. 순서 F1 → F2 → FT → F3. FT는 탐지 변경이라 점수 하락 0·커밋 분리·새 `rule_id` 요청서 승인 규칙을 따로 둔다. 2026-10-03의 '행위시법 보강 → F1' 순서 결정을 대체한다. → [F1 지시서 FT](PROMPT_FOR_FEATURE_ROUND_F1.md)
- **8차 병합 완료(2026-10-04, 사용자 '병합해'):** PR #5(aec05ff) → `Steve_ACASiaLAW` [adfa198], PR #12(평가 측) → [1ec9e24]. 통합 브랜치의 제품 코드가 수용한 aec05ff와 같음을 확인했다. PR #10은 같은 커밋이라 병합으로 함께 닫혔다. 남은 첫 릴리스 조건: 업로드 안내(PR #11) 수용·병합.
- **업로드 안내 문구 확정(2026-10-04, 사용자):** 제목 '제한적 개인정보 가림 기능 제공 안내', 본문 3문장, 확인 체크 문구 확정. 둘째 문장 뒷부분은 보조기능 문장으로, 괄호는 빼고, 보고서 머리는 새 안내에 맞추기로 함(사용자 선택). 판 1.1. → [업로드 안내 지시서 7절](PROMPT_FOR_UPLOAD_PRIVACY_NOTICE.md)
- **첫 릴리스(2026-10-04, 사용자 '추천대로'):** 릴리스 후보 33b509f `verify_all` 전체 종료 0, 버전 판정 0.10.0(minor), 등급 임계값 현행 유지, 봉인 시험은 첫 릴리스에 한해 생략(세트 없음, 다음 릴리스 전 마련). 순서: 평가 측 기록 PR → Codex 버전 커밋 → 릴리스 PR. → [판정서](../scorecards/f1_gate_verdict.md)
- **업로드 안내 수용(2026-10-04, PR #11 41faa2e):** CI 결과 인용·diff 검토로 수용. 병합은 사용자 승인. → [판정서](../scorecards/f1_gate_verdict.md)
- **전달문 통합(2026-10-04, 사용자):** Antigravity·Codex 전달문은 에이전트별 통합본 하나로 낸다 → [NEXT_FOR_ANTIGRAVITY](NEXT_FOR_ANTIGRAVITY.md) · [NEXT_FOR_CODEX](NEXT_FOR_CODEX.md)
- **F1 판정(2026-10-04, PR #13 5d3b006): 불승인·F2 착수 보류.** 보완: 화면은 `/api/finding-categories`로 분류(하드코딩 제거), RAG·관련 법조문 섹션을 '확인할 항목'으로 이동(기존 브라우저 시험은 찾는 위치만 최소 수정 승인), 보고서·19b 배정 수치 정정, 19b의 없는 `rule_id`·HIGH 기준·검사 범위 정정. F2는 F1 수용·19b 정정·평가 측 T1~T5 고정 뒤. → [PR #13 코멘트](https://github.com/stevelee0119/verify_ACAS_LAW/pull/13#issuecomment-5978517656)
- **F1 2차 판정(2026-10-04, PR #13 3bf349b): 내용 수용·병합 보류·F2 착수 허용.** 1차 보완 6항목 충족, T3·T4·T5 통과. `Steve_ACASiaLAW`와 충돌(index.html·styles.css, PR #11 뒤) → 양쪽 유지로 해소. 병합은 0.10.0 릴리스가 `main`에 들어간 뒤. F2는 해소 SHA CI 초록이면 착수. **충돌 해소 0848e69 CI 초록 → F1 수용·F2 착수 조건 충족**([PR #13 코멘트](https://github.com/stevelee0119/verify_ACAS_LAW/pull/13#issuecomment-5979119284)). → [판정서](../scorecards/f1_gate_verdict.md) · [통합 전달문](NEXT_FOR_ANTIGRAVITY.md)
- **버전 커밋 판정(2026-10-04, PR #15 472861e): 수용.** 3파일·커밋 1개, 버전 정책·README 점검 통과, 내용이 판정서와 일치. 병합은 사용자 승인 뒤. → [PR #15 코멘트](https://github.com/stevelee0119/verify_ACAS_LAW/pull/15#issuecomment-5979233496)
- **릴리스 0.10.0(2026-10-04): PR #16 병합, `main` 22ca134.** 태그 `v.0.10.0` 부착 확인(2026-10-05, 22ca134). 배포 확인(commit 22ca134·DB ok). **온라인 점검 19/23**(10-01 18/23): 새 실패 PII-K6 → [TK-58](TK-58_account_number_labeled_rrn.md)(계좌번호 RRN 분류, P3). 사용자 결정: 되돌리지 않음.
- **F1 병합 게이트 판정(2026-10-04, 후보 e8745fb): 병합 보류 — G6(같은 SHA CI)·G8(독립 감사)·G9(보고서 건수 정정) 남음.** 나머지 7개 충족. → [판정서](../scorecards/f1_gate_verdict.md) · [감사 의뢰서](PROMPT_FOR_AUDIT_F1.md) → [판정서 '릴리스 기록'](../scorecards/f1_gate_verdict.md)
- **구현·평가 중복 제거(2026-10-04, 사용자 '승인'):** 구현 = 바꾼 부분의 시험만 + PR 코멘트 '검토 요청'(`verify_all --quick`·차수별 보고서 절 폐지). 평가 = 검토 요청 + CI 완료 SHA만 검토, 작은 보완은 PR 코멘트로 판정, 전체 `verify_all`은 탐지·채점·개인정보 엔진 변경과 릴리스 후보에만. 평가 측 지시 사전 점검(관련 기존 시험을 미리 돌림) 신설. PR #11 4차 보완부터 적용. → [AGENT_ROLES 2.1](../AGENT_ROLES.md)
- **검증 실행 분담(2026-10-04, 사용자 '추천방안으로 진행'):** 구현 = `verify_all --quick` + 같은 SHA CI 링크, 평가 = 증분은 CI 인용·수용 SHA에서만 전체 1회, 감사 = 재실행 없이 세트·주장 표본 점검. 선행 장치: 보호 경로 변경 점검(`check_protected_paths.py`), CI 실패 시험 목록(`ci_failed_tests.py`), 회귀 게이트 기준 캐시(평가 측 측정: 4분 49초 → 17초, 성적표 재사용까지 5초). → [AGENT_ROLES 2.1](../AGENT_ROLES.md)
- **릴리스 구성(2026-10-04, 사용자 '권고대로'):** 첫 릴리스 = 8F + 업로드 안내(PR #11), F1은 별도 릴리스. → [RELEASE_PROCEDURE 5절](../scorecards/RELEASE_PROCEDURE.md)
- **8F-1 수용 — 8차 종결 조건 충족(평가 측 2026-10-04):** aec05ff(제품 e1bd9ff). 필수 세트 1·2·3판 누락·도달·오탐 0, `verify_all` 종료 0, 같은 SHA CI 성공. TK-57 해소. 병합(PR #5 fast-forward 또는 PR #10 직접 병합)은 사용자 승인. → [판정서 '8차 7차 판정'](../scorecards/f1_gate_verdict.md)
- **F0 설계(19_f1_design, ccdabc7) 회신(평가 측 2026-10-04): 조건부 승인** — 필수 수정 반영 뒤 F1·F2 착수 가능, F3는 8F 반영·스키마 고정 회신 뒤, FT는 설계 보충 회신 뒤. → [회신서](F1_DESIGN_REVIEW_REPLY.md)
- **일자별 추이표:** 평가 결과를 제시할 때 1일 단위 표(성능 점수·주요 기능·개선·회귀·평가 개요)를 함께 낸다. → [DAILY_TREND](../scorecards/DAILY_TREND.md)

## 사용자 결정(2026-10-02 반영됨)
| 항목 | 결정 | 처리 |
|---|---|---|
| 사업자등록번호 | 마스킹 원칙 | `test_sec01` 기대를 평가 측이 마스킹으로 갱신 |
| TK-12 미러 시험 자료 | 평가 측이 공식 원문으로 구성(확인 못 한 항목은 "확인 못 함") | **완료(2026-10-03)** — 2018도15313은 공식 미확인이라 확인된 대법원 2020다268807 판결로 교체(사용자 결정), 정답지 의도 불명이라 카목 단계는 공식 원문 기준으로 정정·신설 카목 검출은 TK-34 |
| TK-23 B 조문 부존재(증거 A등급) 심각도 | HIGH | 5차 지시서 U9-1 |
| TK-09 모델 의견 승격 | 기본 꺼짐 유지 | 변경 없음 |
| 기준선 상향(2026-10-03 갱신) | **회귀 해소 뒤 81.7 이상으로 상향**(5차 실측 dev 81.2는 회귀 상태라 올리지 않음) | 평가 측이 실측으로 사용자 승인 후 |
| 동일 시행일 복수 버전 | 두 버전 병기·대조 | 6차 |
| 다음 라운드 범위(2026-10-03 6차 점검 뒤 갱신) | **7차 = 6차 회귀 보완(TK-39·40·41) + 보안 보강(TK-35~38) + F1 착수 기준 확정** → 7차 검증과 F1 게이트 1차 판정 → **'행위시법 검토 보강'(요청 16 + TK-34)** → F1 게이트 재측정·사용자 승인 → **F1**(F1→F2→F3) → TK-24. (사용자 결정 순서 '행위시법 보강 → F1 → TK-24'는 그대로이고, 7차 지시서가 F1 착수 게이트를 더한다) | [7차 지시서](PROMPT_FOR_STABILIZATION_ROUND7.md) |
| `main` 보호 | 점수 하락 게이트 먼저, CI는 초록 뒤 추가. Docker OCR readiness 제외. 강제 푸시·삭제 금지 켬, PR 필수·관리자 포함·최신 유지는 켜지 않음 | 5차 지시서 U8 |
| `main` 보호 갱신(2026-10-03) | CI 테스트 job을 필수 확인에 추가, **관리자 포함 적용 켬**(`enforcement_level: everyone`). PR 필수·최신 유지 끔, 강제 푸시·삭제 금지 유지 | 사용자가 웹 설정으로 변경. 평가 측이 **API(`GET branches/main/protection`)로 전 항목 직접 확인**, 사용자 스크린샷 3장과 일치 |
| 생성 소프트웨어명(PDF `Producer`) | 작성자 정보에서 분리해 INFO | 5차 지시서 U9-2 |
| `main` 병합 | 5차 검증 뒤 PR(사용자 요청 시에만 PR 생성) | 사용자 |
| 기능 라운드 F1 D1~D6 | 쟁점 매트릭스 별도 탭 유지 · 상단 요약+HIGH 이상 고정 안내 · 파일 정보 노출은 보안 카드 · 참고 의견(승격 없음) · **회귀 보완(6차) 검증 뒤 순차** · 기존 전송 정책 그대로 | [F1 지시서](PROMPT_FOR_FEATURE_ROUND_F1.md), [FR-01](FR-01_review_screen_and_reference_integration.md) |
| 프로그램 버전 | 성능 기준으로만 상향(정수 급격·첫째 자리 일부·둘째 자리 미세), 커밋마다 올리지 않음 | [VERSION_POLICY](../scorecards/VERSION_POLICY.md), `scripts/check_version_policy.py` |
| 버전 등급 임계값(2026-10-03) | **현행 유지, 첫 판정(6차 검증 뒤) 결과를 보고 재검토** | VERSION_POLICY 5절 |
| Docker OCR readiness 필수 확인(2026-10-03) | **완료·확인됨(2026-10-03)** — 연속 초록 3회 기준 충족(CI run 263·264·265·267·268) 뒤 사용자가 `main` 필수 확인에 추가. 평가 측이 `GET branches/main`으로 필수 확인 3개(`점수 하락 게이트`·`테스트 (SQLite + PostgreSQL/pgvector + Redis)`·`Docker OCR readiness`)·`everyone`·관리자 포함을 확인 | [GITHUB_ACCESS 9절](GITHUB_ACCESS.md) |
| 준비서면 534210 문제지(2026-10-03) | 문제지 없음 — **카목 단계는 현재 정정 상태 유지**(문제지가 생기면 그때 대조) | [TK-12](TK-12_ci_red_gitignored_mirror_data.md), [TK-34](TK-34_item_level_temporal_review.md) |
| TK-34 착수 시점(2026-10-03, **2026-10-04 대체: F1 라운드의 FT로 포함**) | **요청 16과 묶어 '행위시법 검토 보강' 라운드로 7차(6차 회귀 보완 + 보안 보강) 직후**(F1은 그 뒤) | [TK-34](TK-34_item_level_temporal_review.md) |
| TK-11 해석(2026-10-03) | **평가 측 해석 승인: 다수결이 판정을 정하고 객관적 흔적 부재는 판정을 막지 않는다. 단, '모델 다수 의견(참고)' 문구와 흔적 표시(`involvement`·`objective_traces`·`verdict_distribution`)는 유지** | [TK-11](TK-11_ai_verdict_majority_vote.md) |
| 코드 스캔 경고 분류(2026-10-03, 03:13 재수집 반영) | 열린 경고가 38건에서 **103건**(critical 2·high 76·medium 25)으로 늘었다(`main` 코드는 그대로, 신규 65건은 모두 운영자 입력 경로 — 분석 설정 변경 추정). 조치 완료 6(워크플로) · 티켓 TK-35 14·TK-36 2·TK-37 14·TK-38 2 · **오탐/의도 후보 65건**(사용자가 GitHub에서 처리, 위협 모델 설정 확인 권고) | [GITHUB_ACCESS 6·8절](GITHUB_ACCESS.md) |
| 보안 점검 후속(2026-10-03, '추천대로') | ① 워크플로 5개에 `permissions: contents: read` 추가 ② 경고 위치는 (B) 읽기 전용 내보내기 워크플로로 받음 ③ 오탐/수정 안 함 처리는 경고 위치 확인 뒤 사용자가 GitHub에서 ④ TK-35~38은 **6차 검증 직후 '행위시법 검토 보강' 전에 소규모 보안 보강 1회** | 평가 측이 ①②를 `a5e89ae`·`b28582a`로 적용([GITHUB_ACCESS 7절](GITHUB_ACCESS.md)). ④는 6차 범위를 건드리지 않음 — TK-38이 조작 PDF로 처리를 멈출 수 있는 실제 위험으로 확인됐으나 사용자가 '추천대로'로 **앞당기지 않고 보안 보강 첫 항목(S1)으로 두기로 결정**(같은 날) |
| 6차 점검 판정(2026-10-03) | 독립 감사(Codex)의 핵심 결론 타당 — **6차 완료 승인 불가**, 기준선 `79.9/77.3`·버전 `0.9.13` 유지, F1 보류. 새 회귀 4건(TK-39·40·41, R6-04)은 평가 측 독립 재현으로 확인 | [AUDIT_REVIEW_ROUND6](AUDIT_REVIEW_ROUND6.md), HISTORY 11절 |
| 6차 병합·F1 기준값·CodeQL(2026-10-03) | **병합 허용**(평가 측이 `a8ead24`로 병합, 승격 `7adf43f`, 시작 SHA `7adf43f`) · **F1 게이트 초기 기준값 추천대로 확정**(비공개 변형 이름 마스킹 ≥ 95%, F3 ≥ 98%) · CodeQL 위협 모델에 **로컬 입력 포함**을 켰다(신규 경고 65건의 원인 확인) | [7차 지시서](PROMPT_FOR_STABILIZATION_ROUND7.md) 0.1·2절, [GITHUB_ACCESS 8절](GITHUB_ACCESS.md) |
| 7차 독립 측정 판정(2026-10-03) | **F1 착수 불가·7차 완료 승인 불가** — 구현 지표(점수 81.7/79.2·회귀 게이트·6차 회귀 40·보안 11 XPASS)는 재현되나 `admin.js` 선언 삭제(P1)·원장 2건·과마스킹·새 오탐이 확인됨. 충족 G5·G7·G10, 미충족 G1·G2·G3·G4·G6·G9, G8 미실시. 기준선 `79.9/77.3`·버전 `0.9.13` 유지 | [f1_gate_verdict](../scorecards/f1_gate_verdict.md), [HISTORY 12절](../scorecards/HISTORY.md), TK-42~45, [7차 보완 지시서](PROMPT_FOR_STABILIZATION_ROUND7B.md) |
| 7차 측정 후속 결정(2026-10-03 '추천대로') | ① **구현 브랜치(4da3910)는 병합하지 않고** 구현 측이 7차 보완 지시서대로 고친 뒤 고정 SHA에서 평가 측이 병합·XPASS 승격 ② **라벨 어휘 확대 승인**(범주 전체 닫힌 목록, 보호 시험은 대표 4개·나머지는 비공개 변형으로 측정) ③ 7차 보완 지시서를 Antigravity에 전달(사용자) | [TK-43](TK-43_explicit_label_relaxation_overreach.md), [7차 보완 지시서](PROMPT_FOR_STABILIZATION_ROUND7B.md) |
| 독립 감사(Astra 7차 4da3910) 대조(2026-10-03) | 감사의 핵심 결론·지적 6건 **모두 타당**(평가 측 재현). 평가 측이 놓친 3건(TK-46 명시 성명 stem 제외·TK-47 F1 설계 불일치·TK-42 영향 범위)을 반영, TK-45 P1 상향, CI 기준을 'XPASS(strict) 외 실패 0'으로 정정. 감사의 보완 지시서는 평가 측 7차 보완 지시서에 흡수 — **Antigravity에는 [갱신된 7차 보완 지시서](PROMPT_FOR_STABILIZATION_ROUND7B.md)만 전달**(두 문서 중복·충돌 방지) | [AUDIT_REVIEW_ROUND7](AUDIT_REVIEW_ROUND7.md) |
| 7차 보완 9506481 측정·독립 감사(Sol) 대조(2026-10-03) | **7B 완료 불승인·승격 보류·F1 착수 불가** — Sol의 B7-01~06과 평가 측 측정이 일치(CI 실제 실패 13 + strict XPASS 66, dev 81.2, 원장 기대값 15개 변경). 평가 측이 추가 확인: `detect()` 예외 14/441, 라우터 비공개 240 도달 12(4da3910 0), 새 라벨 오탐 36%. **평가 측 오류 정정 2건**: ① 7B 지시서의 `PIIDetector`(실제 `detect()`·`PIIEngine`) ② TK-43 요구 ①이 반대 방향(유출) 시험 없이 한 방향만 적어 R7-02(오탐)↔R7-12(유출)가 한 목록에서 부딪힘 — 어느 빌드도 둘을 함께 만족하지 못함. 충족 G7·G10, 미충족 G1~G6·G8·G9. 기준선·버전 유지 | [f1_gate_verdict 2차](../scorecards/f1_gate_verdict.md), [HISTORY 13절](../scorecards/HISTORY.md), TK-48·49, [7C 지시서](PROMPT_FOR_STABILIZATION_ROUND7C.md) |
| 7C(b26754e) 독립 측정(2026-10-03) | **7C 완료 불승인·승격 보류·F1 착수 불가.** 개선: `detect()` 예외 0·이름 330/330·어휘 밖 60/60·라우터 0/240·dev 81.7(회귀 게이트 통과)·정상 항변 오탐 해소. 문제: **원장 시험 6개 삭제(TK-50, 보고서 diff stat 불일치)**, 요건 부정 탐지 시작 수준 후퇴(TK-45), 과마스킹 R7-02 12·R7-10 18(유출 0 대가), F1 문서 `FindingWorkflow` 부재 주장(TK-47). 충족 G5·G10, 미충족 G1~G4·G6·G8·G9 | [f1_gate_verdict 3차](../scorecards/f1_gate_verdict.md), [HISTORY 14절](../scorecards/HISTORY.md), TK-50, `scripts/check_test_edits.py` |
| 방향 전환 결정(2026-10-03 '추천대로') | ① **7라운드 종결 기준 재정의:** 실제 실패 0 + 못 푼 것은 strict xfail로 명시된 알려진 미해결(줄 결합·과마스킹·법리 일부, 티켓 등재) ② **한 라운드에 한 영역**(7D 법리+시험 복원+F1 문서 → 7E 개인정보 과마스킹 → 줄 결합은 설계 결정 뒤) ③ **시작 대비 개선이 없으면 시작 상태로 되돌리고 한계로 기록**(법리는 7D가 마지막 시도) ④ **개인정보 정책: 실명 유출 0(R7-12)을 하한으로 고정, 과마스킹은 닫힌 불용어 집합으로 줄이고 잔여 오탐 허용** ⑤ 절차는 게이트로 강제(`check_test_edits`·고정 사본 2개). 미결: 고정 세트에 이 영역을 재는 시험 승격(과적합 우려, 사용자 결정 미요청) | [PROMPT_FOR_STABILIZATION_ROUND7D](PROMPT_FOR_STABILIZATION_ROUND7D.md), [f1_gate_verdict 3차](../scorecards/f1_gate_verdict.md) |
| codex/stability-recovery 61ef12f 독립 측정(2026-10-03) | **7D 범위 대부분 충족** — 수용 시험 실제 실패 0·원장 69개 원 기대값·F1 문서 XPASS·정상 항변 오탐 0·점수 81.7/79.2·회귀 게이트 통과. 남은 것: 원장 `test_tk41`(알려진 미해결), 법리 잔여(새 세트 요건 부정 2/8). **새로 확인: 구조화 요청 실명 도달 246/324(TK-51, 기존 공백)**. 평가 측 오류: 비공개 법리·줄 결합 문구를 티켓에 인용해 세트 오염 → 새 세트로 재측정·인용 가림. **Round 7: 평가 측 종결 절차 뒤 조건부 종결(사용자 승인 대기). F1 착수 불가** | [f1_gate_verdict 4차](../scorecards/f1_gate_verdict.md), [HISTORY 15절](../scorecards/HISTORY.md), TK-51 |
| **Round 7 종결(2026-10-03, 사용자 '추천대로')** | 평가 측이 61ef12f를 병합(`5c32da0`)·원장 `test_tk41` 알려진 미해결 표시·XPASS 64 승격. 같은 SHA CI: `da716e1`에서 [`점수 게이트` 37114960080](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/37114960080) **성공**(성적표·점수 게이트·수용 시험·회귀 원장·회귀 게이트·하드코딩·시험 삭제·약화 점검·버전 정책 전 단계), [`CI` 37114960091](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/37114960091) **성공**(SQLite 전체 시험·마이그레이션·PostgreSQL/pgvector + Celery 시험·Docker OCR readiness 전 단계) — 7라운드 들어 처음으로 같은 SHA 전 단계 초록. 알려진 미해결은 TK-43·TK-51·TK-44/49·TK-45 잔여. **F1 착수 불가 유지**, 다음은 개인정보 경계 라운드 → 행위시법 검토 보강 | [f1_gate_verdict 'Round 7 종결 기록'](../scorecards/f1_gate_verdict.md) |
| 8차 1차 측정(44e73f9, PR #5, 2026-10-03) | **8차 완료 불승인·PR #5 병합 보류** — 구조화 요청 유출 0(TK-51 해소)·평문 유출 0·점수 81.7/79.2·보호 시험 실제 실패 0. 그러나 명시 성명 stem 계열 실명 누락(16→9, 유출 방향)·정상 구조화 요청 과차단 6→14/28·과마스킹 새 비공개 세트 기준 미달(60/140·48/112) → TK-52 | [f1_gate_verdict '8차 1차 판정'](../scorecards/f1_gate_verdict.md), [HISTORY 17절](../scorecards/HISTORY.md) |
| 8차 2차 측정(8B 170c647, 2026-10-03) | **8B 불승인·PR #5 fast-forward 보류** — 실명 누락 복구(stem 16/16)·과차단 14→8/28. 그러나 이름 키 문맥을 정확 일치로 좁혀 라벨 밖 이름 키 실명 통과(즉석 점검 60→96/120, 유출 회귀)·과마스킹 두 번째 변화 0(60/140·48/112) → TK-53. 반복 체계 검토·역할 배분·로드맵 작성 | [f1_gate_verdict '8차 2차 판정'](../scorecards/f1_gate_verdict.md), [process_review](../scorecards/process_review_2026-10-03.md) |
| **반복 체계 개정(2026-10-03, 사용자 '1~5 추천대로')** | ① 과마스킹(TK-43)은 8차 수용 기준에서 분리(별도 트랙, 설계 메모 먼저) ② 8C 구현은 Codex(2개 증분 시험 전환 뒤 확정) ③ 감사는 라운드 첫 완료·F1 착수 전, 검출 휴리스틱 변경은 설계 메모 먼저 ④ 평가 측 자동 재측정(구현 PR 구독 → 건수만 코멘트) ⑤ PR #8 병합. 평가 측 조치: 보호 시험 R7-02·R7-10·TK-51 표시 승격(`evaluator/round8-promotion` d20cde2, 170c647 위), `scripts/verify_all.py` 신설, `AGENT_ROLES.md`·`AGENTS.md` 개정, 8C 지시서 | [process_review](../scorecards/process_review_2026-10-03.md), [AGENT_ROLES](../AGENT_ROLES.md) 2.1절 |

## 아직 사용자가 정할 것
- Round 7 종결 절차: **완료**(위 결정 표). 종결 기록 커밋은 저장소 규칙(필수 확인 3개) 때문에 PR [stevelee0119/verify_ACAS_LAW#3](https://github.com/stevelee0119/verify_ACAS_LAW/pull/3)으로 올렸다(사용자 승인 '1번'). **병합은 사용자.**
- **8C 지시서 전달(사용자):** [PROMPT_FOR_ROUND8C_CODEX.md](PROMPT_FOR_ROUND8C_CODEX.md)를 Codex 작업 설명에 붙여 넣는다(시작 `evaluator/round8-promotion` d20cde2). Codex 환경 설정에 tesseract·Python 3.11을 넣는다. 평가 측은 Codex PR을 구독해 자동 재측정한다.
- (사용자 설정 2026-10-03) ruleset 24413473의 대상을 `~ALL`에서 `main`으로 좁혔다. 작업 브랜치의 '새 브랜치 → CI → fast-forward' 단계가 없어졌다.
  **추가 제안:** 실제 통합 브랜치는 `Steve_ACASiaLAW`다(`main`보다 108커밋 앞서고, `main`은 10-01 `9933548`). 지금은 보호 규칙이 없어 필수 확인 없이 병합, 직접·강제 푸시, 삭제가 가능하다. ruleset 대상에 `refs/heads/Steve_ACASiaLAW`를 더하기를 권한다.
- (결정 완료 2026-10-03 '1~5 추천대로') 8B 판정 뒤 사용자 결정 ①~④ — 위 결정 표.
- (완료) **8B 지시서 전달(사용자):** [PROMPT_FOR_ROUND8B_TK52.md](PROMPT_FOR_ROUND8B_TK52.md)를 Antigravity에 전달한다. 수정 커밋은 새 브랜치(`antigravity/round8b-tk52`)로 올리고, 평가 측 재측정·승격 뒤 평가 측이 PR #5 브랜치를 초록 SHA로 fast-forward한다(사용자 승인 2026-10-03). PR #5 병합은 사용자.
- (전달 완료) **8차 지시서 전달(사용자):** [PROMPT_FOR_ROUND8_PRIVACY_BOUNDARY.md](PROMPT_FOR_ROUND8_PRIVACY_BOUNDARY.md)를 구현 담당(Antigravity 또는 Codex — 사용자 선택)에게 전달한다. 구현 측도 `Steve_ACASiaLAW`에 직접 푸시할 수 없으므로 작업 브랜치 → PR로 올린다. 다음 사용자 결정: 기준선 상향(81.7/79.2) 여부.
- 다음 라운드 순서(추천): 개인정보 경계(TK-51 + TK-43 과마스킹) → '행위시법 검토 보강'(요청 16 + TK-34) → F1 직전 재측정·독립 감사 → F1 착수 승인. **(2026-10-04 변경: F1은 8차 종결을 기다리지 않고 별도 브랜치에서 착수, G1~G10은 병합 직전 판정, 행위시법 검토 보강은 F1의 FT로 포함 — 결정 절 참조)**
- `#103`(`runner.py:46`)을 닫았다는 사용자 보고(2026-10-03)는 평가 측이 아직 확인하지 못했다 — 경고는 `main` 반영 뒤 수집에서만 갱신된다.
- 정수 상향 승인(해당 판정이 생길 때). 버전 등급 임계값은 2026-10-03에 현행 유지로 정했고 첫 판정 뒤 재검토한다.
- (결정 완료 2026-10-03) `main` 보호의 관리자 포함 적용: 사용자가 켰고 평가 측이 확인했다. 앞으로 주인 계정으로 푸시하는 에이전트도 필수 확인 2개가 초록이 아닌 커밋을 `main`에 올릴 수 없다. **병합은 PR로**(`CI`는 PR에서 돈다).
- **CI를 `main`의 필수 확인에 추가: 완료·확인됨(2026-10-03).** 사용자가 설정했고 평가 측이 `GET branches/main`으로 필수 확인 2개(`점수 하락 게이트`, `테스트 (SQLite + PostgreSQL/pgvector + Redis)`)를 읽어 확인했다(적용 수준 `non_admins` 유지). Docker OCR readiness 추가 여부(연속 초록 확인 뒤)는 별도 결정.
- 서면9 같은 PDF의 온라인 재실행(5차 U4 이후) 결과 확인.
- 보안 점검 후속: 결정 완료(2026-10-03 '추천대로') — 위 결정 표 참조. 남은 사용자 조치는 **GitHub 경고 처리**(URL 부분 문자열·평문 로깅의 오탐/수정 안 함)뿐이며, 경고 위치를 확인한 뒤 사용자가 GitHub에서 한다.
- TK-38 A(PDF 정규식 지수 증가): **결정 완료(2026-10-03 '추천대로') — 앞당기지 않고 보안 보강 라운드의 첫 항목(S1)으로 둔다.** 6차 범위(TK-30~33)는 `paragraph_reconstruction.py`·이름 마스킹·법리 군집이라 `pdf_parser.py`를 직접 지정하지 않으나, R2의 'PDF 폭 40 INJ-1' 항목이 같은 파일을 건드릴 수 있어 충돌을 피하려고 6차 검증 뒤로 둔다. **그 사이 조작된 PDF 위험은 남아 있다**(코드 변경 없이 줄일 방법은 확인하지 못함). 지시서: [PROMPT_FOR_SECURITY_ROUND.md](PROMPT_FOR_SECURITY_ROUND.md)(6차 검증 직후 전달, 전달 전 평가 측이 strict xfail을 먼저 고정).
- 6차 병합·F1 기준값·CodeQL 위협 모델: **결정 완료(2026-10-03)** — 위 결정 표 참조. 오탐 65건은 사용자가 처리했고 평가 측이 64건 닫힘·**`#103` 1건 열림**을 확인했다(`GITHUB_ACCESS.md` 9절). 남은 사용자 조치는 **`#103` 닫기**와 7차 완료 뒤 **F1 착수 승인**이다.
- **F1 G6·G9 충족(2026-10-04, d73a8ea) — 남은 G8.** **F2 1차 판정(PR #17 7ab5f2c): 서버 1단계 내용 수용(조건부), 화면 미구현·보고서 정정 필요, 병합은 F1 뒤.** → [판정서](../scorecards/f1_gate_verdict.md)
- **F1 G8 미충족(2026-10-04, Codex 감사 d73a8ea): P1·P2 → [TK-59](TK-59_f1_ai_findings_unreachable_and_category_api_403.md), 보호 시험 T2r·T6a 신설, 병합 보류.**
- **F1 병합(2026-10-04, PR #13 4afb29a → Steve 7f5399f): G1~G10 충족, Codex 재감사 통과.** 다음: F2(PR #17) base 전환 뒤 판정.
- **F2 2차 판정(2026-10-05, PR #17 158d6d4): 불승인 → [TK-60](TK-60_f2_row_workflow_broken_and_workflow_controls_lost.md)** (행 안 상태 저장 거짓 성공, 기존 필터·일괄 검토 선택 회귀, 우선순위·담당자 조작 없음). CI 실패 1(T2r)은 평가 측 시험 대기 결함 — 평가 측 PR로 보강.
- **F2 3차 판정(2026-10-05, b7dfb0a): 불승인(잔여 2) — 복수 finding 행 저장이 다른 finding의 검토 기록을 덮어씀(평가 측 지시 오류, TK-60 7절에서 정정), push CI 시험 이름 변경 감지.**
- **PR #20 병합(2026-10-05, Steve e45772b): T2r 보강이 Steve에 들어갔다.** PR #17은 Steve를 병합 커밋으로 받으면 T2r 대기 실패가 없어진다(전달문 (9) [B] 3).
- **F2 4차 판정(2026-10-05, 5dca58c): 내용 수용.** 병합은 push 실행 '점수 하락 게이트' 거짓 실패(시험 이름 복원 지시로 생김)로 막혀 있다 — 판정서 'F2 4차 판정'. 평가 측 과제: `check_test_edits.py` push 비교 보완.
- **F2 병합(2026-10-05, PR #17 → Steve 8b70497).** 다음: 평가 측이 FT 보호 시험 T10·T11을 고정한 뒤 FT 지시서를 낸다.
- **FT 준비(2026-10-05):** 보호 시험 T10·T11 고정(`tests/acceptance/test_ft_protected.py`), [FT 지시서](PROMPT_FOR_FT.md)(1단계 설계 보충). 사전 점검: FT 모듈 관련 기존 시험 669 통과, `resolve_statute` fail-closed 시험과의 충돌은 범위 한정으로 해소.
- **릴리스 후보 8b70497(F1·F2) 측정(2026-10-05): `verify_all` 종료 0, 고정 81.7/79.2/0, 필수 보장 세트 기존과 같음, 버전 상향 없음.** 남은 것: 봉인 시험(사용자), 릴리스 PR.
- **릴리스 F1·F2(2026-10-05): PR #23 병합, `main` 67a87ba, 0.10.0 유지.** 남은 것: 태그 `release-20261005`, 배포 확인, 온라인 점검.
- **배포 직후 온라인 점검(67a87ba): 19/23, 새 실패 0.** 화면 배치 보고 → [TK-61](TK-61_review_table_whitespace_and_finding_list_layout.md)(표 공백, 세부 항목 위·아래 배치 권고).
- **봉인 세트 형식 안내서(2026-10-05):** [SEALED_SET_FORMAT_GUIDE](SEALED_SET_FORMAT_GUIDE.md). 작성은 Codex 별도 세션(저장소 미연결, 사용자 결정). 탐지 기능(F1·F2·FT)은 Antigravity가 구현했으므로 출제를 분리한다. 평가 측 확인: 자체 점검 스크립트가 홀드아웃 사본에서 오류 0을 냈고, 일부러 넣은 결함 5종을 모두 잡았다. 8절 채점 명령을 홀드아웃 사본으로 실행해 홀드아웃과 같은 79.2를 얻었다(d1d5761, 오프라인). 이 안내서는 구현 측 통합 전달문에 넣지 않는다(구현 세션과 분리).
- **FT 설계 보충(PR #24 bce4bbf, 2026-10-06): 보완 요구.** 없는 rule_id 기재, 목 정규식 오인식, 같은 시행일 버전 순서 의존, 추가 대조군 없음. 평가 측 결정: `TEMPORAL.REVIEW_NEEDED` 재사용. **TK-61(PR #26 df6571c): 수용**(열 비율 10/25/25/40%, 최대 행 높이 2486 → 863px, 브라우저 시험 150 passed). 전달문 (15).
- **FT 설계 보충 개정 1(PR #24 ffe5d47, 2026-10-06): 조건부 승인.** 구현 조건 2건(목 글자 명시 집합, 예외 문구 파싱 금지). 전달문 (16): PR #24 병합 뒤 구현 착수.
- **FT 구현(PR #27 ca0067b, 2026-10-06): 불승인.** [TK-62](TK-62_ft_subitem_absence_forced_contradiction.md)(P1: 목 단위 경로가 판본 대비 없이 CONTRADICTED를 만들어 새 A등급 오탐). 전달문 (17). 사용자 결정: TK-61만 먼저 배포(후보 c206386).
- **FT 보완(PR #27 ed8d7d1, 2026-10-07): 내용 수용**(TK-62 해소, 승격 85e6378, `verify_all` 종료 0). 병합은 #28(TK-61 릴리스) 뒤 평가 측 PR로 한다. 전달문 (18).
- **F3 지시서(2026-10-07):** [PROMPT_FOR_F3](PROMPT_FOR_F3.md) — 1단계 설계 보충(`requests/43_f3_design.md`). 평가 측이 회신 전에 T6~T9·요청 본문 스키마 시험을 고정한다. 착수 조건 (i) 연락처·주민등록번호 게이트 재측정, (ii) T9 등 평가 측 시험, (iii) F2·TK-29 충족. RAG-2는 D4와 맞지 않아 수용 기준에서 제외. F3 릴리스에는 새 봉인 세트가 필요하다. 전달문 (19).
- **F3 릴리스(2026-10-08, `main` 9192b44, 0.10.0 유지).** 봉인 `sealed_20261008` 운영본·후보 같음. 배포 직후 온라인 서면9 19/23(새 실패 0). F3 목표 RAG-1 미달 → [TK-63](TK-63_f3_claim_budget_document_order.md)(P2: 주장 단위 대조가 문서 앞 10개 주장만 고름). 전달문 (26).
- **TK-63 개정 1(2026-10-08, 사용자 결정 (나)안):** 선별 규칙(인용 연결 → 법률효과·요건 → 사실 → 그 밖 → 형식 문장) + 예산형 상한(설정값: 개수 30·시간 240초·비용 $1.00). 승인 설계 5.2를 바꾸므로 구현 PR에서 설계 개정 절을 함께 낸다. 평가 측 보호 시험 하네스는 상한 10으로 고정했다(사전 점검 42 passed). 전달문 (27).
- **TK-63 구현(PR #40 a9de019, 2026-10-08): 불승인(소규모 3)** — 기존 시험 삭제 복원, `budget` 키 4개로 정리, 보고 정확성. 전달문 (28). TK-63 릴리스용 봉인 세트 프롬프트: [PROMPT_FOR_CODEX_SEALED_SET_TK63](PROMPT_FOR_CODEX_SEALED_SET_TK63.md).
- **TK-63 보완(PR #40 57231c2, 2026-10-08): 수용**(`verify_all` 종료 0). PR #40을 Steve에 바로 병합한다. 전달문 (29).
- **TK-64(2026-10-09, P2·기존 결함):** 릴리스용 봉인 세트 프롬프트: [PROMPT_FOR_CODEX_SEALED_SET_TK64](PROMPT_FOR_CODEX_SEALED_SET_TK64.md). [본문 서술 문단을 증거 목록 행으로 읽어 '같은 호증 번호 중복' A등급 오탐](TK-64_exhibit_list_prose_rows_duplicate_number.md). 은퇴 세트 `sealed_20261008b`에서 발견. 전달문 (30). **개정 1(2026-10-09, 평가 측 자기 정정):** 본문 행 삭제 기준 철회·제목 문구 정정, 구현 PR #43 1276504 불승인(소규모 2), 전달문 (33). **보완 f1ba73c 수용(2026-10-09)**: 은퇴 b 29.6/0. Steve 34e1c9a, 봉인 sealed_20261009 기준 충족(오탐 3 → 1, A 2 → 0), 버전 0.11.0 판정, 전달문 (35) 버전 커밋.
- **TK-65(2026-10-09, P2·기능 목표 미달):** [F3 주장 단위 대조에서 인용 주장 응답이 형식 검사에 걸림 — 응답 최상위 형식 명시](TK-65_f3_claim_response_envelope_schema.md). TK-63 배포 직후 온라인 점검에서 발견. 전달문 (31). **구현 PR #44 a54cf40 수용(2026-10-09)**, 릴리스 `main` 4c18528, 배포 직후 온라인 서면9 20/23(RAG-1 통과, 형식 실패 6 → 0).
- **TK-66(2026-10-09, P1·보안 회귀, 릴리스 차단):** [TK-64 목록 제목 정규식의 지수적 백트래킹(ReDoS)](TK-66_exhibit_section_head_regex_redos.md). 릴리스 PR #49 CodeQL에서 발견. 전달문 (37). **구현 PR #50 741b739 수용(2026-10-09).**
- **결정 사안 6건(2026-10-09, 사용자 '1~6 권고대로'):** ① 온라인 서면9 명세 규칙 2판 — RAG-1을 주장 원문(`claim_id`) 기준으로도 인정(보관 보고서 8건 재채점 시 a8b2a7e만 19 → 20). ② [TK-67](TK-67_exhibit_numbering_gap_section_scope.md) 발행. ③ 주장 단계 시간 예산 240초 유지·관찰. ④ [TK-68](TK-68_rag_document_batch_output_truncation.md) 발행(P3). ⑤ FT 후속 → [TK-69](TK-69_ft_subitem_middle_dot_list.md), TK-67과 같은 구현 묶음. ⑥ 태그 표기 `v.<버전>`(RELEASE_PROCEDURE 3절 5). 전달문 Antigravity (39).
- **TK-67(2026-10-09, P3·오탐, 기존 결함):** [증거번호 결번 판정이 목록 밖 본문 언급과 첫 번호 앞까지 셈](TK-67_exhibit_numbering_gap_section_scope.md). 은퇴 `sealed_20261009` 대조군 오탐 원인. 사전 점검 36.2/0, 은퇴 a·b·고정 같음.
- **TK-68(2026-10-09, P3·효율):** [문서 단위 Drive 대조 첫 묶음 출력 잘림](TK-68_rag_document_batch_output_truncation.md). 온라인 보고서 8건 모두 재현.
- **TK-69(2026-10-09, P3):** [FT 목 인용 가운뎃점·여러 목 미인식 + 목 인식 정규식 공백 모호성(제곱 시간)](TK-69_ft_subitem_middle_dot_list.md).
- **장기 미해결 과제 Codex 인계(2026-10-09, 사용자 결정):** [NEXT_FOR_CODEX](NEXT_FOR_CODEX.md) — TK-58(PII-K6) 재인계·TK-24(LEG-2, 설계 메모 먼저)·CodeQL 로그 경보. 두 티켓에 재점검 개정 1. **RAG-2는 사용자 결정 D4(참고 의견 승격 없음)와 충돌해 넘기지 않음 — D4 재검토 여부 사용자 결정 대기.**
- **D4 재검토 결정(2026-10-09, 사용자 '단계적 조건부 승격'):** ① 평가 측 비공개 온라인 측정 세트 `rag_contradiction_set_20261009`(가상 참고자료 3·합성 서면 3, 양성 6·대조 6, 지문 6dd780efc2dbd686 → 파일명 한글화 2판 2dc61fb15bf67e83, 저장소 밖 보관)로 '모순' 의견의 정밀도를 잰다. ② 대조군 '모순' 의견 0이면 조건부 승격 티켓을 낸다 — CONTRADICTS + 원문 인용 검증 통과 + 주장 단위 의견만 `FACT_CONTRADICTION`·SUSPICIOUS·낮은 심각도·C등급, '내부 자료 대조·법적 구속력 미판단' 표기. RAG-2는 승격 뒤 판정. 그때까지 D4는 유지된다.
- **D4 1단계 측정 충족 → TK-70(2026-10-09):** 비공개 온라인 세트 2판(지문 2dc61fb15bf67e83) a8b2a7e 12/12 — 대조군 '모순' 0, 양성 6/6, '모순' 의견 11건 모두 정답. [TK-70](TK-70_rag_contradiction_conditional_promotion.md) 발행(조건부 승격: LOW·C·SUSPICIOUS, 지수·게이트 제외, 기본 켬). 전달문 Antigravity (40) [D]. 승격 채점 명세(24항목) 현재 18/24(승격 6건 미구현이 정상).
- **Codex 인계 판정(2026-10-09):** TK-58 [PR #52](https://github.com/stevelee0119/verify_ACAS_LAW/pull/52) 수용·병합(Steve 3daf7b6) · TK-24 [PR #53](https://github.com/stevelee0119/verify_ACAS_LAW/pull/53) 설계 승인(보완 5, 구현 대기) · CodeQL 로그 [PR #54](https://github.com/stevelee0119/verify_ACAS_LAW/pull/54) 수용·병합(Steve 5d7ac6c).
- **TK-71(2026-10-09, P2·기능 공백):** [표 형식 표준판례 참고자료 미활용](TK-71_structured_case_table_reference.md) — 사용자 Drive 표준판례 표(3,555행)가 문자 상한 초과로 색인되지 않음(사유 'PARSE_FAILED'로 가려짐), 상한을 풀어도 추출 132초, 행 구조 소실, 사건번호 조회·사건정보 대조·요지 라우팅 없음. Codex 전달문 (4) [D].
- **TK-72(2026-10-10, P2·가용성, 기존 결함):** [인용 추출기 제곱 시간](TK-72_citation_extractor_quadratic_time.md). TK-69 통합 뒤 Antigravity.
- **TK-74(2026-10-10, P2·기능 공백):** [표준판례 표가 문서 이름 선별을 통과하지 못하면 색인되지 않음](TK-74_case_table_not_indexed_without_name_match.md). 0.12.0 배포 직후 온라인 점검(21/23)에서 발견. 배정은 사용자 결정 대기.
- **당시 배포 대기 현황(2026-10-10, 운영 0.12.0 main 9c1b218 기준):** 수용·통합 완료 TK-24·TK-69(PR #67, CI 대기) · 보완/구현 대기 TK-70(#60)·TK-43(#62 e4867e7 내용 수용·통합 대기)·TK-74·TK-72(#67 병합 뒤)·TK-56·TK-44/49(평가 측 조건 2 선행)·TK-45(#67 병합 뒤) · 사전 점검 대기 TK-73 · 알려진 미해결(배정 없음) TK-55 3절·TK-57 잔여(intl_paren 1/54). 다음 릴리스 권고: #67 + TK-70 수용분으로 후보 확정 → `verify_all` 전체·개인정보 필수 게이트 → 새 봉인 세트(격리 세션 작성) → 버전 판정·커밋 → 릴리스 PR → 배포 확인·태그·온라인 점검.

- **TK-43 개정 1(PR #62 e4867e7) 내용 수용(2026-10-10, Codex 별도 평가 세션):** 개정 기준 충족. 실제 연락처 가입자 자리 마스킹 확인으로 기존 국가코드 범위 판정을 적용했고, 라우터 재현은 중복 래퍼를 제거해 16/16 일치했다. 통합 SHA 검증·CI와 사용자 병합 승인은 별도이며 다음 릴리스 새 봉인 시험을 유지한다. 근거: [판정서](../scorecards/f1_gate_verdict.md)의 「TK-43 개정 1 보완 재판정」.

- **TK-74 설계(PR #68 c6d0f19) 조건부 승인(2026-10-10, Codex 평가):** 기존 격리 추출 유지, 부분·미검토 상태와 부재 구분, 실제 선별 동기화→문서 검토 시험 조건. 구현 착수 가능, 최종 수용 별도. 통합 전달문 Antigravity (53) [G], 판정서 TK-74 설계 판정.

- **TK-70 보완(PR #60 db21f19) 내용 수용(2026-10-10, Codex 평가):** 실제 pipeline 시험으로 이전 불승인 사유 해소. 최신 통합 SHA 필수 CI·사용자 병합 승인 별도, 배포 후 비공개 온라인 v2·서면9 다회 점검. T6 설명만 D4 개정으로 정리(실행 코드 불변). 통합 전달문 Antigravity (53) [D].
- **당시 배포 대기 현황(2026-10-10, 운영 0.12.0 main 9c1b218 기준):** 수용·통합 완료 TK-24·TK-69(PR #67, CI 대기) · 보완/구현 대기 TK-70(#60)·TK-43(#62, Codex 평가 세션 판정)·TK-74·TK-72(#67 병합 뒤)·TK-56·TK-44/49(평가 측 조건 2 선행)·TK-45(#67 병합 뒤) · 사전 점검 대기 TK-73 · 알려진 미해결(배정 없음) TK-55 3절·TK-57 잔여(intl_paren 1/54). 다음 릴리스 권고: #67 + TK-70 수용분으로 후보 확정 → `verify_all` 전체·개인정보 필수 게이트 → 새 봉인 세트(격리 세션 작성) → 버전 판정·커밋 → 릴리스 PR → 배포 확인·태그·온라인 점검.
- **당시 배포 대기 현황 갱신(2026-10-10):** Steve 반영 TK-24·TK-69(#67) · 수용·통합 PR TK-43 · 판정 대기 TK-70(#60 db21f19, Codex 평가 세션) · 설계 회신 대기 TK-74(#68, Codex 평가 세션) · 착수 가능 TK-72(Antigravity)·TK-56(Codex) · 대기 TK-44/49·TK-45 · 사전 점검 대기 TK-73 · 알려진 미해결 TK-55 3절·TK-57 잔여. 다음 릴리스 권고 구성: TK-24·TK-69·TK-43·TK-70(수용 시) → 탐지·개인정보 엔진 변경으로 새 봉인 시험 필요.

- **평가 역할 전환 재확인(2026-10-10, 사용자 지시):** Codex 평가 세션이 기존 claude-code의 측정·판정·회신·수용 SHA 통합·통합 검증·평가 PR·릴리스 준비 전체를 승계한다. 구현 세션 분리·제품 직접 수정 금지·사용자 최종 승인 유지. TK-70 수용 SHA db21f19를 b92100d로 통합했고 PR #69를 갱신한다. 전달문 Antigravity (54)·Codex (16). 과거 claude-code 측정 기록은 역사적 출처로 보존.

- **TK-43·TK-70 Codex 평가 통합(PR #69, e10a335):** 통합 검증·보호 지표 유지 확인, full 원본의 도구 환경 실패 1과 환경 보완 재검증을 분리 기록. 검증 e10a335 필수 CI 모두 성공·통합 내용 수용. 최종 기록 SHA의 필수 CI는 PR #69 체크 상태로 확인하고 성공 뒤 사용자 병합 승인 단계로 넘긴다. 현재 평가·통합·PR·릴리스 준비 담당은 Codex 평가 세션.
- **측정 체계 추가(2026-10-10, 사용자 지시):** 고정 비공개 벤치마크([FIXED_BENCHMARK](../scorecards/FIXED_BENCHMARK.md), 작성 프롬프트 [PROMPT_FOR_CODEX_FIXED_BENCHMARK](PROMPT_FOR_CODEX_FIXED_BENCHMARK.md), `scripts/fixed_benchmark.py`)와 티켓 지표([TICKET_METRICS](../scorecards/TICKET_METRICS.md), 등록부 `ticket_registry.json`, `scripts/ticket_metrics.py`). 초기값: 티켓 74건·회귀 24건·미해결 13건, 주별 회귀 비율 W40 36% → W41 20%.

- **TK-75(2026-10-10 사용자 결정):** [Claude for Legal 한국법 검토 워크플로우](TK-75_claude_legal_korean_workflow.md). 다음 릴리스 포함, TK-72 수용 완료 후 별도 Codex 구현.  실제 모델 A/B 품질·근거·보안·예산 수용 후 활성화.
