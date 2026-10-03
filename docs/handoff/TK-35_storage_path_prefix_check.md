# TK-35 저장소 경로 검사가 접두 문자열 비교라 형제 디렉터리를 막지 못함
- 유형: 보안 방어 심층(결함 확인, 악용 경로는 확인하지 못함) · 기준 커밋: 028ca14 · 작성: evaluator 2026-10-03 · **6차 라운드 범위 밖**(6차 직후 소규모 보안 보강 후보 — 사용자 결정 대기)
- 근거 경고: CodeQL "Uncontrolled data used in path expression"(high). 경고 위치는 평가 측이 읽지 못해(`GITHUB_ACCESS.md` 6절) **이 코드가 그 경고의 지점인지는 확정하지 못했다.**

## 증상·증거
- `packages/common/storage.py:92-96` `LocalObjectStorage._abs`:
  ```python
  p = (self.root / storage_key).resolve()
  if not str(p).startswith(str(self.root.resolve())):
      raise ValueError("path traversal detected")
  ```
  경로를 `str`로 바꿔 **접두 문자열**만 비교한다. 저장소 루트가 `/data/storage`이면 `/data/storage2/…`도 접두가 같아 통과한다.
- 재현(평가 측 격리 실행, 임시 디렉터리에 `storage`·`storage2`를 만들어 `LocalObjectStorage`로 시험): 
  - `../storage2/secret.txt` → **통과**(차단 안 됨, `storage2/secret.txt`로 해석)
  - `originals/../../storage2/secret.txt` → **통과**
  - `../outside.txt` → 차단(정상)
- `_abs`는 `put`·`get`·`path`·`exists` 등 저장소 인터페이스 전체가 거친다(`storage.py:101,115,121,124,127`).

## 악용 가능성 평가(확인한 범위)
- 현재 호출부가 만드는 키는 서버가 만든 값이다: `{project_id}/{digest}{suffix}`(`apps/api/routers/projects.py:387`), 파생본 `{project_id}/{document_id}/sanitized{suffix}`(`apps/api/routers/viewer.py:206`). 업로드 파일명은 `_safe_filename`이 `/`·`\`·제어문자를 `_`로, `..`을 `_`로 바꾼다(`projects.py:473-479`). 프로젝트 ID는 DB 조회를 거친다.
- 따라서 **사용자 입력이 키에 그대로 들어가는 경로는 확인하지 못했다.** 이 결함은 앞으로 키 조립이 바뀌거나 새 호출부가 생길 때 방어선이 되지 못한다는 뜻이다. 모든 호출부(`apps/`·`packages/`·`workers/`)를 끝까지 추적했다고 주장하지 않는다(위 grep 범위: `.path(`·`_abs(` 호출).

## 수용 기준(착수 시)
- 비교를 **경로 구성요소 단위**(`Path.is_relative_to` 등)로 바꾼다. 문자열 접두 비교를 쓰지 않는다.
- 평가 측이 착수 시점에 먼저 strict xfail 시험을 고정한다(위 재현 2건 + 절대 경로 키 + 심볼릭 링크로 루트 밖을 가리키는 키 + 널 문자). 지금 넣지 않는 이유: 6차 감사 의뢰서의 기대 수치(strict xfail 26건)를 바꾸지 않기 위해서다.
- 기존 저장소 시험(`tests/`의 storage·viewer 관련)이 유지된다. 키 형식·저장 위치는 바꾸지 않는다.
