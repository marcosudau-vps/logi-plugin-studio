"""Optional virtual authoring data; importing this package never imports Qt."""
from .model import (Document, Folder, FolderError, Page, PagingCapability,
                    Placement, Reference)
from .navigation import Navigation

__all__ = ['Document', 'Folder', 'FolderError', 'Page', 'PagingCapability',
           'Placement', 'Reference', 'Navigation']
