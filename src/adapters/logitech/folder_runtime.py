"""Compatibility import for the optional Shared DynamicFolder projection.

New code should import from extensions.shared_folders.runtime_projection.
This module deliberately contains no optional folder policy itself.
"""
from extensions.shared_folders.runtime_projection import (
    VERSION, MAX_LAYOUT_BYTES, FolderRuntimeError,
    validate_layout, initial_layout, project_virtual_folders, folder_source,
)
