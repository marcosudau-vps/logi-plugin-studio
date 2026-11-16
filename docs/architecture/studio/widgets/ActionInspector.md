# ActionInspector – SDK-nativer Aktionseditor (Create/Edit)

**Aktueller Stand AP-INSP-002: IMPLEMENTIERT / APPROVED.** Die v1-Abnahme bleibt historische Baseline; Create/Edit, Delete, Accordion und Stale sind unten und in [ActionLifecycle](ActionLifecycle.md) als geprüfte Erweiterung dokumentiert. [Unabhängige Freigabe](../../../../work/acceptance/20261106-action-lifecycle/ABNAHME.md) erfolgt.


**Stand:** 06.11.2026 · **Status: IMPLEMENTIERT / APPROVED**, unabhängige Abnahme am 06.11.2026 erfolgt. Zielauftrag [AP-INSP-001](../../../../work/planning/AP-INSP-001-native-action-inspector-v01.md).  
Grundlage: [ARCH-ADR-001](../../../decisions/ARCH-ADR-001.md), [Native First v0.2](../../../specifications/logitech-profil-und-aktionsmodell-basis-v02.md), `src/adapters/logitech/native.py` und `schemas/logitech_native_v1.schema.json`.

## 1. Aufgabe und Datenautorität

Der Inspector bearbeitet **bereits vorhandene** SDK-native `NativeAction`-Definitionen im geöffneten `logitech-native-1`-Autorenprojekt, nicht die serviceverwalteten Logitech-`ProfileInfo.json`-Aktionen. Er besitzt **keinen** Dateiwriter und keine zweite Persistenz. Ein flüchtiger Entwurf wird erst nach ausdrücklich ausgelöstem Apply durch den `StudioCoordinator` per `NativeProjectSession.replace(proposed, base_revision=...)` validiert und übernommen. `save()` bleibt ein separater User-Befehl.

**Nicht Teil von AP-INSP-001:** Erstellung/Löschung von Actions, Action-ID-Umbenennung, SDK-Typwechsel, Handler-Erstellung, Folder-/Placement-Änderungen, Ausführung von Python-Callbacks, ICT-/PNG-/SVG-Asset-Writes, Plugin-Service-Installation, LP5-/Profil-Writer. **AP-INSP-002** soll danach Erstellen/Löschen regeln.

## 2. Felder: Existierender Parser ist normativ

| Scope | Bearbeitung | fachliche Grenze |
|---|---|---|
| `id`, `sdk_type` | sichtbar und kopierbar, **read-only** | stabile Identität/kein Typwechsel |
| `display_name` | einzeilig | nicht leer |
| `description` | mehrzeilig | leer erlaubt |
| `group_name` | einzeilig | nicht leer; fehlendes Feld bisher mit Pluginname abgeleitet |
| `handler` | Auswahl aus aktuell vorhandenen `handlers[].id` | keine neuen Handler/Callback-IDs erfinden |
| `parameters[]` | Einfügen/Ändern/Entfernen/Sortieren: `name,display_name,group_name,super_group_name` | eindeutige Namen; referenzierte Parameter-Symbole nicht still verlieren |
| `icon` | Projekt-relative Referenz `.png/.svg` | kein Asset-Writer |
| `icon_template` | Projekt-relative Referenz `.ict` | kein ICT-Writer |
| `symbol` | Projekt-relative Referenz `.svg` | kein Symbol-Writer |
| `parameter_symbols` | Name→SVG-Projektreferenz | Name muss in `parameters[]` vorhanden sein, Konflikte explizit behandeln |
| Multistate `states[]` | Name, Anzeige, Beschreibung, Bild; Reihenfolge/Zeilen | Index 0-basiert lückenlos, mind. zwei; `toggle` exakt zwei; kein `led_color` |
| Multistate `state_change` | `none,increment,decrement,toggle` | nur Typ `PluginMultistateDynamicCommand` |
| Adjustment `adjustment` | `has_reset,minimum,maximum,default,format` | nur `PluginDynamicAdjustment`, endliche Zahlen, Bounds/Default passend |
| ActionEditor `editor_controls[]` | Typ, Name, Label, Description, options; Zeilen einfügen/entfernen/umordnen | nur `ActionEditorCommand`; exakte SDK-Parserregeln |

Unterstützte `editor_controls`: `textbox`, `checkbox`, `textarea`, `file_selector`, `directory_selector`, `slider`, `numeric_up_down`. Für numerische Controls sind Minimum, Maximum, Step und Default erforderlich; Checkbox-Default nur Boolean; Dialogoptionen nur File-/Directory-Selector, Filter nur File-Selector. Alle Anpassungen entsprechend `parse_native_project` einschließlich `_editor_controls` und `_relative_path`.

**JSON-Roundtrip:** Absente optionale Felder/Collections dürfen beim bloßen Anzeigen/Re-Selektieren nicht ungefragt hinzugefügt oder normalisiert werden. Beim Apply unveränderte Rohdaten erhalten, lediglich tatsächlich bearbeitete Teilfelder patchen; finale Parservalidierung vor Session-Commit.

## 3. Entwurf, Revision und Verlustschutz

- Einer Action-ID wird ein **flüchtiger** Draft samt opaker `base_revision` zugeordnet. In einer UI-Sitzung höchstens ein offener schreibbarer Draft.
- Das Formular ändert niemals direkt `NativeProjectSession`, `NativeProject` oder eine Datei; ein Apply erzeugt **höchstens einen** Session-Commit.
- Aktuelle native `action_id` muss vor Commit existieren und `base_revision` exakt passen; niemals still rebasen oder auf gleiche Anzeigenamen ausweichen.
- Ungültige Felder inline mit klaren Erläuterungen markieren, keine Abstürze/halben Commits. `parse_native_project` bleibt finale Wahrheit.
- Bei Auswahlwechsel, Projektwechsel, Reload oder Fensterschließen mit ungespeichertem **Formulardraft** explizit Apply/Verwerfen/Abbrechen anbieten. Session-Dirty und Inspector-Draft-Dirty sind unabhängig zu schützen. Ein Benutzerabbruch erhält Session und Formularwerte.
- Nach Commit/Undo/Redo/Save/Reload frischen Session-Snapshot auslesen, Selektion/Felder/History/Hilfe aktualisieren. Bei externem DiskConflict nie überschreiben.
- Von einem `NativeFolderEntry` darf optional die referenzierte Action im Inspector dargestellt werden, aber der FolderEntry selbst bleibt unberührt.

## 4. Implementierter UI- und Host-Vertrag

- Eigene `ActionInspectorWidget(QWidget)`-Ansicht im **bestehenden Tab-/Detailbereich** der `NativeStudioShell`. Deutlich getrennte allgemeine und typspezifische Bereiche, feldbezogene Hilfe, verständliche Tooltips und Inlinefehler.
- Host → Widget: `set_action(project_snapshot, action_id, raw_action, revision)` oder äquivalente immutable/defensive Payload.
- Widget → Host: `applyRequested(str action_id, str base_revision, object proposed_action)`, `draftDirtyChanged(bool)`, `discardRequested()`, `diagnosticsChanged(object)` mit DraftDiagnostic-Tuple.
- Host validiert, patched nur passende Action unter `actions[]` und führt `Session.replace` aus. Der Inspector darf nicht direkt auf die Session zugreifen.
- Der Katalog-Button **Bearbeiten** öffnet den Inspector-Tab. Der bestehende Toolbar-Befehl **Anzeigename** bleibt als rückwärtskompatible Schnell-Umbenennung über `QInputDialog`. Zwei bestehende Tests erwarten ausdrücklich den alten Katalog→Modal-Weg: Diese Tests nur als **dokumentierte Produktverhaltensänderung** ersetzen und mit echten Inspector-Navigationstests nachweisen, keinesfalls nur löschen/deaktivieren.
- Kein globaler EventBus, keine direkte Widget↔Widget-Schreibverbindung und kein Keypad- oder ICT-Writer.

## 5. Einbindung der bereits abgenommenen Kontexthilfe

- Eigene `inspector_topics.de.json` mit Registryquelle `inspector`; Hilfetexte für Draft/Apply/Cancel, Identität, Handler, Parameter, Symbolreferenzen und die vier SDK-Typen.
- `NativeHelpBindings` verbindet echte Inspector-Controls mit Topics/F1/Pin/Related. Aktuelle Daten-Facts dürfen keine Token, absoluten privaten Pfade, ungeprüften Diagnosemeldungen oder rohen Formulareingaben enthalten.
- Keine neue `HelpCoordinator`- oder `ContextHelpWidget`-Instanz. Änderungen der aktuellen Hilfetests aufgrund neuer Registrierungen **nachvollziehbar und minimal-invasiv** anpassen.
- Neue Kanten im [Verbindungsregister](../04-Verbindungsregister.md) ab **V-53**, jede nur mit Code **und** konkretem bestandenem Integrationstest als IMPLEMENTIERT. [Gesamtkarte](../00-Gesamtkarte.md) und diese Komponentenreferenz im selben AP auf tatsächlich implementierten Stand aktualisieren.

## 6. Abnahmekriterien

1. Alle vier SDK-Typen laden, inklusive Liste-/Spezialfeldern; bestehende ID und SDK-Typ unverändert.
2. Keine Änderung beim reinen Anzeigen, Abbrechen, ungültigen Draft oder Verwerfen.
3. Eine gültige Apply-Aktion führt genau einen Session-Commit aus; Undo/Redo/Save/Reload erhalten alle Daten und Referenzen.
4. Verlustschutz bei Auswahlwechsel/Reload/Projektwechsel/Schließen; stale Revision und verschwindende Action führen fail-closed zu keinem stillen Rebase.
5. Felder/Fehler/F1/Pin/Related und die eingebettete GUI unter Windows getestet und dokumentiert.
6. Ursprüngliches `0.1-draft`-Studio sowie Keypad-/ICT-Read-only-Grenzen unverändert.
7. Eigene Widget-Dokumentation, Gesamtkarte, Verbindungsregister samt Integrationstests vervollständigt; unabhängige Abnahme danach.

**Folgeschritt:** AP-INSP-002 – native Actions erstellen/löschen und Referenzsicherheit; kein neuer Action-/Profil-Persistenztyp.

## Implementierungsreferenz AP-INSP-001

Code: `src/studio/action_inspector/{draft,widget}.py`. Qt-freier `ActionDraft(project,action_id,raw_action,revision)` kopiert Ein-/Ausgabe defensiv. `snapshot()`, `dirty`, `base_revision`, `set_field`, `remove_field`, `set_rows`, `symbol_conflicts`, `resolve_symbol`, `diagnostics`, `proposed_action`, `discard` sind transient. Identität und Typ sind unveränderlich. `set_rows('states',...)` erzeugt Indizes aus der Reihenfolge; ungepatchte Rohdaten werden nicht normalisiert. Diagnosen prüfen den vollständigen Projektentwurf mit dem nativen Parser und zusätzlich endliches JSON.

`ActionInspectorWidget.set_action(project,action_id,raw_action,revision)` akzeptiert nur bei sauberem Formular einen neuen Snapshot; `action_id=None` leert die Ansicht. `dirty` enthält auch nicht darstellbare doppelte Symbolzeilen. `accept_applied()` ist die Hostbestätigung vor dem unmittelbar folgenden frischen Setter, `show_host_error(message)` erhält den Draft bei Fehlern. Kein Sessionobjekt und kein Dateizugriff im Widget.

Die Formulare `ObjectForm`, `ValueField` und `RowsEditor` liegen ausschließlich im Inspector-Modul. Jeder Collection-Eintrag besitzt einzelne native Eingabefelder und Auf-/Ab-/Entfernen-Buttons. File-Selector-Filter sind eigene strukturierte Zeilen. Optionale Felder unterscheiden Nicht gesetzt/entfernen, Null und Wert; ungültige Optionen bleiben diagnostizierbar. Reines Laden patcht nichts. Bei einem Control-Typwechsel fragt eine konkrete Warnung nach dem Entfernen inkompatibler Optionen. Parameter-Symbolkonflikte bleiben als Zeilen erhalten, bis der Nutzer sie bewusst ändert oder entfernt.

`StudioCoordinator.apply_action_edit(action_id,proposed_action,*,base_revision)` prüft Revision, exakte ID, unveränderten SDK-Typ, Parser und lesend die vorhandene Session-Diskbaseline (`_check_disk`), ersetzt genau eine Action und ruft einmal `replace` auf. Diese Nutzung des vorhandenen privaten Diskchecks vermeidet eine zweite Baseline; ein öffentlicher Read-only-Check wäre eine spätere Session-API-Erweiterung außerhalb dieses Schreibscopes. Save wiederholt den Check. Die Session besitzt weiterhin allein History und Dateiwrites.

Die Shell schützt Auswahl einschließlich Filterverlust, Toolbar-Undo/Redo, Save, Reload, Open und Close. Übernehmen/Verwerfen/Abbrechen sind echte Qt-Dialogoptionen. Bei Open/Reload wird Verwerfen bis zu erfolgreichem Laden aufgeschoben; fehlende Ziele erhalten den Draft. Direkter Coordinator-Projektwechsel ohne `discard=True` verweigert offene Drafts. Ein externer Hostrefresh erhält einen Dirty-Draft samt alter Baserevision; erneutes Apply scheitert sichtbar statt Rebase. Die Inspector-Problemsquelle verwendet ausschließlich aktuelle Draftrevisionen und Diagnosepfade, keine erfundene Entity-ID.

Hilfe: 13 neue `inspector.*`-Topics aus Quelle `inspector`, insgesamt 55 Themen. Controls deklarieren `inspectorTopic`; nur `NativeHelpBindings` übersetzt im eigenen Fenster inklusive dynamischer Kinder in `HelpContext`. Facts sind für Inspector-Controls leer. F1/Pin/Related verwenden den bestehenden HelpCoordinator.

Nachweise: [Arbeitsakte](../../../../work/action-inspector/AP-INSP-001/README.md), `tests/test_action_inspector_{draft,widget,integration}.py`, `tools/run_action_inspector_lab.py --smoke` und `--evidence <dir>`. Windows-Qt-Aufnahmen verwenden QWidget.grab unter echter Windows-Plattform; keine Offscreen-Screenshots als Windowsbeleg. Neue Verbindungen V-53–V-62 im [Register](../04-Verbindungsregister.md). Unabhängige Freigabe erfolgt separat durch den Reviewer.

## Unabhängige Abnahme 06.11.2026

**APPROVED** im v1-Umfang für vorhandene SDK-Actions. [Prüfbericht und eigene Windows-Gegenproben](../../../../work/acceptance/20261106-action-inspector/ABNAHME.md). Erstellung/Löschung, Handler-/Folder-/Device- und Asset-Writer verbleiben aufgeschoben.


## Ergänzung AP-INSP-002 – IMPLEMENTIERT / APPROVED

[ActionLifecycle- und UX-Vertrag](ActionLifecycle.md): Der Inspector erstellt alle vier nativen Typen mit denselben Feldeditoren. `start_create(snapshot,revision,project_token)` setzt einen separaten CreateDraft; ID/Typ bleiben bis zum Apply editierbar. `createRequested(token,revision,proposed_action)` ergänzt den bestehenden Editintent. Ein erfolgreicher Hostcommit liefert Editmodus mit readonly Identität. Delete ist nur für explizite Action-Auswahl und nach aktueller Referenzprüfung/Bestätigung verfügbar. Referenzierte und letzte Actions bleiben geschützt; FolderEntry-Auswahl bietet keine Placement-Löschung.

**OBS-INSP-001 umgesetzt:** ObjectForm/RowsEditor basieren auf FoldSection mit sichtbarem Toggle, Tastatur-/Screenreader-Beschriftung und kompakten Zeilen. Allgemein startet offen, andere Sachgruppen kompakt. Individuelle Zeilen zeigen Name sowie Control-Typ/State-Index. `set_expanded` verändert ausschließlich die Darstellung; Eingaben einschließlich ungültiger Werte und numerischer Textformatierung bleiben in denselben Widgets. Validierungsfehler öffnen passende Gruppen/Zeilen; der globale Prüfgrund bleibt sichtbar. Add/Remove/Reorder und Filter behalten ihre Fachverträge.

**OBS-INSP-002 umgesetzt:** Die Shell übergibt über `observe_context(revision,project_token,conflict)` die echte Hostkorrelation. Ein deutliches nicht modales Warnband unterscheidet Formular-Dirty von veralteter Session-/Dateibasis. Apply ist bei Stale gesperrt. `refreshRequested` führt nur nach bewusstem Klick zu Discard/Neu-Laden derselben Action-ID; bei verlorener ID bleibt ein erklärter Leerzustand. „Im Entwurf bleiben“ erhält alle Werte. Save ohne Revisionswechsel baut das Formular nicht neu. Der 350-ms-Beobachter erkennt auch direkte Sessioncommits und externe Bytekonflikte, ohne eine zweite Revision/Writerbaseline.

Zusätzliche Signale: `createRequested(str,str,object)`, `deleteRequested()`, `refreshRequested()`. `set_action` akzeptiert zusätzlich `project_token=None`; die Shell liefert stets ihren tatsächlichen Token. `CreateDraft` erbt nur gemeinsame Bearbeitung/Diagnostik; `_proposed_project()` hängt für die Parservalidierung eine defensive Kopie an. Keine Produktionssession wird zur Draftherstellung manipuliert.

[Neue Kanten V-63–V-70](../04-Verbindungsregister.md), [Tests, Windows-Nachweise und Scope](../../../../work/action-inspector/AP-INSP-002/README.md). AP-INSP-001 bleibt unabhängig APPROVED; die Erweiterung AP-INSP-002 ist **APPROVED**, keine Selbstfreigabe.
