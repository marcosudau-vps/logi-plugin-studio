# Weitere Editoren und ihre Integrationsgrenzen

**Status:** ActionInspector/Lifecycle implementiert (AP-INSP-002 APPROVED); weitere Editoren geplant. Die Planungsabschnitte zu AP-INSP-002 dokumentieren die Vorgeschichte; der aktuelle Stand folgt am Ende.

| Komponente | Zweck | Noch zu klären |
|---|---|---|
| ActionInspector | IMPLEMENTIERT in AP-INSP-001: vorhandene SDK-Actions bearbeiten | unabhängige Abnahme am 06.11.2026 erfolgt |
| FolderEditor | NativeFolder/NativeFolderEntry bearbeiten | Positionen, Gerätetypen, Navigation, Varianten und zulässige Reorder-Operationen |
| ProfileExplorer (optional) | Logitech-Service-Profile lesen | drei empirische Layoutfamilien, Pseudonymisierung, Versionsgrenzen |
| ProfileEditor (nicht freigegeben) | Logitech-Service-Profile schreiben | keine verifizierte stabile Schreib-API, kein getesteter Import-/Roundtrip |

Beim Beginn eines solchen Folge-APs eine eigene `widgets/<Name>.md` erstellen, die [Gesamtkarte](00-Gesamtkarte.md) aktualisieren und tatsächliche Verbindungen im [Register](04-Verbindungsregister.md) protokollieren. Historische `ProfileInfo.json`-Forschung ist **kein** automatischer Produkt-Schreibvertrag.


## Konkretisierte ActionInspector-Reihenfolge (06.11.2026)

**AP-INSP-001 – IMPLEMENTIERT / APPROVED:** [vollständiger Auftrag](../../../work/planning/AP-INSP-001-native-action-inspector-v01.md) und [verbindliche Widget-Spezifikation](widgets/ActionInspector.md). Der Inspector editiert **vorhandene** NativeActions der vier installierten SDK-nativen Typen, inklusive Type-Spezialfelder/Collections, über einen flüchtigen Entwurf mit validiertem Session-Apply, Undo/Redo/Save und integrierter Kontexthilfe. Die Action-ID und der SDK-Typ bleiben unveränderlich. Die bisherige Katalogaktion „Bearbeiten“ öffnet danach die Inspectoransicht; die separate Toolbar-Schnellumbenennung bleibt kompatibel.

**AP-INSP-002 – fachlich danach:** Neue native Aktionen erstellen und vorhandene sicher löschen; Einzigartigkeit von IDs, Vorgaben je SDK-Typ, Handlerreferenzen, nicht löschbare referenzierte Actions, verbleibende Actionanzahl und anschließend FolderEditor/Placement-Integration abnehmen. Keine Umsetzung von AP-INSP-002 in AP-INSP-001 oder automatische Aktivierung des bisher gesperrten „+ Neue Aktion“-Buttons.

## AP-INSP-001 – implementiert, APPROVED

Der [ActionInspector](widgets/ActionInspector.md) bearbeitet alle vier vorhandenen SDK-Aktionstypen einschließlich strukturierter Parameter, States, Adjustment, EditorControls/Filter und Asset-Referenzen. NativeAction ist weiter nur Leseprojektion. Ein defensiver Qt-freier ActionDraft hält Rohdaten und opake Baserevision; nur bewusst geänderte Felder werden gepatcht. ID und Typ bleiben fest, neue Actions und Folderänderungen bleiben ausgeschlossen.

Auswahl aus Explorer/Katalog beziehungsweise FolderEntry→Action wird vom Host in den permanenten Inspector-Tab projiziert. Katalog-Bearbeiten öffnet diesen Tab; Toolbar-Anzeigename bleibt QInputDialog. Apply führt über `StudioCoordinator.apply_action_edit` zu genau einem `NativeProjectSession.replace`, ohne Autosave. Undo/Redo/Save bleiben dieselbe Sessionhistory. Dirty-Drafts werden unabhängig von Session-Dirty geschützt; Cancel, stale Revision, DiskConflict und fehlgeschlagene Projektwechsel erhalten Eingaben. Alle Ansichten werden nach erfolgreichem Commit frisch projiziert; Dirty-Refresh überschreibt keine Felder.

Die eine bestehende Hilfe erhält Quelle inspector mit 13 Topics (55 insgesamt). Lokale `inspectorTopic`-Eigenschaften gelten auch für dynamische Zeilen/Filter; Host-F1/FocusIn/Pin/Related zeigen keine Rohdaten. [Register V-53–V-62](04-Verbindungsregister.md), [Arbeitsakte, Tests und Windows-Bilder](../../../work/action-inspector/AP-INSP-001/README.md). Unabhängige Abnahme am 06.11.2026 erfolgt; AP-INSP-002 bleibt Folgeplanung.


## Ergänzung AP-INSP-002 umgesetzt – APPROVED

Die früher in diesem Dokument geplante ActionLifecycle-Erweiterung ist implementiert: vier SDK-Typen neu erstellen, unreferenzierte Action ausdrücklich bestätigt löschen, Referenzen/letzte Action fail-closed schützen. OBS-INSP-001 und OBS-INSP-002 sind durch FoldSection und proaktives Stale-Band umgesetzt. [Ist-Vertrag](widgets/ActionLifecycle.md), [Arbeitsakte](../../../work/action-inspector/AP-INSP-002/README.md). Unabhängige Abnahme folgt separat. FolderEditor, Handlereditor, Profilwriter und Geräte-/ICT-Integration bleiben außerhalb dieses Pakets; kein automatischer Folgeauftrag.
