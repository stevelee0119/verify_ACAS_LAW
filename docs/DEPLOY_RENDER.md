# Render 배포

## 먼저: 배포 브랜치를 확인한다

Render 서비스가 가리키는 브랜치에 `render.yaml`·`alembic.ini`·`migrations/`가 있어야 한다.
이것들이 없는 브랜치를 배포하면 Start Command의 첫 단계에서 끝난다.

```
FAILED: No 'script_location' key found in configuration.   ← alembic 설정·마이그레이션 없음
Can't load plugin: sqlalchemy.dialects:postgres            ← URL 정규화 없음
No module named 'psycopg2'                                  ← psycopg 미설치
```

세 가지 모두 배포 지원 커밋이 빠진 브랜치에서 나타난다. 확인 방법은 다음과 같다.

```bash
git ls-tree --name-only <배포브랜치> -- render.yaml alembic.ini migrations
grep -E "^(psycopg|pgvector)" requirements.txt
```

Render 대시보드에서는 서비스 → **Settings → Build & Deploy → Branch**에서 바꿀 수 있다.

## Start Command

런타임 선택에 따라 다르다. **OCR이 필요하면 Docker를 쓴다.**

### Docker 런타임 (권장)

Dockerfile에 tesseract 한국어팩이 들어 있어 스캔 문서까지 처리된다.

| 항목 | 값 |
|---|---|
| Runtime | Docker |
| Dockerfile Path | `./docker/Dockerfile` |
| Docker Command | `python -m scripts.start_server` (또는 비워 두어 Dockerfile의 동일한 기본 명령 사용) |
| Health Check Path | `/api/health` |

시작 모듈은 DB 마이그레이션 성공 후에만 API를 실행한다. `PORT` 환경변수를 직접 읽고,
쉘이나 따옴표 재해석 없이 각 인자를 전달한다. Render에서는 프록시를 신뢰하며,
다른 환경의 기본 신뢰 범위는 루프백이다. `FORWARDED_ALLOW_IPS`로 명시할 수 있다.

### `sh: 1: alembic upgrade head && uvicorn ...: not found` / 종료 코드 127

명령 전체가 하나의 실행 파일 이름으로 처리된 오류다. `alembic: not found`와는 다르며,
이 로그만으로 패키지 누락이라고 진단하지 않는다. Docker Command의 기존 `sh -c ...`를
모두 지우고 **따옴표 없이** `python -m scripts.start_server`로 교체한 뒤 최신 커밋을 배포한다.
대시보드에 저장된 명령은 GitHub의 `render.yaml`만 수정해도 바뀌는 것이 아니다.
Docker 빌드 로그의 `CACHED`는 실패가 아니라 이전에 성공한 레이어의 재사용이다.

### Native Python 런타임

기본 Python 패키지 설치만으로 Tesseract 실행 파일과 언어팩이 설치되지는 않는다.
OCR 구성 요소가 없으면 스캔 PDF·이미지 본문은 `UNVERIFIED`로 남는다.
운영 OCR은 아래 Docker 구성으로 설치·실제 인식 검사를 함께 수행한다.

| 항목 | 값 |
|---|---|
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python -m scripts.start_server` |

### Background Worker (선택)

문서량이 많을 때만 추가한다. Redis 인스턴스가 필요하다.

| 항목 | 값 |
|---|---|
| Start Command | `celery -A workers.celery_app worker -l info -Q verification,report --concurrency 2` |

Worker를 두지 않으면 웹 서비스에 `LV_WORKER_MODE=inprocess`를 설정한다.
Redis 없이 DB 작업 큐와 임대 기반 복구를 사용한다. 다중 프로세스의 작업 중복 실행은
임대와 실행 세대 번호로 차단한다. 장애 복구 시 재시도 여부는 작업 상태에서 확인한다.

## `$PORT`

Render는 `PORT` 환경변수로 포트를 지정한다. 시작 모듈이 이를 검증해 `--port`에 전달하고
`--host 0.0.0.0`으로 바인딩한다. `PORT` 미지정 시 로컬 기본값은 8000이다.
CI는 실제 Docker 이미지의 기본 명령과 명시적 시작 명령을 각각 실행하여,
10000번 포트 헬스체크, DB 마이그레이션 완료, 정상 종료까지 검사한다.

## 접속정보

Render가 주는 PostgreSQL URL은 `postgres://` 형식이라 SQLAlchemy가 인식하지 못하고,
`postgresql://`로 바꿔도 기본 드라이버(psycopg2)를 찾는다. 본 프로젝트는 psycopg3를 쓰므로
`resolve_database_url()`이 `postgresql+psycopg://`로 정규화한다.
**Internal Database URL을 그대로 붙여넣어도 된다.**

변수명은 `LV_DATABASE_URL`이 우선이고 없으면 `DATABASE_URL`을 쓴다.
브로커도 `LV_CELERY_BROKER` → `REDIS_URL` 순으로 찾는다.

## 반드시 확인할 것

**1. 영구 디스크 없이 배포하면 원본이 사라진다.**
업로드 원본은 `LV_DATA_DIR` 아래 저장된다. Render의 기본 파일시스템은 재배포·재시작 때
초기화되므로, 디스크를 붙이지 않으면 제15.1장 Immutable Original과 Chain of Custody가
성립하지 않는다. Disk를 `/data`에 마운트하고 `LV_DATA_DIR=/data`를 설정한다.
무료 플랜은 디스크를 지원하지 않는다.

**2. 운영 인증을 명시한다.** `LV_AUTH_MODE=multi-user`를 설정한다.
비밀번호 로그인, API 토큰, 등록된 OIDC 계정 모두 기관·사건별 권한 검사를 사용한다.
Render에서는 모드가 누락되어도 로컬 관리자 모드로 열리지 않는다.
`local` 모드는 개인 PC의 로컬 작업용이며 공개 배포에 사용하지 않는다.

**3. `LV_PSEUDONYM_SECRET`을 교체한다.** 실명-가명 매핑 암호화 키다.
블루프린트는 `generateValue: true`로 자동 생성하지만 운영에서는 KMS·Vault로 관리한다.
**이 값을 잃으면 기존 가명의 원본을 복원할 수 없다.**

**4. PostgreSQL 마이그레이션에는 pgvector가 필요하다.** 최초 운영 마이그레이션은
`CREATE EXTENSION IF NOT EXISTS vector`와 벡터 인덱스를 생성한다. 확장 설치 및
생성 권한을 사전에 확인한다. 이 단계가 실패했는데 JSON으로 자동 강등되었다고
판단하지 않는다. 기존 운영 데이터베이스에는 검증 없이 스키마를 다시 만들지 않는다.

## 블루프린트로 한 번에 만들기

`render.yaml`이 웹 서비스·PostgreSQL·디스크·환경변수를 정의한다.

Dashboard → **New → Blueprint** → 저장소 선택 → Apply.
`sync: false`로 표시된 API Key만 대시보드에서 직접 입력하면 된다.

## 배포 후 첫 확인 — 런타임이 docker인지, OCR이 살아 있는지

배포가 끝났다고 검증이 되는 것은 아니다. OCR이 없으면 이미지·스캔 PDF는 본문을
읽지 못하고, 그 실행 결과는 "이상 없음"이 아니라 "확인하지 못함"이다.
배포 직후 반드시 아래를 확인한다.

```bash
curl -s https://<서비스>.onrender.com/api/health | jq
```

헬스체크의 `version`과 `commit`을 배포한 Git 커밋과 대조한다. 헬스체크에는
자격 증명이나 내부 설정을 노출하지 않는다. 아래 진단은 관리자 로그인 후
`/api/diagnostics`에서 확인한다.

- `verdict: "READY"` → 한국어 시험 스캔 PDF의 본문과 위치 인식을 확인했다.
  실제 사건 문서의 인식 정확도나 전체 페이지 처리까지 보증하지는 않는다.
- `verdict: "DEGRADED"`, `blocking: ["ocr"]` → OCR 실행 파일·언어팩 또는 실제 인식
  점검 실패다. Docker 여부는 배포 설정과 빌드 로그에서 별도로 확인한다.
- `/api/health`는 서버 생존 확인이다. OCR 준비 판정으로 사용하지 않는다.

확인할 필드:

| 필드 | 정상값 | 뜻 |
|---|---|---|
| `capabilities.ocr.available` | `true` | tesseract 실행 및 필수 언어팩 확인 |
| `capabilities.ocr.binary_path` | `/usr/bin/tesseract` | 바이너리 위치 |
| `capabilities.ocr.languages_checked` | `true` | 언어 목록 조회 성공 |
| `capabilities.ocr.missing_languages` | `[]` | 필수 언어 누락 없음. `null`은 확인 불가 |
| `capabilities.ocr.self_test.status` | `PASSED` | 한국어 시험 스캔 PDF 인식 성공 |
| `capabilities.ocr.ready` | `true` | OCR 준비 확인 |
| `capabilities.rasterizer.available` | `true` | 스캔 PDF 래스터화 가능 |
| `capabilities.database.dialect` | `postgresql` | 운영 DB 연결됨 |
| `capabilities.source_keys_present` | 필요한 키가 `true` | Render Environment에 입력됨 |

`source_keys_present`는 **존재 여부만** 알린다. 값은 담지 않는다.

### 런타임을 확인하는 다른 방법

1. **Render 대시보드** — 서비스의 Settings에서 런타임과 Dockerfile 경로를 확인한다.
   docker 런타임이면 `dockerfilePath`가 `./docker/Dockerfile`로 지정되어 있다.
2. **배포 로그** — docker 런타임은 이미지 빌드 단계(`Dockerfile` 각 `RUN` 명령,
   `apt-get install ... tesseract-ocr`)가 로그에 찍힌다. Native 런타임은
   빌드 명령(`pip install -r requirements.txt`)만 찍히고 apt 단계가 없다.

### docker가 아니었다면

기존 서비스의 Settings → Build → Source → Edit에서 런타임을 Docker로 바꿀 수 있다.
대시보드에서 수동 생성한 서비스는 저장소의 `render.yaml`이 자동 적용된다고 가정하지 않는다.
서비스 삭제나 중복 Blueprint 생성 대신, 백업 후 기존 서비스의 구성을 대조한다.
전환 시 저장 경로도 바뀔 수 있으므로 [OCR 전환 절차](OCR_RUNTIME_RECOVERY.md)를 먼저 따른다.

Dockerfile은 한국어·영어 언어팩과 시험용 한국어 글꼴을 설치하고 빌드 중
`python -m scripts.check_ocr_runtime`을 실행한다. 인식 실패는 빌드 실패다.
CI는 실제 운영 이미지에서도 네트워크 없이 같은 검사를 실행한다.
Docker의 `LV_REQUIRE_OCR=1`은 시작 시에도 검사를 강제해 OCR 미준비 상태로 기동하지 않게 한다.
텍스트 전용 환경에서는 명시적으로 `LV_REQUIRE_OCR=0`을 사용할 수 있지만 OCR 복구로 보지 않는다.

## 인증 설정 (배포 전 필수)

운영 모드는 `multi-user`다. 최초 관리자 없이 사건 API가 열리지는 않는다.
배포 전에 최초 관리자를 만들고 비밀번호 로그인부터 확인한다.
브라우저 세션은 HttpOnly 쿠키를 사용하고, 변경 요청은 동일 출처 검사로 보호한다.
`LV_PUBLIC_ORIGIN`에는 실제 HTTPS 접속 주소를 설정하는 것이 좋다.
위의 프록시 신뢰 옵션은 Render가 서비스 앞에서 TLS를 종료하는 환경용이다.
일반 서버에서는 `*` 대신 실제 신뢰할 프록시 주소를 지정한다.

### Render 환경변수로 부트스트랩

Environment 탭에 아래를 넣고 배포하면 기동 시 관리자 계정이 생성된다.

| Key | 값 |
|---|---|
| `LV_AUTH_MODE` | `multi-user` |
| `LV_PUBLIC_ORIGIN` | 실제 서비스의 HTTPS 주소 |
| `LV_BOOTSTRAP_ADMIN_EMAIL` | 관리자 이메일 |
| `LV_BOOTSTRAP_ADMIN_PASSWORD` | 10자 이상 비밀번호 |
| `LV_BOOTSTRAP_ADMIN_NAME` | 표시 이름(선택) |
| `LV_SESSION_TTL_HOURS` | 브라우저 미사용 제한(기본 24시간). 인증된 요청과 검증 진행 조회 시 자동 연장 |
| `LV_SESSION_ABSOLUTE_HOURS` | 최초 로그인부터 자동 연장 상한(기본 168시간, 7일) |

계정이 만들어진 뒤에는 이 변수들이 무시된다. **첫 로그인 후 비밀번호를 바꾸고
두 환경변수를 삭제한다.** 환경변수는 대시보드에서 다시 볼 수 있다.

### 셸에서 직접 생성

```bash
python scripts/create_admin.py --email admin@example.com
```

비밀번호는 인자로 받지 않는다. 명령행 인자는 프로세스 목록과 셸 기록에 남는다.

### 역할

| 역할 | 권한 |
|---|---|
| `ADMIN` | 기관 내 계정·사건 관리, 사건별 감사 이력, 런타임 진단 |
| `MEMBER` | 사건 생성·문서 업로드·검증 실행·봉인 원문 열람 |
| `VIEWER` | 읽기 전용. 봉인 원문 열람과 변경 불가 |

접근 권한이 없는 사건은 403이 아니라 **404**를 돌려준다. 403은 그 ID의 사건이
존재한다는 사실을 알려 주기 때문이다.

전체 기관에 걸친 감사 체인 검증과 전역 설정 변경은 로컬 운영자에게만 허용한다.
사건별 내보내기는 해당 사건의 이벤트 해시 검증과 전체 체인 검증을 구분하여 기록한다.

### 마이그레이션

기존 배포본이 있으면 인증 스키마를 적용해야 한다.

```bash
alembic heads          # 통합 head 1개인지 확인
alembic upgrade head
```

배포 전에 운영 DB 백업과 영구 디스크 상태를 확인한다. 두 브랜치의 기존 이력은
재작성하지 않고 merge revision으로 연결한다. 기존 사용자 ID·비밀번호 해시·세션·
사건 소유권·멤버십을 보존하고 기존 사용자에 필요한 신원 계정만 보완한다.
비밀번호가 없는 토큰 전용 사용자는 토큰/OIDC 경로를 사용하며, 비밀번호 로그인이
필요하면 관리자가 기존 계정에 비밀번호를 설정한다. 계정을 중복 생성하지 않는다.

## 기존 서비스 갱신

### 파일 등록 중 연결 오류

`/api/health` 성공은 업로드 성공이나 OCR 준비 완료를 의미하지 않는다.
파일 등록은 OCR 전에 수행된다. 화면의 연결 오류만으로 메모리 부족이나 파일 손상으로 단정하지 않는다.

- 기기에서 파일을 읽지 못하면 서버에 전송하지 않는다. 클라우드 파일은 기기에 내려받아 다시 선택한다.
- 전송 응답이 끊기면 `등록 확인 필요`로 표시하고, 해당 사건의 자료 목록에서 SHA-256이 같은 원본을 확인한다.
  확인 버튼은 조회만 수행하며 불확실한 POST를 자동 재전송하지 않는다.
- HTTP 오류와 성공 응답의 잘못된 JSON은 연결 실패와 구분한다. 파일별 상태는 화면에 유지된다.
- 저장소/DB 접근 실패는 HTTP 503과 오류 코드, `X-Request-ID` 문의 번호를 반환한다.
  Render Logs의 `upload_failed request_id=...`와 대조한다. 로그에는 파일명·원문·접속 주소·SQL 인자를 남기지 않는다.
- `UPLOAD_STORAGE_UNAVAILABLE`이면 저장소 권한과 용량, `UPLOAD_DATABASE_UNAVAILABLE`이면 DB 연결을 확인한다.
  요청이 서버에 도달하지 않았거나 프로세스가 강제 종료되면 문의 번호가 없을 수 있다.

Docker CI는 임시 관리자와 합성 DOCX만 사용하여 로그인, 업로드, 중복 방지, 원본 다운로드,
관리자 OCR 준비 상태를 검사한다. `scripts.check_upload_runtime`은 폐기 가능한 시험 컨테이너 전용이며
운영 서비스에서 실행하지 않는다.

### 외부 출처 지연과 자동 재조회

검증 실행의 외부 출처 GET 조회는 시간 초과, 연결 장애, HTTP 408/429/5xx에 한해 기본 3회까지
자동 시도한다. 기본 요청 제한은 12초, 재시도는 24초와 36초이며 각 요청은 최대 45초다.
401/403 등 권한 오류, 키 미설정, 정상 응답의 검색 결과 없음은 장애 재시도 대상이 아니다.
429/503 등의 `Retry-After`는 초 또는 HTTP 날짜로 해석하며, 지정된 시각보다 일찍 재요청하지 않는다.
긴 대기를 현재 작업에서 감당할 수 없으면 원인을 남기고 종료한다.

- 이전의 프로젝트 전체 120초 공유 한도를 문서별 한도로 변경했다.
  기본 한도는 `min(900, max(120, 기준일별 인용 검토 수 × 30))`초다.
- 첫 조회에서 지연된 인용만 같은 기준일로 한 번 더 검토한다. 문서별로 최대 120초를 추가 배정한다.
  원문 파싱·OCR·외부 AI 분석은 이 재조회 때문에 반복 실행하지 않는다.
- 동일 출처의 반복 장애는 잠시 조회를 보류하고 회복 확인을 수행한다.
  접근 권한 오류와 서버가 지정한 대기 시각은 다음 문서에서도 보존한다.
- 성공한 응답은 해당 검증 실행 안에서만 재사용한다. 사건·검증 실행을 넘어 공유하지 않으며
  API 키·요청 인자·법령 버전이 다른 요청은 같은 캐시로 처리하지 않는다.
- 진행 화면에 응답 대기·재조회 회차·지연 인용 재확인을 표시한다. 요청과 대기 중에도 취소를 확인한다.
- 결과 JSON의 `documents[].engine_data.source_lookup`에 문서별 시간 사용량을,
  `legal_verdicts[].source_lookup`에 요청 횟수·캐시 사용·재조회 결과를 보존한다.
  `RECOVERED`는 통신 회복을 뜻하며 법률 인용 전체가 `VERIFIED`라는 뜻은 아니다.
  최종 미검증 사유는 화면과 보고서에 남긴다. 회복 전의 조회 실패 기록도 감사 근거로 보존한다.

`.env.example`의 `LV_SOURCE_LOOKUP_*`으로 한도를 조정한다. 새 검증 작업에는 설정을 고정해
실행 기록에 보존한다. 기존 작업의 규칙·실행 설정과 현재 설정이 달라지면 재시도가 거부될 수 있으므로
업데이트된 규칙을 적용하려면 새 검증을 실행한다.
관리자 연결 상태의 기술 진단 정보에 현재 `source_lookup` 설정이 표시된다.

일시 지연만으로 곧바로 미검증 처리되는 경우를 줄이는 기능이지, 외부 기관 장애나 미수록 원문까지
확인된 것으로 바꾸는 기능은 아니다. 자동 재조회도 끝내 실패하면 `UNVERIFIED`와 그 사유를 남긴다.
서비스 복구 후 검증 이력의 재시도 또는 새 검증을 실행한다. 종료된 결과가 나중에 자동 변경되지는 않는다.

구현 참고: [HTTPX 재시도 범위](https://www.python-httpx.org/advanced/transports/),
[HTTP Retry-After 규약](https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after).

### 코드 배포

기존 서비스의 배포 브랜치를 `main`으로 확인하고 테스트를 통과한 커밋을 배포한다.
자동 배포가 꺼져 있으면 Dashboard의 Manual Deploy를 사용한다. 기존 환경변수,
DB, 디스크는 보존한다. Blueprint를 새로 적용하여 서비스를 중복 생성하지 않는다.
Deploys의 실제 가동 커밋과 `/api/health`의 `commit`이 일치해야 배포 완료로 판정한다.
실패 시 먼저 배포 로그와 마이그레이션을 확인하고, 검토 없이 DB downgrade를 실행하지 않는다.
