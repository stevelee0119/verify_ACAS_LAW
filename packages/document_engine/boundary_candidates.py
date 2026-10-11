"""Lazy source-aligned boundary hypotheses; primary text remains unchanged.

These records describe interpretation uncertainty. They are neither additional
checked findings nor independent evidence for a chosen separator.
"""
from __future__ import annotations

import unicodedata
from typing import Any

from packages.common.schemas import Block, NormalizedDocument
from .boundary_signals import JOIN_CONFIRMED, UNKNOWN


def boundary_decision(
    index: int, observed: str, separator: str, reason: str, *,
    legacy_prev_full: bool, legacy_char_wrap: bool, legacy_right_edge: float,
    page_width: float, legacy_content_edge: float,
) -> dict[str, Any]:
    choices = [('', 'JOIN'), (' ', 'SPACE')]
    if observed != UNKNOWN:
        choices = [(separator, 'JOIN' if observed == JOIN_CONFIRMED else 'SPACE')]
    return {
        'version': 1, 'observed_state': observed,
        'selected_separator': separator, 'selection_reason': reason,
        'source': {'left_line': index, 'right_line': index + 1},
        'legacy': {'prev_full': legacy_prev_full, 'char_wrap_context': legacy_char_wrap,
                   'used_for_selection': observed == UNKNOWN,
                   'right_edge': legacy_right_edge, 'page_floor': 0.75 * page_width if page_width > 0 else 0.0,
                   'content_edge': legacy_content_edge,
                   'floor_applied': legacy_right_edge > legacy_content_edge,
                   'evidence': False},
        'alternatives': [{'id': name, 'separator': value,
                          'confirmation': 'UNCONFIRMED' if observed == UNKNOWN else observed}
                         for value, name in choices],
        'alternatives_checked': False,
    }


def _line_runs(lines: list[dict[str, Any]]) -> list[str]:
    runs = []
    for index, line in enumerate(lines):
        text = unicodedata.normalize('NFKC', line['text'])
        if index:
            text = text.lstrip()
        if index < len(lines) - 1:
            text = text.rstrip()
        runs.append(text)
    return runs


def _project(runs: list[str], separators: list[str]) -> tuple[str, bool]:
    """One linear materialization; preserve legacy last-line normalization order."""
    prefix = ''.join(part for index, run in enumerate(runs[:-1])
                     for part in (run, separators[index] if index < len(runs) - 2 else ''))
    normalized = unicodedata.normalize('NFKC', prefix).rstrip()
    return normalized + separators[-1] + runs[-1], normalized == prefix


def align_boundary_sources(
    lines: list[dict[str, Any]], observations: list[dict[str, Any]], primary: str,
) -> list[dict[str, Any]]:
    runs = _line_runs(lines)
    decisions = [row['decision'] for row in observations]
    projected, exact_edges = _project(runs, [row['selected_separator'] for row in decisions])
    alignment_reason = ('PRIMARY_PROJECTION_MISMATCH' if projected != primary else
                        'NORMALIZATION_ACROSS_SOURCE_RUNS' if not exact_edges else None)
    exact_edges = exact_edges and projected == primary
    cursor, sources = 0, []
    for index, (line, run) in enumerate(zip(lines, runs)):
        original = line['text']
        normalized = unicodedata.normalize('NFKC', original)
        changed = normalized != original
        source_start = len(original) - len(original.lstrip()) if index else 0
        source_end = len(original.rstrip()) if index < len(lines) - 1 else len(original)
        glyph_available = bool(line.get('glyph_boundary_evidence', {}).get('source_glyph_indices'))
        sources.append({
            'line_index': index, 'source_block_id': line['source_block_id'],
            'source_span': [source_start, source_end],
            'primary_span': [cursor, cursor + len(run)] if exact_edges else None,
            'precision': 'EXACT_TEXT' if exact_edges and not changed else 'SOURCE_LINE_RANGE',
            'normalization_changed': changed,
            'glyph_mapping': 'LINE_ASSOCIATION' if glyph_available else 'UNAVAILABLE',
            'glyph_indices_ref': ['lines', index, 'glyph_boundary_evidence', 'source_glyph_indices'],
        })
        cursor += len(run)
        if index < len(decisions):
            decision = decisions[index]
            separator = decision['selected_separator']
            decision['alignment'] = {
                'precision': 'EXACT_TEXT' if exact_edges else 'SOURCE_LINE_RANGE',
                'primary_span': [cursor, cursor + len(separator)] if exact_edges else None,
                'reason': alignment_reason,
                'glyph_mapping': 'LINE_ASSOCIATION',
            }
            cursor += len(separator)
    return sources


def project_boundary_view(block: Block, boundary: int | None = None, choice: str | None = None) -> dict[str, Any]:
    """Materialize only the requested edge choice; all other selections stay fixed.

    Reads retained source lines; it never changes block text or promotes a
    hypothesis to evidence. No complete candidate strings are stored in metadata.
    """
    observations = block.attributes.get('boundary_observations', [])
    if not observations or any('decision' not in row for row in observations):
        if boundary is not None or choice is not None:
            raise ValueError('Block has no boundary candidates')
        return {'text': block.text, 'source_runs': [], 'boundaries': []}
    decisions = [row['decision'] for row in observations]
    separators = [row['selected_separator'] for row in decisions]
    runs = _line_runs(block.attributes['lines'])
    if _project(runs, separators)[0] != block.text:
        # A later mask/edit may replace primary text while retained source lines
        # still contain original data. Do not recover it through alternatives.
        raise ValueError('Retained source runs no longer match primary text')
    if boundary is not None:
        if not isinstance(boundary, int) or isinstance(boundary, bool) or not 0 <= boundary < len(decisions):
            raise ValueError('Invalid boundary index')
        alternative = next((row for row in decisions[boundary]['alternatives'] if row['id'] == choice), None)
        if alternative is None:
            raise ValueError('Choice is not a retained boundary hypothesis')
        separators[boundary] = alternative['separator']
    elif choice is not None:
        raise ValueError('A candidate choice requires a boundary index')
    text = _project(runs, separators)[0]
    projected_rows = [{'decision': {**decision, 'selected_separator': separator}}
                      for decision, separator in zip(decisions, separators)]
    sources = align_boundary_sources(block.attributes['lines'], projected_rows, text)
    return {'text': text, 'source_runs': sources,
            'boundaries': [{'boundary_index': index, 'source': row['decision']['source'],
                            'observed_state': row['decision']['observed_state'],
                            'selected_separator': row['decision']['selected_separator'],
                            'alignment': row['decision']['alignment'], 'alternatives_checked': False}
                           for index, row in enumerate(projected_rows)]}


def project_boundary_candidate(block: Block, boundary: int | None = None, choice: str | None = None) -> str:
    """Convenience text projection of one lazy candidate view, without mutation."""
    return project_boundary_view(block, boundary, choice)['text']


def reading_boundary_associations(block: Block, start: int, text: str) -> list[dict[str, Any]]:
    """Exact primary-text separator positions or honestly coarse block association."""
    rows = []
    trim = len(block.text) - len(block.text.lstrip())
    observations = block.attributes.get('boundary_observations', [])
    lines = block.attributes.get('lines', [])
    current_source = bool(lines and observations and all('decision' in row for row in observations)
                          and _project(_line_runs(lines), [row['decision']['selected_separator'] for row in observations])[0] == block.text)
    for index, observation in enumerate(observations):
        decision = observation.get('decision')
        if not decision:
            continue
        alignment = decision['alignment']
        span = alignment['primary_span']
        exact = current_source and span is not None and trim <= span[0] <= span[1] <= trim + len(text)
        rows.append({
            'block_id': block.block_id, 'page': block.page, 'boundary_index': index,
            'observed_state': decision['observed_state'],
            'reading_span': [start + span[0] - trim, start + span[1] - trim] if exact else [start, start + len(text)],
            'precision': 'EXACT_TEXT' if exact else 'BLOCK_ASSOCIATION',
            'verification_needed': decision['observed_state'] == UNKNOWN,
            'alternatives_checked': False,
        })
    return rows


def boundary_association_metadata(doc: NormalizedDocument) -> dict[str, Any] | None:
    """Report metadata only: no alternate engine runs, findings, warnings or grades."""
    rows = []
    for block in doc.body_blocks():
        for index, observation in enumerate(block.attributes.get('boundary_observations', [])):
            decision = observation.get('decision')
            if decision is None:
                continue
            rows.append({
                'block_id': block.block_id, 'page': block.page, 'boundary_index': index,
                'precision': 'BLOCK_ASSOCIATION', 'source': decision['source'],
                'observed_state': decision['observed_state'], 'observation_reason': observation['reason'],
                'selected_separator': decision['selected_separator'], 'selection_reason': decision['selection_reason'],
                'alternatives': decision['alternatives'], 'alternatives_checked': False,
                'verification_needed': decision['observed_state'] == UNKNOWN,
            })
    return {'version': 1, 'association_only': True, 'alternatives_checked': False,
            'unknown_count': sum(row['observed_state'] == UNKNOWN for row in rows), 'boundaries': rows} if rows else None
