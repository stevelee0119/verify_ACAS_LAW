# Render 배포

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
