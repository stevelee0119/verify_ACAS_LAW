# 8D 완료 보고서 — TK-54

## 대상

- PR: [#10 — 8C: TK-53 이름 키 정규화 + 키 문맥 축소](https://github.com/stevelee0119/verify_ACAS_LAW/pull/10)
- 제품 구현 검증 SHA: `751fb50dfe79e7125b46a000ea0780f15c519412` (`codex/round8c-key-context`)
- 기준 SHA: `d20cde2`; 변경량 비교 기준: `86bd035`
- 환경: Linux, Python 3.11.17 (`python --version` 첫 줄), Tesseract 5.3.4 (`tesseract --version` 첫 줄). `verify_all`은 CI 환경 일치 `true`로 판정했다.

## 변경 및 설계 차이

- [8D 설계 메모](32_round8d_design.md)를 첫 커밋 `173de4e`로 제출한 뒤 구현했다.
- 어휘 밖의 한국어 `…명`·이름/명의/보유자 접미 형태와 정규화한 영문 이름 필드 형태를 판별한다. 이름 키 아래 값은 명확한 비인명 타입 근거가 확인되지 않으면 전송 전에 fail-closed로 차단한다. 직함·조사·띄어쓰기·복수 목록의 닫힌 꼬리 목록은 두지 않았다.
- 영문 구조화 키 라벨을 detector의 별도 어휘로 분리하고 `LABELLED_PARTY_PERSON_RE`에 넣지 않았다. 새 시험 `test_english_structured_key_labels_do_not_change_plain_text_label_regex`는 시작 패턴 해시 및 평문 예시를 고정한다.
- 설계 메모 초안은 “각 가능한 시작 경계”에서 이름 후보를 찾는다고 했으나, 구현 전 메모를 수정해 실제 방식과 맞췄다. 구현은 값 첫 한글 토큰의 이름 후보를 사용하고, 그 후보를 놓쳐도 이름 키 경로의 별도 fail-closed 판정으로 불확실 값을 차단한다.
- 새 시험은 새로 만든 키·값만 사용한다. 기존 시험은 수정·삭제하지 않았다.

## Diff 통계

`git diff 86bd035 HEAD --stat`:

```text
docs/handoff/requests/32_round8d_design.md     |  14 +++
docs/handoff/requests/33_round8d_completion.md |  71 ++++++++++++
packages/llm_router/privacy.py                 | 152 +++++++++++++++++++++----
packages/pii_engine/detector.py                 |  16 ++-
tests/regression/test_r8d_key_context.py        | 133 ++++++++++++++++++++++
5 files changed, 360 insertions(+), 26 deletions(-)
```

`git diff 86bd035 HEAD --stat -- tests/`:

```text
tests/regression/test_r8d_key_context.py | 133 ++++++++++++++++++++++++++++++++
1 file changed, 133 insertions(+)
```

## 필수 검증

실행: `python scripts/verify_all.py --base d20cde2` (전체 모드, SHA `751fb50`). 콘솔 출력:

```text
verify_all — HEAD 751fb50, 기준 d20cde2, 모드 full
  환경: python 3.11.17, tesseract 5.3.4, Linux-6.18.44-x86_64-with-glibc2.39
  [통과] environment: python 3.11.17, tesseract 5.3.4
  [통과] acceptance: 통과 909, 실제 실패 0, strict XPASS 0
  [통과] regression_ledger: 통과 457, 실제 실패 0, strict XPASS 0
  [통과] score_gate: 점수 게이트 통과
  [통과] regression_gate: 회귀 없음
  [통과] hardcoding_diff:   새로 추가된 줄에 시험 입력의 값·낱말·조문 번호 없음
  [통과] test_edits:   기존 시험의 삭제·표시 변경 없음
  [통과] version_policy: 버전 정책: 위반 없음 (버전 변경 없음)
  [통과] full_tests: 통과 3160, 실제 실패 0, strict XPASS 0
  [통과] browser_tests: 통과 196, 실제 실패 0, strict XPASS 0
요약 저장: artifacts/verify_all.json
```

종료 코드: `0`.

## 동일 SHA CI 및 리뷰

모두 `751fb50dfe79e7125b46a000ea0780f15c519412`에 대한 결과다.

- [CI run 37170869975](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/37170869975): 테스트(SQLite + PostgreSQL/pgvector + Redis) 성공, Docker OCR readiness 성공.
- [CI run 37170867497](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/37170867497): 테스트(SQLite + PostgreSQL/pgvector + Redis) 성공, Docker OCR readiness 성공.
- [점수 게이트 run 37170869976](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/37170869976) 및 [run 37170867450](https://github.com/stevelee0119/verify_ACAS_LAW/actions/runs/37170867450): 둘 다 성공.
- Sourcery 검토 성공. 남아 있던 조사형 값 지적(comment `4175662839`)과 `_walk_fields` 독스트링 지적(comment `4175662841`)은 대응 답변이 붙었고 두 리뷰 스레드 모두 해결 상태다.

## 미해결

- 평가 에이전트가 새 비공개 입력으로 재측정해야 하는 수용 지표와 즉석 점검은 아직 결과가 없다. 이를 추정하거나 완료로 간주하지 않았다.
- 후속 평가에서 확인할 구조화 과차단 수치는 평가 측이 측정한다.
