"""AP-CORE-001 P1 core tests (SDK/Qt-free). Spike tests stay untouched."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.errors import Diagnostic  # noqa: E402
from core.io import dump_project, load_raw, loads_project, project_from_dict, project_to_dict  # noqa: E402
from core.registry import load_manifests  # noqa: E402
from core.validate import validate_project  # noqa: E402


def _fixture() -> dict:
    return load_raw(ROOT / "examples" / "project_core_valid.json")


class TestCoreModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry, cls.reg_issues = load_manifests(ROOT / "component_types")
        # Registry manifests used by the shared fixture must be clean.
        assert cls.reg_issues == [], [i.as_dict() for i in cls.reg_issues]

    def codes(self, model: dict) -> list[str]:
        return [i.code for i in validate_project(model, self.registry)]

    def issues(self, model: dict) -> list[Diagnostic]:
        return validate_project(model, self.registry)

    def test_valid_neutral_example(self):
        model = _fixture()
        comps = {c["id"] for c in model["components"]}
        self.assertGreaterEqual(len(comps), 2)
        self.assertGreaterEqual(len(model["bindings"]), 2)
        kinds = {b["kind"] for b in model["bindings"]}
        self.assertIn("command", kinds)
        self.assertIn("state", kinds)
        self.assertEqual([], self.codes(model))

    def test_same_component_in_multiple_views(self):
        model = _fixture()
        self.assertEqual(
            model["views"][0]["placements"][0]["component"],
            model["views"][1]["placements"][0]["component"],
        )
        self.assertEqual([], self.codes(model))

    def test_duplicate_id_same_class(self):
        model = _fixture()
        model["components"].append(copy.deepcopy(model["components"][0]))
        self.assertIn("ID_DUPLICATE", self.codes(model))

    def test_same_id_across_classes_allowed(self):
        model = _fixture()
        model["states"].append(
            {
                "id": model["components"][0]["id"],
                "value_schema": {"type": "string"},
                "authority": {"role": "host"},
                "scope": "project",
                "persistence": "none",
            }
        )
        self.assertNotIn("ID_DUPLICATE", self.codes(model))

    def test_invalid_id_rule(self):
        model = _fixture()
        model["components"][0]["id"] = "Bad ID!"
        self.assertIn("ID_INVALID", self.codes(model))

    def test_missing_component_type(self):
        model = _fixture()
        model["components"][0]["type"] = "unknown.type"
        self.assertIn("TYPE_MISSING", self.codes(model))

    def test_missing_manifest_version(self):
        model = _fixture()
        model["components"][0]["version"] = "9.9.9"
        self.assertIn("TYPE_VERSION", self.codes(model))

    def test_missing_endpoint(self):
        model = _fixture()
        model["bindings"][0]["source"]["owner_id"] = "missing"
        self.assertIn("ENDPOINT_MISSING", self.codes(model))

    def test_wrong_port_direction(self):
        model = _fixture()
        model["bindings"][0]["source"], model["bindings"][0]["target"] = (
            model["bindings"][0]["target"],
            model["bindings"][0]["source"],
        )
        self.assertIn("PORT_DIRECTION", self.codes(model))

    def test_wrong_signal_kind(self):
        model = _fixture()
        model["bindings"][0]["kind"] = "event"
        self.assertIn("SIGNAL_MISMATCH", self.codes(model))

    def test_compatible_primitive_schema(self):
        # enum narrowing: source {a} -> target {a, b} is conservatively compatible.
        model = _fixture()
        model["presentations"][0]["variants"] = {
            "variant_0": {"text": "A"},
            "variant_1": {"text": "B"},
            "variant_2": {"text": "C"},
        }
        model["states"][0]["value_schema"] = {"type": "string", "enum": ["variant_0"]}
        codes = self.codes(model)
        self.assertNotIn("PAYLOAD_INCOMPATIBLE", codes)

    def test_incompatible_schema(self):
        model = _fixture()
        model["states"][0]["value_schema"] = {"type": "string", "enum": ["other"]}
        self.assertIn("PAYLOAD_INCOMPATIBLE", self.codes(model))

    def test_complex_schema_conservative_warning(self):
        model = _fixture()
        model["states"][0]["value_schema"] = {
            "type": "string",
            "allOf": [{"minLength": 1}],
        }
        model["states"][0]["fallback"] = "variant_0"
        codes = self.codes(model)
        self.assertIn("SCHEMA_UNSUPPORTED", codes)
        self.assertIn("SCHEMA_NOT_PROVEN", codes)
        # WARNING must not block validity on its own; here SCHEMA_UNSUPPORTED (ERROR) blocks.
        warns = [i for i in self.issues(model) if i.code == "SCHEMA_NOT_PROVEN"]
        self.assertTrue(warns and all(w.severity == "WARNING" for w in warns))

    def test_invalid_state_fallback(self):
        model = _fixture()
        model["states"][0]["fallback"] = "nope"
        self.assertIn("VALUE_ENUM", self.codes(model))

    def test_authority_missing_component(self):
        model = _fixture()
        model["states"][0]["authority"] = {"role": "component", "component": "missing"}
        self.assertIn("AUTHORITY_MISSING", self.codes(model))

    def test_authority_invalid_role(self):
        model = _fixture()
        model["states"][0]["authority"] = {"role": "everyone"}
        self.assertIn("AUTHORITY_INVALID", self.codes(model))

    def test_position_collision_same_view(self):
        model = _fixture()
        dup = copy.deepcopy(model["views"][0]["placements"][0])
        dup["id"] = "placement.other"
        model["views"][0]["placements"].append(dup)
        self.assertIn("POSITION_COLLISION", self.codes(model))

    def test_same_position_across_views_allowed(self):
        model = _fixture()
        pos_a = model["views"][0]["placements"][0]["position"]
        pos_b = model["views"][1]["placements"][0]["position"]
        self.assertEqual(pos_a, pos_b)
        self.assertNotIn("POSITION_COLLISION", self.codes(model))

    def test_unknown_project_field_preserved(self):
        model = _fixture()
        model["future_field"] = {"note": "must not be dropped"}
        codes = self.codes(model)
        self.assertIn("FIELD_UNKNOWN", codes)
        project = project_from_dict(model)
        round_tripped = project_to_dict(project)
        self.assertEqual({"note": "must not be dropped"}, round_tripped["future_field"])

    def test_load_dump_reload_equivalent(self):
        model = _fixture()
        first = dump_project(project_from_dict(model))
        second = dump_project(loads_project(first))
        self.assertEqual(first, second)
        self.assertEqual(model, json.loads(first))

    def test_errors_deterministic_order(self):
        model = _fixture()
        model["components"].append(copy.deepcopy(model["components"][0]))
        model["bindings"][0]["kind"] = "event"
        once = [(i.path, i.code, i.message) for i in self.issues(model)]
        twice = [(i.path, i.code, i.message) for i in self.issues(model)]
        self.assertEqual(once, twice)
        self.assertEqual(once, sorted(once))

    def test_diagnostic_shape(self):
        model = _fixture()
        model["components"][0]["type"] = "unknown.type"
        for issue in self.issues(model):
            d = issue.as_dict()
            self.assertIn("code", d)
            self.assertIn("path", d)
            self.assertIn("message", d)
            self.assertTrue(d["path"].startswith("/"))

    def test_endpoint_must_be_structured(self):
        model = _fixture()
        model["bindings"][0]["source"] = "component:action.primary/activated"
        self.assertIn("ENDPOINT_SHAPE", self.codes(model))


if __name__ == "__main__":
    unittest.main()
