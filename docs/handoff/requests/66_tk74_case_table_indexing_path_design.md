# TK-74 설계 메모 — 문서 선별 무관 표준판례 표 색인 경로

- 작성: 구현 에이전트 Antigravity, 2026-10-10
- 기준: `Steve_ACASiaLAW` 최신 `6323400`
- 브랜치: `antigravity/tk74-case-table-indexing`
- 상태: 설계 메모 전용 (평가 측 승인 전 제품 코드 및 시험 수정 없음)

## 1. 문제와 원인

- **증상**: Drive 참고자료 폴더(예: '판례' 하위 폴더)에 표준판례 표(XLSX/CSV)가 있어도, 문서 단위 선별(`metadata_gate`)에서 서면 본문과 파일명 단어를 공유하지 않아 `NAME_PATH_NOT_RELATED`로 제외(`NOT_SELECTED_METADATA`)된다. 배포 등으로 추출기 버전(`drive-text-v5-case-table-resumable`)이 변경되어 캐시가 없는 상태에서는 다운로드조차 되지 않아 `case_rows` 색인이 완전히 누락된다.
- **결과**: 서면이 대법원 판례를 인용하더라도 `has_case_tables()`가 False가 되어 TK-71의 사건번호 정확 조회(`match_case`) 및 판결요지 대조(`search_case_table`)가 동작하지 않는다.
- **원인 (`packages/rag_engine/library.py:294-297`)**: `_sync_files`는 `metadata_gate` 선별 파일(`chosen`)과 로컬 SQLite 캐시가 있는 파일(`cached`)만 다운로드/색인하므로, 문서 선별과 독립적으로 구조화 판례표를 색인하는 경로가 없다.

## 2. 제안 방법

### 2.1 표 후보 식별 (파일명 무관)
- 파일명이나 사건명이 아닌 메타데이터(확장자 `.xlsx`, `.csv` 및 Google Sheet MIME 타입 `application/vnd.google-apps.spreadsheet`, `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, `text/csv`)와 파일 크기(96MB 이내)로 '표 후보(table candidate)'를 자동 감지한다.

### 2.2 색인 시점과 우선순위
- `_sync_files` 동기화 루프에서 표 후보는 문서 단위 이름 선별(`metadata_gate`) 통과 여부와 무관하게 색인 검토 대상에 포함한다.
- 동기화 순서(`ordered`):
  1. 캐시가 유효한 기존 표(재사용)
  2. 이전 동기화에서 이어 읽기 진행 중인 표(`continuation` 존재)
  3. 신규 표 후보(스프레드시트)
  4. 문서 선별을 통과한 일반 참고자료 (`chosen is True`)
  5. 미선별 일반 참고자료
- 표 후보를 다운로드한 후 `extract_case_table`을 실행한다.
  - 판례표 머리글(`_header_map`)이 확인되면: `case_rows`에 행별로 색인하고 구조화 표로 등록한다.
  - 판례표 머리글이 아닌 일반 스프레드시트이고 문서 선별(`gate`)도 되지 않은 경우: 일반 RAG chunk로 색인하지 않고 `NOT_A_CASE_TABLE` 상태/사유로 캐시하여 이후 불필요한 재다운로드를 방지한다.

## 3. 예산 통제 및 보안 격리

- **시간 예산**: 매 동기화 실행 시 잔여 시간(`client.remaining() >= 30`초)을 보장한다. 시간 예산 부족 시 `SYNC_BUDGET_EXHAUSTED`로 안전하게 중단하고, 진행 중이던 행 위치까지의 `continuation` 체크포인트를 SQLite `files` 테이블에 원자적으로 저장하여 다음 동기화에서 이어 읽는다.
- **단일 추출 시간**: `extract_case_table` 내부의 25초 제한 및 행당 동적 시간 예측(TK-71)을 유지한다.
- **용량 및 파일 수 예산**: 다운로드 누적 용량(`rag_download_mb`, 단일 96MB) 및 파일 수(`rag_max_files`) 예산에 정상 산입한다.
- **보안 검사 격리**: `AdversarialScanner.scan`을 통한 행 단위 보안 검사를 유지하며, 격리 행 수 상한(`LV_CASE_TABLE_MAX_EXCLUDED_ROWS`, 기본 32) 초과 시 파일 전체 격리(`REFERENCE_QUARANTINED`)를 엄격히 적용한다.

## 4. 상태 값 체계 및 결과/진단 분리

### 4.1 서면 검토 결과 (`review`)
- 판례 인용 서면(`citations` 존재)에서 표준판례 표의 상태를 `review["case_table_status"]`에 명시적으로 기록한다:
  - `INDEXED`: 표 색인이 완료되어 사건번호 정확 조회(`match_case`)가 정상 수행됨.
  - `PARTIAL`: 시간/행 상한 등으로 일부 행만 색인됨 (`partial_rows: N`). 색인된 범위 내에서 조회를 수행하고 부분 색인 상태를 표시함.
  - `INDEXING`: 표 후보가 발견되어 현재 색인 진행 중임 (`continuation` 존재, 다음 동기화에서 재개 예정).
  - `NO_CASE_TABLE`: 참고자료 내에 유효한 표준판례 표가 없음.
- 표가 `INDEXED` 또는 `PARTIAL`인 경우에만 `reference_case_matches`에 인용 판례 대조 결과를 기록하고, 표가 없거나 색인 중일 때는 상태 사유를 남겨 판례 부존재와 표 미색인을 명확히 구분한다.

### 4.2 manifest 참고자료 진단 (`summary["diagnostics"]`)
- `diagnostics["case_table_candidates"]`에 표 후보별 상태를 남긴다:
  - `file_id`: 파일 식별자
  - `name`: 파일명
  - `status`: `INDEXED`, `INDEXED_PARTIAL`, `INDEXING`, `NOT_A_CASE_TABLE`, `QUARANTINED`, `BUDGET_EXHAUSTED`
  - `indexed_rows`: 색인된 행 수
  - `continuation`: 이어 읽기 진행 여부 (bool)
  - `reason`: 사유 코드 (`TEXT_INDEXED`, `REFERENCE_PARTIALLY_READ`, `NOT_A_CASE_TABLE`, `SYNC_BUDGET_EXHAUSTED` 등)
  - `stats`: 행 처리 통계 (`discovered`, `indexed`, `quarantined`, `errors`, `pending`)

## 5. 일반 발췌 격리 (Prose Retrieval Isolation)

- 표 후보로 색인된 파일은 `case_rows`에 저장되어 사건번호 정확 조회(`match_case`) 및 주장별 판결요지 검색(`search_case_table`)에만 사용된다.
- 일반 문서 단위 대조 묶음(`library.select()`의 prose chunks / `review["sources"]`)에는 표 조각이 주입되지 않는다 (TK-71 5절 범위 엄격 유지).

## 6. 시험 계획

- **합성 Drive 대역 사용**: 실제 Drive 파일이나 비공개 판례 문구는 저장소에 넣지 않는다.
- **양성 시험**: 서면과 파일명 낱말을 공유하지 않는 판례표가 있을 때, 서면이 인용한 사건번호가 표에서 정확히 조회됨 (일치, 법원/선고일 불일치, 자료 미포함 각 1건 이상).
- **대조군 시험**: 판례표 머리글이 없는 일반 스프레드시트는 표로 색인되지 않음. 기존 `test_drive_rag_relevance.py` 불변 통과.
- **예산 및 이어 읽기**: 동기화 시간 예산 도달 시 중단되고, 다음 동기화에서 `continuation`으로 남은 행이 끝까지 색인됨. 추출기 버전 변경 후 첫 실행에서도 재색인됨.
- **반복 입력 시간 시험**: 표 후보 감지 및 헤더 매핑 2,000회 이상 반복 실행 시 0.1초 이내 통과 검증.
- **회귀 방지**: TK-71 4절 6 회귀 금지 시험 및 고정 81.7/79.2/0 유지.
