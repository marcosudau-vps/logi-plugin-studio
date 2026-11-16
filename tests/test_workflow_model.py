"""Qt-freie Tests des geführten Ablaufs: Fakten → Schrittstatus, benutzerlokaler Speicher."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from studio.workflow import (DONE, ERROR, INFO, LOCKED, OPEN, STALE, WARNING, STEPS, STEP_KEYS, Facts, complete,
                             evaluate, first_incomplete, guidance, step)
from studio.workflow.store import WorkflowStore

READY = Facts(has_project=True, project_saved=True, plugin_id="demo.plugin", display_name="Demo",
              handlers=("handler.main",), handler_file="handlers.py", actions=2)
BUILT = replace(READY, build_done=True, build_current=True, package_valid=True)
LIVE = replace(BUILT, installed=True, loaded=True, connected=True, install_current=True, hardware_confirmed=True)


def status(facts):
    return {s.step.key: s.status for s in evaluate(facts)}


def criterion(facts, key):
    return next(c for s in evaluate(facts) for c in s.criteria if c.key == key)


class WorkflowModelTests(unittest.TestCase):
    def test_seven_steps_in_fixed_order(self):
        self.assertEqual(STEP_KEYS, ("project", "handlers", "actions", "symbols", "layout", "build", "install"))
        self.assertEqual([s.number for s in STEPS], list(range(1, 8)))
        self.assertEqual([s.key for s in STEPS if s.optional], ["symbols", "layout"])
        self.assertEqual(step("build").title, "Prüfen und Bauen")
        self.assertRaises(KeyError, step, "unknown")

    def test_without_project_only_first_step_is_reachable(self):
        states = evaluate(Facts())
        self.assertEqual(states[0].status, OPEN)
        self.assertTrue(states[0].reachable)
        self.assertTrue(all(s.status == LOCKED and not s.reachable for s in states[1:]))
        self.assertEqual(first_incomplete(states), "project")

    def test_handler_step_requires_handler_and_file(self):
        facts = Facts(has_project=True, project_saved=True, plugin_id="a.b", display_name="A")
        self.assertEqual(status(facts)["handlers"], OPEN)
        self.assertEqual(status(facts)["actions"], LOCKED)
        with_handler = replace(facts, handlers=("handler.main",))
        self.assertEqual(criterion(with_handler, "handlers.file").status, OPEN)
        broken = replace(with_handler, handler_file="x.py", handler_file_error="Datei fehlt")
        self.assertEqual(status(broken)["handlers"], ERROR)
        self.assertEqual(status(replace(with_handler, handler_file="x.py"))["handlers"], DONE)

    def test_unregistered_handler_is_a_warning_and_does_not_block(self):
        facts = replace(READY, handlers_unregistered=("handler.extra",))
        states = evaluate(facts)
        self.assertEqual(states[1].status, WARNING)
        self.assertTrue(complete(states[1]))
        self.assertTrue(states[2].reachable)
        self.assertIn("handler.extra", criterion(facts, "handlers.registered").detail)

    def test_action_step_blocks_on_draft_and_missing_handler(self):
        self.assertEqual(status(READY)["actions"], DONE)
        self.assertEqual(status(replace(READY, draft_open=True))["actions"], OPEN)
        self.assertEqual(status(replace(READY, actions_without_handler=("action.x",)))["actions"], ERROR)
        self.assertEqual(status(replace(READY, actions=0))["actions"], OPEN)

    def test_optional_steps_never_block_without_content(self):
        states = {s.step.key: s for s in evaluate(READY)}
        self.assertEqual(states["symbols"].status, INFO)
        self.assertEqual(states["layout"].status, INFO)
        self.assertTrue(states["build"].reachable)
        self.assertEqual(status(replace(READY, missing_assets=("a.png",)))["symbols"], WARNING)
        self.assertEqual(status(replace(READY, actions_with_symbol=1))["symbols"], DONE)

    def test_layout_blocks_on_orphans_and_unsaved_extension(self):
        self.assertEqual(status(replace(READY, orphan_placements=("p1",)))["layout"], ERROR)
        unsaved = replace(READY, placements=2, extension_saved=False)
        self.assertEqual(status(unsaved)["layout"], OPEN)
        self.assertEqual(status(unsaved)["build"], LOCKED)
        self.assertEqual(status(replace(READY, placements=2))["layout"], DONE)

    def test_build_requires_saved_state_no_errors_and_prerequisites(self):
        self.assertEqual(criterion(replace(READY, project_saved=False), "build.saved").status, OPEN)
        self.assertEqual(criterion(replace(READY, problem_errors=3), "build.errors").status, ERROR)
        missing = replace(READY, prerequisites=(".NET SDK fehlt.",))
        self.assertEqual(criterion(missing, "build.prerequisites").status, ERROR)
        self.assertEqual(criterion(READY, "build.done").status, OPEN)
        self.assertEqual(criterion(replace(READY, build_error="CS1002"), "build.done").status, ERROR)
        self.assertEqual(status(BUILT)["build"], DONE)

    def test_later_change_marks_build_and_installation_stale(self):
        changed = replace(LIVE, build_current=False, install_current=False)
        self.assertEqual(status(changed)["build"], STALE)
        self.assertEqual(status(changed)["install"], LOCKED)
        rebuilt = replace(LIVE, install_current=False)
        self.assertEqual(criterion(rebuilt, "install.installed").status, STALE)
        self.assertEqual(status(rebuilt)["install"], STALE)

    def test_install_step_needs_confirmed_device_test(self):
        self.assertEqual(status(BUILT)["install"], OPEN)
        almost = replace(LIVE, hardware_confirmed=False)
        self.assertEqual(criterion(almost, "install.hardware").status, OPEN)
        self.assertEqual(status(LIVE)["install"], DONE)
        self.assertTrue(all(complete(s) for s in evaluate(LIVE)))
        self.assertIn("Fertig", guidance(evaluate(LIVE)[-1]))

    def test_guidance_names_the_first_blocking_criterion(self):
        states = evaluate(replace(READY, draft_open=True))
        self.assertIn("Übernehmen", guidance(states[2]))
        self.assertIn("vorherigen", guidance(states[5]))
        self.assertIn("Weiter", guidance(evaluate(READY)[2]))

    def test_every_criterion_has_text_and_known_target(self):
        tabs = {v for s in STEPS for v in s.views}
        for facts in (Facts(), READY, BUILT, LIVE, replace(READY, orphan_placements=("p",), missing_assets=("m",))):
            for state in evaluate(facts):
                for item in state.criteria:
                    self.assertTrue(item.text.strip())
                    self.assertTrue(item.target in tabs or item.target.startswith("do:"), item)


class WorkflowStoreTests(unittest.TestCase):
    def test_defaults_roundtrip_and_isolation_by_plugin_id(self):
        with tempfile.TemporaryDirectory() as temp:
            store = WorkflowStore(temp)
            self.assertTrue(store.guided())
            self.assertEqual(store.project("p", "a.b"), {})
            self.assertTrue(store.remember("p", "a.b", step="actions", handler_file="handlers.py"))
            self.assertTrue(store.remember("p", "a.b", hardware="abc"))
            self.assertEqual(WorkflowStore(temp).project("p", "a.b"),
                             {"step": "actions", "handler_file": "handlers.py", "hardware": "abc"})
            self.assertEqual(store.project("p", "other.plugin"), {})
            self.assertTrue(store.set_guided(False))
            self.assertFalse(WorkflowStore(temp).guided())
            self.assertEqual(WorkflowStore(temp).project("p", "a.b")["step"], "actions")

    def test_rejects_unknown_fields_and_survives_damaged_file(self):
        with tempfile.TemporaryDirectory() as temp:
            store = WorkflowStore(temp)
            self.assertFalse(store.remember("p", "a.b", secret="x"))
            self.assertFalse(store.remember("p", "a.b", step=3))
            self.assertFalse(store.remember("", "a.b", step="build"))
            Path(temp, "workflow.json").write_text("{kaputt", encoding="utf-8")
            self.assertTrue(store.guided())
            self.assertEqual(store.project("p", "a.b"), {})
            self.assertIsNotNone(store.last_error)
            Path(temp, "workflow.json").write_text(json.dumps({"format": "fremd"}), encoding="utf-8")
            self.assertTrue(store.guided())
            self.assertTrue(store.remember("p", "a.b", step="build"))
            self.assertEqual(store.project("p", "a.b"), {"step": "build"})


if __name__ == "__main__":
    unittest.main()
