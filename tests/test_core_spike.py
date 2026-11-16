from __future__ import annotations
import copy
import json
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core_spike.model import dump_project, load_manifests, load_project, validate_project



class TestCoreSpike(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_project(ROOT / "examples" / "project_v0_1_draft.json")
        cls.manifests = load_manifests(ROOT / "component_types")

    def errors(self, model):
        return [x.code for x in validate_project(model, self.manifests)]

    def test_valid_generic_project(self):
        self.assertEqual([], self.errors(self.model))

    def test_roundtrip_is_deterministic(self):
        a = dump_project(self.model)
        self.assertEqual(a, dump_project(json.loads(a)))
        self.assertEqual(self.model, json.loads(a))

    def test_same_component_in_multiple_placements(self):
        self.assertEqual(self.model["views"][0]["placements"][0]["component"], self.model["views"][1]["placements"][0]["component"])
        self.assertEqual([], self.errors(self.model))

    def test_missing_component_type(self):
        m=copy.deepcopy(self.model); m["components"][0]["type"] = "unknown.type"
        self.assertIn("TYPE_MISSING", self.errors(m))

    def test_missing_endpoint(self):
        m=copy.deepcopy(self.model); m["bindings"][0]["source"]["owner_id"] = "missing"
        self.assertIn("ENDPOINT_MISSING", self.errors(m))

    def test_wrong_port_direction(self):
        m=copy.deepcopy(self.model); m["bindings"][0]["source"],m["bindings"][0]["target"] = m["bindings"][0]["target"],m["bindings"][0]["source"]
        self.assertIn("PORT_DIRECTION", self.errors(m))

    def test_signal_mismatch(self):
        m=copy.deepcopy(self.model); m["bindings"][0]["kind"] = "event"
        self.assertIn("SIGNAL_MISMATCH", self.errors(m))

    def test_invalid_default_value(self):
        m=copy.deepcopy(self.model); m["states"][0]["fallback"] = "nope"
        self.assertIn("VALUE_ENUM", self.errors(m))

    def test_duplicate_ids(self):
        m=copy.deepcopy(self.model); m["components"].append(copy.deepcopy(m["components"][0]))
        self.assertIn("ID_DUPLICATE", self.errors(m))

    def test_position_collision(self):
        m=copy.deepcopy(self.model); pl=copy.deepcopy(m["views"][0]["placements"][0]); pl["id"]="placement.other";m["views"][0]["placements"].append(pl)
        self.assertIn("POSITION_COLLISION", self.errors(m))

    def test_unknown_presentation(self):
        m=copy.deepcopy(self.model);m["views"][0]["placements"][0]["presentation"] = "nope"
        self.assertIn("PLACEMENT_PRESENTATION", self.errors(m))

    def test_payload_schema_mismatch(self):
        m=copy.deepcopy(self.model);m["presentations"][0]["variants"]["variant_2"]={"text":"C"}
        self.assertIn("SCHEMA_NOT_PROVEN", self.errors(m))

    def test_unsupported_schema_fails_closed(self):
        m=copy.deepcopy(self.model);m["states"][0]["value_schema"]["pattern"]="^a"
        self.assertIn("SCHEMA_UNSUPPORTED", self.errors(m))

    def test_bool_not_integer(self):
        m=copy.deepcopy(self.model);m["views"][0]["placements"][0]["position"]=True
        self.assertIn("PLACEMENT_POSITION", self.errors(m))


if __name__ == "__main__":
    unittest.main()
