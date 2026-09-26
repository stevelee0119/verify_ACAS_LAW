"""Decide whether any Drive reference is relevant enough to use, before retrieval feeds a model.

Relevance is measured against the reference corpus itself, never against topic lists:
- A term's weight is its frequency in the checked document times its rarity (IDF) in the
  indexed Drive chunks, so boilerplate shared by most references carries little weight.
- A chunk's coverage is the share of the document's weighted key terms that the chunk contains.
- Folder and file names add a bounded bonus (a file's path is evidence of its subject), but a
  file is selected only when its text also matches; a name alone never puts text in front of a model.
When no file passes, the Drive library is not used for that document.
"""
from __future__ import annotations

from collections import Counter
import math
from pathlib import Path
import re

# Thresholds are recorded in every selection log so a run JSON can be re-evaluated.
QUERY_TERMS = 40            # weighted key terms taken from the checked document
MAX_DF_RATIO = 0.5          # a term in more than half of the chunks is boilerplate for this corpus
RATIO_MIN_CHUNKS = 20       # below this corpus size a document-frequency ratio is not informative
MIN_MATCHED_TERMS = 4       # distinct key terms a chunk must share
MIN_CHUNK_COVERAGE = 0.14   # floor: share of the document's key-term weight in one chunk (a name alone never qualifies)
META_WEIGHT = 0.5           # folder/file-name coverage bonus, applied only to text-matching files
MIN_FILE_SCORE = 0.25       # best chunk coverage + META_WEIGHT x name coverage
PER_FILE_EXCERPTS = 3
CANDIDATE_CHUNKS = 300

COPY_MARK = re.compile(r"의\s*사본|\s*-\s*복사본|복사본|\s*\(\d{1,3}\)|^\s*사본\s*-\s*|^\s*copy of\s+|\s+-\s*copy\b",
                       re.IGNORECASE)
EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,5}$")


def tokens(text):
    """Korean character bigrams plus Latin/number words (the index's own tokenisation)."""
    words = re.findall(r"[a-z0-9]+|[가-힣]+", str(text).lower())
    result = []
    for word in words:
        if re.fullmatch(r"[가-힣]+", word):
            result.extend(word[i:i + 2] for i in range(len(word) - 1))
        elif len(word) > 1:
            result.append(word[:80])
    return result


def copy_marks(name):
    return len(COPY_MARK.findall(str(name or "")))


def base_name(name):
    """File name without extension and Drive/OS copy markers ("…의 사본", "Copy of …", " (1)")."""
    stem = COPY_MARK.sub("", str(name or "")).strip()
    stem = EXTENSION.sub("", stem).strip()
    return COPY_MARK.sub("", stem).strip()


def extension(name):
    return Path(COPY_MARK.sub("", str(name or "")).strip()).suffix.lower()


def name_terms(folder_path, name):
    return set(tokens((folder_path or "").replace("/", " ") + " " + base_name(name)))


def idf(df, total):
    return math.log(1 + (total - df + 0.5) / (df + 0.5))


def query_profile(text, document_frequency, total_chunks):
    """Weighted key terms of the checked document. Terms absent from the corpus are weighted like
    a term seen once, so a document about an unrelated subject keeps most of its weight unmatched."""
    counts = Counter(tokens(text))
    weights = {}
    for term, count in counts.items():
        df = document_frequency.get(term, 0)
        if total_chunks >= RATIO_MIN_CHUNKS and df / total_chunks > MAX_DF_RATIO:
            continue
        weights[term] = (1 + math.log(count)) * idf(max(df, 1), max(total_chunks, 1))
    top = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))[:QUERY_TERMS]
    return dict(top)


def name_weights(eligible):
    """IDF of folder/file-name terms across the library's own names: a word shared by many names
    (a folder, "guide", "handbook") says little about any one file."""
    names = {file_id: name_terms(v.get("folder_path"), v.get("title")) for file_id, v in eligible.items()}
    frequency = Counter(term for terms in names.values() for term in terms)
    total = max(len(names), 1)
    return {file_id: {term: idf(frequency[term], total) for term in terms} for file_id, terms in names.items()}


def name_coverage(weights, document_terms):
    """Share of a file's weighted name terms that the checked document uses."""
    total = sum(weights.values())
    if not total:
        return 0.0, []
    matched = sorted((t for t in weights if t in document_terms), key=lambda t: -weights[t])
    return sum(weights[t] for t in matched) / total, matched


def coverage(profile, terms):
    total = sum(profile.values()) or 1.0
    matched = [term for term in profile if term in terms]
    return sum(profile[t] for t in matched) / total, matched


def thresholds():
    return {"query_terms": QUERY_TERMS, "max_df_ratio": MAX_DF_RATIO, "ratio_min_chunks": RATIO_MIN_CHUNKS,
            "min_matched_terms": MIN_MATCHED_TERMS, "min_chunk_coverage": MIN_CHUNK_COVERAGE,
            "meta_weight": META_WEIGHT, "min_file_score": MIN_FILE_SCORE,
            "per_file_excerpts": PER_FILE_EXCERPTS}


def duplicate_groups(items):
    """Identical Drive files (same MD5 and size) and same-named files with different content.

    The keep candidate is the copy with the fewest copy markers in its name, then the oldest."""
    def describe(item):
        return {"file_id": item["id"], "name": item.get("name", ""), "folder_path": item.get("folder_path", ""),
                "size": int(item.get("size") or 0), "created_time": item.get("createdTime"),
                "modified_time": item.get("modifiedTime"),
                "url": "https://drive.google.com/file/d/" + item["id"] + "/view"}

    identical = {}
    for item in items:
        if item.get("md5Checksum"):
            identical.setdefault((item["md5Checksum"], item.get("size")), []).append(item)
    groups, skip = [], {}
    for members in identical.values():
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda i: (copy_marks(i.get("name")), i.get("createdTime") or "", i["id"]))
        keep, copies = members[0], members[1:]
        for copy in copies:
            skip[copy["id"]] = keep["id"]
        groups.append({"basis": "IDENTICAL_CONTENT_MD5", "keep": describe(keep),
                       "delete_candidates": [describe(c) for c in copies],
                       "reclaimable_bytes": sum(int(c.get("size") or 0) for c in copies)})
    by_name = {}
    for item in items:
        key = base_name(item.get("name")).lower()
        if key:
            by_name.setdefault(key, []).append(item)
    similar = []
    for members in by_name.values():
        digests = {m.get("md5Checksum") or m["id"] for m in members}
        if len(members) > 1 and len(digests) > 1:
            similar.append({"basis": "SAME_NAME_DIFFERENT_CONTENT", "files": [describe(m) for m in members]})
    groups.sort(key=lambda g: -g["reclaimable_bytes"])
    return groups, similar, skip
