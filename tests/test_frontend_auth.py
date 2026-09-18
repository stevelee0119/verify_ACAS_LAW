"""Run browser-independent frontend authentication state regressions."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_frontend_authentication_states():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for frontend authentication tests")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, "--test", "tests/frontend_auth.test.cjs"],
        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
