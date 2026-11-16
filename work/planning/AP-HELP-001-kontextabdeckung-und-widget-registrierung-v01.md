# AP-HELP-001 – Kontextabdeckung und Widget-Hilfe

**Vollständiger Agentenauftrag; kein Vorwissen nötig.**
**Projektroot:** `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture`
**Status:** PREPARED, noch nicht gestartet (06.11.2026).

## Ziel
Die vorhandene `HelpRegistry`, `HelpCoordinator` und `ContextHelpWidget` sind bereits unabhängig abgenommen (AP-WIDGET-005) und in der nativen Shell integriert (AP-STUDIO-002, APPROVED). Nicht neu bauen! Stattdessen alle **tatsächlich aktiven Controls, Selektionen und UI-Zustände** der nativen Shell systematisch auf Hilfetexte und Kontextzuordnungen prüfen und Lücken schließen. Widgets/Host melden ausschließlich `HelpContext(topic_id, facts)`; der Coordinator liefert über `HelpDisplayState` an die **eine** Hilfeansicht. Keine direkte Hilfetextkopie von Widgets in die View.

## Verbindliche Quellen
Vor der Umsetzung vollständig lesen, alle Pfade relativ zum Projektroot:
- `docs/decisions/ARCH-ADR-001.md`, `docs/specifications/logitech-profil-und-aktionsmodell-basis-v02.md`
- `docs/architecture/studio/README.md`, `00-Gesamtkarte.md`, `02-StudioCoordinator.md`, `04-Verbindungsregister.md`
- `docs/architecture/studio/widgets/{NativeProjectExplorer,ActionCatalog,ProblemsPanel,ContextHelp,KeypadPreview}.md`
- `work/acceptance/20261105-context-help/ABNAHME.md`, `work/acceptance/20261106-studio-coordinator/ABNAHME.md`
- `src/studio/context_help/{entries,registry,coordinator,widget}.py` und `resources/default_topics.de.json`
- `src/studio/native_shell/{coordinator,window}.py`
- `src/studio/{native_project_explorer,action_catalog,problems_panel,keypad_preview}/widget.py`
- `tests/test_native_studio_shell.py`, `tests/test_studio_coordinator.py`

Das vorhandene deutsche `default_topics.de.json` enthält 16 Themen. Bisher lädt die Shell diese gesammelt mit `source='studio'`. Eine gleichmäßige, quelleneigene Kontrolle-/Kontextabdeckung existiert noch nicht. Bestehende IDs und den Defaultkatalog beibehalten.

## A – Coverage-Audit VOR Umsetzung
Erstelle `work/help-integration/AP-HELP-001/coverage-before.md` mit **einem Eintrag je relevante aktive Eingabe-/Auswahlfläche**: Codepfad/`objectName`, Fokus/Benutzerereignis, bestehendes Topic/Fallback, gewünschtes Topic, dynamische Facts, `OK/FEHLT/NICHT_AKTIV/BEWUSST_OHNE`, zugehöriger künftiger Test.

Abdecken: ProjectExplorer (Tree, Suche, Action/Handler/Folder/FolderEntry); ActionCatalog (Suche, Parameterauswahl, SDK-Typfilter, Sortierung, Edit, gesperrtes Erstellen); ProblemsPanel (Suche, Severity, Meldung/Details, Leerzustand); Native-Shell-Toolbar (Öffnen, Save, Undo, Redo, Umbenennen, Neu laden, F1), Hilfe-Widget (Pin, Details, Related-Topics). Prüfe Fokus/Selektion bei geöffnetem Dialog, Projektwechsel und unbekannten Objekten.

**KeypadPreview und native ICT sind bewusst nicht produktiv freigeschaltet.** Vorbereitete `keypad.*`- und `symbol.ict`-Themen können vorhanden bleiben, aber als NICHT_AKTIV markieren; keinesfalls erfundene Frame-/Slot-/Placementdaten oder einen ICT-Writer einführen.

## B – Implementierung
Verwende `HelpRegistry.register_many(entries, source=...)` für quelleneigene Themenbeiträge. Bevorzugte neue JSON-Dateien unter `src/studio/context_help/resources/`:
`explorer_topics.de.json`, `catalog_topics.de.json`, `problems_topics.de.json`, `native_shell_topics.de.json`.
Keine doppelten Topic-IDs. Vorhandene `catalog.search`, `catalog.parameter`, `action.definition`, `problems.diagnostic` etc. wiederverwenden. Ein Topic bekommt deutsche Titel, kurze klare Erklärung, optionale Details/Beispiel und verifizierte verwandte Themen – keine SDK-Behauptungen ohne Code-/Quellenbeleg.

Neue **deklarative Zuordnung** `src/studio/native_shell/help_bindings.py` bevorzugen; die aktiven Controls anhand stabiler ObjectNames oder ausdrücklich gebundener Qt-Objekte registrieren. Kontext beim Fokus-/Selektionswechsel über den einen Host setzen; keine direkten Widget→HelpWidget-Aufrufe, keine globale Überwachung fremder Fenster. Bestehende HelpCoordinator-Regeln beachten:
- normale Selektion/Fokus → `set_context`, Pin respektieren;
- F1 → explizites `request_help` passend zum tatsächlichen aktuellen Fokus auch bei Pin;
- RelatedTopic → nur registrierte Topic-ID; kein unbekanntes Routing;
- Projektwechsel → veralteten Kontext/Facts/Diagnosen entfernen;
- gleiche sichtbare Namen → native IDs, keine Stringableitung;
- unbekanntes Topic → definierter Fallback, keine Exception/Feedbackloop.
Hilfefakten nur aus aktuellen, geprüften UI-/Sessiondaten; kein API-Key/Token, unvalidiertes HTML oder ungesicherte Pfad-/Log-Ausgabe. Disable-/Read-only-Features müssen ihren Grund klar erklären.

## Schreibbereiche
NEU: `src/studio/native_shell/help_bindings.py`, die oben genannten JSON-Themen, `tests/test_native_help_coverage.py`, optional `tools/run_native_help_lab.py`, `work/help-integration/AP-HELP-001/`.
MINIMAL: `src/studio/native_shell/{coordinator,window}.py`, ggf. `default_topics.de.json` (nur zwingende additive Änderungen).
DOKUMENTATION: `docs/architecture/studio/{README,00-Gesamtkarte,04-Verbindungsregister}.md`, `docs/architecture/studio/widgets/ContextHelp.md` und betroffene Widgetreferenzen; `work/planning/README.md` ausschließlich Statushinweis.
NICHT verändern: `src/studio/app.py`, `src/studio/native_session.py`, `src/studio/native_ict_binding.py`, SDK-Adapter/Runtime/Core/Schemas, alte Widgets/Abnahmeakten, Logitech-Profile/Service. Keine zweiten Frameworks. Begründeten minimalen Bugfix an bestehender Hilfe-Kernklasse nur bei Reproduktionsbeleg und separatem Regressionstest.

## Tests und unabhängige Abnahmevorbereitung
- Jede aktuell aktive Kontextzuordnung hat `topic_id`, Eigentümer/Quelle, Fokusanlass, mögliche dynamische Fakten und mindestens einen konkreten GUI-/Qt-Test.
- Tests für FocusIn, Tree/Parameterwahl, Suche/Filter, Toolbar, F1-vs-Pin, RelatedTopic, Verlust der Auswahl, Projektwechsel, inaktive Funktionen und Topic-Fallback.
- Keine zusätzliche `session.replace`/`save`-Operation durch Hilfe; kein Qt-Signalloop; keine direkten SDK-/Dateiwrites.
- Neue `IMPLEMENTIERT`-Kanten nur mit **neuer V-ID + realem Codepfad + eigenem Integrationstest**, die bestehenden 42 V-IDs nicht umnummerieren.
- Schreibe `coverage-after.json` als maschinenlesbares Coverage-/Lückenregister, kein pauschales „100 %“ ohne belegte Liste.
- Echte Windows-PySide6-Aufnahmen für Katalogfilter, ProjectExplorer-Auswahl, Problems-Detail; offscreen allein genügt nicht.
- Gesamten bisherigen Testbestand bestehen lassen.

**Pflichtbefehle:**
```powershell
python -m unittest discover -s tests -p test_native_help_coverage.py -v
python -m unittest discover -s tests -q
python tools/check_links.py
```
Optionales eigenes Lab zusätzlich mit `--smoke` testen. Testausgaben, Exitcodes, Dateidiff, Screenshots, Audit in `work/help-integration/AP-HELP-001/README.md` sichern. Bei Problemen innerhalb des Scopes selbst korrigieren.

**Abschluss:** `READY_FOR_REVIEW`, niemals selbst `APPROVED`. Unabhängige Abnahme folgt. Keine automatische Agenten- oder Monitoring-Session starten.
