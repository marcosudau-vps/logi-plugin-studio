"""Run-03 hardening regressions: reviewer repros F06-F09 plus draft/core consistency.

Adopts all 13 assertions from work/packages/AP-CORE-001/10_review_repros_RUN02.py
(import path adapted: the reviewer script's ``from src.core...`` form is shadowed
in this environment by an unrelated third-party ``src`` package in site-packages;
assertions are unchanged). Uses the ``core.*`` import style like the other suites.
"""
from __future__ import annotations

import copy
import tempfile
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.compat import check_value, payload_compatibility  # noqa: E402
from core.io import dump_project, load_raw, loads_project, project_from_dict, project_to_dict  # noqa: E402
from core.registry import TypeRegistry, load_manifests  # noqa: E402
from core.validate import is_valid, validate_project  # noqa: E402


def base() -> dict:
    return load_raw(ROOT / "examples" / "project_core_valid.json")


def fresh_registry() -> TypeRegistry:
    reg, errors = load_manifests(ROOT / "component_types")
    assert not errors, [e.as_dict() for e in errors]
    return reg


class TestReviewF06Lossless(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = fresh_registry()

    def assert_lossless(self, raw: dict) -> None:
        self.assertEqual(project_to_dict(project_from_dict(raw)), raw)

    def test_project_null_roundtrip(self):
        raw = base()
        raw["project"] = None
        self.assert_lossless(raw)
        self.assertFalse(is_valid(validate_project(raw, self.reg)))

    def test_missing_endpoint_keys_roundtrip(self):
        for field in ("source", "target"):
            with self.subTest(field=field):
                raw = base()
                del raw["bindings"][0][field]
                self.assert_lossless(raw)
                self.assertFalse(is_valid(validate_project(raw, self.reg)))

    def test_null_placements_roundtrip(self):
        raw = base()
        raw["views"][0]["placements"] = None
        self.assert_lossless(raw)
        issues = validate_project(raw, self.reg)
        self.assertIn("VIEW_SHAPE", [i.code for i in issues])
        self.assertFalse(is_valid(issues))

    def test_presentation_null_roundtrip_and_validation(self):
        raw = base()
        raw["views"][0]["placements"][0]["presentation"] = None
        self.assert_lossless(raw)
        self.assertFalse(is_valid(validate_project(raw, self.reg)))

    def test_absent_presentation_stays_valid_and_omitted(self):
        raw = base()
        del raw["views"][0]["placements"][0]["presentation"]
        self.assert_lossless(raw)
        self.assertTrue(is_valid(validate_project(raw, self.reg)))


class TestReviewF07Consistency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = fresh_registry()

    def codes(self, raw: dict) -> list[str]:
        return [i.code for i in validate_project(raw, self.reg)]

    def test_dependency_unknown_field(self):
        raw = base()
        raw["dependencies"][0]["future_field"] = 17
        issues = validate_project(raw, self.reg)
        self.assertIn(("FIELD_UNKNOWN", "/dependencies/0/future_field"), {(i.code, i.path) for i in issues})
        self.assertFalse(is_valid(issues))
        self.assertEqual(project_to_dict(project_from_dict(raw)), raw)

    def test_authority_unknown_field(self):
        raw = base()
        raw["states"][0]["authority"]["future_field"] = True
        issues = validate_project(raw, self.reg)
        self.assertIn(("FIELD_UNKNOWN", "/states/0/authority/future_field"), {(i.code, i.path) for i in issues})
        self.assertFalse(is_valid(issues))
        self.assertEqual(project_to_dict(project_from_dict(raw)), raw)

    def test_variant_requires_object(self):
        raw = base()
        raw["presentations"][0]["variants"]["variant_0"] = "invalid"
        self.assertFalse(is_valid(validate_project(raw, self.reg)))
        self.assertIn("PRESENTATION_SHAPE", self.codes(raw))

    def test_empty_variants_rejected(self):
        raw = base()
        raw["presentations"][0]["variants"] = {}
        self.assertFalse(is_valid(validate_project(raw, self.reg)))

    def test_view_type_requires_string(self):
        raw = base()
        raw["views"][0]["type"] = 123
        self.assertFalse(is_valid(validate_project(raw, self.reg)))
        self.assertIn("VIEW_SHAPE", self.codes(raw))

    def test_missing_view_type_required(self):
        raw = base()
        del raw["views"][0]["type"]
        issues = validate_project(raw, self.reg)
        self.assertIn("FIELD_REQUIRED", [i.code for i in issues])
        self.assertFalse(is_valid(issues))
        self.assertEqual(project_to_dict(project_from_dict(raw)), raw)


class TestReviewF08ConservativeCompat(unittest.TestCase):
    def test_extra_properties_compatibility(self):
        source = {"type": "object", "properties": {"x": {"type": "string"}}, "additionalProperties": False}
        target = {"type": "object", "additionalProperties": {"type": "number"}}
        self.assertEqual(check_value({"x": "hello"}, source), [])
        self.assertNotEqual(check_value({"x": "hello"}, target), [])
        self.assertNotIn(payload_compatibility(source, target), ("equal", "compatible"))

    def test_binding_end_to_end(self):
        source = {"type": "object", "properties": {"x": {"type": "string"}}, "additionalProperties": False}
        target = {"type": "object", "additionalProperties": {"type": "number"}}
        reg = TypeRegistry()
        reg.add_manifest({"type_id": "probe.sender", "version": "1.0.0", "ports": [
            {"id": "emit", "direction": "out", "kind": "event", "payload_schema": source}]})
        reg.add_manifest({"type_id": "probe.receiver", "version": "1.0.0", "ports": [
            {"id": "accept", "direction": "in", "kind": "event", "payload_schema": target}]})
        self.assertEqual(reg.issues, [])
        raw = base()
        raw["components"] = [
            {"id": "source.one", "type": "probe.sender", "version": "1.0.0", "config": {}},
            {"id": "target.one", "type": "probe.receiver", "version": "1.0.0", "config": {}}]
        raw["bindings"] = [{"id": "link.one", "kind": "event",
                            "source": {"owner_kind": "component", "owner_id": "source.one", "port": "emit"},
                            "target": {"owner_kind": "component", "owner_id": "target.one", "port": "accept"}}]
        raw["states"] = []
        raw["presentations"] = []
        raw["views"] = []
        raw["dependencies"] = [{"type": "probe.sender", "version": "1.0.0"},
                               {"type": "probe.receiver", "version": "1.0.0"}]
        issues = validate_project(raw, reg)
        self.assertTrue(any(i.code in ("SCHEMA_NOT_PROVEN", "PAYLOAD_INCOMPATIBLE") for i in issues),
                        f"No compatibility warning or error: {[i.as_dict() for i in issues]}")

    def test_identical_malformed_schema_is_not_equal(self):
        broken = {"type": "string", "minLength": []}
        self.assertNotEqual(payload_compatibility(broken, broken), "equal")

    def test_identical_unsupported_schema_is_not_equal(self):
        schema = {"type": "string", "pattern": "^a"}
        self.assertNotIn(payload_compatibility(schema, dict(schema)), ("equal", "compatible"))

    def test_still_compatible_narrowing(self):
        self.assertEqual(
            payload_compatibility({"type": "string", "enum": ["a"]}, {"type": "string", "enum": ["a", "b"]}),
            "compatible",
        )
        self.assertEqual(
            payload_compatibility({"type": "string"}, {"type": "string"}),
            "equal",
        )

    def test_explicit_prop_satisfying_target_additional(self):
        # Sound positive: source x is a number, target extras require numbers.
        source = {"type": "object", "properties": {"x": {"type": "number"}}, "additionalProperties": False}
        target = {"type": "object", "additionalProperties": {"type": "number"}}
        self.assertEqual(payload_compatibility(source, target), "compatible")


class TestReviewF09NestedSchemas(unittest.TestCase):
    def test_nested_schema_checked_even_if_optional_unset(self):
        reg = TypeRegistry()
        reg.add_manifest({"type_id": "probe.bad_schema", "version": "1.0.0",
                          "config_schema": {"type": "object", "properties": {
                              "optional": {"type": "string", "minLength": []}}},
                          "ports": []})
        self.assertTrue(reg.issues, "Malformed optional nested schema silently accepted")
        self.assertTrue(all(i.code == "SCHEMA_INVALID" for i in reg.issues))
        self.assertTrue(any("properties/optional" in i.path for i in reg.issues))

    def test_nested_items_and_additional_properties_checked(self):
        reg = TypeRegistry()
        reg.add_manifest({"type_id": "probe.bad_nested", "version": "1.0.0",
                          "config_schema": {"type": "object",
                                            "additionalProperties": {"type": "integer", "minimum": "bad"}},
                          "ports": [{"id": "p", "direction": "out", "kind": "event",
                                     "payload_schema": {"type": "array", "items": {"type": "string", "maxItems": []}}}]})
        paths = [i.path for i in reg.issues]
        self.assertTrue(any("additionalProperties" in p for p in paths), paths)
        self.assertTrue(any("items" in p for p in paths), paths)

    def test_malformed_nested_schema_does_not_crash_validation(self):
        reg = fresh_registry()
        raw = base()
        raw["states"][0]["value_schema"] = {"type": "object", "properties": {"x": {"type": "string", "minLength": []}}}
        raw["states"][0]["fallback"] = {"x": "ok"}
        issues = validate_project(raw, reg)
        self.assertIn("SCHEMA_INVALID", [i.code for i in issues])
        self.assertFalse(is_valid(issues))


class TestDraftCoreConsistency(unittest.TestCase):
    """Parametric: draft-schema rejections must also fail core validation."""

    @classmethod
    def setUpClass(cls):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            raise unittest.SkipTest("jsonschema not installed")
        cls.validator_cls = Draft202012Validator
        cls.schema = json.loads((ROOT / "schemas" / "project_v0_1_core.schema.json").read_text(encoding="utf-8"))
        cls.reg = fresh_registry()

    def mutations(self) -> dict[str, object]:
        def dep_unknown(m):
            m["dependencies"][0]["future_field"] = 1

        def auth_unknown(m):
            m["states"][0]["authority"]["future_field"] = 1

        def variant_str(m):
            m["presentations"][0]["variants"]["variant_0"] = "nope"

        def view_type_int(m):
            m["views"][0]["type"] = 7

        def presentation_null(m):
            m["views"][0]["placements"][0]["presentation"] = None

        def placements_null(m):
            m["views"][0]["placements"] = None

        def project_null(m):
            m["project"] = None

        def missing_source(m):
            del m["bindings"][0]["source"]

        return {
            "dep_unknown": dep_unknown,
            "auth_unknown": auth_unknown,
            "variant_str": variant_str,
            "view_type_int": view_type_int,
            "presentation_null": presentation_null,
            "placements_null": placements_null,
            "project_null": project_null,
            "missing_source": missing_source,
        }

    def test_draft_and_core_agree_on_negatives(self):
        for name, mutate in self.mutations().items():
            with self.subTest(case=name):
                raw = base()
                mutate(raw)
                draft_errors = list(self.validator_cls(self.schema).iter_errors(raw))
                self.assertTrue(draft_errors, f"draft schema unexpectedly accepts {name}")
                core_issues = validate_project(raw, self.reg)
                self.assertFalse(is_valid(core_issues), f"core validator accepts {name}")
                # lossless in both cases
                self.assertEqual(project_to_dict(project_from_dict(raw)), raw)

    def test_valid_example_passes_both(self):
        raw = base()
        self.assertEqual(list(self.validator_cls(self.schema).iter_errors(raw)), [])
        self.assertTrue(is_valid(validate_project(raw, self.reg)))


class TestStability(unittest.TestCase):
    def test_multi_cycle_load_dump(self):
        raw = base()
        seen = set()
        current = raw
        for _ in range(3):
            text = dump_project(project_from_dict(current))
            seen.add(text)
            current = json.loads(text)
        self.assertEqual(len(seen), 1)
        self.assertEqual(current, raw)

    def test_invalid_multi_cycle_lossless(self):
        raw = base()
        raw["views"][0]["placements"] = None
        raw["project"] = None
        current = raw
        for _ in range(3):
            current = json.loads(dump_project(project_from_dict(current)))
        self.assertEqual(current, raw)

    def test_diagnostics_sorted_and_shaped(self):
        raw = base()
        raw["components"].append(copy.deepcopy(raw["components"][0]))
        del raw["bindings"][0]["source"]
        issues = validate_project(raw, fresh_registry())
        keys = [(i.path, i.code, i.message, i.severity) for i in issues]
        self.assertEqual(keys, sorted(keys))
        self.assertTrue(keys)
        for i in issues:
            d = i.as_dict()
            self.assertTrue({"code", "path", "message", "severity"} <= set(d))
            self.assertTrue(d["path"].startswith("/"))

    def test_cli_invalid_reports_no_traceback(self):
        bad = base()
        bad["views"][0]["placements"] = None
        temporary = tempfile.TemporaryDirectory(prefix="core-cli-test-")
        self.addCleanup(temporary.cleanup)
        tmp = Path(temporary.name) / "invalid.json"
        tmp.write_text(json.dumps(bad), encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "tools/run_core.py", "validate", str(tmp)],
                capture_output=True, text=True, cwd=ROOT,
            )
        finally:
            tmp.unlink(missing_ok=True)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertNotIn("Traceback", proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["valid"])
        self.assertIn("VIEW_SHAPE", [d["code"] for d in payload["issues"]])


if __name__ == "__main__":
    unittest.main()
