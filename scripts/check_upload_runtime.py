"""CI-only authenticated upload check against an isolated disposable container."""
import hashlib
import io
import json
import os

import httpx
from docx import Document


def main():
    if os.getenv("LV_UPLOAD_SMOKE_TEST") != "1":
        raise RuntimeError("Run only in a disposable test container with LV_UPLOAD_SMOKE_TEST=1")
    base = "http://127.0.0.1:" + os.getenv("PORT", "8000")
    document = Document()
    document.add_paragraph("Synthetic upload check. No case documents.")
    buffer = io.BytesIO()
    document.save(buffer)
    data = buffer.getvalue()
    with httpx.Client(base_url=base, headers={"Origin": base}, timeout=20, trust_env=False) as client:
        login = client.post("/api/auth/login", json={
            "email": os.environ["LV_BOOTSTRAP_ADMIN_EMAIL"],
            "password": os.environ["LV_BOOTSTRAP_ADMIN_PASSWORD"],
        })
        login.raise_for_status()
        project = client.post("/api/projects", json={"name": "CI upload smoke"})
        project.raise_for_status()
        path = f"/api/projects/{project.json()['id']}/documents"
        uploaded = client.post(path, files={"file": ("synthetic.docx", data)})
        assert uploaded.status_code == 201
        saved = uploaded.json()
        assert saved["sha256"] == hashlib.sha256(data).hexdigest()
        assert len(uploaded.headers["X-Request-ID"]) == 32
        repeated = client.post(path, files={"file": ("synthetic.docx", data)})
        assert repeated.status_code == 201 and repeated.json()["id"] == saved["id"]
        assert len(client.get(path).json()) == 1
        original = client.get(f"/api/documents/{saved['id']}/original")
        assert original.status_code == 200 and original.content == data
        diagnostics = client.get("/api/diagnostics")
        diagnostics.raise_for_status()
        assert diagnostics.json()["capabilities"]["ocr"]["ready"] is True
    print(json.dumps({"check": "AUTHENTICATED_DOCX_UPLOAD", "status": "PASSED"}))


if __name__ == "__main__":
    main()
