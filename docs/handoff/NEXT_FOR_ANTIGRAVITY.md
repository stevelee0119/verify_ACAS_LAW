# Antigravity 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-07 평가 측(F3 설계 보충 PR #32 판정 뒤). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Antigravity 작업 — 통합 지시 2026-10-07 (20)]

0. 규칙(AGENTS.md): 리베이스·강제 푸시 금지(병합 커밋). 푸시 뒤 PR에 3줄 코멘트(바꾼 것·남은 것·'검토 요청').
   보고서의 시험 건수·버전·점수는 실제 출력 그대로 적는다. 코드 사실(함수 이름·위치·동작)은 코드에서 확인한 것만 적는다.

[A] F1·F2·TK-61·FT — 모두 병합·배포 완료(main 43d3132). 할 일 없음.

[B] F3 1단계 — 설계 보충 PR #32(3398943) 판정: 보완 요구(승인 보류). 아직 코드를 쓰지 않는다.
    같은 브랜치 antigravity/f3-reference-review에서 docs/handoff/requests/43_f3_design.md만 고친다.
    평가 측 회신 원문: PR #32 코멘트 '평가 측 판정 — F3 설계 보충 3398943'.
    필수 보완(메모에 반영)
    1) 호출 수: LLMRouter.run 1회가 일시 장애 때 공급자 호출을 최대 3회 보낸다(router.py:421).
       주장당 3회와 서면 1건 총량을 '공급자로 나간 요청 수' 단위로 다시 센다(문서 단위 배치 포함).
    2) 인용 행 reference_status: SUPPORTED는 인용 동일성 대조에서만 온다(모델 SUPPORTS로 올리지 않음).
       CONTRADICTED가 가려지지 않게 우선순위를 적는다. CONTEXT를 NOT_MENTIONED로 바꾸지 않는다.
       의견과 인용은 link_observations(contract_facts.py:119)의 claim_ids로 연결한다.
    3) 동일성 대조: 사건번호는 경계 일치, 법령명+조는 근접 기준을 적는다. 대조 본문은 마스킹 본문이다.
       규칙 대조이므로 LOCAL_ONLY·QUICK에서도 돈다.
    4) evidence_sources에 Drive 링크(file_id가 든 URL)를 넣는다. ReviewItem.authority_limitation은 없는 필드다
       (새로 만들면 추가 키라고 적고, 아니면 문장을 지운다).
    5) LOCAL_ONLY·QUICK 분기는 진입부가 아니라 현행 위치(review.py:146, provision_obs 뒤)에서 조건만 넓힌다.
    6) fail-closed 검사 함수의 모듈·이름·실패 신호를 적는다. reference_sources 항목 키와 19b 6.1 길이 한도
       (claim_text 1,000자, reference_sources 5개)도 적는다(title 제외 권고).
    7) 주장 단위 search_fulltext 결과 중 읽지 않은 파일의 처리((a) 색인 안에서만 찾기, 또는 (b) 기존 읽기 경로)와
       거절(401·403·429) 시 중단을 적는다.
    8) finding이 없는 참고 의견 행의 검토 상태 저장 위치를 적는다(이번 단계에서 읽기 전용이면 그렇게 적는다).
    사실 정정 5건: 함수명 build_document_review_items, inspect_request는 LLMRouter.run 안(router.py:367),
    incremental_findings_count 이름, 상수 위치(packages/common/config.py)와 매니페스트 키,
    오프라인 CI에서는 review_document가 호출되지 않음.
    다 고치면 같은 PR에 3줄 코멘트와 '검토 요청'을 단다. 평가 측이 승인하면 구현에 착수한다.

[C] FT 후속(목 뒤 가운뎃점 '가목·나목' 인식) — 아직 하지 않는다.
```
