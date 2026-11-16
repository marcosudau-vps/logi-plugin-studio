"""Canonical project binding shared by the standalone and integrated hosts."""
import hashlib
from pathlib import Path


def project_identity(path):
    canonical = str(Path(path).resolve()).casefold()
    return 'project.' + hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def extension_path(path):
    return Path(path).resolve().with_suffix('.vfolders.json')
