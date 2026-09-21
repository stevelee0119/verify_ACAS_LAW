"""Migrate, then start the API without shell quoting or variable expansion."""
from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    try:
        port = int(os.environ.get("PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        print("PORT must be an integer between 1 and 65535.", file=sys.stderr)
        return 2

    print("Applying database migrations...", flush=True)
    try:
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    except subprocess.CalledProcessError as exc:
        print("Database migration failed; API was not started.", file=sys.stderr)
        return exc.returncode if exc.returncode > 0 else 1

    # Render terminates TLS at its proxy; other hosts trust only loopback by default.
    trusted_proxies = os.environ.get(
        "FORWARDED_ALLOW_IPS", "*" if os.environ.get("RENDER_SERVICE_ID") else "127.0.0.1"
    )
    command = [
        sys.executable, "-m", "uvicorn", "apps.api.main:app",
        "--host", "0.0.0.0", "--port", str(port),
        "--proxy-headers", "--forwarded-allow-ips", trusted_proxies,
    ]
    print(f"Starting API on port {port}...", flush=True)
    # Replace PID 1 so the server receives container shutdown signals directly.
    os.execv(sys.executable, command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
