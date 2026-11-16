# KeypadPreviewWidget – Schnittstelle

**Status:** isoliert APPROVED (AP-WIDGET-002), **native Produktintegration AUFGESCHOBEN** bis ein belegter Frame-/Capability-Adapter und ein Placement-Commit-Vertrag vorhanden sind.  
**Code:** `src/studio/keypad_preview/widget.py`; `src/studio/keypad_contract.py`. Abnahme: `work/acceptance/20261104-keypad-catalog/ABNAHME.md`.

## Eingabe-Datentypen

- `KeypadFrame`: `context_id`, `view_id`, `revision`, `NavigationCapability`, `slots`, `page_index/page_count`; **transiente Darstellungsprojektion**, keine Profilpersistenz.
- `SlotData`: physischer Index, Rolle, optional placement-/action-ID, nur extern ermittelte logische Position, Tilebild, Label.
- `SlotAddress`: Ansicht/Seite/physischer Slot/optionale Placement-ID.
- `EditRequest`: `request_id`, `base_revision`, Operation (`move/copy/place/remove`), source/target, action/Parameter.
- `NavigationCapability` muss tatsächlich vom SDK-/Geräteadapter stammen. Die UI darf nicht neun Slots oder Seiten aus Annahmen erfinden.

## Öffentliche Methoden

`set_frame(KeypadFrame)`, `set_mode("preview"|"edit")`, `set_edit_allowed(bool)`, `set_selection(SlotAddress|None)`, `set_skin`, `set_motion_enabled(bool)`, `set_history_available(can_undo,can_redo)`. Lesende Abfragen `frame()`, `selection()`, `view_state()`.

## Qt-Ausgänge

| Signal | Payload | Hostaufgabe |
|---|---|---|
| `slotSelected(object)` | `SlotAddress` | globale Auswahl |
| `pageRequested(int)` | 0-basierte Seite | belegten neuen Frame liefern |
| `pageCreateRequested()` | – | Geräte- und Projektcapability prüfen |
| `symbolEditRequested(object)` | `SlotAddress` | gesicherten ICT-Writer voraussetzen |
| `editRequested(object)` | `EditRequest` | Kontext, Revision, Quelle/Ziel, Permissions, Placement prüfen; dann ggf. `Session.replace` |
| `undoRequested()` / `redoRequested()` | – | Host delegiert Session-History |

**Risiko:** `KeypadFrame.revision` ist nicht implizit die Sessionrevision. `NativeIctCoordinator` kann aktuell separat Projekt-/Assetdateien schreiben. Bis zur expliziten Koordination sind alle nativen Edit-/Symbolpfade zu deaktivieren.

## Host-Verdrahtung

**AUFGESCHOBEN:** V-18 bis V-21. In AP-STUDIO-002 darf das Widget nur mit tatsächlich nachgewiesenem Frame benutzt werden; andernfalls klar erkennbarer „noch nicht verfügbar“-Zustand statt einer scheinbar funktionsfähigen Fake-Belegung. Keine neue `ProfileInfo.json`-Schreib-API.

[Gesamtkarte](../00-Gesamtkarte.md) · [Transaktionsregeln](../01-Daten-und-Transaktionen.md)

## Tatsächlicher Shellzustand AP-STUDIO-002

`src/studio/native_shell/window.py`: V-27 zeigt einen ausdrücklich deaktivierten Hinweis „Native Keypad-Vorschau nicht verfügbar“, da kein belegter KeypadFrame und keine NavigationCapability vorliegen. Es wird **kein KeypadPreviewWidget instanziiert** und kein Frame erfunden. Test `tests/test_native_studio_shell.py::test_v27_capabilities_unavailable_no_writes` prüft fehlende Instanz, gesperrte ICT-Aktion und byteidentische Projektkopie.

V-18 bis V-21 bleiben AUFGESCHOBEN. Kein `set_frame`, kein Placementcommit, kein SymbolDesigner und keine Historykopplung zur Preview in diesem AP. Die oben beschriebenen Setter/Signale sind der vorhandene eigenständige Widgetvertrag und keine Behauptung einer aktiven Shellroute. Ohne Frame ist der vorhandene Widgetzustand `frame() is None`; in der Shell wird bereits vor dessen Konstruktion die Capability-Grenze sichtbar gemacht. Revisionen eines zukünftigen KeypadFrame brauchen eine explizite Hostkorrelation. Kein Profil-/LP5-/Assetwriter.

AP-HELP-001 erfasst Keypad/ICT ausdrücklich als **NICHT_AKTIV**. Die vorbereiteten Defaultthemen keypad.* und symbol.ict bleiben bytegleich unter Quelle prepared; Related-Navigation zeigt zusätzlich den fehlenden Capability-/Writervertrag. Die sichtbaren Shellsperren besitzen native_shell.keypad_unavailable bzw. native_shell.ict_unavailable. Qt-Test `tests/test_native_help_coverage.py::test_disabled_capabilities` prüft fehlende Previewinstanz, dauerhafte Sperren und byteidentisches Projekt. [Coverage-Akte, unabhängig APPROVED](../../../../work/help-integration/AP-HELP-001/README.md).
