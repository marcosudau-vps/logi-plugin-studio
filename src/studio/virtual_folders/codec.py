"""Strict, bounded extension codec and single-writer history/file owner.

NativeProjectSession and logitech-native-1 remain untouched. New exports use
an atomic, exclusive hard-link publication; only an explicitly loaded/exported
extension may subsequently be saved with optimistic disk conflict protection.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from .model import (Document, Folder, FolderError, Page, PagingCapability,
                    Placement, Reference, VERSION)

MAX_BYTES = 4 * 1024 * 1024


def encode(document):
    document.validate()
    try:
        result = (json.dumps(asdict(document), ensure_ascii=False, allow_nan=False,
                             sort_keys=True, indent=2) + '\n').encode('utf-8')
    except (TypeError, ValueError, RecursionError) as exc:
        raise FolderError(f'Extension nicht als UTF-8-JSON darstellbar: {exc}') from exc
    if len(result) > MAX_BYTES:
        raise FolderError('Extension überschreitet 4 MiB.')
    return result


def _object(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        raise FolderError(f'Erwartete JSON-Felder: {keys}')
    return value


def _array(value):
    if not isinstance(value, list):
        raise FolderError('JSON-Array erwartet.')
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise FolderError(f'Doppelter JSON-Schlüssel: {key}')
        result[key] = value
    return result


def decode(data, *, project_id, plugin_id):
    try:
        if len(data) > MAX_BYTES:
            raise FolderError('Extension überschreitet 4 MiB.')
        def invalid(value):
            raise FolderError(f'Ungültiger JSON-Zahlenwert: {value}')
        raw = json.loads(data, object_pairs_hook=_pairs, parse_constant=invalid)
        _object(raw, 'project_id plugin_id root_id folders placements version')
        if raw['version'] != VERSION:
            raise FolderError('Unbekannte Extension-Version.')
        if raw['project_id'] != project_id or raw['plugin_id'] != plugin_id:
            raise FolderError('Projektidentität / Plugin-ID stimmt nicht überein.')
        folders = []
        for f in _array(raw['folders']):
            _object(f, 'id owner name parent_id pages mode capability')
            pages = tuple(Page(**_object(p, 'id name')) for p in _array(f['pages']))
            cap = f['capability']
            if cap is not None:
                cap = PagingCapability(**_object(cap, 'slots source'))
            folders.append(Folder(**dict(f, pages=pages, capability=cap)))
        placements = []
        for p in _array(raw['placements']):
            _object(p, 'id folder_id page_id kind target position action_parameter')
            target = Reference(**_object(p['target'], 'plugin_id resource_id'))
            placements.append(Placement(**dict(p, target=target)))
        return Document(**dict(raw, folders=tuple(folders), placements=tuple(placements))).validate()
    except FolderError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as exc:
        raise FolderError(f'Ungültige Extension: {exc}') from exc


def read_bytes(path):
    with Path(path).open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise FolderError('Extension überschreitet 4 MiB.')
    return data


class ExtensionStore:
    """Separate extension history, never the native session's Undo/Redo stack."""
    def __init__(self, document):
        self.document = document.validate()
        self._saved = encode(document)
        self.path = None
        self._disk = None
        self._undo, self._redo = [], []
        self.revision = uuid4().hex

    @property
    def dirty(self):
        return encode(self.document) != self._saved

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    def commit(self, document):
        if (document.project_id, document.plugin_id) != (self.document.project_id, self.document.plugin_id):
            raise FolderError('Fremdes Projekt nicht in diese Extension übernehmen.')
        content = encode(document)
        if content == encode(self.document):
            return
        self._undo.append(self.document)
        del self._undo[:-50]
        self._redo.clear()
        self.document = document
        self.revision = uuid4().hex

    def _history(self, source, destination):
        if source:
            destination.append(self.document)
            del destination[:-50]
            self.document = source.pop()
            self.revision = uuid4().hex

    def undo(self):
        self._history(self._undo, self._redo)

    def redo(self):
        self._history(self._redo, self._undo)

    @classmethod
    def load(cls, path, *, project_id, plugin_id):
        path = cls._target(path)
        data = read_bytes(path)
        store = cls(decode(data, project_id=project_id, plugin_id=plugin_id))
        store.path, store._disk = path, data
        return store

    @staticmethod
    def _target(path):
        target = Path(path).resolve()
        if not target.name.endswith('.vfolders.json'):
            raise FolderError('Extension muss auf .vfolders.json enden.')
        return target

    def _check_disk(self):
        try:
            if read_bytes(self.path) != self._disk:
                raise FolderError('Disk-Conflict: Extension extern verändert; nichts überschrieben.')
        except OSError as exc:
            raise FolderError(f'Disk-Conflict: Extension nicht lesbar: {exc}') from exc

    def export(self, path):
        """Explicit Save As to a NEW file only; no overwrite switch."""
        self._write(self._target(path), new=True)

    def save(self):
        if self.path is None:
            raise FolderError('Zuerst explizit als neue Extension exportieren.')
        self._write(self.path, new=False)

    def _write(self, path, *, new):
        data = encode(self.document)
        if not new:
            self._check_disk()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.vfolders-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if new:
                os.link(temporary, path)  # atomic publish, EEXIST never overwrites
            else:
                self._check_disk()
                os.replace(temporary, path)
            self.path, self._disk, self._saved = path, data, data
        except OSError as exc:
            raise FolderError(f'Extension nicht gespeichert: {exc}') from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
