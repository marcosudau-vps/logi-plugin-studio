from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from core.ids import is_valid_id
from core.io import dump_project, load_project, project_from_dict, project_to_dict
from core.model import Project
from core.registry import load_manifests
from core.validate import validate_project
from runtime.wire import HostError, json_bytes, parse_json

ROOT = Path(__file__).resolve().parents[2]
COLLECTIONS = ("components", "states", "bindings", "views", "presentations", "assets")
OWNER_KINDS = {"components": "component", "states": "state", "presentations": "presentation"}


class DocumentError(ValueError):
    pass


def empty_project(project_id: str = "my.plugin", name: str = "Mein Plugin") -> dict:
    if not is_valid_id(project_id):
        raise DocumentError("Invalid project ID")
    return {"schema_version": "0.1-draft", "project": {"id": project_id, "display_name": name},
            "dependencies": [], **{key: [] for key in COLLECTIONS}}


def schema_default(schema: dict) -> Any:
    if "enum" in schema and schema["enum"]:
        return copy.deepcopy(schema["enum"][0])
    kind = schema.get("type")
    if kind == "object":
        return {key: schema_default(schema.get("properties", {}).get(key, {}))
                for key in schema.get("required", [])}
    return {"string": "", "integer": 0, "number": 0.0, "boolean": False,
            "array": [], "null": None}.get(kind)


class ProjectDocument:
    """Transactional authoring around core.Project, not a parallel project format."""

    def __init__(self, raw: dict | None = None) -> None:
        self._project: Project = project_from_dict(raw if raw is not None else empty_project())
        self.path: Path | None = None
        self._saved = self.text
        self._disk_bytes: bytes | None = None
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self.registry, self.registry_issues = load_manifests(ROOT / "component_types")

    @property
    def model(self) -> Project:
        return self._project

    @property
    def raw(self) -> dict:
        return project_to_dict(self._project)

    @property
    def text(self) -> str:
        return dump_project(self._project)

    @property
    def dirty(self) -> bool:
        return self.text != self._saved

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def load(self, path: str | Path) -> None:
        file = Path(path).resolve()
        try:
            content = file.read_bytes()
            raw = parse_json(content, limit=16_777_216)
            project = project_from_dict(raw)
        except (OSError, HostError, ValueError) as exc:
            raise DocumentError(str(exc)) from exc
        self._project = project
        self.path = file
        self._saved = self.text
        self._disk_bytes = content
        self._undo.clear()
        self._redo.clear()

    def save(self, path: str | Path | None = None, *, replace_existing: bool = False) -> None:
        target = Path(path).resolve() if path is not None else self.path
        if target is None:
            raise DocumentError("Choose a project file first")
        if target.exists():
            existing = target.read_bytes()
            if self.path == target and self._disk_bytes is not None and existing != self._disk_bytes:
                raise DocumentError("Project changed on disk; save under a new name or reload before overwriting")
            if self.path != target and not replace_existing:
                raise DocumentError("Target already exists; explicit overwrite confirmation required")
        try:
            json_bytes(self.raw, limit=16_777_216)
            data = self.text.encode("utf-8")
        except (HostError, UnicodeError) as exc:
            raise DocumentError(str(exc)) from exc
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".studio-save-", delete=False) as handle:
                temporary = handle.name
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if target.exists() and self.path == target and self._disk_bytes is not None:
                if target.read_bytes() != self._disk_bytes:
                    raise DocumentError("Concurrent disk edit detected; nothing overwritten")
            os.replace(temporary, target)
            temporary = None
        except OSError as exc:
            raise DocumentError(f"Could not save project: {exc}") from exc
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)
        self.path = target
        self._saved = self.text
        self._disk_bytes = data

    def mutate(self, operation: Callable[[dict], None]) -> None:
        before = self.raw
        after = copy.deepcopy(before)
        operation(after)
        updated = project_from_dict(after)
        if dump_project(updated) == self.text:
            return
        self._undo.append(before)
        self._undo = self._undo[-50:]
        self._redo.clear()
        self._project = updated

    def replace_raw(self, raw: dict) -> None:
        def operation(current):
            current.clear()
            current.update(copy.deepcopy(raw))
        self.mutate(operation)

    def undo(self) -> None:
        if self._undo:
            self._redo.append(self.raw)
            self._project = project_from_dict(self._undo.pop())

    def redo(self) -> None:
        if self._redo:
            self._undo.append(self.raw)
            self._project = project_from_dict(self._redo.pop())

    def diagnostics(self) -> list:
        return sorted([*self.registry_issues, *validate_project(self.raw, self.registry)],
                      key=lambda d: d.sort_key())

    def next_id(self, collection: str, stem: str) -> str:
        raw = self.raw
        if any(not isinstance(raw.get(key), list) for key in COLLECTIONS):
            raise DocumentError("Malformed collection; repair explicitly in the project JSON editor")
        if collection == "placements":
            used = {p.get("id") for v in raw.get("views", []) if isinstance(v, dict)
                    for p in (v.get("placements") if isinstance(v.get("placements"), list) else [])
                    if isinstance(p, dict) and isinstance(p.get("id"), str)}
        else:
            used = {r.get("id") for r in raw.get(collection, []) if isinstance(r, dict) and isinstance(r.get("id"), str)}
        if stem not in used:
            return stem
        index = 2
        while f"{stem}.{index}" in used:
            index += 1
        return f"{stem}.{index}"

    def add(self, collection: str, entity: dict) -> None:
        if collection not in COLLECTIONS:
            raise DocumentError("Unknown collection")
        if not is_valid_id(entity.get("id")):
            raise DocumentError("Invalid stable ID")
        def operation(raw):
            rows = raw[collection]
            if not isinstance(rows, list):
                raise DocumentError("Collection is malformed; repair explicitly in the JSON editor")
            if any(isinstance(r, dict) and r.get("id") == entity["id"] for r in rows):
                raise DocumentError("Stable ID already exists in this collection")
            rows.append(copy.deepcopy(entity))
            if collection == "components":
                if not isinstance(raw.get("dependencies"), list):
                    raise DocumentError("Dependencies are malformed; repair explicitly in project JSON")
                if not isinstance(entity.get("type"), str) or not isinstance(entity.get("version"), str):
                    raise DocumentError("Component type and version must be strings")
                dependency = {"type": entity["type"], "version": entity["version"]}
                if dependency not in raw["dependencies"]:
                    raw["dependencies"].append(dependency)
        self.mutate(operation)

    @staticmethod
    def _rename_references(raw: dict, collection: str, old: str, new: str) -> None:
        if any(not isinstance(raw.get(key), list) for key in COLLECTIONS):
            raise DocumentError("Repair malformed collections in project JSON before editing references")
        if any(isinstance(view, dict) and not isinstance(view.get("placements"), list) for view in raw["views"]):
            raise DocumentError("Repair malformed placements before editing references")
        kind = OWNER_KINDS.get(collection)
        for binding in raw.get("bindings", []):
            if not isinstance(binding, dict):
                continue
            for side in ("source", "target"):
                ref = binding.get(side)
                if isinstance(ref, dict) and kind and ref.get("owner_kind") == kind and ref.get("owner_id") == old:
                    ref["owner_id"] = new
        for view in raw.get("views", []):
            if not isinstance(view, dict):
                continue
            for placement in view.get("placements", []) if isinstance(view.get("placements"), list) else []:
                if not isinstance(placement, dict):
                    continue
                field = {"components": "component", "presentations": "presentation"}.get(collection)
                if field and placement.get(field) == old:
                    placement[field] = new
        if collection == "components":
            for state in raw.get("states", []):
                if isinstance(state, dict) and isinstance(state.get("authority"), dict) and state["authority"].get("component") == old:
                    state["authority"]["component"] = new
        if collection == "assets":
            for presentation in raw.get("presentations", []):
                if isinstance(presentation, dict) and isinstance(presentation.get("variants"), dict):
                    for variant in presentation["variants"].values():
                        if isinstance(variant, dict) and variant.get("image") == old:
                            variant["image"] = new

    def replace_entity(self, collection: str, old_id: str, entity: dict) -> None:
        new_id = entity.get("id")
        if not is_valid_id(new_id):
            raise DocumentError("Invalid stable ID; use lowercase letters, digits and . _ - separators")
        def operation(raw):
            rows = raw[collection]
            if not isinstance(rows, list):
                raise DocumentError("Collection is malformed; repair explicitly in project JSON")
            if old_id != new_id and any(isinstance(r, dict) and r.get("id") == new_id for r in rows):
                raise DocumentError("Stable ID already exists")
            index = next((i for i, r in enumerate(rows) if isinstance(r, dict) and r.get("id") == old_id), None)
            if index is None:
                raise DocumentError("Object no longer exists")
            rows[index] = copy.deepcopy(entity)
            if old_id != new_id:
                self._rename_references(raw, collection, old_id, new_id)
            if collection == "components":
                if not isinstance(raw.get("dependencies"), list):
                    raise DocumentError("Dependencies are malformed; repair explicitly in project JSON")
                if not isinstance(entity.get("type"), str) or not isinstance(entity.get("version"), str):
                    raise DocumentError("Component type and version must be strings")
                dependency = {"type": entity["type"], "version": entity["version"]}
                if dependency not in raw["dependencies"]:
                    raw["dependencies"].append(dependency)
        self.mutate(operation)

    def references(self, collection: str, entity_id: str) -> list[str]:
        raw = self.raw
        candidate = copy.deepcopy(raw)
        self._rename_references(candidate, collection, entity_id, "__reference_probe__")
        paths = []
        for section in ("bindings", "views", "states", "presentations"):
            if candidate.get(section) != raw.get(section):
                paths.append(section)
        return paths

    def remove(self, collection: str, entity_id: str) -> None:
        references = self.references(collection, entity_id)
        if references:
            raise DocumentError("Object is referenced by " + ", ".join(references) + "; remove or reroute these references first")
        self.mutate(lambda raw: raw.__setitem__(collection, [
            r for r in raw[collection] if not (isinstance(r, dict) and r.get("id") == entity_id)]))

    def duplicate(self, collection: str, entity_id: str) -> str:
        if collection not in COLLECTIONS or any(d.severity == "ERROR" for d in self.diagnostics()):
            raise DocumentError("Repair invalid model data explicitly before duplicating objects")
        entity = next((r for r in self.raw[collection] if isinstance(r, dict) and r.get("id") == entity_id), None)
        if entity is None:
            raise DocumentError("Object no longer exists")
        entity["id"] = self.next_id(collection, entity_id + ".copy")
        if collection == "views":
            used = {p["id"] for v in self.raw["views"] for p in v["placements"]}
            for placement in entity["placements"]:
                stem = placement["id"] + ".copy"
                candidate = stem
                index = 2
                while candidate in used:
                    candidate = f"{stem}.{index}"
                    index += 1
                placement["id"] = candidate
                used.add(candidate)
        self.add(collection, entity)
        return entity["id"]

    def component_types(self) -> list:
        types = []
        for path in sorted((ROOT / "component_types").glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("test_only"):
                continue
            item = self.registry.resolve(raw.get("type_id"), raw.get("version"))
            if item is not None:
                types.append(item)
        return types
