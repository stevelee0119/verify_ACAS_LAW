# TK-69 FT 목 인용 가운뎃점·복수 목 인식 및 정규식 공백 모호성 제거 설계 메모 (개정 1)

- 작성: Antigravity (구현 에이전트) 2026-10-09
- 관련 티켓: `docs/handoff/TK-69_ft_subitem_middle_dot_list.md` (개정 1)

## 1. 배경 및 문제점
1. **가운뎃점류 미인식**:
   `packages/legal_engine/temporal_review.py`의 `SUBITEM_TAIL_RE`에 가운뎃점(`·`, `・`, `ㆍ`)이 누락되어 '제1호 가목·나목' 등의 인용이 정규식 매칭에 실패하고 기본 조·항 대조 경로로 회귀함.
2. **실제 파이프라인 경로 인용 추출기(extract_citations)의 첫 목 절단 (개정 1)**:
   인용 추출기(`citation_extractor.py`)의 `LAW_RE`는 단일 목만 매칭하므로, 실제 서면에서 `raw_text`가 '…제1호 가목'에서 끝나버림.
   이에 따라 뒤따르는 '·나목', '및 나목', '부터 다목까지'가 `raw_text`에서 제외되어 `extract_subitems_info`가 목 하나(`['가']`)로만 해석하던 실제 경로 결함 확인.
3. **정규식 이중 공백 반복에 따른 백트래킹 (개정 1)**:
   - `ITEM_SUBITEM_RE`의 `(?:제?\s*(?P<item>\d+)호)\s*(?:제?\s*` 구조의 공백 중첩
   - `NEXT_SUBITEM_RE`의 `^\s*(?:[·・ㆍ,]|\s*(?:및|와|과))` 선택지 내부 `\s*`로 인한 공백 분할 백트래킹 (공백 20,000개 입력 시 29초 이상 소요)

## 2. 설계 내용
1. **`SUBITEM_TAIL_RE` 문자 집합 보완**:
   - `\s|[.,()，。:;\-·・ㆍ]|$|의|에|...` 형태로 가운뎃점류(`·`, `・`, `ㆍ`)를 추가함.
   - '다목적 시설', '항목' 등 목 뒤에 일반 명사 어근이 이어지는 경우는 계속 배제함.
2. **정규식 공백 모호성 제거 및 유한 창 상한 (개정 1)**:
   - `ITEM_SUBITEM_RE`: `(?:제\s*)?(?P<item>\d+)호\s*(?:제\s*)?(?P<subitem>[{SUBITEM_LETTERS}])목{SUBITEM_TAIL_RE}`
   - `NEXT_SUBITEM_RE`: `^\s*(?:[·・ㆍ,]|및|와|과)\s*(?:제\s*)?(?P<next>[{SUBITEM_LETTERS}])목{SUBITEM_TAIL_RE}` 로 선택지 내부 공백 분할을 단일화.
   - `SUBITEM_WINDOW_LIMIT = 100`: 유한 창 상한을 적용해 후행 공백 20,000개 입력에서도 0.1초 이내(실제 0.0001초 이내) 처리 보장.
3. **인용 추출기(`citation_extractor.py`) 복수 목 확장 연동 (개정 1)**:
   - `LAW_RE` 매칭 시 `subitem`과 `item`이 존재하면, `parse_subitem_sequence`를 호출하여 뒤따르는 목 열거 및 범위를 소비함.
   - 확장된 끝 위치(`ext_end`)를 기준으로 `raw_text`, `span`, `context`, `quoted_text`를 확장하고 `attributes["subitems"]`를 등록함.
   - 단일 목 인용의 경우 기존과 동일한 `span`과 `raw_text`를 유지하여 기존 인용 시험과 100% 호환됨.
4. **복수 목 추출 파서 (`parse_subitem_sequence`, `extract_subitems_info`)**:
   - `parse_subitem_sequence`: 첫 번째 목 뒤 텍스트에서 열거 및 범위를 유한 창 내에서 파싱하여 전체 목 리스트와 소비 길이를 반환.
   - `extract_subitems_info`: `citation.attributes.get("subitems")`를 우선 지원하고, `raw_text` 직접 입력에도 하위 호환 동작.
5. **목 본문 병합 대조 및 TK-62 원칙 준수**:
   - `version_outcomes`에서 인용된 목들이 판본에 존재하는 경우, 해당 목들의 본문을 합친 범위(`combined_text`)를 대상으로 `compare_claim_to_provision`을 수행함.
   - 어느 판본에서든 목 단위 VERIFIED가 확인된 경우에만 일치하는 목이 없는 판본을 CONTRADICTED로 판정하는 TK-62 규칙을 엄격히 유지함.

## 3. 검증 계획
1. **합성 시험 (양성 3건, 대조 3건, 회귀 1건 이상)**:
   - 양성: 가운뎃점 열거(`가목·나목`), 접속사 열거(`가목 및 나목`), 범위 표기(`가목부터 다목까지`).
   - 대조: '다목적', '항목/품목', 호 표기 없는 '가목' 단독 언급.
   - TK-62 규칙 유지: 신설 목 소급 및 목 이동 개정 시 판정 일관성 검증.
2. **파이프라인 경로 시험 (합성 서면 → extract_citations → version_outcomes) (개정 1)**:
   - 세 형태('가목·나목', '가목 및 나목', '가목부터 다목까지')의 합성 서면에서 인용 추출 시 복수 목이 포함되고, `version_outcomes`에서 결합 본문으로 VERIFIED 판정됨을 단언.
3. **정규식 및 파서 시간 단언 (개정 1)**:
   - '1호' + 공백 4,000자 + 'x'에 대해 `ITEM_SUBITEM_RE` 0.1초 이내 단언.
   - '제1호 가목' + 공백 20,000자 + 'x'에 대해 `NEXT_SUBITEM_RE`, `parse_subitem_sequence`, `extract_subitems_info` 0.1초 이내 단언.
4. **성적표 및 회귀 점검**:
   - 고정 dev(81.7), holdout(79.2), 오탐 0 유지 및 관련 시험 통과.
