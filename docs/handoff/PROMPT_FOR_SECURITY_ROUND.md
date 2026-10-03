# 보안 보강 라운드 작업 지시서 — CodeQL 경고 기반 소규모 보강 (구현 담당 에이전트)

작성: 평가 에이전트(claude-code) 2026-10-03 · **전달 시점: 6차 검증이 끝난 직후**(사용자 결정 2026-10-03: 6차 → 보안 보강 → '행위시법 검토 보강'(요청 16 + TK-34) → F1 → TK-24). 6차 구현이 끝나기 전에는 전달하지 않는다.
근거: GitHub 코드 스캔(CodeQL) 열린 경고 38건을 평가 측이 위치까지 수집·분류한 결과(`docs/handoff/GITHUB_ACCESS.md` 6절)와 티켓 TK-35·36·37·38. **경고 줄 번호는 `main`(`9933548`) 기준이므로 시작 브랜치의 같은 코드를 직접 찾아 고친다.**
아래 전체를 그대로 붙여 넣어 쓴다. 1~6차 지시서의 규칙(보고 규칙·설계 원칙·금지 행위·버전 규칙)은 그대로 유효하다.

---

## 0. 이번 라운드의 성격
**보안 결함 4건을 닫는다. 새 기능·새 규칙·새 `rule_id`·새 설정 파일·새 탐지 유형은 동결이다.** 판정 결과(점수)가 바뀌면 안 된다. 고치는 곳은 아래 S1~S5뿐이며, 시험을 맞추려고 판정 로직을 건드리지 않는다.

### 0.1 전달 전 평가 측 선행 작업(구현 측은 읽기만)
평가 측이 지시서를 전달하기 전에 S1~S5의 **strict xfail 시험을 `tests/acceptance/`에 먼저 고정하고 푸시**한다(6차 감사의 기대 수치를 바꾸지 않으려고 지금은 넣지 않았다). 전달 시 평가 측이 시작 SHA와 xfail 목록을 이 문서 아래에 덧붙인다. 구현 측은 xfail을 지우거나 기대값을 바꾸지 않는다. XPASS(strict) 실패가 나면 `docs/handoff/requests/`로 알린다(평가 측이 표시를 지운다).

## 1. 작업 묶음 (이 순서로, 묶음마다 커밋)

### S1. TK-38 A — PDF 정규식 지수 증가 (첫째: 조작된 PDF 한 건이 처리를 멈춘다)
- 위치: `packages/document_engine/pdf_parser.py`의 `SINGLE_GLYPH_SHOW_RE`(`main` 기준 1296-1298행, 경고 `py/redos` 1297행), 호출 `_is_line_break_marker`.
- 원인: `(?:[-\d.\s]+(?:Tm|Td|TD)\s*)*`에서 반복 끝의 `\s*`와 다음 반복 처음의 `[-\d.\s]+`가 같은 공백을 나눠 가진다. 재현: `_is_line_break_marker("​", b">> BDC" + b" 0 Tm  " * 14 + b"X", 0)`가 20초 이상(중단) 걸린다.
- 요구: **정규식 의미(ActualText U+200B 뒤 한 글리프 표시와 EMC인지)를 바꾸지 않고** 지수 증가를 없앤다. 방식은 구현 측이 정한다(공백 소유권을 한쪽으로 몰기, 반복 부분을 선형 구조로 재작성, 사전 길이·연산자 수 상한 등). 조작 입력의 최악 시간을 1초 이내로 만든다.
- 보존: 정상 Google Docs(Skia) PDF의 `ActualText U+200B` 판정 결과(`_is_line_break_marker`)와 실제 Google Docs PDF 시험(`test_case9_real_pdf.py`)·`test_layout_invariance_pdf.py`가 그대로 통과한다.

### S2. TK-38 B — `korean_amount.py:65`
- `(?:원정|원|정)+$`는 `원정`을 `원`+`정`으로도 읽어 지수로 증가하지만, 현재 호출부는 `원`·`정`을 넘기지 않아 도달하지 않는다. 같은 의미의 선형 정규식 `[원정]+$`로 바꾼다. 기존 `korean_amount` 시험은 그대로 통과해야 한다.

### S3. TK-35 — 저장소 경로 검사
- `packages/common/storage.py`의 `LocalObjectStorage._abs`: `str(p).startswith(str(self.root.resolve()))`를 경로 구성요소 단위 비교(`Path.is_relative_to` 등)로 바꾼다. 재현: 루트가 `…/storage`일 때 키 `../storage2/secret.txt`가 통과한다.
- `PROJECT_ID_RE.match`(`storage.py`의 `_project_dirs`, `apps/api/project_purge.py`)는 `fullmatch`로 바꾼다(`$`가 끝 줄바꿈을 허용). 같은 정규식을 쓰는 다른 호출부도 찾아 같이 고친다.
- 키 형식·저장 위치·기존 저장소 시험은 바꾸지 않는다.

### S4. TK-36 — 예외 문구 응답
- `apps/api/access.py`의 `StorageKeyConfigurationError` 503 응답(`str(exc)`)은 고정 문구 + `request_id`만 싣고 상세(환경변수 이름·하위 예외)는 서버 로그로만 남긴다. `apps/api/main.py`의 `unhandled_error` 방식(문의 번호 + 예외 종류)과 맞춘다. 기동 시 진단용으로 보관하는 경로(`record_storage_encryption_error`)는 **관리자 전용 진단에만** 보이는지 확인해 보고한다. `/api/diagnostics`(관리자 전용)의 `capabilities.py` 오류 문구는 유지해도 되며 유지한다면 사유를 보고한다.

### S5. TK-37 — 관리자 화면 탭 검증
- `apps/web/static/admin.js`: 탭 이름 검증을 자기 속성 검사(`Object.hasOwn(tabs, next)` 또는 `Map`)로 바꾸고 `preferences`를 `Object.create(null)` 또는 `Map`으로 만든다. `#admin/__proto__`·`#admin/constructor`·`#admin/toString`이 `users` 탭으로 돌아가고 `Object.prototype`이 오염되지 않아야 한다. CSV 내려받기 주소의 `year`도 `Number(year)`로 감싼다.
- 화면 동작(탭 전환·검색·필터·페이지 이동)은 그대로여야 한다. 해시에서 온 값으로 객체를 조회하는 곳이 더 있는지 점검해 보고한다.

### 이번 라운드에서 하지 않는 것
TK-38 C(다항·이차 증가 정규식 31건)는 호출부 확인이 선행되어야 하는 낮은 우선순위라 **이번 라운드에서 고치지 않는다**(`scripts/probe_regex_complexity.py` 결과를 보고에 첨부하는 것으로 갈음). 오탐 경고 처리(GitHub)는 사용자 몫이다. 워크플로 권한은 이미 평가 측이 처리했다.

## 2. 설계 원칙·금지
1. **의미 불변:** 정규식·검사 방식 교체가 판정 결과를 바꾸지 않는다. 바꾼 곳마다 **바꾸기 전후 출력 비교**(정상 입력 대조군)를 시험으로 둔다.
2. 평가 자료(사건 값·문구·표식)를 코드·설정에 넣지 않는다. 새 규칙·새 `rule_id` 금지. `tests/acceptance`·`tests/fixtures`·`docs/scorecards`·`.github/`·기준선은 수정하지 않는다.
3. 보안 시험의 입력(조작 PDF 조각, 경로 키)은 구현 측이 새로 짓는다. 평가 측 시험 입력을 복사하지 않는다.

## 3. 검증 명령 (커밋마다, 푸시 전에 전부)
```
python scripts/regression_gate.py --base HEAD~1                      # 종료 코드 1·2는 통과가 아니다. 푸시 전에는 --base <푸시 전 원격 커밋> --pytest
python scripts/check_hardcoding_diff.py --base HEAD~1
python scripts/check_case_literals.py
python scripts/scorecard.py && python scripts/score_gate.py          # 점수 하락 0(시작 상태 대비), 환경 함께 기재
python scripts/check_version_policy.py --base HEAD~1                 # 작업 커밋은 버전 불변
python -m pytest -q tests/regression
python -m pytest -q --ignore=tests/acceptance
python -m pytest tests/acceptance -q -rfxX
python scripts/probe_regex_complexity.py                             # 약 1분 20초. 지수 증가 의심 0건이어야 한다(S1·S2 완료 뒤). 다항 증가 목록은 보고에 첨부
```

## 4. 보고 형식 (묶음마다)
1. 원인 한 줄, 바꾼 파일, 새로 둔 시험, **바꾸기 전후 출력 비교 결과**
2. S1·S3는 재현 입력의 **고치기 전·후 시간/결과**를 적는다(S1: 최악 시간, S3: 재현 키 3종 차단 여부)
3. 4절 명령 출력 요약(시작 상태 대비), 환경(OS·python), 푸시 후 GitHub `점수 게이트` job 결론과 단계별 결과(CI는 브랜치 푸시로 돌지 않으므로 수동 실행 결과 별도)
4. XPASS로 풀린 시험 id, 남은 미해결, **확인하지 못한 것**
5. 커밋 해시(`Agent: implementer`), 버전 상태("변경 없음")

## 5. 완료의 정의
- S1~S5의 strict xfail 전부 XPASS(평가 측이 표시를 지움), 조작 PDF 입력 최악 시간 1초 이내, 재현 경로 키 차단, 503 본문에 `LV_` 접두 환경변수 이름 없음, `#admin/__proto__` 계열 해시가 `Object.prototype`을 오염시키지 않음.
- 점수·판정 변화 0(회귀 게이트 종료 코드 0), 하드코딩 변경분 점검 강한 신호 0, 로컬 전체 시험 새 실패 0(모든 커밋), `probe_regex_complexity.py` 지수 증가 의심 0건. GitHub `점수 게이트` 성공.
- 평가 측이 `보안 경고 내보내기`를 다시 실행해 해당 경고가 `main` 반영 뒤 닫히는지 확인한다(경고는 `main`에서만 갱신되므로 이 확인은 `main` 병합 뒤 평가 측 몫이다).
