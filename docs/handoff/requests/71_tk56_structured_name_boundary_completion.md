# TK-56 구조화 성명 경계 과차단 보완 보고 (2026-10-10)

PR #70, 기준 Steve `03fdcdb`, 브랜치 `codex/tk56-structured-name-boundary`. 최신 Steve `ad25f51`을 병합 커밋 `7a77b73`으로 반영했다. upstream의 TK-43·70·평가 기록과 시험은 원본 그대로이고, PR의 변경은 5파일의 TK-56 범위뿐이다. 최초 설계 `a3608de` 및 보완 설계 `2892b83`를 코드보다 먼저 커밋했다. 제출 SHA·최종 diff stat·같은 SHA CI 링크·scorecard 전후·푸시 전 시험 편집 점검 원문은 PR에 기록한다. 구현 PR은 직접 병합하지 않는다.

초기 제출 `ef790e7`은 목표 21 strict XPASS와 유출 지표를 유지했지만, 평가 측 회신에서 정상 구조화 과차단 상한 초과로 불승인됐다. 비공개 입력은 요청하지 않고 공개 합성 값으로 원인을 재현했다. 명시 성명 필드에서 단일 이름 추출 실패를 무조건 불확실 값으로 취급해 한국어 기관명·업무·복합 값도 차단했다.

`packages/llm_router/privacy.py`의 값 경계를 보완했다. 명시 성명 필드와 일반 이름 필드 모두 유한 이름 창·기존 조사 문법을 먼저 확인한다. 이름 형태·목록·직함·조사는 차단을 유지하고, 그 구조가 없는 완성형 한글·공백 값은 기존 원문 탐지에 맡긴다. 명시 성명 필드의 4음절 이하 값은 성씨 확인 실패도 불확실 값으로 차단한다. 비한글·비문자열·구조가 불확실한 값은 fail-closed로 차단한다. 기존 사람/비인명 키 어휘·가명 토큰 전체 일치·등록 상수의 해시 계약·형제/배열/중첩/문자열 JSON 검사·연락처/RRN·평문 detector는 변경하지 않았다. 새 예외 낱말 목록·의존성·프로그램 버전 변경은 없다. 개인정보 정책 식별자는 payload-pii-v4다. 원문은 감사 결과에 기록하지 않고 경로·PERSON 건수와 기존 PII_INPUT_BLOCKED를 쓴다.

합성 시험 `tests/test_tk56_structured_name_boundary.py`는 681건이다. 같은 키·값 경계에서 system/user/schema/metadata의 실제 LLMRouter.run을 시험했다. 새 보완은 비인명 값 72건, 같은 키의 실명·직함 72건, 비한글·비문자열 및 익숙하지 않은 성씨/한국어 표기 불확실 값 72건과 수천 회 시간 시험이다. 거절 SHA에서 비인명 시험 72건이 실패했고 보완 후 통과했다. 차단은 공급자·비용 예약 전에 일어나며, 정상 대조는 공급자 대역에 도달한다. 초기 464건의 이름 형태·일반 Name 키·비인명 필드의 PII·실제 가명화·복성·이름 끝 음절·등록 스키마·중첩 구조도 그대로 유지한다. 기존 시험·기대값·skip/xfail·보호 경로·다른 담당 파일은 수정하지 않았다.

동일 합성 입력의 실제 라우터 값 경계 전후 원문(최신 공통 구성에서 값 판정 함수만 거절 SHA와 보완 코드로 바꿈, 비공개 지표가 아님):
```text
before ef790e7 boundary: nonperson actual router sent 0/72; names actual router sent 0/72; uncertain actual router sent 0/72
after working tree boundary: nonperson actual router sent 72/72; names actual router sent 0/72; uncertain actual router sent 0/72
```

관련 직접 시험 명령(LV_ALLOW_NETWORK=0, 외부 서비스 대역):
```sh
LV_ALLOW_NETWORK=0 /workspace/venv/bin/python -m pytest -o addopts='' -q tests/test_tk56_structured_name_boundary.py tests/regression/test_r8a_structured_privacy.py tests/regression/test_r8c_key_context.py tests/regression/test_r8d_key_context.py tests/regression/test_r8e_key_context.py tests/regression/test_r8f_contact_rrn.py tests/regression/test_r8f1_rrn_linebreak.py tests/acceptance/test_structured_request_privacy.py tests/acceptance/test_pii_label_variants.py tests/acceptance/test_round6_regressions.py tests/acceptance/test_round7_findings.py tests/test_pii_and_claims.py tests/test_tk20_pii_layout_invariance.py tests/test_tk65_envelope_schema.py tests/test_tk43_category_stopwords.py tests/test_tk43_particle_sentences.py
```
```text
21 failed, 2753 passed, 8 xfailed in 9.63s
```
실패 집계 21건은 모두 목표 TK-56 strict XPASS이며 **XPASS(strict) 외 실패 0**이다. 표시는 평가 측이 통합할 때 지운다.

추가 라우터·DOCX 마스킹·payload guard·기존 요청 통합 및 원장/고정 사본의 직접 관련 선택 시험:
```text
44 passed in 0.93s
34 passed, 274 deselected in 0.71s
```
추가 실행은 기존 로컬 sandbox의 asyncio.to_thread 완료 신호 문제를 피하도록 실행 환경 네트워크 권한을 부여했지만, LV_ALLOW_NETWORK=0과 서비스 대역을 유지했다. 원본 중단 실행을 통과로 집계하지 않는다. 로컬 verify_all은 실행하지 않았다.

반복 시간 원문(새 경로 포함):
```text
TK-56 key grammar 3,000 pairs: 0.028709s
.TK-56 value boundary 3,000 pairs: 0.010634s
.TK-56 collector 2,000 fields: 0.045786s
.TK-56 unknown name windows 3,000 values: 0.011638s
.TK-56 shared Korean value boundary 3,500 values: 0.012939s
.TK-56 repeated long key/value: 0.005555s
.
6 passed, 675 deselected in 0.76s
```

남은 제한·평가: 성명과 같은 모양의 기관명, 비한글·구두점·비문자열 값에는 잔여 과차단이 가능하다. 이름 형태가 확인되지 않은 한국어 복합 값은 원문 검사에 맡기며 성명 자동 마스킹의 보장 범위를 확대하지 않는다. 비공개 정상 요청 과차단 ≤6/28와 유출 0·필수 PII 게이트의 회복 여부는 별도 평가 세션이 판정한다. 비공개 자료·evaluator 브랜치·판정서를 요청/열람/수정하지 않았다. 수용 SHA 전체 검증·표시 제거·통합 승인과 다음 릴리스 새 봉인 시험은 평가 측/사용자 단계다. TK-55 표지 없는 역할 명사 키·TK-44/49 2단계·TK-45에는 착수하지 않았다.
