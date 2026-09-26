"""Bounded official Drive API reads. Never follow document-provided URLs."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import time

import httpx

FOLDER = "application/vnd.google-apps.folder"
FIELDS = "id,name,mimeType,modifiedTime,version,md5Checksum,size,parents,trashed,capabilities(canDownload)"
EXPORTS = {
    "application/vnd.google-apps.document": ("text/plain", ".txt"),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
}


class ReferenceError(Exception):
    """Only stable codes, never HTTP bodies, URLs with keys, or credential details."""


def valid_id(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", str(value)):
        raise ReferenceError("INVALID_DRIVE_ID")
    return value


def revision(item):
    if not item.get("modifiedTime") or not (item.get("version") or item.get("md5Checksum")):
        raise ReferenceError("MISSING_REVISION")
    return hashlib.sha256(json.dumps({k: item.get(k) for k in (
        "id", "name", "mimeType", "modifiedTime", "version", "md5Checksum", "size", "parents")},
        sort_keys=True).encode()).hexdigest()


class DriveClient:
    def __init__(self, *, deadline, check=lambda: None, transport=None, headers=None):
        self.deadline, self.check = deadline, check
        self.http = httpx.Client(base_url="https://www.googleapis.com/drive/v3/",
                                 follow_redirects=False, transport=transport)
        self.headers = headers

    def remaining(self):
        self.check()
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ReferenceError("SYNC_BUDGET_EXHAUSTED")
        return remaining

    def _auth(self):
        if self.headers is not None:
            return self.headers
        key = os.getenv("LV_DRIVE_API_KEY")
        account = os.getenv("LV_DRIVE_SERVICE_ACCOUNT_FILE")
        if account:
            try:
                from google.auth.transport.requests import Request
                from google.oauth2.service_account import Credentials

                info = json.loads(Path(account).read_text(encoding="utf-8"))
                # A secret file must not redirect token exchange to an arbitrary host.
                if info.get("token_uri") != "https://oauth2.googleapis.com/token":
                    raise ReferenceError("INVALID_TOKEN_ENDPOINT")
                credentials = Credentials.from_service_account_info(
                    info, scopes=["https://www.googleapis.com/auth/drive.readonly"])
                request = Request()
                credentials.refresh(lambda **kw: request(**{**kw, "timeout": min(15, self.remaining())}))
                self.headers = {"Authorization": "Bearer " + credentials.token}
            except ReferenceError:
                raise
            except Exception:
                raise ReferenceError("DRIVE_AUTH_FAILED") from None
        elif key:
            self.headers = {"X-Goog-Api-Key": key}
        else:
            raise ReferenceError("DRIVE_CREDENTIALS_MISSING")
        return self.headers

    def read(self, path, params=None, *, max_bytes=4_000_000):
        try:
            with self.http.stream("GET", path, params=params, headers=self._auth(),
                                  timeout=min(15, self.remaining())) as response:
                if response.status_code != 200:
                    raise ReferenceError("DRIVE_HTTP_" + str(response.status_code))
                content = bytearray()
                for block in response.iter_bytes(65536):
                    self.remaining()
                    if len(content) + len(block) > max_bytes:
                        raise ReferenceError("FILE_SIZE_LIMIT")
                    content.extend(block)
                return bytes(content)
        except httpx.HTTPError:
            raise ReferenceError("DRIVE_NETWORK_ERROR") from None

    def metadata(self, file_id):
        return json.loads(self.read("files/" + valid_id(file_id),
            {"fields": FIELDS, "supportsAllDrives": "true"}))

    def inventory(self, folder_id, max_files=1000):
        root = self.metadata(folder_id)
        if root.get("mimeType") != FOLDER or root.get("trashed"):
            raise ReferenceError("ROOT_FOLDER_UNAVAILABLE")
        queue, visited, files = [(folder_id, 0)], set(), {}
        while queue:
            parent, depth = queue.pop(0)
            if parent in visited:
                continue
            if depth > 12 or len(visited) >= 200:
                raise ReferenceError("FOLDER_LIMIT")
            visited.add(parent)
            token, tokens = None, set()
            while True:
                params = {"q": f"'{valid_id(parent)}' in parents and trashed = false",
                          "fields": f"nextPageToken,incompleteSearch,files({FIELDS})", "pageSize": 100,
                          "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
                if token:
                    params["pageToken"] = token
                page = json.loads(self.read("files", params))
                if page.get("incompleteSearch"):
                    raise ReferenceError("INCOMPLETE_LISTING")
                for item in page.get("files", []):
                    valid_id(item["id"])
                    if item.get("mimeType") == FOLDER:
                        queue.append((item["id"], depth + 1))
                    else:
                        files[item["id"]] = item
                        if len(files) > max_files:
                            raise ReferenceError("FILE_COUNT_LIMIT")
                token = page.get("nextPageToken")
                if not token:
                    break
                if token in tokens:
                    raise ReferenceError("REPEATED_PAGE_TOKEN")
                tokens.add(token)
        return list(files.values())

    def download(self, item, *, max_bytes):
        if item.get("capabilities", {}).get("canDownload") is False or item.get("trashed"):
            raise ReferenceError("DOWNLOAD_NOT_ALLOWED")
        native = EXPORTS.get(item.get("mimeType"))
        path = "files/" + valid_id(item["id"])
        if native:
            content = self.read(path + "/export", {"mimeType": native[0]}, max_bytes=max_bytes)
            return content, "reference" + native[1], native[0]
        content = self.read(path, {"alt": "media", "supportsAllDrives": "true"}, max_bytes=max_bytes)
        return content, item.get("name", "reference"), item.get("mimeType", "")

    def close(self):
        self.http.close()
