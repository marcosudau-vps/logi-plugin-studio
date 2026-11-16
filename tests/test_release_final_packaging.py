"""AP-RELEASE-FINAL-001 C1/D: complete SDK package resources and own-plugin workflow."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from adapters.logitech import deployment, workflow
from adapters.logitech.codegen import DEFAULT_SDK_DLL
from adapters.logitech.errors import GenerationError
from adapters.logitech.product import build_product, generate_product, provision_connection
from adapters.logitech.service import diagnose_plugin_load, package_plugin_name
from release_final_support import resource_project

SDK = Path(DEFAULT_SDK_DLL)
TOOL = shutil.which("logiplugintool")


class FakeService(workflow.ServiceAdapter):
    def __init__(self, status="LOADED"):
        self.status, self.reloads = status, []

    def reload(self, name):
        self.reloads.append(name)
        return {"url": f"loupedeck://plugin/{name}/reload", "returncode": 0}

    def diagnose(self, name, package, since):
        return {"status": self.status, "errors": [] if self.status == "LOADED" else [{"message": "boom"}]}


@unittest.skipUnless(SDK.is_file() and shutil.which("dotnet"), "Requires the installed Logitech SDK and .NET")
class ReleasePackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="release-pkg-")
        cls.root = Path(cls._tmp.name)
        cls.project = resource_project(cls.root / "project", "release.test.pkg")
        cls.out = cls.root / "build"
        cls.plan = generate_product(cls.project, output_dir=cls.out, assembly_name="ReleasePkgPlugin", folder_mode="native")
        try:
            build_product(cls.plan, cls.out, log_path=cls.out / "build.log")
        except Exception as exc:
            raise AssertionError((cls.out / "build.log").read_text(encoding="utf-8")) from exc
        cls.connection = provision_connection(cls.plan, cls.out)
        cls.package = deployment.prepare_package(cls.plan, cls.out, cls.connection)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def marker(self, package=None):
        return json.loads(((package or self.package) / "studio.package.json").read_text(encoding="utf-8"))

    def test_package_contains_every_generated_sdk_resource(self):
        names = {Path(k).as_posix() for k in self.marker()["files"]}
        ns = self.plan.namespace
        command = next(s.type_name for s in self.plan.actions if s.component_id == "action.command")
        adjust = next(s.type_name for s in self.plan.actions if s.component_id == "action.adjustment")
        expected = {f"actionicons/{ns}.{command}.png", f"icontemplates/{ns}.{command}.ict",
                    f"actionsymbols/{ns}.{command}.svg", f"actionsymbols/{ns}.{command}___first.svg",
                    f"actionsymbols/{ns}.{adjust}.svg", "metadata/DefaultIconTemplate.ict",
                    "licenses/LICENSE-TEST.txt", "metadata/Icon256x256.png"}
        self.assertTrue(expected <= names, sorted(names))
        self.assertEqual(set(deployment.package_resources(self.plan)), expected)
        for name in expected:
            self.assertEqual((self.package / name).read_bytes(), self.plan.files[name]
                             if isinstance(self.plan.files[name], bytes) else self.plan.files[name].encode())
        # State images are embedded resources of the DLL, not loose files.
        self.assertFalse(any(n.startswith("native_state_images/") for n in names))
        self.assertEqual(package_plugin_name(self.package), "ReleasePkg")

    @unittest.skipUnless(TOOL, "LogiPluginTool not installed")
    def test_official_logiplugintool_accepts_package_structure(self):
        target = self.root / "verify" / "ReleasePkg_0_2.lplug4"
        target.parent.mkdir(exist_ok=True)
        packed = subprocess.run([TOOL, "pack", str(self.package), str(target)], capture_output=True, text=True, timeout=120)
        self.assertEqual(packed.returncode, 0, packed.stdout + packed.stderr)
        # LogiPluginTool exits 0 even on failed verification: judge its output.
        self.assertIn("Operation succeeded", packed.stdout, packed.stdout)
        verified = subprocess.run([TOOL, "verify", str(target)], capture_output=True, text=True, timeout=120)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertIn("Operation succeeded", verified.stdout, verified.stdout)
        self.assertNotIn("ERROR", verified.stdout, verified.stdout)
        import zipfile
        with zipfile.ZipFile(target) as archive:
            names = set(archive.namelist())
        self.assertTrue(any(n.startswith("actionicons/") for n in names), names)
        self.assertTrue(any(n.startswith("icontemplates/") for n in names), names)

    def test_update_removes_stale_own_resource_and_failed_update_keeps_previous_package(self):
        out = self.root / "update"
        shutil.copytree(self.out, out)
        package = out / "development-package"
        connection = out / "bin" / "Debug" / "studio.connection.json"
        symbol = next(k for k in self.plan.files if k.endswith("___first.svg"))
        smaller = dataclasses.replace(self.plan, files={k: v for k, v in self.plan.files.items() if k != symbol})
        deployment.prepare_package(smaller, out, connection)
        self.assertFalse((package / symbol).exists())
        self.assertNotIn(symbol, {Path(k).as_posix() for k in self.marker(package)["files"]})
        before = {p.relative_to(package).as_posix(): p.read_bytes() for p in package.rglob("*") if p.is_file()}
        (out / deployment.package_resources(self.plan)[0]).write_bytes(b"tampered")
        with self.assertRaisesRegex(GenerationError, "modified"):
            deployment.prepare_package(self.plan, out, connection)
        after = {p.relative_to(package).as_posix(): p.read_bytes() for p in package.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse(any(p.name.startswith(".package-") for p in out.iterdir()))

    def test_case_collision_and_foreign_resource_files_are_refused(self):
        out = self.root / "collision"
        shutil.copytree(self.out, out)
        connection = out / "bin" / "Debug" / "studio.connection.json"
        name = next(k for k in self.plan.files if k.startswith("actionicons/"))
        twin = "actionicons/" + name.split("/")[1].upper()
        files = dict(self.plan.files, **{twin: self.plan.files[name]})
        (out / twin).write_bytes(self.plan.files[name])
        with self.assertRaisesRegex(GenerationError, "collision"):
            deployment.prepare_package(dataclasses.replace(self.plan, files=files), out, connection)
        package = out / "development-package"
        for evil in ("actionicons/run.exe", "actionsymbols/nested/x.svg", "profiles/p.lp5"):
            target = package / evil
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x")
            marker = self.marker(package)
            marker["files"][evil] = hashlib.sha256(b"x").hexdigest()
            original = (package / "studio.package.json").read_bytes()
            (package / "studio.package.json").write_text(json.dumps(marker))
            with self.assertRaises(GenerationError):
                deployment._validate_package(package)
            (package / "studio.package.json").write_bytes(original)
            target.unlink()

    def test_workflow_install_update_failure_rollback_uninstall_restore(self):
        plugins = self.root / "fake-plugins"
        receipts = self.root / "receipts"
        foreign = plugins / "Foreign.link"
        plugins.mkdir()
        foreign.write_text("C:\\somewhere\\foreign\\bin\\")
        with patch("adapters.logitech.deployment.plugin_directory", return_value=plugins):
            fake = FakeService()
            state, live = workflow.plan(self.package, method="link")
            self.assertEqual(live["operation"], "create")
            state = workflow.install_and_verify(self.package, confirm_plugin_id="release.test.pkg",
                                                receipt_dir=receipts / "1", expected_plan=live, adapter=fake, method="link")
            self.assertEqual(state.status["installed"], "INSTALLED")
            self.assertEqual(state.status["loaded"], "LOADED")
            self.assertEqual(state.status["rollback"], "AVAILABLE")
            self.assertEqual(fake.reloads, ["ReleasePkg"])
            link = plugins / "release.test.pkg.link"
            self.assertEqual(link.read_text().strip(), str(self.package.resolve()))
            # Update to a second own package whose load fails -> automatic rollback.
            second = self.root / "second"
            shutil.copytree(self.out, second)
            failing = FakeService("LOAD_FAILED")
            state2 = workflow.install_and_verify(second / "development-package", confirm_plugin_id="release.test.pkg",
                                                 receipt_dir=receipts / "2", adapter=failing, method="link")
            self.assertEqual(state2.status["installed"], "ROLLED_BACK")
            self.assertEqual(link.read_text().strip(), str(self.package.resolve()))
            # Explicit rollback of the first install removes the own link only.
            workflow.rollback(state, adapter=fake)
            self.assertFalse(link.exists())
            state3 = workflow.install_and_verify(self.package, confirm_plugin_id="release.test.pkg",
                                                 receipt_dir=receipts / "3", adapter=fake, method="link")
            self.assertEqual(state3.status["installed"], "INSTALLED")
            inventory = {row["link"]: row for row in deployment.inventory()}
            self.assertTrue(inventory["release.test.pkg.link"]["studio_owned"])
            self.assertFalse(inventory["Foreign.link"]["studio_owned"])
            with self.assertRaises(GenerationError):
                deployment.plan_uninstall("Foreign")
            result = workflow.uninstall("release.test.pkg", confirm_plugin_id="release.test.pkg",
                                        receipt_dir=receipts / "4", adapter=fake)
            self.assertFalse(link.exists())
            self.assertTrue(self.package.is_dir(), "package files are kept for rollback")
            deployment.restore_uninstalled(result["receipt"], confirm_plugin_id="release.test.pkg")
            self.assertEqual(link.read_text().strip(), str(self.package.resolve()))
            with self.assertRaises(GenerationError):
                deployment.restore_uninstalled(result["receipt"], confirm_plugin_id="release.test.pkg")
        self.assertEqual(foreign.read_text(), "C:\\somewhere\\foreign\\bin\\")

    def test_runtime_data_written_by_a_running_plugin_never_blocks_rollback_or_uninstall(self):
        out = self.root / "runtime-data"
        shutil.copytree(self.out, out)
        package = out / "development-package"
        plugins = self.root / "fake-plugins-runtime"
        plugins.mkdir()
        with patch("adapters.logitech.deployment.plugin_directory", return_value=plugins):
            state = workflow.install_and_verify(package, confirm_plugin_id="release.test.pkg",
                                                receipt_dir=self.root / "rt-receipts", adapter=FakeService(), method="link")
            (package / "bin" / "callbacks.jsonl").write_text('{"x": 1}' + chr(10))
            (package / "bin" / "owner-stops.txt").write_text("1" + chr(10))
            with self.assertRaisesRegex(GenerationError, "unstaged"):
                deployment._validate_package(package)  # never a NEW install target
            self.assertEqual(deployment.plan_uninstall("release.test.pkg")["plugin_id"], "release.test.pkg")
            workflow.rollback(state, adapter=FakeService())
            self.assertFalse((plugins / "release.test.pkg.link").exists())
            (package / "bin" / "evil.dll").write_bytes(b"MZ")
            with self.assertRaises(GenerationError):
                deployment._validate_package(package, allow_legacy=True)

    def test_directory_install_update_rollback_uninstall_restore_and_collisions(self):
        from adapters.logitech import directory_install
        plugins = self.root / "fake-plugins-dir"
        plugins.mkdir()
        foreign = plugins / "ForeignPlugin"
        foreign.mkdir()
        (foreign / "x.dll").write_bytes(b"foreign")
        with patch("adapters.logitech.deployment.plugin_directory", return_value=plugins):
            fake = FakeService()
            state = workflow.install_and_verify(self.package, confirm_plugin_id="release.test.pkg",
                                                receipt_dir=self.root / "dir-r1", adapter=fake)
            target = plugins / "ReleasePkg"
            self.assertEqual(state.status["installed"], "INSTALLED")
            self.assertEqual(state.loaded_from, str(target))
            first = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()}
            self.assertIn("actionicons", {Path(k).parts[0] for k in first})
            (target / "bin" / "callbacks.jsonl").write_text("{}")  # runtime data of the running plugin
            # Update from a second build without one resource.
            second = self.root / "dir-second"
            shutil.copytree(self.out, second)
            symbol = next(k for k in self.plan.files if k.endswith("___first.svg"))
            smaller = dataclasses.replace(self.plan, files={k: v for k, v in self.plan.files.items() if k != symbol})
            shutil.rmtree(second / "development-package")
            package2 = deployment.prepare_package(smaller, second, second / "bin" / "Debug" / "studio.connection.json")
            update = workflow.install_and_verify(package2, confirm_plugin_id="release.test.pkg",
                                                 receipt_dir=self.root / "dir-r2", adapter=fake)
            self.assertEqual(update.status["installed"], "UPDATED")
            self.assertFalse((target / symbol).exists())
            self.assertTrue((target / "bin" / "callbacks.jsonl").exists())
            workflow.rollback(update, adapter=fake)
            restored = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()}
            restored.pop("bin/callbacks.jsonl")
            self.assertEqual(restored, first)
            # Link and directory for the same plugin are refused (double load).
            (plugins / "release.test.pkg.link").write_text(str(self.package))
            with self.assertRaisesRegex(GenerationError, "development link"):
                directory_install.plan_install(self.package)
            (plugins / "release.test.pkg.link").unlink()
            result = workflow.uninstall("release.test.pkg", confirm_plugin_id="release.test.pkg", method="directory",
                                        plugin_name="ReleasePkg", receipt_dir=self.root / "dir-r3", adapter=fake)
            self.assertFalse((target / "studio.package.json").exists())
            self.assertFalse(any(p.suffix == ".dll" for p in target.rglob("*")) if target.exists() else False)
            directory_install.restore_uninstalled(result["receipt"], confirm_plugin_id="release.test.pkg")
            self.assertIsNotNone(directory_install.owned(target))
            # A foreign directory with the same SDK name is never touched.
            other = self.root / "dir-other-plugins"
            (other / "ReleasePkg").mkdir(parents=True)
            (other / "ReleasePkg" / "foreign.dll").write_bytes(b"x")
            with self.assertRaisesRegex(GenerationError, "collision"):
                directory_install.plan_install(self.package, target_root=other)
            with self.assertRaises(GenerationError):
                directory_install.plan_uninstall("ForeignPlugin", "release.test.pkg")
        self.assertEqual((foreign / "x.dll").read_bytes(), b"foreign")

    def test_load_diagnosis_parses_real_service_log_format(self):
        logs = self.root / "logs"
        logs.mkdir(exist_ok=True)
        (logs / "ReleasePkg.log").write_text(
            "2026-11-08T15-15-20-185 |   7 | INFO  | Started loading plugin 'ReleasePkg' type ''\n"
            f"2026-11-08T15-15-20-480 |   2 | INFO  | Plugin 'ReleasePkg' version '0.2.0' loaded from '{self.package}' in 290 ms\n",
            encoding="utf-8")
        self.assertEqual(diagnose_plugin_load("ReleasePkg", self.package, log_dir=logs)["status"], "LOADED")
        (logs / "ReleasePkg.log").write_text(
            "2026-11-08T15-15-20-185 |   7 | INFO  | Started loading plugin 'ReleasePkg' type ''\n"
            "2026-11-08T15-15-20-186 |   7 | ERROR | Cannot load plugin 'ReleasePkg': BadImageFormatException\n",
            encoding="utf-8")
        self.assertEqual(diagnose_plugin_load("ReleasePkg", self.package, log_dir=logs)["status"], "LOAD_FAILED")
        (logs / "ReleasePkg.log").write_text(
            "2026-11-08T15-15-20-186 |   7 | ERROR | Cannot load plugin from 'x' because plugin 'ReleasePkg' is already loaded\n",
            encoding="utf-8")
        self.assertEqual(diagnose_plugin_load("ReleasePkg", self.package, log_dir=logs)["status"],
                         "ALREADY_LOADED_RELOAD_REQUIRED")


if __name__ == "__main__":
    unittest.main()
