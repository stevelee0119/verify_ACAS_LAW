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
TOPIC_WINDOW = 800
TOPIC_STEP = 600

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
    counts = Counter(query_tokens(text))
    weights = {}
    for term, count in counts.items():
        df = document_frequency.get(term, 0)
        if total_chunks >= RATIO_MIN_CHUNKS and df / total_chunks > MAX_DF_RATIO:
            continue
        weights[term] = (1 + math.log(count)) * idf(max(df, 1), max(total_chunks, 1))
    top = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))[:QUERY_TERMS]
    return dict(top)


def query_profiles(text, document_frequency, total_chunks):
    """Multi-issue pleadings need local queries; unrelated terms retain their weight in every window."""
    profiles = [query_profile(text, document_frequency, total_chunks)]
    if len(text) > 1200:
        for start in range(0, len(text), TOPIC_STEP):
            part = text[start:start + TOPIC_WINDOW]
            if len(part) < 160:
                continue
            profile = query_profile(part, document_frequency, total_chunks)
            if len(profile) >= MIN_MATCHED_TERMS:
                profiles.append(profile)
    return profiles


QUERY_NOISE = frozenset("으로 에서 관한 관하여 대하여 따라 위한 위한 것은 되는 하는 있습니다 합니다 원고 피고 제호 호증".split())
QUERY_NOISE_TOKENS = frozenset(tokens(" ".join(QUERY_NOISE)))
FORMAL_ENDING = re.compile(r"(?:하였|되었|이었|였|있|없|않|합|됩|입|습)?(?:습니다|습니까|니다|니까)(?=\s|[.,!?;:)]|$)")


def query_text(text):
    text = FORMAL_ENDING.sub("", text)
    text = re.sub(r"(?:갑|을|병|정)\s*제?\s*\d+(?:\s*[,~]\s*\d+)*\s*호증(?:의\s*\d+)?", " ", text)
    text = re.sub(r"\d[\d,.]*\s*(?:원|년|월|일|%)(?:정)?", " ", text)
    return text


def query_tokens(text):
    return [term for term in tokens(query_text(text)) if term not in QUERY_NOISE_TOKENS and not term.isdigit()]


def priority_reference(item, text):
    """Search subject-matching standard casebooks independently, without waiving body relevance."""
    title = re.sub(r"\s+", "", item.get("title") or item.get("name") or "")
    subjects = re.findall(r"([가-힣]{1,20}법)표준판례", title)
    compact = re.sub(r"\s+", "", text)
    return any(subject in compact for subject in subjects)


def metadata_priority(item, text):
    """Ordering signal only. A matching title never bypasses the body relevance gate."""
    words = Counter(re.findall(r"[가-힣]{3,}|[a-zA-Z]{3,}", query_text(text[:100000]).lower()))
    name = (item.get("folder_path", "") + " " + base_name(item.get("name")) + " " +
            str(item.get("description") or "")[:2000]).lower()
    matches = [word for word, _ in words.most_common(80)
               if word not in QUERY_NOISE and word in name]
    score = sum((1 + math.log(words[word])) * len(word) for word in matches)
    if score:
        score += 2 if re.search(r"업무편람|가이드북|사안처리|매뉴얼|지침|해설|질의회신|판례집", name) else 0
    return {"score": round(score, 3), "matched_terms": matches[:20]}


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


# --- 열기 전 선정(metadata gate): 폴더·파일명·설명과 Drive 본문 검색으로 열어 볼 파일만 고른다 -------------------
# 파일명만으로는 관련성을 확정할 수 없으므로 여기서는 '열어 볼 후보'만 정하고, 사용 여부는 연 뒤 본문 관련도가 정한다.
GATE_MIN_SCORE = 0.25        # 파일의 폴더·파일명 핵심어(희소도 가중) 중 검사 문서에 나오는 비율
GATE_MIN_TERMS = 2           # 일치해야 하는 이름 핵심어 수(한 글자 겹침·우연 일치 방지)
GATE_MAX_CANDIDATES = 24     # 한 번의 분석에서 새로 열어 볼 후보 상한(이미 색인된 파일은 제외)
FULLTEXT_TERMS = 2           # 문서마다 Drive 본문 검색에 함께(AND) 넣는 핵심 단어 수

JOSA_END = re.compile(r"(?:에서는|으로서|으로써|에게서|이라는|이라고|에서|에게|으로|부터|까지|보다|처럼|이며|이고|"
                      r"하였다|하였고|하여|하는|하고|한다|했다|된다|되어|되는|은|는|을|를|에|로|와|과|도|만)$")
# '의·이·가'는 떼지 않는다: 주의·합의·이의·평가처럼 이 글자로 끝나는 명사가 많다.
WORD_NOISE = frozenset("원고 피고 법원 대법원 판결 법률 법령 조항 규정 주장 사건 경우 대하여 관하여 따라 위하여 있다 "
                       "없다 한다 것이 것은 등의 이유 내용 사실 부분 관계 해당 다음 이상 이하 이후 이전 기재 제출 청구 "
                       "판단 인정 검토 검증 확인 문서 자료 데이터 시스템 결과 관련 방법 기준 이를 그러나 따라서".split())
LATIN_NOISE = frozenset("the and for with from under into over this that pdf hwp docx".split())


def gate_weights(items):
    """파일마다 이름 핵심어(폴더·파일명·설명의 한글 2자 조각)와 파일 이름들 사이의 희소도 가중치."""
    # 파일명의 번호(연도·일련번호)는 주제를 알려 주지 않으므로 뺀다.
    names = {item["id"]: {t for t in name_terms(item.get("folder_path"), str(item.get("name", "")) + " " +
                                                str(item.get("description") or "")[:500])
                          if not t.isdigit() and (re.match(r"[가-힣]", t) or (len(t) >= 3 and t not in LATIN_NOISE))}
             for item in items}
    frequency = Counter(term for terms in names.values() for term in terms)
    total = max(len(names), 1)
    return {file_id: {term: idf(frequency[term], total) for term in terms} for file_id, terms in names.items()}


def gate_score(weights, document_terms):
    covered, hits = name_coverage(weights, document_terms)
    return round(covered, 3), hits


def salient_words(text, limit=FULLTEXT_TERMS):
    """Drive 본문 검색에 쓸 문서의 대표 단어(조사를 뗀 2자 이상 한글 단어 중 자주 나오는 것)."""
    stems = [JOSA_END.sub("", word) for word in re.findall(r"[가-힣]{2,}", query_text(text))]
    known = set(stems)
    counts = Counter()
    for stem in stems:
        # '이·가·의'는 뗀 형태가 문서에 따로 쓰였을 때만 조사로 본다(수급인이→수급인, 영장주의는 그대로).
        if len(stem) >= 3 and stem[-1] in "이가의" and stem[:-1] in known:
            stem = stem[:-1]
        if len(stem) >= 2 and stem not in WORD_NOISE and not re.search(r"(?:습니다|니다|이다)$", stem):
            counts[stem] += 1
    ranked = sorted(counts.items(), key=lambda kv: (-(kv[1] * min(len(kv[0]), 4)), kv[0]))
    return [word for word, count in ranked if count >= 2][:limit]


def name_gate_passes(weights, text):
    """이 문서 기준으로 이름·경로가 열어 볼 후보에 해당하는지(문서별 미검토 후보 판정용)."""
    score, hits = gate_score(weights, set(query_tokens(text)))
    return score >= GATE_MIN_SCORE and len(hits) >= GATE_MIN_TERMS


def metadata_gate(items, queries, fulltext_hits=None):
    """열어 볼 파일을 고른다. 반환: {file_id: {score, terms, fulltext, selected, reason}}.

    선정 근거: ① 이름 점수가 기준 이상이고 일치 핵심어가 2개 이상 ② Drive 본문 검색 적중 ③ 기존 제목 우선순위
    (metadata_priority) 적중. 후보가 많으면 점수 순으로 상한까지만 고른다."""
    weights = gate_weights(items)
    per_query = [set(query_tokens(q)) for q in queries if q]
    fulltext_hits = fulltext_hits or {}
    out, per_file = {}, {}
    texts = [q for q in queries if q]
    for item in items:
        file_id = item["id"]
        best, terms = 0.0, []
        scores = []
        for document_terms in per_query:
            score, hits = gate_score(weights[file_id], document_terms)
            scores.append(score)
            if (score, len(hits)) > (best, len(terms)):
                best, terms = score, hits
        # 제목 단어 일치는 한글 단어가 맞을 때만 인정한다(영문 일반어 'system' 같은 우연 일치 방지).
        priorities = [m["score"] if any(re.match(r"[가-힣]", w) for w in m["matched_terms"]) else 0
                      for m in (metadata_priority(item, q) for q in texts)]
        priority = max(priorities, default=0)
        per_file[file_id] = list(zip(scores, priorities))
        reasons = []
        if best >= GATE_MIN_SCORE and len(terms) >= GATE_MIN_TERMS:
            reasons.append("NAME_PATH_MATCH")
        if file_id in fulltext_hits:
            reasons.append("DRIVE_FULLTEXT_MATCH")
        if priority > 0:
            reasons.append("TITLE_WORD_MATCH")
        out[file_id] = {"score": best, "terms": terms[:8], "fulltext": fulltext_hits.get(file_id, []),
                        "title_priority": priority, "selected": bool(reasons),
                        "reason": "+".join(reasons) or "NAME_PATH_NOT_RELATED"}
    # 문서별 순위: 문서마다 자기 후보를 점수 순으로 줄 세우고, 파일의 순위는 가장 앞선 문서 기준이다.
    # 여는 순서와 상한을 이 순위로 정하면 시간 예산이 한 문서의 후보에 몰리지 않는다(각 문서의 1순위부터 연다).
    selected = [f for f in out if out[f]["selected"]]
    for f in selected:
        out[f]["rank"] = len(selected)
    for index in range(len(texts)):
        order = sorted((f for f in selected if per_file[f] and (per_file[f][index][0] > 0 or per_file[f][index][1] > 0
                                                                or out[f]["fulltext"])),
                       key=lambda f: (-(len(out[f]["fulltext"]) > 0), -per_file[f][index][0], -per_file[f][index][1], f))
        for position, f in enumerate(order):
            out[f]["rank"] = min(out[f]["rank"], position)
    ranked = sorted(selected, key=lambda f: (out[f]["rank"], -(len(out[f]["fulltext"]) > 0), -out[f]["score"],
                                             -out[f]["title_priority"], f))
    for file_id in ranked[GATE_MAX_CANDIDATES:]:
        out[file_id].update(selected=False, reason="CANDIDATE_LIMIT")
    return out


def gate_thresholds():
    return {"min_score": GATE_MIN_SCORE, "min_terms": GATE_MIN_TERMS, "max_candidates": GATE_MAX_CANDIDATES,
            "fulltext_terms": FULLTEXT_TERMS}
