# 02_fix_windows_path_in_test_no_case_literals

- **무엇이**: `tests/acceptance/test_no_case_literals.py` 및 `scripts/check_case_literals.py`의 파일 경로 정규화 (`.as_posix()`)
- **왜**: Windows 환경에서 `Path.relative_to()` 결과가 `packages\legal_engine\...`와 같이 백슬래시(`\`)로 반환되어, 하드코딩된 허용 목록(whitelist)의 POSIX 스타일 경로(`packages/legal_engine/...`)와 일치하지 않아 단언 실패가 발생함.
- **제안하는 변경**:
  경로 비교 시 `.as_posix()` 또는 `str(path).replace("\\", "/")`로 통일:
  ```python
  rel_str = rel_path.as_posix()
  ```
