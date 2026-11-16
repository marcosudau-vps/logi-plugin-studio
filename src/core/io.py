"""Deterministic JSON load/dump with lossless preservation (P0-ADR-002/007).

Invariant: ``project_to_dict(project_from_dict(raw)) == raw`` holds for *every*
input, valid or not. The typed model is a best-effort structured view; validity
is decided exclusively by the validator. Invalid input is therefore never
silently normalised into a seemingly valid project, and no unknown field,
malformed collection, or mistyped value is ever dropped.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .model import (
    MISSING,
    Asset,
    Binding,
    ComponentInstance,
    Dependency,
    EndpointRef,
    Placement,
    Presentation,
    Project,
    StateDefinition,
    View,
)

TOP_LEVEL_KNOWN = frozenset(
    {
        "schema_version",
        "project",
        "dependencies",
        "components",
        "states",
        "bindings",
        "presentations",
        "assets",
        "views",
    }
)

_COLLECTIONS = (
    "dependencies",
    "components",
    "states",
    "bindings",
    "presentations",
    "assets",
    "views",
)


def _get(d: dict, key: str) -> Any:
    """MISSING when the key is absent (so serialization omits it); else a deep copy."""
    return copy.deepcopy(d[key]) if key in d else MISSING


def _endpoint_from_dict(raw: Any) -> Any:
    """EndpointRef when well-formed; otherwise the raw value verbatim."""
    if (
        isinstance(raw, dict)
        and set(raw) == {"owner_kind", "owner_id", "port"}
        and isinstance(raw.get("owner_kind"), str)
        and isinstance(raw.get("owner_id"), str)
        and isinstance(raw.get("port"), str)
    ):
        return EndpointRef(owner_kind=raw["owner_kind"], owner_id=raw["owner_id"], port=raw["port"])
    return copy.deepcopy(raw)


def _endpoint_field(owner: dict, key: str) -> Any:
    """MISSING when the key is absent; otherwise EndpointRef or the raw value verbatim."""
    if key not in owner:
        return MISSING
    return _endpoint_from_dict(owner[key])


def _split(raw: dict, known: set[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    return ({k: v for k, v in raw.items() if k in known}, {k: v for k, v in raw.items() if k not in known})


def _endpoint_to_dict(ref: Any) -> Any:
    if isinstance(ref, EndpointRef):
        return {"owner_kind": ref.owner_kind, "owner_id": ref.owner_id, "port": ref.port}
    return copy.deepcopy(ref)


def project_from_dict(raw: Any) -> Project:
    if not isinstance(raw, dict):
        raise ValueError("Project root must be an object")
    present = frozenset(k for k in TOP_LEVEL_KNOWN if k in raw)
    extra = {k: copy.deepcopy(v) for k, v in raw.items() if k not in TOP_LEVEL_KNOWN}

    raw_proj = raw.get("project")
    project_extra: dict[str, Any] = {}
    project_raw: Any = MISSING
    project_id: Any = MISSING
    display_name: Any = MISSING
    if isinstance(raw_proj, dict):
        project_id = _get(raw_proj, "id")
        display_name = _get(raw_proj, "display_name")
        project_extra = {k: copy.deepcopy(v) for k, v in raw_proj.items() if k not in {"id", "display_name"}}
    elif "project" in raw:
        project_raw = copy.deepcopy(raw_proj)

    raw_items: list[tuple[str, int, Any]] = []
    raw_collections: dict[str, Any] = {}

    def items(key: str) -> list[dict]:
        val = raw.get(key, [])
        if not isinstance(val, list):
            raw_collections[key] = copy.deepcopy(val)
            return []
        out: list[dict] = []
        for idx, entry in enumerate(val):
            if isinstance(entry, dict):
                out.append(entry)
            else:
                raw_items.append((key, idx, copy.deepcopy(entry)))
        return out

    dependencies = tuple(
        Dependency(
            type=_get(d, "type"),
            version=_get(d, "version"),
            extra={k: copy.deepcopy(v) for k, v in d.items() if k not in {"type", "version"}},
        )
        for d in items("dependencies")
    )
    components = tuple(
        ComponentInstance(
            id=_get(c, "id"),
            type=_get(c, "type"),
            version=_get(c, "version"),
            config=_get(c, "config"),
            extra={k: copy.deepcopy(v) for k, v in c.items() if k not in {"id", "type", "version", "config"}},
        )
        for c in items("components")
    )
    states = tuple(
        StateDefinition(
            id=_get(s, "id"),
            value_schema=_get(s, "value_schema"),
            authority=_get(s, "authority"),
            scope=_get(s, "scope"),
            persistence=_get(s, "persistence"),
            fallback=copy.deepcopy(s["fallback"]) if "fallback" in s else MISSING,
            has_fallback="fallback" in s,
            extra={
                k: copy.deepcopy(v)
                for k, v in s.items()
                if k not in {"id", "value_schema", "authority", "scope", "persistence", "fallback"}
            },
        )
        for s in items("states")
    )
    bindings = tuple(
        Binding(
            id=_get(b, "id"),
            source=_endpoint_field(b, "source"),
            target=_endpoint_field(b, "target"),
            kind=_get(b, "kind"),
            extra={k: copy.deepcopy(v) for k, v in b.items() if k not in {"id", "source", "target", "kind"}},
        )
        for b in items("bindings")
    )
    presentations = tuple(
        Presentation(
            id=_get(p, "id"),
            variants=_get(p, "variants"),
            extra={k: copy.deepcopy(v) for k, v in p.items() if k not in {"id", "variants"}},
        )
        for p in items("presentations")
    )
    assets = tuple(
        Asset(
            id=_get(a, "id"),
            path=_get(a, "path"),
            extra={k: copy.deepcopy(v) for k, v in a.items() if k not in {"id", "path"}},
        )
        for a in items("assets")
    )
    views = tuple(
        _view_from_dict(v) for v in items("views")
    )
    return Project(
        schema_version=_get(raw, "schema_version"),
        project_id=project_id,
        display_name=display_name,
        dependencies=dependencies,
        components=components,
        states=states,
        bindings=bindings,
        presentations=presentations,
        assets=assets,
        views=views,
        extra=extra,
        present_keys=present,
        project_raw=project_raw,
        project_extra=project_extra,
        raw_items=tuple(raw_items),
        raw_collections=raw_collections,
    )


def _view_from_dict(v: dict) -> View:
    raw_pl = _get(v, "placements")
    if isinstance(raw_pl, list):
        placements = tuple(
            Placement(
                id=_get(pl, "id"),
                component=_get(pl, "component"),
                presentation=_get(pl, "presentation"),
                position=_get(pl, "position"),
                extra={
                    k: copy.deepcopy(x)
                    for k, x in pl.items()
                    if k not in {"id", "component", "presentation", "position"}
                },
            )
            for pl in raw_pl
            if isinstance(pl, dict)
        )
    else:
        placements = ()
    # placements_raw always carries the verbatim value (or MISSING when absent),
    # so serialization is lossless regardless of validity.
    view = View(
        id=_get(v, "id"),
        type=_get(v, "type"),
        placements=placements,
        placements_raw=raw_pl,
        extra={k: copy.deepcopy(x) for k, x in v.items() if k not in {"id", "type", "placements"}},
    )
    return view


def _restore_list(typed: list, skipped: list[tuple[int, Any]]) -> list:
    out = list(typed)
    for idx, value in sorted(skipped, key=lambda t: t[0]):
        out.insert(idx, copy.deepcopy(value))
    return out


def _obj(**fields: Any) -> dict[str, Any]:
    """Build a dict, omitting MISSING (absent-in-raw) fields."""
    return {k: copy.deepcopy(v) for k, v in fields.items() if v is not MISSING}


def project_to_dict(project: Project) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "schema_version" in project.present_keys and project.schema_version is not MISSING:
        out["schema_version"] = copy.deepcopy(project.schema_version)
    if "project" in project.present_keys:
        if project.project_raw is not MISSING:
            out["project"] = copy.deepcopy(project.project_raw)
        else:
            header: dict[str, Any] = {}
            if project.project_id is not MISSING:
                header["id"] = copy.deepcopy(project.project_id)
            if project.display_name is not MISSING:
                header["display_name"] = copy.deepcopy(project.display_name)
            header.update(copy.deepcopy(project.project_extra))
            out["project"] = header

    skipped: dict[str, list[tuple[int, Any]]] = {}
    for coll, idx, value in project.raw_items:
        skipped.setdefault(coll, []).append((idx, value))

    def collection(key: str, typed: list) -> Any:
        if key in project.raw_collections:
            return copy.deepcopy(project.raw_collections[key])
        return _restore_list(typed, skipped.get(key, []))

    if "dependencies" in project.present_keys:
        out["dependencies"] = collection(
            "dependencies",
            [
                {**_obj(type=d.type, version=d.version), **copy.deepcopy(d.extra)}
                for d in project.dependencies
            ],
        )
    if "components" in project.present_keys:
        out["components"] = collection(
            "components",
            [
                {**_obj(id=c.id, type=c.type, version=c.version, config=c.config), **copy.deepcopy(c.extra)}
                for c in project.components
            ],
        )
    if "states" in project.present_keys:
        out["states"] = collection(
            "states",
            [
                {
                    **_obj(
                        id=s.id,
                        value_schema=s.value_schema,
                        authority=s.authority,
                        scope=s.scope,
                        persistence=s.persistence,
                    ),
                    **({"fallback": copy.deepcopy(s.fallback)} if s.has_fallback else {}),
                    **copy.deepcopy(s.extra),
                }
                for s in project.states
            ],
        )
    if "bindings" in project.present_keys:
        out["bindings"] = collection(
            "bindings",
            [
                {
                    **_obj(id=b.id, kind=b.kind),
                    **({} if b.source is MISSING else {"source": _endpoint_to_dict(b.source)}),
                    **({} if b.target is MISSING else {"target": _endpoint_to_dict(b.target)}),
                    **copy.deepcopy(b.extra),
                }
                for b in project.bindings
            ],
        )
    if "presentations" in project.present_keys:
        out["presentations"] = collection(
            "presentations",
            [
                {**_obj(id=p.id, variants=p.variants), **copy.deepcopy(p.extra)}
                for p in project.presentations
            ],
        )
    if "assets" in project.present_keys:
        out["assets"] = collection(
            "assets",
            [
                {**_obj(id=a.id, path=a.path), **copy.deepcopy(a.extra)}
                for a in project.assets
            ],
        )
    if "views" in project.present_keys:
        serialized_views = []
        for v in project.views:
            entry: dict[str, Any] = {
                **_obj(id=v.id, type=v.type),
                **copy.deepcopy(v.extra),
            }
            if v.placements_raw is not MISSING:
                entry["placements"] = copy.deepcopy(v.placements_raw)
            serialized_views.append(entry)
        out["views"] = collection("views", serialized_views)
    for key, value in project.extra.items():
        if key not in out:
            out[key] = copy.deepcopy(value)
    return out


def load_project(path: str | Path) -> Project:
    return project_from_dict(load_raw(path))


def loads_project(text: str) -> Project:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Project root must be an object")
    return project_from_dict(data)


def dump_project(project: Project) -> str:
    return json.dumps(project_to_dict(project), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def load_raw(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Project root must be an object")
    return data
