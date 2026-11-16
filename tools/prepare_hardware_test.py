"""Prepare a built, own-plugin-only hardware gate without installing or reloading."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from adapters.logitech.codegen import DEFAULT_SDK_DLL, check_output_dir
from adapters.logitech.deployment import plan_install, prepare_package
from adapters.logitech.errors import GenerationError
from adapters.logitech.product import build_product, generate_product, provision_connection, read_asset
from library.document import ProjectDocument
from runtime.wire import ConnectionSettings, json_bytes, project_digest
from probe_helpers import check_callback_process


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=ROOT / "examples" / "first_plugin" / "project.json")
    parser.add_argument("--out", type=Path, default=ROOT / "work" / "autopilot" / "FINAL-PRODUCT-02" / "hardware-test")
    parser.add_argument("--id", default="studio.mx.keypad02")
    parser.add_argument("--verify-existing", action="store_true", help="Check an existing prepared gate without any installation")
    args = parser.parse_args()
    output = check_output_dir(args.out)
    if args.verify_existing:
        project = output / "project.json"
        document = ProjectDocument()
        document.load(project)
        old = json.loads((output / "evidence.json").read_text())
        if old.get("plugin_id") != args.id or document.raw["project"]["id"] != args.id:
            raise GenerationError("Existing gate has another identity")
        generated = generate_product(project, output_dir=output / "process-source", assembly_name="MxKeypad02")
        build_dir = output / "build"
        for name, source in generated.files.items():
            current = (build_dir / name).read_bytes() if isinstance(source, bytes) else (build_dir / name).read_text(encoding="utf-8")
            if current != source:
                raise GenerationError("Prepared generated sources differ from current recipe; create a new gate")
        dll = build_dir / "bin" / "Debug" / "MxKeypad02.dll"
        if hashlib.sha256(dll.read_bytes()).hexdigest() != old["build"]["assembly_sha256"]:
            raise GenerationError("Prepared SDK assembly hash changed")
        connection = dll.parent / "studio.connection.json"
        settings = ConnectionSettings.load(connection)
        if settings.plugin_id != args.id or settings.project_hash != project_digest(document.raw):
            raise GenerationError("Prepared connection belongs to another revision")
        checks = check_callback_process(generated, project, build_dir, connection, output, document.raw, DEFAULT_SDK_DLL)
        result = {"ok": True, "hardware_test": False, "installation_executed": False,
                  "sdk_assembly_hash_unchanged": True, "checks": checks}
        (output / "process-evidence.json").write_bytes(json_bytes(result))
        print(json.dumps(result, indent=2))
        return 0
    if output.exists() and any(output.iterdir()):
        raise GenerationError("Hardware gate needs a fresh isolated output; preserve existing gates and receipts")
    document = ProjectDocument()
    document.load(args.project)
    raw = document.raw
    raw["project"]["id"] = args.id
    raw["project"]["display_name"] = "Isolierter MX-Keypad-Test FINAL-PRODUCT-02"
    document.replace_raw(raw)
    output.mkdir(parents=True, exist_ok=True)
    project = output / "project.json"
    for asset in raw["assets"]:
        content = read_asset(args.project.resolve().parent, asset)
        destination = output / asset["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    document.save(project)
    build_dir = output / "build"
    generated = generate_product(project, output_dir=build_dir, assembly_name="MxKeypad02")
    build = build_product(generated, build_dir, log_path=output / "sdk-build.log")
    connection = provision_connection(generated, build_dir)
    package = prepare_package(generated, build_dir, connection)
    process_checks = check_callback_process(generated, project, build_dir, connection, output, raw, DEFAULT_SDK_DLL)
    plan = plan_install(package)
    target = Path(plan["target"])
    before = target.read_bytes() if target.exists() else None
    if before is not None:
        private = output / "private"
        private.mkdir()
        (private / "original-link.bytes").write_bytes(before)
    (output / "install-plan.json").write_bytes(json_bytes(plan))
    before_record = {"target": str(target), "exists": before is not None,
                     "sha256": hashlib.sha256(before).hexdigest() if before is not None else None,
                     "collision_policy": "unproven_or_foreign_link_refused", "link_modified": False}
    (output / "before.json").write_bytes(json_bytes(before_record))
    rollback = {"status": "PREPARED_NOT_EXECUTED", "future_receipt": str(output / "receipts" / (args.id + ".receipt.json")),
                "operation": "remove_own_link" if before is None else "restore_exact_original_bytes",
                "target": str(target), "expected_current_sha256": plan["new_sha256"],
                "expected_restore_sha256": plan["previous_sha256"], "service_restart": False}
    (output / "rollback-preparation.json").write_bytes(json_bytes(rollback))
    actions = [(p["component"], p["id"]) for view in raw["views"] for p in view["placements"]]
    unique_actions = list(dict.fromkeys(component for component, _ in actions))
    commands = "\n".join(f"python tools\\run_product.py press --connection \"{connection}\" "
                         f"--action {component} --placement {next(pid for cid, pid in actions if cid == component)}"
                         for component in unique_actions)
    guide = f"""# Isolierter MX-Keypad-Hardwaretest

DRY_RUN_ONLY / HARDWARE_PENDING. BUILD_PROVEN, keine Registrierung oder Dienst-/Profilaktion ausgefuehrt.

- Plugin-ID: `{args.id}`
- Projekt: `{project}`
- Paket: `{package}`
- Eigener Link: `{target}`
- Vorher: exists={before_record['exists']}; SHA={before_record['sha256']}
- Geplantes neues Link-SHA: `{plan['new_sha256']}`
- Kollisionsschutz: nur nachweislich eigener Link; Installationsbefehl berechnet und vergleicht den Dry-Run erneut.
- Backup: Originalbytes im neuen privaten Installationsbeleg; falls Update, zusaetzlich `private/original-link.bytes`.
- Connection und Beleg/Backup bleiben privat. Diesen kompletten Ordner NICHT als Quellarchiv teilen.

## Vor einer Freigabe

Den authentisierten Standalone-Host starten und Diagnose/simulierte Eingabe in einem zweiten Fenster pruefen:

```powershell
python examples\\first_plugin\\host.py --project "{project}" --connection "{connection}"
python tools\\run_product.py diagnose --connection "{connection}"
{commands}
```

Die CLI-Eingaben sind KEINE Hardware-Callbacks. Strg+C stoppt nur den eigenen Host.

## Nur nach ausdruecklicher Nutzerfreigabe

```powershell
python tools\\run_product.py install --plan "{output / 'install-plan.json'}" --confirm-plugin-id {args.id} --receipts "{output / 'receipts'}"
```

Vorher `before.json` und frischen Dry-Run vergleichen. Danach Linkinhalt und SHA mit
`install-plan.json` vergleichen, privaten Beleg erhalten. Es wird nur dieser Link geaendert,
kein fremdes Plugin, kein Profil, kein Service.

Ein lokaler Plugin-Service-Reload ueber die Logitech-Bedienoberflaeche ist ein SEPARAT
freizugebender Nutzerschritt. Keine unbestaetigte Service-ID und keinen pauschalen
Prozess-Kill verwenden. Falls nur Neustart moeglich ist, Auswirkungen zuerst pruefen.
Profile nicht durch diesen Test automatisch aendern; eine notwendige Zuordnung ist separat zu genehmigen.

## Beobachtung am Geraet

Zeit, Options+-/Plugin-Service-/Geraeteversion und verwendetes Profil notieren.
Jede eigene Aktion physisch druecken: SDK-Callback -> vertrauenswuerdiger Handler ->
expliziter component-scoped `state.mode` Write -> passende Text-/PNG-Variante auf dem LCD.
Zweiter Druck toggelt zurueck. Alle {len(raw['views'])} Views oeffnen/schliessen; Back und
Pagination bei mehr als einer Seite; wiederholte Aktion darf keinen zweiten State erzeugen.
Host kontrolliert stoppen: vorheriger Wert bleibt stale, keine automatische Command-Wiederholung.
Neu starten: neue Runtime, Vollsnapshot und erneuter expliziter Tastendruck.
LCD/Bildmodus/Schrift bei tatsaechlichen 50/80/116px erst danach als Hardwarebeleg werten.

## Nur eigenes Rollback

Im Studio den privaten Beleg waehlen, `Rollback nur pruefen`, Ziel/SHA kontrollieren und
nach bewusster Freigabe genaue ID plus Dateiaenderung bestaetigen. Alternativ:

```powershell
python tools\\run_product.py rollback --receipt "{output / 'receipts' / (args.id + '.receipt.json')}" --confirm-plugin-id {args.id}
```

Rollback entfernt nur den neuen eigenen Link oder stellt dessen Originalbytes wieder her.
Nach externen Linkaenderungen wird es verweigert. Vorherzustand/SHA erneut pruefen.
Paket und Belege behalten; ggf. separater bewusster Logitech-Reload. Kein Hardware-PASS ohne
unabhaengigen Beobachtungs-/Abnahmenachweis.
"""
    (output / "README.md").write_text(guide, encoding="utf-8")
    evidence = {"status": "READY_FOR_REVIEW", "hardware_status": "HARDWARE_PENDING", "installation_executed": False,
                "service_restart": False, "profile_change": False, "plugin_id": args.id,
                "build": build.as_dict(), "plan": plan, "before": before_record, "actions": unique_actions,
                "process_checks": process_checks}
    (output / "evidence.json").write_bytes(json_bytes(evidence))
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
