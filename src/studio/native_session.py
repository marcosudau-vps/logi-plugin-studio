"""Qt-free transaction owner for existing ``logitech-native-1`` JSON documents.

The raw JSON tree is authoritative; NativeProject is only a read projection.
Callers must serialize access to a session (one host / one document writer).
Disk checks are optimistic, not an OS-level compare-and-swap or an asset transaction.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from adapters.logitech.native import NativeProject, NativeProjectError, parse_native_project

MAX_PROJECT_BYTES = 16 * 1024 * 1024
HISTORY_LIMIT = 50


class NativeSessionError(ValueError):
    """A document could not be read, validated or saved."""


class NativeRevisionConflict(NativeSessionError):
    """The proposed snapshot is based on a different session revision."""


class NativeDiskConflict(NativeSessionError):
    """The originally opened file changed or is no longer readable."""


def _read_limited(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(MAX_PROJECT_BYTES + 1)
    if len(data) > MAX_PROJECT_BYTES:
        raise NativeSessionError("Projektdatei überschreitet 16 MiB")
    return data


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise NativeSessionError(f"Doppelter JSON-Schlüssel: {key!r}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise NativeSessionError(f"Kein gültiger JSON-Zahlenwert: {value}")


def _prepare(raw: dict) -> tuple[dict, NativeProject, bytes]:
    """Validate native semantics only through the existing normative parser.

    JSON encoding additionally enforces the technical UTF-8/finite-number/size
    boundary. Canonical bytes compare content independently of dictionary order,
    while retaining distinctions such as false versus 0 that Python == loses.
    """
    try:
        candidate = copy.deepcopy(raw)
        if isinstance(candidate, dict) and candidate.get("schema_version") == "0.1-draft":
            raise NativeSessionError(
                "0.1-draft gehört in den alten Kompatibilitätseditor; keine implizite Migration")
        project = parse_native_project(candidate)
        content = (json.dumps(candidate, ensure_ascii=False, allow_nan=False,
                              sort_keys=True, indent=2) + "\n").encode("utf-8")
        if len(content) > MAX_PROJECT_BYTES:
            raise NativeSessionError("Projektinhalt überschreitet 16 MiB als gespeichertes UTF-8-JSON")
        return candidate, project, content
    except NativeSessionError:
        raise
    except (NativeProjectError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise NativeSessionError("Ungültiges natives Projekt: " + str(exc)) from exc


class NativeProjectSession:
    """Validated full-snapshot commits with bounded history and protected save.

    from_raw starts clean against its initial in-memory snapshot, with no path.
    Only load attaches a save target. No method implicitly saves or discards edits.
    Revisions are opaque, transient tokens; save does not change the revision.
    """

    def __init__(self, raw: dict) -> None:
        self._raw, self._project, self._content = _prepare(raw)
        self._saved_content = self._content
        self._path: Path | None = None
        self._disk_bytes: bytes | None = None
        self._disk_sha256: str | None = None
        self._revision = uuid4().hex
        self._undo: list[dict] = []
        self._redo: list[dict] = []

    @classmethod
    def from_raw(cls, raw: dict) -> NativeProjectSession:
        return cls(raw)

    @classmethod
    def load(cls, path: str | Path) -> NativeProjectSession:
        try:
            target = Path(path).resolve()
            data = _read_limited(target)
            raw = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                             parse_constant=_invalid_constant)
            session = cls.from_raw(raw)
        except NativeSessionError:
            raise
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            raise NativeSessionError(f"Projekt konnte nicht geladen werden: {exc}") from exc
        session._path = target
        session._disk_bytes = data
        session._disk_sha256 = hashlib.sha256(data).hexdigest()
        return session

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def revision(self) -> str:
        return self._revision

    @property
    def dirty(self) -> bool:
        return self._content != self._saved_content

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def snapshot(self) -> dict:
        return copy.deepcopy(self._raw)

    def native_project(self) -> NativeProject:
        # Frozen dataclasses still contain mutable handler/navigation/symbol dicts.
        return copy.deepcopy(self._project)

    def replace(self, proposed: dict, *, base_revision: str) -> str:
        if base_revision != self._revision:
            raise NativeRevisionConflict("Veraltete oder fremde base_revision; aktuellen Snapshot neu beziehen")
        raw, project, content = _prepare(proposed)
        if content == self._content:
            return self._revision
        self._undo.append(self._raw)
        del self._undo[:-HISTORY_LIMIT]
        self._redo.clear()
        self._raw, self._project, self._content = raw, project, content
        self._revision = uuid4().hex
        return self._revision

    def _restore(self, source: list[dict], destination: list[dict]) -> bool:
        if not source:
            return False
        raw, project, content = _prepare(source[-1])
        destination.append(self._raw)
        del destination[:-HISTORY_LIMIT]
        source.pop()
        self._raw, self._project, self._content = raw, project, content
        self._revision = uuid4().hex
        return True

    def undo(self) -> bool:
        return self._restore(self._undo, self._redo)

    def redo(self) -> bool:
        return self._restore(self._redo, self._undo)

    def _check_disk(self) -> None:
        try:
            data = _read_limited(self._path)
        except (OSError, NativeSessionError) as exc:
            raise NativeDiskConflict(f"Projektdatei nicht mehr sicher lesbar; nichts überschrieben: {exc}") from exc
        if hashlib.sha256(data).hexdigest() != self._disk_sha256 or data != self._disk_bytes:
            raise NativeDiskConflict("Projektdatei extern verändert; nichts überschrieben. Änderungen explizit abgleichen")

    def save(self) -> None:
        """Save only the original project file, never copying or repairing assets.

        Checks both before staging and immediately before atomic replacement.
        Uncoordinated writers can still race in the final check/replace gap;
        the future host must coordinate every writer through one session.
        """
        if self._path is None:
            raise NativeSessionError("Kein ursprünglich geöffneter Pfad; save_new/Save-As ist nicht implementiert")
        self._check_disk()
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self._path.parent, prefix=".native-session-",
                                             suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(self._content)
                stream.flush()
                os.fsync(stream.fileno())
            self._check_disk()
            os.replace(temporary, self._path)
            temporary = None
        except OSError as exc:
            raise NativeSessionError(f"Projekt konnte nicht gespeichert werden: {exc}") from exc
        finally:
            if temporary is not None:
                active_error = sys.exception()
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as exc:
                    message = f"Temporäre Datei konnte nicht entfernt werden: {temporary}: {exc}"
                    if active_error is None:
                        raise NativeSessionError(message) from exc
                    active_error.add_note(message)
        self._saved_content = self._content
        self._disk_bytes = self._content
        self._disk_sha256 = hashlib.sha256(self._content).hexdigest()


__all__ = ["NativeProjectSession", "NativeSessionError", "NativeRevisionConflict", "NativeDiskConflict"]
