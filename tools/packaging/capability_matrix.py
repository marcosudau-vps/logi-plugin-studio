"""Machine-readable capability matrix of both Windows editions (AP-POLISH-001 / 15.3).

    python tools/packaging/capability_matrix.py --rc <release_candidate> --installed <installed-files.json> --out <dir>

Proves from the ARTIFACTS (not from intent) that the Setup installation and the
Portable ZIP contain the identical program payload: every payload file with
the same SHA-256 in both, and lists the only permitted differences
(edition marker + Inno Setup uninstaller). Capabilities are attached to the
payload components that implement them, so identical payload ⇒ identical
capabilities. Writes ``capability_matrix.json`` and ``capability_matrix.md``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ALLOWED_SETUP_ONLY = {"studio-edition.json", "unins000.exe", "unins000.dat"}
CAPABILITIES = [
    ("Studio-Oberfläche (Projekte, ActionInspector, KeypadPreview, SymbolDesigner/ICT, FolderComposer)", "LogiPluginStudio.exe"),
    ("Plugin-Build Kompatibel / Nativ / Shared (Generator, C#-Vorlagen, eingebettete Hosts)", "_internal/adapters/logitech/templates/HostChild.cs.in"),
    ("Pluginlokale Host-Laufzeit (stdlib-only, wird in jedes Plugin kopiert)", "hostruntime/studio-host-runtime.json"),
    ("Installation / Update / Rollback / Deinstallation (Verzeichnismodus)", "LogiPluginStudio.exe"),
    ("Shared-Peers: Pairing, gerichtete Freigaben, DPAPI-Schlüsselablage", "LogiPluginStudio.exe"),
    ("Diagnose und Selbsttest", "Diagnose.cmd"),
    ("Automatisierung (--build/--install/--uninstall)", "LogiPluginStudio.exe"),
    ("Projekt- und Plugin-Formate (logitech-native-1, .vfolders.json, Paket/Record-Formate)", "component_types/core.command_action.json"),
    ("Lizenz- und Drittanbieterhinweise", "THIRD_PARTY_NOTICES.md"),
    ("Anwenderhandbuch", "ANWENDERHANDBUCH.md"),
]


def zip_hashes(archive: Path) -> dict:
    with zipfile.ZipFile(archive) as handle:
        names = [n for n in handle.namelist() if not n.endswith("/")]
        top = {n.split("/", 1)[0] for n in names}
        assert len(top) == 1, top
        return {n.split("/", 1)[1]: hashlib.sha256(handle.read(n)).hexdigest() for n in names}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rc", type=Path, required=True)
    parser.add_argument("--installed", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = json.loads((args.rc / "release_manifest.json").read_text(encoding="utf-8"))
    payload = json.loads((args.rc / manifest["payload"]["sha256_list"]).read_text(encoding="utf-8"))
    portable = zip_hashes(args.rc / manifest["artifacts"]["portable_zip"]["file"])
    rows = json.loads(args.installed.read_text(encoding="utf-8-sig"))
    installed = {r["path"]: r["sha256"] for r in rows}
    portable_diff = sorted(set(portable) ^ set(payload)) + sorted(k for k in payload if portable.get(k) not in (None, payload[k]))
    setup_extra = sorted(set(installed) - set(payload))
    setup_missing = sorted(set(payload) - set(installed))
    setup_changed = sorted(k for k in payload if k in installed and installed[k] != payload[k])
    unexpected = [p for p in setup_extra if p not in ALLOWED_SETUP_ONLY]
    capabilities = []
    for name, component in CAPABILITIES:
        capabilities.append({"capability": name, "component": component,
                             "portable": component in portable, "setup": component in installed,
                             "same_bytes": portable.get(component) == installed.get(component) is not None})
    result = {
        "format": "capability-matrix-1", "version": manifest["version"],
        "payload_files": len(payload), "payload_tree_sha256": manifest["payload"]["tree_sha256"],
        "portable": {"artifact": manifest["artifacts"]["portable_zip"], "differences_to_payload": portable_diff},
        "setup": {"artifact": manifest["artifacts"].get("setup_exe"), "installed_files": len(installed),
                  "missing": setup_missing, "changed": setup_changed, "extra": setup_extra,
                  "unexpected_extra": unexpected},
        "allowed_edition_differences": sorted(ALLOWED_SETUP_ONLY),
        "capabilities": capabilities,
        "identical_functionality": not portable_diff and not setup_missing and not setup_changed and not unexpected
                                   and all(c["portable"] and c["setup"] and c["same_bytes"] for c in capabilities),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "capability_matrix.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [f"# Capability-Matrix – Logitech Plugin Studio {manifest['version']}", "",
             "Automatisch erzeugt von `tools/packaging/capability_matrix.py` aus den **Artefakten** "
             "(Portable-ZIP und tatsächlich per Setup installierte Dateien in der Windows Sandbox). "
             "Maschinenlesbar: `capability_matrix.json`.", "",
             f"* Programm-Payload: **{len(payload)} Dateien**, Baum-SHA-256 `{manifest['payload']['tree_sha256']}`",
             f"* Portable-ZIP: Abweichungen zum Payload: **{len(portable_diff)}**",
             f"* Setup-Installation: fehlend **{len(setup_missing)}**, verändert **{len(setup_changed)}**, "
             f"zusätzlich {len(setup_extra)} ({', '.join(setup_extra) or '–'}), davon unerwartet **{len(unexpected)}**",
             f"* Ergebnis **identische Funktionalität: {'JA' if result['identical_functionality'] else 'NEIN'}**", "",
             "| Fähigkeit | Komponente | Portable | Setup | gleiche Bytes |", "|---|---|---|---|---|"]
    for c in capabilities:
        mark = lambda v: "✔" if v else "✘"
        lines.append(f"| {c['capability']} | `{c['component']}` | {mark(c['portable'])} | {mark(c['setup'])} | {mark(c['same_bytes'])} |")
    lines += ["", "## Zulässige Unterschiede (nur Installation/Integration)", "",
              "| Setup | Portable |", "|---|---|",
              "| `studio-edition.json` (Kennzeichnung „setup“ für Diagnose) | – (Fassung wird als „portable“ erkannt) |",
              "| `unins000.exe/.dat`, Eintrag „Apps & Features“ (HKCU), Startmenü, optional Desktop | – |",
              "| Standardordner `%LOCALAPPDATA%\\Programs\\LogiPluginStudio` (wählbar) | beliebiger, verschiebbarer Ordner |",
              "", "Benutzerdaten, Projekt-/Paketformate, Generator- und Runtime-Verträge sind in beiden Fassungen identisch "
              "(gleiche Bytes der Programmdateien)."]
    (args.out / "capability_matrix.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"identical_functionality": result["identical_functionality"], "portable_diff": len(portable_diff),
                      "setup_missing": len(setup_missing), "setup_changed": len(setup_changed),
                      "unexpected": unexpected}, indent=1))
    return 0 if result["identical_functionality"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
