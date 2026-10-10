# TK-74 설계 메모 — 문서 선별 무관 표준판례 표 색인 경로

- 작성: 구현 에이전트 Antigravity, 2026-10-10
- 기준: `Steve_ACASiaLAW` 최신 `6323400`
- 브랜치: `antigravity/tk74-case-table-indexing`
- 상태: 평가 측 조건부 승인 반영 개정판 (구현 진행)

## 1. 문제와 원인

- **증상**: Drive 참고자료 폴더(예: '판례' 하위 폴더)에 표준판례 표(XLSX/CSV)가 있어도, 문서 단위 선별(`metadata_gate`)에서 서면 본문과 파일명 단어를 공유하지 않아 `NAME_PATH_NOT_RELATED`로 제외(`NOT_SELECTED_METADATA`)된다. 배포 등으로 추출기 버전(`drive-text-v5-case-table-resumable`)이 변경되어 캐시가 없는 상태에서는 다운로드조차 되지 않아 `case_rows` 색인이 완전히 누락된다.
- **결과**: 서면이 대법원 판례를 인용하더라도 `has_case_tables()`가 False가 되어 TK-71의 사건번호 정확 조회(`match_case`) 및 판결요지 대조(`search_case_table`)가 동작하지 않는다.
- **원인 (`packages/rag_engine/library.py:294-297`)**: `_sync_files`는 `metadata_gate` 선별 파일(`chosen`)과 로컬 SQLite 캐시가 있는 파일(`cached`)만 다운로드/색인하므로, 문서 선별과 독립적으로 구조화 판례표를 색인하는 경로가 없다.

## 2. 제안 방법

### 2.1 표 후보 식별 (파일명 무관)
- 파일명이나 사건명이 아닌 메타데이터(확장자 `.xlsx`, `.csv` 및 Google Sheet MIME 타입 `application/vnd.google-apps.spreadsheet`, `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, `text/csv`)와 파일 크기(96MB 이내)로 '표 후보(table candidate)'를 자동 감지한다.

### 2.2 색인 시점과 우선순위 (기존 격리 추출 유지 — 평가 측 조건 1)
- `_sync_files` 동기화 루프에서 표 후보는 문서 단위 이름 선별(`metadata_gate`) 통과 여부와 무관하게 색인 검토 대상에 포함한다.
- 동기화 순서(`ordered`):
  1. 캐시가 유효한 기존 표(재사용)
  2. 이전 동기화에서 이어 읽기 진행 중인 표(`continuation` 존재)
  3. 신규 표 후보(스프레드시트)
  4. 문서 선별을 통과한 일반 참고자료 (`chosen is True`)
  5. 미선별 일반 참고자료
- **격리 추출 및 다운로드 통제 준수**: `extract_case_table`을 직접 호출하는 우회 경로를 만들지 않고, 기존 `isolated_extract` 서브프로세스 추출 경로(`self.extractor`)를 그대로 거친다. 표 후보 다운로드 시에도 기존 권한 확인, 리비전 비교, 체크섬 검증, 다운로드 용량 및 시간 예산 검사를 동일하게 거친다.
- 판례표 여부 판별 결과 캐싱 및 격리 (평가 측 보완 반영):
  - Google Sheets(`application/vnd.google-apps.spreadsheet`)는 확장자가 없더라도 `inventory`의 `mimeType` 메타데이터를 보존하여 표 후보 식별에서 누락되지 않도록 한다.
  - 판례표 머리글(`_header_map`)이 확인되면: `case_rows`에 행별로 색인하고 구조화 표로 등록한다.
  - 판례표 머리글이 없는 일반 스프레드시트이고 문서 선별(`gate`)도 되지 않은 경우:
    - 추후 다른 질의에서 해당 문서가 일반 참고자료로 선별(`chosen`)될 때 캐시를 즉시 재사용할 수 있도록, 추출된 원본 `chunks`와 파싱 결과는 SQLite DB(`files`, `chunks`)에 온전히 보존하여 캐시한다.
    - 현재 실행에서는 `entry["status"] = "NOT_A_CASE_TABLE"`로 기록하고, `self.eligible` 등록에서 제외하여 일반 RAG `select()` 검색 대상에서 안전하게 격리한다.
    - 이를 통해 비판례 스프레드시트의 RAG 발췌 격리를 유지하면서도, 질의 변경 재선별 시의 회귀를 완전히 방지한다.

## 3. 예산 통제 및 보안 격리

- **시간 예산**: 매 동기화 실행 시 잔여 시간(`client.remaining() >= 30`초)을 보장한다. 시간 예산 부족 시 `SYNC_BUDGET_EXHAUSTED`로 안전하게 중단하고, 진행 중이던 행 위치까지의 `continuation` 체크포인트를 SQLite `files` 테이블에 원자적으로 저장하여 다음 동기화에서 이어 읽는다.
- **단일 추출 시간**: `extract_case_table` 내부의 25초 제한 및 행당 동적 시간 예측(TK-71)을 유지한다.
- **용량 및 파일 수 예산**: 다운로드 누적 용량(`rag_download_mb`, 단일 96MB) 및 파일 수(`rag_max_files`) 예산에 정상 산입한다.
- **보안 검사 격리**: `AdversarialScanner.scan`을 통한 행 단위 보안 검사를 유지하며, 격리 행 수 상한(`LV_CASE_TABLE_MAX_EXCLUDED_ROWS`, 기본 32) 초과 시 파일 전체 격리(`REFERENCE_QUARANTINED`)를 엄격히 적용한다.

## 4. 상태 값 체계 및 결과/진단 분리 (평가 측 조건 2)

### 4.1 부분·미검토 상태와 완전 부재(`NO_CASE_TABLE`)의 분리
- 예산 중단, 읽기 실패, 보안 격리, 0행 이어 읽기 등은 `NO_CASE_TABLE`로 확정하지 않고 해당 상태와 사유를 구분 기록한다.
- **실제 sync 경로의 추출기 실패/타임아웃 보존 (2차 보완 반영)**:
  - 서면 본문 선별에서 제외된 표 후보(`is_candidate and not chosen`)라도, 추출기가 `partial=True` 및 `REFERENCE_EXTRACT_TIMEOUT` 또는 `REFERENCE_PARSE_FAILED`를 반환하거나 미완료 상태(`continuation` 존재 등)인 경우:
  - `is_non_case_candidate` 분기에서 이를 정상 음성(`NOT_A_CASE_TABLE`)으로 덮어쓰지 않고, 실제 실패 상태(`PARSE_FAILED`, `INDEXED_PARTIAL`, `QUARANTINED`)와 원본 사유를 `inventory` 및 `issues`에 온전히 보존한다.
  - 이를 통해 실제 sync 결과 및 manifest에서 미검토 범위와 사유가 소실되는 문제를 원천 방지한다.
- 여러 표 후보가 존재할 경우 각 후보의 완료/부분/대기 상태를 종합하여 전체 `case_table_status`를 산출한다:
  - 완료된 표가 존재하더라도 격리(`QUARANTINED`), 실패/타임아웃(`PARSE_FAILED`), 대기/진행 중(`INDEXING`), 부분 색인(`INDEXED_PARTIAL`) 후보가 하나라도 공존하면 전체 상태를 `INDEXED`가 아닌 `PARTIAL`로 산출한다.
  - 색인된 표가 0건일 때, 읽기 실패나 타임아웃이 발생한 후보가 있으면 `NO_CASE_TABLE`로 단정하지 않고 `PARTIAL`로 유지하여 미검토 범위 및 사유를 남긴다.
  - 오직 모든 후보가 정상 추출되어 판례표가 아님이 확인된 경우(`NOT_A_CASE_TABLE`)에만 `NO_CASE_TABLE`로 판정한다.
- 부분 색인(`PARTIAL`) 상태에서 사건번호가 조회되지 않은 경우:
  - 기존 `lookup_records`의 `"status": "NOT_IN_REFERENCE"` 계약은 그대로 유지한다.
  - 동시에 `match` 결과에 `scope="PARTIAL_INDEX_RANGE"`, `partial_indexed=True`를 보강하여, '전체 표에 없는 것이 아니라 현재 색인된 범위 내 미조회'임을 결과 및 진단에서 명확히 구분할 수 있게 한다.

### 4.2 서면 검토 결과 (`review`)
- 판례 인용 서면(`citations` 존재)에서 표준판례 표의 상태를 `review["case_table_status"]`에 명시적으로 기록한다:
  - `INDEXED`: 표 색인이 완료되어 사건번호 정확 조회(`match_case`)가 정상 수행됨.
  - `PARTIAL`: 시간/행 상한 등으로 일부 행만 색인됨. 색인된 범위 내에서 조회를 수행하고 부분 색인 상태 및 사유를 남김.
  - `INDEXING`: 표 후보가 발견되어 현재 색인 진행 중임 (`continuation` 존재 또는 예산 대기).
  - `QUARANTINED`: 표 후보가 보안 검사에서 격리됨.
  - `NO_CASE_TABLE`: 참고자료 내에 유효한 표준판례 표가 없음 (모든 후보가 판별 완료되었으나 판례표가 아님).
- 일반 prose 발췌가 0건이어도 표가 색인되어 있으면(`has_case_tables()`), 사건번호 정확 조회가 실행된다 (평가 측 조건 3).

### 4.3 manifest 참고자료 진단 (`summary["diagnostics"]`)
- `diagnostics["case_table_candidates"]`에 표 후보별 상태를 남긴다:
  - `file_id`: 파일 식별자
  - `name`: 파일명
  - `status`: `INDEXED`, `INDEXED_PARTIAL`, `INDEXING`, `NOT_A_CASE_TABLE`, `QUARANTINED`, `SELECTED_PENDING`
  - `indexed_rows`: 색인된 행 수
  - `continuation`: 이어 읽기 진행 여부 (bool)
  - `reason`: 사유 코드 (`TEXT_INDEXED`, `REFERENCE_PARTIALLY_READ`, `NOT_A_CASE_TABLE`, `SYNC_BUDGET_EXHAUSTED` 등)
  - `stats`: 행 처리 통계 (`discovered`, `indexed`, `quarantined`, `errors`, `pending`)

## 5. 일반 발췌 격리 (Prose Retrieval Isolation)

- 표 후보로 색인된 파일은 `case_rows`에 저장되어 사건번호 정확 조회(`match_case`) 및 주장별 판결요지 검색(`search_case_table`)에만 사용된다.
- 일반 문서 단위 대조 묶음(`library.select()`의 prose chunks / `review["sources"]`)에는 표 조각이 주입되지 않는다 (TK-71 5절 범위 엄격 유지).
- 문서 선별(`metadata_gate`)을 통과하지 않고 표 후보로만 색인된 파일은 `select()`의 FTS5 chunk 검색 대상에서 제외한다.

## 6. 시험 계획 (실제 선별 경로 통합 시험 — 평가 측 조건 3)

- **합성 Drive 대역 사용**: 실제 Drive 파일이나 비공개 판례 문구는 저장소에 넣지 않는다.
- **실제 선별 경로 양성 시험**: `sync(query=...)`에서 서면 본문 및 파일명 낱말이 불일치하는 판례표가 주어졌을 때, 메타데이터 게이트에서 제외되더라도 표 후보로 식별되어 색인되고, 인용 문서 검토(`review_references`)까지 연결되어 사건번호가 정확히 조회됨 (일치, 법원/선고일 불일치, 자료 미포함 각 1건 이상). 일반 prose 발췌가 0건이어도 정확 조회가 정상 실행됨을 확인.
- **대조군 시험**: 판례표 머리글이 없는 일반 스프레드시트는 `NOT_A_CASE_TABLE`로 판정되고 RAG chunk로 색인되지 않음. 기존 `test_drive_rag_relevance.py` 불변 통과.
- **예산 및 이어 읽기**: 동기화 시간 예산 도달 시 중단되고, 다음 동기화에서 `continuation`으로 남은 행이 끝까지 색인됨. 추출기 버전 변경 후 첫 실행에서도 재색인됨.
- **표 조각 미주입 검증**: 표가 색인된 상태에서 일반 문서 대조 묶음(`sources`)에 표 행 chunk가 주입되지 않음을 검증.
- **회귀 방지**: TK-71 4절 6 회귀 금지 시험 및 고정 81.7/79.2/0 유지.
