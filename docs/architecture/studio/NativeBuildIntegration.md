# NativeStudioShell – SDK-Plugin-Build und virtuelle Folder-Projektion

**Stand 07.11.2026.** Softwareintegration implementiert; tatsächliche Logitech-Geräteinstallation und die vollständige Endnutzer-Deploymentoberfläche gehören nicht zu diesem Schritt.

## Benutzerablauf

1. `python tools/run_studio.py --native examples/project_logitech_native_v1.json`.
2. Native Actions und bei Bedarf virtuelle Ordner konfigurieren.
3. Native JSON und optionale `<projekt>.vfolders.json` jeweils ausdrücklich separat speichern.
4. In der Toolbar **SDK-Plugin bauen** auswählen. Der Tab **Plugin-Build** zeigt Generator-, dotnet- und Paketergebnis.
5. Der Build benutzt einen eindeutigen neuen Ausgabeordner `work/generated/native-builds/<UUID>/`. Er installiert weder das Plugin noch verändert er Logitech-Profile oder Dienste.

Das Toolbar-Kommando erzeugt auch ein lokales Paket mit der vorhandenen `BuildWorker`-/`prepare_package`-Kette. Das Paket ist **nicht automatisch installiert**. Ein lokales `studio.connection.json` enthält vertrauliche Verbindungsinformationen: die ganze Buildausgabe nicht als share-safe Quellarchiv weitergeben.

## Owner und Preflight

`src/studio/native_shell/build_integration.py::prepare_native_build` ist die nichtinteraktive, Qt-freie Übergabegrenze. Sie prüft die aktiven Owner `NativeProjectSession` und `ExtensionStore` auf:

- beide Sitzungen vorhanden, keine ausstehenden Native-/Extension-Commits oder flüchtigen Inspector-Drafts;
- unveränderte Quelldateien (bestehende optimistische Disk-Conflict-Gates);
- korrekte kanonische Extension-Projektidentität, Plugin-ID und Dateipaarung;
- strukturelle Gültigkeit, ohne verwaiste Actions im Editor heimlich zu löschen;
- strikte Laufzeitprojektion: verwaiste lokale Actionziele werden **vor dem Build** abgelehnt.

Es werden defensive native und virtuelle Snapshots eingefroren. BuildWorker erzeugt und kompiliert daraus über die bereits vorhandene Schnittstelle `generate_product(..., raw_project=..., folder_runtime=...)`. Die Schreibautoritäten der beiden Projektdateien bleiben unberührt. Zwischen beiden Dateien wird keine atomare gemeinsame Transaktion behauptet.

### Folder-Einstieg

- **Kein gespeichertes Sidecar:** Der Generator behält den nativen `initial_layout`-Pfad. Der neue, leere Editor-Root verändert SDK-Folder nicht automatisch.
- **Sidecar gespeichert, eine reale SDK-Folderdefinition:** deren Einstieg wird automatisch auf den vom Benutzer festgelegten `Document.root_id` gelegt.
- **Sidecar gespeichert, mehrere reale SDK-Folderdefinitionen:** für jede wird ihr virtueller Startknoten explizit aus den vorhandenen virtuellen Ordnern gewählt; SDK-Folder bleiben unabhängig.
- **Sidecar mit Platzierungen, aber ohne native SDK-Folderdefinition:** Build wird abgelehnt, statt virtuelle Placements unbemerkt zu ignorieren.

Die `sdk-folders-1`-Projektion übernimmt lokale NativeAction-Referenzen, Linkziele, virtuelle Seiten und die im Extensionformat enthaltenen Actionparameter. Der Runtimevertrag und die Support-Matrix stehen unter [SDK-DynamicFolder-Vertrag](../sdk-dynamic-folders.md). Im Folder nicht belegte ActionEditor-Ausführung bleibt explizit gesperrt.

## Ausführung, Fehler und Lebenszyklus

`NativeBuildController` besitzt allein UI/Worker/Log; `StudioCoordinator` bleibt Eigentümer der Sessions. Der Build wird ausschließlich auf Benutzerklick gestartet, nicht durch einen Ordner-Commit und nicht bei jedem Refresh. Während eines Builds werden ein erneuter Start, Projektwechsel und Schließen des Fensters verhindert, damit kein laufender QThread zerstört wird. Nach Fehler bleibt der ursprüngliche Projekt- und Extensionstand erhalten. Fehler erscheinen im Build-Log und beim vorhandenen ProblemsPanel. Der Pfad enthält eindeutige Job-IDs; ältere Buildordner werden nicht überschrieben.

Belegte Tests: `tests/test_native_folder_build_integration.py` mit Preflight-Negativfällen, mehreren Startknoten, tatsächlichem MainWindow-/QThread-Pfad, echtem C#-Build gegen die installierte SDK-DLL sowie Quellbytegleichheit. Zusätzliche Studio-/SDK-Gesamttests bleiben relevant.

## Verbleibende Grenzen

- Noch kein nativer UI-Workflow für Installation/Reload/Rollback; nur Build und lokales Paket.
- Der Build nutzt die auf diesem Windows-Rechner installierte `PluginApi.dll`, .NET 10 und Python-Abhängigkeiten.
- Die [native Keypad-/ICT-Integration](NativeKeypadAndIct.md) speichert Ressourcen vor dem Build. Der Generator erzeugt die SDK-Ressourcen im Ausgabebaum. Die bestehende Entwicklungspaketstufe enthält DLL, Metadaten und Verbindung; die Übernahme der getrennten `icontemplates/` in dieses Paket ist außerhalb der Studiointegration. Eine Hardwarefreigabe bleibt separat.
- Bei Projekten mit mehreren realen SDK-Foldern wird die individuelle Startzuordnung bei jedem Build abgefragt; noch kein separat persistiertes Bindingmodell.
- Hardware-DynamicFolder-Paging, echte Host-Requery/Cache-/Seitenindexeffekte und Multi-Device bleiben `HARDWARE_PENDING`.
