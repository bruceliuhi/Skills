#!/usr/bin/env python3
"""
PPT制作与美化专家 - Slide Roster Helpers

Orders slide SVG filenames by numeric segments for consistent page rosters.

Usage:
    Imported by export, validation, preview, animation, and narration tools.

Examples:
    discover_slide_svgs(Path("projects/demo/svg_output"))

Dependencies:
    None (only uses standard library)
"""

from __future__ import annotations

from _flat_layout import activate as _activate_flat_layout, asset as _bundle_path
_activate_flat_layout()

import re
from pathlib import Path


_NUMBER_RE = re.compile(r"(\d+)")


def _slide_filename_sort_key(
    path: Path,
) -> tuple[tuple[tuple[int, int | str], ...], str]:
    """Order numeric filename segments by value, then break ties by name."""
    name = path.name
    folded = name.casefold()
    segments = tuple(
        (0, int(segment)) if segment.isdigit() else (1, segment)
        for segment in _NUMBER_RE.split(folded)
    )
    return segments, name


def discover_slide_svgs(directory: Path) -> list[Path]:
    """Return direct child SVG files in numeric filename order."""
    return sorted(
        directory.glob("*.svg"),
        key=_slide_filename_sort_key,
    )
