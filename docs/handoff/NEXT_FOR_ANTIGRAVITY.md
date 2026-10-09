# Antigravity 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-10 평가 측(TK-68 PR #59 사전 점검, 비용 비증가 조건 — 사용자 지시). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Antigravity 작업 — 통합 지시 2026-10-10 (45)]

0. 규칙(AGENTS.md)
 - 시작: 평가 측 기록 PR #51이 Steve_ACASiaLAW에 병합된 뒤 최신 Steve_ACASiaLAW에서 작업 브랜치를 만든다(새 티켓이 거기 들어 있다).
 - 리베이스·강제 푸시 금지(병합 커밋). 푸시 뒤 PR에 3줄 코멘트(바꾼 것·남은 것·'검토 요청').
 - 푸시 전 python scripts/check_test_edits.py --base origin/Steve_ACASiaLAW 출력을 보고에 붙인다.
 - 정규식을 새로 넣거나 바꾸면 반복 입력(수천 번) 시간 시험을 함께 둔다(0.1초 이내, TK-66 교훈).
 - 은퇴 세트 측정은 작업 트리를 깨끗이 한 상태에서 한다.
 - 다른 구현 담당(Codex)이 같은 시기에 개인정보 엔진(TK-58)과 법리 규칙(TK-24)을 고친다. packages/pii_engine/와
   packages/legal_engine/claim_review.py는 건드리지 않는다.
   TK-70은 packages/verification_engine/pipeline.py·candidate_verifier.py·gate.py, TK-68은 packages/rag_engine/review.py를 고친다. 두 PR이 같은 파일을 고치게 되면 먼저 병합된 쪽을 병합 커밋으로 받아 맞춘다.
   사용자 결정(2026-10-09): Codex의 TK-71(PR #57, packages/rag_engine/·review_items.py 등)을 먼저 받는다.
   TK-68은 packages/rag_engine/review.py를 TK-71과 함께 고치므로, TK-71이 Steve에 병합된 뒤 최신 Steve를 병합 커밋으로 받아 시작한다.
   TK-71(PR #57 7aecc51)은 Steve에 병합됐다(3c89a4e, 2026-10-09). TK-68은 지금 시작한다(최신 Steve에서 브랜치).

[A] 릴리스 0.11.0 완료(main a8b2a7e, 태그 v.0.11.0). 할 일 없음.

[B] (다음 구현 묶음 — 두 티켓을 각각 PR로, 릴리스는 함께) 증거·조문 탐지 보완
 B1. TK-67 — PR #55(472eb69) 수용·병합(Steve 2c54486). 할 일 없음.
 B2. TK-69 — PR #56(e8764b3) 불승인(소규모 1). 같은 브랜치에 보완 커밋을 올린다. 자세한 내용은 PR #56 평가 측 코멘트와 티켓 개정 1.
   - 문제: 실제 경로의 citation.raw_text는 첫 목에서 끝난다(extract_citations 결과 '…제1호 가목'). 그래서 '가목·나목'·'가목 및 나목'·'가목부터 다목까지'가 ['가']로만 해석된다.
     PR 시험은 인용 객체를 직접 만들어 이를 놓쳤다. 평가 측 티켓 1절의 증상표도 문장 전체로 잰 잘못이 있었다(개정 1).
   - 요구
     1) 인용 바로 뒤의 목 열거·범위를 실제 경로에서 읽는다(인용 추출기가 담거나, 본문의 인용 끝 위치 다음 유한 창을 해석하는 등).
        인용 추출기를 바꾸면 기존 인용 시험이 그대로 통과해야 한다.
     2) 파이프라인 경로 시험: 합성 서면 → extract_citations → version_outcomes에서 세 형태가 여러 목으로 대조됨을 단언
     3) 본문을 읽으면 창 상한과 NEXT_SUBITEM_RE 이중 공백(^\s*(?:…|\s*(?:및|와|과))) 정리, 반복 입력 시간 시험(0.1초 이내)
        (평가 측 측정: 지금 함수에 공백 2만 개 직접 입력 시 2.26초, 제곱 증가)
     4) 고정·은퇴 점수 하락 없음, 기존 시험 수정 없음, TK-62 규칙 유지
 - 수용 SHA마다 평가 측이 verify_all 전체 모드를 돌린다. 두 PR 병합 뒤 새 봉인 세트 하나로 릴리스 전 봉인 시험을 한다.

[D] (보통, B와 병행 가능 — 파일이 겹치지 않음) TK-70 Drive 참고자료 '모순' 의견의 조건부 finding 승격(D4 개정, 사용자 결정)
   — docs/handoff/TK-70_rag_contradiction_conditional_promotion.md
   - CONTRADICTS + verify_rag_candidate 통과 의견을 FACT_CONTRADICTION·SUSPICIOUS·LOW·C등급으로 올린다(문서·주장 단위 모두, advisory_only 표시만으로 빼지 않음).
     '내부 참고자료 대조 — 법적 구속력 미판단, 사람 확인 필요' 표기, claim_id·주장 원문 기록, 같은 주장·같은 참고자료는 하나로 합친다.
   - 검증위험 지수·차단 게이트·official_status·다른 finding 심각도는 바꾸지 않는다. 기본 켬, 끌 수 있는 운영 스위치 하나.
     LV_CANDIDATE_PROMOTION_ENABLED(그 밖의 모델 후보)는 그대로 둔다.
   - 평가 측 사전 점검: 플래그·advisory 건너뛰기만 뗀 임시 패치로 RAG 관련 14개 파일 431 passed·1 xfailed(전후 같음).
     기존 가짜 공급자는 '모순' 의견을 내지 않으므로 승격 경로를 지키는 새 시험(티켓 2.7)이 꼭 필요하다.
   - 설계 메모를 첫 커밋으로. 브랜치 antigravity/tk70-rag-contradiction-promotion. RAG 경로라 봉인 시험은 없고, 배포 뒤 평가 측 비공개 온라인 세트와 서면9로 본다.

[C] (보통, 지금) TK-68 문서 단위 Drive 대조 출력 잘림 — PR #59(ad93e84) 보완. 같은 브랜치에 보완 커밋을 올린다.
   docs/handoff/TK-68_rag_document_batch_output_truncation.md 개정 1(비용 비증가 조건, 사용자 지시). 판정은 CI 완료 뒤 PR #59 평가 측 코멘트로 확정한다.
   - 유지(평가 측 사전 점검 충족): 응답 형식·등록 프롬프트·advisory_only·stage 'drive_rag_advisory'·max_tokens 4000 불변, 관련 222 passed.
   - 비용 비증가 조건(N = 문서 단위 대조 참고자료 수, '변경 전' = Steve 3c89a4e 경로: 6개 묶음, 잘림 시 대체 공급자 1회)
     C1 잘림 없는 입력: 문서 단위 호출 수·입력 토큰 합계가 변경 전 이하. 지금처럼 늘 3개로 나누면 작은 참고자료 6개도 1회 → 2회가 되어 서면 본문을 두 번 보낸다(위반).
     C2 잘림 나는 입력(서면9형): 호출 수·입력/출력 토큰·지연 시간 합계가 변경 전 이하, 비용 합계는 변경 전보다 작다.
     C3 최악 상한: 잘림이 계속돼도 문서 단위 호출 수(재시도·분할 포함) ≤ 2 × ceil(N/6), 입력 토큰 합계 ≤ 변경 전 최악(묶음마다 2회).
        지금은 반으로 나누기를 거듭해 N=11에서 4회 → 29회(위반). 상한에 닿으면 더 나누지 않고, 남은 참고자료는 '미대조'로 기록해 분모에 남긴다.
     C4 max_tokens·LV_LLM_MAX_OUTPUT_TOKENS·등록 프롬프트 불변. 의견 수 상한을 프롬프트에 넣으려면 설계 메모와 사용자 결정 먼저.
     C5 시험: 가짜 공급자가 실행 기록에 input_tokens·cost_usd(입력 글자 수 비례), output_tokens·latency_ms(참고자료 수 비례)를 남기고,
        정한 수를 넘는 묶음은 OUTPUT_TRUNCATED를 낸다. 세 경우(잘림 없음/서면9형/계속 잘림)에서 실행 기록 합계를 변경 전 기대값과 비교해 C1~C3을 단언한다.
   - 방법은 설계 재량(예: 입력 크기 기준 묶음으로 작으면 6개 유지, 잘림 시 한 번만 나누기). 설계 메모(64)에 고른 방법과 C1~C3 계산을 덧붙인다.
   - 보고에 세 경우의 호출 수·토큰·비용 합계 전후 표를 붙인다. RAG 경로만 바꾸므로 봉인 시험은 없다.
   - 배포 뒤 평가 측 확인: 서면9 문서 단위 OUTPUT_TRUNCATED 0·비용/시간 감소, 비공개 측정 세트 문서 단위 비용 비증가.
```
