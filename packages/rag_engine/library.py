"""Incremental FTS5/BM25 cache; fresh Drive permissions gate every run's corpus."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time

from filelock import FileLock, Timeout

from packages.common.config import REPO_ROOT
from .drive import DriveClient, EXPORTS, ReferenceError, access_problem, revision, valid_id
from .extract import EXTRACTOR_VERSION
from . import relevance
from .relevance import tokens
from .case_table import lookup_records

SUPPORTED = {".pdf", ".docx", ".hwpx", ".hwp", ".xlsx", ".txt", ".md", ".csv"}


def isolated_extract(data, filename, mime, *, directory, timeout, continuation=None):
    from apps.api.security import scan_upload

    # MIME and signature take precedence over cosmetic names such as "x.pdf copy".
    if data.lstrip().startswith(b"%PDF"):
        filename, mime = "reference.pdf", "application/pdf"
    else:
        filename = "reference" + relevance.extension(filename)
    if Path(filename).suffix not in SUPPORTED or scan_upload(filename, data):
        raise ReferenceError("UNSUPPORTED_OR_UNSAFE_REFERENCE")
    with tempfile.TemporaryDirectory(prefix="extract-", dir=directory) as temporary:
        path, output = Path(temporary) / filename, Path(temporary) / "result.json"
        path.write_bytes(data)
        arguments = [sys.executable, "-m", "packages.rag_engine.extract", str(path), str(output), filename, mime]
        if continuation:
            checkpoint = Path(temporary) / "continuation.json"
            checkpoint.write_text(json.dumps(continuation, ensure_ascii=False), encoding="utf-8")
            arguments.append(str(checkpoint))
        env = {k: v for k, v in os.environ.items() if k.upper() in {
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "PYTHONUTF8",
            "LV_CASE_TABLE_MAX_EXCLUDED_ROWS"}}
        env.update(LV_ALLOW_NETWORK="0", LV_OCR_MAX_PAGES="0", LV_INDEPENDENT_OCR="off",
                   OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
                   LV_DATA_DIR=str(Path(temporary) / "data"), LV_STORAGE_ROOT=str(Path(temporary) / "storage"))
        try:
            subprocess.run(arguments, cwd=REPO_ROOT, env=env, timeout=timeout,
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise ReferenceError("REFERENCE_PARSE_TIMEOUT") from None
        except subprocess.CalledProcessError:
            raise ReferenceError("REFERENCE_PARSE_FAILED") from None
        if not output.exists():
            raise ReferenceError("REFERENCE_TEXT_LIMIT")
        # Structured tables carry row provenance alongside text.  Their bound
        # is explicit and independent from the ordinary 16 MB extraction cap;
        # a malformed/unbounded workbook still fails closed.
        payload_size = output.stat().st_size
        if payload_size > 64_000_000:
            raise ReferenceError("REFERENCE_TEXT_LIMIT")
        payload = json.loads(output.read_text(encoding="utf-8"))
        if payload_size > 16_000_000 and not payload.get("structured_case_table"):
            raise ReferenceError("REFERENCE_TEXT_LIMIT")
        return payload


def stale_quarantine(parsed):
    return parsed.get("reason") == "REFERENCE_QUARANTINED" and "scan_findings" not in parsed


class ReferenceLibrary:
    def __init__(self, settings, *, check=lambda: None, notify=lambda done, total: None,
                 client_factory=DriveClient, extractor=isolated_extract):
        self.settings, self.check = settings, check
        self.notify = notify
        self.client_factory, self.extractor = client_factory, extractor
        self._case_rows_cache: list[dict] | None = None
        self._case_number_index: dict[str, list[dict]] = {}
        self.folder = settings.rag_drive_folder_id
        folder_key = hashlib.sha256(self.folder.encode()).hexdigest()
        self.directory = Path(settings.storage_root) / "reference-cache" / folder_key
        self.db_path = self.directory / "index.sqlite3"
        self.eligible = {}
        self.summary = {"status": "DISABLED", "folder_id": self.folder, "checked_at": None,
                        "snapshot_hash": None, "files_seen": 0, "files_indexed": 0,
                        "files_reused": 0, "issues": [], "sources": [], "duplicates": [], "similar_names": [],
                        "diagnostics": {}, "inventory": [],
                        "retrieval": "SQLite FTS5; Korean character bigrams; corpus-IDF relevance gate "
                                     "with folder/file-name bonus; structured case rows use exact lookup and claim-level holding-first search",
                        "authority": "USER_REFERENCE_NOT_OFFICIAL", "extractor": EXTRACTOR_VERSION}

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=2)
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        db.execute(f"PRAGMA max_page_count={512 * 1024 * 1024 // page_size}")
        db.execute("CREATE TABLE IF NOT EXISTS files (id TEXT PRIMARY KEY, revision TEXT, payload TEXT)")
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5("
                   "file_id UNINDEXED, revision UNINDEXED, page UNINDEXED, start UNINDEXED, text UNINDEXED, terms)")
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunk_terms USING fts5vocab(chunks, 'row')")
        db.execute("""CREATE TABLE IF NOT EXISTS case_rows (
            record_id TEXT PRIMARY KEY, file_id TEXT NOT NULL, revision TEXT NOT NULL,
            sheet TEXT, row_number INTEGER, source_cell_range TEXT,
            original_number TEXT, title TEXT, case_info TEXT, court TEXT,
            decision_date TEXT, case_numbers TEXT, target_case_numbers TEXT, referenced_case_numbers TEXT,
            issue TEXT, facts TEXT,
            reason TEXT, holding TEXT, hyperlinks TEXT, quality_warnings TEXT,
            case_head TEXT, indexed_text TEXT, raw_cells TEXT
        )""")
        columns = {row[1] for row in db.execute("PRAGMA table_info(case_rows)")}
        for missing in ("target_case_numbers", "referenced_case_numbers", "raw_cells"):
            if missing not in columns:
                db.execute(f"ALTER TABLE case_rows ADD COLUMN {missing} TEXT")
        try:
            yield db
        finally:
            db.close()

    def sync(self, query=""):
        started = time.monotonic()
        self.eligible = {}
        self._case_rows_cache = None
        self._case_number_index = {}
        self.summary.update(checked_at=None, snapshot_hash=None, files_seen=0, files_indexed=0,
                            files_reused=0, issues=[], sources=[], duplicates=[], similar_names=[], inventory=[])
        # 분석 문서마다 따로 받은 질의(목록)나 하나로 합친 질의(문자열) 모두 받는다.
        queries = [q for q in (query if isinstance(query, (list, tuple)) else [query]) if q]
        self.sync_query = "\n".join(queries) if self.settings.rag_metadata_first else ""
        queries = queries if self.sync_query else []
        budget = max(1, min(600, self.settings.rag_sync_seconds))
        diagnostics = self.summary["diagnostics"] = {
            "started_at": datetime.now(timezone.utc).isoformat(), "folder_id": self.folder,
            "network_allowed": bool(self.settings.allow_network), "budget_seconds": budget,
            "max_files": self.settings.rag_max_files, "inventory_max_files": self.settings.rag_inventory_max_files,
            "selection_strategy": "METADATA_GATE" if self.sync_query else "CACHE_SIZE_ORDER",
            "download_budget_mb": self.settings.rag_download_mb,
            "credential_mode": None, "stages": [], "downloads": {"count": 0, "bytes": 0},
            "extractions": {"count": 0, "ms": 0}, "duplicates_skipped": 0, "deferred": 0}
        if not self.folder:
            return self.summary
        self.summary["status"] = "UNAVAILABLE"
        if not self.settings.allow_network:
            self.summary["issues"] = [{"reason": "NETWORK_DISABLED"}]
            return self._finish(started, None)
        deadline = time.monotonic() + budget
        client = self.client_factory(deadline=deadline, check=self.check)
        diagnostics["credential_mode"] = getattr(client, "credential_mode", "injected")
        try:
            valid_id(self.folder)
            self.directory.mkdir(parents=True, exist_ok=True)
            with FileLock(str(self.db_path) + ".lock", timeout=min(3, client.remaining())):
                mark = time.monotonic()
                items = client.inventory(self.folder, max_files=self.settings.rag_inventory_max_files)
                self._stage("inventory", mark, files=len(items))
                self.summary["checked_at"] = datetime.now(timezone.utc).isoformat()
                self.summary["files_seen"] = len(items)
                self.summary["inventory"] = [{"file_id": item["id"], "name": item.get("name", ""),
                    "folder_path": item.get("folder_path", ""), "size": int(item.get("size") or 0),
                    "metadata": relevance.metadata_priority(item, self.sync_query),
                    "status": "SELECTED_PENDING", "reason": "NOT_PROCESSED", "background_queued": False}
                    for item in items]
                folders = getattr(client, "folders", {}) or {}
                diagnostics["folders_seen"] = len(folders)
                diagnostics["folder_paths"] = sorted(p for p in folders.values() if p)[:200]
                extensions = {}
                for item in items:
                    mime = item.get("mimeType", "")
                    key = mime if mime.startswith("application/vnd.google-apps") else (
                        relevance.extension(item.get("name")) or "(none)")
                    extensions[key] = extensions.get(key, 0) + 1
                diagnostics["files_by_type"] = extensions
                duplicates, similar, skip = relevance.duplicate_groups(items)
                self.summary["duplicates"], self.summary["similar_names"] = duplicates, similar
                # 분석 중에는 폴더·파일명·Drive 본문 검색으로 고른 후보만 새로 연다. 질의 없는 동기화(관리자 점검
                # 스크립트)는 종전처럼 전체를 색인해 캐시를 채운다.
                gate = None
                if queries:
                    try:
                        gate = self._metadata_gate(client, items, queries, folders)
                    except ReferenceError:
                        raise
                    except Exception as exc:  # 선정 단계의 결함이 Drive 검토 전체를 멈추게 하지 않는다
                        diagnostics["metadata_gate"] = {"error": type(exc).__name__, "fallback": "ALL_FILES_BY_PRIORITY"}
                if gate:
                    for entry in self.summary["inventory"]:
                        entry["gate"] = gate[entry["file_id"]]
                mark = time.monotonic()
                with self.connect() as db:
                    self._sync_files(client, db, items, skip, gate)
                self._stage("files", mark, indexed=len(self.eligible))
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
        return self._finish(started, client)

    def _stage(self, name, mark, **values):
        self.summary["diagnostics"]["stages"].append(
            {"stage": name, "ms": round((time.monotonic() - mark) * 1000), **values})

    def _finish(self, started, client):
        diagnostics = self.summary["diagnostics"]
        diagnostics["finished_at"] = datetime.now(timezone.utc).isoformat()
        diagnostics["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        diagnostics["outcome"] = self.summary["status"]
        counts = {}
        for item in self.summary["inventory"]:
            if item["reason"] == "NOT_PROCESSED":
                item["reason"] = "SYNC_INTERRUPTED"
        for issue in self.summary["issues"]:
            counts[issue.get("reason", "")] = counts.get(issue.get("reason", ""), 0) + 1
        diagnostics["issue_counts"] = counts
        if client is not None:
            diagnostics["http"] = {"totals": getattr(client, "call_totals", {}),
                                   "calls": list(getattr(client, "calls", []))}
        return self.summary

    def _metadata_gate(self, client, items, queries, folders):
        """열어 볼 후보: 폴더·파일명 점수 + Drive 서버 본문 검색(파일을 내려받지 않음)."""
        info = {"thresholds": relevance.gate_thresholds(), "fulltext": []}
        hits = {}
        search = getattr(client, "search_fulltext", None)
        folder_ids = list(folders) or [self.folder]
        mark = time.monotonic()
        for query in queries if search else []:
            words = relevance.salient_words(query)
            if not words:
                continue
            try:
                found = search(folder_ids, words)
            except ReferenceError as exc:
                # 본문 검색을 쓸 수 없으면 이름 점수만으로 고른다(열기 전 선정의 보조 수단일 뿐이다).
                entry = {"terms": words, "error": str(exc)}
                if getattr(client, "last_error_reason", ""):
                    entry["reason"] = client.last_error_reason
                info["fulltext"].append(entry)
                if str(exc) in ("DRIVE_HTTP_401", "DRIVE_HTTP_403", "DRIVE_HTTP_429", "DRIVE_FULLTEXT_FORBIDDEN",
                                "SYNC_BUDGET_EXHAUSTED"):
                    # 같은 거절을 문서마다 반복하지 않는다(0.9.8 실제 실행: 403 5회).
                    info["fulltext_available"] = False
                    break
                continue
            info["fulltext"].append({"terms": words, "files": len(found)})
            for file_id in found:
                hits.setdefault(file_id, []).append(" ".join(words))
        gate = relevance.metadata_gate(items, queries, hits)
        self._gate_weights = relevance.gate_weights(items)
        info["selected"] = sum(1 for g in gate.values() if g["selected"])
        info["not_selected"] = len(gate) - info["selected"]
        info["ms"] = round((time.monotonic() - mark) * 1000)
        self.summary["diagnostics"]["metadata_gate"] = info
        return gate

    def _sync_files(self, client, db, items, skip, gate=None):
        diagnostics = self.summary["diagnostics"]
        seen = {item["id"] for item in items}
        # Delete only after a complete listing, never infer deletion from a failed page.
        for (file_id,) in db.execute("SELECT id FROM files").fetchall():
            if file_id not in seen:
                db.execute("DELETE FROM chunks WHERE file_id=?", (file_id,))
                db.execute("DELETE FROM case_rows WHERE file_id=?", (file_id,))
                db.execute("DELETE FROM files WHERE id=?", (file_id,))
        db.commit()
        downloaded = 0
        new_files = 0
        # Identical copies come last and are skipped when their kept original is usable.
        # Cached files next, so bounded runs stay useful while new material warms up.
        cached = {row[0] for row in db.execute("SELECT id FROM files")}
        audit = {item["file_id"]: item for item in self.summary["inventory"]}
        chosen = (lambda file_id: True) if gate is None else (lambda file_id: gate[file_id]["selected"])
        ordered = sorted(items, key=lambda i: (not chosen(i["id"]), gate[i["id"]].get("rank", 0) if gate else 0,
            -audit[i["id"]]["metadata"]["score"],
            -(gate[i["id"]]["score"] if gate else 0), i["id"] in skip, i["id"] not in cached,
            int(i.get("size") or 0), i["id"]))
        for index, item in enumerate(ordered):
            self.notify(index, len(ordered))
            file_id = item["id"]
            entry = audit[file_id]
            if not chosen(file_id) and file_id not in cached:
                # 후보가 아니고 색인된 적도 없는 파일은 권한 확인·내려받기 없이 넘어간다.
                entry.update(status="NOT_SELECTED_METADATA", reason=gate[file_id]["reason"])
                continue
            try:
                client.remaining()
                if skip.get(file_id) in self.eligible:
                    diagnostics["duplicates_skipped"] += 1
                    db.execute("DELETE FROM chunks WHERE file_id=?", (file_id,))
                    db.execute("DELETE FROM case_rows WHERE file_id=?", (file_id,))
                    db.execute("DELETE FROM files WHERE id=?", (file_id,))
                    db.commit()
                    entry.update(status="DUPLICATE_REUSED", reason="IDENTICAL_CONTENT", duplicate_of=skip[file_id])
                    continue
                # The listing was read moments ago in this run; it already carries parents, trash state,
                # download permission and revision, so an unchanged cached file needs no second request.
                problem = access_problem(item)
                if problem:
                    raise ReferenceError(problem)
                folder_path = item.get("folder_path", "")
                version = revision(item) + ":" + EXTRACTOR_VERSION
                row = db.execute("SELECT payload FROM files WHERE id=? AND revision=?", (file_id, version)).fetchone()
                if row and stale_quarantine(json.loads(row[0])):
                    row = None                    # 예전 규칙(파일 전체 격리, 근거 미기록)의 결과는 다시 읽는다
                prior = json.loads(row[0]) if row else None
                continuation = prior.get("continuation") if prior else None
                if continuation:
                    row = None  # Only a progressing structured table is retried at the same revision.
                if row:
                    parsed = json.loads(row[0])
                    self.summary["files_reused"] += 1
                    entry["reused"] = True
                elif not chosen(file_id):
                    # 이름·경로·본문 검색 어느 쪽으로도 관련 후보가 아니면 열지 않는다(이미 색인된 파일은 위에서 재사용).
                    entry.update(status="NOT_SELECTED_METADATA", reason=gate[file_id]["reason"])
                    continue
                else:
                    if new_files >= self.settings.rag_max_files:
                        raise ReferenceError("INDEX_FILE_BUDGET_EXHAUSTED")
                    new_files += 1
                    if client.remaining() < 30:
                        raise ReferenceError("SYNC_BUDGET_EXHAUSTED")
                    fresh = client.metadata(file_id)
                    problem = access_problem(item, fresh)
                    if problem:
                        self._access_detail(item, fresh, problem)
                        raise ReferenceError(problem)
                    item = {**fresh, "folder_path": folder_path, "listed_parent": item.get("listed_parent")}
                    version = revision(item) + ":" + EXTRACTOR_VERSION
                    if prior and continuation:
                        stored = db.execute("SELECT revision FROM files WHERE id=?", (file_id,)).fetchone()
                        if not stored or stored[0] != version:
                            prior, continuation = None, None
                    mime = item.get("mimeType", "")
                    if (mime not in EXPORTS and mime != "application/pdf"
                            and relevance.extension(item.get("name")) not in SUPPORTED):
                        raise ReferenceError("UNSUPPORTED_REFERENCE_FORMAT")
                    limit = min(96 * 1024 * 1024, self.settings.rag_download_mb * 1024 * 1024 - downloaded)
                    if limit <= 0 or int(item.get("size") or 0) > limit:
                        raise ReferenceError("DOWNLOAD_BUDGET_EXHAUSTED")
                    data, filename, mime = client.download(item, max_bytes=limit)
                    downloaded += len(data)
                    diagnostics["downloads"]["count"] += 1
                    diagnostics["downloads"]["bytes"] += len(data)
                    after = client.metadata(file_id)
                    if access_problem(item, after):
                        self._access_detail(item, after, access_problem(item, after))
                        raise ReferenceError(access_problem(item, after))
                    if revision(after) != revision(item):
                        raise ReferenceError("REFERENCE_CHANGED_DURING_DOWNLOAD")
                    if item.get("md5Checksum") and hashlib.md5(data).hexdigest() != item["md5Checksum"]:
                        raise ReferenceError("REFERENCE_CHECKSUM_MISMATCH")
                    if client.remaining() < 30:
                        raise ReferenceError("SYNC_BUDGET_EXHAUSTED")
                    mark = time.monotonic()
                    try:
                        kwargs = {"directory": self.directory, "timeout": 30}
                        if continuation:
                            kwargs["continuation"] = continuation
                        parsed = self.extractor(data, filename, mime, **kwargs)
                        if (continuation and not parsed.get("resumed")
                                and parsed.get("reason") in ("REFERENCE_PARSE_TIMEOUT", "REFERENCE_PARSE_FAILED")):
                            raise ReferenceError(parsed["reason"])
                    except ReferenceError as exc:
                        if str(exc) not in ("REFERENCE_PARSE_TIMEOUT", "REFERENCE_PARSE_FAILED"):
                            raise
                        if continuation:
                            # Retain committed rows/cursor, but do not retry a stuck row forever.
                            failed_batch = dict(prior)
                            failed_batch["resume_failures"] = int(prior.get("resume_failures", 0)) + 1
                            if failed_batch["resume_failures"] >= 2:
                                failed_batch["continuation"] = None
                                failed_batch.update(partial=True, reason=str(exc))
                            with db:
                                db.execute("UPDATE files SET payload=? WHERE id=? AND revision=?",
                                           (json.dumps(failed_batch), file_id, version))
                            raise
                        parsed = {"chunks": [], "partial": True, "reason": str(exc)}
                    finally:
                        diagnostics["extractions"]["count"] += 1
                        diagnostics["extractions"]["ms"] += round((time.monotonic() - mark) * 1000)
                    chunks = parsed.pop("chunks", [])
                    case_records = parsed.pop("case_records", [])
                    append_batch = bool(prior and parsed.get("resumed") and prior.get("sha256") == parsed.get("sha256")
                                        and parsed.get("reason") != "REFERENCE_QUARANTINED")
                    parsed["chunk_count"] = len(chunks) + (prior.get("chunk_count", 0) if append_batch else 0)
                    # Cache terminal parse outcomes, too; a large unreadable file must not starve later files.
                    with db:
                        if not append_batch:
                            db.execute("DELETE FROM chunks WHERE file_id=?", (file_id,))
                            db.execute("DELETE FROM case_rows WHERE file_id=?", (file_id,))
                        db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?)", (file_id, version, json.dumps(parsed)))
                        db.executemany("INSERT INTO chunks VALUES (?,?,?,?,?,?)", [
                            (file_id, version, c["page"], c["start"], c["text"], " ".join(tokens(c["text"]))) for c in chunks])
                        if case_records:
                            db.executemany("""INSERT OR REPLACE INTO case_rows
                                (record_id,file_id,revision,sheet,row_number,source_cell_range,
                                 original_number,title,case_info,court,decision_date,case_numbers,
                                 target_case_numbers,referenced_case_numbers,issue,facts,reason,holding,
                                 hyperlinks,quality_warnings,case_head,indexed_text,raw_cells) VALUES
                                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", [
                                (r.get("record_id"), file_id, version, r.get("sheet"), r.get("row"),
                                 r.get("source_cell_range"), r.get("original_number"), r.get("title"),
                                 r.get("case_info"), r.get("court"), r.get("decision_date"),
                                 json.dumps(r.get("case_numbers", []), ensure_ascii=False),
                                 json.dumps(r.get("target_case_numbers", r.get("case_numbers", [])), ensure_ascii=False),
                                 json.dumps(r.get("referenced_case_numbers", []), ensure_ascii=False), r.get("issue"),
                                 r.get("facts"), r.get("reason"), r.get("holding"),
                                 json.dumps(r.get("hyperlinks", []), ensure_ascii=False),
                                 json.dumps(r.get("quality_warnings", []), ensure_ascii=False),
                                 r.get("case_head"), r.get("indexed_text"),
                                 json.dumps(r.get("raw_cells", {}), ensure_ascii=False)) for r in case_records])
                if parsed.get("partial") or not parsed.get("chunk_count"):
                    self.summary["issues"].append({"file_id": file_id, "name": item.get("name"),
                        "reason": parsed.get("reason") or "REFERENCE_EMPTY",
                        "read_pages": parsed.get("read_pages"), "pages": parsed.get("pages")})
                entry.update(status=("INDEXED_PARTIAL" if parsed.get("partial") else "INDEXED")
                             if parsed.get("chunk_count") else "PARSE_FAILED",
                             reason=parsed.get("reason") or "TEXT_INDEXED", pages=parsed.get("pages"),
                             read_pages=parsed.get("read_pages"))
                for key in ("excluded_pages", "scan_findings", "no_text_pages", "unprocessed_pages", "coverage_note",
                            "text_parser", "fallback_pages", "stats", "read_ranges", "excluded_rows", "table_version"):
                    if parsed.get(key):
                        entry[key] = parsed[key]
                if parsed.get("structured_case_table"):
                    entry["structured_case_table"] = True
                    entry["case_table_stats"] = parsed.get("stats", {})
                entry["page_numbers_reliable"] = parsed.get("page_numbers_reliable", True)
                entry["body_extraction_scope"] = parsed.get("body_extraction_scope")
                if parsed.get("chunk_count"):
                    self.eligible[file_id] = {"file_id": file_id, "title": item.get("name", ""),
                        "folder_path": folder_path,
                        "metadata_score": entry["metadata"]["score"],
                        "url": "https://drive.google.com/file/d/" + file_id + "/view",
                        "revision": version, "modified_time": item.get("modifiedTime"),
                        "sha256": parsed["sha256"], "partial": bool(parsed.get("partial")),
                        "pages": parsed.get("pages"), "read_pages": parsed.get("read_pages"),
                        "page_numbers_reliable": parsed.get("page_numbers_reliable", True),
                        "body_extraction_scope": parsed.get("body_extraction_scope"),
                        "chunk_count": parsed["chunk_count"],
                        "structured_case_table": bool(parsed.get("structured_case_table")),
                        "case_table_stats": parsed.get("stats", {})}
            except ReferenceError as exc:
                code = str(exc)
                entry.update(status="UNSUPPORTED_TYPE" if code == "UNSUPPORTED_REFERENCE_FORMAT" else
                             "SELECTED_PENDING" if "BUDGET" in code else "UNAVAILABLE", reason=code)
                if str(exc) in ("DRIVE_HTTP_401", "DRIVE_HTTP_429"):
                    raise
                self.summary["issues"].append({"file_id": file_id, "name": item.get("name"), "reason": str(exc)})
                if str(exc) == "SYNC_BUDGET_EXHAUSTED":
                    # 미룬 파일 수는 열기로 한 후보 중 남은 것만 센다(선정되지 않은 파일은 미룬 것이 아니다).
                    diagnostics["deferred"] = sum(1 for later in ordered[index:] if chosen(later["id"]))
                    self.summary["issues"].append({"reason": "FILES_DEFERRED", "count": diagnostics["deferred"]})
                    for later in ordered[index + 1:]:
                        if chosen(later["id"]):
                            audit[later["id"]].update(status="SELECTED_PENDING", reason="SYNC_BUDGET_EXHAUSTED")
                        else:
                            audit[later["id"]].update(status="NOT_SELECTED_METADATA", reason=gate[later["id"]]["reason"])
                    break
            except Exception:
                entry.update(status="PARSE_FAILED", reason="REFERENCE_PROCESSING_FAILED")
                self.summary["issues"].append({"file_id": file_id, "reason": "REFERENCE_PROCESSING_FAILED"})

    def _access_detail(self, listed, fresh, problem):
        """Record the fields behind an access decision (IDs and flags only) for the run JSON."""
        details = self.summary["diagnostics"].setdefault("access_checks", [])
        if len(details) < 10:
            details.append({"file_id": listed.get("id"), "reason": problem,
                            "listed_parent": listed.get("listed_parent"),
                            "listed_parents": listed.get("parents"), "fresh_parents": fresh.get("parents"),
                            "fresh_trashed": fresh.get("trashed"),
                            "fresh_can_download": (fresh.get("capabilities") or {}).get("canDownload")})

    def select(self, text, limit=12):
        """Choose relevant files (text match plus folder/file-name bonus), then their best excerpts.

        Returns the decision log; `sources` is empty when nothing is relevant, and then the Drive
        library is not used for the document."""
        log = {"decision": "NOT_USED", "reason": "", "thresholds": relevance.thresholds(),
               "corpus_chunks": 0, "query_terms": [], "candidates": [], "files_selected": 0, "sources": []}
        # 관련 있어 보이는데 읽지 못한 파일이 있으면 '관련 자료 없음'으로 단정하지 않는다. 일부 쪽만 못 읽은
        # 파일(INDEXED_PARTIAL)은 이미 색인돼 대조에 들어갔으므로 미검토로 세지 않는다.
        pending = [item for item in self.summary.get("inventory", [])
                   if item["status"] not in ("INDEXED", "INDEXED_PARTIAL", "DUPLICATE_REUSED", "NOT_SELECTED_METADATA")
                   and (relevance.metadata_priority(item, text)["score"] > 0
                        or relevance.name_gate_passes(getattr(self, "_gate_weights", {}).get(item["file_id"], {}), text))]
        log["coverage"] = "INCOMPLETE_COVERAGE" if pending else "CHECKED_INDEXED_CORPUS"
        log["unreviewed_candidates"] = pending
        if not self.eligible:
            if pending:
                log["decision"] = "INCOMPLETE_COVERAGE"
            log["reason"] = "NO_ELIGIBLE_REFERENCE"
            return log
        mark = time.monotonic()
        total = sum(v.get("chunk_count") or 0 for v in self.eligible.values())
        log["corpus_chunks"] = total
        counts = set(relevance.query_tokens(text[:24000]))
        names = relevance.name_weights(self.eligible)
        priority_ids = sorted(k for k, v in self.eligible.items() if relevance.priority_reference(v, text))
        log["priority_references"] = [{"file_id": k, "title": self.eligible[k].get("title"),
                                      "searched": False, "search_reason": "NOT_EXECUTED" if i < 12 else "SEARCH_LIMIT"}
                                     for i, k in enumerate(priority_ids)]
        with self.connect() as db:
            deadline = time.monotonic() + 5
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
            frequency = {}
            terms = sorted(counts)
            for offset in range(0, len(terms), 500):
                batch = terms[offset:offset + 500]
                frequency.update(db.execute("SELECT term, doc FROM chunk_terms WHERE term IN ("
                                            + ",".join("?" for _ in batch) + ")", batch).fetchall())
            profiles = relevance.query_profiles(text[:24000], frequency, total)
            profile = profiles[0]
            # Round-robin window terms keeps one issue from consuming the query budget.
            present = list(dict.fromkeys(t for rank in range(relevance.QUERY_TERMS)
                for p in profiles for t in list(p)[rank:rank + 1] if t in frequency))[:160]
            log["query_windows"] = len(profiles) - 1
            log["topic_window_chars"] = relevance.TOPIC_WINDOW
            log["topic_step_chars"] = relevance.TOPIC_STEP
            log["query_terms"] = [{"term": t, "weight": round(profile[t], 3), "chunks": frequency.get(t, 0)}
                                  for t in list(profile)[:20] if t in frequency]
            if not present:
                if pending:
                    log["decision"] = "INCOMPLETE_COVERAGE"
                log["reason"] = "NO_SHARED_KEY_TERMS"
                for item in log["priority_references"]:
                    item["search_reason"] = "NO_SHARED_KEY_TERMS"
                log["ms"] = round((time.monotonic() - mark) * 1000)
                return log
            db.execute("CREATE TEMP TABLE eligible (id TEXT PRIMARY KEY, revision TEXT)")
            db.executemany("INSERT INTO eligible VALUES (?,?)", [(k, v["revision"]) for k, v in self.eligible.items()])
            rows = db.execute("SELECT file_id, page, start, text, terms FROM chunks "
                "JOIN eligible e ON e.id=chunks.file_id AND e.revision=chunks.revision "
                "WHERE chunks MATCH ? ORDER BY bm25(chunks) LIMIT ?",
                (" OR ".join('"' + term + '"' for term in present), relevance.CANDIDATE_CHUNKS)).fetchall()
            # A large, relevant casebook must not disappear behind the global top-chunk limit.
            for index, file_id in enumerate(priority_ids[:12]):
                rows.extend(db.execute("SELECT file_id, page, start, text, terms FROM chunks "
                    "WHERE chunks MATCH ? AND file_id=? AND revision=? ORDER BY bm25(chunks) LIMIT 40",
                    (" OR ".join('"' + term + '"' for term in present), file_id,
                     self.eligible[file_id]["revision"])).fetchall())
                log["priority_references"][index].update(searched=True, search_reason="SEARCH_COMPLETED")
        # A short query cannot share more terms than it has.
        required = min(relevance.MIN_MATCHED_TERMS, len(profile))
        log["required_shared_terms"] = required
        files = {}
        for file_id, page, start, excerpt, terms in dict.fromkeys(rows):
            chunk_terms = set(terms.split())
            scores = [(*relevance.coverage(p, chunk_terms), index) for index, p in enumerate(profiles)]
            score, matched, window = max(scores, key=lambda s: (len(s[1]) >= required, s[0], len(s[1])))
            entry = files.setdefault(file_id, {"chunks": []})
            entry["chunks"].append((score, len(matched), int(page), int(start), excerpt, window))
        candidates = []
        for file_id, entry in files.items():
            source = self.eligible[file_id]
            name_score, name_hits = relevance.name_coverage(names.get(file_id, {}), counts)
            best = max(entry["chunks"], key=lambda c: (c[1] >= required and c[0] >= relevance.MIN_CHUNK_COVERAGE, c[0], c[1]))
            metadata_bonus = min(0.05, (source.get("metadata_score") or 0) / 1000)
            file_score = best[0] + relevance.META_WEIGHT * name_score + metadata_bonus
            reasons = []
            if best[1] < required:
                reasons.append("TOO_FEW_SHARED_TERMS")
            if best[0] < relevance.MIN_CHUNK_COVERAGE:
                reasons.append("LOW_TEXT_COVERAGE")
            if file_score < relevance.MIN_FILE_SCORE:
                reasons.append("LOW_FILE_SCORE")
            candidates.append({"file_id": file_id, "title": source.get("title"), "folder_path": source.get("folder_path"),
                               "text_coverage": round(best[0], 3), "shared_terms": best[1],
                               "name_coverage": round(name_score, 3), "name_terms": name_hits[:8],
                               "metadata_bonus": round(metadata_bonus, 3),
                               "matched_query_window": best[5],
                               "file_score": round(file_score, 3), "selected": not reasons, "rejected_because": reasons,
                               "_name": name_score, "_chunks": entry["chunks"]})
        candidates.sort(key=lambda c: (-c["file_score"], c["file_id"]))
        chosen = [c for c in candidates if c["selected"]]
        excerpts = []
        for candidate in chosen:
            usable = sorted((c for c in candidate["_chunks"]
                             if c[0] >= relevance.MIN_CHUNK_COVERAGE and c[1] >= required),
                            key=lambda c: (-c[0], c[2], c[3]))[:relevance.PER_FILE_EXCERPTS]
            excerpts.extend((c[0] + relevance.META_WEIGHT * candidate["_name"] + candidate["metadata_bonus"],
                             candidate["file_id"], c) for c in usable)
        excerpts.sort(key=lambda e: (-e[0], e[1], e[2][2], e[2][3]))
        reserved, reserved_ids = [], set()
        for excerpt in excerpts:
            if excerpt[1] in priority_ids[:12] and excerpt[1] not in reserved_ids:
                reserved.append(excerpt)
                reserved_ids.add(excerpt[1])
        excerpts = reserved + [e for e in excerpts if e not in reserved]
        result, seen = [], set()
        for score, file_id, (coverage, shared, page, start, excerpt, window) in excerpts:
            # Identical copies cannot occupy every retrieval slot.
            digest = hashlib.sha256(excerpt.encode()).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            result.append({**self.eligible[file_id], "source_id": "R" + str(len(result) + 1), "page": page,
                           "start": start, "text": excerpt, "relevance": round(score, 3),
                           "text_coverage": round(coverage, 3), "shared_terms": shared,
                           "matched_query_window": window})
            if limit is not None and len(result) >= limit:
                break
        for candidate in candidates:
            candidate.pop("_name"), candidate.pop("_chunks")
        log["candidates"] = candidates
        log["candidates_total"] = len(candidates)
        log["files_qualified"] = len(chosen)
        selected_ids = {s["file_id"] for s in result}
        log["files_selected"] = len(selected_ids)
        for candidate in candidates:
            candidate["qualified"] = candidate["selected"]
            candidate["selected"] = candidate["file_id"] in selected_ids
            if candidate["qualified"] and not candidate["selected"]:
                candidate["rejected_because"] = ["EXCERPT_BUDGET_OR_DUPLICATE"]
        for item in log["priority_references"]:
            item["selected"] = item["file_id"] in selected_ids
        log["sources"] = result
        log["decision"] = "USED" if result else "INCOMPLETE_COVERAGE" if pending else "NOT_USED"
        log["reason"] = "RELEVANT_REFERENCE_FOUND" if result else (
            "NO_CANDIDATE_CHUNK" if not candidates else "BELOW_RELEVANCE_THRESHOLD")
        log["ms"] = round((time.monotonic() - mark) * 1000)
        return log

    def search(self, text, limit=12):
        return self.select(text, limit)["sources"]

    def has_case_tables(self) -> bool:
        return any(v.get("structured_case_table") for v in self.eligible.values())

    def _case_rows(self) -> list[dict]:
        if self._case_rows_cache is not None:
            return self._case_rows_cache
        if not self.has_case_tables() or not self.db_path.exists():
            return []
        try:
            with self.connect() as db:
                rows = db.execute("""SELECT record_id,file_id,revision,sheet,row_number,
                    source_cell_range,original_number,title,case_info,court,decision_date,
                    case_numbers,target_case_numbers,referenced_case_numbers,issue,facts,reason,holding,hyperlinks,quality_warnings,
                    case_head,indexed_text,raw_cells FROM case_rows""").fetchall()
        except sqlite3.Error:
            self._case_rows_cache = []
            self._case_number_index = {}
            return self._case_rows_cache
        fields = ("record_id", "file_id", "revision", "sheet", "row", "source_cell_range",
                  "original_number", "title", "case_info", "court", "decision_date",
                  "case_numbers", "target_case_numbers", "referenced_case_numbers", "issue", "facts", "reason", "holding", "hyperlinks",
                  "quality_warnings", "case_head", "indexed_text", "raw_cells")
        result = []
        for row in rows:
            item = dict(zip(fields, row))
            if item["file_id"] not in self.eligible:
                continue
            for key in ("case_numbers", "target_case_numbers", "referenced_case_numbers", "hyperlinks", "quality_warnings", "raw_cells"):
                try:
                    item[key] = json.loads(item[key] or "[]")
                except (TypeError, ValueError):
                    item[key] = []
            result.append(item)
        self._case_rows_cache = result
        self._case_number_index = {}
        for item in result:
            for number in item.get("target_case_numbers") or item.get("case_numbers") or []:
                key = str(number or "").replace(" ", "")
                if key:
                    self._case_number_index.setdefault(key, []).append(item)
        return result

    def match_case(self, citation) -> dict:
        """Exact lookup in the structured corpus; never changes official findings."""
        case_number = getattr(citation, "canonical_case_number", None) or getattr(citation, "case_number", None)
        court = getattr(citation, "court", None) or getattr(citation, "court_name", None)
        decision_date = getattr(citation, "decision_date", None) or getattr(citation, "date", None)
        if isinstance(citation, dict):
            case_number = case_number or citation.get("canonical_case_number") or citation.get("case_number")
            court = court or citation.get("court") or citation.get("court_name")
            decision_date = decision_date or citation.get("decision_date") or citation.get("date")
        self._case_rows()  # Populate the per-document exact-number index once.
        normalized = str(case_number or "").replace(" ", "")
        rows = self._case_number_index.get(normalized, []) if normalized else self._case_rows()
        return lookup_records(rows, normalized, court=court,
                              decision_date=str(decision_date or "") or None)

    def search_case_table(self, text: str, *, citations=None, limit: int = 5) -> list[dict]:
        """Claim-level search over every eligible case-table row.

        Holding/reason are ordered before the issue text so the existing
        request envelope receives the most probative editorial material first.
        """
        rows = self._case_rows()
        if not rows:
            return []
        exact_ids = set()
        for citation in citations or []:
            match = self.match_case(citation)
            if match.get("record_id"):
                exact_ids.add(match["record_id"])
            exact_ids.update(match.get("record_ids") or [])
        query = str(text or "")
        from .relevance import salient_words
        words = salient_words(query, limit=12)
        if not words:
            import re
            words = list(dict.fromkeys(re.findall(r"[가-힣]{2,}", query)))[:12]
        ranked = []
        for row in rows:
            hay = " ".join([row.get("title", ""), row.get("issue", ""), row.get("reason", ""),
                            row.get("holding", ""), row.get("facts", "")])
            score = (1000 if row.get("record_id") in exact_ids else 0) + sum(hay.count(w) for w in words)
            exact = row.get("record_id") in exact_ids
            if exact or score >= 2:
                ranked.append((score, row, exact))
        ranked.sort(key=lambda pair: (-pair[0], pair[1].get("file_id", ""), pair[1].get("row", 0)))
        result = []
        exact_ranked = [item for item in ranked if item[2]]
        related_ranked = [item for item in ranked if not item[2]][:max(0, limit - len(exact_ranked))]
        for _score, row, exact in (exact_ranked + related_ranked)[:limit]:
            source = self.eligible.get(row["file_id"], {})
            # One source item remains within the established 800-character
            # claim envelope; the review layer applies masking before use.
            holding = row.get("holding") or ""
            support = " | ".join(filter(None, [row.get("case_head"), holding, row.get("reason"), row.get("issue")]))
            result.append({**source, "source_id": "", "text": support[:800], "page": row.get("row", 1),
                           "relevance": _score, "structured_case_table": exact,
                           "case_table_candidate": True,
                           "case_record_id": row.get("record_id"), "case_head": row.get("case_head"),
                           "sheet": row.get("sheet"), "row": row.get("row"),
                           "source_cell_range": row.get("source_cell_range"),
                           "case_numbers": row.get("case_numbers", []), "court": row.get("court"),
                           "decision_date": row.get("decision_date"), "holding": holding})
        return result
