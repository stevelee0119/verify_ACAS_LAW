# 한국법 검토 프로필 kr2

사용자 결정(2026-10-10): Claude for Legal에서 선별한 스킬 지침을 기존 Claude 서버 API에 적용한다. Claude Code 실행기나 법률 특화 모델을 추가하는 기능이 아니다. 실제 MCP는 한국법 자료 범위·접근 권한을 확인한 뒤 별도 연결한다.

대상은 `review_document → LLMRouter.run`의 문서·주장 단위 참고자료 검토 중 실제 선택 공급자가 Anthropic인 요청이다. OpenAI·Gemini fallback과 기존 모델 ID·역할·주장 의견 `consult_all`·공식 DB 조회·원문 대조·Finding 생성 규칙은 유지한다. 다른 stage나 다른 역할의 Claude 호출에는 적용하지 않는다.

## 켬·복귀

`LV_KOREAN_LAW_REVIEW_PROFILE=1`로 API/worker 설정을 함께 다시 로드하면 새 실행에 적용한다. 기본 및 `1` 이외 값은 꺼짐이며, `0`으로 설정을 다시 로드하면 기존 지침/입력으로 복귀한다. 프로그램 버전·모델 설정은 변경하지 않는다. 켬의 `+kr2` 프롬프트 버전은 끔 캐시 및 이전 잘못된 경로의 `+kr1`과 구별한다. worker의 기존 설정 스냅샷 드리프트 차단을 유지한다. 진행 중 요청이나 Settings 객체를 중간에 수정하지 않는다.

기존 자료 선택·발췌·마스킹과 주장 요청 허용 키 검사를 거친 요청에 명시 기준일을 내부 marker로 담는다. 라우터가 공급자를 한 번 선택한 뒤 marker를 소비한다. Anthropic의 지정 stage/원 지침/스키마/PRIMARY_REASONER가 모두 맞을 때 고정 한국법 지침 및 기존 허용 키 `system_instructions`의 context를 사용한다. 다른 공급자는 marker 없이 기존 요청을 그대로 전송한다. 정적 지침만 개인정보 해시 등록소에 등록하며 동적 context/user는 기존 입력 검사를 거친다.

관할은 대한민국이고 `ProjectContext.case_date`의 유효한 ISO 날짜만 기준일로 받는다. 미지정·부적합 날짜는 `UNSPECIFIED`이며 현재 날짜나 문서 날짜로 보충하지 않는다. 분석 순서는 쟁점 → 적용 요건 → 문서 사실 → 근거 원문 → 적용 차이·반론 → 불확실성이다. 문서 사실·당사자 주장·모델 추론을 구분하고 자료 밖 사건번호·조문·인용문은 만들지 않는다. 기존 응답 인용 필드와 두 문장 explanation을 사용한다. 기존 원문 인용 대조는 인용의 존재만 검사하며 법률적 타당성을 보증하지 않는다.

기존 참고자료만 사용하며 새 공식 원문 수집/입력 보강은 없다. 자료가 한국 공식 시행본/판결 원문인지 확인되지 않거나 발췌가 부족하면 적용 판단을 유보해야 한다. 문서 길이/자료 선택/주장 발췌 한도, 문서 배치·분할/fallback·주장당 한 번 run·공급자 transient retry·출력 4000토큰·temperature 0·예산/timeout/입출력 검사·응답 스키마는 유지한다. 추가 호출 경로는 없지만 실제 잘림/실패/재시도 횟수는 응답 변화에 따라 달라질 수 있다.

## 같은 입력의 지침 비교

`build_review_comparison_request(request, korean_profile=False/True, reference_date=...)`는 같은 마스킹된 입력·참고자료·관할/기준일·schema·temperature·출력 한도·metadata를 갖는 두 요청을 만든다. 오직 system이 다르다. 네트워크 호출·채점·자동 이중 실행을 하지 않는다. 비교 요청은 기존 LLMRouter를 거치며 동일 Anthropic 모델과 외부 AI 정책/예산/시간 상한을 유지한다.

릴리즈 후 Render에서는 실제 스위치 끔/켬 운영 비교를 기본으로 한다. 끔에는 새 context가 없으므로 이 비교는 전체 효과이며 순수 지침 효과와 구분한다. 위 빌더를 사용하는 별도 지침 비교는 선택 사항이다. OpenAI/Gemini는 이번 개선 대상이 아니고 fallback 계약 및 회귀 대조군이다. 실행 기록의 모델·usage·cost_status·latency·실패/격리/재시도와 실행 전체 벽시계 시간을 함께 확인한다.

최신 사용자 결정에 따라 실제 품질·비용·지연은 릴리즈 후 API 키가 설정된 Render 환경에서 대표 입력으로 종합 평가한다. 20% 비용·p95 지연 증가 기준은 참고 목표이며 자동 합격/탈락 조건이 아니다. 릴리즈 전에는 구현/보호 계약과 같은 SHA의 필수 CI 및 기존 승인 절차를 확인하고 기본 꺼짐으로 릴리즈한다. 실제 A/B 결과를 릴리즈 전 필수 조건으로 요구하지 않는다. 평가 시 제한적으로 켜고 결과에 따라 계속 사용/보완/복귀를 결정한다. 모델 자기평가·문장 길이·대역 시험·고정 오프라인 점수만으로 개선을 판정하지 않는다.

[보완 설계](../docs/handoff/requests/korean_law_review_revision_design.md), [출처/라이선스 및 SHA 변경 사유](../docs/handoff/requests/korean_law_review_profile_sources.md), [다중 모델/MCP 결정](../docs/handoff/requests/korean_law_review_multimodel_design.md), [영향 분석·채택 기준](../docs/handoff/requests/korean_law_review_impact_analysis.md), [평가 인계](../docs/handoff/requests/korean_law_review_evaluation_handoff.md).
