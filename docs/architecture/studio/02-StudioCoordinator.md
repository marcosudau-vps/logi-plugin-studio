# StudioCoordinator – implementierter nativer Host

**Erweiterung AP-INSP-002: IMPLEMENTIERT / APPROVED.** Aktuelle Create-/Delete-APIs und Draftbeobachtung stehen im Schlussabschnitt; frühere Aussagen zum fehlenden Createvertrag gelten nur für die abgenommene v1-Baseline.


Stand: 06.11.2026 · AP-STUDIO-002 · unabhängig APPROVED am 06.11.2026, [Abnahme dokumentiert](../../../work/acceptance/20261106-studio-coordinator/ABNAHME.md).

Code: `src/studio/native_shell/coordinator.py`, Oberfläche `src/studio/native_shell/window.py`, Paket `__init__.py`. Start: `python tools/run_studio.py --native <logitech-native-1.json>`. Ohne Flag bleibt `StudioWindow` der Legacy-Editor. `python tools/run_native_studio_lab.py` öffnet ausschließlich eine temporäre Beispielkopie.

## Öffentliche Hostoperationen

| API | Wirkung / Fehlergrenze |
|---|---|
| `open_project(path,discard=False)` | load vor Austausch; direkte Dirty-Session ohne Freigabe verweigern |
| `refresh()` | Sessionprojektion an bestehende Widgets; stille Auswahl spiegeln |
| `select_node(kind,id)`, `select_offer(ActionOffer)` | nur aktuelle native IDs und konkrete Parameter; kein Commit |
| `selected_action()` | aktuelle Actiondefinition, ggf. über FolderEntry-Referenz |
| `request_edit(id)` | geprüfte Inspector-Navigation über `editRequested(str)` |
| `rename_action(id,name,base_revision=...)` | nur NativeAction.display_name über snapshot/replace; Fehler als NativeSessionError |
| `undo()`, `redo()`, `save()` | einzige Sessionhistory und konfliktgeschützter Save |
| `publish_diagnostics(source,items,project_token=...,base_revision=...)` | zwei Korrelationswerte prüfen; False bei stale Antwort |
| `report_error(source,error)` | transparente Diagnostic-Hülle mit Pfad `/` |
| `related_help(topic)` | nur existierendes Registrythema explizit anfordern |

`changed()` aktualisiert Status/History; `selectionChanged()` aktualisiert Details und Hilfe. Sessionrevision und Projekttoken gehören nur dem Host; Widgets erzeugen sie nicht. Die beiden nativen Views erhalten keine Sessionreferenz.

## Komposition und Grenzen

Explorer und Katalog stehen nebeneinander, Details/Probleme/Hilfe/gesperrte Vorschau in Tabs. Der Katalog wird wiederverwendet; eine Host-EnabledChange-Sperre verhindert auch nach internen Filter-/Sortierupdates eine unimplementierte Erstellung. Anzeigenamenbearbeitung ist ein klar beschrifteter Dialog. Inspector ergänzt AP-INSP-001, kein EventBus, kein konkurrierender JSON-Dateiwriter. Die echte Preview wird mangels Frame/Capability nicht instanziiert. ICT ist sichtbar gesperrt.

F1 gilt im Fenster, setzt explizite Hilfe trotz Pin und öffnet den Hilfetab. Fokuswechsel und Auswahl liefern normale Kontexte, Pin bleibt dabei wirksam. Related-Topics validiert der Host. Projektwechsel entfernt auch alten Pin und Fakten. Diagnosen können ohne geprüfte IDabbildung nur zur Diagnosehilfe führen.

## Prüfung

Phasen A/B/C besitzen eingefrorene Quellstände und eigene Logs in der [Arbeitsakte](../../../work/studio-integration/AP-STUDIO-002/README.md). `tests/test_studio_coordinator.py` und `tests/test_native_studio_shell.py` prüfen echte PySide6-Widgets und Qt-Interaktionen. Die [V-ID-Matrix](04-Verbindungsregister.md) ordnet jede implementierte Kante einer eigenen Testfunktion zu. Visuelle Nachweise verwenden Windows-Qt mit OS-DPR 1,5; Offscreen-Nachweise sind ausschließlich automatisierte Funktionstests.

## AP-INSP-001 – implementiert, APPROVED

Der [ActionInspector](widgets/ActionInspector.md) bearbeitet alle vier vorhandenen SDK-Aktionstypen einschließlich strukturierter Parameter, States, Adjustment, EditorControls/Filter und Asset-Referenzen. NativeAction ist weiter nur Leseprojektion. Ein defensiver Qt-freier ActionDraft hält Rohdaten und opake Baserevision; nur bewusst geänderte Felder werden gepatcht. ID und Typ bleiben fest, neue Actions und Folderänderungen bleiben ausgeschlossen.

Auswahl aus Explorer/Katalog beziehungsweise FolderEntry→Action wird vom Host in den permanenten Inspector-Tab projiziert. Katalog-Bearbeiten öffnet diesen Tab; Toolbar-Anzeigename bleibt QInputDialog. Apply führt über `StudioCoordinator.apply_action_edit` zu genau einem `NativeProjectSession.replace`, ohne Autosave. Undo/Redo/Save bleiben dieselbe Sessionhistory. Dirty-Drafts werden unabhängig von Session-Dirty geschützt; Cancel, stale Revision, DiskConflict und fehlgeschlagene Projektwechsel erhalten Eingaben. Alle Ansichten werden nach erfolgreichem Commit frisch projiziert; Dirty-Refresh überschreibt keine Felder.

Die eine bestehende Hilfe erhält Quelle inspector mit 13 Topics (55 insgesamt). Lokale `inspectorTopic`-Eigenschaften gelten auch für dynamische Zeilen/Filter; Host-F1/FocusIn/Pin/Related zeigen keine Rohdaten. [Register V-53–V-62](04-Verbindungsregister.md), [Arbeitsakte, Tests und Windows-Bilder](../../../work/action-inspector/AP-INSP-001/README.md). Unabhängige Abnahme am 06.11.2026 erfolgt; AP-INSP-002 bleibt Folgeplanung.

## Zusätzliche Host-APIs AP-INSP-002 – APPROVED

`request_create()/createRequested()` verbinden den existierenden Katalogintent mit dem Draftguard der Shell. `apply_action_create(proposed_action,*,base_revision,project_token)` prüft Korrelation/Diskbaseline und ruft nach defensiver Parserprojektion genau einmal replace. `action_delete_check(action_id)` liefert DeleteCheck mit Folder-/Placement-Referenzen und Grund. `delete_action(action_id,*,base_revision,project_token)` prüft dies erneut und committet nur erlaubte unreferenzierte Actions; danach Auswahl/Parameter leer. Weder neue Handler noch Folderänderungen.

Die Catalog-EnabledChange-Sperre gilt jetzt nur ohne Session. Shellslots `create_action`, `_apply_create`, `delete_selected`, `refresh_draft` integrieren bestehende Übernehmen/Verwerfen/Abbrechen-Guards. `changed/selectionChanged → _observe_inspector_context → observe_context` zeigt Stale proaktiv. Ein 350-ms-Timer ergänzt nur die Beobachtung direkter Sessioncommits/externer Byteänderungen; keine zweite Revisionsquelle. Create-/Edit-Drafts bewahren ihre Basis bis bewusstem Apply/Discard/Refresh. Historische Aussagen zum fehlenden Erstellungsvertrag weiter oben beschreiben die v1-Baseline.

[Tatsächliche Signale, Payloads, Guards](widgets/ActionLifecycle.md), [V-63–V-70 samt eigenen Tests](04-Verbindungsregister.md), [Windows-Evidenz](../../../work/action-inspector/AP-INSP-002/README.md). Legacy und Hilfe-Kern bleiben unverändert.


## AP-FOLDER-002: integrierter Composer

Zusätzliche APIs: `prepare_project(path)` liefert ein vollständig geladenes `(session, extension_store)`-Paar; `activate_project(prepared)` aktiviert ausschließlich bereits vorbereitete Kandidaten. `open_project` schützt bei direktem Aufruf nun auch Dirty-Extensions. Die Shell übernimmt die tatsächlichen Save/Discard/Cancel-Dialoge und hält alte Entwürfe bis zur erfolgreichen Aktivierung.

`extension_store` ist die einzige Extension-Instanz pro Studio-Sitzung; der wiederverwendete Composer erhält denselben Store sowie defensive native Snapshots. Bei Projektwechsel werden Composer, Provider, Navigation und Extensionhistory ausgetauscht; der alte Composer beendet Timer/Subscriptions. `action_delete_check` ergänzt den unveränderten Lifecycle-DeleteCheck um virtuelle Folder-/Placement-Referenzen; `delete_action` prüft diesen erneut unmittelbar vor dem nativen Commit. `_guard_history` schützt native Undo-/Redo-Schritte ohne Mutation der bestehenden Stackzuständigkeit.

Shell-API `save_folders()` speichert explizit die Extension, `save_project()` weiterhin nur das native Projekt. Aktiver Ordnertab bestimmt die Toolbar-Undo-/Redo-History, beide Aktionen sind entsprechend beschriftet. `folders.studio` gehört als neues Topic zur bestehenden Registryquelle `folders`; Fokus/F1, Dialoge und Help-Tab verwenden das vorhandene HelpCoordinator-System. Fehler gehen zusätzlich an ProblemsPanel; dauerhafte Orphan-Diagnosen haben die Quelle `folders.references`.

[Eigene Hosttests und Register V-74–V-82](04-Verbindungsregister.md), [Prüfakte](../../../work/studio-integration/AP-FOLDER-002/README.md).
