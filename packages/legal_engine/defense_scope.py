"""Source-preserving quotation and clause scope for the existing defense rule."""
from __future__ import annotations

import re
from typing import Any

from .polarity import ASSERTED, REPORTED, REPORT_VERB_RE, polarity


def quotation_projection(text: str, *, previous: str = '') -> tuple[str, list[dict[str, Any]]]:
    """Exclude confirmed speech, retaining authored terminology and emphasis.

    Quote punctuation establishes a span, not a speaker. Its matrix speech
    relation uses the same report/citation evidence as the other legal rules.
    All coordinates stay in this input string; no document-global claim is made.
    """
    pairs = {'"': '"', "'": "'", '“': '”', '‘': '’', '「': '」', '『': '』'}
    stack: list[tuple[str, int]] = []
    spans = []
    for index, character in enumerate(text):
        if (character == "'" and 0 < index < len(text) - 1
                and all(neighbor.isascii() and neighbor.isalpha() for neighbor in (text[index - 1], text[index + 1]))):
            continue  # Word-internal apostrophe, rather than a speech delimiter.
        if stack and character == stack[-1][0]:
            _, start = stack.pop()
            if not stack:
                spans.append((start, index + 1))
        elif character in pairs:
            stack.append((pairs[character], index))
    masked = list(text)
    observations = []
    for start, end in spans:
        # Neutralize delimiters before asking about the outer predicate. The
        # quoted proposition itself remains the trigger, not its own negation.
        outer = text[:start] + ' ' + text[start + 1:end - 1] + ' ' + text[end:]
        tail = text[end:].lstrip()
        quotative = bool(re.match(r'(?:라고|다고|라는|다는|고)(?=\s|[가-힣]|[,;.!?]|$)', tail))
        speech_relation = quotative or bool(REPORT_VERB_RE.match(tail))
        reported = speech_relation and polarity(outer, (start, end), previous=previous) == REPORTED
        role = 'REPORTED' if reported else 'UNCERTAIN' if quotative else 'AUTHORED'
        if reported:
            masked[start:end] = [' '] * (end - start)
        else:
            masked[start] = masked[end - 1] = ' '
        observations.append({'span': [start, end], 'role': role})
    if stack:
        observations.append({'span': [stack[0][1], len(text)], 'role': 'UNCLOSED'})
    return ''.join(masked), observations


def mask_quotations(text: str) -> tuple[str, list[tuple[int, int]], bool]:
    """Compatibility view of the role-aware, source-preserving projection."""
    masked, rows = quotation_projection(text)
    return masked, [tuple(row['span']) for row in rows], any(
        row['role'] in {'UNCERTAIN', 'UNCLOSED'} for row in rows)


def clause_end(text: str, anchor_end: int, breaks: re.Pattern[str]) -> int:
    return next((match.end() for match in breaks.finditer(text) if match.end() >= anchor_end), len(text))


def categorical_patterns(patterns: list[str]) -> list[str]:
    """Expand only grammatical focus particles in configured subject slots."""
    return [pattern.replace('(?:이|은)?', '(?:이|은|도|조차|마저)?') for pattern in patterns]


# Finite morphology supplies review candidates, never a domain vocabulary or
# proof that a nonpast negative is a legal exemption rather than a fact.
_FINITE_NEGATIVE_EFFECT_RE = re.compile(
    r"(?<![가-힣])(?P<argument>[가-힣]+?)(?:을|를)\s+"
    r"(?:[가-힣]+(?:히|게)\s+)*"
    r"(?P<predicate>[가-힣]+?(?:지는|지도|지)\s*(?:않는다|않습니다|못한다))"
    r"(?=\s|[,;.!?]|$)"
)
SUBJECT_CASE_RE = re.compile(r"(?<![가-힣])(?P<argument>[가-힣]{2,}?)(?:이|가|은|는)(?=\s|[,;.!?]|$)")
_OBJECT_CASE_RE = re.compile(r"(?<![가-힣])(?P<argument>[가-힣]+?)(?:을|를)(?=\s|[,;.!?]|$)")
_EXPLICIT_CONCLUSION_LINK_RE = re.compile(r"^\s*(?:따라서|그러므로|그렇기에|이에)(?=\s|,)")


def linked_conclusion_text(
    previous_text: str, text: str, categorical: list[str], limited: list[str],
    breaks: re.Pattern[str], anchor: re.Pattern[str],
) -> tuple[str, dict[str, Any]] | None:
    """Supply only an immediately prior authored anchor with an explicit link.

    An introduced subject needs a shared argument head from the prior limited
    conclusion. An unexplained subject/topic reset cannot inherit its premise.
    Returned spans are local to the two source sentences, not the document.
    """
    link = _EXPLICIT_CONCLUSION_LINK_RE.match(text)
    if not link or not previous_text:
        return None
    projected, rows = quotation_projection(previous_text)
    match = anchor.search(projected)
    if match is None or any(row['role'] in {'UNCERTAIN', 'UNCLOSED'} for row in rows):
        return None
    prior_scopes = conclusion_scopes(previous_text, categorical, limited, breaks,
                                    start=match.end('concession'), projected_text=projected)
    if not any(row['authored'] for row in prior_scopes):
        return None
    current, _ = quotation_projection(text, previous=previous_text)
    subjects = list(SUBJECT_CASE_RE.finditer(current[link.end():]))
    if subjects:
        heads = [argument.group('argument') for pattern in limited
                 for limit in re.finditer(pattern, projected)
                 for argument in _OBJECT_CASE_RE.finditer(limit.group())]
        if not heads or any(not any(subject.group('argument').endswith(head) for head in heads)
                            for subject in subjects):
            return None
    combined = previous_text + ' ' + text
    return combined, {'relation': 'EXPLICIT_IMMEDIATE_CONCLUSION',
                      'prior_sentence_span': [0, len(previous_text)],
                      'current_sentence_span': [len(previous_text) + 1, len(combined)],
                      'link_span': [len(previous_text) + 1 + link.start(),
                                    len(previous_text) + 1 + link.end()]}


def conclusion_scopes(
    text: str, categorical: list[str], limited: list[str], breaks: re.Pattern[str],
    *, previous: str = '', start: int = 0, speaker_prefix: str = '',
    excluded_spans: list[tuple[int, int]] | None = None,
    projected_text: str | None = None, quotation_uncertain: bool = False,
) -> list[dict[str, Any]]:
    """Classify each configured effect's speaker and its own limit span."""
    if projected_text is None:
        projected, rows = quotation_projection(speaker_prefix + text, previous=previous)
        masked = projected[len(speaker_prefix):]
        uncertain_quote = any(row['role'] in {'UNCERTAIN', 'UNCLOSED'} for row in rows)
    else:
        masked, uncertain_quote = projected_text, quotation_uncertain
    limits = [match.span() for pattern in limited for match in re.finditer(pattern, masked)]
    observed = []
    for pattern in categorical_patterns(categorical):
        # Focus particles occupy the same grammatical subject slot as nominative
        # and topic particles; the legal predicate vocabulary stays configured.
        for match in re.finditer(pattern, masked):
            if match.start() < start:
                continue
            if any(left < match.end() and match.start() < right for left, right in excluded_spans or []):
                continue
            end = clause_end(masked, match.end(), breaks)
            speaker = polarity(speaker_prefix + masked[:end],
                               (len(speaker_prefix) + match.start(), len(speaker_prefix) + match.end()),
                               previous=previous)
            observed.append({
                'span': list(match.span()),
                'candidate_kind': 'CONFIGURED',
                'scope_uncertain': False,
                'clause_end': end,
                'speaker': speaker,
                'uncertain_quotation': uncertain_quote,
                'limited': any(left <= match.start() and match.end() <= right for left, right in limits),
                'authored': speaker == ASSERTED,
            })
    anchors = [row for row in observed if row['authored']]
    for match in _FINITE_NEGATIVE_EFFECT_RE.finditer(masked):
        if match.start() < start or any(left < match.end() and match.start() < right
                                       for left, right in excluded_spans or []):
            continue
        if any(row['span'][0] < match.end() and match.start() < row['span'][1] for row in observed):
            continue
        earlier = [row for row in anchors if row['span'][1] <= match.start()]
        if not earlier:
            continue
        anchor = max(earlier, key=lambda row: row['span'][1])
        # Preserve independent subjects and stated facts; a matrix attribution
        # or topic reset is not merely another effect of the old argument.
        between = masked[anchor['clause_end']:match.start()]
        if SUBJECT_CASE_RE.search(between):
            continue
        end = clause_end(masked, match.end(), breaks)
        speaker = polarity(speaker_prefix + masked[:end],
                           (len(speaker_prefix) + match.start(), len(speaker_prefix) + match.end()),
                           previous=previous)
        observed.append({'span': list(match.span()), 'clause_end': end,
                         'candidate_kind': 'FINITE_NEGATIVE', 'scope_uncertain': True,
                         'speaker': speaker, 'uncertain_quotation': uncertain_quote,
                         'limited': any(left <= match.start() and match.end() <= right for left, right in limits),
                         'authored': speaker == ASSERTED,
                         'argument_span': list(match.span('argument')),
                         'predicate_span': list(match.span('predicate')),
                         'anchor_span': anchor['span']})
    return sorted(observed, key=lambda observation: observation['span'])
