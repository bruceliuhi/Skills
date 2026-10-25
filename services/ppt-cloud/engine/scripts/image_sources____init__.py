"""Web image source providers for PPT制作与美化专家.

Each ``provider_<name>.py`` module exposes a ``search(request, *,
license_tier_filter)`` function returning a list of ``AssetCandidate``
objects, plus a ``parse_results(payload)`` helper. ``image_search.py``
dispatches to them by name.
"""

from __future__ import annotations

from _flat_layout import activate as _activate_flat_layout, asset as _bundle_path
_activate_flat_layout()
if __name__ == '__main__' and not __package__:
    __package__ = 'image_sources'
