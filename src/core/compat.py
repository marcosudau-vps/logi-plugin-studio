"""Conservative JSON-Schema helpers (P0-ADR-004).

Only a deliberately small subset of JSON Schema Draft 2020-12 is interpreted.
Anything outside that subset fails closed: value checks report SCHEMA_UNSUPPORTED
or SCHEMA_INVALID, and payload-compatibility analysis returns ``unknown``
(reported as SCHEMA_NOT_PROVEN with WARNING severity). This module never claims
full JSON-Schema subsumption and never raises on malformed schemas or values.
"""
from __future__ import annotations

from typing import Any

SUPPORTED_VALUE_KEYWORDS = frozenset(
    {
        "type",
        "enum",
        "const",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
    }
)

_SIMPLE_TYPES = ("string", "boolean", "integer", "number", "object", "array", "null")


def _is_int(value: Any) -> bool:
    return type(value) is int


def _is_num(value: Any) -> bool:
    return type(value) in (int, float)


def schema_shape_paths(schema: Any, _path: str = "") -> list[tuple[str, str]]:
    """Recursive well-formedness of *known* keywords' values (F09).

    Unknown keywords are ignored (handled conservatively elsewhere). Returns
    ``(json_pointer_suffix, detail)`` pairs; empty means well-formed within the
    supported subset. Recursion covers ``properties`` values, ``items`` and
    ``additionalProperties`` dicts, so a malformed optional nested schema is
    reported even when no configured value ever reaches it.
    """
    if not isinstance(schema, dict):
        return [(_path, "Schema must be an object")]
    details: list[tuple[str, str]] = []

    def at(sub: str) -> str:
        return f"{_path}/{sub}" if _path else f"/{sub}"

    if "type" in schema and schema["type"] not in _SIMPLE_TYPES:
        details.append((_path, f"Invalid type {schema['type']!r}"))
    if "enum" in schema and not isinstance(schema["enum"], list):
        details.append((_path, "enum must be an array"))
    if "required" in schema and (
        not isinstance(schema["required"], list)
        or any(not isinstance(r, str) for r in schema["required"])
    ):
        details.append((_path, "required must be an array of strings"))
    if "properties" in schema and not isinstance(schema["properties"], dict):
        details.append((_path, "properties must be an object"))
    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        if key in schema and (not _is_int(schema[key]) or schema[key] < 0):
            details.append((_path, f"{key} must be a non-negative integer"))
    for key in ("minimum", "maximum"):
        if key in schema and not _is_num(schema[key]):
            details.append((_path, f"{key} must be a number"))
    if "items" in schema and not isinstance(schema["items"], dict):
        details.append((_path, "items must be an object"))
    if "additionalProperties" in schema and not isinstance(
        schema["additionalProperties"], (bool, dict)
    ):
        details.append((_path, "additionalProperties must be a boolean or an object"))
    if isinstance(schema.get("properties"), dict):
        for name, sub in schema["properties"].items():
            details.extend(schema_shape_paths(sub, at(f"properties/{name}")))
    if isinstance(schema.get("items"), dict):
        details.extend(schema_shape_paths(schema["items"], at("items")))
    if isinstance(schema.get("additionalProperties"), dict):
        details.extend(schema_shape_paths(schema["additionalProperties"], at("additionalProperties")))
    return details


def schema_unknown_paths(schema: Any, _path: str = "") -> list[tuple[str, str]]:
    """Recursively collect unknown keywords (F11).

    Checks every supported schema position: the schema itself plus nested
    ``properties`` values, ``items`` and ``additionalProperties`` dicts — even
    for optional fields that no configured value ever reaches. Returns sorted
    ``(json_pointer_suffix, keyword)`` pairs; empty means no unknown keywords.
    Non-dict subschemas are ignored here (reported by ``schema_shape_paths``).
    """
    found: list[tuple[str, str]] = []

    def visit(node: Any, path: str) -> None:
        if not isinstance(node, dict):
            return
        for key in sorted(set(node) - SUPPORTED_VALUE_KEYWORDS):
            found.append((path, key))
        if isinstance(node.get("properties"), dict):
            for name, sub in node["properties"].items():
                visit(sub, f"{path}/properties/{name}")
        if isinstance(node.get("items"), dict):
            visit(node["items"], f"{path}/items")
        if isinstance(node.get("additionalProperties"), dict):
            visit(node["additionalProperties"], f"{path}/additionalProperties")

    visit(schema, _path)
    return sorted(found)


def schema_shape_errors(schema: Any) -> list[str]:
    """Well-formedness of *known* keywords' values (unknown keywords ignored).

    Used to fail closed without claiming anything about keywords outside the
    supported subset. Returns human-readable details; empty means well-formed.
    """
    return [detail for _, detail in schema_shape_paths(schema)]


def _type_matches(value: Any, kind: str) -> bool:
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "integer":
        return type(value) is int
    if kind == "number":
        return type(value) in (int, float) and not isinstance(value, bool)
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "null":
        return value is None
    return False


def check_value(value: Any, schema: Any) -> list[tuple[str, str]]:
    """Return ``[(code, detail)]`` violations; malformed schemas fail closed."""
    if not isinstance(schema, dict):
        return [("SCHEMA_INVALID", "Schema must be an object")]
    unknown = sorted(set(schema) - SUPPORTED_VALUE_KEYWORDS)
    if unknown:
        return [("SCHEMA_UNSUPPORTED", f"Unsupported schema keywords: {unknown}")]
    nested = [(sub, key) for sub, key in schema_unknown_paths(schema) if sub]
    if nested:
        return [("SCHEMA_UNSUPPORTED", f"{sub}: unsupported keyword {key!r}") for sub, key in nested]
    shape = schema_shape_paths(schema)
    if shape:
        return [("SCHEMA_INVALID", f"{sub or '/'}: {detail}") for sub, detail in shape]
    problems: list[tuple[str, str]] = []
    kind = schema.get("type")
    if kind is not None and not _type_matches(value, kind):
        problems.append(("VALUE_TYPE", f"Expected {kind}"))
        return problems
    if "const" in schema and value != schema["const"]:
        problems.append(("VALUE_CONST", "Value differs from const"))
    if "enum" in schema:
        try:
            if value not in schema["enum"]:
                problems.append(("VALUE_ENUM", "Value not present in enum"))
        except TypeError:
            problems.append(("VALUE_ENUM", "Value not present in enum"))
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            problems.append(("VALUE_LENGTH", "String below minLength"))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            problems.append(("VALUE_LENGTH", "String exceeds maxLength"))
    if _is_num(value):
        if "minimum" in schema and value < schema["minimum"]:
            problems.append(("VALUE_RANGE", "Value below minimum"))
        if "maximum" in schema and value > schema["maximum"]:
            problems.append(("VALUE_RANGE", "Value above maximum"))
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            problems.append(("VALUE_LENGTH", "Array below minItems"))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            problems.append(("VALUE_LENGTH", "Array exceeds maxItems"))
        if "items" in schema:
            for idx, item in enumerate(value):
                for code, detail in check_value(item, schema["items"]):
                    problems.append((code, f"[{idx}]: {detail}"))
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for required in schema.get("required", []) or []:
            if required not in value:
                problems.append(("VALUE_REQUIRED", f"Missing {required}"))
        for key, item in value.items():
            if key in properties:
                for code, detail in check_value(item, properties[key]):
                    problems.append((code, f"{key}: {detail}"))
            elif schema.get("additionalProperties") is False:
                problems.append(("VALUE_UNKNOWN", f"Unexpected property {key}"))
            elif isinstance(schema.get("additionalProperties"), dict):
                for code, detail in check_value(item, schema["additionalProperties"]):
                    problems.append((code, f"{key}: {detail}"))
    return problems


def _freeze(value: Any) -> Any | None:
    """Deterministic hashable form; None when the value is not JSON-like."""
    if isinstance(value, bool) or value is None or isinstance(value, (str, int, float)):
        return value
    if isinstance(value, list):
        frozen = [_freeze(v) for v in value]
        return tuple(frozen) if all(f is not None for f in frozen) else None
    if isinstance(value, dict):
        frozen = [(k, _freeze(v)) for k, v in value.items() if isinstance(k, str)]
        if len(frozen) != len(value) or any(f is None for _, f in frozen):
            return None
        return tuple(sorted(frozen))
    return None


def _enum_set(values: Any) -> set | None:
    if not isinstance(values, list):
        return None
    frozen = [_freeze(v) for v in values]
    if any(f is None for f in frozen):
        return None
    try:
        return set(frozen)
    except TypeError:
        return None


def _object_verdict(source: dict, target: dict) -> str:
    """Conservative object-subschema verdict: ``"compatible"`` | ``"unknown"`` | ``"incompatible"``.

    Only called when both schemas use the supported subset and are well-formed.
    ``"compatible"`` means every source-valid object is provably target-valid;
    ``"incompatible"`` means the value sets are provably disjoint; otherwise
    ``"unknown"`` (overlap possible or unprovable either way).
    """
    s_props: dict = source.get("properties", {})
    t_props: dict = target.get("properties", {})
    s_req = set(source.get("required", []))
    t_req = set(target.get("required", []))
    s_ap = source.get("additionalProperties", True)
    t_ap = target.get("additionalProperties", True)
    narrowed = False

    def target_constraint(name: str) -> Any:
        if name in t_props:
            return t_props[name]
        if isinstance(t_ap, dict):
            return t_ap
        return None  # unconstrained

    # (A) Target-required names: `compatible` additionally requires that EVERY
    # source-valid instance carries a satisfying value (F10). Mere provision
    # ability ("the source *can* contain the field") is not a guarantee ("the
    # source *always* contains it") — only `required` on the source side gives
    # the latter.
    for name in t_req:
        guaranteed = name in s_req
        if name in s_props:
            provision: Any = s_props[name]
        elif isinstance(s_ap, dict):
            provision = s_ap
        elif s_ap is True or guaranteed:
            provision = None  # unconstrained values: satisfiable, never provable
        else:
            return "incompatible"  # s_ap False, not required: source never has it
        constraint = target_constraint(name)
        if provision is None or constraint is None:
            if guaranteed and provision is not None and constraint is None:
                continue  # always present; the target imposes nothing on it
            # Overlap exists (or is possible) but a universal proof does not:
            # instances without `name` violate the target requirement.
            return "unknown"
        sub = payload_compatibility(provision, constraint)
        if sub == "incompatible":
            return "incompatible"
        if sub == "unknown":
            return "unknown"
        if not guaranteed:
            return "unknown"  # satisfiable instances exist, but so do violators
        if sub == "compatible":
            narrowed = True

    # (B) Source-governed names must satisfy the target restriction that
    # applies to them — including source-explicit properties the target treats
    # as additional properties (F08).
    for name in s_props:
        constraint = target_constraint(name)
        if constraint is None:
            narrowed = True  # source restricts a name the target ignores
            continue
        sub = payload_compatibility(s_props[name], constraint)
        if sub == "compatible":
            narrowed = True
        elif sub == "equal":
            pass
        elif sub == "incompatible":
            if name in s_req:
                return "incompatible"  # every source instance carries a violating value
            return "unknown"  # omitting the name may still satisfy the target
        else:
            return "unknown"
    if s_req - set(s_props):
        # Source-required names without an explicit schema carry unconstrained
        # values; any target restriction on them is neither provable nor
        # excludable.
        for name in s_req - set(s_props):
            if target_constraint(name) is not None:
                return "unknown"

    # (C) Source additional properties vs. target named/extra restrictions.
    for name, t_sub in t_props.items():
        if name in s_props or name in t_req:
            continue  # covered by (A)/(B)
        if s_ap is False:
            continue  # source never carries this extra name
        if not isinstance(s_ap, dict):
            return "unknown"  # unconstrained extras may violate the named schema
        sub = payload_compatibility(s_ap, t_sub)
        if sub == "compatible":
            narrowed = True
        elif sub != "equal":
            return "unknown"
    if t_ap is False:
        extra_names = set(s_props) - set(t_props)
        if extra_names & s_req:
            return "incompatible"  # always-present names the target forbids
        if extra_names or s_ap is not False:
            # Avoidable but possible extras: overlap exists, proof does not.
            return "unknown"
    elif isinstance(t_ap, dict):
        if isinstance(s_ap, dict):
            sub = payload_compatibility(s_ap, t_ap)
            if sub == "compatible":
                narrowed = True
            elif sub != "equal":
                return "unknown"
        elif s_ap is not False:
            return "unknown"
        if set(s_props) - set(t_props) and s_ap is False:
            narrowed = True  # explicit names already checked in (B)

    if s_req - t_req:
        narrowed = True  # source guarantees names the target does not demand
    return "compatible" if narrowed else "unknown"


def payload_compatibility(source: Any, target: Any) -> str:
    """Return ``"equal"`` | ``"compatible"`` | ``"incompatible"`` | ``"unknown"``.

    Conservative and truthful: a non-equal ``"compatible"`` is returned only
    when every value valid under ``source`` is provably valid under ``target``
    for *every* constraining keyword present in either schema. Any tighter
    target constraint the source does not provably satisfy (``maxLength``,
    ``minLength``, ``minimum``/``maximum``, ``properties``/``required``,
    ``items``, ...) yields ``"unknown"``. Provably disjoint value sets yield
    ``"incompatible"``. Malformed schemas yield ``"unknown"``, never an
    exception. No claim of full JSON-Schema subsumption is made.
    Malformed or unsupported schemas never yield ``"equal"`` or ``"compatible"``:
    shape and keyword checks run before the equality shortcut, and ``"unknown"``
    (rather than an exception or a guess) is returned for anything unprovable.
    """
    if not isinstance(source, dict) or not isinstance(target, dict):
        return "unknown"
    if set(source) - SUPPORTED_VALUE_KEYWORDS or set(target) - SUPPORTED_VALUE_KEYWORDS:
        return "unknown"
    if schema_unknown_paths(source) or schema_unknown_paths(target):
        return "unknown"
    if schema_shape_errors(source) or schema_shape_errors(target):
        return "unknown"
    if source == target:
        return "equal"
    if source.get("type") != target.get("type"):
        # Provably disjoint primitive pairs (Draft 2020-12 type semantics):
        # every pair except integer/number (subset) is disjoint. Anything else
        # stays `unknown` — never a guess.
        s_t, t_t = source.get("type"), target.get("type")
        if s_t in _SIMPLE_TYPES and t_t in _SIMPLE_TYPES and {s_t, t_t} != {"integer", "number"}:
            return "incompatible"
        return "unknown"
    if source.get("type") not in _SIMPLE_TYPES:
        return "unknown"

    verdicts: list[str] = []

    # enum / const: the source value set must be a subset of the target's.
    if "enum" in source or "enum" in target:
        s_vals = _enum_set(source["enum"]) if "enum" in source else None
        t_vals = _enum_set(target["enum"]) if "enum" in target else None
        if s_vals is None and "enum" in source:
            return "unknown"
        if t_vals is None and "enum" in target:
            return "unknown"
        if s_vals is not None and t_vals is not None:
            if s_vals == t_vals:
                pass
            elif s_vals < t_vals:
                verdicts.append("narrower")
            elif s_vals.isdisjoint(t_vals):
                return "incompatible"
            else:
                return "unknown"
        elif t_vals is not None:
            return "unknown"  # source may produce values outside the target enum
        else:
            verdicts.append("narrower")  # source enum values share target's type
    if "const" in source or "const" in target:
        if "const" in source and "const" in target:
            if source["const"] != target["const"]:
                return "incompatible"
        elif "const" in source:
            problems = check_value(source["const"], target)
            blocking = [c for c, _ in problems if c.startswith(("VALUE_", "SCHEMA_"))]
            if blocking:
                if any(c in ("VALUE_CONST", "VALUE_ENUM", "VALUE_TYPE") for c, _ in problems):
                    return "incompatible"
                return "unknown"
            verdicts.append("narrower")
        else:
            return "unknown"

    # Range / length keywords: a tighter target constraint the source does not
    # provably satisfy means compatibility cannot be shown.
    for key, cmp in (
        ("minLength", lambda s, t: s >= t),
        ("maxLength", lambda s, t: s <= t),
        ("minimum", lambda s, t: s >= t),
        ("maximum", lambda s, t: s <= t),
        ("minItems", lambda s, t: s >= t),
        ("maxItems", lambda s, t: s <= t),
    ):
        if key in target and key not in source:
            return "unknown"
        if key in source and key in target and source[key] != target[key]:
            if cmp(source[key], target[key]):
                verdicts.append("narrower")
            else:
                return "unknown"

    # Object keywords: every target restriction must provably hold for source
    # values. This includes source-explicit properties that the target
    # classifies as additional (F08): they must satisfy the target's
    # additionalProperties schema or compatibility is unprovable.
    if any(k in source or k in target for k in ("required", "properties", "additionalProperties")):
        sub = _object_verdict(source, target)
        if sub == "incompatible":
            return "incompatible"
        if sub == "unknown":
            return "unknown"
        if sub == "compatible":
            verdicts.append("narrower")

    # Array items: element schemas must be compatible; disjointness cannot be
    # proven (the empty array is valid under both unless minItems forbids it,
    # which the minItems rule above already handles conservatively).
    if "items" in target or "items" in source:
        if "items" not in target:
            verdicts.append("narrower")
        elif "items" not in source:
            return "unknown"
        else:
            sub = payload_compatibility(source["items"], target["items"])
            if sub == "compatible":
                verdicts.append("narrower")
            elif sub != "equal":
                return "unknown"

    return "compatible" if verdicts else "unknown"
