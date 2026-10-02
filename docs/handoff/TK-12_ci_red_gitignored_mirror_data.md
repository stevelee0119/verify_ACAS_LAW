# TK-12 CI 빨간불: 두 시험이 .gitignore된 미러 데이터에 의존
- 유형: 시험 설계(환경 의존) · 기준 커밋: 4ad64a7 · 작성: evaluator 2026-09-30

## 증상·증거
- main의 `CI` 워크플로(`테스트 (SQLite + PostgreSQL/pgvector + Redis)` 작업의 `pytest -q` 단계)가 4ad64a7에서 실패한다([실행 기록](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/36683167780)). 실패는 정확히 두 시험이다.
  - `tests/test_ground_truth_prepared_brief.py::test_precedent_and_regulation_existence` — `LocalLegalMirror().find_case("2018도15313")`가 `None`
  - `tests/test_ground_truth_prepared_brief.py::test_temporal_retroactive_application_review` — 부정경쟁방지법 제2조 버전이 없어 `review_temporal_application`이 `None`
- 원인: 두 시험은 `config/legal_mirror/*.json`의 판례·조문 자료를 전제로 한다. 이 파일들은 `.gitignore`(17행 `config/legal_mirror/*.json`)에 들어 있어 저장소에는 `README.md`만 있다. 작성자 PC에서는 통과하고 깨끗한 복제본·CI에서는 실패한다. 시험이 들어온 커밋은 c287b12(9/29 22:17)다. 확인한 실행 aa93276·73357d8·4ad64a7이 모두 실패했고 그 사이 커밋의 실행은 취소되었다.
- 평가 측 재현: 깨끗한 복제본(이 세션)에서 같은 두 시험이 실패하고, 4ad64a7의 미러 자동 보강(TK-10)으로도 해결되지 않았다.

## 수용 기준
- CI `pytest -q`가 통과한다. **시험을 건너뛰거나(skip) 기대값을 낮추어 통과시키지 않는다.**
- 두 시험이 쓰는 자료를 저장소 안 시험 자료(`tests/fixtures/` 아래, 전용 미러 폴더)로 두고, 시험이 `LocalLegalMirror(root=<그 폴더>)`로 읽게 한다. 자료는 국가법령정보센터 등 **공식 원문에서 확인한 것만** 쓴다(지어내지 않는다). 2018도15313 판결의 존재, 부정경쟁방지법 제2조 제1호 카목의 신설일(시험이 기대하는 2022-04-20)을 출처 URL과 함께 적는다.
- 시험 자료 폴더는 보호 경로(`tests/fixtures/`)이므로 구현 에이전트는 이 티켓에 자료를 첨부해 평가 에이전트에게 반영을 요청한다(`docs/AGENT_ROLES.md`).
- 해결 전까지 main의 `CI`는 빨간 상태다. 이 티켓과 무관한 변경의 병합 가부 판단에는 `점수 게이트`(`score-gate`)와 `tests/acceptance`를 쓴다.

## 경과(2026-10-01, de243cc)
- 구현 에이전트가 시험 쪽(`MIRROR_ROOT`)을 고치고 자료를 직접 적어 `requests/06_mirror_fixture.md`로 올렸다. **자료를 반영하지 않았다.** 조번호 오류(근로기준법 제107조→실제 제109조)와 출처 불명 URL이 확인되어서다. 자세한 근거는 [TK-21](TK-21_process_round2.md) 1절.
- 해결 경로(사용자 결정): (a) 사용자의 로컬 `config/legal_mirror/*.json` 제공 (b) 평가 에이전트가 공식 원문에서 구성(판례 2018도15313은 공식 확인 필요).
- 그때까지 main `CI`는 빨갛다(이 두 시험 + TK-19의 4건).

## 사용자 결정(2026-10-02) — **평가 측이 공식 원문으로 구성**
해결 경로 (b)를 사용자가 선택했다(로컬 파일 제공·시험 제외는 선택하지 않음). 평가 측이 국가법령정보센터 등 공식 원문에서 확인되는 것만 `tests/fixtures/` 아래 전용 미러 폴더로 만든다. 판례 2018도15313의 실재와 부정경쟁방지법 제2조 버전은 공식 원문 확인이 선행되어야 하며, 확인하지 못한 항목은 지어내지 않고 \"확인 못 함\"으로 보고한다. 구현 측은 자료를 올리지 않는다(요청 06 반려 유지). 이 자료가 들어가면 `main`의 `CI`가 초록이 되는지 `workflow_dispatch`로 확인한 뒤 필수 확인 추가를 사용자에게 요청한다.

## 평가 측 작업 결과(2026-10-02) — 공식 원문 구성, **일부만 해소**
자료: `tests/fixtures/prepared_brief_mirror/laws.json`(5항목)·`SOURCES.md`(출처·한계). 시험: `tests/acceptance/test_prepared_brief_mirror_official.py`(6건 통과). 원 시험 `tests/test_ground_truth_prepared_brief.py`는 **2건 모두 아직 실패**한다(`MIRROR_ROOT`가 이 폴더를 가리킴).

| 확인 항목 | 결과 | 근거 |
|---|---|---|
| 부경법 제14조의2 제6항 3배→5배(행위일 2020-05-12) | **공식 원문으로 확인됨** — 3배(시행 2019. 7. 9.~2024. 8. 20.), 5배(시행 2024. 8. 21.~) | 연혁 4개 시행본([206596](https://www.law.go.kr/lsInfoP.do?lsiSeq=206596)·[222483](https://www.law.go.kr/lsInfoP.do?lsiSeq=222483)·[224623](https://www.law.go.kr/lsInfoP.do?lsiSeq=224623)·현행 [277201](https://www.law.go.kr/LSW/lsSideInfoP.do?lsiSeq=277201&joNo=0014&joBrNo=02&docCls=jo&urlMode=lsScJoRltInfoR)). 이 부분의 판단(`TEMPORAL.CURRENT_ONLY_MATCH`, HIGH, `RETROACTIVE_APPLICATION_ERROR`)은 현재 엔진이 정확히 낸다 |
| 제2조 제1호 카목 "2022-04-20 신설"·"2020-05-12 부존재" | **원 시험의 전제가 공식 원문과 다름** | 2019. 7. 9. 시행본에 **카목(성과 도용)이 이미 있었다.** 2021. 12. 7. 개정(법률 제18548호)이 "카목을 파목으로 하고 같은 호에 카목(데이터 부정사용)·타목을 신설"했다. 시험의 `claim_text`(성과 도용 문언)는 2020년에도 카목이었다. 대법원도 2020. 3. 26.자 2019마6525 결정에서 "(카)목의 성과물 도용"을 판단했다(SOURCES.md) |
| 판례 대법원 2018도15313 | **확인 못 함** | 국가법령정보센터·케이스노트·대법원 판례속보 검색에서 이 번호가 나오지 않았다(비슷한 2019도15313은 강제추행 사건). 다만 국가법령정보센터 판례 검색은 실재 사건번호도 0건으로 돌려줘 **부존재의 근거는 아니다.** 그래서 `cases.json`을 만들지 않았다 |
| 가상 판례 2023다284109 | 미러에 없음(시험 기대와 일치) | `test_cases_file_if_present_has_only_officially_linked_real_cases` |

**원 시험이 계속 실패하는 이유와 하지 않은 일.** (1) 2018도15313: 존재 확인 전에는 넣을 수 없다. (2) 카목 단계: 공식 연혁대로 제2조를 넣으면 `review_temporal_application`이 `None`을 낸다(엔진은 조 단위 버전만 보고 **목 단위 신설·이동은 보지 않는다**; 제2조는 2019년에도 있었으므로 "행위 당시 부존재" 경로에 들어가지 않는다). 시험을 통과시키려고 제2조의 이전 시행본을 빼거나 날짜를 바꾸는 것은 거짓 자료이므로 하지 않았다. 시험의 기대값을 낮추거나 건너뛰지도 않았다.

## 사용자 결정 필요(2026-10-02, 평가 측 권고 포함)
1. **2018도15313(실재 판례 단계)** — 권고: (a) 이 사건번호의 출처(판결문·선고일·사건명)를 사용자가 제공하면 평가 측이 공식 확인 후 `cases.json`에 추가한다. 제공이 어려우면 (b) 같은 단계에 공식 확인이 끝난 다른 실재 판례로 바꾼다(평가 측이 후보를 확인해 제안한다). 확인되지 않은 번호를 "실재"로 두는 선택지는 없다.
2. **카목 단계(원 시험 3-1)** — 권고: 정답지가 의도한 오류가 무엇인지 사용자가 확인한다. 2020년 행위에 **데이터 부정사용(현행 카목)**을 인용한 서면이라면, 시험의 `claim_text`를 그 문언으로 고치고, 엔진이 목 단위 신설 시점을 보지 못하는 점은 별도 결함 티켓으로 올려 해당 단계를 strict xfail로 둔다. **성과 도용 문언을 카목으로 인용한** 서면이라면 2020년에도 맞는 인용이므로 이 단계의 "오류" 기대를 거두어야 한다.
3. 결정 전까지 main `CI`는 이 두 시험 때문에 빨갛다(필수 확인은 `점수 하락 게이트`만이므로 병합에는 영향 없음).

## 사용자 결정(2026-10-03)과 해소
- **2018도15313 → 교체.** 사용자가 공식 데이터베이스에서도 확인되지 않음을 확인하고 다른 판례로 바꾸기로 했다. 평가 측이 국가법령정보센터 판례정보로 확인된 **대법원 2022. 10. 14. 선고 2020다268807 판결**([precSeq=237643](https://www.law.go.kr/LSW/precInfoP.do?precSeq=237643), 구 부경법 제2조 제1호 (카)목 = 현행 (파)목)을 `tests/fixtures/prepared_brief_mirror/cases.json`에 넣고 원 시험의 사건번호를 바꿨다. 판결요지는 해당 페이지에 없어 넣지 않았다. 2018도15313과 가상 사건 2023다284109는 미러에 있으면 시험이 실패한다(`test_cases_are_officially_linked_and_unverified_numbers_are_absent`).
- **카목 단계.** 사용자 확인: 문제지·정답지를 작성한 모델(Gemini Spark)의 의도를 정확히 알 수 없다. 평가 측은 정답지의 추정 의도 대신 **공식 원문으로 성립하는 형태**로 정정했다. (1) 원 시험 3-1: "성과 도용 문언의 카목 인용을 2020. 5. 12. 행위에 적용하면 HIGH"라는 기대는 공식 연혁과 맞지 않아 "오류로 표시하지 않는다"로 바꿨다. (2) 신설된 카목(데이터 부정사용)을 2020년 행위에 인용하는 경우는 현재 엔진이 검출하지 못하므로 `test_new_data_ka_cited_for_2020_act_is_flagged`를 **strict xfail**로 두고 [TK-34](TK-34_item_level_temporal_review.md)를 올렸다(6차 범위 밖). 그 시험의 청구 문언은 평가 측이 공식 원문을 요약해 지은 것이다. 문제지 원문을 확보하면 이 정정이 의도와 맞는지 다시 대조한다.
- **한 일의 성격.** 시험을 건너뛰거나 기대값을 낮춰 통과시킨 것이 아니다. 공식 원문과 맞지 않는 기대를 거두고, 맞는 기대(제14조의2 3배→5배 HIGH, 카목 성과 도용 오탐 없음)를 유지했으며, 엔진이 못 하는 검출은 xfail로 눈에 보이게 남겼다.
- **결과(로컬, 오프라인):** `tests/test_ground_truth_prepared_brief.py` 6건 통과, `tests/acceptance` 541 통과·xfail 26(기존 25 + TK-34), 전체 시험(`--ignore=tests/acceptance`) 3,007 통과·13 건너뜀·**실패 1건**(`test_v5_ocr_dates::test_rotated_scan_page_impossible_date_is_found`, 환경 사유 TK-15; 이전 3건에서 TK-12 2건 해소; Linux·python 3.11·오프라인, 373초). CI 초록 여부는 `workflow_dispatch` 실행으로 확인하며, 확인되면 `CI`를 `main` 필수 확인에 추가할지 사용자에게 묻는다(사용자 결정 2026-10-02의 후속 절차).

## CI 초록 확인(2026-10-02, `workflow_dispatch`)
[`CI` run 263](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/37074643039)(브랜치 `Steve_ACASiaLAW`, 커밋 f82e679): job `Docker OCR readiness` **success**, job `테스트 (SQLite + PostgreSQL/pgvector + Redis)` **success**(단계별: SQLite + 인프로세스 Worker 6분 36초 success, PostgreSQL/pgvector + Celery 브로커 6분 7초 success, 나머지 단계 모두 success). 이 실행 뒤 커밋(437a5d0)은 문서 변경뿐이다. **이 티켓은 해소로 닫는다.** `CI`를 `main` 필수 확인에 추가하는 것은 사용자 승인 사항이며 아직 하지 않았다.

## `CI`를 `main` 필수 확인에 추가 — 사용자 승인(2026-10-03), 설정은 사용자 조치 대기
- 승인: 사용자가 `CI`를 `main` 필수 확인에 추가하라고 승인했다. 평가 세션이 `gh api`로 `main` 보호 설정을 읽고 쓰려 했으나 **HTTP 403**(`Resource not accessible by integration`)이라 바꾸지 못했다(이 세션의 GitHub 연동에 저장소 관리 권한이 없다). 설정을 바꾸지 않았다.
- 읽은 현재 값(`GET branches/main`, 2026-10-02): 보호 켜짐, 필수 확인 `점수 하락 게이트`만, 적용 수준 `non_admins`(관리자는 예외).
- 사용자 조치(관리자 권한 필요), 둘 중 하나:
  1. 저장소 Settings → Branches → `main` 보호 규칙 편집 → "Require status checks to pass before merging"에서 `테스트 (SQLite + PostgreSQL/pgvector + Redis)` 검색해 추가(최근 실행 기록이 있어 목록에 나온다). 다른 항목(최신 상태 유지 끔 등)은 그대로 둔다.
  2. 관리자 토큰이 있는 곳에서: `echo '["테스트 (SQLite + PostgreSQL/pgvector + Redis)"]' | gh api -X POST repos/stevelee0119/verify_ACAS_LAW/branches/main/protection/required_status_checks/contexts --input -` (기존 필수 확인을 유지하고 이 항목만 더한다).
- 유의: `CI`는 `main`·`claude/**`·`codex/**` 브랜치 푸시와 PR, 수동 실행에서만 돈다. 평가 브랜치 `Steve_ACASiaLAW`나 구현 브랜치 푸시에서는 돌지 않으므로, 필수 확인이 걸린 `main`으로 병합하려면 PR을 열어 `CI`가 PR에서 실행되어야 한다(사용자가 PR을 요청할 때). Docker OCR readiness는 이 승인에 포함되지 않았다.

### 반영 확인(2026-10-03)
사용자가 웹 설정으로 추가했다고 알려 왔고, 평가 세션이 `gh api repos/stevelee0119/verify_ACAS_LAW/branches/main`을 읽어 확인했다: `protected: true`, 필수 확인 contexts = [`점수 하락 게이트`, `테스트 (SQLite + PostgreSQL/pgvector + Redis)`], 적용 수준 `non_admins`(변경 없음). **확인하지 못한 것:** 강제 푸시·삭제 금지, PR 필수·최신 유지 끔 등 나머지 보호 옵션은 이 세션에 관리 권한이 없어(`GET .../protection` 403) 읽지 못했다. 위 "사용자 조치 대기" 문단은 이 확인으로 완료되었다.

### 관리자 포함 적용 켬 — 반영 확인(2026-10-03)
사용자가 `Do not allow bypassing the above settings`를 켰다고 알려 왔고, 평가 세션이 `gh api repos/stevelee0119/verify_ACAS_LAW/branches/main`을 읽어 확인했다: 필수 확인 contexts = [`점수 하락 게이트`, `테스트 (SQLite + PostgreSQL/pgvector + Redis)`] 유지, 적용 수준 **`non_admins` → `everyone`**. 의미: 주인 계정(구현·평가 에이전트가 푸시에 쓰는 계정)도 두 필수 확인이 초록이 아닌 커밋을 `main`에 올리거나 병합할 수 없다. **확인하지 못한 것:** 강제 푸시·삭제 금지, PR 필수 끔·최신 유지 끔 등 나머지 옵션은 이 세션에 관리 권한이 없어(403) 읽지 못했다. 되돌리려면 같은 체크를 해제한다.
