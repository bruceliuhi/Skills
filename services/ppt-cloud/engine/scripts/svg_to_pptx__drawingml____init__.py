"""DrawingML conversion helpers for SVG-to-PPTX export."""

from _flat_layout import activate as _activate_flat_layout, asset as _bundle_path
_activate_flat_layout()
if __name__ == '__main__' and not __package__:
    __package__ = 'svg_to_pptx.drawingml'
