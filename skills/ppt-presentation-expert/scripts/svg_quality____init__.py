#!/usr/bin/env python3
"""PPT制作与美化专家 SVG quality-check internals.

Use the stable ``scripts/svg_quality_checker.py`` entry point for CLI execution
and compatibility imports.

Usage:
    Import through ``svg_quality_checker``.

Examples:
    from svg_quality_checker import SVGQualityChecker

Dependencies:
    Local PPT制作与美化专家 validation modules.
"""

from _flat_layout import activate as _activate_flat_layout, asset as _bundle_path
_activate_flat_layout()
if __name__ == '__main__' and not __package__:
    __package__ = 'svg_quality'
