"""LogiPluginStudio.exe – end-user entry point (also usable from sources).

Default: the SDK-native Studio shell (optional project path argument).
``--legacy``    the historical 0.1-draft editor.
``--diagnose``  write a prerequisite report (``--out``), exit 0/1.
``--selftest``  scripted end-to-end check of the portable edition (``--work``, ``--out``).
``--build`` / ``--install`` / ``--uninstall``  scriptable Studio operations (see automation.py).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def _report_path(value):
    if value:
        return Path(value)
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LogiPluginStudio"
    base.mkdir(parents=True, exist_ok=True)
    return base / "diagnose.txt"


def diagnose(out) -> int:
    from adapters.logitech.host_runtime import studio_runtime_dir
    from adapters.logitech.service import detect_prerequisites
    from studio.version import describe
    result = detect_prerequisites()
    lines = [describe() + " – Diagnose", f"Programm: {sys.executable}",
             f"Studio-Ordner (zur Laufzeit ermittelt): {Path(sys.executable).resolve().parent}",
             f"Gefroren (EXE): {bool(getattr(sys, 'frozen', False))}",
             f"Host-Laufzeit für Plugins: {studio_runtime_dir() or 'FEHLT'}",
             f"Logi Plugin Service: {result.plugin_service_version or ('installiert' if result.plugin_service_installed else 'FEHLT')} "
             f"({'läuft' if result.plugin_service_running else 'läuft nicht'})",
             f"Logi Options+: {'installiert' if result.options_plus_installed else 'FEHLT'}",
             f"PluginApi.dll (lokal, nicht mitgeliefert): {result.plugin_api_dll or 'FEHLT'}",
             f".NET SDKs: {', '.join(result.dotnet_sdks) or 'FEHLEN'}",
             f"Host-Laufzeit für Handler/Shared: {result.python_for_shared or 'FEHLT'}",
             f"Plugin-Reload-Werkzeug: {result.service_tool or 'FEHLT'}", ""]
    lines += [f"[{i['severity'].upper()}] {i['code']}: {i['message']}" for i in result.issues] or ["Alle Voraussetzungen erfüllt."]
    try:
        from adapters.logitech.deployment import installed_runtimes
        installed = installed_runtimes()
    except Exception as exc:  # no Logitech plugin directory
        installed = []
        lines.append(f"Installierte Studio-Plugins: nicht lesbar ({type(exc).__name__})")
    if installed:
        lines += ["", "Installierte Studio-Plugins und ihre Host-Laufzeit:"]
        for row in installed:
            runtime = row["runtime"]
            note = runtime.get("executable", "") if runtime["status"] == "LEGACY_ABSOLUTE_PATH" else runtime.get("directory", "")
            lines.append(f"  {row['plugin_id']} ({row['kind']}): {runtime['status']} {note}".rstrip())
            if runtime["status"] == "LEGACY_ABSOLUTE_PATH":
                lines.append("    -> vor 1.0 gebaut: im Studio neu bauen und aktualisieren (Migration auf pluginlokale Laufzeit)")
    path = _report_path(out)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (path.with_suffix(".json")).write_text(json.dumps(result.as_dict(), indent=2), encoding="utf-8")
    errors = [i for i in result.issues if i["severity"] == "error"]
    return 1 if errors else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="LogiPluginStudio")
    parser.add_argument("project", nargs="?")
    parser.add_argument("--legacy", action="store_true")
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--work")
    parser.add_argument("--out")
    parser.add_argument("--build", metavar="PROJECT")
    parser.add_argument("--mode", choices=("compatible", "native", "shared"), default="compatible")
    parser.add_argument("--handler")
    parser.add_argument("--install", metavar="PACKAGE")
    parser.add_argument("--uninstall", metavar="PLUGIN_ID")
    parser.add_argument("--confirm", metavar="PLUGIN_ID")
    parser.add_argument("--name", metavar="SDK_NAME")
    args = parser.parse_args(argv)
    if args.diagnose:
        return diagnose(args.out)
    if args.build or args.install or args.uninstall:
        import automation
        out = _report_path(args.out)
        if args.build:
            return automation.build(Path(args.build), args.mode, args.handler, out)
        if args.install:
            return automation.install(Path(args.install), args.confirm or "", out)
        return automation.uninstall(args.uninstall, args.confirm or "", args.name or "", out)
    if args.selftest:
        import portable_selftest
        return portable_selftest.run(Path(args.work), _report_path(args.out))
    from studio.app import main as app_main
    forwarded = ([] if args.legacy else ["--native"]) + ([args.project] if args.project else [])
    return app_main(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
