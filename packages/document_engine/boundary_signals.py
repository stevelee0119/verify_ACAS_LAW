"""Traceable PDF boundary observations, without lexical classification."""
from __future__ import annotations

import math
from statistics import median
from typing import Any

JOIN_CONFIRMED = "JOIN_CONFIRMED"
SPACE_CONFIRMED = "SPACE_CONFIRMED"
UNKNOWN = "UNKNOWN"
BOUNDARY_SIGNALS = frozenset({JOIN_CONFIRMED, SPACE_CONFIRMED, UNKNOWN})


def glyph_line_evidence(chars: list[dict[str, Any]], indices: list[int]) -> dict[str, Any]:
    """Summarize existing glyphs before stripping line-edge spaces.

    No missing space, full endpoint or regular font establishes word continuity.
    Source indices refer to the original page.chars array, not reconstructed text.
    """
    widths, gaps, space_widths = [], [], []
    usable = bool(chars)
    for index, char in enumerate(chars):
        try:
            x0, x1 = float(char["x0"]), float(char["x1"])
            size = float(char.get("size", 0))
            usable &= (all(math.isfinite(v) for v in (x0, x1, size))
                       and x1 > x0 and size > 0 and bool(char.get("upright", True)))
            if str(char.get("text", "")).isspace():
                space_widths.append(x1 - x0)
            else:
                widths.append(x1 - x0)
            if index:
                gap = x0 - float(chars[index - 1]["x1"])
                usable &= gap >= -0.05 * size
                if (not str(char.get("text", "")).isspace()
                        and not str(chars[index - 1].get("text", "")).isspace()):
                    gaps.append(gap)
        except (KeyError, TypeError, ValueError):
            usable = False
    nonspace = [i for i, c in enumerate(chars) if str(c.get("text", "")).strip()]
    leading = list(range(nonspace[0])) if nonspace else []
    trailing = list(range(nonspace[-1] + 1, len(chars))) if nonspace else []
    # Only actual source whitespace glyphs count; coordinates alone do not.
    leading = [indices[i] for i in leading if str(chars[i].get("text", "")).isspace()]
    trailing = [indices[i] for i in trailing if str(chars[i].get("text", "")).isspace()]
    advance = median(widths) if widths else 0.0
    return {
        "source_glyph_indices": indices,
        "usable": bool(usable and nonspace),
        "leading_space_glyphs": leading,
        "trailing_space_glyphs": trailing,
        "char_advance": advance,
        "char_gap_em": median(gaps) / advance if gaps and advance > 0 else None,
        "space_gap_em": median(space_widths) / advance if space_widths and advance > 0 else None,
    }


def observe_boundary(previous: dict[str, Any], following: dict[str, Any]) -> dict[str, Any]:
    """Return a conservative boundary observation from adjacent source lines."""
    left = previous.get("glyph_boundary_evidence", {})
    right = following.get("glyph_boundary_evidence", {})
    spaces = left.get("trailing_space_glyphs", []) + right.get("leading_space_glyphs", [])
    usable = bool(left.get("usable") and right.get("usable"))
    confirmed = usable and bool(spaces)
    return {
        "boundary_signal": SPACE_CONFIRMED if confirmed else UNKNOWN,
        "reason": ("DIRECT_SPACE_GLYPH" if confirmed else
                   "NO_DIRECT_BOUNDARY_EVIDENCE" if usable else "UNUSABLE_GLYPH_GEOMETRY"),
        "space_glyph_indices": spaces,
        "previous_glyph_indices": left.get("source_glyph_indices", []),
        "following_glyph_indices": right.get("source_glyph_indices", []),
        "char_gap_em": left.get("char_gap_em"),
        "space_gap_em": left.get("space_gap_em"),
    }
