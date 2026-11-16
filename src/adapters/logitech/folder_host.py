"""Compatibility import for the optional Shared DynamicFolder host.

Normal SDK adapter/transport use does not instantiate this optional host.
"""
from extensions.shared_folders.host import FolderRuntimeHost
