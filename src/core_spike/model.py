"""Non-production P0 model/validator SPIKE. Not an approved public API."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_COLLECTIONS = ("components", "states", "bindings", "presentations", "assets", "views")
_KINDS = {"command", "event", "state"}
_SUPPORTED_SIMPLE_KEYWORDS = {"type", "enum", "properties", "required", "additionalProperties", "items", "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems", "const"}


@dataclass(frozen=True)
class Issue:
    code: str
    path: str
    message: str
    severity: str = "ERROR"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def load_project(path: str | Path) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    model = json.loads(text)
    if not isinstance(model, dict):
        raise ValueError("The project root must be an object")
    return model


def dump_project(project: dict) -> str:
    return json.dumps(project, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _schema_check(value: Any, schema: dict[str, Any], path: str, problems: list[Issue]) -> None:
    """Deliberately restricted JSON Schema subset. Unknown rules fail closed."""
    if not isinstance(schema, dict):
        problems.append(Issue("SCHEMA_INVALID", path, "Schema must be an object"))
        return
    unknown = set(schema) - _SUPPORTED_SIMPLE_KEYWORDS
    if unknown:
        problems.append(Issue("SCHEMA_UNSUPPORTED", path, f"Unsupported schema keywords: {sorted(unknown)}"))
        return
    kind = schema.get("type")
    type_test = {
        "string": lambda v: isinstance(v, str),
        "boolean": lambda v: isinstance(v, bool),
        "integer": lambda v: type(v) is int,
        "number": lambda v: type(v) in (int, float),
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "null": lambda v: v is None,
    }
    if kind is not None and (kind not in type_test or not type_test[kind](value)):
        problems.append(Issue("VALUE_TYPE", path, f"Expected {kind}"))
        return
    if "const" in schema and value != schema["const"]:
        problems.append(Issue("VALUE_CONST", path, "Value differs from const"))
    if "enum" in schema and value not in schema["enum"]:
        problems.append(Issue("VALUE_ENUM", path, "Value not present in enum"))
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            problems.append(Issue("VALUE_LENGTH", path, "String below minLength"))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            problems.append(Issue("VALUE_LENGTH", path, "String exceeds maxLength"))
    if type(value) in (int, float):
        if "minimum" in schema and value < schema["minimum"]:
            problems.append(Issue("VALUE_RANGE", path, "Value below minimum"))
        if "maximum" in schema and value > schema["maximum"]:
            problems.append(Issue("VALUE_RANGE", path, "Value above maximum"))
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            problems.append(Issue("VALUE_LENGTH", path, "Array below minItems"))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            problems.append(Issue("VALUE_LENGTH", path, "Array exceeds maxItems"))
        if "items" in schema:
            for idx, item in enumerate(value):
                _schema_check(item, schema["items"], f"{path}/{idx}", problems)
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            if required not in value:
                problems.append(Issue("VALUE_REQUIRED", path, f"Missing {required}"))
        for key, v in value.items():
            if key in properties:
                _schema_check(v, properties[key], f"{path}/{key}", problems)
            elif schema.get("additionalProperties") is False:
                problems.append(Issue("VALUE_UNKNOWN", f"{path}/{key}", "Unexpected property"))
            elif isinstance(schema.get("additionalProperties"), dict):
                _schema_check(v, schema["additionalProperties"], f"{path}/{key}", problems)


def _add(issues: list[Issue], code: str, path: str, message: str) -> None:
    issues.append(Issue(code, path, message))


def validate_project(project: dict, manifests: dict[str, dict]) -> list[Issue]:
    """Structural plus semantic validation for the *small* draft model. It is not full JSON Schema."""
    issues: list[Issue] = []
    if not isinstance(project, dict):
        return [Issue("PROJECT_SHAPE", "/", "Root must be an object")]
    required = {"schema_version", "project", "dependencies", *_COLLECTIONS}
    for missing in sorted(required - set(project)):
        _add(issues, "FIELD_REQUIRED", "/", f"Missing {missing}")
    for unexpected in sorted(set(project) - required):
        _add(issues, "FIELD_UNKNOWN", f"/{unexpected}", "Unknown project field")
    if project.get("schema_version") != "0.1-draft":
        _add(issues, "VERSION_UNSUPPORTED", "/schema_version", "Expected 0.1-draft")
    identities: dict[str, dict[str, dict]] = {}
    for collection in _COLLECTIONS:
        objects = project.get(collection, [])
        if not isinstance(objects, list):
            _add(issues, "COLLECTION_SHAPE", f"/{collection}", "Expected array")
            objects = []
        seen = {}
        for idx, obj in enumerate(objects):
            p = f"/{collection}/{idx}"
            if not isinstance(obj, dict):
                _add(issues, "OBJECT_SHAPE", p, "Expected object")
                continue
            ident = obj.get("id")
            if not isinstance(ident, str) or not _ID_RE.fullmatch(ident):
                _add(issues, "ID_INVALID", f"{p}/id", "Invalid identifier")
                continue
            if ident in seen:
                _add(issues, "ID_DUPLICATE", f"{p}/id", f"Duplicate {ident} in {collection}")
            seen[ident] = obj
        identities[collection] = seen
    for idx, comp in enumerate(project.get("components", [])):
        if not isinstance(comp, dict):
            continue
        p = f"/components/{idx}"
        mid = comp.get("type")
        manifest = manifests.get(mid)
        if not manifest:
            _add(issues, "TYPE_MISSING", f"{p}/type", f"Unknown component type {mid!r}")
            continue
        if comp.get("version") != manifest.get("version"):
            _add(issues, "TYPE_VERSION", f"{p}/version", "Component version not pinned to available manifest")
        config = comp.get("config", {})
        _schema_check(config, manifest.get("config_schema", {}), f"{p}/config", issues)
    for idx, state in enumerate(project.get("states", [])):
        if not isinstance(state, dict):
            continue
        p = f"/states/{idx}"
        schema = state.get("value_schema")
        if not isinstance(schema, dict):
            _add(issues, "SCHEMA_INVALID", f"{p}/value_schema", "Expected schema object")
        elif "fallback" in state:
            _schema_check(state["fallback"], schema, f"{p}/fallback", issues)
        if state.get("scope") not in {"project", "component", "placement", "session"}:
            _add(issues, "SCOPE_INVALID", f"{p}/scope", "Invalid scope")
        auth = state.get("authority", {})
        if not isinstance(auth, dict) or auth.get("role") not in {"host", "runtime", "component"}:
            _add(issues, "AUTHORITY_INVALID", f"{p}/authority", "Invalid authority")
        elif auth["role"] == "component" and auth.get("component") not in identities["components"]:
            _add(issues, "AUTHORITY_MISSING", f"{p}/authority/component", "Missing authority component")
    def endpoint(ref: Any, path: str) -> tuple[str, str, dict] | None:
        if not isinstance(ref, dict) or set(ref) != {"owner_kind", "owner_id", "port"}:
            _add(issues, "ENDPOINT_SHAPE", path, "Expected owner_kind, owner_id, port")
            return None
        owner_kind, owner_id, port = (ref[key] for key in ("owner_kind", "owner_id", "port"))
        sources = {"component": "components", "state": "states", "presentation": "presentations"}
        if owner_kind not in sources or owner_id not in identities[sources[owner_kind]]:
            _add(issues, "ENDPOINT_MISSING", path, f"Unknown endpoint owner {owner_kind}:{owner_id}")
            return None
        owner = identities[sources[owner_kind]][owner_id]
        if owner_kind == "component":
            manifest = manifests.get(owner.get("type"), {})
            matches = [p for p in manifest.get("ports", []) if p.get("id") == port]
            if not matches:
                _add(issues, "PORT_MISSING", path, f"Unknown port {port}")
                return None
            portobj = matches[0]
        elif owner_kind == "state":
            if port != "value":
                _add(issues, "PORT_MISSING", path, "State supports only value")
                return None
            portobj = {"direction": "out", "kind": "state", "payload_schema": owner.get("value_schema", {})}
        else:
            if port != "selector":
                _add(issues, "PORT_MISSING", path, "Presentation supports only selector")
                return None
            portobj = {"direction": "in", "kind": "state", "payload_schema": {"type": "string", "enum": sorted(owner.get("variants", {}))}}
        return owner_kind, str(owner_id), portobj
    for idx, bind in enumerate(project.get("bindings", [])):
        if not isinstance(bind, dict):
            continue
        p = f"/bindings/{idx}"
        src = endpoint(bind.get("source"), p + "/source")
        dst = endpoint(bind.get("target"), p + "/target")
        if src and dst:
            a, b = src[2], dst[2]
            if a["direction"] != "out" or b["direction"] != "in":
                _add(issues, "PORT_DIRECTION", p, "Binding requires out → in")
            if a["kind"] != b["kind"] or bind.get("kind") != a["kind"]:
                _add(issues, "SIGNAL_MISMATCH", p, "Binding signal categories differ")
            if _canonical(a.get("payload_schema", {})) != _canonical(b.get("payload_schema", {})):
                _add(issues, "SCHEMA_NOT_PROVEN", p, "Different payload schemas; no implicit conversion")
    all_placements: set[str] = set()
    for view_i, view in enumerate(project.get("views", [])):
        if not isinstance(view, dict):
            continue
        used_positions: set[int] = set()
        for idx, pl in enumerate(view.get("placements", [])):
            p = f"/views/{view_i}/placements/{idx}"
            ident = pl.get("id")
            if not isinstance(ident, str) or not _ID_RE.fullmatch(ident):
                _add(issues, "ID_INVALID", p + "/id", "Invalid placement identifier")
            elif ident in all_placements:
                _add(issues, "ID_DUPLICATE", p + "/id", "Placement ID repeated")
            else:
                all_placements.add(ident)
            if pl.get("component") not in identities["components"]:
                _add(issues, "PLACEMENT_COMPONENT", p + "/component", "Missing component")
            if pl.get("presentation") is not None and pl["presentation"] not in identities["presentations"]:
                _add(issues, "PLACEMENT_PRESENTATION", p + "/presentation", "Missing presentation")
            pos = pl.get("position")
            if type(pos) is not int or pos < 0:
                _add(issues, "PLACEMENT_POSITION", p + "/position", "Position must be non-negative integer")
            elif pos in used_positions:
                _add(issues, "POSITION_COLLISION", p + "/position", "Position already occupied in this view")
            else:
                used_positions.add(pos)
    return issues


def load_manifests(directory: str | Path) -> dict[str, dict]:
    manifests = {}
    for file in sorted(Path(directory).glob("*.json")):
        data = json.loads(file.read_text(encoding="utf-8"))
        manifests[data["type_id"]] = data
    return manifests
