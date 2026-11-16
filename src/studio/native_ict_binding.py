"""NF-16: thin, SDK-native binding between an action/Keypad slot and ICT files.

No new action/state model or persisted widget document. The SDK-native project
owns the action-to-template reference; SymbolDesigner owns ICT semantics.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from adapters.logitech.native import NativeProject, parse_native_project
from studio.keypad_contract import KeypadViewState
from symbol_designer.ict import IconTemplate, IctError


class NativeIctBindingError(ValueError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_ict(path: Path, limit: int) -> bytes:
    if not path.is_file():
        raise NativeIctBindingError("Referenzierte ICT-Datei fehlt oder ist keine Datei: " + str(path))
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise NativeIctBindingError(f"ICT-Datei überschreitet {limit} Bytes: {path}")
    return data


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@dataclass(frozen=True)
class NativeIctBinding:
    action_id: str
    action_parameter: str | None
    source: Path | None
    target: Path
    relative_target: str
    forked: bool
    project_sha256: str
    source_sha256: str | None
    template: IconTemplate
    relative_source: str | None = None

    @property
    def needs_project_update(self) -> bool:
        return self.forked


class NativeIctCoordinator:
    """Standalone NF-16 entrypoint. The native shell supplies a session-bound subclass."""

    asset_limit = 16 * 1024 * 1024

    def __init__(self, project_path: str | Path):
        self.project_path = Path(project_path).resolve(strict=True)
        if not self.project_path.is_file():
            raise NativeIctBindingError("Native Projektdatei fehlt")
        self.project_root = self.project_path.parent
        self._read()

    def _read(self) -> None:
        data = self.project_path.read_bytes()
        try:
            raw = json.loads(data.decode("utf-8-sig"))
            model = parse_native_project(raw)
        except (ValueError, UnicodeError, TypeError) as exc:
            raise NativeIctBindingError("Ungültiges SDK-natives Projekt: " + str(exc)) from exc
        self.raw: dict = raw
        self.project: NativeProject = model
        self.project_sha256 = _sha(data)

    def _safe(self, relative: str) -> Path:
        path = (self.project_root / relative).resolve()
        if not path.is_relative_to(self.project_root):
            raise NativeIctBindingError("ICT-Pfad verlässt das Projektverzeichnis")
        if path.suffix.lower() != ".ict":
            raise NativeIctBindingError("Nur native .ict-Vorlagen können bearbeitet werden")
        return path

    def open_action(self, action_id: str, *, action_parameter: str | None = None) -> NativeIctBinding:
        action = next((a for a in self.project.actions if a.id == action_id), None)
        if action is None:
            raise NativeIctBindingError("Unbekannte SDK-Aktion: " + action_id)
        if action_parameter is not None and action_parameter not in {p.name for p in action.parameters}:
            raise NativeIctBindingError("SDK-actionParameter ist in der Aktion nicht deklariert")
        direct = action.icon_template
        inherited = self.project.default_icon_template
        relative = direct or inherited
        source = self._safe(relative) if relative else None
        source_bytes: bytes | None = None
        if source is not None:
            source_bytes = _read_ict(source, self.asset_limit)
            template = self.decode_template(source_bytes)
        else:
            template = IconTemplate()
            template.text = action.display_name
        forked = not direct or self._is_shared(self.project, action_id, source) or self._force_fork(action_id, source)
        target_relative = f"icontemplates/{action.id}.ict" if forked else direct
        target = self._safe(target_relative)
        if forked and target == source:
            target_relative = f"icontemplates/{action.id}__own.ict"
            target = self._safe(target_relative)
        if forked and (target.exists() or target.is_symlink()):
            target_relative = self._alternate_target(action.id, target)
            target = self._safe(target_relative)
        return NativeIctBinding(
            action_id, action_parameter, source, target, target_relative,
            forked, self.project_sha256, _sha(source_bytes) if source_bytes is not None else None,
            template, relative,
        )

    def _is_shared(self, project, action_id, source):
        refs = [project.default_icon_template, *(
            other.icon_template for other in project.actions if other.id != action_id)]
        return any(relative and self._safe(relative) == source for relative in refs)

    def _force_fork(self, action_id, source):
        return False

    def _alternate_target(self, action_id, target):
        raise NativeIctBindingError("Neuer aktionsspezifischer ICT-Pfad ist bereits belegt: " + str(target))

    def decode_template(self, data):
        try:
            return IconTemplate.from_bytes(data)
        except (IctError, RecursionError) as exc:
            raise NativeIctBindingError(str(exc)) from exc

    def from_slot(self, state: KeypadViewState, physical_index: int) -> NativeIctBinding:
        """Existing preview DTO selects an action; editing needs explicit mode."""
        if not state.editing_enabled:
            raise NativeIctBindingError("Keypad ist im Vorschaumodus; Bearbeiten muss explizit aktiviert werden")
        slot = next((s for s in state.frame.slots if s.physical_index == physical_index), None)
        if slot is None or slot.role != "placement" or not slot.editable:
            raise NativeIctBindingError("Dieser Slot ist keine bearbeitbare SDK-Aktionsplatzierung")
        return self.open_action(slot.action_id, action_parameter=slot.action_parameter)

    def check_assets(self, binding: NativeIctBinding) -> None:
        if (self._safe(binding.relative_target) != binding.target
                or (binding.relative_source and self._safe(binding.relative_source) != binding.source)):
            raise NativeIctBindingError("ICT-Pfad wurde extern geändert; nicht überschrieben")
        if binding.source is not None and (
            not binding.source.is_file() or _sha(_read_ict(binding.source, self.asset_limit)) != binding.source_sha256
        ):
            raise NativeIctBindingError("ICT-Quelle wurde extern verändert; nicht überschrieben")
        if binding.forked and binding.target != binding.source and binding.target.exists():
            raise NativeIctBindingError("Ziel-ICT wurde mittlerweile angelegt; nicht überschrieben")
        if not binding.forked and not binding.target.is_file():
            raise NativeIctBindingError("ICT-Ziel wurde extern entfernt")

    def encode_template(self, template: IconTemplate) -> bytes:
        try:
            new_bytes = template.to_bytes()
            self.decode_template(new_bytes)
        except (IctError, TypeError, ValueError) as exc:
            raise NativeIctBindingError("ICT-Format ungültig: " + str(exc)) from exc
        if len(new_bytes) > self.asset_limit:
            raise NativeIctBindingError(f"ICT überschreitet {self.asset_limit} Bytes")
        return new_bytes

    def save(self, binding: NativeIctBinding, template: IconTemplate) -> Path:
        """Optimistic conflict check + atomic writes; roll back on project-write error."""
        if _sha(self.project_path.read_bytes()) != binding.project_sha256:
            raise NativeIctBindingError("Projekt wurde extern verändert; bitte erneut öffnen")
        self.check_assets(binding)
        new_bytes = self.encode_template(template)
        raw = copy.deepcopy(self.raw)
        new_project_bytes = None
        if binding.forked:
            record = next((a for a in raw["actions"] if a["id"] == binding.action_id), None)
            if record is None:
                raise NativeIctBindingError("Aktion existiert nicht mehr im Projekt")
            record["icon_template"] = binding.relative_target.replace("\\", "/")
            try:
                parse_native_project(raw)
            except ValueError as exc:
                raise NativeIctBindingError("Projektverknüpfung ungültig: " + str(exc)) from exc
            # Save only when a new action-specific link is needed. Preserve all other fields.
            project_original = self.project_path.read_bytes()
            newline = "\r\n" if b"\r\n" in project_original else "\n"
            ending = newline if project_original.endswith((b"\n", b"\r")) else ""
            text = json.dumps(raw, ensure_ascii=False, indent=2) + ending
            new_project_bytes = text.replace("\n", newline).encode("utf-8")
        old_target = binding.target.read_bytes() if binding.target.exists() else None
        try:
            _atomic_write(binding.target, new_bytes)
            if new_project_bytes is not None:
                _atomic_write(self.project_path, new_project_bytes)
        except Exception:
            if old_target is not None:
                _atomic_write(binding.target, old_target)
            elif binding.target.exists():
                binding.target.unlink()
            raise
        self._read()
        return binding.target
