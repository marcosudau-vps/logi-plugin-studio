# NativeProjectExplorerWidget – Schnittstelle

**Status:** als eigenständiges Widget APPROVED (AP-WIDGET-006); **native Hostintegration IMPLEMENTIERT, unabhängig APPROVED am 06.11.2026**.  
**Code:** `src/studio/native_project_explorer/widget.py`. Nachweis: `work/acceptance/20261105-native-session-explorer/ABNAHME.md`.

## Zweck

Read-only Ansicht eines `NativeProject` mit den Knotentypen `plugin`, `action`, `handler`, `folder` und `folder_entry`. Die ID eines FolderEntry bezeichnet die **Platzierung**, nicht eine neue Action-Definition. Keine Logos/ProfileInfo-Profile und keine direkte Projektmutation.

## Öffentliche Methoden (Host → Widget)

| API | Eingabe | Seiteneffekt |
|---|---|---|
| `set_project(project, *, revision=None)` | `NativeProject \| None`; opakes Revisionslabel | Baum neu erzeugen, existierende Selektion nach Möglichkeit halten; keine Benutzersignale |
| `set_selection(node_kind, native_id)` | zwei Strings | nur vorhandenen sichtbaren Knoten programmatisch selektieren, `bool` zurückgeben, **kein** Benutzerintent |
| `set_filter(text)` | `str` | nicht-persistenter Filter, Case-insensitive |
| `clear()` | – | Daten/Selektion/Filter leeren |

## Qt-Signale (Widget → Host)

- `nodeSelected(str,str)`: tatsächliche Benutzerauswahl (`kind`, `native_id`).
- `nodeActivated(str,str)`: Enter/Doppelklick als expliziter Navigationsintent, kein Ausführen der SDK-Action.

Gruppenknoten emittieren keine Phantom-ID. Ein Projektwechsel entfernt nicht mehr vorhandene Entitäten. Revisionen werden nicht im Widget erzeugt oder persistiert.

## Host-Verdrahtung

**IMPLEMENTIERT:** zentrale Sessionprojektion und hostgeführte Auswahl. Signalrouten V-01, V-03, V-04. Keine direkten Explorer→ActionCatalog-Methodenaufrufe, keine direkte Session-Referenz.

**Abnahmeforderung:** echte Qt-UI-Selektion, ID-Erhalt bei Snapshotwechsel, stilles `set_selection` und sichere Projektwechsel sind im Shell-Integrationstest nachzuweisen.

[Gesamtkarte](../00-Gesamtkarte.md) · [Verbindungsregister](../04-Verbindungsregister.md)

## Implementierter Hostvertrag AP-STUDIO-002

`src/studio/native_shell/coordinator.py`: V-01 `refresh → set_project`, V-03 `nodeSelected → select_node`, V-04 `nodeActivated → activate_node`, V-23 Filter → `_filtered`, V-40 `_mirror → set_selection`. Die exakten eigenen Testfunktionen stehen im [Register](../04-Verbindungsregister.md).

Native IDs und opake Revision stammen ausschließlich aus der Session. Hostselektion ist flüchtig; FolderEntry bleibt Placement-ID. Der Host macht das Gegenstück bei expliziter Auswahl sichtbar und leert unsichtbare Auswahl nach Filteränderungen. `set_project` und `set_selection` schreiben keine Projektdatei und emittieren keine Benutzerintents. Unbekannte/veraltete IDs werden nicht übernommen. Leerzustand: kein Projekt oder kein Filtertreffer; Gruppen sind keine Entities. Ein Projektwechsel leert Auswahl und Filter vor Neubestückung. Echte Mausauswahl, Enter, stiller Spiegelweg und gleiche Anzeigenamen sind im neuen Shelltest geprüft.

V-42: `tree.itemSelectionChanged → Coordinator._explorer_selection` leert bei echter Gruppenauswahl die bisherige Hostauswahl. Eigener Integrationstest `tests/test_studio_coordinator.py::test_v42_explorer_group_clears_host_selection`. Programmatische Gruppen-/Baumänderungen bleiben still.

AP-HELP-001 (**APPROVED**) ergänzt ausschließlich im Host die Kontexte `explorer`, `explorer.search`, `explorer.plugin`, `explorer.handler`, `explorer.folder`, `explorer.folder_entry` und das bestehende `action.definition`. Suche/Rücksetzen und Fokus/Selektion verwenden aktuelle IDs; FolderEntry-Facts trennen Placement- und Action-ID. Keine Änderung dieses Widgets. Einzelnachweise: `tests/test_native_help_coverage.py::test_explorer_entities`, `test_explorer_groups_and_loss`, `test_explorer_search`, `test_explorer_reset`; [Coverage-Akte](../../../../work/help-integration/AP-HELP-001/README.md).

## AP-INSP-001 – APPROVED

Hostauswahl füllt den Inspector mit der exakt ausgewählten Action. FolderEntry wird über seine echte Actionreferenz aufgelöst; Placement und Folder bleiben unverändert (V-53). Dirty-Auswahlwechsel erhält Übernehmen/Verwerfen/Abbrechen (V-56).

Nachweis: `tests/test_action_inspector_integration.py`; [Inspector-Vertrag](ActionInspector.md), [Arbeitsakte](../../../../work/action-inspector/AP-INSP-001/README.md). Unabhängige Abnahme am 06.11.2026 erfolgt.
