#!/usr/bin/env python3
"""SVG Editor subpackage for ppt-master — annotation read/write utilities and web server."""

from _flat_layout import activate as _activate_flat_layout, asset as _bundle_path
_activate_flat_layout()
if __name__ == '__main__' and not __package__:
    __package__ = 'svg_editor'
