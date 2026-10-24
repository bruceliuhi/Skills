#!/usr/bin/env python3
"""
PPT制作与美化专家 - Page Context Compatibility Module

Re-export the project-management page-context API from its domain package.
New internal imports should use ``project_management.page_context``.

Usage:
    Import the public projection helpers from this module.

Examples:
    from page_context import build_page_context

Dependencies:
    Same as project_management.page_context.
"""

from _flat_layout import activate as _activate_flat_layout, asset as _bundle_path
_activate_flat_layout()

from project_management.page_context import (
    LOCK_PROJECTION_TOKEN_TARGET,
    PAGE_CONTEXT_REPORT_SCHEMA,
    PAGE_CONTEXT_SCHEMA,
    PAGE_CONTEXT_TOKEN_TARGET,
    PAGE_CONTEXT_USAGE_SCHEMA,
    TOKEN_ENCODING,
    PageContextError,
    PageContextResult,
    PageRead,
    build_page_context,
    normalize_page_key,
    page_context_usage_report,
    record_page_context_usage,
    render_page_context,
)

__all__ = [
    "LOCK_PROJECTION_TOKEN_TARGET",
    "PAGE_CONTEXT_REPORT_SCHEMA",
    "PAGE_CONTEXT_SCHEMA",
    "PAGE_CONTEXT_TOKEN_TARGET",
    "PAGE_CONTEXT_USAGE_SCHEMA",
    "TOKEN_ENCODING",
    "PageContextError",
    "PageContextResult",
    "PageRead",
    "build_page_context",
    "normalize_page_key",
    "page_context_usage_report",
    "record_page_context_usage",
    "render_page_context",
]
