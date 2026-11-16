"""Regression tests for independent review of RUN-AP-CORE-001-01 (F01-F05).

Each test fails on the RUN-01 implementation and passes after the RUN-02 fixes.
Stdlib only (jsonschema usage is optional and skipped when unavailable).
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

from core.compat import payload_compatibility  # noqa: E402
from core.io import dump_project, load_raw, project_from_dict, project_to_dict  # noqa: E402
from core.registry import TypeRegistry, load_manifests  # noqa: E402
from core.validate import validate_project  # noqa: E402

SCHEMA = ROOT / "schemas" / "project_v0_1_core.schema.json"


def fixture() -> dict:
    return load_raw(ROOT / "examples" / "project_core_valid.json")


def fresh_registry() -> TypeRegistry:
    reg, issues = load_manifests(ROOT / "component_types")
    assert issues == [], [i.as_dict() for i in issues]
    return reg


class TestSchemaFile(unittest.TestCase):
    def test_schema_parses_as_json(self):
        data = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(data["title"].split("–")[0].strip(), "Logi Plugin Studio Project")

    def test_schema_meta_valid_draft2020_12(self):
        jsonschema = unittest.skipUnless
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema not installed")
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)

    def test_valid_example_satisfies_schema(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema not installed")
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(fixture())

    def test_mutated_example_fails_schema(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema not installed")
        import jsonschema as _js

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        bad = fixture()
        bad["views"][0]["placements"] = "bad"
        with self.assertRaises(_js.ValidationError):
            Draft202012Validator(schema).validate(bad)


class TestNoCrash(unittest.TestCase):
    """F02: malformed inputs must yield diagnostics, never tracebacks."""

    @classmethod
    def setUpClass(cls):
        cls.reg = fresh_registry()

    def codes(self, model) -> list[str]:
        return [i.code for i in validate_project(model, self.reg)]

    def assert_invalid(self, model, *expected_codes: str):
        codes = self.codes(model)
        for code in expected_codes:
            self.assertIn(code, codes, f"expected {code} in {codes}")
        self.assertTrue(
            any(i.severity == "ERROR" for i in validate_project(model, self.reg)),
            "must be invalid (at least one ERROR)",
        )

    def test_list_component_type(self):
        m = fixture()
        m["components"][0]["type"] = []
        self.assert_invalid(m, "TYPE_SHAPE")

    def test_list_component_version(self):
        m = fixture()
        m["components"][0]["version"] = []
        self.assert_invalid(m, "TYPE_SHAPE")

    def test_list_owner_kind(self):
        m = fixture()
        m["bindings"][0]["source"]["owner_kind"] = []
        self.assert_invalid(m, "ENDPOINT_SHAPE")

    def test_list_owner_id(self):
        m = fixture()
        m["bindings"][0]["source"]["owner_id"] = []
        self.assert_invalid(m, "ENDPOINT_SHAPE")

    def test_bad_minlength_constraint(self):
        m = fixture()
        m["states"][0]["value_schema"] = {"type": "string", "minLength": "bad"}
        self.assert_invalid(m, "SCHEMA_INVALID")

    def test_list_authority_component(self):
        m = fixture()
        m["states"][0]["authority"] = {"role": "component", "component": []}
        self.assert_invalid(m, "AUTHORITY_MISSING")

    def test_list_placement_component(self):
        m = fixture()
        m["views"][0]["placements"][0]["component"] = []
        self.assert_invalid(m, "PLACEMENT_COMPONENT")


class TestLosslessIO(unittest.TestCase):
    """F03: invalid input is rejected AND preserved — never silently normalised."""

    @classmethod
    def setUpClass(cls):
        cls.reg = fresh_registry()

    def assert_lossless(self, model: dict) -> None:
        self.assertEqual(project_to_dict(project_from_dict(model)), model)

    def test_unknown_project_metadata_flagged_and_kept(self):
        m = fixture()
        m["project"]["future_metadata"] = {"value": 1}
        codes = [i.code for i in validate_project(m, self.reg)]
        self.assertIn("FIELD_UNKNOWN", codes)
        self.assert_lossless(m)

    def test_endpoint_extra_key_flagged_and_kept(self):
        m = fixture()
        m["bindings"][0]["source"]["future_key"] = 1
        codes = [i.code for i in validate_project(m, self.reg)]
        self.assertIn("ENDPOINT_SHAPE", codes)
        self.assert_lossless(m)

    def test_placements_string_flagged_and_kept(self):
        m = fixture()
        m["views"][0]["placements"] = "bad"
        codes = [i.code for i in validate_project(m, self.reg)]
        self.assertIn("VIEW_SHAPE", codes)
        self.assert_lossless(m)

    def test_nondict_items_flagged_and_kept(self):
        m = fixture()
        m["components"].insert(0, "bad")
        m["views"].append(42)
        codes = [i.code for i in validate_project(m, self.reg)]
        self.assertIn("OBJECT_SHAPE", codes)
        self.assert_lossless(m)
        # Raw indices must be used: the real first component is now at index 1.
        paths = [(i.code, i.path) for i in validate_project(m, self.reg)]
        self.assertIn(("OBJECT_SHAPE", "/components/0"), paths)

    def test_array_config_flagged_and_kept(self):
        m = fixture()
        m["components"][0]["config"] = []
        codes = [i.code for i in validate_project(m, self.reg)]
        self.assertIn("CONFIG_INVALID", codes)
        self.assert_lossless(m)

    def test_missing_required_keys_flagged(self):
        m = fixture()
        del m["components"][0]["config"]
        del m["states"][0]["value_schema"]
        codes = [i.code for i in validate_project(m, self.reg)]
        self.assertIn("FIELD_REQUIRED", codes)

    def test_invalid_project_never_repaired(self):
        m = fixture()
        m["views"][0]["placements"] = "bad"
        m["components"][0]["type"] = []
        m["project"]["future_metadata"] = 1
        self.assert_lossless(m)
        self.assertTrue(any(i.severity == "ERROR" for i in validate_project(m, self.reg)))


class TestConservativeCompat(unittest.TestCase):
    """F04: no unproven compatibility claims."""

    def test_equal_schemas(self):
        s = {"type": "string", "enum": ["a"]}
        self.assertEqual(payload_compatibility(s, copy.deepcopy(s)), "equal")

    def test_enum_narrowing_compatible(self):
        src = {"type": "string", "enum": ["a"]}
        dst = {"type": "string", "enum": ["a", "b"]}
        self.assertEqual(payload_compatibility(src, dst), "compatible")

    def test_enum_with_tighter_target_is_unknown(self):
        src = {"type": "string", "enum": ["abcd"]}
        dst = {"type": "string", "enum": ["abcd"], "maxLength": 1}
        self.assertEqual(payload_compatibility(src, dst), "unknown")

    def test_disjoint_enums_incompatible(self):
        src = {"type": "string", "enum": ["a"]}
        dst = {"type": "string", "enum": ["b"]}
        self.assertEqual(payload_compatibility(src, dst), "incompatible")

    def test_minlength_tightening_is_unknown(self):
        src = {"type": "string"}
        dst = {"type": "string", "minLength": 3}
        self.assertEqual(payload_compatibility(src, dst), "unknown")

    def test_malformed_constraint_is_unknown(self):
        src = {"type": "string", "minLength": "bad"}
        dst = {"type": "string"}
        self.assertEqual(payload_compatibility(src, dst), "unknown")

    def test_validator_reports_not_proven_warning(self):
        reg = TypeRegistry()
        reg.add_manifest(
            {
                "type_id": "t.src",
                "version": "1.0.0",
                "config_schema": {"type": "object"},
                "ports": [
                    {
                        "id": "out",
                        "direction": "out",
                        "kind": "state",
                        "payload_schema": {"type": "string", "enum": ["abcd"]},
                    }
                ],
            },
            origin="test",
        )
        reg.add_manifest(
            {
                "type_id": "t.dst",
                "version": "1.0.0",
                "config_schema": {"type": "object"},
                "ports": [
                    {
                        "id": "in",
                        "direction": "in",
                        "kind": "state",
                        "payload_schema": {"type": "string", "enum": ["abcd"], "maxLength": 1},
                    }
                ],
            },
            origin="test",
        )
        self.assertEqual(reg.issues, [])
        m = {
            "schema_version": "0.1-draft",
            "project": {"id": "t.case", "display_name": "T"},
            "dependencies": [],
            "components": [
                {"id": "c.src", "type": "t.src", "version": "1.0.0", "config": {}},
                {"id": "c.dst", "type": "t.dst", "version": "1.0.0", "config": {}},
            ],
            "states": [],
            "bindings": [
                {
                    "id": "b.link",
                    "source": {"owner_kind": "component", "owner_id": "c.src", "port": "out"},
                    "target": {"owner_kind": "component", "owner_id": "c.dst", "port": "in"},
                    "kind": "state",
                }
            ],
            "presentations": [],
            "assets": [],
            "views": [],
        }
        issues = validate_project(m, reg)
        warns = [i for i in issues if i.code == "SCHEMA_NOT_PROVEN"]
        self.assertTrue(warns and all(w.severity == "WARNING" for w in warns))
        self.assertNotIn("PAYLOAD_INCOMPATIBLE", [i.code for i in issues])


class TestNestedShapes(unittest.TestCase):
    """F05: nested structural validation with true JSON indices."""

    @classmethod
    def setUpClass(cls):
        cls.reg = fresh_registry()

    def codes(self, model) -> list[str]:
        return [i.code for i in validate_project(model, self.reg)]

    def test_project_must_be_object(self):
        m = fixture()
        m["project"] = "bad"
        self.assertIn("PROJECT_SHAPE", self.codes(m))
        self.assertEqual(project_to_dict(project_from_dict(m)), m)

    def test_dependency_item_must_be_object(self):
        m = fixture()
        m["dependencies"].append("bad")
        self.assertIn("OBJECT_SHAPE", self.codes(m))
        self.assertEqual(project_to_dict(project_from_dict(m)), m)

    def test_variants_must_be_object(self):
        m = fixture()
        m["presentations"][0]["variants"] = []
        self.assertIn("PRESENTATION_SHAPE", self.codes(m))
        self.assertEqual(project_to_dict(project_from_dict(m)), m)

    def test_asset_path_must_be_string(self):
        m = fixture()
        m["assets"].append({"id": "a.extra", "path": []})
        codes = self.codes(m)
        self.assertIn("ASSET_PATH", codes)

    def test_missing_placements_key(self):
        m = fixture()
        del m["views"][0]["placements"]
        self.assertIn("VIEW_SHAPE", self.codes(m))
        self.assertEqual(project_to_dict(project_from_dict(m)), m)

    def test_deterministic_valid_roundtrip(self):
        m = fixture()
        first = dump_project(project_from_dict(m))
        self.assertEqual(first, dump_project(project_from_dict(json.loads(first))))
        issues = validate_project(m, self.reg)
        keys = [(i.path, i.code, i.message) for i in issues]
        self.assertEqual(keys, sorted(keys))


class TestCliBehaviour(unittest.TestCase):
    def test_cli_rejects_malformed_without_traceback(self):
        bad = fixture()
        bad["components"][0]["type"] = []
        temporary = tempfile.TemporaryDirectory(prefix="core-cli-test-")
        self.addCleanup(temporary.cleanup)
        tmp = Path(temporary.name) / "invalid.json"
        tmp.write_text(json.dumps(bad), encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "tools/run_core.py", "validate", str(tmp)],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
        finally:
            tmp.unlink(missing_ok=True)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertNotIn("Traceback", proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["valid"])
        self.assertTrue(all({"code", "path", "message"} <= set(d) for d in payload["issues"]))


if __name__ == "__main__":
    unittest.main()
