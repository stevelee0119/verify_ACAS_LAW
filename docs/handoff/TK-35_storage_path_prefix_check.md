# TK-35 저장소 경로 검사가 접두 문자열 비교라 형제 디렉터리를 막지 못함
- 유형: 보안 방어 심층(결함 확인, 악용 경로는 확인하지 못함) · 기준 커밋: a5e89ae(경고 위치는 `main` `9933548` 기준) · 작성: evaluator 2026-10-03 · **6차 라운드 범위 밖**(6차 직후 소규모 보안 보강 후보 — 사용자 결정으로 확정, README)
- 근거 경고: CodeQL `py/path-injection`(high) **10건** + (2026-10-03 03:13 재수집, `GITHUB_ACCESS.md` 8절) `py/overly-permissive-file` 1건·`py/log-injection` 3건. 위치를 읽어 부류로 나눴다.

## 부류 1 — `_abs` 접두 비교(6건, 결함 확인)
- 위치: `packages/common/storage.py:93,102,105,106,108,127`(`LocalObjectStorage._abs`와 그 결과를 쓰는 `put_original`·`exists`).
  ```python
  p = (self.root / storage_key).resolve()
  if not str(p).startswith(str(self.root.resolve())):
      raise ValueError("path traversal detected")
  ```
  경로를 `str`로 바꿔 **접두 문자열**만 비교한다. 저장소 루트가 `/data/storage`이면 `/data/storage2/…`도 접두가 같아 통과한다.
- 재현(평가 측 격리 실행, 임시 디렉터리에 `storage`·`storage2`를 만들어 `LocalObjectStorage`로 시험): `../storage2/secret.txt` → **통과**, `originals/../../storage2/secret.txt` → **통과**, `../outside.txt` → 차단(정상).
- 악용 가능성(확인한 범위): 현재 호출부가 만드는 키는 서버가 만든 값이다 — `{project_id}/{digest}{suffix}`(`apps/api/routers/projects.py:387`), 파생본 `{project_id}/{document_id}/sanitized{suffix}`(`apps/api/routers/viewer.py:206`). 업로드 파일명은 `_safe_filename`이 `/`·`\`·제어문자와 `..`을 치환한다(`projects.py:473-479`). 프로젝트 ID는 DB 조회를 거친다. **사용자 입력이 키에 그대로 들어가는 경로는 확인하지 못했다.** 이 결함은 키 조립이 바뀌거나 새 호출부가 생길 때 방어선이 되지 못한다는 뜻이다. 모든 호출부를 끝까지 추적했다고 주장하지 않는다.

## 부류 2 — 허용 문자 검사가 이미 막는 곳(4건, 영향 없음 / 위생)
- 위치: `packages/common/storage.py:68`(`shutil.rmtree(target)`)·`:77`(`(base/area/project_id).resolve()`), `apps/api/project_purge.py:67,68`(`vault.exists()`·`vault.unlink()`).
- 이 경로는 `PROJECT_ID_RE`(`^[A-Za-z0-9_-]{1,40}$`)로 먼저 거른다(`storage.py:73`, `project_purge.py:64`). `/`·`.`이 들어갈 수 없어 **디렉터리 이탈은 불가능**하다. 다만 `re.match`+`$`는 **끝 줄바꿈을 허용**한다(`match("abc\n")` 참, `fullmatch("abc\n")` 거짓 — 평가 측 확인). 경로 이탈은 아니지만 이름에 줄바꿈이 든 파일을 만들 수 있으므로 `fullmatch`가 맞다. CodeQL은 이 사용자 정의 검사를 방어로 인식하지 못해 경고로 남긴다.

## 수용 기준(착수 시)
- `_abs`의 비교를 **경로 구성요소 단위**(`Path.is_relative_to` 등)로 바꾼다. 문자열 접두 비교를 쓰지 않는다.
- `PROJECT_ID_RE.match` 호출을 `fullmatch`로 바꾼다(`storage.py:73`, `project_purge.py:64`와 같은 정규식을 쓰는 다른 곳도 확인).
- 평가 측이 착수 시점에 먼저 strict xfail 시험을 고정한다: 위 재현 2건 + 절대 경로 키 + 심볼릭 링크로 루트 밖을 가리키는 키 + 널 문자 + 끝 줄바꿈이 든 프로젝트 ID. 지금 넣지 않는 이유: 6차 감사 의뢰서의 기대 수치(strict xfail 26건)를 바꾸지 않기 위해서다.
- 기존 저장소 시험(`tests/`의 storage·viewer 관련)이 유지된다. 키 형식·저장 위치는 바꾸지 않는다.

## 부류 3 — 원본 파일 권한(1건, 실제 개선, 03:13 재수집에서 추가)
- 위치: `packages/common/storage.py:108` `os.chmod(p, 0o444)` (CodeQL `py/overly-permissive-file` #99). 원본을 읽기 전용으로 고정하려는 의도이나 `0o444`는 **같은 서버의 모든 계정에 읽기를 허용**한다. 사건 원본의 기밀성이 불변성보다 약해진다.
- 요구: 소유자만 읽는 `0o400`으로 바꾼다(쓰기 금지로 불변성은 유지). 이미 `0o444`로 저장된 기존 원본을 어떻게 다룰지(기동 시 점검·마이그레이션)는 구현이 제안한다. Windows 등 `chmod`가 의미 없는 환경에서 실패하지 않는 기존 처리(`except OSError`)는 유지한다.

## 부류 4 — 로그에 프로젝트 ID 그대로(3건, 낮음, 03:13 재수집에서 추가)
- 위치: `apps/api/project_purge.py:62,70`, `apps/api/routers/projects.py:252`(CodeQL `py/log-injection` #100·#101·#102). 같은 호출부에서 프로젝트 ID를 `%s`로 기록한다. 프로젝트 ID 검사가 `match`+`$`라 **끝 줄바꿈이 든 ID가 통과**하면 로그 줄을 위조할 수 있다(부류 2와 같은 원인).
- 요구: `fullmatch`로 ID를 엄격히 검사하고(부류 2), 로그에는 `%r` 또는 줄바꿈 이스케이프를 쓴다. `apps/worker/runner.py:46`(#103)은 이미 `%r`이고 운영자 환경변수 값이라 이 티켓 범위가 아니다(오탐).
- 평가 측 시험(착수 시): 끝 줄바꿈이 든 프로젝트 ID가 로그 한 줄에 그대로 실리지 않을 것.
