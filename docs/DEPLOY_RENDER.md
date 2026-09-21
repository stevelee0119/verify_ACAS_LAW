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
| Docker Command | `sh -c "alembic upgrade head && uvicorn apps.api.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips=*"` |
| Health Check Path | `/api/health` |

### Native Python 런타임

기본 Python 패키지 설치만으로 Tesseract 실행 파일과 언어팩이 설치되지는 않는다.
OCR 구성 요소가 없으면 스캔 PDF·이미지 본문은 `UNVERIFIED`로 남는다.
운영 OCR은 아래 Docker 구성으로 설치·실제 인식 검사를 함께 수행한다.

| 항목 | 값 |
|---|---|
| Build Command | `pip install -r requirements.txt` |
| Start Command | `alembic upgrade head && uvicorn apps.api.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips=*` |

### Background Worker (선택)

문서량이 많을 때만 추가한다. Redis 인스턴스가 필요하다.

| 항목 | 값 |
|---|---|
| Start Command | `celery -A workers.celery_app worker -l info -Q verification,report --concurrency 2` |

Worker를 두지 않으면 웹 서비스에 `LV_WORKER_MODE=inprocess`를 설정한다.
Redis 없이 DB 작업 큐와 임대 기반 복구를 사용한다. 다중 프로세스의 작업 중복 실행은
임대와 실행 세대 번호로 차단한다. 장애 복구 시 재시도 여부는 작업 상태에서 확인한다.

## `$PORT`

Render는 `PORT` 환경변수로 포트를 지정한다. `--port $PORT`와 `--host 0.0.0.0`이
모두 있어야 헬스체크가 통과한다. 둘 중 하나라도 빠지면 "포트를 열지 못했다"로 배포가 실패한다.

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
| `LV_SESSION_TTL_HOURS` | 세션 유효시간(기본 12) |

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

기존 서비스의 배포 브랜치를 `main`으로 확인하고 테스트를 통과한 커밋을 배포한다.
자동 배포가 꺼져 있으면 Dashboard의 Manual Deploy를 사용한다. 기존 환경변수,
DB, 디스크는 보존한다. Blueprint를 새로 적용하여 서비스를 중복 생성하지 않는다.
Deploys의 실제 가동 커밋과 `/api/health`의 `commit`이 일치해야 배포 완료로 판정한다.
실패 시 먼저 배포 로그와 마이그레이션을 확인하고, 검토 없이 DB downgrade를 실행하지 않는다.
