import copy
import json

from packages.report_engine.source_objects import compact_sources, resolve_source


def test_source_pool_is_lossless_preserves_versions_and_does_not_mutate_input():
    raw = {"law_id": "synthetic", "version_id": "v1", "full_text": "source " * 2000,
           "provisions": [{"number": "1", "text": "first"}], "detail_raw": {"original": "original " * 2000}}
    verdicts = [{"citation_id": str(i), "reference_date": "2026-01-01",
                 "official_record": copy.deepcopy(raw), "review": {"provision": {"text": "cited text"}}} for i in range(20)]
    verdicts.append({"official_record": {**raw, "version_id": "v2"}, "reference_date": "2026-09-01"})
    original = {"documents": [{"engine_data": {"legal_verdicts": verdicts, "legal_reviews": [{"verdicts": verdicts}]},
                  "source_records": [{"source_record_id": "s1", "response_hash": "hash", "payload": raw}]}]}
    snapshot = copy.deepcopy(original)
    compact = compact_sources(original)
    assert original == snapshot
    assert len(json.dumps(compact)) < len(json.dumps(original)) / 10
    assert len(compact["source_objects"]) == 2
    doc = compact["documents"][0]
    record = doc["engine_data"]["legal_verdicts"][0]["official_record"]
    assert record["text"] == "cited text" and record["version_id"] == "v1"
    assert resolve_source(compact, record) == raw
    assert resolve_source(compact, doc["source_records"][0]["payload"]) == raw
    assert doc["source_records"][0]["response_hash"] == "hash"
    assert compact_sources(compact) == compact
    assert resolve_source({}, raw) == raw


def test_small_and_absent_source_records_keep_legacy_shape():
    payload = {"documents": [{"engine_data": {"legal_verdicts": [{"official_record": None},
        {"official_record": {"court": "synthetic", "full_text": "short"}}]}, "source_records": []}]}
    assert compact_sources(payload) == payload


def test_saved_report_reexport_keeps_original_source_pool():
    from packages.report_engine.exporters import to_payload
    from packages.report_engine.snapshot import view_from_snapshot
    from packages.verification_engine.pipeline import DocumentResult, VerificationRunResult
    run = VerificationRunResult("r", "p", "COMPLETED", "key")
    raw = {"law_id": "example", "full_text": "source " * 3000}
    run.documents = [DocumentResult("d", "file.pdf", engine_data={"legal_verdicts": [{"official_record": raw}]})]
    first = to_payload(run)
    snapshot = {"engine_result": first, "report": {"state": "DRAFT", "audience": "INTERNAL"}}
    second = to_payload(view_from_snapshot(snapshot, "snapshot-hash"))
    record = second["documents"][0]["engine_data"]["legal_verdicts"][0]["official_record"]
    assert resolve_source(second, record) == raw
    assert second["source_objects"] == first["source_objects"]
