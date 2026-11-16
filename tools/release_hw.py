"""AP-RELEASE-FINAL-001 hardware session tooling (own test plugins only).

Subcommands (all output JSON):
  prepare   build isolated test plugins (native N, Shared A owner, Shared B consumer),
            pair A<->B and grant exactly A's command[p1] and toggle to B. No installation.
  install   install/update the prepared own plugins (link + documented per-plugin reload + diagnosis)
  host      start (detached) or stop the trusted native Python host for plugin N
  status    load diagnosis, connections, shared peer status, callback counters
  mark      start a correlated test step (ID, expectation); prints the step record
  check     close a step: user answer + automatically collected callbacks/log lines -> PASS/FAIL
  reload    request the SDK reload deep link for one own plugin (N, A or B)
  cleanup   uninstall own links via receipts, stop host, unpair; verify foreign links unchanged
Run directory: work/release-final/AP-RELEASE-FINAL-001/outputs/hardware/<run>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from adapters.logitech import deployment, service, workflow
from adapters.logitech.gate import DEFAULT_MANIFEST_DIR
from adapters.logitech.host_runtime import host_command, native_host_bundle
from adapters.logitech.product import build_product, generate_product, provision_connection
from extensions.shared_folders.pairing import PairingStore, project_offers
from extensions.shared_folders.peer_runtime import Scope
from extensions.shared_folders.runtime_projection import initial_layout
from runtime.wire import json_bytes
from symbol_designer.ict import IconTemplate, new_template_data

WORK = ROOT / "work" / "release-final" / "AP-RELEASE-FINAL-001"
BASE = WORK / "outputs" / "hardware"
IDS = {"N": ("studio.release.native", "StudioRelNativePlugin"),
       "A": ("studio.release.a", "StudioRelAPlugin"),
       "B": ("studio.release.b", "StudioRelBPlugin")}
RECORDER = '''"""Trusted hardware-test handler: records every SDK callback with a timestamp."""
import json, os, time
from pathlib import Path


def register(host):
    def record(payload, context):
        row = dict(time=time.time(), component=context.component_id, placement=context.placement_id,
                   parameter=context.action_parameter, operation=context.operation,
                   diff=context.adjustment_diff, command=context.command_id, pid=os.getpid())
        with Path("callbacks.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps(row) + "\\n")
        return {"ok": True}
    host.register_handler("handler.main", "invoke", record)
'''


def png(width, height, rgba, mark=None):
    import struct
    import zlib
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            inside = mark and mark[0] <= x < mark[2] and mark[1] <= y < mark[3]
            row += bytes((255, 255, 255, 255) if inside else rgba)
        rows.append(b"\0" + bytes(row))
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def sdk_name(info):
    return service.package_plugin_name(info["package"])


def emit(value):
    print(json.dumps(value, indent=2, ensure_ascii=True, default=str))


def run_dir(name):
    return BASE / name


def write_assets(directory: Path, color, label):
    assets = directory / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "command.png").write_bytes(png(80, 80, color, (20, 20, 60, 60)))
    (assets / "toggle-off.png").write_bytes(png(80, 80, (70, 70, 70, 255), (30, 30, 50, 50)))
    (assets / "toggle-on.png").write_bytes(png(80, 80, (20, 190, 70, 255), (10, 10, 70, 70)))
    (assets / "symbol.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
                                       '<circle cx="12" cy="12" r="10" fill="#E67E22"/></svg>', encoding="utf-8")
    template = IconTemplate(new_template_data(label))
    template.background = 0xFF8E44AD
    template.save(assets / "command.ict")
    default = IconTemplate(new_template_data(""))
    default.background = 0xFF1F3A5F
    default.save(assets / "default.ict")


def project(plugin_id, display, *, parameters=10, color=(30, 120, 220, 255), label="REL"):
    params = [{"name": f"p{i}", "display_name": f"Parameter {i}", "group_name": "Parameter"}
              for i in range(1, parameters + 1)]
    entries = [{"id": f"placement.p{i}", "action": "action.command", "position": i - 1, "action_parameter": f"p{i}"}
               for i in range(1, parameters + 1)]
    entries.insert(1, {"id": "placement.toggle", "action": "action.toggle", "position": 0})
    for position, entry in enumerate(entries):
        entry["position"] = position
    return {
        "schema_version": "logitech-native-1",
        "plugin": {"id": plugin_id, "display_name": display, "default_icon_template": "assets/default.ict"},
        "handlers": [{"id": "handler.main", "callback_id": "handler.main"}],
        "actions": [
            {"id": "action.command", "sdk_type": "PluginDynamicCommand", "display_name": f"{display} Befehl",
             "description": "Release-Hardwaretest: Parameterübergabe an Python", "group_name": display,
             "handler": "handler.main", "parameters": params, "icon": "assets/command.png",
             "icon_template": "assets/command.ict", "symbol": "assets/symbol.svg"},
            {"id": "action.toggle", "sdk_type": "PluginMultistateDynamicCommand", "display_name": f"{display} Schalter",
             "group_name": display, "handler": "handler.main", "state_change": "toggle",
             "states": [{"index": 0, "name": "off", "display_name": "AUS", "description": "aus", "image": "assets/toggle-off.png"},
                        {"index": 1, "name": "on", "display_name": "AN", "description": "an", "image": "assets/toggle-on.png"}]},
        ],
        "folders": [{"id": "folder.main", "display_name": f"{display} Ordner", "navigation": "ButtonArea",
                     "entries": entries}],
    }


def build(directory: Path, raw: dict, assembly: str, mode: str, *, layout=None, references=None, handler=True):
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "project.json"
    source.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    (directory / "handler.py").write_text(RECORDER, encoding="utf-8")
    out = directory / "build"
    plan = generate_product(source, output_dir=out, assembly_name=assembly, folder_mode=mode,
                            folder_runtime=layout, shared_references=references,
                            shared_handler="handler.py" if mode == "shared" and handler else None)
    result = build_product(plan, out, log_path=directory / "sdk-build.log")
    connection = provision_connection(plan, out)
    package = deployment.prepare_package(plan, out, connection)
    info = {"plugin_id": plan.plugin_id, "assembly": plan.assembly_name, "mode": mode, "package": str(package),
            "connection": str(connection), "output": str(out), "dll_sha256": result.dll_sha256}
    if mode != "shared":
        bundle = directory / "native-host.pyz"
        handler_bytes = (directory / "handler.py").read_bytes() if handler else None
        bundle.write_bytes(native_host_bundle(raw, None, mode, DEFAULT_MANIFEST_DIR, handler_bytes))
        info["host_bundle"] = str(bundle)
    return info


def consumer_layout(raw, owner):
    layout, _ = initial_layout(raw)
    folder = layout["folders"][0]
    root = folder["nodes"][0]
    sub = {"id": "node.sub", "label": "Unterordner B", "pages": [{"id": "page.sub", "entries": [
        {"id": "placement.sub.toggle", "kind": "action", "label": "B Schalter", "action_id": "action.toggle"},
        {"id": "placement.sub.p2", "kind": "action", "label": "B p2", "action_id": "action.command", "action_parameter": "p2"}]}]}
    folder["nodes"].append(sub)
    entries = root["pages"][0]["entries"]
    remote = [
        {"id": "placement.remote.cmd", "kind": "unavailable", "label": "A Befehl (fremd)", "reason": "EXTERNAL_REFERENCE_OFFLINE"},
        {"id": "placement.remote.toggle", "kind": "unavailable", "label": "A Schalter (fremd)", "reason": "EXTERNAL_REFERENCE_OFFLINE"},
        {"id": "placement.link.sub", "kind": "folder", "label": "Unterordner B", "target_id": "node.sub"},
    ]
    root["pages"][0]["entries"] = remote + entries[:4]
    root["pages"].append({"id": "page.2", "entries": entries[4:]})
    references = [dict(placement="placement.remote.cmd", plugin=owner, scope=Scope("action", "action.command", "p1").wire()),
                  dict(placement="placement.remote.toggle", plugin=owner, scope=Scope("action", "action.toggle").wire())]
    return layout, references


def prepare(args):
    run = run_dir(args.run)
    if run.exists():
        raise SystemExit(f"run directory exists: {run}")
    run.mkdir(parents=True)
    links = {r["link"]: r for r in deployment.inventory()}
    names = {p.stem for p in (service.service_data_dir() / "Plugins").iterdir()} | {
        p.stem for p in (service.service_data_dir() / "Logs" / "plugin_logs").glob("*.log")}
    # Existing entries are acceptable only if they are this Studio plugin (update).
    owned = {r["link"]: r["plugin_id"] for r in links.values() if r["studio_owned"]}
    collisions = [(key, pid, asm) for key, (pid, asm) in IDS.items()
                  for name in (pid + ".link", asm.removesuffix("Plugin"))
                  if name in links and owned.get(name) != pid]
    if collisions:
        raise SystemExit(f"identity collision, refusing: {collisions}")
    env = service.detect_prerequisites().as_dict()
    devices = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'VID_046D&PID_C354' } | "
                              "Select-Object Status,Class,FriendlyName,InstanceId | ConvertTo-Json -Compress"],
                             capture_output=True, text=True, timeout=60).stdout
    snapshot = {"time": time.time(), "prerequisites": env, "mx_creative_keypad_pnp": json.loads(devices or "[]"),
                "links_before": {k: hashlib.sha256((service.service_data_dir() / "Plugins" / k).read_bytes()).hexdigest()
                                 for k, r in links.items() if r.get("kind") == "link"},
                "directories_before": sorted(k for k, r in links.items() if r.get("kind") == "directory")}
    (run / "environment-before.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    plugins = {}
    for key, color in (("N", (30, 120, 220, 255)), ("A", (200, 60, 40, 255))):
        pid, assembly = IDS[key]
        display = {"N": "Release Nativ", "A": "Release A"}[key]
        directory = run / key
        write_assets(directory, color, {"N": "NAT", "A": "A"}[key])
        plugins[key] = build(directory, project(pid, display, color=color), assembly,
                             "native" if key == "N" else "shared")
    pid_b, assembly_b = IDS["B"]
    raw_b = project(pid_b, "Release B", color=(240, 190, 20, 255), parameters=8)
    directory = run / "B"
    write_assets(directory, (240, 190, 20, 255), "B")
    layout, references = consumer_layout(raw_b, IDS["A"][0])
    plugins["B"] = build(directory, raw_b, assembly_b, "shared", layout=layout, references=references)
    store = PairingStore()
    a, b = IDS["A"][0], IDS["B"][0]
    if store.is_paired(a, b):
        store.unpair(a, b)
    store.pair(a, b)
    raw_a = json.loads((run / "A" / "project.json").read_text(encoding="utf-8"))
    offers = project_offers(raw_a, initial_layout(raw_a)[0])
    store.grant(a, b, Scope("action", "action.command", "p1"), ["command"], offers=offers)
    store.grant(a, b, Scope("action", "action.toggle"), ["command"], offers=offers)
    plans = {key: deployment.plan_install(info["package"]) for key, info in plugins.items()}
    state = {"run": str(run), "plugins": plugins, "plans": plans, "pairing": {"pairs": [[a, b]],
             "grants": [g.describe() for g in store.grants(a)]}, "steps": []}
    (run / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    emit({"prepared": str(run), "plugins": {k: v["package"] for k, v in plugins.items()},
          "plans": {k: v["operation"] for k, v in plans.items()}, "grants": state["pairing"]["grants"]})


def pair(args):
    """(Re)create pairing A<->B and the exact grants; separate step so it can run
    outside an app-container/MSIX context that would virtualise %LOCALAPPDATA%."""
    state = load_state(args.run)
    store = PairingStore()
    a, b = IDS["A"][0], IDS["B"][0]
    if store.is_paired(a, b):
        store.unpair(a, b)
    store.pair(a, b)
    raw_a = json.loads((run_dir(args.run) / "A" / "project.json").read_text(encoding="utf-8"))
    offers = project_offers(raw_a, initial_layout(raw_a)[0])
    store.grant(a, b, Scope("action", "action.command", "p1"), ["command"], offers=offers)
    store.grant(a, b, Scope("action", "action.toggle"), ["command"], offers=offers)
    result = {"home": str(store.home), "grants": [g.describe() for g in store.grants(a)],
              "check_a": store.check(a), "check_b": store.check(b)}
    state["pairing"] = result
    save_state(args.run, state)
    emit(result)


def load_state(run):
    return json.loads((run_dir(run) / "state.json").read_text(encoding="utf-8"))


def save_state(run, state):
    (run_dir(run) / "state.json").write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def install(args):
    state = load_state(args.run)
    results = {}
    for key in args.plugins.split(","):
        info = state["plugins"][key]
        receipts = run_dir(args.run) / "receipts" / f"{key}-{time.strftime('%Y%m%d-%H%M%S')}"
        _, live = workflow.plan(info["package"])
        result = workflow.install_and_verify(info["package"], confirm_plugin_id=info["plugin_id"], receipt_dir=receipts,
                                             expected_plan=live, reload=not args.no_reload, load_timeout=args.timeout,
                                             rollback_on_failure=not args.keep_on_failure)
        info.setdefault("installs", []).append(result.as_dict())
        info["receipt"] = result.receipt
        info["installed_dir"] = result.loaded_from
        results[key] = result.status
    save_state(args.run, state)
    emit(results)


def host(args):
    state = load_state(args.run)
    info = state["plugins"]["N"]
    pid_file = run_dir(args.run) / "N" / "host.pid"
    if args.action == "start":
        log = (run_dir(args.run) / "N" / "native-host.log").open("ab")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0) | \
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        process = subprocess.Popen(host_command(info["host_bundle"], info["connection"]), stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, cwd=str(Path(info["connection"]).parent),
                                   creationflags=flags)
        pid_file.write_text(str(process.pid))
        emit({"host": "started", "pid": process.pid})
    else:
        pid = int(pid_file.read_text()) if pid_file.exists() else None
        if pid:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            pid_file.unlink()
        emit({"host": "stopped", "pid": pid})


def callbacks(state):
    rows = []
    for key, info in state["plugins"].items():
        path = Path(info["connection"]).parent / "callbacks.jsonl"
        if key in ("A", "B"):
            path = Path(info.get("installed_dir") or info["package"]) / "bin" / "callbacks.jsonl"
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    rows.append(dict(json.loads(line), plugin=key))
                except ValueError:
                    pass
    return sorted(rows, key=lambda r: r["time"])


def status(args):
    state = load_state(args.run)
    store = PairingStore()
    result = {}
    for key, info in state["plugins"].items():
        name = sdk_name(info)
        item = {"load": service.diagnose_plugin_load(name, info.get("installed_dir") or info["package"], since=args.since)["status"],
                "events": [e["message"][:160] for e in service.plugin_log_lines(name, since=args.since)][-6:]}
        ws = workflow.WorkflowState(info["plugin_id"], info["package"], name)
        item["connection"] = workflow.check_connection(ws, workflow.ServiceAdapter(), timeout=2)
        if info["mode"] == "shared":
            item["shared_status"] = store.status(info["plugin_id"])
            item["shared_hosts"] = service.shared_host_processes(Path(info.get("installed_dir") or info["package"]) / "bin" / "studio.connection.json")
        result[key] = item
    rows = callbacks(state)
    result["callbacks_total"] = len(rows)
    result["callbacks_last"] = rows[-5:]
    emit(result)


def mark(args):
    state = load_state(args.run)
    step = {"id": args.id, "expect": args.expect, "started": time.time(), "callbacks_before": len(callbacks(state))}
    state["steps"].append(step)
    save_state(args.run, state)
    emit(step)


def check(args):
    state = load_state(args.run)
    step = next(s for s in reversed(state["steps"]) if s["id"] == args.id)
    rows = [r for r in callbacks(state) if r["time"] >= step["started"]]
    logs = {}
    for key, info in state["plugins"].items():
        logs[key] = [e["message"][:200] for e in service.plugin_log_lines(sdk_name(info), since=step["started"])][-8:]
    expected = json.loads(args.callbacks) if args.callbacks else None
    auto_ok = True
    if expected is not None:
        got = [{k: r.get(k) for k in expected[0]} for r in rows] if expected else []
        auto_ok = all(any(all(g.get(k) == v for k, v in e.items()) for g in got) for e in expected) if expected else not rows
    answer = (args.answer or "").strip().lower()
    user_ok = answer in ("ja", "yes", "j", "y") if args.answer is not None else None
    verdict = "PASS" if auto_ok and user_ok is not False else "FAIL"
    step.update(finished=time.time(), answer=args.answer, observed_callbacks=rows, logs=logs,
                expected_callbacks=expected, auto_ok=auto_ok, user_ok=user_ok, verdict=verdict, note=args.note)
    save_state(args.run, state)
    emit({k: step[k] for k in ("id", "verdict", "auto_ok", "user_ok", "observed_callbacks", "logs", "note")})


def reload_plugin(args):
    state = load_state(args.run)
    info = state["plugins"][args.plugin]
    since = time.time() - 1
    result = service.request_plugin_reload(sdk_name(info))
    time.sleep(args.wait)
    result["diagnosis"] = service.diagnose_plugin_load(sdk_name(info), info.get("installed_dir") or info["package"], since=since)
    emit(result)


def cleanup(args):
    state = load_state(args.run)
    out = {}
    pid_file = run_dir(args.run) / "N" / "host.pid"
    if pid_file.exists():
        subprocess.run(["taskkill", "/PID", pid_file.read_text().strip(), "/T", "/F"], capture_output=True)
        pid_file.unlink()
    for key, info in state["plugins"].items():
        try:
            out[key] = workflow.uninstall(info["plugin_id"], confirm_plugin_id=info["plugin_id"], method="directory",
                                          plugin_name=sdk_name(info),
                                          receipt_dir=run_dir(args.run) / "receipts" / f"uninstall-{key}-{int(time.time())}")
        except Exception as exc:
            out[key] = {"error": str(exc)}
    store = PairingStore()
    a, b = IDS["A"][0], IDS["B"][0]
    if store.is_paired(a, b):
        store.unpair(a, b)
    before = json.loads((run_dir(args.run) / "environment-before.json").read_text(encoding="utf-8"))["links_before"]
    plugins = service.service_data_dir() / "Plugins"
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in plugins.glob("*.link")}
    out["links_restored_exactly"] = after == before
    out["own_directories_left"] = sorted(p.name for p in plugins.iterdir() if p.is_dir()
                                         and p.name in {sdk_name(i) for i in state["plugins"].values()})
    out["links_diff"] = {k: (before.get(k), after.get(k)) for k in set(before) | set(after) if before.get(k) != after.get(k)}
    state["cleanup"] = out
    save_state(args.run, state)
    emit(out)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare"); p.add_argument("--run", required=True); p.set_defaults(fn=prepare)
    p = sub.add_parser("pair"); p.add_argument("--run", required=True); p.set_defaults(fn=pair)
    p = sub.add_parser("install"); p.add_argument("--run", required=True); p.add_argument("--plugins", default="N,A,B")
    p.add_argument("--no-reload", action="store_true"); p.add_argument("--timeout", type=float, default=25)
    p.add_argument("--keep-on-failure", action="store_true"); p.set_defaults(fn=install)
    p = sub.add_parser("host"); p.add_argument("--run", required=True); p.add_argument("action", choices=("start", "stop"))
    p.set_defaults(fn=host)
    p = sub.add_parser("status"); p.add_argument("--run", required=True); p.add_argument("--since", type=float, default=0)
    p.set_defaults(fn=status)
    p = sub.add_parser("mark"); p.add_argument("--run", required=True); p.add_argument("--id", required=True)
    p.add_argument("--expect", required=True); p.set_defaults(fn=mark)
    p = sub.add_parser("check"); p.add_argument("--run", required=True); p.add_argument("--id", required=True)
    p.add_argument("--answer"); p.add_argument("--callbacks"); p.add_argument("--note"); p.set_defaults(fn=check)
    p = sub.add_parser("reload"); p.add_argument("--run", required=True); p.add_argument("--plugin", required=True)
    p.add_argument("--wait", type=float, default=6); p.set_defaults(fn=reload_plugin)
    p = sub.add_parser("cleanup"); p.add_argument("--run", required=True); p.set_defaults(fn=cleanup)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
