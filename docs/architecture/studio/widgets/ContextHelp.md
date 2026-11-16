# ContextHelpWidget, HelpCoordinator und HelpRegistry

**Status:** isoliert APPROVED (AP-WIDGET-005); **native Hostintegration IMPLEMENTIERT, unabhängig APPROVED am 06.11.2026**.  
**Code:** `src/studio/context_help/{entries,registry,coordinator,widget}.py`. Abnahme: `work/acceptance/20261105-context-help/ABNAHME.md`.

## Eigentümer und Datenmodell

| Bestandteil | API / Verantwortung |
|---|---|
| `HelpEntry` | unveränderliche Topicdefinition: `topic_id`, `title`, `summary`, Details, Related-Topics |
| `HelpRegistry` | `register(entry,source=...)`, `register_many(entries,source=...)`, `unregister_source(source)`, `get(topic_id)`, `resolve(topic_id)`. Eindeutige Topic-IDs, quelleneigene Einträge, hierarchischer Fallback |
| `HelpContext` | flüchtige `topic_id` mit optionalen Anzeigefakten; keine SDK-Datenpersistenz |
| `HelpCoordinator` | `set_context(context|None)`, `request_help(context)`, `set_pinned(bool)`, `current()`, `refresh()` |
| `HelpDisplayState` | gerenderter Inhalt plus `pinned` und tatsächliche Topicauflösung |
| `ContextHelpWidget` | `set_help(HelpDisplayState)`; passive Oberfläche |

## Signale und Verdrahtung

- `HelpCoordinator.helpChanged(object)` → `ContextHelpWidget.set_help(state)`.
- `ContextHelpWidget.pinRequested(bool)` → `HelpCoordinator.set_pinned`.
- `ContextHelpWidget.relatedTopicRequested(str)` → Host validiert Topic → `HelpCoordinator.request_help(HelpContext)`.
- Hostauswahl/Fokus/F1 → `HelpContext` → `HelpCoordinator.set_context` bzw. explizit `request_help`.

**IMPLEMENTIERT:** V-08 bis V-11. Programmeigene Auswahlsetter dürfen keinen neuen User-Intent simulieren. Gepinnte Hilfe wechselt nicht bei normalen Fokusänderungen, explizite Hilfeforderung darf wechseln. Keine direkten Aufrufe einzelner Widgetklassen in der HelpRegistry und keine Abhängigkeit von SDK-/Profilinstanz-Interna.

[Gesamtkarte](../00-Gesamtkarte.md)

## Implementierter Hostvertrag AP-STUDIO-002

`src/studio/native_shell/coordinator.py` und `window.py`: V-08 Auswahl → `set_context`; V-09 `helpChanged → set_help`; V-10 Pin → `set_pinned`; V-11 Related → geprüfte `request_help`; V-28 FocusIn → Kontext; V-29 F1 → explizite Hilfe und Hilfetab; V-30 Projektwechsel → Unpin und leerer Kontext. Jeweils eigener Hostintegrationstest im [Register](../04-Verbindungsregister.md).

Die ursprüngliche Sammelregistrierung als Quelle studio wurde durch AP-HELP-001 abgelöst: `native_shell/help_bindings.py::register_topics` verteilt die 16 unveränderten Defaultthemen an ihre Eigentümer und ergänzt 26 Themen aus vier expliziten JSON-Dateien. Quellen: explorer, catalog (einschließlich action.definition), problems, native_shell (einschließlich studio.help und help.*), prepared (inaktive keypad.* und symbol.ict). Jedes Topic wird genau einmal über `register_many` registriert. Themen sind Dokumentation, keine SDK-Daten. Auswahlfakten führen native ID und ggf. exakten Parameternamen, ohne Themen zu mutieren. F1 berücksichtigt aktuellen Fokus/Selektion auch bei Pin. Normale Auswahl/Fokuswechsel respektieren Pin; Related-Topics müssen in der Registry existieren. Projektwechsel entfernt Pin und alte Fakten, auch bei identischen Plugin-/Action-IDs.

`set_help(HelpDisplayState|None)` ist still, zeigt unbekannte Themen neutral und verarbeitet Texte als Plaintext. Registryfehler sind explizite ValueError/TypeError; keine automatische Netzabfrage. Keine Projekt-/Datei-/Servicewrites. Bestehende allgemeine Hilfethemen beschreiben mögliche Bausteinfunktionen; Vorschau und ICT sind in dieser Shell sichtbar gesperrt und bleiben eigene Folgeaufträge.

## Kontextabdeckung AP-HELP-001 – APPROVED

`NativeHelpBindings.CONTROL_BINDINGS` und `TOOLBAR_BINDINGS` binden konkrete Qt-Objekte; der Eventfilter bleibt auf dem eigenen Fenster und seinen besitzenden Kinddialogen. Kein globaler QApplication-Fokusmonitor. FocusIn und aktuelle Auswahl liefern `set_context`; Such-/Filter-/Sortierereignisse aktualisieren begrenzte Facts. F1 fordert explizit das tatsächlich fokussierte Control an und öffnet die eine Hilfeansicht. Der Host veröffentlicht den Kontext nach dem synchronen Fokuswechsel des Tabs, damit eine dabei fokussierte Toolbar die F1-Anfrage nicht überschreibt.

Fokus auf Pin, Details, Scrollbereich und Related-Buttons erhält den aktuellen Artikel. F1 erklärt das jeweilige Control; Pin/Related bleiben explizite Benutzerintents. Später erzeugte Related-Buttons und eigene Qt-Dialoge werden über ChildAdded/ChildPolished erfasst. Dialogbesitz wird entlang der parentWidget-Kette geprüft, da isAncestorOf an Fenstergrenzen endet. Der Öffnendialog verwendet die Qt-Variante, sodass sein Fokus lokal zuordenbar bleibt. Eingabetext und Dateipfad werden nie als Hilfefakten übernommen.

Fakten beschränken sich auf aktuelle native Identitäten/Parameter, Zähler, geprüften SDK-Typ, Reihenfolge und Verfügbarkeit. Diagnosepfade/-meldungen sowie Suchtexte werden nicht in Hilfe-Facts kopiert; Diagnosecodes werden vor Anzeige geprüft. Unbekannte oder syntaktisch ungültige Related-IDs werden verworfen. Registry-Fallback bleibt der unveränderte Vertrag des abgenommenen Kerns. Vorbereitete Keypad-/ICT-Themen erhalten bei Related-Navigation einen ausdrücklichen NICHT-AKTIV-Hinweis.

Die [Arbeitsakte](../../../../work/help-integration/AP-HELP-001/README.md) enthält den Vorher-Audit, das maschinenlesbare Einzelregister, Testlogs, Scope-Diff und echte Windows-Qt-Aufnahmen. `tests/test_native_help_coverage.py` prüft Controls, Dialoge, Projektwechsel, Pin/F1, Fallback, fremde Fenster und ausbleibende Sessionoperationen. Neue Kanten V-43–V-52 im [Verbindungsregister](../04-Verbindungsregister.md). Die bisherigen unabhängigen Freigaben bleiben die Baseline; dieses AP ist [unabhängig abgenommen](../../../../work/acceptance/20261106-help-coverage/ABNAHME.md).

## AP-INSP-001 – APPROVED

Quelle inspector ergänzt 13 deutsche Topics; Registry insgesamt 55. NativeHelpBindings liest inspectorTopic ausschließlich bei fenstereigenen Controls, auch dynamischen Zeilen und Filtern. Facts bleiben leer; F1/Pin/Related laufen durch dieselbe Hilfeinstanz (V-60/V-61). Hilfe-Kern und bestehende Topics sind unverändert.

Nachweis: `tests/test_action_inspector_integration.py`; [Inspector-Vertrag](ActionInspector.md), [Arbeitsakte](../../../../work/action-inspector/AP-INSP-001/README.md). Unabhängige Abnahme am 06.11.2026 erfolgt.

## AP-INSP-002 – IMPLEMENTIERT / APPROVED

Dieselbe Registryquelle inspector enthält jetzt 23 Topics (65 insgesamt), zehn neu: inspector.create, create_id, create_type, unplaced, delete, delete_references, delete_last, fold_sections, stale und refresh. Die bereits registrierten v1-IDs bleiben erhalten. Neue Controls vererben inspectorTopic an Inputs/Buttons; FoldSection-Toggles binden fold_sections, dynamische Zeilen weiterhin ihren Feldkontext. Der Createbutton bindet inspector.create, der eigene Delete-QMessageBox inspector.delete. Der lokale Topicwert wird vor dem allgemeinen Dialogfallback ausgewertet; alle Aufrufe bleiben im bestehenden NativeHelpBindings/HelpCoordinator.

FocusIn, F1, Pin und Related verwenden weiterhin die eine Hilfeansicht. Neue Facts bleiben leer, auch in Delete-/Stale-Kontexten; keine Rohentwürfe, Token oder Pfade. Die nicht aktive frühere catalog.create_unavailable-Themendefinition wird aus Kompatibilitätsgründen behalten und nicht mehr als aktive Createhilfe geroutet. [Register V-69/V-70](../04-Verbindungsregister.md), [Coverage mit konkreten Controls/Tests](../../../../work/action-inspector/AP-INSP-002/coverage-after.json). Die Hilfe-Kernklassen bleiben unverändert.
