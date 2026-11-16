# AP-STUDIO-002 – StudioCoordinator und native Studio-Shell v1

**Vollständiger, eigenständig ausführbarer Agentenauftrag**  
**Projekt:** `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture`  
**Stand:** 06.11.2026 · **Status: PREPARED (nicht gestartet, noch nicht abgenommen)**  
**Ziel:** Die separat abgenommenen native ProjectSession, ProjectExplorer, ActionCatalog, ProblemsPanel und ContextHelp in einer tatsächlich bedienbaren, SDK-nativen Studio-Oberfläche zu einer sicheren Benutzerreise verbinden. Die KeypadPreview wird **nur** bei nachgewiesenen Capabilities aktiviert. Die vollständige Widget-Verdrahtung muss dauerhaft dokumentiert werden.

## 0. Pflichtlektüre – exakt diese Projektpfade

Vor jeglicher Implementierung diese Dateien vollständig lesen; unbekannte Fakten nicht erraten:

1. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\docs\decisions\ARCH-ADR-001.md`
2. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\docs\specifications\logitech-profil-und-aktionsmodell-basis-v02.md`
3. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\work\planning\modell-und-parallelentwicklung-nach-ap-prof-001-v01.md`
4. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\docs\architecture\studio\README.md` und **sämtliche dort aufgeführten** Architektur-/Widget-/Service-Referenzen
5. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\work\acceptance\20261105-native-session-explorer\ABNAHME.md`
6. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\work\acceptance\20261104-keypad-catalog\ABNAHME.md`
7. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\work\acceptance\20261105-problems-panel\ABNAHME.md`
8. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\work\acceptance\20261105-context-help\ABNAHME.md`
9. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\native_session.py`
10. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\native_project_explorer\widget.py`
11. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\action_catalog\widget.py`
12. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\keypad_contract.py` und `src\studio\keypad_preview\widget.py`
13. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\problems_panel\widget.py`
14. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\context_help\registry.py`, `entries.py`, `coordinator.py` und `widget.py`
15. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\native_ict_binding.py`
16. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\app.py` und die tatsächlich verwendeten Studio-Einstiegspunkte
17. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\examples\project_logitech_native_v1.json`

Bei Widerspruch gelten tatsächlicher Code und SDK-native Entscheidungen vor älteren Work-Entwürfen. Den aktuellen Bestand vor dem ersten Schreiben inventarisieren, Änderungen des Benutzers oder paralleler Agenten respektieren. Kein anderer Kontext oder vorausgegangener Chat ist erforderlich.

## 1. Architekturauftrag

Implementiere einen **StudioCoordinator** als zentrale Host-/Orchestrierungsschicht. Er darf keine neue persistente Action-, Handler-, State-, Binding- oder Profil-Domäne einführen. `NativeProjectSession` ist der **einzige Schreiber** des nativen Autorenprojekt-JSON; `parse_native_project` ist der normative Validator.

Eine **NativeStudioShell** in einem neuen, eigenen PySide6-Paket zeigt die vorhandenen Widgets. Bestehende Widgets **wiederverwenden, nicht als Varianten nachbauen**. Das bisherige `StudioWindow` bearbeitet weiterhin `0.1-draft`. Native Projekte werden über einen expliziten, minimalen Einstieg in die native Shell geöffnet; keine implizite Formatmigration.

### Verbindliche erste Benutzerreise

1. `logitech-native-1`-Projekt öffnen und anzeigen; tatsächliche vier SDK-Actiontypen, Handler, NativeFolder und Entries des vorhandenen Beispiels sichtbar.
2. Session-`native_project()` an `NativeProjectExplorerWidget` und `ActionCatalogWidget` verteilen, Sessionrevision ausschließlich im Host führen.
3. Auswahl im Projektbaum und im Katalog **bidirektional**, mit stabilen nativen IDs und konkreter Action-Parameteridentität synchronisieren; keine Signalloops oder Phantomselektionen.
4. Einen **klar begrenzten nativen Änderungsfall** realisieren, vorzugsweise `NativeAction.display_name`: User-Intent → ursprüngliches JSON-Snapshot → gezielte Änderung → `replace(proposed, base_revision=...)`. Kein vollwertiger ActionInspector und keine Action-Erstellungsfunktion vortäuschen.
5. Undo/Redo, Dirty, Save, erneutes Laden der Datei funktionieren; invalides JSON, stale Revision, verlorene ID und externer Dateikonflikt führen fail-closed zu **keiner** stillen Überschreibung.
6. `ProblemsPanelWidget` mit echten, nach Quellen differenzierten `core.errors.Diagnostic`-Snapshots verbinden. Native Diagnosepfade nicht ohne nachgewiesene Zuordnung als Entity-ID interpretieren.
7. `HelpRegistry`, `HelpCoordinator` und `ContextHelpWidget` mit Auswahl/F1/Pin/Related-Topics verbinden. Aktuellen Themenkontext und UI-Status bei Projektwechsel bereinigen.
8. `KeypadPreviewWidget` **nur** mit belegtem `KeypadFrame` und `NavigationCapability`; andernfalls ausdrücklich deaktivierte/unverfügbare Native-Preview anzeigen. Keine Fake-9-Tasten-Belegung oder erfundene Geräteseiten.
9. Alte `0.1-draft`-Oberfläche weiterhin öffnen, ändern und speichern können; kein ungefragtes Entfernen des alten Editors.

## 2. Umsetzung in drei intern geprüften Etappen

**A – Native Shell / Lesen:** native Datei öffnen, Session erzeugen, Projektbaum und Katalog mit echten Werten bestücken, Selektion sicher synchronisieren, Legacy-Format explizit trennen. Echte UI-/Qt-Tests.

**B – Diagnose und Hilfe:** ProblemsPanel + Registry/Coordinator/ContextHelp einbinden, F1/Pin/Related-Topics und Projektwechsel-/Filterfälle testen. Keine direkten fachlichen Widget-zu-Widget-Schreibaufrufe.

**C – Sicherer Änderungspfad:** eine erlaubte NativeAction-Anzeigenamenänderung, Validator, Undo/Redo, explizites Save, Reload; Fehlerszenarien einschließlich DiskConflict und Dirty-Projektwechsel. Kein zusätzlicher unabhängiger JSON-Writer.

Nach **jeder Etappe** einen lauffähigen Zwischenstand sowie konkrete Testlogs in der eigenen Arbeitsakte dokumentieren. Nicht mit einer großen unüberprüfbaren GUI-Umgestaltung beginnen.

## 3. Feste Änderungs-/Schreibgrenzen

**Neue Produktionsdateien:**

- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\native_shell\__init__.py`
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\native_shell\coordinator.py`
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\native_shell\window.py`
- Erforderliche private Helpers **ausschließlich im neuen `native_shell`-Paket**, solange keine gesonderte Architekturentscheidung nötig ist.

**Neue Tests und Lab:**

- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\tests\test_studio_coordinator.py`
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\tests\test_native_studio_shell.py`
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\tools\run_native_studio_lab.py`
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\work\studio-integration\AP-STUDIO-002\README.md`
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\work\studio-integration\AP-STUDIO-002\evidence\`

**Minimal zulässige Anpassung:** `src\studio\app.py` oder vorhandener Launcher nur für einen **explizit begründeten Einstieg/Route** zur nativen Shell. Den alten `0.1-draft`-Workflow ansonsten nicht umbauen.

**Verpflichtende Dokumentationsänderungen:**

- `docs\architecture\studio\00-Gesamtkarte.md`
- `docs\architecture\studio\01-Daten-und-Transaktionen.md`
- `docs\architecture\studio\02-StudioCoordinator.md`
- `docs\architecture\studio\04-Verbindungsregister.md`
- `docs\architecture\studio\README.md`
- Die fünf Einzeldateien unter `docs\architecture\studio\widgets\`
- `docs\architecture\studio\services\NativeProjectSession.md`
- Nur erforderliche Dokumentationsindizes unter `docs\README.md` und `work\planning\README.md`

**Nicht verändern:** `src/studio/native_session.py`, `src/studio/native_ict_binding.py`, `src/adapters/logitech/native.py`, bestehende Widgets, `src/runtime/`, `src/core/`, `schemas/`, bestehende Tests, Logitech Plugin Service, `ProfileInfo.json`, `Applications.Backups`, `PluginApi.dll` und `.lp5`-Dateien. Keine unnötigen Fremdänderungen, keine Services installieren/neustarten.

## 4. Native Writer- und UI-Sicherheitsregeln

- Die Session besitzt eine opake Revision. Jeder Commit verwendet `base_revision` und muss mit aktuellen nativen IDs übereinstimmen.
- Programmatisches `set_project`/`set_selection` der Widgets darf keine erneute Benutzer-Auswahl, keine Signalechos und keine versehentlichen Commits erzeugen.
- `NativeProject`-Dataclasses sind **nur Leseprojektionen**, nicht die direkte Speicherwahrheit.
- `NativeIctCoordinator`/SymbolDesigner haben aktuell einen separaten Pfad zur Projektdatei und zu Assets. **Diese Funktion in der nativen Shell gesperrt lassen**, bis eine sichere zentrale Writer-/Multi-File-Koordination unabhängig abgenommen wird.
- `save()` ist bereits konfliktgeschützt, aber kein globaler OS-Dateilock. Bei DiskConflict Fehler transparent anzeigen und niemals einfach neu überschreiben.
- Bei Dirty-Session vor Neu/Öffnen/Schließen Dialog für **Save / Verwerfen / Abbrechen**; bei Konflikt darf keine Änderung verloren gehen. Keine stillen Auto-Saves.
- Eventuelle asynchrone Ergebnisse müssen gegen aktuelles Projekt/Revision korreliert werden.
- Das Produkt darf keine versteckten/fiktiven Keypad-Seiten, Profilordner oder zusätzlichen SDK-Actionzustände erfinden.

## 5. Dokumentation ist Teil der Implementierung – verpflichtend

**Jedes Widget hat eine einzelne, führende Markdown-Schnittstellenreferenz** mit Codepfad, Funktion, öffentlichen Settern, Payloadtypen, Qt-Signalen, erlaubten Seiteneffekten, Identität/Revision, Fehler-/Leerzuständen und konkreter Hostverbindung.

Im **Verbindungsregister** enthält jede Kante: feste V-ID, tatsächlichen Sender/Signal, Empfänger/Methode, Datenformat, Gültigkeits-/Revisionsprüfung, erlaubte Seiteneffekte, Status `GEPLANT | IMPLEMENTIERT | AUFGESCHOBEN` und **konkrete Testfunktion**. Die **Gesamtkarte** muss IST und SOLL getrennt zeigen und bei Änderung aktualisiert werden.

**IMPLEMENTIERT** ist nur zulässig, wenn die exakte Verbindung im echten Code existiert **und** ein eigenständiger Integrationstest bestanden hat. Bestehende Widget-Unit-Tests zählen **nicht** als Test der neuen Verbindung. Prüfe die Gesamtreferenz auf unmögliche Pfeile und kopplungsbedingte Datenverluste. Jede neue Verbindung erhält eine neue V-ID. Keine grünen Scheinnachweise.

## 6. Prüfplan und Nachweise

Mindestens folgende automatische Tests:

1. Native Projektdatei → Explorer zeigt tatsächlich Plugin/4 Actions/Handler/Folder/4 Entries; Katalog hat vier native Actiontypen.
2. Projektbaumselektion → Katalogauswahl, Katalogaktion → Projektauswahl; keine UI-/Signal-Loops, duplicate Anzeigenamen bleiben durch ID unterscheidbar.
3. Anzeigenamenänderung erzeugt exakt einen erlaubten Commit; JSON und native Projektion konsistent, Undo/Redo, Dirty und Save/Reload korrekt.
4. Stale Revision, ungültiger Action-/Handlerverweis, fehlende Entity, falsches Schema, externe Byteänderung → kein Commit/keine Überschreibung.
5. `0.1-draft` öffnet weiterhin im Altfenster, ohne Auto-Migration.
6. ProblemsPanel zeigt Projektdiagnosen kanalweise und entfernt stale Meldungen bei Projektwechsel.
7. HelpRegistry/HelpCoordinator/F1/Pin/Related-Topics interagieren tatsächlich in der nativen Shell.
8. Keypad-Preview/ICT ohne belegte Capabilities sichtbar deaktiviert; **keine** Datei-/Servicewrites.
9. Dirty-Abbruch, erfolgreiches Save, Verwerfen und DiskConflict beim Projektwechsel/Schließen sicher.
10. Jede als IMPLEMENTIERT gelistete V-ID besitzt einen eigenen Integrationstest.
11. Echte Windows-Qt-GUI-Screenshots: hell/dunkel, breite/schmale Ansicht, Auswahl/Details, Fehler/Hilfe, Dirty/Save-Konflikt, HiDPI ohne überlappende Texte.
12. Nur temporäre Kopien der Beispielprojekte verändern; originale Beispiel-JSONs/ICT-Assets und Logitech-Service-Dateien byteidentisch.

**Pflichtbefehle (Ausgabe/Exitcode dokumentieren):**

```powershell
python -m unittest discover -s tests -p test_studio_coordinator.py -v
python -m unittest discover -s tests -p test_native_studio_shell.py -v
python -m unittest discover -s tests -q
python tools/run_native_studio_lab.py --smoke
python tools/check_links.py
```

GUI-Smoke zusätzlich real unter Windows starten; Qt-Offscreen ist keine visuelle Abnahme. Bestehende Tests nicht deaktivieren, um neue Fehler zu verdecken.

## 7. Abschluss

Lieferung unter `work\studio-integration\AP-STUDIO-002\README.md` mit Ablauf A/B/C, Codeänderungen, allen Testergebnissen, GUI-Screenshots, Integrationsmatrix V-IDs→Code→Test, Risiken und ausgegrenzten Folgeaufträgen. Keine Fremd-/Legacy-Run-Akten überschreiben. Wenn eine echte externe Sperre auftritt, eng dokumentieren; ansonsten bis zur bestmöglichen prüfbaren Fertigstellung arbeiten.

**Abschlussstatus: READY_FOR_REVIEW**, niemals selbst `APPROVED`. Eine unabhängige Abnahme entscheidet anschließend. **Fehlende aktualisierte Gesamtkarte oder Widget-Einzeldokumente sind ein Abnahmehindernis, auch wenn die GUI funktioniert.**
