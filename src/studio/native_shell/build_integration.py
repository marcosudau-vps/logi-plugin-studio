"""Preflight for an explicit SDK build from one native session and optional sidecar.

The native JSON and virtual-folders extension remain separately owned. A build
uses frozen, saved snapshots; it never writes either source or a Logitech profile.
"""
from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from pathlib import Path
from copy import deepcopy

from extensions.shared_folders.runtime_projection import project_virtual_folders
from studio.native_session import NativeSessionError
from studio.virtual_folders.binding import extension_path, project_identity
from studio.virtual_folders.model import FolderError


class NativeBuildPreflightError(ValueError):
    pass


#: User-facing plugin types. The key is the generator's ``folder_mode``.
FOLDER_MODES = {
    "compatible": ("Kompatibel (Standard)",
                   "Bisheriges Verhalten bestehender Projekte: SDK-Actions plus optionaler "
                   "virtueller Folderaufsatz aus der gespeicherten .vfolders.json. Keine Peer-Runtime."),
    "native": ("Nativ – reines SDK-Plugin",
               "Nur originale Logitech-SDK-Actions und statische SDK-DynamicFolder aus dem "
               "nativen Projekt; normale Python-Bridge. Keine Folder-/Peer-Runtime, virtuelle "
               "Ordner werden nicht ausgeliefert."),
    "shared": ("Shared DynamicFolder",
               "SDK-Actions plus vollständig eingebettete Folder- und Peer-Runtime. Fremde "
               "Referenzen aus den virtuellen Ordnern werden zur Laufzeit beim Owner-Plugin "
               "ausgeführt, sofern dort freigegeben (Pairing/Berechtigungen)."),
}
HANDLER_LIMIT = 262_144


def validate_handler(project_path: Path, relative: str | None) -> str | None:
    """Static check of an optional trusted, project-relative handler file.

    The file is never imported by Studio; it must define ``register(host)``.
    """
    if relative in (None, ""):
        return None
    if ":" in relative or "\\" in relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise NativeBuildPreflightError("Handler-Datei muss ein projektrelativer Pfad ohne '..' sein.")
    base = Path(project_path).resolve().parent
    file = (base / relative).resolve()
    if not file.is_relative_to(base) or file.suffix != ".py" or not file.is_file():
        raise NativeBuildPreflightError("Handler-Datei (.py) im Projektordner nicht gefunden.")
    if file.stat().st_size > HANDLER_LIMIT:
        raise NativeBuildPreflightError("Handler-Datei ist größer als 256 KiB.")
    try:
        tree = ast.parse(file.read_text(encoding="utf-8"), filename=relative)
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise NativeBuildPreflightError(f"Handler-Datei ist kein gültiges Python: {exc}") from exc
    if not any(isinstance(n, ast.FunctionDef) and n.name == "register" and len(n.args.args) == 1
               for n in tree.body):
        raise NativeBuildPreflightError("Handler-Datei muss eine Funktion register(host) definieren.")
    return relative


@dataclass(frozen=True)
class NativeBuildInputs:
    project_path: Path
    raw_project: dict
    folder_runtime: dict | None
    native_revision: str
    extension_revision: str | None
    folder_mode: str = "compatible"
    shared_references: list | None = None
    shared_handler: str | None = None
    warnings: tuple = field(default_factory=tuple)


def needs_entrypoints(folder_mode: str) -> bool:
    return folder_mode != "native"


def external_placements(store) -> list:
    if store is None or store.path is None:
        return []
    own = store.document.plugin_id
    return [p for p in store.document.placements if p.target.plugin_id != own]


def prepare_native_build(session, store, *, entrypoints=None, folder_mode="compatible",
                         shared_handler=None) -> NativeBuildInputs:
    """Validate saved inputs, including disk conflicts, and freeze build payloads.

    No sidecar means the generator uses its native SDK-folder definitions.
    With a sidecar, all real SDK-folder entrypoints must be supplied explicitly.
    """
    if session is None or session.path is None or store is None:
        raise NativeBuildPreflightError("Zuerst ein natives Projekt öffnen.")
    if session.dirty:
        raise NativeBuildPreflightError("Natives Projekt vor dem Build separat speichern.")
    if store.dirty:
        raise NativeBuildPreflightError("Virtuelle Ordner vor dem Build separat speichern.")
    path = Path(session.path).resolve()
    expected = extension_path(path).resolve()
    if store.path is None and expected.exists():
        raise NativeBuildPreflightError(
            "Eine neue externe Extension liegt auf dem Datenträger. Projekt zuerst neu laden.")
    if store.path is not None and Path(store.path).resolve() != expected:
        raise NativeBuildPreflightError("Extension gehört nicht zum kanonischen Projekt-Sidecar.")
    if store.document.project_id != project_identity(path):
        raise NativeBuildPreflightError("Extension-Projektidentität stimmt nicht überein.")
    if folder_mode not in FOLDER_MODES:
        raise NativeBuildPreflightError("Unbekannte Plugin-Betriebsart.")
    handler = validate_handler(path, shared_handler)
    warnings = []
    externals = external_placements(store)
    if folder_mode == "native":
        if store.path is not None and store.document.placements:
            warnings.append("Nativ: Die gespeicherten virtuellen Ordner werden NICHT ausgeliefert; "
                            "nur die SDK-Folder des nativen Projekts.")
        entrypoints = None if entrypoints in (None, {}) else entrypoints
        if entrypoints:
            raise NativeBuildPreflightError("Im Modus Nativ werden keine virtuellen Einstiegspunkte verwendet.")
    elif folder_mode == "compatible" and externals:
        warnings.append(f"{len(externals)} externe Referenz(en) bleiben im Modus Kompatibel offline; "
                        "für fremde Actions den Modus Shared DynamicFolder wählen.")
    references = None
    try:
        session._check_disk()
        if store.path is not None:
            store._check_disk()
        raw = session.snapshot()
        store.document.validate_native(raw, require_available=False)
        if store.path is None or folder_mode == "native":
            if entrypoints not in (None, {}):
                raise NativeBuildPreflightError("Ohne Extension keine virtuellen Einstiegspunkte übergeben.")
            layout = None
            references = [] if folder_mode == "shared" else None
        else:
            ids = {folder["id"] for folder in raw["folders"]}
            if not ids and store.document.placements:
                raise NativeBuildPreflightError(
                    "Virtuelle Platzierungen benötigen mindestens einen nativen SDK-DynamicFolder.")
            if entrypoints is None or set(entrypoints) != ids:
                raise NativeBuildPreflightError(
                    "Für jede native SDK-Folderdefinition muss ein Einstiegsknoten gewählt werden.")
            if folder_mode == "shared":
                from extensions.shared_folders.peer_projection import project_shared_folders
                from extensions.shared_folders.peer_wire import PeerError
                try:
                    layout, references = project_shared_folders(
                        raw, asdict(store.document), entrypoints=entrypoints, revision=0)
                except PeerError as exc:
                    raise NativeBuildPreflightError(f"Shared-Referenzen ungültig: {exc}") from exc
            else:
                layout = project_virtual_folders(
                    raw, asdict(store.document), entrypoints=entrypoints, revision=0)
        # Prevent starting from already stale source bytes; worker receives frozen data.
        session._check_disk()
        if store.path is not None:
            store._check_disk()
    except (NativeSessionError, FolderError, OSError, ValueError) as exc:
        raise NativeBuildPreflightError(str(exc)) from exc
    return NativeBuildInputs(path, deepcopy(raw), deepcopy(layout),
                             session.revision, store.revision if store.path is not None else None,
                             folder_mode, deepcopy(references), handler, tuple(warnings))
