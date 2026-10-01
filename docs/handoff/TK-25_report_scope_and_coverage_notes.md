# TK-25 보고서 표시 잔여 불일치와 커버리지 관찰
- 유형: 정책 이행 잔여 + 관찰 · 기준 커밋: main 9933548 · 작성: evaluator 2026-10-01
- 근거: 서면9 사용자 온라인 보고서(`verification_rpt_98d4014bcc7b4b80.json`).

## 1. AI 판정 축의 `scope`가 흔적 0건이면 `NOT_APPLICABLE` (TK-18 잔여)
보고서 `scores.axes.ai_authorship`: `verdict=AI_FULL_GENERATION_LIKELY`(점수 0.91, 다수결 `MAJORITY_AI_CONSENSUS`), `involvement=NO_OBJECTIVE_TRACES`, **`scope=NOT_APPLICABLE`**. 판정은 "문서 전체 AI 생성 가능성 높음"인데 범위가 "해당 없음"이다. 원인: `scoring.unified_authorship`가 `scope = (...verdict 매핑...) if traces else "NOT_APPLICABLE"`로 범위를 흔적 유무에 묶었다. 사용자 결정(다수결이 판정, 객관적 흔적 부재는 별도 축으로 표시)은 판정에 한정하지 않고 범위 표시에도 적용된다.
- 요구: `scope`는 `verdict`에서 정하고(`WHOLE_DOCUMENT`·`PART_OF_DOCUMENT`), `involvement`·`objective_traces`만 흔적에 따른다. 표시 문구는 사용자가 정한다(라벨 변경 금지).
- 수용: 단위 시험 — 흔적 0건 + 다수결 AI_FULL → `scope == "WHOLE_DOCUMENT"`, `involvement == "NO_OBJECTIVE_TRACES"`. `tests/acceptance/test_ai_majority_rule.py` 유지.

## 2. 관찰(선택 개선, 정책 아님)
- **인용 검증 커버리지:** 인용 10건 중 `fully_verified` 0, `temporal_pending` 6, `lookup_unverified` 1. `legal_history.select_version`이 같은 시행일 버전이 둘이면 `ValueError("Multiple versions share the requested effective boundary")`를 내 국가재정법 제96조가 미검증(INFO)으로 남았다. 안전하게 미검증으로 두는 현재 동작도 허용되나 커버리지 손실이다. 같은 시행일이면 공포일·버전 번호로 최신을 고르고 두 버전을 모두 보고서에 싣는 방안을 검토한다.
- **모델 호출 12건 중 2건 실패:** anthropic `OUTPUT_TRUNCATED`(출력 4000토큰 한도), openai `INVALID_RESPONSE_SCHEMA`(최상위 required 위반). 다른 공급자·재시도로 이어져 실행은 `PARTIAL_COMPLETED`로 끝났다. 출력 한도 상향 또는 분할, 스키마 위반 응답의 복구·재요청이 필요하다.
- **정상 동작(유지):** `AUTHORSHIP_METADATA_LEAK`(문서요약정보 작성자 노출, LOW)·`STYLE_SHIFT`(INFO)는 정답지에 없는 추가 관찰이며 근거(Producer 필드, 문체 변화)가 보고서에 있다.
