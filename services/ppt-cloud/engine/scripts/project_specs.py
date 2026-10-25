#!/usr/bin/env python3
"""
PPT制作与美化专家 - Project Specification Compatibility Module

Re-export the project planning-artifact API from its domain package. New
internal imports should use ``project_management.project_specs``.

Usage:
    Import validation or scaffold helpers from this module.

Examples:
    from project_specs import validate_markdown_schema

Dependencies:
    Same as project_management.project_specs.
"""

from _flat_layout import activate as _activate_flat_layout, asset as _bundle_path
_activate_flat_layout()

from project_management.project_specs import (
    SCAFFOLD_DIR,
    SCHEMA_DIR,
    SKILL_DIR,
    TOOLS_DIR,
    default_spec_lock_forbidden,
    parse_markdown_artifact,
    parse_spec_lock,
    parse_spec_lock_artifact,
    parse_spec_lock_image_value,
    scaffold_project_artifact,
    validate_markdown_schema,
    validate_project_artifacts,
)

__all__ = [
    "SCAFFOLD_DIR",
    "SCHEMA_DIR",
    "SKILL_DIR",
    "TOOLS_DIR",
    "default_spec_lock_forbidden",
    "parse_markdown_artifact",
    "parse_spec_lock",
    "parse_spec_lock_artifact",
    "parse_spec_lock_image_value",
    "scaffold_project_artifact",
    "validate_markdown_schema",
    "validate_project_artifacts",
]
