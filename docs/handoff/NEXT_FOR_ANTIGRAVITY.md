# Antigravity 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-04 평가 측(F1 2차 판정 뒤). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Antigravity 작업 — 통합 지시 2026-10-04 (2)]

0. 시작: 작업 브랜치마다 `git fetch origin evaluator/round8-promotion Steve_ACASiaLAW` 뒤 병합 커밋으로 받는다(리베이스·강제 푸시 금지).
   규칙(AGENTS.md): 커밋 전에는 바꾼 부분의 시험만 돌린다. 푸시 뒤 PR에 3줄 코멘트(바꾼 것·남은 것·'검토 요청').

[A] PR #13 F1 — 내용 수용(3bf349b). 남은 일은 병합 충돌 해소 하나.
 1) 브랜치 antigravity/f1-review-screen에 `git merge origin/Steve_ACASiaLAW`(병합 커밋).
    충돌 파일 2개는 양쪽을 모두 살린다.
    - apps/web/index.html: 검토 자료 패널의 개인정보 안내·확인 블록(privacy-notice, privacyAck 등)과
      '파일 추가' label의 id="fileInputButton"을 그대로 두고, 탭 이름·AI 탭·확인할 항목 패널은 F1 쪽을 쓴다.
    - apps/web/static/styles.css: 두 블록(업로드 안내 스타일, F1 배너·보안 카드 스타일)을 모두 남긴다.
 2) 로컬: tests/test_upload_privacy_notice_api.py, tests/test_upload_privacy_notice_browser.py, tests/test_frontend_upload.py,
    tests/test_f1_ai_security_tab_browser.py,
    tests/acceptance/test_f1_protected.py, tests/test_finding_categories.py만 돌린다. 시험 파일은 고치지 않는다.
 3) 푸시 뒤 PR #13에 '검토 요청'. PR #13은 첫 릴리스(0.10.0)가 main에 들어간 뒤 평가 측이 병합한다. 그 전에 병합하지 않는다.

[B] F2 통합 '검토 항목' 탭 — 착수 허용. 조건: [A] 해소 SHA의 CI가 초록.
 - 범위·수용 기준: docs/handoff/PROMPT_FOR_FEATURE_ROUND_F1.md 1절 F2와 19b 설계(정정본).
 - 브랜치: [A] 해소 SHA에서 antigravity/f2-review-items를 만든다.
   PR은 base를 antigravity/f1-review-screen으로 열고, F1이 Steve_ACASiaLAW에 들어가면 base를 Steve_ACASiaLAW로 바꾼다.
 - 필수:
   · 서버가 documents[].review_items를 만든다. 인용 하나에 행 하나, 행 심각도는 연결된 finding 중 가장 높은 값(연결 없으면 INFO).
   · AI·보안 탭 배정 유형은 검토 행에 넣지 않는다. 그 밖의 finding은 모두 어느 검토 행에 연결한다(HIGH 이상 포함).
   · 기존 JSON 키(findings, ai_hallucination_table, engine_data.rag, 보고서 필드)는 지우거나 이름을 바꾸지 않는다. 추가만 한다.
   · 심각도 규칙·rule_id를 새로 만들지 않는다. 점수·probe 결과는 전후 같아야 한다(점수 하락 게이트).
   · 주장 행은 켜지 않는다(TK-22 해결 전).
 - 평가 측 보호 시험 T1·T2·T4(검토 행)가 F2에서 처음 돈다. 건너뜀 없이 통과해야 한다.
 - 묶음이 끝나면 docs/handoff/requests/에 보고서(지시서 5절 형식) 1개, PR에 '검토 요청'.

[C] FT·F3 — 아직 착수하지 않는다. F2 수용 뒤 평가 측이 T10·T11(FT)을 고정하고 알린다.
```
