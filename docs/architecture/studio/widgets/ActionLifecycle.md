# ActionLifecycle – Native Actions erstellen und löschen

**Stand:** 06.11.2026 · **Status: IMPLEMENTIERT / APPROVED (AP-INSP-002)**  
Fachliche Ergänzung zum [abgenommenen ActionInspector v1](ActionInspector.md), zur [Studio-Gesamtkarte](../00-Gesamtkarte.md) und zum [vollständigen Agentenauftrag](../../../../work/planning/AP-INSP-002-native-action-lifecycle-und-inspector-ux-v01.md).

## 1. Verantwortung und Writerhoheit

Neue Aktionen und Löschoperationen verändern die Root-Liste `actions[]` eines `logitech-native-1`-Autorenprojekts, **nicht** Logitech-Service-Profile, Gerätezuordnungen oder den SDK-Plugin-Service. Eine neu erzeugte Action ist zunächst **unplatziert**; keine automatische FolderEntry-Erstellung. Die eine Schreibkette lautet: UI-Intent → NativeStudioShell → StudioCoordinator → Qt-freie defensive Mutation eines aktuellen Snapshots → native Parservalidierung → genau ein `NativeProjectSession.replace(proposed, base_revision=...)`. Kein Autosave. Keine neue Persistenz oder eigener Dateiwriter.

## 2. Erstellen

- Die bestehende `ActionCatalogWidget.createActionRequested()`-Schnittstelle im Host anschließen. Der `EnabledChange`-Filter blockiert jetzt ausschließlich ohne geöffnete Session; mit geladenem Projekt bleibt Create auch nach internem Filter-/Sortierrefresh aktiv. Keine Änderungen am wiederverwendbaren Catalog-Widget.
- Benutzer erstellt eine Action in einem **flüchtigen Create-Draft**, der die bestehenden Inspector-Feldeditoren nutzt. Eingabe: einer der **vier** existierenden SDK-Typen, vor Commit editierbare und eindeutige Action-ID, Anzeigename und vorhandener Handler. Weitere gemeinsame und typspezifische Felder bleiben vollständig bearbeitbar.
- ID-Regel aus `src/core/ids.py`: `^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$`. Vorbelegter deterministischer Vorschlag wie `action.<slug>` mit kollisionsfreiem Suffix ist erlaubt, muss aber jederzeit vor dem Commit sichtbar/editierbar sein. Nach dem Commit sind ID und SDK-Typ immutable. Sichtbarer Name ist keine Identität.
- Erlaubte Initialwerte nur nach `src/adapters/logitech/native.py` und `schemas/logitech_native_v1.schema.json`:
  1. `PluginDynamicCommand`: Pflichtfelder ID/SDK-Typ/Anzeigename/Handler; Parameter optional/leere Liste erlaubt.
  2. `PluginMultistateDynamicCommand`: mindestens zwei feste Zustände mit Index 0 und 1, unterschiedlichen Namen, gültigem Anzeigenamen und leerer Beschreibung; `toggle` nur mit exakt zwei States.
  3. `PluginDynamicAdjustment`: `adjustment: {}` oder konsistente endliche Werte; kein NaN/Infinity.
  4. `ActionEditorCommand`: mindestens ein gültiger `editor_controls`-Eintrag wie `textbox` mit Typ/Name/Label; ein vorhandener leerer `editor_controls[]`-Array ist laut Parser ungültig.
- Vor Apply kein Eintrag in `NativeProjectSession.snapshot()['actions']`; ungültige ID, Duplikat, unbekannter Handler und fehlerhafter Typ erzeugen **keinen** Sessioncommit. Erfolgreiches Apply fügt **genau eine** Action mit **einem** Sessioncommit ein; Explorer/Katalog/Inspector synchronisieren und neue Action-ID selektieren. Keine implizite Folder-Belegung.

## 3. Löschen – explizit und referenzsicher

- Eigener Delete-Intent für ausgewählte native Action; vor Commit eine klare Bestätigung mit **ID und Anzeigename**.
- Bestehende `folders[*].entries[*].action`-Referenzen zur aktuellen Sessionrevision auswerten. Eine referenzierte Action **nicht** löschen; verständliche Anzeige mit Anzahl und Folder-/Placement-IDs. **Keine** stille Kaskadenlöschung, kein stilles Umhängen. Diese Operation gehört zu einem späteren FolderEditor.
- Die letzte native Action **nicht** löschen: der vorhandene Parser verlangt eine **nichtleere** `actions[]`-Liste. Ein nie referenzierter Handler bleibt erhalten, selbst wenn seine letzte Action gelöscht wurde; keine automatische Handlerbereinigung.
- Ein gültiges Löschen einer unreferenzierten Action führt zu **einem** validierten Sessioncommit; alle Ansichten, Selektion, Help-Kontext und ActionOffer werden aktualisiert. Undo stellt die vollständig identische Action wieder her, Redo löscht erneut, Save/Reload persistiert.
- Offene Inspector- oder Create-Drafts: vorher Apply/Verwerfen/Abbrechen, niemals stiller Datenverlust. Bei Cancel keinerlei Commit. Bei stale Revision, nicht mehr vorhandener ID, DiskConflict oder ungültigem Restdokument: fail-closed. Nicht anhand von Anzeigenamen abgleichen.
- Wenn das mitgelieferte Beispiel nur referenzierte Actions enthält, eine neue unreferenzierte Action erzeugen und **an dieser** die erfolgreiche Löschung testen; eine referenzierte Beispielaction ist ein expliziter Negativfall.

## 4. Verbindliche UX-Verbesserungen aus AP-INSP-001

**OBS-INSP-001 – kompakte Formulare:** Die nativen Qt-Formulare erhalten sinnvoll gruppierte **ein-/ausklappbare Abschnitte**. Für Parameter, States und EditorControls kompakte Zeilenübersichten mit Name, Typ, Index bzw. Validierungszustand und einem einzeln aufklappbaren Zeileneditor. Die bisherigen Add/Remove/Reorder/Filter-Aktionen bleiben funktionsfähig. Collapse/Expand darf den Draft **nicht** verändern, Felder nicht zurücksetzen, nicht committen und nicht von Fokus-/Hilfe-Topics abkoppeln. Bei Fehler öffnet/markiert die Oberfläche den betroffenen Abschnitt. Geringe Breite und 150-%-DPI auf echter Windows-Qt-Plattform prüfen.

**OBS-INSP-002 – veraltete Drafts proaktiv anzeigen:** Bei `NativeProjectSession.revision != draft.base_revision` oder geändertem `project_token` sofort ein **nicht modales Warnband** (Projekt seit Entwurfbeginn geändert), ohne Formulareinträge zu überschreiben, ohne automatisches Rebase und ohne Popup-Schleifen. Apply fail-closed; Benutzer kann bewusst verwerfen und aktuelle Daten neu laden oder im Formular bleiben. Warnung verschwindet nach bewusstem Discard/Refresh. Session-Dirty und Draft-Dirty bleiben getrennt. Fälle: Toolbar-Schnellrename, externe Hostmutation, Save, Undo/Redo, projektbezogene Auswahl und Projektwechsel. Bewusste Fokuserhaltung und kein Dialogverlust.

## 5. Kontexthilfe, Tests und Architektur

- Erweiterung der **bestehenden** quelleneigenen `inspector_topics.de.json`-Registryquelle, etwa `inspector.create`, `inspector.create_type`, `inspector.create_id`, `inspector.delete`, `inspector.delete_references`, `inspector.fold_sections` und `inspector.stale`. Über `NativeHelpBindings` echte F1-/FocusIn-/Pin-/Related-Verbindungen für alle neuen/dynamischen Controls, keine zweite HelpRegistry oder HelpWidget.
- Mit dem AP [ActionInspector](ActionInspector.md), [Gesamtkarte](../00-Gesamtkarte.md), [StudioCoordinator](../02-StudioCoordinator.md), [Daten-/Transaktionsreferenz](../01-Daten-und-Transaktionen.md) und [Verbindungsregister](../04-Verbindungsregister.md) aktualisieren; neue IDs **ab V-63** und nur Code+eigener Integrationstest als IMPLEMENTIERT.
- Tests: vier Creation-Defaults, eindeutige ID/Handler/Parser, Ablehnung referenzierter und letzter Action, gültige unreferenzierte Löschung, Undo/Redo/Save/Reload, Create→Edit→Delete, Draft-Guards/Revision/DiskConflict, Accordion ohne Datenverlust und Fehler-Fokus, proaktive Stale-Warnung, Hilfe-F1/Pin und Windows-Screenshots auf 150-%-DPI. Alles mit temporären Projektdateikopien. Die vorhandenen abgenommenen AP-INSP-001-Tests bleiben gültig.
- Keine Logitech-Service-/ProfileInfo-/LP5-/Geräte-/Keypad-/ICT-/Asset-Datei-Schreibfunktionen. Ein neues AP-INSP-002-Feature gilt erst nach **unabhängiger** Abnahme als freigegeben.

**Nicht Teil von AP-INSP-002:** FolderEntry-Placement löschen/umhängen, Handler erzeugen/löschen, SDK-Typ einer bestehenden Action ändern, Save-As, Build/Deployment, Device HID, ICT-Asset-Writer.

## 6. Tatsächlicher Codevertrag AP-INSP-002

Code: `src/studio/action_inspector/lifecycle.py`, bestehende Formulare in `widget.py`, Host in `native_shell/{coordinator,window,help_bindings}.py`. Keine Änderung an Parser, IDs, Schema oder Session-API. **APPROVED ist keine unabhängige Freigabe.**

| API / Signal | Daten und Schutz |
|---|---|
| `starter_action(sdk_type,id,display_name,handler)` | nur vier ACTION_TYPES; Command minimal, Multistate off/on/toggle, Adjustment `{}`, Editor mit textbox |
| `suggest_id(project,name='neu')` | gültiger kollisionsfreier sichtbarer Vorschlag; kein automatisches Umbenennen beim Commit |
| `propose_create(project,action)` | defensive Kopie; ID-Regel/Kollision/Name, endliches JSON und vollständiger nativer Parser; nur actions[] anhängen |
| `check_delete(project,id) → DeleteCheck` | action_id, display_name, references: Tuple aus `(folder_id,placement_id)`, reason; allowed nur ohne Grund |
| `propose_delete(project,id)` | Existenz, alle Folderreferenzen, Mindestanzahl und Ergebnisparser; nur passende ID entfernen |
| `CreateDraft(project,revision,project_token,sdk_type=...)` | ActionDraft-Feldeditoren wiederverwenden; eigene Validierungsprojektion durch Anhängen einer Kopie; keine vorgetäuschte Session-Action; aktiver Draft immer separat dirty |
| `CreateDraft.change_type(sdk_type)` | gemeinsame Felder erhalten, typgebundene Starter ersetzen; UI bestätigt den Verlust geänderter Spezialwerte |
| `Coordinator.request_create()/createRequested()` | Catalogintent nur mit Session an Shell; Shell löst bestehenden Draftschutz aus |
| `Inspector.start_create(project,revision,token)` | sichtbare editierbare ID/Typ; Name und bestehender Handler; neue Action unplatziert |
| `Inspector.createRequested(str token,str revision,object proposed_action)` | an Shell._apply_create → Coordinator.apply_action_create; genau ein replace, kein Save |
| `Coordinator.apply_action_create(proposed_action,*,base_revision,project_token)` | Projekttoken, Sessionrevision und Sessiondiskbaseline vor Parser/Commit prüfen; bestätigte ID selektieren; Ansichten frisch projizieren |
| `Inspector.deleteRequested()` | Shell.delete_selected verlangt Action-Auswahl; FolderEntry ist ausdrücklich kein Löschziel; Draftschutz vor Prüfung/Bestätigung |
| `Coordinator.action_delete_check(id)` | aktuelle erlaubte Löschbarkeit; UI zeigt Gründe/IDs und deaktiviert Delete |
| `Coordinator.delete_action(id,*,base_revision,project_token)` | Guards, erneute Referenz-/Parserprüfung, genau ein replace; Auswahl/Parameter leeren; keine Handlerbereinigung |
| `Inspector.observe_context(revision,token,conflict=False)` | existierende Hostrevision und Token vergleichen; keine eigene Revisionsquelle; nicht modales Warnband, Apply gesperrt, Eingaben erhalten |
| `Inspector.refreshRequested()` | Shell.refresh_draft: bewusst verwerfen, exakt dieselbe alte ID im selben Projekt neu lesen; fehlende ID erklärt leeren Zustand |

Die Shell reagiert synchron auf `changed`/`selectionChanged`. Ein fenstereigener 350-ms-Timer beobachtet zusätzlich direkte Sessionänderungen und lesend `_check_disk()` derselben Sessionbaseline; er erzeugt keine Revision und keine Dateischreiboperation. Ein Save ohne Revisionswechsel erhält Draft, Accordionzustand und Daten. Bei externem Dateikonflikt erklärt das Band, dass ein bewusstes Projekt-Neuladen erforderlich ist. Stale bleibt bis zur ausdrücklichen Aktualisierung sichtbar. Ein Refresh schreibt nichts.

Nach Apply wechselt Create in Edit mit readonly ID/SDK-Typ. Nach Delete: kein Draft zur gelöschten ID, keine ActionOffer-Kopie; Undo/Redo über dieselbe Session, Save ausschließlich auf deren ursprünglichen temporär geprüften Dateipfad. Die Shell-History verwirft einen zuvor ausdrücklich behandelten Draft vor dem Historyrefresh; ein externer Hosthistorywechsel markiert ihn dagegen stale.

`FoldSection.set_expanded(bool)` verändert nur Sichtbarkeit, Pfeil und Accessibilitybeschreibung. ObjectForm und RowsEditor behalten dieselben Widgetinstanzen beim Falten; kompakte Zeilentitel nennen Name, Typ/State-Index und bei Fehler ein Warnzeichen. Fehler öffnen betroffene Gruppen/Zeilen; Add/Remove/Reorder, optionale Missing/Null/Wert-Modi sowie alle sieben Controls und Dateifilter bleiben erhalten.

Neue geprüfte Hostverbindungen **V-63–V-70**, eindeutige Sender/Payload/Guards und individuelle Testfunktionen im [Verbindungsregister](../04-Verbindungsregister.md). Keine neuen V-IDs für rein lokale Accordionbedienung. Hilfe: zehn additive Topics aus Owner inspector (23 Inspector-/65 Gesamtthemen); Facts leer. [Einzelcoverage und Arbeitsakte](../../../../work/action-inspector/AP-INSP-002/README.md).

Prüfungen: `tests/test_action_lifecycle_{mutations,widget,integration}.py`, `tests/test_action_inspector_ux.py`, Gesamtsuite und `tools/run_action_lifecycle_lab.py --smoke/--evidence`. Der Labmodus akzeptiert für visuelle Nachweise ausschließlich echte Windows-Qt bei DPR 1,5 und temporäre Projektkopien. Kein Hardware-/Service-/Profilnachweis wird daraus abgeleitet.

## Unabhängiger Abnahmeentscheid (06.11.2026)

**APPROVED** für native Create/Delete-Operationen und Inspector-UX. [Unabhängiger Reviewbericht](../../../../work/acceptance/20261106-action-lifecycle/ABNAHME.md). Keine Freigabe für referenzierte oder letzte Action-Löschung, Folder-/Placement-Writer oder Gerät-/ICT-Assets.
