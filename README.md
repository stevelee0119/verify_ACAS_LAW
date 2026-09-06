# 법률 분야 AI 문서 검증 및 위조 식별 시스템

기술설계서 종합본 v0.2 구현체이다. 사건별 프로젝트 안에서 법률문서의 진정성, 위·변조 의심징후,
판례·법령·학술자료의 실재성, 인용 정확성, 사실관계 일관성, 논리적 모순, AI 작성 가능성,
메타 지시어·프롬프트 인젝션 등 적대적 조작을 종합적으로 검증한다.

## 핵심 원칙

| 원칙 | 구현 |
|---|---|
| Source First | 사건번호·선고일·조문·계산·해시는 공식 API와 결정론적 엔진이 먼저 확인한다. LLM은 의미 비교·반대검증에만 쓴다. |
| Evidence First | 모든 Finding은 `Evidence`와 `SourceRecord`에 연결된다. |
| Human Final Decision | 위조·진정성립·고의에 관한 최종 평가는 사용자에게 남긴다. |
| Abstention | 확정이 불가능하면 `UNVERIFIED` / `ABSTAIN`으로 남긴다. |
| Provider Independence | OpenAI·Anthropic·Gemini·Local LLM을 교체 가능한 Provider로 구성한다. |
| Graceful Degradation | 한 Source나 모델의 장애가 전체 Job 실패로 이어지지 않는다(`PARTIAL_COMPLETED`). |
| Secure by Design | 문서는 자료이지 명령이 아니다. Tool 권한은 최소화한다. |
| Reproducibility | 파일·Source·모델·프롬프트 버전·결과를 추적한다. |

## 빠른 시작

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn apps.api.main:app --reload      # http://localhost:8000
pytest                                   # 155개 테스트
```

Docker: `docker compose up --build`

API Key가 하나도 없어도 동작한다. 이 경우 외부 Source 검증 항목은 `UNVERIFIED`로 표시되고,
결정론적 검사(은닉 텍스트·인젝션·포렌식·계산·타임라인)는 모두 정상 수행된다.

### 환경변수

| 변수 | 용도 |
|---|---|
| `LV_LAW_GO_KR_OC` | 국가법령정보 공동활용 OC (판례·법령 공식 검증) |
| `LV_KCI_KEY` | KCI 학술 API Key |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | LLM Provider |
| `LV_PSEUDONYM_SECRET` | 실명-가명 매핑 암호화 키. **운영에서는 반드시 교체한다.** |
| `LV_DATABASE_URL` | 기본 SQLite. 운영은 PostgreSQL. |
| `LV_ALLOW_NETWORK=0` | 폐쇄망 모드. 외부 Adapter를 모두 비활성화한다. |

API Key는 Frontend LocalStorage나 평문 DB에 저장하지 않는다. 응답에도 키 값은 포함되지 않으며 보유 여부만 노출한다.

## 구조

```
apps/api/          FastAPI (라우터·DB·서비스·업로드 보안)
apps/web/          검증 콘솔 (대시보드·뷰어·필터·리뷰·감사추적)
packages/
  document_engine/     PDF·DOCX·HWPX·HWP·XLSX·이미지 파서, OCR Adapter, bbox 보존
  adversarial_engine/  MM-1 인젝션 탐지, Unicode·인코딩·레이어 비교, Tool Firewall, 출력 검사
  forensic_engine/     MM-2 잔류, MM-3 은닉채널, MM-4 참고신호, 마스킹 실패, 특권 게이트, Outbound Guard
  legal_engine/        인용 추출·정규화, 판례 검증 5단계, 시행법 기준시점 검증
  source_adapters/     국가법령정보·KCI·OpenAlex·Semantic Scholar·Crossref, 내부 Mirror
  claim_engine/        Claim·Entity·Timeline, 계산 검증, 문서간 모순
  pii_engine/          한국형 PII 탐지, 법률 식별자 보호, 프로젝트 고정 가명
  llm_router/          Provider 추상화, Cascade, Judge Source Priority, 예산 라우팅
  verification_engine/ 파이프라인 오케스트레이션, AI 작성 분석, 축별 점수
  audit_engine/        SHA-256 해시 체인, Chain of Custody Manifest
  report_engine/       PDF·Highlight PDF·XLSX·CSV·JSON·Manifest
workers/           Celery Task (미설치 시 인프로세스 실행)
```

## 검증 파이프라인

```
QUEUED → PARSING → ADVERSARIAL_SCANNING → EXTRACTING → PII_PROCESSING
       → VERIFYING → CROSS_CHECKING → AGGREGATING → COMPLETED
```

Adversarial Scan은 **모든 LLM 호출보다 먼저** 실행된다. MM-2·MM-3에서 추출된 원문은
LLM Context에 투입되지 않고 유형 태그·위치·길이·해시만 전달된다.

## 은닉 메타메시지 4유형

| 유형 | 수신자 | 처리 |
|---|---|---|
| MM-1 기계 지시형 | LLM·자동검증 절차 | 결정론 + 의미분류 → Finding |
| MM-2 잔류형 | 없음(비의도 유출) | 결정론적 포렌식 → Finding 확정, 원문 봉인 |
| MM-3 은닉 채널형 | 특정 인간·추적 주체 | 결정론적 포렌식 → Finding, URL·QR 접속 금지 |
| MM-4 함축형 | 재판부·상대방 | 참고 신호만. Severity ≤ MEDIUM, Grade D, UNVERIFIED 고정 |

MM-2·MM-3 원문은 봉인 상태로 저장된다. 열람은 사용자의 명시적 확인이 있을 때만 가능하고
그 사실이 감사추적에 기록되며, 기관 관리자는 열람 기능 자체를 차단할 수 있다.
관할별 입장 차이(ABA Formal Opinion 06-442, NYSBA Opinion 749)를 경고문으로 안내하되
시스템은 법적·윤리적 결론을 내리지 않는다.

## Release Gate

`tests/test_release_gates.py`가 제24.3장과 부록 C를 코드로 강제한다.

- 공식 Source가 있는 확정판정에는 Source가 연결된다
- HIGH/CRITICAL은 Evidence 또는 명시적 UNVERIFIED를 가진다
- 원본은 SHA-256을 생성하고 분석 중 수정되지 않는다(재기록 차단)
- 문서는 UNTRUSTED로 처리되고 raw text가 system prompt와 결합되지 않는다
- 문서 내 instruction은 Tool Call로 승격되지 않는다
- 의심 문서는 자동 Indexing되지 않는다(QUARANTINED)
- LLM 실행 전 Adversarial Scan, 실행 후 Output Scan을 수행한다
- 문체만으로 특정 AI 모델 Attribution을 확정하지 않는다
- 공식 Source와 AI 의견이 충돌하면 다수결이 아니라 공식 Source를 따른다
- 모델 의견이 엇갈리면 다수결 대신 UNVERIFIED로 남긴다

## 구현 범위와 한계

**구현됨**: 제1~26장 및 부록 A~C의 파이프라인 전 구간, 제25.2장 Vertical Slice 전 단계.

**설계서와 다른 점**
- Frontend는 Next.js 대신 FastAPI가 서빙하는 무의존 SPA로 구현했다. 화면 구성(대시보드·뷰어·
  Finding 패널·필터·리뷰 상태)은 제19장을 그대로 따르며, API 계약이 동일하므로 Next.js로 교체 가능하다.
- Worker는 Redis/Celery 대신 인프로세스 스레드가 기본이다. `workers/celery_app.py`가 동일 진입점을
  Celery task로 노출하므로 브로커만 붙이면 전환된다.
- DB 기본값은 SQLite이다. 모델은 PostgreSQL+pgvector를 전제로 작성되어 있고 `embedding` 컬럼이 준비되어 있다.

**의도적으로 남긴 한계**
- OCR은 Adapter 인터페이스만 제공한다. tesseract가 설치되면 자동 사용하고, 없으면 해당 항목을 UNVERIFIED로 남긴다.
- `config/legal_mirror/`에는 판례·법령 데이터를 기본 포함하지 않는다. 검증 신뢰성이 데이터 출처에
  직접 좌우되므로, 국가법령정보에서 정식 절차로 받은 데이터만 배치해야 한다. 테스트는 가상 데이터임을
  명시한 `tests/fixtures/legal_mirror/`만 사용한다.
- Level 4(판례 취지)·Level 5(문맥 왜곡) 검증은 LLM 담당 구간이다. Provider가 없으면 `PENDING_LLM`
  상태로 남고 결코 VERIFIED로 승격되지 않는다.
- 서명 값의 암호학적 검증은 존재·구조 확인까지만 수행한다.

## 참고 Source

국가법령정보 공동활용 <https://open.law.go.kr/> · KCI <https://www.kci.go.kr/> ·
OpenAlex <https://developers.openalex.org/> · Semantic Scholar <https://www.semanticscholar.org/product/api> ·
Crossref <https://www.crossref.org/documentation/retrieve-metadata/rest-api/> ·
C2PA <https://spec.c2pa.org/> ·
OWASP Prompt Injection Prevention Cheat Sheet
<https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html> ·
NIST Generative AI <https://www.nist.gov/artificial-intelligence>

본 시스템은 검증 보조 도구이다. 진정성립·위조·고의에 관한 판단은 사용자의 책임이다.
