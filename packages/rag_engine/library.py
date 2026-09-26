"""Incremental FTS5/BM25 cache; fresh Drive permissions gate every run's corpus."""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import time

from filelock import FileLock, Timeout

from packages.common.config import REPO_ROOT
from .drive import DriveClient, EXPORTS, ReferenceError, revision, valid_id
from .extract import EXTRACTOR_VERSION

SUPPORTED = {".pdf", ".docx", ".hwpx", ".hwp", ".xlsx", ".txt", ".md", ".csv"}


def tokens(text):
    words = re.findall(r"[a-z0-9]+|[가-힣]+", text.lower())
    result = []
    for word in words:
        if re.fullmatch(r"[가-힣]+", word):
            result.extend(word[i:i + 2] for i in range(len(word) - 1))
        elif len(word) > 1:
            result.append(word[:80])
    return result


def isolated_extract(data, filename, mime, *, directory, timeout):
    from apps.api.security import scan_upload

    # MIME and signature take precedence over cosmetic names such as "x.pdf copy".
    if data.lstrip().startswith(b"%PDF"):
        filename, mime = "reference.pdf", "application/pdf"
    else:
        filename = "reference" + Path(filename).suffix.lower()
    if Path(filename).suffix not in SUPPORTED or scan_upload(filename, data):
        raise ReferenceError("UNSUPPORTED_OR_UNSAFE_REFERENCE")
    with tempfile.TemporaryDirectory(prefix="extract-", dir=directory) as temporary:
        path, output = Path(temporary) / filename, Path(temporary) / "result.json"
        path.write_bytes(data)
        env = {k: v for k, v in os.environ.items() if k.upper() in {
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "PYTHONUTF8"}}
        env.update(LV_ALLOW_NETWORK="0", LV_OCR_MAX_PAGES="0", LV_INDEPENDENT_OCR="off",
                   OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
                   LV_DATA_DIR=str(Path(temporary) / "data"), LV_STORAGE_ROOT=str(Path(temporary) / "storage"))
        try:
            subprocess.run([sys.executable, "-m", "packages.rag_engine.extract", str(path), str(output),
                            filename, mime], cwd=REPO_ROOT, env=env, timeout=timeout,
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise ReferenceError("REFERENCE_PARSE_TIMEOUT") from None
        except subprocess.CalledProcessError:
            raise ReferenceError("REFERENCE_PARSE_FAILED") from None
        if not output.exists() or output.stat().st_size > 16_000_000:
            raise ReferenceError("REFERENCE_TEXT_LIMIT")
        return json.loads(output.read_text(encoding="utf-8"))


class ReferenceLibrary:
    def __init__(self, settings, *, check=lambda: None, notify=lambda done, total: None,
                 client_factory=DriveClient, extractor=isolated_extract):
        self.settings, self.check = settings, check
        self.notify = notify
        self.client_factory, self.extractor = client_factory, extractor
        self.folder = settings.rag_drive_folder_id
        folder_key = hashlib.sha256(self.folder.encode()).hexdigest()
        self.directory = Path(settings.storage_root) / "reference-cache" / folder_key
        self.db_path = self.directory / "index.sqlite3"
        self.eligible = {}
        self.summary = {"status": "DISABLED", "folder_id": self.folder, "checked_at": None,
                        "snapshot_hash": None, "files_seen": 0, "files_indexed": 0,
                        "files_reused": 0, "issues": [], "sources": [],
                        "retrieval": "SQLite FTS5 BM25; Korean character bigrams",
                        "authority": "USER_REFERENCE_NOT_OFFICIAL", "extractor": EXTRACTOR_VERSION}

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=2)
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        db.execute(f"PRAGMA max_page_count={512 * 1024 * 1024 // page_size}")
        db.execute("CREATE TABLE IF NOT EXISTS files (id TEXT PRIMARY KEY, revision TEXT, payload TEXT)")
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5("
                   "file_id UNINDEXED, revision UNINDEXED, page UNINDEXED, start UNINDEXED, text UNINDEXED, terms)")
        try:
            yield db
        finally:
            db.close()

    def sync(self):
        self.eligible = {}
        self.summary.update(checked_at=None, snapshot_hash=None, files_seen=0, files_indexed=0,
                            files_reused=0, issues=[], sources=[])
        if not self.folder:
            return self.summary
        self.summary["status"] = "UNAVAILABLE"
        if not self.settings.allow_network:
            self.summary["issues"] = [{"reason": "NETWORK_DISABLED"}]
            return self.summary
        deadline = time.monotonic() + max(1, min(600, self.settings.rag_sync_seconds))
        client = self.client_factory(deadline=deadline, check=self.check)
        try:
            valid_id(self.folder)
            self.directory.mkdir(parents=True, exist_ok=True)
            with FileLock(str(self.db_path) + ".lock", timeout=min(3, client.remaining())):
                items = client.inventory(self.folder, max_files=self.settings.rag_max_files)
                self.summary["checked_at"] = datetime.now(timezone.utc).isoformat()
                self.summary["files_seen"] = len(items)
                with self.connect() as db:
                    self._sync_files(client, db, items)
                self.summary["sources"] = list(self.eligible.values())
                self.summary["files_indexed"] = len(self.eligible)
                self.summary["snapshot_hash"] = hashlib.sha256(json.dumps(
                    sorted((k, v["revision"], v["sha256"]) for k, v in self.eligible.items())).encode()).hexdigest()
                self.summary["status"] = "PARTIAL" if self.summary["issues"] else "READY"
        except Exception as exc:
            # No offline fallback: previous cached references are ineligible on listing/auth failure.
            self.eligible = {}
            self.summary["issues"].append({"reason": str(exc) if isinstance(exc, ReferenceError)
                                            else "CACHE_BUSY" if isinstance(exc, Timeout) else "SYNC_FAILED"})
        finally:
            client.close()
        return self.summary

    def _sync_files(self, client, db, items):
        seen = {item["id"] for item in items}
        # Delete only after a complete listing, never infer deletion from a failed page.
        for (file_id,) in db.execute("SELECT id FROM files").fetchall():
            if file_id not in seen:
                db.execute("DELETE FROM chunks WHERE file_id=?", (file_id,))
                db.execute("DELETE FROM files WHERE id=?", (file_id,))
        db.commit()
        downloaded = 0
        # Cached files first makes bounded subsequent runs useful while new material warms up.
        cached = {row[0] for row in db.execute("SELECT id FROM files")}
        ordered = sorted(items, key=lambda i: (i["id"] not in cached, int(i.get("size") or 0), i["id"]))
        for index, item in enumerate(ordered):
            self.notify(index, len(ordered))
            file_id = item["id"]
            try:
                client.remaining()
                fresh = client.metadata(file_id)
                if (fresh.get("trashed") or fresh.get("parents") != item.get("parents")
                        or fresh.get("capabilities", {}).get("canDownload") is False):
                    raise ReferenceError("REFERENCE_MOVED_OR_REVOKED")
                item = fresh
                version = revision(item) + ":" + EXTRACTOR_VERSION
                row = db.execute("SELECT payload FROM files WHERE id=? AND revision=?", (file_id, version)).fetchone()
                if row:
                    parsed = json.loads(row[0])
                    self.summary["files_reused"] += 1
                else:
                    if client.remaining() < 30:
                        raise ReferenceError("SYNC_BUDGET_EXHAUSTED")
                    mime = item.get("mimeType", "")
                    if (mime not in EXPORTS and mime != "application/pdf"
                            and Path(item.get("name", "")).suffix.lower() not in SUPPORTED):
                        raise ReferenceError("UNSUPPORTED_REFERENCE_FORMAT")
                    limit = min(96 * 1024 * 1024, self.settings.rag_download_mb * 1024 * 1024 - downloaded)
                    if limit <= 0 or int(item.get("size") or 0) > limit:
                        raise ReferenceError("DOWNLOAD_BUDGET_EXHAUSTED")
                    data, filename, mime = client.download(item, max_bytes=limit)
                    downloaded += len(data)
                    after = client.metadata(file_id)
                    if revision(after) != revision(item) or after.get("capabilities", {}).get("canDownload") is False:
                        raise ReferenceError("REFERENCE_CHANGED_DURING_DOWNLOAD")
                    if item.get("md5Checksum") and hashlib.md5(data).hexdigest() != item["md5Checksum"]:
                        raise ReferenceError("REFERENCE_CHECKSUM_MISMATCH")
                    if client.remaining() < 30:
                        raise ReferenceError("SYNC_BUDGET_EXHAUSTED")
                    try:
                        parsed = self.extractor(data, filename, mime, directory=self.directory, timeout=30)
                    except ReferenceError as exc:
                        if str(exc) not in ("REFERENCE_PARSE_TIMEOUT", "REFERENCE_PARSE_FAILED"):
                            raise
                        parsed = {"chunks": [], "partial": True, "reason": str(exc)}
                    chunks = parsed.pop("chunks", [])
                    parsed["chunk_count"] = len(chunks)
                    # Cache terminal parse outcomes, too; a large unreadable file must not starve later files.
                    with db:
                        db.execute("DELETE FROM chunks WHERE file_id=?", (file_id,))
                        db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?)", (file_id, version, json.dumps(parsed)))
                        db.executemany("INSERT INTO chunks VALUES (?,?,?,?,?,?)", [
                            (file_id, version, c["page"], c["start"], c["text"], " ".join(tokens(c["text"]))) for c in chunks])
                if parsed.get("partial") or not parsed.get("chunk_count"):
                    self.summary["issues"].append({"file_id": file_id, "name": item.get("name"),
                        "reason": parsed.get("reason") or "REFERENCE_EMPTY",
                        "read_pages": parsed.get("read_pages"), "pages": parsed.get("pages")})
                if parsed.get("chunk_count"):
                    self.eligible[file_id] = {"file_id": file_id, "title": item.get("name", ""),
                        "url": "https://drive.google.com/file/d/" + file_id + "/view",
                        "revision": version, "modified_time": item.get("modifiedTime"),
                        "sha256": parsed["sha256"], "partial": bool(parsed.get("partial")),
                        "pages": parsed.get("pages"), "read_pages": parsed.get("read_pages")}
            except ReferenceError as exc:
                if str(exc) in ("DRIVE_HTTP_401", "DRIVE_HTTP_429"):
                    raise
                self.summary["issues"].append({"file_id": file_id, "name": item.get("name"), "reason": str(exc)})
                if str(exc) == "SYNC_BUDGET_EXHAUSTED":
                    self.summary["issues"].append({"reason": "FILES_DEFERRED", "count": len(ordered) - index})
                    break
            except Exception:
                self.summary["issues"].append({"file_id": file_id, "reason": "REFERENCE_PROCESSING_FAILED"})

    def search(self, text, limit=6):
        if not self.eligible:
            return []
        terms = [word for word, _ in Counter(tokens(text[:24000])).most_common(48)]
        if not terms:
            return []
        query = " OR ".join('"' + term + '"' for term in terms)
        with self.connect() as db:
            deadline = time.monotonic() + 5
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
            db.execute("CREATE TEMP TABLE eligible (id TEXT PRIMARY KEY, revision TEXT)")
            db.executemany("INSERT INTO eligible VALUES (?,?)", [(k, v["revision"]) for k, v in self.eligible.items()])
            rows = db.execute("SELECT file_id, page, start, text, bm25(chunks) AS rank FROM chunks "
                "JOIN eligible e ON e.id=chunks.file_id AND e.revision=chunks.revision "
                "WHERE chunks MATCH ? ORDER BY rank LIMIT ?", (query, limit * 4)).fetchall()
        result, seen = [], set()
        for file_id, page, start, excerpt, rank in rows:
            # Identical copies cannot occupy every retrieval slot.
            digest = hashlib.sha256(excerpt.encode()).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            source = self.eligible[file_id]
            result.append({**source, "source_id": "R" + str(len(result) + 1), "page": int(page),
                           "start": int(start), "text": excerpt, "rank": rank})
            if len(result) >= limit:
                break
        return result
