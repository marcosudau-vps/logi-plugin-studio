"""Run-04 contract regressions: F10 (required proof) and F11 (nested keywords).

Conservative closed-world checks for the object-compatibility contract plus a
positive set guarding against over-correction.
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.compat import check_value, payload_compatibility  # noqa: E402
from core.io import load_raw  # noqa: E402
from core.registry import TypeRegistry, load_manifests  # noqa: E402
from core.validate import is_valid, validate_project  # noqa: E402


def fresh_registry() -> TypeRegistry:
    reg, errors = load_manifests(ROOT / "component_types")
    assert not errors, [e.as_dict() for e in errors]
    return reg


def obj(*, required=(), properties=None, ap=True):
    schema: dict = {"type": "object"}
    if required:
        schema["required"] = list(required)
    if properties is not None:
        schema["properties"] = properties
    if ap is not True:
        schema["additionalProperties"] = ap
    return schema


STR = {"type": "string"}
NUM = {"type": "number"}


class TestF10RequiredProof(unittest.TestCase):
    def test_capability_not_guarantee_is_unknown(self):
        # Reviewer F10 case: the witness is source-valid but target-invalid.
        source = obj(required=["y"], properties={"y": STR}, ap=True)
        target = obj(required=["x"], properties={"y": STR}, ap=True)
        self.assertEqual(check_value({"y": "ok"}, source), [])
        self.assertNotEqual(check_value({"y": "ok"}, target), [])
        self.assertEqual(payload_compatibility(source, target), "unknown")

    def test_source_required_superset_is_compatible(self):
        source = obj(required=["x", "y"], properties={"x": STR, "y": STR}, ap=True)
        target = obj(required=["x"], properties={"x": STR}, ap=True)
        self.assertEqual(payload_compatibility(source, target), "compatible")

    def test_identical_required_schemas_are_equal(self):
        schema = obj(required=["x"], properties={"x": STR}, ap=True)
        self.assertEqual(payload_compatibility(schema, copy.deepcopy(schema)), "equal")

    def test_unprovidable_target_required_is_incompatible(self):
        source = obj(required=["y"], properties={"y": STR}, ap=False)
        target = obj(required=["x"], properties={"y": STR}, ap=False)
        self.assertEqual(payload_compatibility(source, target), "incompatible")

    def test_required_provision_violation_is_incompatible(self):
        # string vs. number value sets are provably disjoint.
        source = obj(required=["x"], properties={"x": STR}, ap=True)
        target = obj(required=["x"], properties={"x": NUM}, ap=True)
        self.assertEqual(payload_compatibility(source, target), "incompatible")

    def test_required_without_schema_is_unknown(self):
        # Presence guaranteed, values unconstrained: overlap but no proof.
        source = obj(required=["x"], ap=True)
        target = obj(required=["x"], properties={"x": NUM}, ap=True)
        self.assertEqual(payload_compatibility(source, target), "unknown")

    def test_optional_satisfiable_name_is_unknown(self):
        source = obj(properties={"y": STR}, ap=True)
        target = obj(required=["y"], properties={"y": STR}, ap=True)
        self.assertEqual(payload_compatibility(source, target), "unknown")

    def test_end_to_end_warns(self):
        source = obj(required=["y"], properties={"y": STR}, ap=True)
        target = obj(required=["x"], properties={"y": STR}, ap=True)
        reg = TypeRegistry()
        reg.add_manifest({"type_id": "probe.req_src", "version": "1.0.0", "ports": [
            {"id": "s", "direction": "out", "kind": "event", "payload_schema": source}]})
        reg.add_manifest({"type_id": "probe.req_dst", "version": "1.0.0", "ports": [
            {"id": "t", "direction": "in", "kind": "event", "payload_schema": target}]})
        self.assertEqual(reg.issues, [])
        raw = load_raw(ROOT / "examples" / "project_core_valid.json")
        raw["dependencies"] = [{"type": "probe.req_src", "version": "1.0.0"},
                               {"type": "probe.req_dst", "version": "1.0.0"}]
        raw["components"] = [
            {"id": "c.src", "type": "probe.req_src", "version": "1.0.0", "config": {}},
            {"id": "c.dst", "type": "probe.req_dst", "version": "1.0.0", "config": {}}]
        raw["states"] = []
        raw["presentations"] = []
        raw["views"] = []
        raw["bindings"] = [{"id": "b.req", "kind": "event",
                            "source": {"owner_kind": "component", "owner_id": "c.src", "port": "s"},
                            "target": {"owner_kind": "component", "owner_id": "c.dst", "port": "t"}}]
        issues = validate_project(raw, reg)
        self.assertTrue(any(i.code == "SCHEMA_NOT_PROVEN" and i.severity == "WARNING" for i in issues),
                        [i.as_dict() for i in issues])


class TestF11NestedKeywords(unittest.TestCase):
    def test_nested_pattern_not_equal(self):
        schema = {"type": "object", "properties": {"optional": {"type": "string", "pattern": "^x"}}}
        self.assertNotIn(payload_compatibility(schema, copy.deepcopy(schema)), ("equal", "compatible"))

    def test_nested_unknown_in_items_and_extras(self):
        for schema in (
            {"type": "array", "items": {"type": "string", "pattern": "^x"}},
            {"type": "object", "properties": {"x": {"type": "string"}},
             "additionalProperties": {"type": "string", "pattern": "^x"}},
        ):
            with self.subTest(schema=schema):
                self.assertNotIn(payload_compatibility(schema, copy.deepcopy(schema)), ("equal", "compatible"))
                codes = [c for c, _ in check_value({"x": "ok"}, schema)]
                self.assertIn("SCHEMA_UNSUPPORTED", codes, codes)

    def test_nested_unsupported_manifest_diagnosed_with_path(self):
        reg = TypeRegistry()
        reg.add_manifest({"type_id": "probe.nested_kw", "version": "1.0.0",
                          "config_schema": {"type": "object",
                                            "properties": {"optional": {"type": "string", "pattern": "^x"}}},
                          "ports": []})
        self.assertTrue(reg.issues)
        self.assertTrue(all(i.code == "SCHEMA_UNSUPPORTED" for i in reg.issues))
        self.assertTrue(any("properties/optional" in i.path for i in reg.issues),
                        [i.as_dict() for i in reg.issues])

    def test_nested_unsupported_port_schema_diagnosed(self):
        reg = TypeRegistry()
        reg.add_manifest({"type_id": "probe.nested_port", "version": "1.0.0",
                          "ports": [{"id": "p", "direction": "out", "kind": "event",
                                     "payload_schema": {"type": "array", "items": {"type": "string",
                                                                                 "pattern": "^x"}}}]})
        self.assertTrue(reg.issues)
        self.assertTrue(any("items" in i.path for i in reg.issues))

    def test_supported_nested_schemas_still_work(self):
        good = {"type": "object", "properties": {"x": {"type": "string"}},
                "additionalProperties": {"type": "number"}}
        self.assertEqual(payload_compatibility(good, copy.deepcopy(good)), "equal")
        self.assertEqual(check_value({"x": "a"}, good), [])
        self.assertNotEqual(check_value({"x": "a", "extra": "s"}, good), [])
        reg = TypeRegistry()
        reg.add_manifest({"type_id": "probe.good_nested", "version": "1.0.0",
                          "config_schema": {"type": "object",
                                            "properties": {"name": {"type": "string", "minLength": 1},
                                                           "tags": {"type": "array",
                                                                    "items": {"type": "string"}}}},
                          "ports": []})
        self.assertEqual(reg.issues, [])
        raw = load_raw(ROOT / "examples" / "project_core_valid.json")
        issues = validate_project(raw, fresh_registry())
        self.assertTrue(is_valid(issues))

    def test_state_schema_nested_unknown_flagged(self):
        reg = fresh_registry()
        raw = load_raw(ROOT / "examples" / "project_core_valid.json")
        raw["states"][0]["value_schema"] = {
            "type": "object", "properties": {"x": {"type": "string", "pattern": "^x"}}}
        del raw["states"][0]["fallback"]
        issues = validate_project(raw, reg)
        self.assertIn("SCHEMA_UNSUPPORTED", [i.code for i in issues])
        self.assertFalse(is_valid(issues))


if __name__ == "__main__":
    unittest.main()
