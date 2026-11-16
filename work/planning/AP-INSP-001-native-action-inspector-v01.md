# AP-INSP-001 – SDK-nativer ActionInspector v1 mit Studio- und Hilfeintegration

**Vollständiger eigenständig ausführbarer Agentenauftrag**  
**Projektroot:** `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture`  
**Stand:** 06.11.2026  
**Status:** PREPARED – noch kein Agent gestartet; Umsetzung endet mit READY_FOR_REVIEW und eigener unabhängiger Abnahme.  
**Leitentscheidung:** Native First / Minimal Bridge. Bestehende native Action-Definitionen vollständig editieren, ohne eine zweite Persistenzdomäne, ohne SDK-Parser-Umbau und ohne Logitech-Profildateien zu schreiben.

## 0. Pflichtlektüre und Baseline

Vor dem Schreiben vollständige Lektüre dieser **konkreten Dateien** im Projektroot:

1. `docs/decisions/ARCH-ADR-001.md` – Native First.
2. `docs/specifications/logitech-profil-und-aktionsmodell-basis-v02.md` – Action-Definition, FolderEntry, Service-Profile unterscheiden.
3. `docs/architecture/studio/README.md`, `00-Gesamtkarte.md`, `01-Daten-und-Transaktionen.md`, `02-StudioCoordinator.md`, `03-Geplante-Editoren.md`, `04-Verbindungsregister.md`.
4. **Normative Inspector-Spezifikation:** `docs/architecture/studio/widgets/ActionInspector.md`. Diese enthält die vollständige Feldmatrix, fachliche Grenzen und Verlustschutzregeln.
5. `docs/architecture/studio/widgets/{ActionCatalog,NativeProjectExplorer,ContextHelp,ProblemsPanel,KeypadPreview}.md` und `docs/architecture/studio/services/NativeProjectSession.md`.
6. `work/acceptance/20261106-studio-coordinator/ABNAHME.md` und `work/acceptance/20261106-help-coverage/ABNAHME.md`.
7. `src/adapters/logitech/native.py` (vollständig, insbesondere `parse_native_project`, `_parameters`, `_states`, `_editor_controls`, `_relative_path`), `schemas/logitech_native_v1.schema.json`, `src/core/ids.py`.
8. `src/studio/native_session.py`; `src/studio/native_shell/{__init__,coordinator,window,help_bindings}.py`.
9. `src/studio/context_help/{entries,registry,coordinator,widget}.py` und `src/studio/context_help/resources/*topics.de.json`.
10. `src/studio/action_catalog/widget.py`, `src/studio/native_project_explorer/widget.py`, `src/studio/keypad_contract.py`.
11. `examples/project_logitech_native_v1.json` mit vier nativen SDK-Typen.
12. `tests/test_studio_coordinator.py`, `tests/test_native_studio_shell.py`, `tests/test_native_help_coverage.py`, `tests/test_native_session.py` und `tools/run_native_studio_lab.py`.

**Vor erster Änderung:** Vollständige Datei-/SHA-256-Baseline der produktiven und dokumentarischen Projektdateien anlegen unter `work/action-inspector/AP-INSP-001/baseline-before.json`. Projektroot hat in früheren APs kein aktives Git-Repository gehabt; also nicht von Git als Änderungsquelle ausgehen. Laufende fremde Änderungen nicht überschreiben. Snapshot und Reviewartefakte nur in `work/action-inspector/AP-INSP-001/`. Eigenen kompletten Prompt unverändert als `01_original_prompt.md` ablegen.

## 1. Ziel und Abnahmegegenstand

Implementiere einen **vollständig integrierten ActionInspectorWidget v1** als PySide6-Widget **ohne QML** für alle **vier im Parser erlaubten SDK-Klassen**:

- `PluginDynamicCommand`
- `PluginMultistateDynamicCommand`
- `PluginDynamicAdjustment`
- `ActionEditorCommand`

Es geht nicht nur um einen Namen-Editor: Die gemeinsamen und typspezifischen Felder (einschließlich Parameter, States, Adjustment, EditorControls und Asset-Referenzen) müssen **tatsächlich bearbeitbar** sein und einen validierten NativeProjectSession-Commit erzeugen können. Es darf dabei weder `NativeAction` als Schreibautorität noch eine neue persistente Aktionsdatenbank eingeführt werden.

Bewusst **NICHT** in diesem Paket: Neu-Anlegen/Löschen von Actions, Action-ID-/SDK-Typ-Wechsel, neue Handler/Callbacks, Folder-Platzierung ändern, Plugin-Service-Updates, Keypad-Frame-/Slot-Abbildungen, Asset-Dateien oder ICT schreiben, LP5-/ProfileInfo-Import/Export. Action-Erstellung/Löschung soll ein separates **AP-INSP-002** werden. Daher den bestehenden deaktivierten `+ Neue Aktion`-Button **nicht** versehentlich aktivieren.

## 2. Technische Entwurfsarchitektur

**Neue produktive Dateien** (exakte Pfade):
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\action_inspector\__init__.py`
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\action_inspector\draft.py` – **Qt-frei**; defensiver JSON-Entwurf/gezielter Patch, lokale Diagnose-/Änderungsabfrage, keine Dateizugriffe
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\action_inspector\widget.py` – echte PySide6-Oberfläche inkl. Typspezialbereichen und editierbarer Collection-Zeilen
- Optional weitere kleine Qt-Unterwidgets **nur innerhalb** `src/studio/action_inspector/` mit begründetem Bedarf.

Der Draft ist **transient** und actionbezogen (Action-ID + opake Baserevision + exakte Originalrohdaten). Er darf nie eine eigenständige persistierte Action- oder Binding-Domäne bilden. Speichern von Roh-JSON nur durch `NativeProjectSession.replace(proposed,base_revision=...)` in einem Host-/Coordinator-Aufruf. Kein Session-Objekt und keine SDK-Service-Anbindung im Widget.

Empfohlener Hostvertrag:
- `inspector.set_action(project,action_id,raw_action,revision)` oder fachlich gleichwertiger, streng typisierter Setter mit **defensiver Kopie**.
- Qt-Signale für `applyRequested`, `draftDirtyChanged`, `discardRequested`; keine direkten Aufrufe der Session.
- `StudioCoordinator.apply_action_edit(action_id,proposed_action,*,base_revision)`: NativeProjekt-JSÓN-`snapshot()` kopieren, aktuelle Action über **exakte ID** finden, nur das betreffende Action-Objekt ersetzen, vollständiges Dokument via `Session.replace` validieren, dann alle Ansichten aktualisieren. Veraltete Revision oder verschwundene ID: Fehler und kein Commit. Bestehende `rename_action`-Schnittstelle für Bestands-/Kompatibilitätstests beibehalten.
- Jeden erfolgreichen Apply **als genau einen Session-Historyeintrag**, kein Autosave. No-op darf keine neue History erzeugen.

Der nativen JSON-Parser `parse_native_project` ist die **einzige fachliche letzte Validierungsautorität**. Lokale Inlinefehler dürfen seine Regeln ergänzen/erklären, aber keine ungesicherte SDK-Semantik erfinden. Keine generische JSON-Text-Editierfläche als Ersatz für Formulare.

## 3. Formularumfang – verbindliche Matrix

**Gemeinsam (alle vier Typen):**
- Read-only `id` und `sdk_type`.
- editierbar `display_name` (nicht leer), `description` (leer erlaubt), `group_name` (nicht leer), `handler` als Auswahl aus echten `handlers[].id`.
- `parameters` als strukturierte Zeilenliste: `name`, `display_name`, `group_name`, optional `super_group_name`; Einfügen, Ändern, Löschen, Umordnen; Namen im Projekt-Actionumfang eindeutig.
- `icon` (`.png/.svg`), `icon_template` (`.ict`), `symbol` (`.svg`) als **projekt-relative Datei-REFERENZEN** mit eindeutiger Null-/Leer-/Entfernen-Option. **Kein Schreiben oder automatisches Erzeugen der Dateien**.
- `parameter_symbols` als Zuordnung vorhandener Parametername → relative `.svg`-Referenz. Beim Umbenennen/Löschen eines referenzierten Parameternamens den Konflikt sichtbar machen und nur nach expliziter Zustimmung/Benutzerentscheidung das Mapping passend aktualisieren oder entfernen. Niemals still Daten verlieren.

**PluginMultistateDynamicCommand:**
- `states[]` voll editierbar mit `name,display_name,description,image` (optional `.png/.svg`), Einfügen/Löschen/Umordnen. Indices werden nur aus der geordneten Liste 0..N-1 erzeugt; mindestens zwei States.
- `state_change`: `none` / `increment` / `decrement` / `toggle`; Toggle erfordert exakt zwei States.
- `led_color` ist ausdrücklich **nicht** zu unterstützen (im installierten SDK nicht verifiziert).

**PluginDynamicAdjustment:**
- `adjustment.has_reset` Boolean, optionale endliche Zahlen `minimum`/`maximum`/`default` und `format`.
- Bounds logisch konsistent; kein NaN/Infinity, bool nicht als Zahl akzeptieren.

**ActionEditorCommand:**
- `editor_controls[]`: Hinzufügen, Editieren, Entfernen und Umordnen jedes vorhandenen Types: `textbox`, `checkbox`, `textarea`, `file_selector`, `directory_selector`, `slider`, `numeric_up_down`.
- Felder nach gültigem Typ: gemeinsame `type,name,label,description`; Checkbox `default` nur bool; numeric `minimum,maximum,step,default` erforderlich und endlich, optional `format_string`; File/Directory `dialog_title,initial_directory`, `filters[{pattern,label}]` nur File Selector. Nicht passende Felder beim Wechsel vorhandener Controls **nicht still entfernen**: die Aktion mit expliziter, verständlicher Warnung abfangen. Da SDK-Typwechsel dieser Action verboten ist, nur Control-Type-Wechsel wenn im selben Editor sicher.
- Nicht bearbeitete optionale Feldabsenzen im Roh-JSON bleiben nach Laden/Wegklicken/erneutem Laden identisch; spätere Apply patcht tatsächlich geänderte Werte, keinen stillen Komplett-Normalisierungsroundtrip.

**Nicht zutreffende Felder** dürfen für andere Aktionstypen nicht als valide Schreibfelder erscheinen (z. B. kein `states` bei DynamicCommand). Kein falsches Typmapping zur alten `0.1-draft`-Welt.

## 4. Nutzerführung und sichere Draft-Lebenszyklen

Baue eine **permanent erreichbare Inspector-Ansicht** im bestehenden Tab-Bereich der `NativeStudioShell`, neben Details/Probleme/Hilfe/gesperrter Preview. Gute Bedienbarkeit bei schmaler Sidebar und 150 % DPI; Gruppenüberschriften, verständliche Labels, Inlinevalidierung, Apply/Verwerfen und klare Anzeige „ungespeicherter Formularentwurf“.

- Bei Action-Auswahl im Explorer/Katalog Anzeige der genau referenzierten Action. Bei FolderEntry nur die tatsächlich referenzierte Action anzeigen; FolderEntry selbst **nicht** umschreiben.
- **Katalog-Button Bearbeiten öffnet den Inspector-Tab.** Das ist eine ausdrücklich **gewollte Produktänderung** des AP. Die Toolbar-Aktion `Anzeigename` bleibt als bestehender, rückwärtskompatibler QInputDialog-Schnelleditor erhalten.
- Bestehende Tests, die `actionEditRequested` aus dem Katalog als alten Modal-Dialog interpretieren (z. B. `tests/test_native_studio_shell.py::test_v31_catalog_edit_to_dialog` und `tests/test_native_help_coverage.py::test_catalog_edit`), **nur genau insoweit aktualisieren**, wie sich die gewollte Navigation tatsächlich geändert hat. Durch neue echte Qt-Navigationstests ersetzen; niemals Tests abschalten oder pauschal assertions streichen.
- **Draft-Dirty ist unabhängig von Session-Dirty.** Benutzer kann ein Formular ändern, ohne dass `Session.dirty` gesetzt oder eine Datei beschrieben wird. Bei Auswahlwechsel, Reload, Open/Projektwechsel, Fensterschließen: Apply/Verwerfen/Abbrechen anbieten bzw. aktuelle Entwurfsansicht sicher beibehalten; **kein stiller Verlust**.
- Bei nicht aktualisierbarer/stale Revision oder von außen geänderter Projektdatei: keine stille Revisionserhöhung, keine Überschreibung und kein unbemerkter Rebase. Benutzer kann bewusst neu laden, verwerfen oder zur Bearbeitung zurückkehren.
- Nach Commit, Undo/Redo/Save werden Explorer, Katalog, Inspector, Hilfethemen, Status, Undo-Knöpfe konsistent aktualisiert. Bei aktuell markiertem Editor-Feld darf ein Host-Refresh den noch nicht angewendeten Entwurf nicht überschreiben.
- Bei invalidem Formular lokalisierte Diagnosen am betroffenen Feld anzeigen und eine hilfreiche ProblemsPanel-Quelle nur nach echter Quelle/aktueller Revision melden. `Diagnostic.path` nicht als native Entity-ID ausgeben.
- Keine implizite Dateipfad-Wahl / DevicePlacement-Generierung. Das Originalbeispiel `examples/project_logitech_native_v1.json` bleibt byteidentisch; Labs arbeiten mit einer temporären Projektkopie.

## 5. Kontexthilfe in demselben AP implementieren

Die bereits unabhängig abgenommene Hilfe von AP-HELP-001 gehört **verbindlich** zum Inspector.

- Neues Themenpaket: `src/studio/context_help/resources/inspector_topics.de.json`, Registryquelle `inspector` über bestehenden `register_topics`.
- `NativeHelpBindings` erweitert seine fensterlokalen F1-/FocusIn-/Pin-/Related-Zuordnungen um **jedes relevante Inspector-Control** inklusive dynamisch hinzugefügter Parameter-/State-/EditorControl-Zeilen, Fehleranzeigen und Apply/Discard.
- Keine direkte `ContextHelpWidget`-Referenz im Inspector, keine zweite Registry, kein allgemeiner EventBus und kein globaler Fokusfilter.
- Themen u. a. `inspector.overview`, `inspector.identity`, `inspector.handler`, `inspector.parameters`, `inspector.parameter_symbols`, `inspector.states`, `inspector.state_change`, `inspector.adjustment`, `inspector.editor_controls`, `inspector.assets`, `inspector.apply`, `inspector.discard`, `inspector.invalid`. Titel, kurze Zusammenfassung, verständliche Anleitung/Beispiel, sinnvolle Related-Topics auf Deutsch; nur bestätigte SDK-Semantik beschreiben.
- Fakten dürfen keine API-Keys, Rohinhalte aus Dateisystemen, privaten absoluten Pfade oder unvalidierten Benutzereingaben enthalten. Bestehende Default-16-Themen nicht ändern, bisherige AP-HELP-001-Quellen nicht duplizieren.
- Bisherige `tests/test_native_help_coverage.py`-Erwartung von **42 Themen** ist historische Baseline; nach neuen Inspector-Themen die betroffenen Prüfungen **spezifisch** aktualisieren, neuen vollständigen Thema-/Owner-Test ergänzen, alte Funktionen weiter abdecken. Keine Aussagen „alles abgedeckt“ ohne eigenes Coverage-Register.

## 6. Schreibscope – explizit und begrenzt

**Produktionsdateien NEU:** `src/studio/action_inspector/{__init__,draft,widget}.py`, bei Bedarf ausschließlich kleine weitere Dateien dort; `src/studio/context_help/resources/inspector_topics.de.json`.

**MINIMAL Änderbar:** `src/studio/native_shell/{coordinator,window,help_bindings}.py`. Bestehende öffentliche APIs erhalten; Implementierung nur der nötigen Inspector-Host-Verbindungen.

**Tests NEU:**
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\tests\test_action_inspector_draft.py`
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\tests\test_action_inspector_widget.py`
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\tests\test_action_inspector_integration.py`
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\tools\run_action_inspector_lab.py` (CLI `--smoke` und `--evidence <dir>`).

**Bestehende Tests nur minimal bei absichtlich veränderter Katalog-Edit-Navigation / neuer Registry-Themenanzahl anpassen** und jede Änderung im Review-Protokoll auf Funktionsebene erklären. Keine Änderungen an bestehenden Tests, nur um Regressionen zu verdecken.

**Dokumentation VERPFLICHTEND:**
- `docs/architecture/studio/widgets/ActionInspector.md` (von GEPLANT zu tatsächlich implementierter Schnittstellenreferenz)
- `docs/architecture/studio/{README,00-Gesamtkarte,01-Daten-und-Transaktionen,02-StudioCoordinator,03-Geplante-Editoren,04-Verbindungsregister}.md`
- `docs/architecture/studio/widgets/{ActionCatalog,NativeProjectExplorer,ContextHelp}.md`, wenn deren Hostrouten tatsächlich betroffen sind
- `work/planning/README.md` Status `IN_PROGRESS/READY_FOR_REVIEW` und nachgewiesene Grenzen, **keine Selbstabnahme**.

**Arbeitsakte:** `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\work\action-inspector\AP-INSP-001\`. Hier `README.md`, `01_original_prompt.md`, `02_verlauf.md`, `03_ergebnisse.md`, `04_abschlussbericht.md`, `baseline-before.json`, `scope-after.json`, `coverage-after.json`, Testlogs, Exitcodes, Screenshot-Evidenz und vollständige End-to-End-Benutzerreise.

**Nicht verändern:** `src/studio/app.py`, `src/studio/native_session.py`, `src/adapters/logitech/native.py`, `schemas/`, `src/studio/native_ict_binding.py`, bestehende Widgetimplementierungen (`action_catalog`, `native_project_explorer`, `problems_panel`, `keypad_preview`), bestehende Hilfe-Kernklassen, `src/runtime`, `src/core`, Legacy-/Logitech-Service-/Plugin-/Profil-Dateien sowie frühere Abnahmeakten. Keine Pakete, Services oder kommerziellen Tools installieren.

## 7. Etappen und verbindliche Tests

**A – Qt-freier Draft/Mutationsvertrag.** Baue defensive Ein-/Ausgabe und unveränderte Identität/Typgarantie. Parameternamen, Symbolreferenzen, State-Indices und EditorControl-Optionen sicher behandeln. Neue Unit-Tests für jeden SDK-Typ, optionale Feldabwesenheit, No-op, fehlerhafte Typen, referenzierte Namen und nicht mutierte Eingangsdaten. Kein Produkt-Session-Commit in diesem Schritt.

**B – Wiederverwendbares Widget und echte UI.** Strukturierte native Controls, typspezifische Bereiche, Liste-Editoren für `parameters/states/editor_controls`, Projekt-Referenzen, Inlinevalidierung, Draft-Dirty und ein einziger Apply-Intent. Offscreen-Widgettests plus Windows-GUI-Screenshot je SDK-Typ.

**C – Hostintegration & Draft-Verlustschutz.** Inspector in NativeStudioShell einfügen, echte Action-/FolderEntry-Auswahl, Katalog-Bearbeiten→Inspector, Toolbar-Schnellrename weiterhin funktionsfähig, validierter Coordinator-Commit. Undo/Redo/Save/Reload, Folder-/Handler-Referenzgleichheit, stale/missing ID, DiskConflict, Draft bei Auswahl-/Projektwechsel/Schließen; keine Halbtransaktion. Fenster-/Lifecycle-Tests auf Windows.

**D – Kontexthilfe & Architektur.** Themenquelle `inspector`, Control-Fokus, F1, Pin, Related-Topics, strukturierte Coverage und Datenschutz. Jedes aktive Control bekommt belegten Kontext; neues Verbindungsregister ab **V-53** (V-01–V-52 nicht still umnummerieren). Echte aktuelle Gesamtkarte und individuelle Schnittstellenreferenz; neue Kante nur bei Code + eigenem Integrationstest als IMPLEMENTIERT dokumentieren. Screenshots hell/dunkel, schmal/breit, hoher DPI und Fehlersituation.

**Pflichtbefehle** – selbst ausführen, Exitcodes und Logauszüge im eigenen Run sichern:

```powershell
$env:QT_QPA_PLATFORM="offscreen"
python -m unittest discover -s tests -p test_action_inspector_draft.py -v
python -m unittest discover -s tests -p test_action_inspector_widget.py -v
python -m unittest discover -s tests -p test_action_inspector_integration.py -v
python -m unittest discover -s tests -q
python tools/run_action_inspector_lab.py --smoke
python tools/check_links.py
```

**Windows-GUI erforderlich:** Mit echter Qt-Windows-Plattform `python tools/run_action_inspector_lab.py --evidence work/action-inspector/AP-INSP-001/screenshots`. Offscreen allein ist kein visueller Nachweis. Mindestens 4 Action-Typen + Dirty/Validierung + Hilfe/Pin/SDK-Referenz prüfen. Testmodus ausschließlich auf temporären Kopien der nativen Projektdatei; Originaldateien und Assets bleiben byteidentisch.

**Explizite negative Tests:**
1. Auswählen/Anzeigen/Abbrechen hinterlässt Sessionrevision, `dirty` und JSON vollständig unverändert.
2. Ungültiger Handler, doppelter Parametername, fehlerhafte Symbolreferenz, `toggle` mit drei States, Lücke im State-Index, unzulässige EditorControl-Optionen/Bounds → keine Mutation.
3. Bestehende Action-ID und SDK-Typ können im Inspector nicht geändert werden; FolderEntry-Referenzen unverändert.
4. Zwei echte Formulareingaben + Apply ergeben **einen** Session-Commit, Undo/Redo, Save und frischer Ladezyklus erhalten die fachlichen Felder.
5. Selektionswechsel bei Dirty-Draft, Reload, Projektwechsel und Schließen: Apply/Verwerfen/Abbrechen ohne Datenverlust. Stale Revision führt zu dokumentiertem Fehler, kein stilles Rebase.
6. Keine Änderung an durch dieses AP nicht betroffenen Actions/Handlers/Folders und keine ICT-/Keypad-/Logitech-Servicewrites.
7. Help-Fokus/F1/Pin/Related für Inspector-Felder und dynamische Zeilen, keine Weitergabe privater Rohdaten.
8. Frühere 925 Baseline-Tests weiter grün (Erwartungsänderungen nur bei bewusst veränderter Katalog-Edit-Route/Topics, siehe Abschnitt 6).

## 8. Abschluss und Folgephase

Nach Implementierung eine reproduzierbare, fachlich nachvollziehbare **vertikale Benutzerreise** dokumentieren: Native Projektdatei öffnen → vorhandene Action wählen → Common- und Typ-Spezialfeld ändern → Inlineprüfung → Apply → Explorer/Katalog/Inspector synchron → Undo/Redo → explizites Save → Datei neu laden → korrekte F1-Hilfe.

Das Ergebnis des Agents heißt **READY_FOR_REVIEW**, niemals APPROVED. Der Nutzer wird selbst eine unabhängige Abnahme beauftragen. Bei gewöhnlichen Implementierungs-/Testfehlern eigenständig korrigieren; BLOCKED nur bei nachgewiesener extern unlösbarer Sperre. Keine Agenten-Folgebeauftragung, kein zeitgesteuertes Monitoring.

**Nächste fachliche Etappe nach unabhängiger Freigabe:** AP-INSP-002 zum sicheren **Erstellen/Löschen** von NativeActions inklusive Schutz von FolderEntry-, Handler- und Parameterreferenzen. Noch keine Gerätetasten- oder SDK-Service-Funktion vortäuschen.
