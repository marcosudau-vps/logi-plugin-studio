"""Generated SDK DLLs and their embedded owner processes, staged in clean directories.

AP-RELEASE-FINAL-001: parameterised entries are labelled with the SDK parameter
display name ("Erste Variante") instead of the action name (hardware finding HW-N5).
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
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]

from adapters.logitech.codegen import DEFAULT_SDK_DLL
from adapters.logitech.deployment import prepare_package
from adapters.logitech.product import generate_product, build_product, provision_connection
from extensions.shared_folders.runtime_projection import initial_layout
from extensions.shared_folders.peer_runtime import Scope
from extensions.shared_folders.peer_wire import Discovery
from probe_helpers import ProcessProbe
from runtime.host import PluginHost
from runtime.wire import ConnectionSettings, LocalClient

FIXTURES = ROOT / "tests" / "fixtures" / "ap_shared_final_001"
SDK = Path(DEFAULT_SDK_DLL)


def raw_plugin(plugin):
    sample = json.loads((ROOT / "examples/project_logitech_native_v1.json").read_text(encoding="utf-8"))
    sample["plugin"]["id"] = plugin
    sample["folders"][0]["entries"][0]["action_parameter"] = "first"
    return sample


def wait_until(check, timeout=15):
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


def grant(scope, *ops):
    return dict(scope=scope.wire(), operations=list(ops))


@unittest.skipUnless(SDK.is_file() and shutil.which("dotnet"), "Requires the installed Logitech SDK and .NET")
class SharedPluginBuildTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = self.root / "local"
        (self.home / "config").mkdir(parents=True)
        self.enterContext(patch.dict(os.environ, {"LOGI_SHARED_HOME": str(self.home),
                                                   "LOGI_SHARED_PYTHON": sys.executable,
                                                   "PYTHONPATH": str(self.root / "deliberately-missing")}))
        self.discovery = Discovery(self.home / "discovery", "", "")
        self.packages = {}

    def build(self, raw, mode, *, layout=None, references=None):
        name = raw["plugin"]["id"].split(".")[-1]
        out = self.root / ("build-" + name)
        source = self.root / (name + ".json")
        source.write_text(json.dumps(raw), encoding="utf-8")
        shutil.copyfile(FIXTURES / "owner.py", self.root / "owner.py")
        plan = generate_product(source, output_dir=out, assembly_name="Plugin" + name,
                                folder_mode=mode, folder_runtime=layout, shared_references=references,
                                shared_handler="owner.py" if mode == "shared" else None)
        try:
            build_product(plan, out, log_path=out / "build.log")
        except Exception as exc:
            raise AssertionError((out / "build.log").read_text(encoding="utf-8")) from exc
        connection = provision_connection(plan, out)
        package = self.root / ("standalone-" + name)
        shutil.copytree(prepare_package(plan, out, connection), package)
        self.packages[name] = package
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
                                capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        dll = directory / "bin/Debug/net10.0/Probe.dll"
        return ProcessProbe(dll, package / "bin/studio.connection.json", directory / "probe.log", sdk_dll=SDK)

    def test_explicit_native_compiles_without_optional_runtime(self):
        raw = raw_plugin("shared.native")
        plan, package = self.build(raw, "native")
        self.assertFalse(plan.manifest["folder_runtime"]["enabled"])
        self.assertNotIn("src/NativeFolders.cs", plan.files)
        self.assertNotIn("shared-folder-host.pyz", plan.files)
        self.assertNotIn("FolderLayout", plan.files["src/Spec.cs"])
        self.assertIn("StaticSdkFolder", plan.files["src/StaticSdkFolder.cs"])
        self.assertIn('"first"', next(v for k, v in plan.files.items() if k.startswith("src/folders/")))
        self.assertNotIn("SharedSdk", plan.files["src/Plugin.cs"])
        self.assertFalse((package / "shared-folder-host.pyz").exists())
        settings = ConnectionSettings.load(package / "bin/studio.connection.json")
        host = PluginHost(raw, settings)
        calls = []
        host.register_handler("handler.main", "invoke", lambda _, ctx: calls.append(
            (ctx.component_id, ctx.action_parameter, ctx.placement_id, ctx.adjustment_diff)))
        with host, self.probe(plan, package, "native-probe") as probe:
            view = probe.wait(lambda row: row.get("ready"))
            button, label = next((name, label) for name, label in zip(view["names"], view["labels"])
                                 if name.endswith("placement.command"))
            self.assertEqual(label, "Erste Variante")
            probe.rpc("run|" + button)
            wait_until(lambda: calls)
            self.assertEqual(calls, [("action.command", "first", "placement.command", None)])
            self.assertFalse(any(n.endswith("placement.editor") for n in view["names"]))
            encoder = next(n for n in view["encoders"] if n.endswith("placement.adjustment"))
            probe.rpc("adjust|" + encoder + "|6")
            wait_until(lambda: len(calls) == 2)
            self.assertEqual(calls[1], ("action.adjustment", None, "placement.adjustment", 6))
            self.assertIn("56%", probe.rpc("inspect")["values"])
        self.assertIsNone(self.discovery.read("shared.native"))

    def test_three_embedded_plugins_owner_callbacks_and_rejoin(self):
        a, b, c = ("shared.a", "shared.b", "shared.c")
        command = Scope("action", "action.command", "first")
        multistate = Scope("action", "action.multistate")
        adjust = Scope("action", "action.adjustment")
        folder = Scope("folder", "folder.main")
        other = Scope("action", "action.command", "second")
        builds = {}
        pairwise = {(a,b): "a1"*32, (a,c): "a2"*32, (b,c): "b1"*32}
        for plugin in (a, b, c):
            peers = {p: dict(key=pairwise[tuple(sorted((p,plugin)))], grants=[]) for p in (a,b,c) if p != plugin}
            if plugin == a:
                peers[c]["grants"] = [grant(command, "command"), grant(multistate, "command"),
                                        grant(adjust, "adjustment", "command"), grant(folder)]
            if plugin == b:
                peers[c]["grants"] = [grant(other, "command")]
            (self.home / "config" / (plugin + ".json")).write_text(json.dumps(dict(peers=peers)), encoding="utf-8")
            raw = raw_plugin(plugin)
            layout = None
            refs = None
            if plugin == c:
                layout, _ = initial_layout(raw)
                entries = layout["folders"][0]["nodes"][0]["pages"][0]["entries"]
                refs = []
                for index, (owner, scope, label) in enumerate(((a,command,"A_01"), (a,multistate,"A_state"),
                                                               (a,adjust,"A_encoder"), (b,other,"B_02"), (a,folder,"A_folder"))):
                    placement = "placement.remote." + str(index)
                    entries.append(dict(id=placement, kind="unavailable", label=label, reason="EXTERNAL_REFERENCE_OFFLINE"))
                    refs.append(dict(placement=placement, plugin=owner, scope=scope.wire()))
                layout["folders"][0]["nodes"][0]["pages"].append(dict(id="page.next", entries=[]))
            builds[plugin] = self.build(raw, "shared", layout=layout, references=refs)
        with tempfile.TemporaryDirectory() as extracted:
            pyz = Path(extracted) / "test.pyz"
            pyz.write_bytes(builds[a][0].files["shared-folder-host.pyz"])
            with zipfile.ZipFile(pyz) as bundle:
                names = bundle.namelist()
                self.assertIn("extensions/shared_folders/peer_runtime.py", names)
                self.assertIn("runtime/host.py", names)
                self.assertFalse(any(n.startswith("studio/") for n in names))
        # Remove all build sources and standalone .pyz files before starting the DLLs.
        for plugin in (a,b,c):
            directory = self.root / ("build-" + plugin[-1])
            self.assertEqual(directory.resolve().parent, self.root.resolve())
            shutil.rmtree(directory)
        with ExitStack() as processes:
            pc = processes.enter_context(self.probe(*builds[c], "probe-c"))
            pb = processes.enter_context(self.probe(*builds[b], "probe-b"))
            pa = processes.enter_context(self.probe(*builds[a], "probe-a"))
            for probe in (pa, pb, pc):
                self.assertTrue(probe.wait(lambda x: x.get("ready"))["ready"])
            def visible(suffix):
                result = pc.rpc("inspect")
                self.assertNotIn("error", result)
                return next((n for n in result["names"] if n.endswith(suffix)), None)
            def text_for(suffix):
                result = pc.rpc("inspect")
                return next((label for n,label in zip(result["names"],result["labels"]) if n.endswith(suffix)), None)
            try:
                wait_until(lambda: text_for("placement.remote.0") == "Erste Variante")
            except AssertionError as error:
                self.fail(str(error) + repr([p.rpc("inspect") for p in (pa,pb,pc)]) +
                          repr([self.discovery.read(p) for p in (a,b,c)]) +
                          "\n".join(p.log_path.read_text(encoding="utf-8")[-3000:] for p in (pa,pb,pc)))
            wait_until(lambda: text_for("placement.remote.3") == "Zweite Variante")
            wait_until(lambda: text_for("placement.remote.1") == "Aus")
            remote_a = visible("placement.remote.0")
            pc.rpc("run|" + remote_a)
            rows = wait_until(lambda: owner_results(builds[a][1]))
            self.assertEqual([(r["action"], r["parameter"]) for r in rows], [("action.command", "first")])
            self.assertFalse(owner_results(builds[c][1]))
            pc.rpc("run|" + visible("placement.remote.1"))
            wait_until(lambda: text_for("placement.remote.1") == "An")
            self.assertTrue(pa.rpc("direct|action.multistate"))
            wait_until(lambda: text_for("placement.remote.1") == "Aus")
            remote_encoder = next(n for n in pc.rpc("inspect")["encoders"] if n.endswith("placement.remote.2"))
            pc.rpc("adjust|" + remote_encoder + "|7")
            wait_until(lambda: "57%" in pc.rpc("inspect")["values"])
            remote_reset = next(n for n in pc.rpc("inspect")["resets"] if n.endswith("placement.remote.2"))
            pc.rpc("run|" + remote_reset)
            wait_until(lambda: pc.rpc("inspect")["values"].count("50%") == 2)
            wait_until(lambda: len([r for r in owner_results(builds[a][1]) if r["action"] == "action.adjustment"]) == 2)
            pc.rpc("run|" + visible("placement.remote.4"))
            self.assertTrue(pc.rpc("inspect")["node"].startswith("peer.node."))
            self.assertTrue("Erste Variante" in pc.rpc("inspect")["labels"])
            pc.rpc("run|" + visible("back"))
            owner_client = LocalClient(ConnectionSettings.load(builds[a][1] / "bin/studio.connection.json"))
            owner_client.handshake()
            scopes_before = owner_client.snapshot()["shared_watch"]
            self.assertEqual(len(scopes_before), 3)
            pc.rpc("run|" + visible("next"))
            self.assertEqual(pc.rpc("inspect")["page"], 1)
            pc.rpc("run|" + visible("previous"))
            self.assertEqual(owner_client.snapshot()["shared_watch"], scopes_before)
            old_b = self.discovery.read(b)["instance"]
            old_callback = visible("placement.remote.3")
            pb.process.kill()
            pb.process.wait(timeout=5)
            wait_until(lambda: "[unavailable]" in (text_for("placement.remote.3") or ""))
            self.assertTrue(pa.rpc("direct|action.command|first"))
            self.assertTrue(pc.rpc("direct|action.command|first"))
            pb2 = processes.enter_context(self.probe(*builds[b], "probe-b-restart"))
            pb2.wait(lambda x: x.get("ready"))
            wait_until(lambda: text_for("placement.remote.3") == "Zweite Variante")
            self.assertNotEqual(old_b, self.discovery.read(b)["instance"])
            self.assertNotEqual(old_callback, visible("placement.remote.3"))
            pc.rpc("run|" + old_callback)
            pc.rpc("run|" + visible("placement.remote.3"))
            second = wait_until(lambda: owner_results(builds[b][1]))
            self.assertEqual([(r["action"],r["parameter"]) for r in second], [("action.command", "second")])
            self.assertEqual(len({rows[0]["pid"], second[0]["pid"], owner_results(builds[c][1])[0]["pid"]}), 3)
            commands = [r for r in owner_results(builds[a][1]) if r["action"] == "action.command"]
            self.assertEqual([r["parameter"] for r in commands], ["first", "first"])
            self.assertEqual(len({pa.rpc("inspect")["pid"], pb2.rpc("inspect")["pid"], pc.rpc("inspect")["pid"]}), 3)
        try:
            wait_until(lambda: all(self.discovery.read(p) is None for p in (a,b,c)), timeout=5)
        except AssertionError:
            self.fail(repr([self.discovery.read(p) for p in (a,b,c)]) +
                      repr([(p, str(file.read_text()) if file.is_file() else None)
                            for p in (a,b,c) for file in [builds[p][1] / "bin/owner-stops.txt"]]) +
                      repr([p.process.returncode for p in (pa,pb,pb2,pc)]) +
                      repr(old_b) +
                      "\n".join(p.log_path.read_text(encoding="utf-8")[-2500:] for p in (pa,pb2,pc)))
