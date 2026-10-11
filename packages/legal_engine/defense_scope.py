"""Source-preserving quotation and clause scope for the existing defense rule."""
from __future__ import annotations

import re
from typing import Any

from .polarity import ASSERTED, polarity


def mask_quotations(text: str) -> tuple[str, list[tuple[int, int]], bool]:
    """Mask delimited speech while keeping offsets into the original statement."""
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
    # Preserve unclosed speech for uncertain review; masking it would erase a
    # potentially authored claim instead of acknowledging missing structure.
    masked = list(text)
    for start, end in spans:
        masked[start:end] = [' '] * (end - start)
    return ''.join(masked), spans, bool(stack)


def clause_end(text: str, anchor_end: int, breaks: re.Pattern[str]) -> int:
    return next((match.end() for match in breaks.finditer(text) if match.end() >= anchor_end), len(text))


def categorical_patterns(patterns: list[str]) -> list[str]:
    """Expand only grammatical focus particles in configured subject slots."""
    return [pattern.replace('(?:이|은)?', '(?:이|은|도|조차|마저)?') for pattern in patterns]


def conclusion_scopes(
    text: str, categorical: list[str], limited: list[str], breaks: re.Pattern[str],
    *, previous: str = '', start: int = 0, speaker_prefix: str = '',
    excluded_spans: list[tuple[int, int]] | None = None,
) -> list[dict[str, Any]]:
    """Classify each configured effect's speaker and its own limit span."""
    masked, _, uncertain_quote = mask_quotations(text)
    uncertain_quote = uncertain_quote or mask_quotations(speaker_prefix + text)[2]
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
                'clause_end': end,
                'speaker': speaker,
                'uncertain_quotation': uncertain_quote,
                'limited': any(left <= match.start() and match.end() <= right for left, right in limits),
                'authored': speaker == ASSERTED,
            })
    return sorted(observed, key=lambda observation: observation['span'])
