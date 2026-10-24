#!/usr/bin/env python3
"""
PPT制作与美化专家 - PPTX Shape Errors

Shared exception types for the DrawingML preset-geometry package.

Usage:
    Import exception classes from pptx_shapes.errors.

Examples:
    from pptx_shapes.errors import FormulaEvaluationError

Dependencies:
    None (only uses standard library)
"""

from _flat_layout import activate as _activate_flat_layout, asset as _bundle_path
_activate_flat_layout()
if __name__ == '__main__' and not __package__:
    __package__ = 'pptx_shapes'


class PresetShapeError(ValueError):
    """Base error for invalid preset-shape data or evaluation input."""


class PresetShapeDataError(PresetShapeError):
    """Raised when the bundled preset catalog is incomplete or malformed."""


class FormulaSyntaxError(PresetShapeError):
    """Raised when a DrawingML guide formula has invalid syntax."""


class FormulaEvaluationError(PresetShapeError):
    """Raised when a syntactically valid formula cannot be evaluated."""


class UnknownGuideError(PresetShapeError):
    """Raised when a formula references an unknown guide token."""


class UnknownPresetShapeError(KeyError):
    """Raised when a preset name is absent from the locked shape catalog."""
