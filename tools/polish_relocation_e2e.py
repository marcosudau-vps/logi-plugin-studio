"""AP-POLISH-001 mandatory test 7.6 against the REAL Logi Plugin Service.

1. Unzip the Portable edition to location 1 (no Python on PATH for the Studio).
2. The FROZEN Studio builds a native plugin and two Shared plugins (owner A with
   a trusted handler, consumer B with an external reference to A's action) and
   installs them (directory method, documented per-plugin reload).
3. No Studio process runs. Each plugin's host must have been started by the
   Logi Plugin Service from the plugin's OWN runtime directory; Python
   callbacks, the C# bridge session and the Shared peer link are checked.
4. The portable Studio folder is moved to location 2; all three plugins are
   reloaded through the service; hosts, callbacks and the peer link (rejoin)
   are checked again.
5. The Studio is started from location 2 (diagnosis + full self-test).
6. Cleanup: the Studio (location 2) uninstalls the three plugins, the test
   pairing is removed, and the Logitech plugin directory is compared with its
   state before the test (foreign entries byte-identical).

Writes one JSON evidence file. Never touches foreign plugins or profiles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src")]

from adapters.logitech import service  # noqa: E402
from adapters.logitech.deployment import plugin_directory  # noqa: E402
from extensions.shared_folders.pairing import PairingStore, project_offers  # noqa: E402
from extensions.shared_folders.peer_runtime import Scope  # noqa: E402
from runtime.wire import ConnectionSettings, HostError, LocalClient  # noqa: E402

PLUGINS = {"native": "polish.e2e.native", "alpha": "polish.e2e.alpha", "beta": "polish.e2e.beta"}
MODES = {"native": "native", "alpha": "shared", "beta": "shared"}
FIXTURE = ROOT / "tests" / "fixtures" / "ap_shared_final_001" / "owner.py"


def inventory(root: Path) -> dict:
    rows = {}
    for entry in sorted(root.iterdir()):
        if entry.is_file():
            rows[entry.name] = hashlib.sha256(entry.read_bytes()).hexdigest()
        else:
            rows[entry.name + "/"] = sorted(p.relative_to(entry).as_posix() for p in entry.rglob("*") if p.is_file())[:50]
    return rows


def studio_env(data: Path) -> dict:
    windows = Path(os.environ["SystemRoot"])
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
    env["PATH"] = os.pathsep.join([str(windows / "System32"), str(windows), r"C:\Program Files\dotnet"])
    env.update(QT_QPA_PLATFORM="offscreen", LOGI_STUDIO_DATA=str(data), DOTNET_CLI_TELEMETRY_OPTOUT="1",
               DOTNET_NOLOGO="1")
    env.pop("LOGI_SHARED_PYTHON", None)
    env.pop("LOGI_STUDIO_HOST_RUNTIME", None)
    env.pop("LOGI_SHARED_HOME", None)
    return env


def run_studio(exe: Path, args: list[str], out: Path, env: dict, timeout: int = 900) -> tuple[int, dict]:
    result = subprocess.run([str(exe), *args, "--out", str(out)], env=env, timeout=timeout,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        return result.returncode, json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return result.returncode, {"raw_output": result.stdout.decode("utf-8", "replace")[-3000:]}


def processes(pattern: str) -> list[dict]:
    script = ("$all = Get-CimInstance Win32_Process; $by = @{}; foreach ($p in $all) { $by[[int]$p.ProcessId] = $p }; "
              f"$all | Where-Object {{ $_.ExecutablePath -like '{pattern}' }} | ForEach-Object {{ "
              "$parent = $by[[int]$_.ParentProcessId]; $grand = if ($parent) { $by[[int]$parent.ParentProcessId] } else { $null }; "
              "[pscustomobject]@{ pid = $_.ProcessId; exe = $_.ExecutablePath; parent = $_.ParentProcessId; "
              "parent_name = if ($parent) { $parent.Name } else { $null }; "
              "grandparent_name = if ($grand) { $grand.Name } else { $null } } } | ConvertTo-Json -Compress")
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                         capture_output=True, text=True, timeout=120).stdout.strip()
    if not out:
        return []
    rows = json.loads(out)
    return rows if isinstance(rows, list) else [rows]


def wait(check, timeout=60.0, step=0.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(step)
    return None


class E2E:
    def __init__(self, args):
        self.args = args
        self.work = args.work.resolve()
        self.data = self.work / "studio-data"
        self.loc1 = self.work / "D_Programme" / "LogiStudio"
        self.loc2 = self.work / "E_Tools" / "LogiStudio"
        self.report = {"format": "polish-relocation-e2e-1", "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "zip": str(args.zip), "steps": []}
        self.names, self.packages, self.installed = {}, {}, {}

    def step(self, name, fn):
        started = time.time()
        try:
            detail = fn()
            self.report["steps"].append({"step": name, "result": "PASS", "seconds": round(time.time() - started, 1),
                                         "detail": detail})
            return detail
        except Exception as exc:
            self.report["steps"].append({"step": name, "result": "FAIL", "seconds": round(time.time() - started, 1),
                                         "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc(limit=5)})
            return None

    @property
    def exe(self):
        return (self.loc2 if self.loc2.exists() else self.loc1) / "LogiPluginStudio.exe"

    # -- steps ---------------------------------------------------------------
    def prepare(self):
        if self.work.exists():
            raise RuntimeError("work directory must be fresh")
        self.loc1.parent.mkdir(parents=True)
        with zipfile.ZipFile(self.args.zip) as archive:
            top = {n.split("/")[0] for n in archive.namelist()}
            assert len(top) == 1, top
            archive.extractall(self.loc1.parent)
        (self.loc1.parent / top.pop()).rename(self.loc1)
        self.before = inventory(plugin_directory())
        self.report["plugins_before"] = self.before
        assert not any(k.startswith(("StudioPolishE2e", "polish.e2e")) for k in self.before), "test leftovers present"
        sample = json.loads((ROOT / "examples/project_logitech_native_v1.json").read_text(encoding="utf-8"))
        for key, plugin in PLUGINS.items():
            raw = json.loads(json.dumps(sample))
            raw["plugin"]["id"] = plugin
            raw["plugin"]["display_name"] = "Polish E2E " + key
            raw["folders"][0]["entries"][0]["action_parameter"] = "first"
            path = self.work / "projects" / key / "project.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
            shutil.copyfile(FIXTURE, path.parent / "owner.py")
        from studio.virtual_folders.binding import extension_path, project_identity
        from studio.virtual_folders.codec import encode
        from studio.virtual_folders.model import Document, Reference
        beta = self.work / "projects" / "beta" / "project.json"
        document = Document.create(project_identity(beta), PLUGINS["beta"])
        document, placement = document.add_action(document.root_id, Reference(PLUGINS["alpha"], "action.command"),
                                                  action_parameter="first")
        extension_path(beta).write_bytes(encode(document))
        return {"location_1": str(self.loc1), "files": sum(1 for _ in self.loc1.rglob("*")),
                "external_placement": placement}

    def build_all(self):
        env = studio_env(self.data)
        results = {}
        for key in PLUGINS:
            project = self.work / "projects" / key / "project.json"
            handler = ["--handler", "owner.py"] if key in ("native", "alpha") else []
            code, row = run_studio(self.exe, ["--build", str(project), "--mode", MODES[key], *handler],
                                   self.work / f"build-{key}.json", env)
            assert code == 0 and row.get("ok"), row
            assert row["host_runtime"]["status"] == "PLUGIN_LOCAL", row["host_runtime"]
            record = (Path(row["package"]) / "bin" / "studio.host-runtime.json").read_text(encoding="utf-8")
            assert str(self.loc1).lower() not in record.lower(), "Studio path leaked into the package"
            self.packages[key] = Path(row["package"])
            self.names[key] = service.package_plugin_name(row["package"])
            results[key] = {k: row[k] for k in ("studio", "executable", "folder_mode", "plugin_id", "host_runtime")}
        return results

    def pair(self):
        store = PairingStore()
        alpha_raw = json.loads((self.work / "projects" / "alpha" / "project.json").read_text(encoding="utf-8"))
        scope = Scope("action", "action.command", "first")
        store.pair(PLUGINS["alpha"], PLUGINS["beta"])
        store.grant(PLUGINS["alpha"], PLUGINS["beta"], scope, ["command"], offers=project_offers(alpha_raw))
        return {"key_storage": {p: store.key_storage(p) for p in (PLUGINS["alpha"], PLUGINS["beta"])},
                "grant": scope.wire()}

    def install_all(self):
        env = studio_env(self.data)
        results = {}
        for key, plugin in PLUGINS.items():
            code, row = run_studio(self.exe, ["--install", str(self.packages[key]), "--confirm", plugin],
                                   self.work / f"install-{key}.json", env)
            assert code == 0 and row.get("ok"), {k: row.get(k) for k in ("status", "error", "steps")}
            self.installed[key] = Path(row["loaded_from"])
            results[key] = {"status": row["status"], "loaded_from": row["loaded_from"],
                            "runtime": next((s for s in row["steps"] if s["step"] == "host_runtime"), None)}
        return results

    def no_studio_running(self):
        rows = processes("*\\LogiPluginStudio.exe")
        assert not rows, rows
        return {"studio_processes": 0}

    def observe(self, label, previous=None):
        result = {}
        for key, plugin in PLUGINS.items():
            target = self.installed[key]
            hosts = wait(lambda: processes(str(target / "bin" / "hostruntime-*" / "LogiPluginStudioHost.exe")), 60)
            assert hosts and len(hosts) == 1, f"{key}: expected one plugin-local host, got {hosts}"
            host = hosts[0]
            assert "logiplugin" in str(host["parent_name"]).lower() or "logiplugin" in str(host["grandparent_name"]).lower(), host
            if previous:
                assert host["pid"] != previous[key]["host"]["pid"], "host was not restarted by the reload"
            client = LocalClient(ConnectionSettings.load(target / "bin" / "studio.connection.json"), timeout=5)
            wait(lambda: _try(client.handshake), 30)
            row = {"host": host}
            if key in ("native", "alpha"):
                results = target / "bin" / "owner-results.jsonl"
                before = len(results.read_text(encoding="utf-8").splitlines()) if results.exists() else 0
                client.command("action.command", action_parameter="first")
                rows = wait(lambda: results.exists() and len(results.read_text(encoding="utf-8").splitlines()) > before
                            and results.read_text(encoding="utf-8").splitlines(), 20)
                assert rows, f"{key}: no Python callback"
                last = json.loads(rows[-1])
                assert last["pid"] == host["pid"], (last, host)
                row["callback"] = last
            result[key] = row
        store = PairingStore()
        link = wait(lambda: store.status(PLUGINS["alpha"])["peers"].get(PLUGINS["beta"], {}).get("connected")
                    and store.status(PLUGINS["beta"])["peers"].get(PLUGINS["alpha"], {}).get("connected"), 90, 1)
        status_a, status_b = store.status(PLUGINS["alpha"]), store.status(PLUGINS["beta"])
        assert link, (status_a, status_b)
        assert status_a["sdk_attached"] and status_b["sdk_attached"], (status_a, status_b)
        result["shared_link"] = {"alpha": {k: status_a[k] for k in ("online", "sdk_attached", "peers")},
                                 "beta": {k: status_b[k] for k in ("online", "sdk_attached", "peers")}}
        # The native C# bridge keeps its own session: after our session idled out (> 60 s)
        # the host's heartbeat still counts >= 1 session.
        log = Path(os.environ["LOCALAPPDATA"]) / "LogiPluginStudio" / "HostLogs" / (PLUGINS["native"] + ".log")
        mark = time.time()
        time.sleep(75)
        beats = [line for line in log.read_text(encoding="utf-8", errors="replace").splitlines() if "heartbeat" in line]
        sessions = int(re.search(r"sessions=(\d+)", beats[-1]).group(1)) if beats else 0
        assert sessions >= 1, beats[-3:]
        result["native_bridge_heartbeat"] = {"last": beats[-1], "waited_s": round(time.time() - mark)}
        self.report.setdefault("observations", {})[label] = result
        return result

    def move(self):
        self.loc2.parent.mkdir(parents=True)
        os.rename(self.loc1, self.loc2)
        assert not self.loc1.exists() and (self.loc2 / "LogiPluginStudio.exe").is_file()
        return {"from": str(self.loc1), "to": str(self.loc2)}

    def reload_all(self):
        since = time.time() - 1
        results = {}
        for key in PLUGINS:
            service.request_plugin_reload(self.names[key])
        for key in PLUGINS:
            diagnosis = wait(lambda: (d := service.diagnose_plugin_load(self.names[key], self.installed[key], since=since))
                             ["status"] in ("LOADED", "LOAD_FAILED") and d, 60, 1)
            assert diagnosis and diagnosis["status"] == "LOADED", diagnosis
            results[key] = diagnosis["status"]
        return results

    def studio_from_new_location(self):
        env = studio_env(self.data)
        code, _ = run_studio(self.exe, ["--diagnose"], self.work / "diagnose-loc2.txt", env, timeout=300)
        text = (self.work / "diagnose-loc2.txt").read_text(encoding="utf-8")
        assert str(self.loc2) in text, "diagnosis does not show the new location"
        assert "hostruntime" in text and "FEHLT" not in text.split("Host-Laufzeit für Plugins:")[1].splitlines()[0]
        for key in PLUGINS:
            assert f"{PLUGINS[key]} (directory): PLUGIN_LOCAL" in text, text
        work = self.work / "selftest-loc2"
        result = subprocess.run([str(self.exe), "--selftest", "--work", str(work), "--out", str(work / "report.json")],
                                env=env, timeout=1200)
        report = json.loads((work / "report.json").read_text(encoding="utf-8"))
        assert result.returncode == 0 and report["failed"] == 0, [c for c in report["checks"] if c["result"] == "FAIL"]
        return {"diagnose_exit": code, "selftest": {k: report[k] for k in ("executable", "passed", "expected_refusals",
                                                                            "failed", "total")}}

    def cleanup(self):
        env = studio_env(self.data)
        results = {}
        for key, plugin in PLUGINS.items():
            if key not in self.installed:
                continue
            code, row = run_studio(self.exe, ["--uninstall", plugin, "--confirm", plugin, "--name", self.names[key]],
                                   self.work / f"uninstall-{key}.json", env)
            results[key] = {"exit": code, "removed": row.get("removed"), "residual_files": row.get("residual_files"),
                            "directory_removed": row.get("directory_removed"), "profile_note": row.get("profile_note"),
                            "error": row.get("error")}
        store = PairingStore()
        try:
            store.unpair(PLUGINS["alpha"], PLUGINS["beta"])
        except Exception as exc:
            results["unpair"] = str(exc)
        for plugin in PLUGINS.values():
            policy = store.config_dir / (plugin + ".json")
            if policy.exists() and json.loads(policy.read_text(encoding="utf-8")) == {"peers": {}}:
                policy.unlink()
        leftover = wait(lambda: not any(processes(str(t / "bin" / "hostruntime-*" / "*")) for t in self.installed.values())
                        or None, 30)
        results["no_host_processes_left"] = bool(leftover)
        after = inventory(plugin_directory())
        changed = {k: (self.before.get(k), after.get(k)) for k in set(self.before) | set(after)
                   if self.before.get(k) != after.get(k)}
        # Studio keeps data the plugins wrote themselves (by design). These are the
        # TEST plugins' own result files: keep them as evidence, then remove them.
        results["plugin_data_kept_by_studio"] = changed
        evidence = self.args.out.parent / (self.args.out.stem + "-artifacts")
        evidence.mkdir(parents=True, exist_ok=True)
        local = Path(os.environ["LOCALAPPDATA"])
        shared = local / "LogiPluginStudio" / "SharedFolders"
        for key, target in self.installed.items():
            files = sorted(p for p in target.rglob("*") if p.is_file()) if target.exists() else []
            if files and {p.relative_to(target).as_posix() for p in files} <= {"bin/owner-results.jsonl",
                                                                              "bin/owner-stops.txt", "bin/callbacks.jsonl"}:
                for file in files:
                    shutil.copyfile(file, evidence / f"{key}-{file.name}")
                shutil.rmtree(target)
        for plugin in PLUGINS.values():
            digest = hashlib.sha256(plugin.encode()).hexdigest() + ".json"
            for source in (shared / "logs" / f"{plugin}.log", local / "LogiPluginStudio" / "HostLogs" / f"{plugin}.log"):
                if source.exists():
                    shutil.copyfile(source, evidence / f"{source.parent.name}-{source.name}")
                    source.unlink()
            for sub in ("status", "discovery"):
                (shared / sub / digest).unlink(missing_ok=True)
        final = inventory(plugin_directory())
        results["plugin_directory_identical_to_before"] = final == self.before
        assert final == self.before, {k: (self.before.get(k), final.get(k)) for k in set(self.before) | set(final)
                                      if self.before.get(k) != final.get(k)}
        assert leftover, "plugin host processes still running after uninstall"
        return results


def _try(fn):
    try:
        return fn() or True
    except HostError:
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    test = E2E(args)
    ok = test.step("prepare_portable_location_1", test.prepare) is not None
    if ok:
        ok = test.step("frozen_studio_builds_native_and_shared", test.build_all) is not None
    if ok:
        ok = test.step("pair_shared_with_protected_keys", test.pair) is not None
    if ok:
        ok = test.step("frozen_studio_installs_into_real_service", test.install_all) is not None
    if ok:
        test.step("studio_fully_closed", test.no_studio_running)
        ok = test.step("plugins_run_without_studio", lambda: test.observe("before_move")) is not None
        previous = test.report.get("observations", {}).get("before_move")
        test.step("move_portable_studio_folder", test.move)
        test.step("service_reload_after_move", test.reload_all)
        test.step("plugins_and_peers_after_move_and_reload", lambda: test.observe("after_move", previous))
        test.step("studio_starts_from_new_location", test.studio_from_new_location)
    test.step("cleanup_uninstall_and_compare", test.cleanup)
    test.report["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    test.report["summary"] = {s["step"]: s["result"] for s in test.report["steps"]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(test.report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(test.report["summary"], indent=2))
    return 0 if all(s["result"] == "PASS" for s in test.report["steps"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
