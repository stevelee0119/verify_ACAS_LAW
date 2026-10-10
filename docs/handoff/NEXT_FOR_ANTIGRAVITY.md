# Antigravity 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-10 평가 측(TK-69 수용, TK-70 불승인 소규모 1, TK-72 신설). 이전 전달문을 모두 대체한다. 이 파일에 없는 지시는 없다.

```
[Antigravity 작업 — 통합 지시 2026-10-10 (51)]

0. 규칙(AGENTS.md)
 - 시작: 최신 Steve_ACASiaLAW에서 작업 브랜치를 만든다. 이미 연 PR은 같은 브랜치에 보완 커밋을 올린다.
 - 리베이스·강제 푸시 금지(병합 커밋). 푸시 뒤 PR에 3줄 코멘트(바꾼 것·남은 것·'검토 요청').
 - 푸시 전 python scripts/check_test_edits.py --base origin/Steve_ACASiaLAW 출력을 보고에 붙인다.
 - 정규식이나 문장·문서마다 도는 반복·재탐색 로직을 새로 넣거나 바꾸면 반복 입력(수천 번) 시간 시험을 함께 둔다(0.1초 이내).
 - 새 시험은 실제 경로를 거친다(파일 → parse_document → 엔진, 또는 VerificationPipeline.run). 시험 안에 제품 로직을 복사하지 않는다.
 - 은퇴 세트 측정은 작업 트리를 깨끗이 한 상태에서 한다.
 - 0.12.0 배포 전에는 탐지 엔진 PR을 Steve에 병합하지 않는다(봉인 채점을 마친 릴리스 후보가 바뀐다). 수용된 PR은 배포 뒤 평가 측이 통합한다.
 - 다른 구현 담당(Codex)이 같은 시기에 packages/pii_engine/(TK-43·56), packages/document_engine/paragraph_reconstruction.py(TK-44·49),
   packages/legal_engine/legal_rules.py·claim_review.py·statutory_exclusion.py(TK-45·24)를 고친다. 이 파일들은 건드리지 않는다.

[A] 릴리스 0.11.0 완료(main a8b2a7e, 태그 v.0.11.0). 할 일 없음.

[E] (1순위, 지금) 버전 커밋 0.11.0 → 0.12.0 (VERSION_POLICY 6절 3단계, 0.11.0 때 PR #48과 같은 방식)
   - 근거: docs/scorecards/version_verdicts.json의 0.12.0 판정서(measured_commit 0bf4ccc, level minor). 최신 Steve(928b242 이후)에서 브랜치
     antigravity/version-0.12.0.
   - 바꾸는 것만: packages/common/config.py의 version, docs/releases.json 항목(판정서의 근거 수치와 포함 티켓 TK-58·TK-67·TK-71·TK-68),
     python scripts/update_readme.py가 갱신하는 README 표. 다른 변경을 섞지 않는다. 커밋 1개.
   - 푸시 전 python scripts/check_version_policy.py --base origin/Steve_ACASiaLAW 출력(위반 없음)과 check_test_edits 출력을 PR에 붙인다.
   - CI 필수 3개 성공 뒤 '검토 요청'. 평가 측 확인 → 사용자 병합 → 평가 측이 릴리스 PR(Steve → main)을 연다.

[D] (2순위, [E]를 올린 뒤) TK-70 — PR #60(356b5ad) 불승인(소규모 1). 같은 브랜치에 보완 커밋을 올린다. 자세한 내용은 PR #60 평가 측 코멘트.
   - 기능은 평가 측 파이프라인 재현에서 요구대로 동작했다(승격·합치기·거부·스위치·게이트 불변). 바꿀 것은 시험이다.
   - 문제: 양성 시험은 VerificationPipeline()을 만들기만 하고 승격 반복문을 시험 안에 복사해 돈다. 중복 합치기 시험도 묶기 로직을 다시 구현하고,
     스위치 시험은 설정값만 본다. 그래서 pipeline.py의 새 블록이 깨져도 통과한다.
   - 요구
     1) 양성·대조·중복 합치기·스위치·게이트 불변 시험이 VerificationPipeline.run을 거치게 한다
        (참고자료 라이브러리와 review_document를 가짜로 바꿔 '모순' 의견을 주입하고 결과 documents[].findings를 단언하는 방식 등).
     2) 스위치: 같은 입력에서 켬 → 승격 있음, 끔 → 승격 0을 파이프라인 결과로 단언한다.
     3) 중복 합치기: 주장 단위(claim_id 있음)와 문서 단위(claim_id 없음, 같은 인용문)가 하나로 합쳐지는 경우를 넣는다.
   - 선택(같은 커밋에): config.py 새 필드와 기존 설명 문자열 위치 정리, 새 경로가 켜지면 TK-09 RAG 경로(elif)가 돌지 않는 점을 설계 메모에 한 줄,
     승격 거부를 rejected_observations에 더하는 이유를 메모에 한 줄.
   - 병합은 0.12.0 배포 뒤. RAG 경로라 봉인 시험은 없고, 배포 뒤 평가 측 비공개 온라인 세트와 서면9로 본다.

[B] 증거·조문 탐지 보완
 B1. TK-67 — PR #55 수용·병합(Steve 2c54486). 0.12.0으로 배포 예정. 할 일 없음.
 B2. TK-69 — PR #56(ce68dc4) 수용. 할 일 없음. 이 PR에 커밋을 더 올리지 않는다(올리면 재판정).
   - 확인: 실제 경로에서 여러 목 인식, 새 함수 시간 0.001초 미만, verify_all 전체 종료 0, 고정·은퇴 점수 같음.
   - 0.12.0 배포 뒤 평가 측이 통합한다. 다음 릴리스에서 봉인 시험.

[C] TK-68 — PR #59 수용·병합(Steve 0bf4ccc). 0.12.0으로 배포 예정. 할 일 없음.

[F] (3순위, TK-69가 Steve에 통합된 뒤) TK-72 인용 추출기 제곱 시간(기존 결함, P2) — docs/handoff/TK-72_citation_extractor_quadratic_time.md
   - 같은 파일(packages/legal_engine/citation_extractor.py)을 TK-69가 고쳤으므로, TK-69 통합 뒤 최신 Steve에서 시작한다.
   - 증상(평가 측, 운영본과 같은 코드): 합성 80KB 한 줄(목 인용 뒤 공백 반복) 42초, 인용 32,000건 960KB 92초.
   - 원인: 겹침 검사 overlaps()와 문장별 인용 배정이 인용마다 전체를 다시 훑음, INTERPRETATION_RE·ACADEMIC_RE가 공백·'·' 반복 구간을 시작 위치마다 다시 훑음.
     같은 파일의 다른 정규식·반복문도 같은 기준으로 점검한다.
   - 요구: 문서 길이·인용 수에 선형(또는 n log n), 추출 결과 불변(기준 코드와 합성 입력 묶음 비교 차이 0), 티켓 3절의 시간 시험(80KB·960KB 각 1초 이내).
   - 선택: TK-69 판정의 선택 항목('또는' 뒤 목, 반복 입력의 중복 목)을 같은 PR에서 정리해도 된다(시험 동반).
```

