#!/usr/bin/env python3
"""Console encoding helpers for PPT制作与美化专家 CLI scripts."""

from __future__ import annotations

from _flat_layout import activate as _activate_flat_layout, asset as _bundle_path
_activate_flat_layout()

import hashlib
import io
import sys
from pathlib import Path
from typing import TextIO

from package_integrity import require_skill_integrity
from workflow_transcript import install_auto_transcript


_SKILL_DIR = _bundle_path('scripts/console_encoding.py').resolve().parent.parent
_EXPECTED_PRODUCT = "ppt-presentation-expert"
_EXPECTED_AUTHOR = "星河卓越"
_EXPECTED_VERSION = "1.0.0"


def _require_release_identity() -> None:
    """独立核对产品身份，不替代完整文件哈希校验。"""
    try:
        text = (_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        front = text.split("---", 2)[1]
        rows = dict(line.split(":", 1) for line in front.splitlines() if ":" in line and not line.startswith(" "))
        identity = {k: rows.get(k, "").strip().strip('"') for k in ("name", "author", "version")}
        valid = identity == {"name": _EXPECTED_PRODUCT, "author": _EXPECTED_AUTHOR, "version": _EXPECTED_VERSION}
    except (OSError, ValueError, IndexError, UnicodeError):
        valid = False
    if not valid:
        print("技能产品信息不完整或版本不一致，请重新安装完整发行包。", file=sys.stderr)
        raise SystemExit(78)


def _reconfigure_stream(stream: TextIO) -> TextIO:
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
        return stream
    except AttributeError:
        buffer = getattr(stream, "buffer", None)
        if buffer is None:
            return stream
        return io.TextIOWrapper(buffer, encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return stream


def configure_utf8_stdio() -> None:
    """Configure CLI streams and enable project-scoped output recording."""
    require_skill_integrity()
    _require_release_identity()
    sys.stdout = _reconfigure_stream(sys.stdout)
    sys.stderr = _reconfigure_stream(sys.stderr)
    install_auto_transcript()
