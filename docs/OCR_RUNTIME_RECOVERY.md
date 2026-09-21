# Render OCR 복구 및 데이터 보존

## 배포 전 중단 조건

기존 서비스가 SQLite를 사용한다면 저장 경로와 영구 디스크 연결 여부가 확인되기 전에는
자동 배포·수동 재배포·런타임 변경을 진행하지 않는다. 디스크 추가도 배포를 유발할 수 있다.
DB, 업로드 원본, 감사 기록이 임시 파일시스템에 있으면 재배포로 사라질 수 있다.
`main`에 푸시하기 전에 현재 자동 배포 설정부터 확인한다.

## 백업과 복구 확인

1. Render에서 기존 서비스의 ID, 런타임, 배포 브랜치·커밋, 자동 배포 설정,
   영구 디스크와 마운트 경로를 확인한다. API 키나 DB 접속 주소는 화면·로그에 노출하지 않는다.
2. 쓰기 작업과 새 검증 접수를 중단하고 진행 작업을 마친 뒤, 실제 DB 접속 설정과
   `LV_DATA_DIR`, `LV_STORAGE_ROOT`가 가리키는 위치를 확인한다.
3. SQLite는 SQLite backup API 또는 `.backup`으로 일관된 스냅샷을 만든다.
   실행 중인 DB 파일만 복사하면 WAL에 남은 내용이 누락될 수 있다.
   원본 저장소·감사 기록·필요한 운영 설정도 같은 시점 기준으로 별도 보존한다.
4. 백업은 기존 인스턴스 밖의 승인된 암호화 저장소로 옮기고, 별도 작업 경로에서
   SQLite `PRAGMA integrity_check`, 레코드 수, 원본 파일 수와 SHA-256, 감사 체인을 검증한다.
   파일 경로를 저장하는 DB 열이 있으므로 `/opt/render/project/src`에서 `/app` 또는
   `/data`로 바뀌는 경우 경로 매핑과 복원 검증을 수행한다. 운영 DB에 일괄 문자열 치환하지 않는다.
5. 기존 `LV_PSEUDONYM_SECRET`과 인증·봉인 자료에 필요한 비밀값은 승인된 비밀 저장소에서
   보존한다. 새 값을 생성해 덮어쓰면 기존 암호화 자료를 읽지 못할 수 있다.

## 기존 서비스 전환

백업 복원 검증을 마친 뒤 현재 서비스의 Settings → Build → Source → Edit를 사용한다.

| 항목 | 값 |
| --- | --- |
| Repository / Branch | 기존 저장소 / 검증을 통과한 main 커밋 |
| Runtime | Docker |
| Dockerfile Path / Context | `./docker/Dockerfile` / `.` |
| Docker Command | `sh -c "alembic upgrade head && uvicorn apps.api.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips=*"` |
| OCR 언어 | `LV_OCR_LANG=kor+eng` |
| 기동 시 OCR 필수 검사 | `LV_REQUIRE_OCR=1` |
| OCR 요청 한도 | `LV_OCR_TIMEOUT_SECONDS=30` (한 번의 이미지 인식) |
| Worker | 별도 작업 서버가 없으면 `LV_WORKER_MODE=inprocess` |
| 저장 위치 | 실제 영구 디스크 경로와 `LV_DATA_DIR` / `LV_STORAGE_ROOT` 일치 |

기존 DB를 유지한다. OCR 복구에 PostgreSQL 전환은 필수가 아니다.
DB 접속 주소를 PostgreSQL로 바꾸기만 하면 기존 SQLite 데이터는 자동 이전되지 않는다.
영구 디스크는 비용이 발생할 수 있으며, 별도 서비스와 공유할 수 없다.
다중 작업 서버로 분리하려면 업로드 저장소 공유 설계를 먼저 수행한다.

## 완료 판정

- 배포 로그에서 Tesseract·kor/eng·fonts-nanum 설치와 한국어 스캔 PDF 시험 성공을 확인한다.
- `/api/health`의 커밋을 확인하되, 이것만으로 OCR 준비 완료라고 판정하지 않는다.
- 관리자 설정의 `ocr.available`, `ocr.languages_checked`, `ocr.ready`가 모두 `true`,
  `ocr.missing_languages=[]`, `ocr.self_test.status=PASSED`인지 확인한다.
- 기존 계정·사건·원본·검증 이력·감사 기록을 복구 전과 대조한다.
- 비밀 없는 시험 스캔 PDF를 실제 업로드해 OCR 본문, 페이지 위치, 미검증 사유와 결과 저장을 확인한다.
- OCR 미설치 상태의 과거 결과를 재사용하지 말고, 기존 업로드 자료에서 새 검증을 시작한다.

설정 화면의 시험은 합성 문서만 사용하며 사건 원문·외부 API·AI·DB를 사용하지 않는다.
관리자 진단의 인식 시험 결과는 최대 60초 재사용한다. 서버 실행 파일·언어팩을 설치하거나
환경변수를 바꾼 뒤에는 프로세스를 재시작해야 한다.

근거: [Render 런타임 변경](https://render.com/docs/native-runtimes),
[Docker 배포](https://render.com/docs/docker), [영구 디스크](https://render.com/docs/disks).
