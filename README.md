# Logitech Plugin Studio

Windows-Studio und Python-Anbindung für Logitech-Actions-SDK-Plugins. Führende Fachsemantik: **SDK Native First**, siehe [ARCH-ADR-001](docs/decisions/ARCH-ADR-001.md).

**Aktueller Entwicklungsstand, 07.11.2026:** Native Actions bearbeiten/erstellen/löschen, VirtualFolder-Composer in der nativen Shell, SDK-native Folder-Ausführung und dynamische Membership sowie der integrierte SDK-Build aus gespeicherten virtuellen Ordnern sind softwareseitig implementiert. AP-FOLDER-002 und REVIEW-FIX-20261106 wurden in ihrem Softwareumfang [gemeinsam unabhängig abgenommen](work/acceptance/20261107-joint-folder-build/ABNAHME.md). Eine vollständige Hardware-/Gesamtproduktfreigabe wird nicht behauptet. [Aktueller Status](STATUS.md).

## Start

```powershell
python -m pip install -r requirements-dev.txt
python tools/run_studio.py --native examples/project_logitech_native_v1.json
```

Im nativen Fenster: Projektübersicht, Aktionskatalog/-inspektor, virtuelle Ordner, Probleme und Kontexthilfe. Native Projektdatei und optionale `.vfolders.json`-Extension haben getrennte Writer und Speichervorgänge. **SDK-Plugin bauen** erstellt jetzt direkt aus den gespeicherten nativen und virtuellen Daten einen SDK-Build und ein lokales Paket (ohne Installation). Die Keypad-/ICT-Integration sowie Installations-/Reload-/Rollback-Bedienung bleiben getrennte Integrationsaufgaben.

Ohne `--native` öffnet der Launcher den bisherigen kompatiblen `0.1-draft`-Editor:

```powershell
python tools/run_studio.py examples/first_plugin/project.json
```

[Umgebung, reproduzierbare Befehle und Export](docs/DEVELOPMENT.md) · [Bisheriges Benutzerhandbuch](docs/13_Benutzerhandbuch.md).

## Aktuelle Architektur und SDK-Folder

- [Studio-Architektur](docs/architecture/studio/README.md): zentrale native Projektsitzung, Hostkoordination und Views.
- [SDK-DynamicFolder-Vertrag](docs/architecture/sdk-dynamic-folders.md): native Actioninstanzen, Parameter/Placements, Membership, Linkpfad-/Back-/Seitennavigation, Python-/C#-Übergabeformat und explizite Grenzen.
- [Profil-/Aktionsmodell](docs/specifications/logitech-profil-und-aktionsmodell-basis-v02.md): SDK-eigene Funktionen und Logitech-verwaltete Profile klar getrennt.
- [Testanleitung](tests/README.md), [aktive Arbeitsplanung](work/planning/README.md), [Review-Fix-Arbeitsakte](work/reviews/REVIEW-FIX-20261106/README.md).

Der neue native Build-Tab übernimmt eine **gespeicherte** Studio-Extension automatisch. Ohne Sidecar bleibt der native Standardfolder erhalten; bei mehreren realen SDK-Foldern werden deren virtuelle Einstiegsknoten bewusst ausgewählt. [Native Build-Anbindung](docs/architecture/studio/NativeBuildIntegration.md). Der eigenständige CLI-Weg `tools/run_folder_runtime.py` bleibt verfügbar. Ein erzeugtes Plugin benötigt kein geöffnetes Studio.

## Hardware und Lieferung

Ein früherer Produktpfad ist mit echten Tastendrücken und Python-Callbacks dokumentiert ([HW-01](work/product-readiness/HW-01/06_hardwarefunktionspruefung_2026-11-03.md)). Das ersetzt keine vollständige Abnahme der neuen nativen Folder-Runtime. SDK-Requery/Cache, reale Slotgeometrie, Seitentasten, Multi-Device und Langzeitverhalten bleiben HARDWARE_PENDING.

```powershell
python tools/package_result.py --run FINAL-PRODUCT-03
```

Nur den geprüften sicheren Quellarchivexport teilen. Private Connection-Dateien, Hersteller-DLLs und Betriebsdaten gehören nicht in ein Vollprojekt-ZIP. [Sichere Übergabe](docs/14_Sichere_Projektuebergabe.md).

## Verzeichnisstruktur

`src/`, `schemas/`, `tests/`, `component_types/`, `examples/` enthalten die Implementierung und technische Artefakte. `docs/` beschreibt geltende Verträge, `work/` Planung/Läufe/Abnahmen, `references/` unveränderte historische und SDK-Quellen. Ältere Freigaben gelten jeweils für ihren dokumentierten Scope.

## SDK-Bridge und optionale Erweiterungen (08.11.2026)

Die Basis-Bridge transportiert ausschließlich neutrale SDK-Aufrufe, Snapshots und Ereignisse; optionale virtuelle Folderlogik liegt unter `src/extensions/shared_folders/`. Der alte Python-Importpfad bleibt als Kompatibilitätsfassade erhalten. [Schichtentrennung mit Abhängigkeitsregeln](docs/architecture/sdk-bridge-schichtentrennung.md) · [SDK-Funktions- und Python-API-Checkliste mit Checkboxen](docs/specifications/sdk-python-api-checklist.md).

**Wichtig:** Der C#-SDK-Generator unterstützt mehr SDK-Funktionen, als bisher als direkte Python-API angeboten werden. Die Checkliste unterscheidet C#-Erzeugung, Python-Callbacks, echte Python-Methoden und Hardwareprüfung ausdrücklich. Keine API-Vollständigkeit oder hardwareseitige Freigabe wird aus den C#-Buildtests abgeleitet.

## Abnahme der nativen Studio- und Shared-Folder-Finalpakete (08.11.2026)

Die getrennten Softwarelieferungen [AP-STUDIO-FINAL-001 und AP-SHARED-FINAL-001](work/acceptance/20261108-two-final-packages/GEMEINSAME-ABNAHME.md) sind nach unabhängigem Test **APPROVED/CLOSED in ihrem Softwareumfang**. Gemeinsame Gesamtsuite **1.157/1.157 PASS**. KeypadPreview und SymbolDesigner sind im Hauptfenster aktiv; der Shared-Generator kann native oder pro Plugin eingebettete Peer-Runtime liefern. **Noch nicht als vollständiger Studio-Bedienablauf integriert:** Auswahl Shared-Modus, Peer-Freigaben/Pairing sowie der vollständige installierbare Asset-/Deploymentpfad. Hardware und Options+-Service bleiben ungeprüft.

## Produktabschlussprüfung AP-RELEASE-FINAL-001 (08.11.2026)

Die NativeStudio-/Shared-Folder-/Deployment-/Packaging-Lieferung wurde unabhängig überprüft: [Abnahmebericht](work/acceptance/20261108-release-final/ABNAHME.md). **1.180/1.180 Tests erfolgreich**, portable Ausgabe `work/release-final/AP-RELEASE-FINAL-001/outputs/release_candidate/` mit vollständigem Hashnachweis. Native und Shared-Plugins wurden im echten Service und MX Keypad getestet; die fremden Plugins/Links blieben geschützt, Testplugins sind entfernt. Für das öffentliche v1.0-Paket sind noch geringfügige Dokumentations-/UX-Korrekturen und die Hinweise zu SmartScreen, Hostrunner-Pfad und Options+-Profilbelegungen relevant. Keine vollständige Python-SDK-Neuimplementierung.
