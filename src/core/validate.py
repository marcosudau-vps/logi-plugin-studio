"""Static project validation (P0-ADR-001..007, ADR-005 with scope limit).

Works directly on the raw JSON document with true JSON indices, so diagnostics
always point at the actual input location. The typed model (io.py) is a
lossless view used for serialization; validity is decided here.

Deterministic: issues are sorted by (path, code, message, severity).
``valid`` means zero ERROR diagnostics; WARNING diagnostics (conservative
payload uncertainty, deferred capabilities) do not block validity.
No runtime semantics, no device access, no eval, no exceptions on malformed
input — every shape violation becomes a structured Diagnostic.
"""
from __future__ import annotations

from typing import Any

from .compat import SUPPORTED_VALUE_KEYWORDS, check_value, payload_compatibility, schema_shape_paths, schema_unknown_paths
from .errors import Diagnostic
from .ids import is_valid_id
from .io import TOP_LEVEL_KNOWN
from .registry import SIGNAL_KINDS, TypeRegistry

SCHEMA_VERSION = "0.1-draft"

# Draft candidates — explicitly NOT a final enum (P0-ADR-005 scope limit).
SCOPE_CANDIDATES_DRAFT = ("project", "component", "placement", "session")
AUTHORITY_ROLE_CANDIDATES_DRAFT = ("host", "runtime", "component")
PERSISTENCE_CANDIDATES_DRAFT = ("none", "runtime_local", "external")

_COLLECTIONS = ("components", "states", "bindings", "presentations", "assets", "views")


def _raw_lists(raw: dict[str, Any]) -> dict[str, list]:
    out: dict[str, list] = {}
    for key in _COLLECTIONS:
        val = raw.get(key, [])
        out[key] = val if isinstance(val, list) else []
    return out


def validate_project(raw: Any, registry: TypeRegistry) -> list[Diagnostic]:
    issues: list[Diagnostic] = []

    def add(code: str, path: str, message: str, severity: str = "ERROR") -> None:
        issues.append(Diagnostic(code, path, message, severity))

    if not isinstance(raw, dict):
        return [Diagnostic("PROJECT_SHAPE", "/", "Root must be an object")]
    for missing in sorted(TOP_LEVEL_KNOWN - set(raw)):
        add("FIELD_REQUIRED", "/", f"Missing {missing}")
    for unexpected in sorted(set(raw) - TOP_LEVEL_KNOWN):
        add("FIELD_UNKNOWN", f"/{unexpected}", "Unknown project field (preserved, not silently dropped)")
    if raw.get("schema_version") != SCHEMA_VERSION:
        add("VERSION_UNSUPPORTED", "/schema_version", f"Expected {SCHEMA_VERSION!r}")
    for key in _COLLECTIONS:
        if key in raw and not isinstance(raw[key], list):
            add("COLLECTION_SHAPE", f"/{key}", "Expected array")
    if "dependencies" in raw and not isinstance(raw["dependencies"], list):
        add("COLLECTION_SHAPE", "/dependencies", "Expected array")

    raw_lists = _raw_lists(raw)

    # --- identity: unique per object class (P0-ADR-001) ---
    identities: dict[str, dict[str, Any]] = {}
    for collection in _COLLECTIONS:
        seen: dict[str, Any] = {}
        for idx, obj in enumerate(raw_lists[collection]):
            path = f"/{collection}/{idx}"
            if not isinstance(obj, dict):
                add("OBJECT_SHAPE", path, "Expected object")
                continue
            ident = obj.get("id")
            if not is_valid_id(ident):
                add("ID_INVALID", f"{path}/id", "Invalid identifier")
                continue
            if ident in seen:
                add("ID_DUPLICATE", f"{path}/id", f"Duplicate {ident!r} in {collection}")
            else:
                seen[ident] = obj
        identities[collection] = seen

    _known_per_object = {
        "components": {"id", "type", "version", "config"},
        "states": {"id", "value_schema", "authority", "scope", "persistence", "fallback"},
        "bindings": {"id", "source", "target", "kind"},
        "presentations": {"id", "variants"},
        "assets": {"id", "path"},
        "views": {"id", "type", "placements"},
    }
    for collection, known in _known_per_object.items():
        for idx, obj in enumerate(raw_lists[collection]):
            if not isinstance(obj, dict):
                continue
            for key in sorted(set(obj) - known):
                add("FIELD_UNKNOWN", f"/{collection}/{idx}/{key}", "Unknown field (preserved, not silently dropped)")

    # --- project header ---
    meta = raw.get("project")
    if "project" in raw and not isinstance(meta, dict):
        add("PROJECT_SHAPE", "/project", "Project header must be an object")
    elif isinstance(meta, dict):
        if not is_valid_id(meta.get("id")):
            add("ID_INVALID", "/project/id", "Invalid project identifier")
        if not isinstance(meta.get("display_name"), str) or not meta.get("display_name"):
            add("FIELD_REQUIRED", "/project/display_name", "display_name must be a non-empty string")
        for key in sorted(set(meta) - {"id", "display_name"}):
            add("FIELD_UNKNOWN", f"/project/{key}", "Unknown project metadata (preserved, not silently dropped)")

    # --- dependencies ---
    raw_deps = raw.get("dependencies", [])
    if not isinstance(raw_deps, list):
        raw_deps = []
    for idx, dep in enumerate(raw_deps):
        path = f"/dependencies/{idx}"
        if not isinstance(dep, dict):
            add("OBJECT_SHAPE", path, "Expected object")
            continue
        if not is_valid_id(dep.get("type")):
            add("ID_INVALID", f"{path}/type", "Invalid dependency type identifier")
        if not isinstance(dep.get("version"), str):
            add("DEPENDENCY_VERSION", f"{path}/version", "Dependency version must be a string")
        for key in sorted(set(dep) - {"type", "version"}):
            add("FIELD_UNKNOWN", f"{path}/{key}", "Unknown dependency field (preserved, not silently dropped)")

    # --- components / type registry (exact version) ---
    for idx, comp in enumerate(raw_lists["components"]):
        if not isinstance(comp, dict):
            continue  # OBJECT_SHAPE already reported
        path = f"/components/{idx}"
        ctype, cver = comp.get("type"), comp.get("version")
        if not isinstance(ctype, str) or not isinstance(cver, str):
            add("TYPE_SHAPE", path, "Component type and version must be string identifiers")
            continue
        if "config" not in comp:
            add("FIELD_REQUIRED", f"{path}/config", "Component config is required")
            continue
        manifest = registry.resolve(ctype, cver)
        if manifest is None:
            if registry.has_type(ctype):
                add(
                    "TYPE_VERSION",
                    f"{path}/version",
                    f"Component version not pinned to available manifest "
                    f"(available: {registry.available_versions(ctype)})",
                )
            else:
                add("TYPE_MISSING", f"{path}/type", f"Unknown component type {ctype!r}")
            continue
        config = comp.get("config")
        if not isinstance(config, dict):
            add("CONFIG_INVALID", f"{path}/config", "config must be an object")
            continue
        for code, detail in check_value(config, manifest.config_schema):
            mapped = "CONFIG_INVALID" if code.startswith("VALUE_") else code
            add(mapped, f"{path}/config", detail)
        if manifest.capabilities:
            add(
                "CAPABILITY_DEFERRED",
                path,
                f"Capabilities {sorted(manifest.capabilities)} require a separate adapter-stage check",
                "WARNING",
            )

    # --- states: value schema + typed fallback; authority/scope declarative only ---
    for idx, state in enumerate(raw_lists["states"]):
        if not isinstance(state, dict):
            continue  # OBJECT_SHAPE already reported
        path = f"/states/{idx}"
        schema = state.get("value_schema")
        schema_ok = True
        if "value_schema" not in state:
            add("FIELD_REQUIRED", f"{path}/value_schema", "State value_schema is required")
            schema_ok = False
        elif not isinstance(schema, dict):
            add("SCHEMA_INVALID", f"{path}/value_schema", "value_schema must be an object")
            schema_ok = False
        elif set(schema) - SUPPORTED_VALUE_KEYWORDS:
            add(
                "SCHEMA_UNSUPPORTED",
                f"{path}/value_schema",
                f"Unsupported schema keywords: {sorted(set(schema) - SUPPORTED_VALUE_KEYWORDS)}",
            )
            schema_ok = False
        else:
            nested_unknown = [(s, k) for s, k in schema_unknown_paths(schema) if s]
            if nested_unknown:
                for sub, key in nested_unknown:
                    add("SCHEMA_UNSUPPORTED", f"{path}/value_schema{sub}", f"Unsupported schema keyword {key!r}")
                schema_ok = False
            else:
                for sub, detail in schema_shape_paths(schema):
                    add("SCHEMA_INVALID", f"{path}/value_schema{sub or ''}", detail)
                    schema_ok = False
        if schema_ok and "fallback" in state:
            for code, detail in check_value(state["fallback"], schema):
                add(code, f"{path}/fallback", detail)
        if "authority" not in state:
            add("FIELD_REQUIRED", f"{path}/authority", "State authority is required")
        scope = state.get("scope")
        if not isinstance(scope, str) or scope not in SCOPE_CANDIDATES_DRAFT:
            add(
                "SCOPE_INVALID",
                f"{path}/scope",
                f"Unknown scope {scope!r} (DRAFT candidates: {sorted(SCOPE_CANDIDATES_DRAFT)})",
            )
        persistence = state.get("persistence")
        if persistence is not None and (
            not isinstance(persistence, str) or persistence not in PERSISTENCE_CANDIDATES_DRAFT
        ):
            add(
                "PERSISTENCE_INVALID",
                f"{path}/persistence",
                f"Unknown persistence {persistence!r} (DRAFT candidates: {sorted(PERSISTENCE_CANDIDATES_DRAFT)})",
            )
        auth = state.get("authority")
        if not isinstance(auth, dict):
            if "authority" in state:
                add(
                    "AUTHORITY_INVALID",
                    f"{path}/authority",
                    f"Invalid authority (DRAFT roles: {sorted(AUTHORITY_ROLE_CANDIDATES_DRAFT)})",
                )
        else:
            for key in sorted(set(auth) - {"role", "component"}):
                add("FIELD_UNKNOWN", f"{path}/authority/{key}", "Unknown authority field (preserved, not silently dropped)")
            role = auth.get("role")
            if role not in AUTHORITY_ROLE_CANDIDATES_DRAFT:
                add(
                    "AUTHORITY_INVALID",
                    f"{path}/authority",
                    f"Invalid authority role {role!r} (DRAFT roles: {sorted(AUTHORITY_ROLE_CANDIDATES_DRAFT)})",
                )
            elif role == "component":
                target = auth.get("component")
                if not isinstance(target, str) or target not in identities["components"]:
                    add("AUTHORITY_MISSING", f"{path}/authority/component", "Missing authority component")
        # Writer-hoheit (ADR-005 Grundsatz): exactly one declared writer per state
        # entry is structurally guaranteed (single authority object); runtime
        # multi-instance enforcement is P2 and explicitly NOT implemented here.

    # --- endpoints (derived) ---
    def endpoint(ref: Any, path: str) -> tuple[str, str, dict[str, Any]] | None:
        if not (
            isinstance(ref, dict)
            and set(ref) == {"owner_kind", "owner_id", "port"}
            and isinstance(ref.get("owner_kind"), str)
            and isinstance(ref.get("owner_id"), str)
            and isinstance(ref.get("port"), str)
        ):
            add("ENDPOINT_SHAPE", path, "Expected {owner_kind, owner_id, port} with string values")
            return None
        owner_kind, owner_id, port = ref["owner_kind"], ref["owner_id"], ref["port"]
        sources = {"component": "components", "state": "states", "presentation": "presentations"}
        if owner_kind not in sources or owner_id not in identities[sources[owner_kind]]:
            add("ENDPOINT_MISSING", path, f"Unknown endpoint owner {owner_kind!r}:{owner_id!r}")
            return None
        raw_owner = identities[sources[owner_kind]][owner_id]
        if owner_kind == "component":
            manifest = registry.resolve(raw_owner.get("type"), raw_owner.get("version"))
            if manifest is None:
                add("ENDPOINT_MISSING", path, "Owner component type unresolved")
                return None
            match = next((p for p in manifest.ports if p.id == port), None)
            if match is None:
                add("PORT_MISSING", path, f"Unknown port {port!r}")
                return None
            return ("component", str(owner_id), {"direction": match.direction, "kind": match.kind, "payload_schema": match.payload_schema})
        if owner_kind == "state":
            if port != "value":
                add("PORT_MISSING", path, "State supports only virtual port 'value'")
                return None
            schema = raw_owner.get("value_schema", {})
            return ("state", str(owner_id), {"direction": "out", "kind": "state", "payload_schema": schema if isinstance(schema, dict) else {}})
        if port != "selector":
            add("PORT_MISSING", path, "Presentation supports only virtual port 'selector'")
            return None
        variants = raw_owner.get("variants", {})
        keys = sorted(variants) if isinstance(variants, dict) else []
        return (
            "presentation",
            str(owner_id),
            {"direction": "in", "kind": "state", "payload_schema": {"type": "string", "enum": keys}},
        )

    # --- bindings (raw iteration: true JSON indices) ---
    for idx, raw_bind in enumerate(raw_lists["bindings"]):
        if not isinstance(raw_bind, dict):
            continue  # OBJECT_SHAPE already reported
        path = f"/bindings/{idx}"
        if raw_bind.get("kind") not in SIGNAL_KINDS:
            add("SIGNAL_MISMATCH", f"{path}/kind", f"Unknown signal kind {raw_bind.get('kind')!r}")
        src = endpoint(raw_bind.get("source"), path + "/source")
        dst = endpoint(raw_bind.get("target"), path + "/target")
        if src is None or dst is None:
            continue
        a, b = src[2], dst[2]
        if a["direction"] != "out" or b["direction"] != "in":
            add("PORT_DIRECTION", path, "Binding requires out → in")
        if a["kind"] != b["kind"] or raw_bind.get("kind") != a["kind"]:
            add("SIGNAL_MISMATCH", path, "Binding signal categories differ")
            continue
        verdict = payload_compatibility(a.get("payload_schema", {}), b.get("payload_schema", {}))
        if verdict == "incompatible":
            add("PAYLOAD_INCOMPATIBLE", path, "Payload schemas are provably incompatible; no implicit conversion")
        elif verdict == "unknown":
            equal = a.get("payload_schema", {}) == b.get("payload_schema", {})
            if not equal:
                add(
                    "SCHEMA_NOT_PROVEN",
                    path,
                    "Payload compatibility not conservatively provable; explicit converter required",
                    "WARNING",
                )

    # --- presentations / assets ---
    for idx, pres in enumerate(raw_lists["presentations"]):
        if not isinstance(pres, dict):
            continue  # OBJECT_SHAPE already reported
        if "variants" not in pres:
            add("FIELD_REQUIRED", f"/presentations/{idx}/variants", "Presentation variants are required")
        elif not isinstance(pres.get("variants"), dict):
            add("PRESENTATION_SHAPE", f"/presentations/{idx}/variants", "variants must be an object")
        elif not pres["variants"]:
            add("PRESENTATION_SHAPE", f"/presentations/{idx}/variants", "variants must define at least one variant")
        else:
            for name in sorted(pres["variants"]):
                if not isinstance(pres["variants"][name], dict):
                    add(
                        "PRESENTATION_SHAPE",
                        f"/presentations/{idx}/variants/{name}",
                        "Each variant must be an object",
                    )
    for idx, asset in enumerate(raw_lists["assets"]):
        if not isinstance(asset, dict):
            continue  # OBJECT_SHAPE already reported
        if "path" not in asset:
            add("FIELD_REQUIRED", f"/assets/{idx}/path", "Asset path is required")
        elif not isinstance(asset.get("path"), str) or not asset.get("path"):
            add("ASSET_PATH", f"/assets/{idx}/path", "Asset path must be a non-empty string")

    # --- views / placements (raw iteration: true JSON indices) ---
    all_placements: set[str] = set()
    for view_i, raw_view in enumerate(raw_lists["views"]):
        if not isinstance(raw_view, dict):
            continue  # OBJECT_SHAPE already reported
        for key in sorted(set(raw_view) - {"id", "type", "placements"}):
            add("FIELD_UNKNOWN", f"/views/{view_i}/{key}", "Unknown view field (preserved, not silently dropped)")
        if "type" not in raw_view:
            add("FIELD_REQUIRED", f"/views/{view_i}/type", "View type is required")
        elif not isinstance(raw_view.get("type"), str):
            add("VIEW_SHAPE", f"/views/{view_i}/type", "View type must be a string")
        placements_raw = raw_view.get("placements")
        if not isinstance(placements_raw, list):
            add("VIEW_SHAPE", f"/views/{view_i}/placements", "placements must be an array")
            continue
        used_positions: set[Any] = set()
        for idx, pl in enumerate(placements_raw):
            path = f"/views/{view_i}/placements/{idx}"
            if not isinstance(pl, dict):
                add("OBJECT_SHAPE", path, "Expected object")
                continue
            for key in sorted(set(pl) - {"id", "component", "presentation", "position"}):
                add("FIELD_UNKNOWN", f"{path}/{key}", "Unknown placement field (preserved, not silently dropped)")
            pid = pl.get("id")
            if not is_valid_id(pid):
                add("ID_INVALID", path + "/id", "Invalid placement identifier")
            elif pid in all_placements:
                add("ID_DUPLICATE", path + "/id", "Placement ID repeated")
            else:
                all_placements.add(pid)
            pc = pl.get("component")
            if not isinstance(pc, str) or pc not in identities["components"]:
                add("PLACEMENT_COMPONENT", path + "/component", "Missing component")
            if "presentation" in pl:
                # Absent presentation is allowed (draft: optional); an explicit
                # null or mistyped/unknown value is not and must not be dropped.
                pp = pl.get("presentation")
                if not isinstance(pp, str) or pp not in identities["presentations"]:
                    add("PLACEMENT_PRESENTATION", path + "/presentation", "Missing presentation")
            pos = pl.get("position")
            if type(pos) is not int or pos < 0:
                add("PLACEMENT_POSITION", path + "/position", "Position must be a non-negative integer")
            elif pos in used_positions:
                add("POSITION_COLLISION", path + "/position", "Position already occupied in this view")
            else:
                used_positions.add(pos)
        # No hard-coded slot limit (P0-ADR-006/AR-009): any count allowed.

    issues.sort(key=lambda d: d.sort_key())
    return issues


def is_valid(issues: list[Diagnostic]) -> bool:
    return all(i.severity != "ERROR" for i in issues)
