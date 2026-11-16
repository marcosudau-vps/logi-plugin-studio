# Reproduzierbare Entwicklung und Prüfung

Stand 06.11.2026. Dieser Auftrag bereitet Versionsverwaltung vor; er initialisiert kein Git-Repository und erzeugt keine Commits.

## Voraussetzungen

- Windows mit Python 3.12; geprüft mit 3.12.10.
- Python-Runtimepaket PySide6 6.12.0; für vollständige Tests zusätzlich jsonschema 4.26.0. Die Manifeste pinnen die direkt verwendeten Pakete; ein vollständiges transitive Lockfile wird nicht behauptet.
- Für Plugin-Builds: .NET SDK 10.x, geprüft mit 10.0.403.
- Lokal installierte Logitech Options+/Plugin-Service-SDK-Dateien. Geprüft: `C:\Program Files\Logi\LogiPluginService\PluginApi.dll`, Dateiversion 6.4.2.3414, zugehörige native Bibliotheken im selben Verzeichnis.
- SDK und Gerätevorlagen werden nicht blind mitgeliefert. Die Originalgrafiken für sieben optionale visuelle Vergleichstests liegen außerhalb des Quellprojekts; ohne sie werden ausschließlich diese Vergleiche sichtbar übersprungen.

## Frische Python-Umgebung

Aus dem Projektroot, PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe tools/run_tests.py
```

Für das sichtbare Studio die Offscreen-Variable wieder entfernen:

```powershell
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe tools/run_studio.py --native examples/project_logitech_native_v1.json
```

Die gebündelten Quell-/Contractfixtures unter `tests/fixtures` sind ausreichend; historische Agenten-Arbeitsakten werden von den Regressionstests nicht mehr als Eingabedaten benötigt. Der Standardstart ohne `--native` öffnet den kompatiblen Legacy-Editor.

## Echte SDK-/Prozessprüfungen

```powershell
python tools/run_native_first_probe.py --out work/local-checks/native
python tools/run_product_checks.py --out work/local-checks/legacy
python -m unittest discover -s tests -p test_review_folder_runtime.py -v
```

Diese Befehle bauen Quellen gegen das installierte SDK und testen C#-/Python-Prozesse. Sie registrieren kein Plugin und starten keinen Logitech-Service neu. Die Folder-Prüfung ruft tatsächliche SDK-Methoden auf und vergleicht SDK-Statebilder; ein Gerätetest bleibt separat.

## Sicherer Quellarchivexport

```powershell
python tools/package_result.py --run FINAL-PRODUCT-03
python tools/package_result.py --verify work/autopilot/FINAL-PRODUCT-03/delivery/source-snapshot.zip
```

Das Archiv enthält native SVG-/ICT-Assets, die notwendigen Contractfixtures und die Abhängigkeitsmanifeste. Es enthält keine privaten Connection-Dateien, Logs, Builds oder Hersteller-DLLs. CRC und Dateihashes werden beim Erzeugen und Prüfen verifiziert. Ein vollständiges Verzeichnis-ZIP ist weiterhin keine freigegebene sichere Übergabe.

Zum Nachweis frisch in ein neues Verzeichnis entpacken, in `PluginStudioArchitecture` wechseln, Voraussetzungen herstellen und `python tools/run_tests.py` starten. Die Reviewakte dokumentiert einen solchen vollständigen Lauf einschließlich der explizit fehlenden externen Grafikreferenzen.

## Vor späterer Git-Initialisierung

`.gitignore` schließt bekannte Betriebsdaten und Buildverzeichnisse aus. Vor einer ausdrücklich freigegebenen Initialisierung müssen der tatsächlich zu versionierende Bestand und private Dateien geprüft werden. Hashbaselines und bestehende Reviewakten bleiben erhalten. Ein Quellarchiv-/Python-Testlauf auf diesem Rechner ersetzt noch keinen separaten Clean-Windows-Distributionstest.
