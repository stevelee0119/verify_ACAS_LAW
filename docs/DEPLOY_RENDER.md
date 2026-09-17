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
| Docker Command | `sh -c "alembic upgrade head && uvicorn apps.api.main:app --host 0.0.0.0 --port $PORT"` |
| Health Check Path | `/api/health` |

### Native Python 런타임

시스템 패키지를 설치할 수 없어 OCR이 비활성화된다. 스캔 PDF·이미지 본문은
`UNVERIFIED`로 남고 나머지 검증은 정상 동작한다.

| 항목 | 값 |
|---|---|
| Build Command | `pip install -r requirements.txt` |
| Start Command | `alembic upgrade head && uvicorn apps.api.main:app --host 0.0.0.0 --port $PORT` |

### Background Worker (선택)

문서량이 많을 때만 추가한다. Redis 인스턴스가 필요하다.

| 항목 | 값 |
|---|---|
| Start Command | `celery -A workers.celery_app worker -l info -Q verification,report --concurrency 2` |

Worker를 두지 않으면 웹 서비스에 `LV_WORKER_MODE=inprocess`를 설정한다.
Redis 없이 동작하며, 브로커 장애 시에도 인프로세스로 강등되므로 기능이 멈추지 않는다.

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

**2. 인증이 없다.** 이 애플리케이션에는 로그인·RBAC이 구현되어 있지 않다.
Render에 그대로 올리면 URL을 아는 누구나 문서를 열람·업로드할 수 있다.
공개 배포 전에 인증을 붙이거나, 최소한 접근을 제한한 상태로만 사용한다.

**3. `LV_PSEUDONYM_SECRET`을 교체한다.** 실명-가명 매핑 암호화 키다.
블루프린트는 `generateValue: true`로 자동 생성하지만 운영에서는 KMS·Vault로 관리한다.
**이 값을 잃으면 기존 가명의 원본을 복원할 수 없다.**

**4. pgvector가 없어도 동작한다.** Render PostgreSQL에서 `vector` 확장을 쓸 수 없으면
`embedding` 컬럼이 JSON으로 자동 대체되며 마이그레이션은 실패하지 않는다.

## 블루프린트로 한 번에 만들기

`render.yaml`이 웹 서비스·PostgreSQL·디스크·환경변수를 정의한다.

Dashboard → **New → Blueprint** → 저장소 선택 → Apply.
`sync: false`로 표시된 API Key만 대시보드에서 직접 입력하면 된다.

## 배포 후 첫 확인 — 런타임이 docker인지, OCR이 살아 있는지

배포가 끝났다고 검증이 되는 것은 아니다. OCR이 없으면 이미지·스캔 PDF는 본문을
읽지 못하고, 그 실행 결과는 "이상 없음"이 아니라 "확인하지 못함"이다.
배포 직후 반드시 아래를 확인한다.

```bash
curl -s https://<서비스>.onrender.com/api/diagnostics | jq
```

- `verdict: "READY"` → 이미지·스캔 문서까지 본문 추출이 가능하다.
- `verdict: "DEGRADED"`, `blocking: ["ocr"]` → **런타임이 docker가 아니다.**
  Native Python 런타임에는 시스템 패키지(tesseract)를 설치할 수 없다.

확인할 필드:

| 필드 | 정상값 | 뜻 |
|---|---|---|
| `capabilities.ocr.available` | `true` | tesseract 실행 가능 |
| `capabilities.ocr.binary_path` | `/usr/bin/tesseract` | 바이너리 위치 |
| `capabilities.ocr.missing_languages` | `[]` | 한국어 데이터 설치됨 |
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

`render.yaml`을 사용하는 Blueprint로 다시 만드는 편이 확실하다. 대시보드에서 수동
생성한 서비스는 `render.yaml`을 읽지 않으므로, `runtime: docker`뿐 아니라
`LV_ALLOW_NETWORK`·`LV_DATA_DIR` 같은 환경변수도 적용되지 않는다.

## 인증 설정 (배포 전 필수)

인증을 끄는 스위치는 없다. 계정이 하나도 없으면 API는 503으로 거부한다.
배포 전에 최초 관리자를 만들어야 한다.

### Render 환경변수로 부트스트랩

Environment 탭에 아래를 넣고 배포하면 기동 시 관리자 계정이 생성된다.

| Key | 값 |
|---|---|
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
| `ADMIN` | 계정 관리, 기관 내 모든 사건, 감사 체인 검증, 런타임 진단 |
| `MEMBER` | 사건 생성·문서 업로드·검증 실행·봉인 원문 열람 |
| `VIEWER` | 읽기 전용. 봉인 원문 열람과 변경 불가 |

접근 권한이 없는 사건은 403이 아니라 **404**를 돌려준다. 403은 그 ID의 사건이
존재한다는 사실을 알려 주기 때문이다.

### 마이그레이션

기존 배포본이 있으면 인증 스키마를 적용해야 한다.

```bash
alembic upgrade head   # b2d5f88c0e31
```

기존 사용자 행이 있다면 `password_hash`가 비어 있어 로그인할 수 없다.
관리자가 계정을 다시 만들거나 비밀번호를 설정해야 한다.
