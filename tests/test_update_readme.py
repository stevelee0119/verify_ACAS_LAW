"""README '버전별 변경 내역' 표 자동 생성."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location("update_readme", ROOT / "scripts" / "update_readme.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_readme_table_is_in_sync_with_releases_and_program_version():
    """커밋된 README 표가 releases.json·프로그램 버전과 일치해야 한다(푸시 전에 스크립트를 실행)."""
    module = _module()
    releases = module.load_releases(add_missing=False)
    assert module.current_version() in {item["version"] for item in releases}
    assert module.updated_readme(releases) == (ROOT / "README.md").read_text(encoding="utf-8")


def test_missing_version_is_filled_from_the_last_commit(tmp_path, monkeypatch):
    module = _module()
    releases = tmp_path / "releases.json"
    releases.write_text(json.dumps([{"version": "0.1.0", "date": "2026-01-01", "changes": ["처음"]}]), encoding="utf-8")
    config = tmp_path / "config.py"
    config.write_text('    version: str = "0.2.0"\n', encoding="utf-8")
    monkeypatch.setattr(module, "RELEASES", releases)
    monkeypatch.setattr(module, "CONFIG", config)
    monkeypatch.setattr(module, "_last_commit_subject", lambda: "feat: 새 기능")
    rows = module.load_releases()
    assert [r["version"] for r in rows] == ["0.1.0", "0.2.0"] and rows[-1]["changes"] == ["feat: 새 기능"]
    table = module.render_table(rows)
    assert table.index("| 0.2.0 |") < table.index("| 0.1.0 |")     # 최신 버전이 위


def test_versions_sort_numerically_and_cells_are_escaped():
    module = _module()
    rows = [{"version": v, "date": "d", "changes": ["a|b"]} for v in ("0.6.10", "0.6.9", "0.7.0")]
    ordered = sorted(rows, key=lambda r: module._version_key(r["version"]))
    assert [r["version"] for r in ordered] == ["0.6.9", "0.6.10", "0.7.0"]
    assert "a\\|b" in module.render_table(ordered)
