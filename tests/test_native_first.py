from __future__ import annotations

import copy
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adapters.logitech.codegen import DEFAULT_SDK_DLL
from adapters.logitech.native import NativeProjectError, parse_native_project, project_view, runtime_projection
from adapters.logitech.product import build_product, generate_product
from runtime.host import PluginHost
from runtime.wire import ConnectionSettings, LocalClient, project_digest


def native_sample() -> dict:
    return json.loads((ROOT / "examples" / "project_logitech_native_v1.json").read_text(encoding="utf-8"))


class NativeProjectTests(unittest.TestCase):
    def test_native_contract_and_runtime_projection(self):
        native = parse_native_project(native_sample())
        self.assertEqual([a.sdk_type for a in native.actions], [
            "PluginDynamicCommand", "PluginMultistateDynamicCommand",
            "PluginDynamicAdjustment", "ActionEditorCommand"])
        self.assertEqual([s.index for s in native.actions[1].states], [0, 1])
        projected = runtime_projection(native_sample())
        self.assertEqual(projected["schema_version"], "0.1-draft")
        self.assertEqual(len(projected["components"]), 5)
        self.assertEqual(len(projected["bindings"]), 4)
        self.assertEqual(projected["views"][0]["placements"][0]["id"], "placement.command")

    def test_legacy_project_remains_native_accessible_and_lossless(self):
        raw = json.loads((ROOT / "examples" / "project_v0_1_draft.json").read_text(encoding="utf-8"))
        view = project_view(raw)
        self.assertTrue(view.actions[0].legacy)
        self.assertEqual(view.actions[0].sdk_type, "PluginDynamicCommand")
        self.assertEqual(runtime_projection(raw), raw)

    def test_fixed_state_indices_toggle_count_and_installed_led_gap(self):
        for mutate, message in (
            (lambda r: r["actions"][1]["states"][1].update(index=3), "fixed, contiguous"),
            (lambda r: r["actions"][1]["states"].append({"index": 2, "name": "third", "display_name": "Third", "description": ""}), "exactly two"),
            (lambda r: r["actions"][1]["states"][0].update(led_color="#ff0000"), "no LED property"),
        ):
            raw = native_sample()
            mutate(raw)
            with self.assertRaisesRegex(NativeProjectError, message):
                parse_native_project(raw)


class NativeEditorControlValidationTests(unittest.TestCase):
    def test_invalid_numeric_bounds_and_wrong_control_options_fail(self):
        original = native_sample()
        for editor, message in (
            ({"type": "slider", "name": "Level", "label": "Level",
              "minimum": 20, "maximum": 10, "default": 15, "step": 1}, "inconsistent"),
            ({"type": "numeric_up_down", "name": "Count", "label": "Count",
              "minimum": 0, "maximum": 10, "default": 2, "step": 0}, "inconsistent"),
            ({"type": "textarea", "name": "Notes", "label": "Notes", "step": 1}, "not applicable"),
            ({"type": "directory_selector", "name": "Dir", "label": "Dir", "filters": []}, "requires"),
        ):
            raw = copy.deepcopy(original)
            raw["actions"][3]["editor_controls"].append(editor)
            with self.subTest(editor=editor["type"]):
                with self.assertRaisesRegex(NativeProjectError, message):
                    parse_native_project(raw)


class NativeWireTests(unittest.TestCase):
    def setUp(self):
        self.raw = native_sample()
        self.settings = ConnectionSettings(self.raw["plugin"]["id"], project_digest(self.raw), 0, "11" * 32)
        self.host = PluginHost(self.raw, self.settings)
        self.seen = []
        self.host.register_handler("handler.main", "invoke", self._handler)
        self.host.start()
        self.addCleanup(self.host.close)
        self.client = LocalClient(self.host.settings)
        self.client.handshake()

    def _handler(self, payload, context):
        self.seen.append((context.action_parameter, context.placement_id, context.operation,
                          context.adjustment_diff, context.editor_values))
        return {"ok": True}

    def _wait(self):
        end = time.monotonic() + 3
        while time.monotonic() < end and not self.seen:
            time.sleep(0.01)
        self.assertTrue(self.seen)

    def test_action_parameter_is_not_placement_and_empty_is_preserved(self):
        self.client.command("action.command", placement_id="placement.command", action_parameter="")
        self._wait()
        self.assertEqual(self.seen[-1][:3], ("", "placement.command", "command"))

    def test_old_client_without_native_fields_remains_accepted(self):
        response = self.client.scoped_request("/v1/command", {
            "command_id": "a" * 32, "component_id": "action.command",
            "placement_id": None, "payload": {},
        })
        self.assertEqual(response["status"], "QUEUED")
        self._wait()
        self.assertEqual(self.seen[-1][:3], (None, None, "command"))

    def test_adjustment_and_editor_context_are_explicit(self):
        self.client.command("action.adjustment", action_parameter="fine", operation="adjustment", adjustment_diff=-2)
        self._wait()
        self.assertEqual(self.seen[-1], ("fine", None, "adjustment", -2, None))
        self.seen.clear()
        self.client.command("action.editor", operation="action_editor", editor_values={"Text": "hello", "Enabled": True})
        self._wait()
        self.assertEqual(self.seen[-1][2:], ("action_editor", None, {"Text": "hello", "Enabled": True}))


@unittest.skipUnless(DEFAULT_SDK_DLL.is_file(), "Real installed SDK required")
class NativeSdkBuildTests(unittest.TestCase):
    def test_all_native_action_types_resources_and_sdk_build(self):
        with tempfile.TemporaryDirectory(prefix="native-first-") as temp:
            root = Path(temp)
            (root / "icon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0h10v10z"/></svg>', encoding="utf-8")
            (root / "state.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>', encoding="utf-8")
            (root / "action.ict").write_text('{"backgroundColor":4278190080,"items":[]}', encoding="utf-8")
            (root / "LICENSE.txt").write_text("test fixture license\n", encoding="utf-8")
            raw = native_sample()
            raw["plugin"]["default_icon_template"] = "action.ict"
            raw["licenses"] = ["LICENSE.txt"]
            raw["actions"][0].update(icon="icon.svg", icon_template="action.ict", symbol="icon.svg",
                                     parameter_symbols={"first": "icon.svg"})
            raw["actions"][1]["states"][0]["image"] = "state.svg"
            raw["actions"][3]["editor_controls"].extend([
                {"type": "textarea", "name": "Notes", "label": "Notes"},
                {"type": "file_selector", "name": "File", "label": "File",
                 "dialog_title": "Choose file",
                 "filters": [{"pattern": "*.png", "label": "PNG"}]},
                {"type": "directory_selector", "name": "Directory", "label": "Directory"},
                {"type": "slider", "name": "Level", "label": "Level",
                 "minimum": 0, "maximum": 10, "default": 2.5, "step": 0.5},
                {"type": "numeric_up_down", "name": "Count", "label": "Count",
                 "minimum": 0, "maximum": 100, "default": 20, "step": 1},
            ])
            project = root / "project.json"
            project.write_text(json.dumps(raw), encoding="utf-8")
            output = root / "build"
            plan = generate_product(project, output_dir=output, assembly_name="NativeFirstProbe")
            sources = "\n".join(v for k, v in plan.files.items() if k.endswith(".cs") and isinstance(v, str))
            self.assertIn(": PluginMultistateDynamicCommand", sources)
            self.assertIn("this.AddState(\"off\"", sources)
            self.assertIn(": PluginDynamicAdjustment", sources)
            self.assertIn(": ActionEditorCommand", sources)
            for control in ("ActionEditorTextArea", "ActionEditorFileSelector",
                            "ActionEditorDirectorySelector", "ActionEditorSlider",
                            "ActionEditorNumericUpDown"):
                self.assertIn("new " + control, sources)
            self.assertIn('actionParameters.GetString("Level")', sources)
            self.assertIn("actionParameter: actionParameter", sources)
            self.assertTrue(any(k.startswith("icontemplates/") for k in plan.files))
            self.assertTrue(any(k.startswith("actionsymbols/") for k in plan.files))
            self.assertTrue(any(k.startswith("actionicons/") for k in plan.files))
            self.assertIn("metadata/DefaultIconTemplate.ict", plan.files)
            self.assertIn("licenses/LICENSE.txt", plan.files)
            result = build_product(plan, output, log_path=root / "build.log")
            self.assertEqual(result.returncode, 0, (root / "build.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
