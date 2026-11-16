"""AP-POLISH-001: plugin-local host runtime, DPAPI pairing keys, build-mode
persistence, version/edition and the corrected installation texts.

The process tests build REAL SDK plugins, move their packages, remove every
Studio/Python hint from the environment and start the plugin in the C# probe:
the plugin must start its own host from its plugin-local runtime.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "tools")]

from adapters.logitech import deployment, directory_install, host_runtime, workflow  # noqa: E402
from adapters.logitech.codegen import DEFAULT_SDK_DLL  # noqa: E402
from adapters.logitech.errors import GenerationError  # noqa: E402
from extensions.shared_folders import secret_store  # noqa: E402
from extensions.shared_folders.embedded_host import policy  # noqa: E402
from extensions.shared_folders.pairing import PairingError, PairingStore  # noqa: E402
from extensions.shared_folders.peer_runtime import Scope  # noqa: E402
from extensions.shared_folders.peer_wire import PeerError  # noqa: E402
from polish_support import (fake_runtime, hand_package, make_dev_runtime, read_json, run_runtime,  # noqa: E402
                            runtime_payload)
from runtime.wire import json_bytes  # noqa: E402
from studio.native_shell.build_mode_store import BuildModeStore  # noqa: E402

SDK = Path(DEFAULT_SDK_DLL)
FIXTURES = ROOT / "tests" / "fixtures" / "ap_shared_final_001"


class HostRuntimeDistributionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_distribution_hashes_every_file_and_detects_tampering_and_planted_files(self):
        runtime = fake_runtime(self.root / "rt")
        row = host_runtime.load_distribution(runtime)
        self.assertEqual(set(row["files"]), {"LogiPluginStudioHost.exe", "_internal/python312.dll",
                                             "_internal/stdlib.zip"})
        (runtime / "_internal" / "python312.dll").write_bytes(b"tampered")
        with self.assertRaisesRegex(GenerationError, "modified"):
            host_runtime.load_distribution(runtime)
        fake_runtime(self.root / "rt2")
        (self.root / "rt2" / "_internal" / "evil.dll").write_bytes(b"x")
        with self.assertRaisesRegex(GenerationError, "unlisted"):
            host_runtime.load_distribution(self.root / "rt2")

    def test_record_is_relative_content_addressed_and_contains_no_studio_path(self):
        runtime = fake_runtime(self.root / "Studio Ordner" / "hostruntime")
        record, files = runtime_payload(runtime)
        row = host_runtime.parse_record(record)
        self.assertEqual(row["format"], "studio-host-runtime-2")
        self.assertRegex(row["directory"], r"^hostruntime-[0-9a-f]{16}$")
        self.assertNotIn(str(self.root).encode(), record)
        self.assertNotIn(b":\\\\", record)
        self.assertIn("dpapi-user-1", row["peer_key_formats"])
        self.assertTrue(all(name.startswith("bin/" + row["directory"] + "/") for name in files))
        # A different runtime yields a different directory (no in-place overwrite of a running runtime).
        record2, _ = runtime_payload(fake_runtime(self.root / "rt-v2", b"v2"))
        self.assertNotEqual(host_runtime.parse_record(record2)["directory"], row["directory"])

    def test_record_validation_rejects_unsafe_entries(self):
        record, _ = runtime_payload(fake_runtime(self.root / "rt"))
        row = json.loads(record)
        for mutate in (lambda r: r["files"].update({"../x.dll": "0" * 64}),
                       lambda r: r["files"].update({"C:/x.dll": "0" * 64}),
                       lambda r: r.update(directory="hostruntime-" + "f" * 16),
                       lambda r: r.update(executable="other.exe"),
                       lambda r: r.update(extra=True)):
            bad = json.loads(record)
            mutate(bad)
            with self.subTest(bad=bad), self.assertRaises(GenerationError):
                host_runtime.parse_record(json.dumps(bad).encode())
        legacy = host_runtime.parse_record(json.dumps({"format": "studio-host-runtime-1",
                                                       "executable": "C:/old/LogiPluginStudioHost.exe"}).encode())
        self.assertEqual(legacy["format"], "studio-host-runtime-1")
        self.assertEqual(row["format"], "studio-host-runtime-2")

    def test_studio_finds_its_runtime_next_to_its_own_executable_after_moving(self):
        for place in ("D/Programme/LogiStudio", "E/Tools/LogiStudio"):
            folder = self.root / place
            fake_runtime(folder / "hostruntime")
            (folder / "LogiPluginStudio.exe").write_bytes(b"")
            with patch.object(sys, "frozen", True, create=True), \
                    patch.object(sys, "executable", str(folder / "LogiPluginStudio.exe")), \
                    patch.dict(os.environ, {}, clear=False) as env:
                env.pop("LOGI_STUDIO_HOST_RUNTIME", None)
                self.assertEqual(host_runtime.studio_runtime_dir(), (folder / "hostruntime").resolve())
                self.assertEqual(Path(host_runtime.studio_host_runner()),
                                 (folder / "hostruntime" / "LogiPluginStudioHost.exe").resolve())

    def test_source_checkout_without_runtime_records_no_directory(self):
        with patch.dict(os.environ, {}, clear=False) as env:
            env.pop("LOGI_STUDIO_HOST_RUNTIME", None)
            record, files = host_runtime.plugin_runtime()
        self.assertIsNone(host_runtime.parse_record(record)["directory"])
        self.assertEqual(files, {})

    def test_installed_status_classifies_legacy_local_damaged(self):
        legacy = self.root / "legacy"
        (legacy / "bin").mkdir(parents=True)
        (legacy / "bin" / "studio.host-runtime.json").write_bytes(json_bytes(
            {"format": "studio-host-runtime-1", "executable": str(self.root / "gone" / "LogiPluginStudioHost.exe")}))
        status = host_runtime.installed_runtime_status(legacy)
        self.assertEqual(status["status"], "LEGACY_ABSOLUTE_PATH")
        self.assertFalse(status["executable_exists"])
        self.assertFalse(host_runtime.supports_protected_keys(legacy))
        record, files = runtime_payload(fake_runtime(self.root / "rt"))
        package = hand_package(self.root / "pkg", record=record, runtime=files)
        self.assertEqual(host_runtime.installed_runtime_status(package)["status"], "PLUGIN_LOCAL")
        self.assertTrue(host_runtime.supports_protected_keys(package))
        victim = next(package.glob("bin/hostruntime-*/_internal/python312.dll"))
        victim.write_bytes(b"changed")
        self.assertEqual(host_runtime.installed_runtime_status(package)["status"], "PLUGIN_LOCAL_DAMAGED")


class PackageAndDirectoryInstallTests(unittest.TestCase):
    """File-level ownership, integrity and Windows file-lock handling."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True)))
        self.plugins = self.root / "Plugins"
        self.plugins.mkdir()
        # A REAL runnable runtime: a running runner holds a genuine Windows image lock.
        self.record, self.files = runtime_payload(make_dev_runtime(self.root / "rt1"))
        self.processes = []

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)

    def start(self, target):
        process = run_runtime(next(target.glob("bin/hostruntime-*")))
        self.processes.append(process)
        time.sleep(0.5)
        self.assertIsNone(process.poll(), "runtime runner must be running")
        return process

    def package(self, name, **kwargs):
        return hand_package(self.root / name, record=kwargs.pop("record", self.record),
                            runtime=kwargs.pop("runtime", self.files), **kwargs)

    def test_package_validation_accepts_runtime_and_rejects_tampering_extras_and_mismatch(self):
        package = self.package("ok")
        marker, _ = deployment._validate_package(package)
        self.assertTrue(any("/hostruntime-" in name for name in marker["files"]))
        bad = self.package("tampered")
        next(bad.glob("bin/hostruntime-*/LogiPluginStudioHost.exe")).write_bytes(b"MZ-other")
        with self.assertRaisesRegex(GenerationError, "modified"):
            deployment._validate_package(bad)
        extra = self.package("extra")
        (next(extra.glob("bin/hostruntime-*")) / "evil.dll").write_bytes(b"x")
        with self.assertRaisesRegex(GenerationError, "unstaged"):
            deployment._validate_package(extra)
        # A runtime file the record does not list is outside the SDK structure.
        files = dict(self.files)
        files[next(iter(files)).rsplit("/", 1)[0] + "/unlisted.pyd"] = b"x"
        with self.assertRaisesRegex(GenerationError, "outside the SDK resource structure"):
            deployment._validate_package(self.package("unlisted", runtime=files))

    def _install(self, package, receipts):
        _, plan = workflow.plan(package, target_root=self.plugins)
        return directory_install.install(plan, confirm_plugin_id=plan["plugin_id"], receipt_dir=receipts,
                                         target_root=self.plugins), plan

    def test_update_while_runtime_is_locked_retires_old_files_and_keeps_ownership(self):
        receipt, plan = self._install(self.package("v1"), self.root / "r1")
        target = Path(plan["target"])
        runner = next(target.glob("bin/hostruntime-*/LogiPluginStudioHost.exe"))
        old_dir = runner.parent
        process = self.start(target)  # the "plugin host" runs from the installed runtime
        with self.assertRaises(OSError):
            runner.unlink()  # Windows: a running image cannot be deleted ...
        before = runner.stat().st_mtime_ns
        # Same runtime, new DLL: unchanged (locked) runtime files are not rewritten.
        self._install(self.package("v1b", dll=b"dll-v2"), self.root / "r2")
        self.assertEqual(runner.stat().st_mtime_ns, before)
        # New runtime (new content-addressed directory) while the old one is in use.
        record3, files3 = runtime_payload(make_dev_runtime(self.root / "rt2", extra=b"v2"))
        receipt3, _ = self._install(self.package("v2", record=record3, runtime=files3, dll=b"dll-v3"),
                                    self.root / "r3")
        retired = list((target / "bin" / ".studio-retired").rglob("*"))
        # ... but renamed aside, and deleted once released.
        self.assertTrue(any(p.name == "LogiPluginStudioHost.exe" for p in retired), retired)
        self.assertIsNone(process.poll(), "the running host is not disturbed by the update")
        self.assertIsNotNone(directory_install.owned(target), "ownership must survive retired files")
        self.assertEqual(host_runtime.installed_runtime_status(target)["status"], "PLUGIN_LOCAL")
        self.assertGreater(directory_install.purge_retired(target), 0)  # still in use
        process.kill()
        process.wait(timeout=10)
        self.assertEqual(directory_install.purge_retired(target, attempts=10, delay=0.3), 0)
        self.assertFalse(old_dir.exists() and any(old_dir.rglob("*")))
        # Rollback to v1b restores the previous runtime directory byte for byte.
        directory_install.rollback(receipt3, confirm_plugin_id=plan["plugin_id"])
        self.assertTrue(runner.is_file())
        self.assertEqual(host_runtime.installed_runtime_status(target)["status"], "PLUGIN_LOCAL")

    def test_uninstall_with_running_host_removes_only_own_files_after_release(self):
        _, plan = self._install(self.package("v1"), self.root / "r1")
        target = Path(plan["target"])
        (target / "bin" / "callbacks.jsonl").write_text("{}\n", encoding="utf-8")  # plugin-written data
        process = self.start(target)

        class Service(workflow.ServiceAdapter):
            def reload(self, name):
                process.kill()  # the service unloads the plugin: its host exits
                process.wait(timeout=10)
                return {"returncode": 0}

        result = workflow.uninstall(plan["plugin_id"], confirm_plugin_id=plan["plugin_id"],
                                    receipt_dir=self.root / "u", method="directory", plugin_name=plan["plugin_name"],
                                    target_root=self.plugins, adapter=Service())
        self.assertEqual(result["residual_files"], 0)
        self.assertEqual(result["profile_note"], "OPTIONS_PLUS_ASSIGNMENTS_MAY_REMAIN")
        self.assertFalse(list(target.rglob("*.exe")) + list(target.rglob("*.dll")))
        self.assertTrue((target / "bin" / "callbacks.jsonl").is_file(), "plugin-written data is not Studio's to delete")

    def test_legacy_absolute_record_package_is_still_owned_and_migrated_by_update(self):
        legacy = json_bytes({"format": "studio-host-runtime-1", "executable": "C:/Gone/LogiPluginStudioHost.exe"})
        _, plan = self._install(self.package("old", record=legacy, runtime={}), self.root / "r1")
        target = Path(plan["target"])
        self.assertEqual(host_runtime.installed_runtime_status(target)["status"], "LEGACY_ABSOLUTE_PATH")
        rows = deployment.installed_runtimes(target_root=self.plugins)
        self.assertEqual(rows[0]["runtime"]["status"], "LEGACY_ABSOLUTE_PATH")
        self.assertEqual(deployment.installed_key_support(plan["plugin_id"], target_root=self.plugins), "plaintext-only")
        self._install(self.package("new"), self.root / "r2")
        self.assertEqual(host_runtime.installed_runtime_status(target)["status"], "PLUGIN_LOCAL")
        self.assertEqual(deployment.installed_key_support(plan["plugin_id"], target_root=self.plugins), "protected-ok")


class ProtectedPairingTests(unittest.TestCase):
    COMMAND = Scope("action", "action.command")

    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = PairingStore(self.home, plaintext_only=lambda plugin: False)
        self.offers = {self.COMMAND: ("command",)}

    def disk(self, plugin):
        return read_json(self.home / "config" / (plugin + ".json"))

    def test_keys_are_dpapi_protected_on_disk_and_readable_by_the_runtime(self):
        self.store.pair("p.a", "p.b")
        self.store.grant("p.a", "p.b", self.COMMAND, ["command"], offers=self.offers)
        for plugin, peer in (("p.a", "p.b"), ("p.b", "p.a")):
            item = self.disk(plugin)["peers"][peer]
            self.assertEqual(set(item), {"key_protected", "grants"})
            self.assertTrue(item["key_protected"].startswith("dpapi-user-1:"))
        trust_a, trust_b = policy(self.home, "p.a"), policy(self.home, "p.b")
        self.assertEqual(trust_a["p.b"].key, trust_b["p.a"].key)
        self.assertEqual(trust_a["p.b"].grants, {self.COMMAND: frozenset({"command"})})
        self.assertTrue(self.store.is_paired("p.a", "p.b"))
        self.assertEqual(self.store.key_storage("p.a"), "protected")
        key = trust_a["p.b"].key.hex()
        for file in self.home.rglob("*"):
            if file.is_file():
                self.assertNotIn(key, file.read_text(encoding="utf-8", errors="replace"), file)

    def test_plaintext_policy_of_earlier_versions_is_migrated_without_new_key_or_grant(self):
        key = "ab" * 32
        grants = [{"scope": self.COMMAND.wire(), "operations": ["command"]}]
        (self.home / "config").mkdir()
        (self.home / "config" / "p.a.json").write_bytes(json_bytes({"peers": {"p.b": {"key": key, "grants": grants}}}))
        (self.home / "config" / "p.b.json").write_bytes(json_bytes({"peers": {"p.a": {"key": key, "grants": []}}}))
        self.assertEqual(policy(self.home, "p.a")["p.b"].key.hex(), key)  # runtime still reads plaintext
        result = self.store.migrate()
        self.assertEqual(sorted(result["protected"]), ["p.a", "p.b"])
        self.assertEqual(self.disk("p.a")["peers"]["p.b"]["grants"], grants)
        self.assertNotIn("key", self.disk("p.a")["peers"]["p.b"])
        self.assertEqual(policy(self.home, "p.a")["p.b"].key.hex(), key)
        self.assertEqual(policy(self.home, "p.b")["p.a"].grants, {})
        self.assertNotIn(key, (self.home / "audit.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(self.store.migrate()["protected"], [])  # idempotent

    def test_installed_pre_1_0_build_keeps_plaintext_until_its_update(self):
        legacy = PairingStore(self.home, plaintext_only=lambda plugin: plugin == "p.a")
        legacy.pair("p.a", "p.b")
        self.assertIn("key", self.disk("p.a")["peers"]["p.b"])
        self.assertIn("key_protected", self.disk("p.b")["peers"]["p.a"])
        self.assertTrue(legacy.is_paired("p.a", "p.b"))
        self.assertEqual(legacy.migrate()["kept_plaintext"], ["p.a"])
        self.assertEqual(legacy.key_storage("p.a"), "plaintext-required")
        self.assertEqual(self.store.migrate()["protected"], ["p.a"])  # after the plugin was updated

    def test_undecryptable_key_fails_closed_and_is_never_regenerated(self):
        self.store.pair("p.a", "p.b")
        path = self.home / "config" / "p.a.json"
        row = read_json(path)
        # A blob written for another slot (or another user) does not decrypt.
        row["peers"]["p.b"]["key_protected"] = secret_store.protect(b"\x01" * 32, owner="p.x", peer="p.y")
        path.write_bytes(json_bytes(row))
        before = path.read_bytes()
        with self.assertRaisesRegex(PairingError, "nicht entschlüsselt"):
            self.store.grants("p.a")
        with self.assertRaises(PairingError):
            self.store.grant("p.a", "p.b", self.COMMAND, ["command"], offers=self.offers)
        with self.assertRaisesRegex(PeerError, "POLICY_KEY_UNAVAILABLE"):
            policy(self.home, "p.a")
        self.assertFalse(self.store.is_paired("p.a", "p.b"))
        self.assertTrue(self.store.check("p.a"))
        self.assertEqual(path.read_bytes(), before, "no silent regeneration")
        self.assertEqual(self.store.migrate()["protected"], [])
        self.store.pair("p.a", "p.b", rekey=True)  # explicit user action repairs it
        self.assertTrue(self.store.is_paired("p.a", "p.b"))


class BuildModeStoreTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = BuildModeStore(self.root / "settings")

    def test_roundtrip_identity_and_plugin_binding(self):
        self.assertEqual(self.store.mode_for("project.a", "plugin.a"), "compatible")
        self.assertTrue(self.store.remember("project.a", "plugin.a", "shared"))
        self.assertEqual(BuildModeStore(self.root / "settings").mode_for("project.a", "plugin.a"), "shared")
        self.assertEqual(self.store.mode_for("project.a", "plugin.other"), "compatible")  # foreign project at same path
        self.assertEqual(self.store.mode_for("project.moved", "plugin.a"), "compatible")  # moved project
        self.assertFalse(self.store.remember("project.a", "plugin.a", "turbo"))

    def test_unknown_values_damaged_files_and_unwritable_locations_fall_back(self):
        self.store.remember("project.a", "plugin.a", "native")
        row = read_json(self.store.path)
        row["projects"]["project.a"]["mode"] = "obsolete-mode"
        self.store.path.write_text(json.dumps(row), encoding="utf-8")
        self.assertEqual(self.store.mode_for("project.a", "plugin.a"), "compatible")
        self.store.path.write_text("{broken", encoding="utf-8")
        self.assertEqual(self.store.mode_for("project.a", "plugin.a"), "compatible")
        self.assertIn("unlesbar", self.store.last_error)
        blocked = self.root / "file-not-dir"
        blocked.write_text("x", encoding="utf-8")
        store = BuildModeStore(blocked / "settings")
        self.assertFalse(store.remember("project.a", "plugin.a", "native"))
        self.assertIn("nicht gespeichert", store.last_error)


class StudioIntegrationTests(unittest.TestCase):
    """Real Qt widgets (offscreen): persistence across project switches and the texts."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {"LOGI_STUDIO_DATA": str(self.root / "data"),
                                                   "LOGI_SHARED_HOME": str(self.root / "shared")}))
        sample = json.loads((ROOT / "examples/project_logitech_native_v1.json").read_text(encoding="utf-8"))
        self.paths = []
        for index in (1, 2):
            raw = json.loads(json.dumps(sample))
            raw["plugin"]["id"] = f"polish.mode{index}"
            path = self.root / f"p{index}" / "project.json"
            path.parent.mkdir()
            path.write_text(json.dumps(raw), encoding="utf-8")
            self.paths.append(path)

    def test_plugin_type_is_restored_per_project_and_title_shows_version(self):
        from studio.native_shell import NativeStudioShell
        from studio.version import VERSION
        window = NativeStudioShell(str(self.paths[0]))
        try:
            controller = window.build_controller
            self.assertEqual(controller.folder_mode, "compatible")
            controller.set_folder_mode("shared")
            self.assertTrue(window.open_project(str(self.paths[1])))
            self.assertEqual(controller.folder_mode, "compatible")
            controller.set_folder_mode("native")
            self.assertTrue(window.open_project(str(self.paths[0])))
            self.assertEqual(controller.folder_mode, "shared")
            self.assertTrue(window.reload_project())
            self.assertEqual(controller.folder_mode, "shared")
            self.assertTrue(window.open_project(str(self.paths[1])))
            self.assertEqual(controller.folder_mode, "native")
            self.assertIn(VERSION, window.windowTitle())
            # The project files themselves were never touched by the setting.
            self.assertNotIn("folder_mode", self.paths[0].read_text(encoding="utf-8"))
        finally:
            window.close()

    def test_installation_texts_distinguish_directory_and_link_and_note_options_plus(self):
        from studio.native_shell import NativeStudioShell
        from studio.native_shell.delivery_panels import METHOD_TEXT, OPTIONS_PLUS_NOTE
        window = NativeStudioShell(str(self.paths[0]))
        try:
            panel = window.deployment_controller
            texts = " ".join(label.text() for label in panel.panel.findChildren(type(panel.status_labels["build"])))
            self.assertIn("Verzeichnis-Installation", texts)
            self.assertNotIn("über einen eigenen Entwicklungs-Link", texts)
            self.assertIn("ohne geöffnetes Studio", texts)
            self.assertEqual(panel.host_button.text(), "Test-Host starten")
            self.assertIn("Options+", OPTIONS_PLUS_NOTE)
            self.assertIn("Plugins", METHOD_TEXT["directory"])
            self.assertIn("Dienststart", METHOD_TEXT["link"])
            from types import SimpleNamespace
            panel.uninstall_receipt = None
            panel.state = SimpleNamespace(method="directory", plugin_id="polish.mode1", receipt=None, status={})
            panel._uninstalled({"receipt": "r.json", "removed": "X", "residual_files": 0})
            self.assertIn("Options+", panel.log.toPlainText())
            self.assertIn("erfolgreich entfernt", panel.log.toPlainText())
        finally:
            window.close()

    def test_pairing_tab_reports_protected_key_storage(self):
        from studio.native_shell import NativeStudioShell
        store = PairingStore(self.root / "shared", plaintext_only=lambda plugin: False)
        store.pair("polish.mode1", "polish.peer")
        window = NativeStudioShell(str(self.paths[0]))
        try:
            pc = window.pairing_controller
            pc.store = store
            pc.refresh()
            cells = {pc.plugins.item(r, 0).text(): pc.plugins.item(r, 4).text() for r in range(pc.plugins.rowCount())}
            self.assertEqual(cells["polish.mode1"], "DPAPI-geschützt")
        finally:
            window.close()


class VersionTests(unittest.TestCase):
    def test_edition_is_detected_at_run_time(self):
        from studio import version
        self.assertEqual(version.edition(), "source")
        with tempfile.TemporaryDirectory() as temp, patch.object(sys, "frozen", True, create=True), \
                patch.object(sys, "executable", str(Path(temp) / "LogiPluginStudio.exe")):
            self.assertEqual(version.edition(), "portable")
            (Path(temp) / "studio-edition.json").write_text('{"edition": "setup"}', encoding="utf-8")
            self.assertEqual(version.edition(), "setup")
        self.assertRegex(version.VERSION, r"^\d+\.\d+\.\d+(-rc\d+)?$")

    def test_release_tooling_reads_the_central_version(self):
        text = (ROOT / "tools/packaging/build_release.py").read_text(encoding="utf-8")
        self.assertIn("from studio.version import", text)
        self.assertNotIn('VERSION = "', text)
        iss = (ROOT / "tools/packaging/LogiPluginStudio.iss").read_text(encoding="utf-8")
        self.assertIn("PrivilegesRequired=lowest", iss)
        self.assertIn("{autopf}\\LogiPluginStudio", iss)
        self.assertNotIn("LOCALAPPDATA%\\LogiPluginStudio\"; Type", iss)


def wait_until(check, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("condition timed out")


@unittest.skipUnless(SDK.is_file() and shutil.which("dotnet"), "Requires the installed Logitech SDK and .NET")
class SelfHostedPluginProcessTests(unittest.TestCase):
    """Real C# plugins start their own host from the plugin-local runtime."""

    @classmethod
    def setUpClass(cls):
        from adapters.logitech.product import build_product, generate_product, provision_connection
        cls._tmp = tempfile.TemporaryDirectory(prefix="polish-selfhost-")
        cls.root = Path(cls._tmp.name)
        cls.runtime = make_dev_runtime(cls.root / "studio-a" / "hostruntime")
        sample = json.loads((ROOT / "examples/project_logitech_native_v1.json").read_text(encoding="utf-8"))
        cls.builds = {}
        with patch.dict(os.environ, {"LOGI_STUDIO_HOST_RUNTIME": str(cls.runtime)}):
            for mode, plugin in (("native", "polish.native"), ("compatible", "polish.compat"),
                                 ("shared", "polish.shared.alpha"), ("shared", "polish.shared.beta")):
                raw = json.loads(json.dumps(sample))
                raw["plugin"]["id"] = plugin
                raw["folders"][0]["entries"][0]["action_parameter"] = "first"
                name = plugin.split(".")[-1]
                source = cls.root / "projects" / name / "project.json"
                source.parent.mkdir(parents=True)
                source.write_text(json.dumps(raw), encoding="utf-8")
                shutil.copyfile(FIXTURES / "owner.py", source.parent / "owner.py")
                out = cls.root / "build" / name
                plan = generate_product(source, output_dir=out, assembly_name="Polish" + name.capitalize() + "Plugin",
                                        folder_mode=mode, embed_host=True, shared_handler="owner.py")
                try:
                    build_product(plan, out, log_path=out / "build.log")
                except Exception as exc:
                    raise AssertionError((out / "build.log").read_text(encoding="utf-8")) from exc
                connection = provision_connection(plan, out)
                package = deployment.prepare_package(plan, out, connection)
                cls.builds[plugin] = (plan, package, raw)
        # The "Studio" disappears: its runtime directory is removed entirely.
        shutil.rmtree(cls.root / "studio-a")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.env = self.enterContext(patch.dict(os.environ, {"LOGI_SHARED_HOME": str(self.root / "shared-home"),
                                                              "LOGI_HOST_LOG_DIR": str(self.root / "host-logs")}))
        for name in ("LOGI_SHARED_PYTHON", "LOGI_STUDIO_HOST_RUNTIME", "PYTHONPATH", "PYTHONHOME"):
            os.environ.pop(name, None)
        # Make sure no plain "python" can be found through PATH either.
        os.environ["PATH"] = os.pathsep.join(p for p in os.environ.get("PATH", "").split(os.pathsep)
                                             if "python" not in p.lower())

    def probe(self, plan, package, label):
        from probe_helpers import ProcessProbe
        directory = self.root / "probes" / label
        directory.mkdir(parents=True)
        (directory / "Program.cs").write_text(
            (FIXTURES / "PluginProbe.cs.in").read_text(encoding="utf-8-sig").replace("$ASSEMBLY$", plan.assembly_name),
            encoding="utf-8")
        (directory / "Probe.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
            '<TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup>'
            f'<Reference Include="PluginApi"><HintPath>{escape(str(SDK))}</HintPath></Reference>'
            '</ItemGroup></Project>', encoding="utf-8")
        result = subprocess.run(["dotnet", "build", str(directory / "Probe.csproj"), "-v:q", "--nologo"],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return ProcessProbe(directory / "bin/Debug/net10.0/Probe.dll", package / "bin/studio.connection.json",
                            directory / "probe.log", sdk_dll=SDK)

    def place(self, plugin, where):
        plan, package, raw = self.builds[plugin]
        target = self.root / where / plugin
        shutil.copytree(package, target)
        return plan, target

    @staticmethod
    def results(package):
        path = package / "bin" / "owner-results.jsonl"
        return [json.loads(r) for r in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def run_native(self, plugin, where):
        plan, package = self.place(plugin, where)
        with self.probe(plan, package, f"{where}-{plugin}") as probe:
            view = probe.wait(lambda row: row.get("ready"))
            button = next(n for n in view["names"] if n.endswith("placement.command"))
            probe.rpc("run|" + button)
            rows = wait_until(lambda: self.results(package))
            log = probe.log_path
        host_pid = rows[-1]["pid"]
        text = log.read_text(encoding="utf-8", errors="replace")
        self.assertIn("HOST_STARTED plugin-local", text)
        # Clean process end: stdin EOF on unload ends the plugin's host.
        wait_until(lambda: (package / "bin" / "owner-stops.txt").exists()
                   and str(host_pid) in (package / "bin" / "owner-stops.txt").read_text())
        return rows

    def test_native_and_compatible_plugins_run_without_studio_and_after_moving(self):
        for plugin in ("polish.native", "polish.compat"):
            with self.subTest(plugin=plugin):
                first = self.run_native(plugin, "D-Programme")
                self.assertEqual(first[-1]["action"], "action.command")
                self.assertEqual(first[-1]["parameter"], "first")
                second = self.run_native(plugin, "E-Tools-moved")
                self.assertEqual(second[-1]["action"], "action.command")

    def test_manipulated_runtime_is_refused_without_fallback(self):
        os.environ["LOGI_SHARED_PYTHON"] = sys.executable  # a fallback exists but must NOT be used
        for label, code in (("modified", "RUNTIME_FILE_MODIFIED"), ("planted", "RUNTIME_UNLISTED_FILE")):
            with self.subTest(label=label):
                fresh_plan, fresh = self.place("polish.native", "tampered-" + label)
                runtime = next(fresh.glob("bin/hostruntime-*"))
                if label == "modified":
                    next(runtime.glob("*._pth")).write_text("C:\\evil\n")
                else:
                    (runtime / "version.dll").write_bytes(b"MZ")  # DLL planting beside the runner
                with self.probe(fresh_plan, fresh, "tampered-" + label) as probe:
                    time.sleep(3)
                    self.assertFalse(probe.rpc("inspect")["ready"])
                    text = probe.log_path.read_text(encoding="utf-8", errors="replace")
                self.assertIn("HOST_RUNTIME_INTEGRITY_FAILED " + code, text)
                self.assertNotIn("HOST_STARTED", text)
                self.assertFalse(self.results(fresh))

    def test_shared_plugins_pair_with_protected_keys_and_rejoin_after_moving(self):
        home = self.root / "shared-home"
        store = PairingStore(home, plaintext_only=lambda plugin: False)
        store.pair("polish.shared.alpha", "polish.shared.beta")
        self.assertEqual(store.key_storage("polish.shared.alpha"), "protected")
        for round_name in ("first-place", "moved-place"):
            with self.subTest(round=round_name):
                plan_a, package_a = self.place("polish.shared.alpha", round_name)
                plan_b, package_b = self.place("polish.shared.beta", round_name)
                with self.probe(plan_a, package_a, round_name + "-A") as pa, \
                        self.probe(plan_b, package_b, round_name + "-B") as pb:
                    pa.wait(lambda row: row.get("ready"))
                    pb.wait(lambda row: row.get("ready"))
                    connected = wait_until(lambda: store.status("polish.shared.alpha")["peers"].get(
                        "polish.shared.beta", {}).get("connected"), timeout=30)
                    self.assertTrue(connected)
                    logs = pa.log_path.read_text(encoding="utf-8", errors="replace")
                self.assertIn("HOST_STARTED plugin-local", logs)
                host_log = (home / "logs" / "polish.shared.alpha.log").read_text(encoding="utf-8", errors="replace")
                self.assertIn("Peer policy accepted: peers=1", host_log)
                self.assertNotIn(policy(home, "polish.shared.alpha")["polish.shared.beta"].key.hex(), host_log)


ASYNCIO_PROBE = """
import asyncio
async def inner():
    assert asyncio.current_task() is not None, "current_task is None inside a task"
    await asyncio.wait_for(asyncio.sleep(0.01), 2)
    async with asyncio.timeout(2):
        await asyncio.sleep(0.01)
    return "ASYNCIO_OK"
print(asyncio.run(inner()))
"""


class HostRunnerAsyncioTests(unittest.TestCase):
    """Regression: the runner imported ``_asyncio`` before ``asyncio`` (found by the
    real-service relocation test): every asyncio timeout failed and Shared peers
    never connected under the frozen runtime."""

    def test_runner_keeps_asyncio_tasks_functional(self):
        import zipfile
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp) / "probe.pyz"
            with zipfile.ZipFile(bundle, "w") as archive:
                archive.writestr("__main__.py", ASYNCIO_PROBE)
            result = subprocess.run([sys.executable, "-I", str(ROOT / "tools/packaging/host_runner.py"), "-I", "-B",
                                     str(bundle)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn("ASYNCIO_OK", result.stdout)

    def test_runner_imports_asyncio_before_its_c_extension(self):
        lines = (ROOT / "tools/packaging/host_runner.py").read_text(encoding="utf-8").splitlines()
        first_asyncio = next(i for i, line in enumerate(lines) if line.startswith("import asyncio"))
        first_c = next(i for i, line in enumerate(lines) if line.startswith("import ") and "_asyncio" in line)
        self.assertLess(first_asyncio, first_c)


class LinkCheckTests(unittest.TestCase):
    def test_documentation_links_resolve(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools" / "check_links.py")],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("fehlende Ziele: 0", result.stdout)


if __name__ == "__main__":
    unittest.main()
