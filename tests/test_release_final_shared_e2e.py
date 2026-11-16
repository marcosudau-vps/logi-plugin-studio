"""AP-RELEASE-FINAL-001 B/C2/F: real DLL processes, Studio pairing, remote images.

Three Shared plugins are generated, compiled and started as separate SDK-like
processes (C# probe loading the real PluginApi.dll). Pairing and permissions are
created exclusively through ``PairingStore`` (the Studio backend), never by
hand-written policy JSON.
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools"), str(ROOT / "tests")]

from adapters.logitech.codegen import DEFAULT_SDK_DLL
from adapters.logitech.deployment import prepare_package
from adapters.logitech.product import build_product, generate_product, provision_connection
from extensions.shared_folders.pairing import PairingStore, project_offers
from extensions.shared_folders.peer_runtime import Scope
from extensions.shared_folders.runtime_projection import initial_layout
from probe_helpers import ProcessProbe
from release_final_support import resource_project

FIXTURES = ROOT / "tests" / "fixtures" / "release_final"
SDK = Path(DEFAULT_SDK_DLL)
EVIDENCE = os.environ.get("RELEASE_FINAL_EVIDENCE")


def wait_until(check, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.075)
    raise AssertionError("condition timed out")


def owner_results(package):
    path = package / "bin/owner-results.jsonl"
    return [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


@unittest.skipUnless(SDK.is_file() and shutil.which("dotnet"), "Requires the installed Logitech SDK and .NET")
class SharedEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="release-e2e-")))
        self.home = self.root / "local"
        self.enterContext(patch.dict(os.environ, {"LOGI_SHARED_HOME": str(self.home),
                                                   "LOGI_SHARED_PYTHON": sys.executable,
                                                   "PYTHONPATH": str(self.root / "deliberately-missing")}))
        self.store = PairingStore(self.home)

    def build(self, project, *, layout=None, references=None):
        raw = json.loads(project.read_text(encoding="utf-8"))
        name = raw["plugin"]["id"].split(".")[-1]
        shutil.copyfile(FIXTURES / "owner.py", project.parent / "owner.py")
        out = self.root / ("build-" + name)
        plan = generate_product(project, output_dir=out, assembly_name="E2e" + name.capitalize(),
                                folder_mode="shared", folder_runtime=layout, shared_references=references,
                                shared_handler="owner.py")
        try:
            build_product(plan, out, log_path=out / "build.log")
        except Exception as exc:
            raise AssertionError((out / "build.log").read_text(encoding="utf-8")) from exc
        package = self.root / ("package-" + name)
        shutil.copytree(prepare_package(plan, out, provision_connection(plan, out)), package)
        shutil.rmtree(out)
        return plan, package

    def probe(self, plan, package, label):
        directory = self.root / label
        directory.mkdir()
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

    def consumer(self, plugin, refs):
        project = self.root / plugin.split(".")[-1] / "project.json"
        project.parent.mkdir()
        raw = json.loads((ROOT / "examples/project_logitech_native_v1.json").read_text(encoding="utf-8"))
        raw["plugin"]["id"] = plugin
        raw["folders"][0]["entries"][0]["action_parameter"] = "first"
        project.write_text(json.dumps(raw), encoding="utf-8")
        layout, _ = initial_layout(raw)
        entries = layout["folders"][0]["nodes"][0]["pages"][0]["entries"]
        references = []
        for index, (owner, scope, label) in enumerate(refs):
            placement = f"placement.remote.{index}"
            entries.append(dict(id=placement, kind="unavailable", label=label, reason="EXTERNAL_REFERENCE_OFFLINE"))
            references.append(dict(placement=placement, plugin=owner, scope=scope.wire()))
        return self.build(project, layout=layout, references=references)

    def test_studio_pairing_remote_images_push_unauthorized_invalid_policy_and_rejoin(self):
        a, b, c = "release.a", "release.b", "release.c"
        command, multistate = Scope("action", "action.command", "first"), Scope("action", "action.multistate")
        owner_project = resource_project(self.root / "a", a, display="Owner A")
        owner_raw = json.loads(owner_project.read_text(encoding="utf-8"))
        # Studio backend: pairing first (grants nothing), then exact directed grants.
        self.store.pair(a, b)
        self.store.pair(a, c)
        offers = project_offers(owner_raw, initial_layout(owner_raw)[0])
        self.store.grant(a, b, command, ["command"], offers=offers)
        self.store.grant(a, b, multistate, ["command"], offers=offers)
        builds = {a: self.build(owner_project)}
        builds[b] = self.consumer(b, [(a, command, "A_cmd"), (a, multistate, "A_state")])
        builds[c] = self.consumer(c, [(a, command, "A_cmd_unauthorized")])
        # C gets a corrupt policy: fail closed, local actions must keep working.
        (self.home / "config" / (c + ".json")).write_text("{broken", encoding="utf-8")
        evidence = {}
        with ExitStack() as processes:
            pb = processes.enter_context(self.probe(*builds[b], "probe-b"))
            pc = processes.enter_context(self.probe(*builds[c], "probe-c"))
            pa = processes.enter_context(self.probe(*builds[a], "probe-a"))
            for probe in (pa, pb, pc):
                probe.wait(lambda x: x.get("ready"))

            def cell(probe, suffix, field="labels"):
                view = probe.rpc("inspect")
                return next((value for name, value in zip(view["names"], view[field]) if name.endswith(suffix)), None)

            def name(probe, suffix):
                return next(n for n in probe.rpc("inspect")["names"] if n.endswith(suffix))

            try:
                wait_until(lambda: cell(pb, "placement.remote.0") == "Erste Variante", 30)
            except AssertionError:
                self.fail(repr(pb.rpc("inspect")) + pb.log_path.read_text(encoding="utf-8")[-3000:]
                          + pa.log_path.read_text(encoding="utf-8")[-3000:])
            # Status files written by the runtimes (consumed by the Studio tab).
            wait_until(lambda: self.store.status(b)["peers"].get(a, {}).get("connected"))
            evidence["status_b"] = self.store.status(b)
            self.assertTrue(evidence["status_b"]["online"])
            # C2: owner package icon and multistate state image arrive as real PNG bitmaps.
            icon = pb.rpc("hashpng|" + str(owner_project.parent / "assets/command.png"))
            off = pb.rpc("hashpng|" + str(owner_project.parent / "assets/state-off.png"))
            on = pb.rpc("hashpng|" + str(owner_project.parent / "assets/state-on.png"))
            wait_until(lambda: cell(pb, "placement.remote.0", "images") == icon)
            wait_until(lambda: cell(pb, "placement.remote.1", "images") == off)
            self.assertTrue(all(isinstance(h, str) and len(h) == 64 for h in (icon, off, on)))
            self.assertEqual(len({icon, off, on}), 3)
            evidence["image_hashes"] = dict(icon=icon, off=off, on=on)
            # Owner invoke + push: B presses A's multistate, A changes state, B shows the new label and image.
            pb.rpc("run|" + name(pb, "placement.remote.1"))
            wait_until(lambda: cell(pb, "placement.remote.1") == "An")
            wait_until(lambda: cell(pb, "placement.remote.1", "images") == on)
            pb.rpc("run|" + name(pb, "placement.remote.0"))
            rows = wait_until(lambda: [r for r in owner_results(builds[a][1]) if r["action"] == "action.command"])
            self.assertEqual([(r["action"], r["parameter"]) for r in rows], [("action.command", "first")])
            updates = pb.rpc("inspect")["remote_images"]
            self.assertGreaterEqual(updates, 3)
            # Owner-side direct change is pushed to B (targeted image update).
            self.assertTrue(pa.rpc("direct|action.multistate"))
            wait_until(lambda: cell(pb, "placement.remote.1", "images") == off)
            # Unauthorized: C is paired but has no grant and a corrupt policy -> stays unavailable.
            self.assertIn("[unavailable]", cell(pc, "placement.remote.0") or "")
            pc.rpc("run|" + name(pc, "placement.remote.0"))
            time.sleep(1.0)
            self.assertEqual(len([r for r in owner_results(builds[a][1]) if r["action"] == "action.command"]), 1)
            self.assertTrue(pc.rpc("direct|action.command|first"))
            wait_until(lambda: owner_results(builds[c][1]))
            # Failure + rejoin of the owner: B degrades, keeps local function, recovers.
            pa.process.kill()
            pa.process.wait(timeout=5)
            wait_until(lambda: "[unavailable]" in (cell(pb, "placement.remote.0") or ""), 30)
            self.assertIsNone(cell(pb, "placement.remote.0", "images"))
            self.assertTrue(pb.rpc("direct|action.command|first"))
            pa2 = processes.enter_context(self.probe(*builds[a], "probe-a-restart"))
            pa2.wait(lambda x: x.get("ready"))
            wait_until(lambda: cell(pb, "placement.remote.0") == "Erste Variante", 30)
            wait_until(lambda: cell(pb, "placement.remote.0", "images") == icon)
            pb.rpc("run|" + name(pb, "placement.remote.0"))
            wait_until(lambda: len([r for r in owner_results(builds[a][1]) if r["action"] == "action.command"]) == 2)
            evidence["final_b"] = pb.rpc("inspect")
            # Revocation through the Studio backend takes effect at the owner's next start.
            self.store.revoke(a, b, command)
        if EVIDENCE:
            Path(EVIDENCE).write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
        audit = (self.home / "audit.jsonl").read_text(encoding="utf-8")
        # AP-POLISH-001: key is DPAPI-protected on disk; take the decrypted key from the runtime parser.
        from extensions.shared_folders.embedded_host import policy
        key = policy(self.home, a)[b].key.hex()
        self.assertNotIn(key, audit)


if __name__ == "__main__":
    unittest.main()
