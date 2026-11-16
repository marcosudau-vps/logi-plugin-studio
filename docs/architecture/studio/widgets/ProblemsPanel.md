# ProblemsPanelWidget – Schnittstelle

**Status:** als einzelnes PySide6-Widget APPROVED (AP-WIDGET-004), **native Hostintegration IMPLEMENTIERT, unabhängig APPROVED am 06.11.2026**.  
**Code:** `src/studio/problems_panel/{model,widget}.py`; fachlicher Fehlerdatentyp `core.errors.Diagnostic`. Abnahme: `work/acceptance/20261105-problems-panel/ABNAHME.md`.

## Fachlicher Auftrag

Zeigt mehrere Diagnosequellen **ohne selbst zu validieren**. Suche, Severity-Filter und Navigation sind Anzeigefunktionen; eine Diagnostic ist keine Action-Definition und kein direkter JSON-Pointer.

## Öffentliche Host-Eingaben

- `set_diagnostics(Sequence[Diagnostic])`: ersetzt Standardquelle `project`.
- `set_source_diagnostics(source, diagnostics, *, revision=None)`: eine benannte Quelle ersetzen; Revision als opakes Korrelationslabel.
- `remove_source(source)`, `clear()`: Quellverwaltung bei Projektwechsel.
- `set_filter(text)`, `set_severity_filter(severity)`, `reset_filters()`: nur Anzeige.
- Lesende Queries `sources()`, `source_revision(source)`, `diagnostics(source)`, `visible_entries()`, `counts()`.

## Qt-Ausgänge

`diagnosticSelected(object)`: Original-`Diagnostic` oder `None` nach realer Benutzerselektion.  
`diagnosticActivated(object)`: Original-`Diagnostic` bei ausdrücklichem Navigationsintent.

## Verbindungsgrenze

**IMPLEMENTIERT:** V-12 bis V-14. Der Host liefert geprüfte Quellen/Revisionen, entfernt stale Ergebnisse bei Projektwechsel und darf nur bei verifizierter ID-/Pfadabbildung zu nativen Projektknoten navigieren. Keine erfundenen Feld-zu-Action-Zuordnungen. Das Panel führt niemals automatische Korrekturen aus.

[Gesamtkarte](../00-Gesamtkarte.md) · [Verbindungsregister](../04-Verbindungsregister.md)

## Implementierter Hostvertrag AP-STUDIO-002

`src/studio/native_shell/coordinator.py`: V-12 `publish_diagnostics → set_source_diagnostics`; V-13 `diagnosticSelected → diagnostic_selected`; V-14 `diagnosticActivated → diagnostic_activated`; V-39 Projektwechsel → `clear/reset_filters`. Eigene neue Integrationstests je Kante im [Register](../04-Verbindungsregister.md).

Quellen `native.validation`, `open`, `edit`, `save` bleiben getrennt. Normative native Validierung läuft bereits in load/replace. Gültige Session verteilt einen leeren native.validation-Snapshot; Fehler sind unveränderte Texte als echte `core.errors.Diagnostic`, Code `NATIVE_<QUELLE>`, Pfad `/`. Keine erfundene präzise Parserstelle. Zusätzliche Quellen können nur mit aktuellem Projekttoken UND aktueller opaker Revision publizieren. Stale Antworten verändern nichts.

AP-HELP-001 (**APPROVED**) ergänzt im Host die Kontexte für Suche, alle vier Severity-Buttons, Meldung, Detailfeld, Leerzustand, Rücksetzen, Sortierkopf und Kontextmenü. Quelle problems registriert Defaultthemen plus problems.empty und problems.sort. F1 im Detailfeld bewahrt die konkrete Diagnosehilfe auch nach dem Tabwechsel. Hilfefakten kopieren keine Pfade, Meldungstexte oder Quellnamen; sie enthalten geprüften Code, Filter und Zähler. Das Panel selbst bleibt unverändert. Tests `tests/test_native_help_coverage.py::test_problems_search`, `test_problems_severity`, `test_problems_diagnostic`, `test_problems_details`, `test_problems_empty`, `test_problems_reset`, `test_problems_header`, `test_problems_menu`; [Windows-Evidenz und Audit](../../../../work/help-integration/AP-HELP-001/README.md).

Auswahl-/Aktivierungsintents akzeptiert der Host nur für dieselbe noch aktive Diagnostic-Instanz. Die Aktivierung öffnet Diagnosehilfe mit dem Hinweis auf fehlende geprüfte Entity-Zuordnung; kein JSON-Index wird als ID interpretiert. Projektwechsel löscht alte Quellen, Auswahl, Suche und Severity-Filter. Commit/Undo/Redo entfernen veraltete Meldungen. Leere Prüfung bleibt von fehlenden Quellen und ausgefilterten Treffern unterscheidbar. Erlaubte Widgeteffekte: Anzeige, Filtern, explizite Zwischenablagekopie; kein Validator und kein Dateiwriter.
