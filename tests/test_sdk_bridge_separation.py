"""Guardrail: the native Python transport is independent of optional Shared Folders."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adapters.logitech.codegen import DEFAULT_SDK_DLL
from adapters.logitech.product import generate_product


class BridgeSeparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_bridge = (ROOT / "src/adapters/logitech/templates/Bridge.cs.in").read_text(encoding="utf-8")
        cls.optional_folder = (ROOT / "src/extensions/shared_folders/templates/NativeFolders.cs.in").read_text(encoding="utf-8")

    def test_generic_transport_does_not_interpret_optional_folder_protocol(self):
        bridge = self.base_bridge
        for forbidden in ("FolderLayout", "FolderLayoutChanged", "folder_runtime", "folder.layout",
                          "sdk-folders-1", "FolderRuntimeHub", "NativeFolderBase"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, bridge)
        self.assertIn("SnapshotReceived?.Invoke(_runtime, response)", bridge)
        self.assertIn("JournalEventReceived?.Invoke(_runtime, evt)", bridge)
        self.assertIn('else if (kind == "event")', bridge)

    def test_optional_extension_is_only_owner_of_folder_wire_semantics(self):
        source = self.optional_folder
        self.assertIn("Bridge.SnapshotReceived += ReceiveSnapshot", source)
        self.assertIn("Bridge.JournalEventReceived += ReceiveJournalEvent", source)
        self.assertIn('response.TryGetProperty("folder_runtime"', source)
        self.assertIn('port.GetString() == "folder.layout"', source)
        self.assertIn("public static void Initialize()", source)
        self.assertIn("this.ButtonActionNamesChanged()", source)

    def test_old_python_import_paths_are_identity_compatible_with_optional_extension(self):
        from adapters.logitech.folder_runtime import project_virtual_folders as old_project
        from adapters.logitech.folder_host import FolderRuntimeHost as old_host
        from extensions.shared_folders.runtime_projection import project_virtual_folders as new_project
        from extensions.shared_folders.host import FolderRuntimeHost as new_host
        self.assertIs(old_project, new_project)
        self.assertIs(old_host, new_host)
        self.assertNotIn("shared_folders", __import__("runtime.wire").wire.__file__)

    def test_native_plugin_bootstraps_extension_before_transport(self):
        from adapters.logitech.product import _plugin
        from types import SimpleNamespace
        plan = SimpleNamespace(namespace="Probe.Sample", plugin_class="SamplePlugin")
        standard = _plugin(plan)
        native = _plugin(plan, native_folders=True)
        self.assertNotIn("FolderRuntimeHub", standard)
        self.assertIn("FolderRuntimeHub.Initialize(); Bridge.StartFromPluginAssembly", native)

    def test_original_native_project_compiles_with_optional_folder_component(self):
        native = ROOT / "examples/project_logitech_native_v1.json"
        with tempfile.TemporaryDirectory(prefix="sdk-bridge-isolation-") as tmp:
            plan = generate_product(native, output_dir=Path(tmp) / "build", assembly_name="NativeIsolation")
            bridge = plan.files["src/Bridge.cs"]
            folder = plan.files["src/NativeFolders.cs"]
            plugin = plan.files["src/Plugin.cs"]
            self.assertNotIn("folder.layout", bridge)
            self.assertNotIn("folder_runtime", bridge)
            self.assertIn("SnapshotReceived", bridge)
            self.assertIn("JournalEventReceived", bridge)
            self.assertIn("folder.layout", folder)
            self.assertIn("FolderRuntimeHub.Initialize()", plugin)

    def test_legacy_project_is_not_forced_to_load_folder_extension(self):
        legacy = ROOT / "examples/first_plugin/project.json"
        with tempfile.TemporaryDirectory(prefix="sdk-bridge-legacy-") as tmp:
            plan = generate_product(legacy, output_dir=Path(tmp) / "build", assembly_name="LegacyIsolation")
            self.assertNotIn("src/NativeFolders.cs", plan.files)
            self.assertNotIn("FolderRuntimeHub", plan.files["src/Plugin.cs"])
            self.assertIn("SnapshotReceived", plan.files["src/Bridge.cs"])


if __name__ == "__main__":
    unittest.main()
