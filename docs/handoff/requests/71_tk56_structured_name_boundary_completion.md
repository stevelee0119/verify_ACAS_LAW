# TK-56 구조화 성명 경계 보완 보고 (2026-10-10)

기준 Steve `03fdcdb`, 브랜치 `codex/tk56-structured-name-boundary`. 설계 `a3608de`를 먼저 커밋했다. 제출 SHA와 같은 SHA의 CI 링크는 PR에 기록한다. 구현 PR은 직접 병합하지 않는다.

`packages/llm_router/privacy.py`에서 키 분류와 값 전송 안전성 판정을 분리했다. 기존 사람 역할·비인명 키 집합을 유지하고 성명 필드 접미 문법을 정규화한다. 주체를 모르는 일반 `…Name` 키는 키만으로 사람 라벨을 만들지 않고 값 구조를 함께 확인한다. 새 비인명 예외 낱말 사전·이름 사전·의존성은 추가하지 않았다. 단일 성명/조사 문맥은 기존 detector로 확인하며, 명시 성명 필드의 목록·직함·띄어쓰기·불확실 비문자열 값은 미전송 처리한다. 복성 이름의 조사와 조사처럼 보이는 이름 끝 음절을 대조 시험했다.

불확실 값은 원문을 기록하지 않고 경로·PERSON 건수·기존 `PII_INPUT_BLOCKED` 코드로 남긴다. 개인정보 정책 식별자는 `payload-pii-v4`이며 프로그램 버전은 바꾸지 않았다. 원본 system, user, 미등록 schema, metadata, 중첩·문자열 JSON이 같은 수집 경로를 쓴다. 등록 고정 상수의 해시 계약·원문 탐지·router 검사 실패 미전송·예약 전 차단을 유지했다. 실제 PseudonymStore 토큰은 전송되고 가명 접두부 뒤에 이름을 붙인 값은 차단된다.

합성 자료 시험 `tests/test_tk56_structured_name_boundary.py`는 355건이다. 새로운 성명 접미, 이름 형태 5종 × 이름 3종 × 키 4종 × 요청 위치 4종, 비한글/비문자열 값, 비인명 값과 그 필드 안 개인정보, 가명화·등록 스키마, 복성·끝 음절, 중첩 구조를 검사한다. 실제 LLMRouter.run의 system/user 및 schema/metadata에서 차단 시 공급자 도달과 비용 예약은 모두 0이다. 통과 대조는 실제 공급자 대역에 도달한다. 기존 시험·기대값·skip/xfail·보호 경로·다른 구현 담당 파일은 수정하지 않았다.

관련 직접 시험 명령(오프라인·외부 서비스 대역):
```sh
LV_ALLOW_NETWORK=0 /workspace/venv/bin/python -m pytest -o addopts='' -q tests/test_tk56_structured_name_boundary.py tests/regression/test_r8a_structured_privacy.py tests/regression/test_r8c_key_context.py tests/regression/test_r8d_key_context.py tests/regression/test_r8e_key_context.py tests/regression/test_r8f_contact_rrn.py tests/regression/test_r8f1_rrn_linebreak.py tests/acceptance/test_structured_request_privacy.py tests/acceptance/test_pii_label_variants.py tests/acceptance/test_round6_regressions.py tests/acceptance/test_round7_findings.py tests/test_pii_and_claims.py tests/test_tk20_pii_layout_invariance.py tests/test_tk65_envelope_schema.py
```
```text
21 failed, 873 passed, 8 xfailed in 5.45s
```
실패로 집계된 21건은 모두 목표의 strict XPASS다. **XPASS(strict) 외 실패 0**. 목표 표시 21건은 그대로 유지했으며 평가 측이 통합할 때 지운다. 등록 상수·system 변조·직접 요청 개인정보 경계의 원장/고정 사본 관련 선택 시험도 `34 passed, 274 deselected in 0.83s`다.

라우터·실제 DOCX 마스킹·payload guard·구조화 경계와 기존 요청 통합 시험의 추가 실행은 `44 passed in 0.92s`다. 이 추가 범위의 최초 묶음 실행은 로컬 샌드박스의 asyncio.to_thread 완료 신호 대기로 중단했다. 네트워크 금지 상태의 최소 스레드 재현이 3초 timeout이고 실행 환경 네트워크 권한을 부여한 동일 재현은 즉시 완료됨을 확인했다. 제품·시험을 바꾸지 않고 후자의 실행 권한으로 위 44건을 다시 실행했다. LV_ALLOW_NETWORK=0과 외부 서비스 대역은 그대로 유지했다. 최초 중단 실행을 통과로 집계하지 않는다.

동일 합성 이름 형태 60건·비인명 대조 9건·가명 대조 3건을 기준과 보완 트리에 비교했다(비공개 수치 아님):
```text
before 03fdcdb: synthetic name shapes blocked 0/60; nonperson controls blocked 0/9; masked controls blocked 0/3
after working tree: synthetic name shapes blocked 60/60; nonperson controls blocked 0/9; masked controls blocked 0/3
```
새 키/값/수집 경로는 각각 수천 회 0.1초 이내이며 반복 긴 키·값의 시간도 시험한다.
```text
TK-56 key grammar 3,000 pairs: 0.029921s
.TK-56 value boundary 3,000 pairs: 0.007969s
.TK-56 collector 2,000 fields: 0.043490s
.TK-56 repeated long key/value: 0.005177s
.
4 passed, 351 deselected in 0.78s
```
scorecard 전후 원문, 푸시 전 시험 편집 점검은 PR에 붙인다. 고정 점수는 dev 81.7·holdout 79.2·오탐 0으로 같다.

남은 판정: 비공개 정상 구조화 과차단 ≤6/28, 키 변형·구조화·평문 유출 0 유지, 개인정보 필수 게이트와 수용 SHA verify_all·릴리스 봉인 시험은 별도 평가 세션이 확인한다. 비공개 자료를 요청·열람하거나 evaluator 브랜치/판정서를 수정하지 않았다. 로컬 verify_all은 실행하지 않았다. TK-55 표지 없는 역할 명사 키는 추론하지 않는다. 기존 역할/주체 불명 이름 키의 비인명 한국어 복합 값 계약을 보존하므로, 그 값의 일부가 실명과 같은 모양이라는 이유만으로 새 사람 문맥을 붙이지 않는다. 명시 성명 필드의 불확실 값·비문자열 값은 보수적으로 차단하므로 잔여 과차단은 평가 대상이다. TK-44/49 2단계와 TK-45는 TK-56 수용 전 착수하지 않는다.
