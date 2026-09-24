# ACASia_LAW

변호사의 법률문서 검토를 보조하는 작업 공간입니다. v0.4 개선 내용과
현재 제한 사항은 [구현 현황](docs/IMPLEMENTATION_STATUS.md), 상세 계획은
[개선 계획](docs/ASSESSMENT_AND_IMPROVEMENT_PLAN.md)을 참조하세요.

Windows 실행: `.\scripts\start-local.ps1` (http://127.0.0.1:8765).
포트가 사용 중이면 `.\scripts\start-local.ps1 -Port 8766`으로 실행하세요.
기존 데이터가 있으면 실행 전에 백업하고 `python -m alembic upgrade head`를 적용하세요.
기본은 로컬 단일 소유자 모드입니다. 다중 사용자 운영은 `LV_AUTH_MODE=multi-user`와
HTTPS, 계정 초기 설정, 사건별 권한 및 키 보관 설정이 필요합니다.
[인증·권한·키 관리](docs/IDENTITY_SECURITY_INTEGRATION.md)와
[작업 복구·비용 원장](docs/OPERATIONS_DURABILITY.md)을 먼저 확인하세요.

기술설계서 v0.2 기반에 변호사 작업 공간과 오판 방지 개선을 반영한 v0.4 구현체이다.
문서 위·변조 의심징후, 인용·사실관계·계산의 검토를 지원한다. 확인한 범위와
미확인·미지원 범위를 구별하며, 법률적 판단이나 진정성립을 자동 확정하지 않는다.

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
```

테스트는 별도 의존성과 Chromium을 설치한 뒤 실행한다. Linux에서는
`--with-deps`가 브라우저 실행에 필요한 시스템 패키지도 설치한다.

```bash
pip install -r requirements-test.txt
python -m playwright install --with-deps chromium
pytest                                   # 외부 환경별 테스트는 설정에 따라 일부 건너뜀
```

한국어 OCR을 쓰려면 시스템 패키지가 필요하다.

```bash
sudo apt install tesseract-ocr tesseract-ocr-kor
```

전체 구성(API + Worker + PostgreSQL/pgvector + Redis):

```bash
cp .env.example .env      # LV_PSEUDONYM_SECRET, POSTGRES_PASSWORD 등을 채운다
docker compose up --build
```

PostgreSQL·Celery까지 포함해 테스트하려면:

```bash
LV_TEST_DATABASE_URL=postgresql+psycopg://legal:비밀번호@localhost:5432/legal_verifier \
LV_TEST_CELERY_BROKER=redis://localhost:6379/0 pytest
```

API Key가 하나도 없어도 동작한다. 이 경우 외부 Source 검증 항목은 `UNVERIFIED`로 표시되고,
결정론적 검사(은닉 텍스트·인젝션·포렌식·계산·타임라인)는 모두 정상 수행된다.

### 환경변수

| 변수 | 용도 |
|---|---|
| `LV_LAW_GO_KR_OC` | 국가법령정보 공동활용 OC (판례·법령 공식 검증) |
| `LV_KCI_KEY` | KCI 학술 API Key |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | LLM Provider. 기본 모델은 `config/providers.json`(gpt-6-luna · claude-opus-5-5 · gemini-3.8-flash). 보고서의 모델별 판정에는 "OpenAI · GPT-6 Luna"처럼 공급자와 모델명이 함께 표시된다 |
| `LV_OPENAI_MODEL` / `LV_ANTHROPIC_MODEL` / `LV_GEMINI_MODEL` | 모델 ID 덮어쓰기(공급자가 모델을 바꿨을 때) |
| `LV_LLM_CROSS_CHECK` | AI 교차검증 범위. `all`(기본, 사용 가능한 모델 모두) · `auto`(판례 의미·적용 검토에서만 신뢰도가 낮거나 중요도가 높을 때 반증 모델 사용, 다른 검토는 `all`과 같음) · `off`(1순위 모델 하나) |
| `LV_HTTP_TIMEOUT` | 외부 출처 요청 제한시간(초, 기본 12). law.go.kr 응답이 느리면 30 권장 |
| `LV_SOURCE_MIN_INTERVAL_SECONDS` | 같은 출처에 연달아 보내는 요청 간격(초, 기본 0.3) |
| `LV_PSEUDONYM_SECRET` | 실명-가명 매핑 암호화 키. **운영에서는 반드시 교체한다.** |
| `LV_DATABASE_URL` | 기본 SQLite. 운영은 `postgresql+psycopg://...` |
| `LV_CELERY_BROKER` | 설정하면 Celery Worker로 분산 처리한다. 없으면 인프로세스. |
| `LV_OCR_LANG` / `LV_INDEPENDENT_OCR` | OCR 언어(기본 `kor+eng`), 독립 OCR 교차검증 모드 |
| `LV_ALLOW_NETWORK=0` | 폐쇄망 모드. 외부 Adapter를 모두 비활성화한다. |

기본 설정은 `.env.example`, 추가 인증·작업·예산 설정은 위 운영 문서에 있다.

API Key는 Frontend LocalStorage나 평문 DB에 저장하지 않는다. 응답에도 키 값은 포함되지 않으며 보유 여부만 노출한다.

## 구조

```
apps/api/          FastAPI (라우터·DB·서비스·업로드 보안)
apps/web/          검증 콘솔 (대시보드·뷰어·필터·리뷰·감사추적)
packages/
  document_engine/     PDF·DOCX·HWPX·HWP·XLSX·이미지 파서, OCR Adapter·래스터화, bbox 보존
  adversarial_engine/  MM-1 인젝션 탐지, Unicode·인코딩·레이어 비교, Tool Firewall, 출력 검사
  forensic_engine/     MM-2 잔류, MM-3 은닉채널, MM-4 참고신호, 마스킹 실패, 특권 게이트, Outbound Guard
  legal_engine/        인용 추출·정규화, 판례 검증 5단계, 시행법 기준시점 검증
  source_adapters/     국가법령정보·KCI·OpenAlex·Semantic Scholar·Crossref, 내부 Mirror
  claim_engine/        Claim·Entity·Timeline, 계산 검증, 문서간 모순
  pii_engine/          한국형 PII 탐지, 법률 식별자 보호, 프로젝트 고정 가명
  llm_router/          Provider 추상화, Cascade, Judge Source Priority, 예산 라우팅
  verification_engine/ 파이프라인 오케스트레이션, AI 작성 분석, 축별 점수
  audit_engine/        SHA-256 해시 체인, Chain of Custody Manifest
  report_engine/       초안·확정본 snapshot, PDF·DOCX·Highlight PDF·XLSX·CSV·JSON·Manifest
  evaluation/          사건 단위 분할, 라벨·예측 비교, 오류 유형별 오프라인 품질 평가
apps/worker/       DB 임대·펜싱·재시도·취소·복구, Celery 수명주기 연동
workers/           기존 Celery Task 호환 진입점
migrations/        Alembic. pgvector 인덱스와 audit_events append-only 트리거 포함
```

## 인프라 구성

| 구성요소 | 기본값 | 확장 |
|---|---|---|
| DB | SQLite | `LV_DATABASE_URL`로 PostgreSQL 전환. JSON 컬럼은 JSONB, `embedding`은 pgvector `vector(1536)`로 자동 매핑되고 HNSW 인덱스가 생성된다. |
| Worker | 인프로세스 스레드 + 영속 DB 작업 | Celery도 동일한 DB 임대·펜싱을 적용한다. auto 모드만 브로커 장애 시 로컬로 전환하며, 명시적 celery 모드는 큐를 보존한다. |
| OCR | 없으면 해당 항목 UNVERIFIED | tesseract 설치 시 자동 사용. 스캔 PDF는 페이지를 래스터화해 본문을 OCR하고 bbox를 보존하므로 인용 추출·Highlight가 그대로 이어진다. |

마이그레이션은 `audit_events`에 UPDATE·DELETE를 거부하는 트리거를 만든다.
감사추적 불변성(부록 C 제7항)을 애플리케이션이 아니라 DB가 강제한다.

```bash
alembic upgrade head
```

## 검증 파이프라인

```
QUEUED → PARSING → ADVERSARIAL_SCANNING → EXTRACTING → PII_PROCESSING
       → VERIFYING → CROSS_CHECKING → AGGREGATING → COMPLETED
```

Adversarial Scan은 **모든 LLM 호출보다 먼저** 실행된다. MM-2·MM-3에서 추출된 원문은
LLM Context에 투입되지 않고 유형 태그·위치·길이·해시만 전달된다.

### AI 교차검증

LLM을 쓰는 세 곳 모두 사용 가능한 모델(OpenAI·Anthropic·Gemini)을 함께 거친다.
한 공급자가 실패하면 다음 공급자로 넘어가고, 호출마다 정책 확인·예산 원장·출력 검사가 적용된다.
외부 모델에 보내는 본문은 `MASKED` 정책에서 개인정보를 가린다.

| 검토 | 모델 사용 방식 | 판정을 정하는 것 |
|---|---|---|
| 판례 의미·적용(Level 4·5) | 주 분석 → 반증 → 제3 모델 순서의 캐스케이드. 근거 인용이 공식 전문에 실제로 있어야 채택 | 공식 출처 우선. 모델 의견이 엇갈리면 `UNVERIFIED` |
| 법률 주장 타당성 | 모든 모델에 같은 질문. 항목별 의견과 일치·불일치를 **참고 의견**으로 표시 | 규칙(성립 불가 사건번호 / 인용 내용 불일치 / 공식 DB 미확인). 모델 답으로 '허위'가 되지 않는다 |
| AI 작성 여부 | 모든 모델에 같은 질문. 본문에 없는 의심 문단은 버린다 | 과반이 지지하는 판정(모델 둘이면 둘 다 동의해야 상향). 모델이 일치할 때만 증거등급 B |

화면의 요약 아래에는 **배포가능 판정 사유**가 펼쳐진 채로 표시된다. '배포 차단 사유'와
'사람 검토 사유'를 나누어 번호 목록으로 보인다.

**공식 DB에서 확인하지 못한 판례는 '미확인'이지 '부존재'가 아니다.** 국가법령정보 판례 DB는
모든 재판을 수록하지 않는다. 사건번호의 연도·사건부호가 성립할 수 없을 때만 임의 생성을 의심한다.

#### 모델이 응답하지 못할 때

교차검증에서 빠진 모델이 있으면 보고서에 **빠진 모델과 사유**를 함께 적는다.
예: `1개 모델(openai)의 의견만 있어 교차검증되지 않음 — 응답하지 못한 모델: gemini(사용 한도(쿼터) 초과(HTTP 429) — 공급자 요금제·결제 확인 필요)`

| 보고서의 사유 | 뜻 | 처리 | 해야 할 일 |
|---|---|---|---|
| 공급자 일시 과부하(HTTP 429·5xx·529) | 공급자 쪽 순간 과부하(예: Gemini `high demand`) | 2초·6초 간격으로 두 번 더 시도 | 반복되면 잠시 뒤 다시 분석 |
| 사용 한도(쿼터) 초과 | API 키의 요금제·결제·한도 소진(`exceeded your current quota`) | 재시도하지 않음(기다려도 풀리지 않음) | 공급자 콘솔에서 요금제·결제 확인 |
| API 키 또는 권한 오류(HTTP 401·403) | 키가 틀렸거나 권한 없음 | 재시도하지 않음 | Render 환경변수의 키 확인 |
| 응답이 출력 한도에서 잘림 | 답이 길어 JSON이 끝나지 않음 | 실패로 기록 | 반복되면 문서 분량과 함께 개선 요청. `LV_LLM_MAX_OUTPUT_TOKENS`(기본 4096)를 그보다 낮추면 호출 자체가 예산 단계에서 거절된다 |
| 응답 형식 오류(항목) | 정해진 JSON 형식과 다름. 어긋난 항목을 함께 적는다 | 그 모델 의견을 채택하지 않음 | 반복되면 모델 ID 확인 |

한국어 JSON은 공급자마다 토큰 사용량이 크게 다르다(같은 요청에 Anthropic이 OpenAI의 수 배).
그래서 판별·타당성 검토는 출력 한도 4,096, 판례 판단은 2,500으로 두고 항목별 분량 상한을
프롬프트에 둔다. 주장 타당성은 인용 4건씩 나누어 묻는다. 과금은 실제 생성량 기준이다.

판례 의미·적용 검토는 **공식 판결 전문을 받아야** 수행된다. 전문 조회가 실패하면 이 단계는
건너뛰어지고 사유가 기록된다. 배포 서버에서 전문 조회가 되는지는 아래
[배포 후 확인](#배포-후-확인)의 `/api/diagnostics/sources`로 확인한다.

### 판정을 나누는 기준

한 값으로 뭉뚱그리면 "확인된 것"과 "확인하지 못한 것"이 섞이므로 아래처럼 나눠 판정·표시한다.
회귀시험은 `tests/test_verification_regressions.py`에 있다(공식 DB 응답은 모두 모의 응답).

| 대상 | 따로 판정하는 항목 | 주의 |
|---|---|---|
| 법령 인용 | 법령 존재 · 조문 존재 · 시행 버전 · 조문 본문 대조 · 시간적 적용(기준일) · 사건 적용 | 기준일이 없으면 시간적 적용만 미확인이다. 문서의 날짜는 **기준일 후보**로만 보이고 자동 적용하지 않는다 |
| 조문 부존재 | 조회한 시행 버전의 **전체 조문**을 대조한 경우에만 "해당 버전에 없음"(범위·조문 수 기재) | 조회 실패·전문 미확보는 미확인. 다른 시행 버전·부칙 가능성은 열어 둔다 |
| 판례 인용 | 사건번호 형식 · 존재(조회 범위 내) · 법원·선고일 · 인용문 · 취지 · 사건 적용 | "조회 범위 내 미발견"과 "성립할 수 없는 번호 형식"을 구분한다. 다른 번호의 검색 결과를 붙이지 않는다 |
| 행정규칙(훈령·예규·고시·지침) | 존재 · 발령기관·종류·번호·시행일 · 조항 · 본문 · 위임 근거 · 법적 효력 | "법률과 같은 효력" 같은 문서의 주장은 확인 처리하지 않고 사람 검토로 둔다 |
| 사용하지 못한 출처 | 이번 실행에서 영향을 받은 인용 | 학술 인용이 없는 문서에서 KCI 키 없음은 `NOT_NEEDED`로 표시하고 잔여 미확인으로 세지 않는다 |
| 문서 속 지시문 | 명령형 어미·AI 호명·숨김 여부로 **명령**과 **언급**(표제·명사구·설명)을 구분 | 언급은 INFO 참고 표시, 실제 명령은 기존대로 HIGH 이상. 원문·위치·일치 패턴을 보존한다 |
| 첨부·증거 | 첨부 목록 표의 행(자료명↔첨부 여부), 본문 진술, 입력 파일을 대조해 `ATTACHED`·`NOT_PROVIDED`·`REFERENCE_MISSING`·`UNVERIFIED` | 자료가 없다는 것은 "검증되지 않은 사실"이지 허위·위조가 아니다 |
| 해시 | 형식(SHA-256은 16진수 64자) · 파일 대조(파일이 있을 때만) · 원본성 | 형식 이상은 불일치가 아니다. 해시가 일치해도 진정성립·내용의 진실성은 보증하지 않는다 |
| 주장 유형 | 사실 · 법령 문언 · 판례 취지 · 당사자 법률 주장 · 의견 · 문서 안내(제목·시험 안내) · 문서 속 지시문 | 사실 축은 "검사 범위 내 이상 없음"과 "검사 불충분"을 구분한다 |
| AI 작성 가능성 | 모델별 판단·분포, 추정치(모델 점수 중앙값), 근거 신뢰도 | 모델 의견이 갈리거나 객관적 작성 흔적(도구 표기·챗봇 잔재)이 없으면 판단 유보. 인용 오류·문서 속 지시문·서식·문체는 작성 주체 근거로 쓰지 않는다 |

같은 인용에서 나온 finding(예: 조회 범위 내 미발견 + 그 판례에 기댄 주장)은 화면과 차단 사유에서
하나로 묶고 하위 근거를 함께 보인다. 차단(BLOCK) 자체는 유지하고, 검증위험 지수에서는 같은 인용의
같은 유형을 한 번만 센다. 검증위험 지수는 AI 작성 확률이 아니다.

## 은닉 메타메시지 4유형

| 유형 | 수신자 | 처리 |
|---|---|---|
| MM-1 기계 지시형 | LLM·자동검증 절차 | 결정론 + 의미분류 → Finding |
| MM-2 잔류형 | 없음(비의도 유출) | 결정론적 포렌식 → Finding 확정, 원문 봉인 |
| MM-3 은닉 채널형 | 특정 인간·추적 주체 | 결정론적 포렌식 → Finding, URL·QR 접속 금지 |
| MM-4 함축형 | 재판부·상대방 | 참고 신호만. Severity ≤ MEDIUM, Grade D, UNVERIFIED 고정 |

### 독립 OCR 교차검증 (제7.3장)

OCR이 가능한 환경에서는 위험 신호가 있는 PDF의 페이지를 다시 렌더링해 직접 읽고,
그 결과를 내장 텍스트 레이어와 대조한다. 사람이 보는 화면에는 없는데 모델이 읽는
텍스트 레이어에만 존재하는 지시문이 발견되면 `OCR_LAYER_INJECTION`(CRITICAL)으로 보고한다.
OCR 인식 오차로 인한 오탐을 막기 위해, 단순 분량 차이로는 Finding을 만들지 않고
지시형 문자열이 한쪽에만 존재할 때만 보고한다.

MM-2·MM-3 원문은 봉인 상태로 저장된다. 열람은 사용자의 명시적 확인이 있을 때만 가능하고
그 사실이 감사추적에 기록되며, 기관 관리자는 열람 기능 자체를 차단할 수 있다.
관할별 입장 차이(ABA Formal Opinion 06-442, NYSBA Opinion 749)를 경고문으로 안내하되
시스템은 법적·윤리적 결론을 내리지 않는다.

## GitHub에서 실행하기

| 워크플로 | 트리거 | 하는 일 |
|---|---|---|
| `CI` | push·PR | SQLite와 PostgreSQL/pgvector+Redis 양쪽에서 전체 테스트, 감사추적 append-only 트리거 확인. Secret을 쓰지 않는다. |
| `외부 Source 실연동 점검` | 수동 또는 `[live-check]` 커밋 | Secret 주입 상태 → Adapter 상태 → **실제 API 호출** → LLM Provider → **판례 의미·적용 캐스케이드**(law.go.kr 전문으로 1회) → **주장 타당성·AI 작성 판별**(실제 코드로 1회) 순으로 점검하고, 모델별 참여 여부와 실패 사유·토큰 수를 표로 남긴다. LLM 호출은 `with_llm` 입력을 켤 때만. |
| `문서 검증 실행` | 수동 또는 `[run-verify]` 커밋 | **검증 파이프라인을 끝까지 돌리고** 보고서 6종을 아티팩트로 남긴다. |

`workflow_dispatch` 버튼은 워크플로 파일이 **기본 브랜치에 있어야** Actions 탭에 나타난다.
병합 전이라면 커밋 메시지 트리거를 쓴다.

```bash
git commit --allow-empty -m "연동 확인 [live-check]"
git commit --allow-empty -m "검증 실행 [run-verify]"
```

Actions는 잡이 끝나면 사라지는 실행기이므로 **웹 콘솔을 상시 띄우는 용도로는 쓸 수 없다.**
UI를 직접 다루려면 Codespaces를 쓴다. `.devcontainer/`가 OCR·의존성·포트 8000을
자동 구성하므로, 컨테이너가 뜬 뒤 `uvicorn apps.api.main:app --host 0.0.0.0 --port 8000`만 실행하면 된다.
API Key는 **Settings → Codespaces → Repository secrets**에 등록하면 자동 주입된다.

실연동 점검이 기대하는 Secret 이름이다. 다르게 등록했다면 워크플로의 `env:` 우변만 바꾸면 된다.

```
LV_LAW_GO_KR_OC   LV_KCI_KEY   LV_CROSSREF_MAILTO   LV_SEMANTIC_SCHOLAR_KEY
OPENAI_API_KEY    ANTHROPIC_API_KEY   GEMINI_API_KEY
```

모델 ID는 공급자 사정으로 바뀌므로 Repository **Variables**(`LV_ANTHROPIC_MODEL` 등)로 덮어쓸 수 있다.

호출이 성공했는데 정규화가 0건이면 응답 구조를 함께 보고하므로, 한 번의 실행으로
매핑 불일치 지점을 알 수 있다. **비밀값은 어떤 경로로도 출력하지 않는다.**
존재 여부와 길이만 기록한다.

```bash
# 로컬에서도 같은 점검을 할 수 있다
python scripts/live_source_check.py --with-llm --strict
```

GitHub 러너는 국외 IP라 **law.go.kr 응답이 자주 끊기거나 시간 초과된다.** 이 워크플로에서
law.go.kr 항목이 실패해도 배포 서버의 상태를 뜻하지 않는다. 운영 서버의 판단은
`/api/diagnostics/sources`로 한다.

### CLI 일괄 검증

서버 없이 파이프라인을 돌린다. CI 실행과 폐쇄망 일괄 처리에 쓴다.

```bash
python scripts/make_sample_documents.py --out samples   # 예시 문서 생성(선택)
python scripts/verify_cli.py --input samples --out out \
    --project-name "손해배상 사건" --case-number 2026가합1234 --incident-date 2015-06-01
```

`out/`에 PDF 검증보고서·Highlight PDF·XLSX·CSV·JSON·Chain of Custody Manifest와
요약 텍스트가 생성된다. `--fail-on CRITICAL`을 주면 해당 등급 이상 Finding이 있을 때
종료코드 1을 반환하므로 파이프라인 게이트로 쓸 수 있다.

**실제 사건 문서를 공개 저장소에 커밋하지 말 것.** `samples/`는 `.gitignore` 대상이다.

## Render 배포

```
# Docker 런타임 (OCR 포함, 권장)
python -m scripts.start_server

# Native Python 런타임 (OCR 없음)
python -m scripts.start_server

# Background Worker (선택)
celery -A apps.worker.celery_app worker -l info -Q verification,report --concurrency 2
```

`render.yaml` 블루프린트로 웹 서비스·PostgreSQL·디스크·환경변수를 한 번에 만들 수 있다.
Render가 주는 `postgres://` 형식 URL은 코드가 `postgresql+psycopg://`로 정규화하므로
Internal Database URL을 그대로 붙여넣어도 된다.

**영구 디스크 없이 배포하면 업로드 원본이 재배포 때 사라져 Chain of Custody가
성립하지 않는다.** 자세한 내용은 [docs/DEPLOY_RENDER.md](docs/DEPLOY_RENDER.md).

### 배포 후 확인

관리자로 로그인한 브라우저에서 아래 주소를 연다. 비밀값은 응답에 포함되지 않는다.

| 주소 | 확인할 것 |
|---|---|
| `/api/health` | `commit`이 방금 병합한 커밋인지 |
| `/api/diagnostics` | OCR·디스크 내구성·저장소 암호화, AI 공급자별 키 보유와 `cross_check` 설정 (키가 있어도 쿼터 초과는 여기서 보이지 않는다. 실연동 점검이나 보고서의 불참 사유로 확인한다) |
| `/api/diagnostics/sources` | 이 서버에서 law.go.kr 사건번호 조회와 **판례 전문 조회**가 되는지. `verdict`가 `FULL_TEXT_UNAVAILABLE`이면 `steps[].message`가 원인이다(HTTP 상태, JSON이 아닌 응답, 형식 차이 등) |

### 보고서 생성과 진행률

보고서는 서버 뒤편에서 만들고, 화면은 1초마다 단계·진행률만 받아 온다
(`POST /api/projects/{id}/report-jobs` → `GET /api/projects/{id}/report-jobs/{job_id}`).
요청 하나가 생성이 끝날 때까지 붙잡혀 있다가 끊기던 문제("서버와 연결되지 않았거나 응답이 끊겼습니다")를 없앴다.

- 초안 창에 단계(검증 결과 불러오기 → 개인정보·미확인 항목 점검 → 형식별 작성 → 저장), 진행률, 경과 시간이 보인다.
- 창을 닫아도 생성은 계속되고, 보고서 목록 위에 진행 중인 작업이 표시된다.
- 조회가 잠시 끊기면 자동으로 다시 확인한다(최대 30회). 서버 재시작 등으로 2분 넘게 진행 기록이 멈춘 작업은 실패로 알린다.
- 한 번에 하나씩 만든다. 검증 작업·헬스체크와 CPU를 나누기 위해서다.
- 기존 `POST /api/projects/{id}/reports`(즉시 생성)는 API 호환을 위해 남겨 둔다.

생성 시간 단축(주장·인용 각 1,800건, 결과 3.2MB인 합성 표본에 6개 형식을 모두 선택한 경우. 5분 이상 → 65초, 개발 환경 측정):

| 원인 | 조치 | 측정 |
|---|---|---|
| 주소 탐지 정규식이 긴 한글 구간에서 되짚기(길이의 제곱) | 지명 길이 제한 | 사전 점검 27초 → 2.7초 |
| Word 문단을 넣을 때마다 본문 전체 탐색 | 구역 설정 위치를 한 번만 찾아 직접 삽입(결과 XML 동일) | Word 247초 → 22초 |
| PDF 기술 부록을 항목마다 낱말 단위로 줄바꿈 | 글자 폭을 한 번씩만 재어 미리 줄바꿈한 블록으로 수록 | PDF 44초 → 21초 |
| 부록에 같은 주장 전문이 4번 반복 | 전문은 `documents[].claims`에 한 번, 나머지는 주장 ID로 참조(고정본·JSON은 그대로) | 부록 6.4MB → 3.3MB |
| 확정 전 점검 때마다 개인정보 재탐지 | 내용 해시로 결과 기억 | 두 번째부터 즉시 |

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

**구현 범위**: 기본 생성·자료 제외/복구, 공식 출처 대조, 쟁점별 기준일, 주장·증거 검토표,
사람 검토·이력·임시 저장, 문서 버전 비교, 기간별 이자·변제 계산, 초안/확정 보고서,
사건별 권한, 영속 작업 복구와 중앙 비용 원장. 상세 완료 범위와 검증 근거는
[구현 현황](docs/IMPLEMENTATION_STATUS.md)에 기록한다. 모든 법률 판단을 자동화한 것은 아니다.

**설계서와 다른 점**
- Frontend는 Next.js 대신 FastAPI가 서빙하는 무의존 SPA로 구현했다. 화면 구성(대시보드·뷰어·
  Finding 패널·필터·리뷰 상태)은 제19장을 그대로 따르며, API 계약이 동일하므로 Next.js로 교체 가능하다.
- 인증·조직/사건별 RBAC, 명시적 OIDC 신원 연결, 서버 세션과 CSRF 검사가 구현되어 있다.
  실제 기관 IdP·KMS·프록시의 설정과 연동 검증은 별도 수행해야 한다.
- 화면은 쉬운 용어를 쓰고 보고서는 검사 코드·단계·범위·근거·버전을 보존한다.
  변호사의 검토 완료와 자동 검사의 확인 완료는 별도 상태다.

**의도적으로 남긴 한계**
- 행정규칙 공식 조회(`target=admrul`)는 응답 형식을 모의 응답으로만 시험했다. 운영 응답 필드가
  다르면 오류(미확인)로 남기므로 잘못 확인되지는 않지만, 실연동 점검으로 확인해야 한다.
- 주장 유형·첨부 목록·기준일 후보는 어휘 규칙으로 찾는다. 표현이 다르면 놓치거나 유형을 잘못 붙일 수
  있으므로 확정 판정에 쓰지 않고 검토 단서로만 쓴다.
- OCR 정확도는 원본 품질에 좌우된다. OCR 결과로 추출한 인용문의 문자열 대조(Level 3)는
  원본 확인이 필요하다는 경고를 함께 남긴다.
- `config/legal_mirror/`에는 판례·법령 데이터를 기본 포함하지 않는다. 검증 신뢰성이 데이터 출처에
  직접 좌우되므로, 국가법령정보에서 정식 절차로 받은 데이터만 배치해야 한다. 테스트는 가상 데이터임을
  명시한 `tests/fixtures/legal_mirror/`만 사용한다.
- Level 4(판례 취지)·Level 5(문맥 왜곡) 검증은 LLM 담당 구간이다. Provider가 없으면 `PENDING_LLM`
  상태로 남고 결코 VERIFIED로 승격되지 않는다.
- 서명 값의 암호학적 검증은 존재·구조 확인까지만 수행한다.
- 경과조치·부분 시행·판례 적용 가능성은 근거를 제시하는 검토 보조이며 법적 결론을 확정하지 않는다.
- 합성 평가 예제는 평가 도구의 동작을 검증할 뿐 실제 법률문서 정확도나 시간 절감률을 입증하지 않는다.
- 비용 한도는 같은 DB와 설정 가격을 사용하는 호출에 대한 사전 승인 원장이다. 공급자 청구액 보증은 아니다.

## 참고 Source

국가법령정보 공동활용 <https://open.law.go.kr/> · KCI <https://www.kci.go.kr/> ·
OpenAlex <https://developers.openalex.org/> · Semantic Scholar <https://www.semanticscholar.org/product/api> ·
Crossref <https://www.crossref.org/documentation/retrieve-metadata/rest-api/> ·
C2PA <https://spec.c2pa.org/> ·
OWASP Prompt Injection Prevention Cheat Sheet
<https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html> ·
NIST Generative AI <https://www.nist.gov/artificial-intelligence>

본 시스템은 검증 보조 도구이다. 진정성립·위조·고의에 관한 판단은 사용자의 책임이다.
