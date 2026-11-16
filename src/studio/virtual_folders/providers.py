"""Small, in-process push boundary; no discovery, IPC or remote execution.

Cached display facts are transient. Only reference identities live in the
extension. An absent provider never causes removal of a placement.
"""
from dataclasses import dataclass
from typing import Callable, Protocol

from adapters.logitech.native import parse_native_project
from .model import FolderError, Reference


@dataclass(frozen=True)
class DisplayData:
    reference: Reference
    kind: str
    name: str
    available: bool
    sdk_type: str = ''


class ReferenceProvider(Protocol):
    """A later transport supplies an initial snapshot, then owner-originated pushes.

    subscribe is for all actually referenced identities, not visible entries.
    Local execution remains the native owner's responsibility.
    """
    def snapshot(self) -> tuple[DisplayData, ...]: ...
    def subscribe(self, references: frozenset[Reference], changed: Callable) -> Callable: ...


class ReferenceHub:
    def __init__(self, native_snapshot):
        self._data = {}
        self._listeners = []
        self.update_native(native_snapshot)

    def update_native(self, snapshot):
        native = parse_native_project(snapshot)
        if hasattr(self, 'plugin_id') and self.plugin_id != native.plugin_id:
            raise FolderError('Pluginwechsel benötigt einen neuen ReferenceHub.')
        self.plugin_id = native.plugin_id
        self._data = {k: v for k, v in self._data.items() if k.plugin_id != native.plugin_id}
        self.push(tuple(DisplayData(Reference(native.plugin_id, a.id), 'action',
                                    a.display_name, True, a.sdk_type) for a in native.actions))
        self._notify(frozenset(r for refs, _ in self._listeners for r in refs if r.plugin_id == native.plugin_id))

    def push(self, values):
        """All-or-nothing metadata update. Caller marshals callbacks to its UI thread."""
        values = tuple(values)
        for value in values:
            if not isinstance(value, DisplayData) or value.kind not in ('folder', 'action') or not isinstance(value.name, str) or type(value.available) is not bool:
                raise FolderError('Ungültige Provider-Darstellungsdaten.')
            if not isinstance(value.reference, Reference):
                raise FolderError('Providerreferenz erwartet namespaced Reference.')
            value.reference.__post_init__()
        self._data.update((value.reference, value) for value in values)
        self._notify(frozenset(value.reference for value in values))

    def offline(self, plugin_id):
        self.push(tuple(DisplayData(v.reference, v.kind, v.name, False, v.sdk_type)
                        for v in self._data.values() if v.reference.plugin_id == plugin_id))

    def resolve(self, reference, kind=None):
        value = self._data.get(reference)
        if value is None or (kind is not None and value.kind != kind):
            return DisplayData(reference, kind or 'action', reference.key, False)
        return value

    def snapshot(self):
        return tuple(self._data.values())

    def actions(self):
        return tuple(v for v in self._data.values() if v.kind == 'action')

    def subscribe(self, references, changed):
        listener = (frozenset(references), changed)
        self._listeners.append(listener)
        changed(tuple(self.resolve(r) for r in listener[0]))
        def release():
            if listener in self._listeners:
                self._listeners.remove(listener)
        return release

    def _notify(self, references):
        for wanted, callback in tuple(self._listeners):
            if wanted & references:
                callback(tuple(self.resolve(r) for r in wanted))
