from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from core.io import load_raw
from library.document import DocumentError, ProjectDocument, empty_project


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.document = ProjectDocument(load_raw(ROOT / "examples" / "project_v0_1_draft.json"))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "project.json"

    def test_new_project_valid_and_atomic_save_round_trip(self):
        document = ProjectDocument(empty_project())
        self.assertFalse(document.diagnostics())
        document.save(self.path)
        loaded = ProjectDocument()
        loaded.load(self.path)
        self.assertEqual(document.raw, loaded.raw)
        self.assertFalse(loaded.dirty)
        self.assertEqual([], list(self.path.parent.glob(".studio-save-*")))

    def test_component_rename_is_atomic_referential_and_undoable(self):
        before = self.document.raw
        action = before["components"][0].copy()
        action["id"] = "action.renamed"
        self.document.replace_entity("components", "action.primary", action)
        after = self.document.raw
        self.assertEqual(after["bindings"][0]["source"]["owner_id"], "action.renamed")
        self.assertTrue(all(v["placements"][0]["component"] == "action.renamed" for v in after["views"]))
        self.assertFalse(self.document.diagnostics())
        self.assertTrue(self.document.dirty)
        self.document.undo()
        self.assertEqual(self.document.raw, before)
        self.document.redo()
        self.assertEqual(self.document.raw, after)

    def test_referenced_deletion_is_blocked_without_mutation(self):
        before = self.document.raw
        with self.assertRaisesRegex(DocumentError, "referenced"):
            self.document.remove("components", "action.primary")
        self.assertEqual(before, self.document.raw)

    def test_duplicate_view_gives_placements_unique_ids(self):
        self.document.duplicate("views", "view.main")
        ids = [p["id"] for v in self.document.raw["views"] for p in v["placements"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(self.document.diagnostics())

    def test_disk_conflict_and_foreign_overwrite_preserve_files(self):
        self.document.save(self.path)
        self.path.write_text('{"foreign":true}', encoding="utf-8")
        with self.assertRaisesRegex(DocumentError, "changed on disk"):
            self.document.save()
        self.assertEqual(self.path.read_text(), '{"foreign":true}')
        other = self.path.parent / "foreign.json"
        other.write_text("unrelated")
        with self.assertRaises(DocumentError):
            self.document.save(other)
        self.assertEqual(other.read_text(), "unrelated")

    def test_unknown_fields_survive_edit_and_save(self):
        raw = self.document.raw
        raw["future"] = {"something": 42}
        self.document.replace_raw(raw)
        action = self.document.raw["components"][0]
        action["config"]["display_name"] = "Renamed label"
        self.document.replace_entity("components", action["id"], action)
        self.document.save(self.path)
        self.assertEqual(load_raw(self.path)["future"], {"something": 42})
        self.assertTrue(any(d.code == "FIELD_UNKNOWN" for d in self.document.diagnostics()))

    def test_invalid_json_duplicate_ids_and_id_collision_do_not_mutate(self):
        self.path.write_text('{"a":1,"a":2}', encoding="utf-8")
        before = self.document.raw
        with self.assertRaises(DocumentError):
            self.document.load(self.path)
        self.assertEqual(before, self.document.raw)
        entity = before["components"][0]
        entity["id"] = "handler.primary"
        with self.assertRaises(DocumentError):
            self.document.replace_entity("components", "action.primary", entity)
        before = self.document.raw
        with self.assertRaises(DocumentError):
            self.document.add("components", {"id": "action.incomplete"})
        self.assertEqual(before, self.document.raw)
        self.document.replace_raw({**before, "dependencies": None})
        broken = self.document.raw
        with self.assertRaises(DocumentError):
            self.document.add("components", {"id": "action.new", "type": "core.command_action", "version": "1.0.0", "config": {}})
        with self.assertRaises(DocumentError):
            self.document.duplicate("views", "view.main")
        self.assertEqual(broken, self.document.raw)

    def test_asset_and_presentation_reference_rename(self):
        raw = self.document.raw
        raw["assets"] = [{"id": "asset.one", "path": "assets/one.png"}]
        raw["presentations"][0]["variants"]["variant_0"]["image"] = "asset.one"
        self.document.replace_raw(raw)
        self.document.replace_entity("assets", "asset.one", {"id": "asset.two", "path": "assets/one.png"})
        self.assertEqual(self.document.raw["presentations"][0]["variants"]["variant_0"]["image"], "asset.two")
        presentation = self.document.raw["presentations"][0]
        presentation["id"] = "visual.changed"
        self.document.replace_entity("presentations", "visual.primary", presentation)
        self.assertEqual(self.document.raw["bindings"][1]["target"]["owner_id"], "visual.changed")
        self.assertEqual(self.document.raw["views"][0]["placements"][0]["presentation"], "visual.changed")


if __name__ == "__main__":
    unittest.main()
