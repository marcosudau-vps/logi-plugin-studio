# Studio-Architektur: Komponenten und Verdrahtung

**Aktueller Ergänzungsstand AP-INSP-002: IMPLEMENTIERT / APPROVED.** Native Actions können erstellt und unreferenziert bestätigt gelöscht werden. Accordion und proaktive Stale-Warnung sind implementiert; unabhängige Abnahme vom 06.11.2026 liegt vor. Die unten aufgeführten AP-INSP-001-Grenzen sind dessen historischer Umfang.


Stand: 06.11.2026 · AP-STUDIO-002: **APPROVED**, [unabhängige Abnahme](../../../work/acceptance/20261106-studio-coordinator/ABNAHME.md) abgeschlossen. NativeStudioShell und StudioCoordinator sind implementiert und geprüft. Der alte 0.1-draft-Editor bleibt der Standardstart.

Vorrang: [ARCH-ADR-001](../../decisions/ARCH-ADR-001.md), [Profil-/Aktionsmodell v0.2](../../specifications/logitech-profil-und-aktionsmodell-basis-v02.md). NativeProject bleibt die SDK-native Leseprojektion; serviceverwaltete Profile sind keine Studio-Schreibdomäne.

## Architektur lesen

1. [Gesamtkarte: IST und SOLL](00-Gesamtkarte.md)
2. [Daten, Identität und Transaktionen](01-Daten-und-Transaktionen.md)
3. [StudioCoordinator und native Shell](02-StudioCoordinator.md)
4. [Verbindungsregister: V-ID → Code → eigener Integrationstest](04-Verbindungsregister.md)
5. [Geplante Editoren](03-Geplante-Editoren.md)

## Führende Komponentenreferenzen

| Komponente | Einzelreferenz |
|---|---|
| NativeProjectExplorerWidget | [Projektbaum](widgets/NativeProjectExplorer.md) |
| ActionCatalogWidget | [Katalog](widgets/ActionCatalog.md) |
| KeypadPreviewWidget | [Preview: Integration aufgeschoben](widgets/KeypadPreview.md) |
| ProblemsPanelWidget | [Probleme](widgets/ProblemsPanel.md) |
| ContextHelpWidget, Registry, HelpCoordinator | [Hilfe](widgets/ContextHelp.md) |
| NativeProjectSession | [Session-Service](services/NativeProjectSession.md) |

Start: `python tools/run_studio.py --native <Projekt.json>`. Ohne `--native` bleibt der vorhandene `StudioWindow` für `0.1-draft` aktiv. Keine automatische Formatmigration. Lab: `python tools/run_native_studio_lab.py` (temporäre Projektkopie).

Jede zukünftige API-/Hoständerung aktualisiert Einzelreferenz, Gesamtkarte, Register und einen eigenständigen Integrationstest im selben AP. IMPLEMENTIERT verlangt existierenden Code UND bestandenen Hosttest. Aufgeschobene Kanten dürfen keine produktive Fähigkeit behaupten.

[AP-STUDIO-002-Vertrag](../../../work/planning/AP-STUDIO-002-agentenauftrag-studio-coordinator-v01.md) · [Arbeitsakte / Phasen / Befehle / Screenshots](../../../work/studio-integration/AP-STUDIO-002/README.md)

## Kontextabdeckung AP-HELP-001

**APPROVED (06.11.2026)**; [unabhängige Abnahme](../../../work/acceptance/20261106-help-coverage/ABNAHME.md) abgeschlossen. Die bestehende Hilfeinfrastruktur wird weiterverwendet. `native_shell/help_bindings.py` ergänzt quelleneigene Registrierung, deklarative Controlzuordnung und fenstereigene Fokus-/F1-Routen. Der unveränderte Defaultkatalog bleibt erhalten; neue Themen erklären aktive Controls und sichtbare Sperren. [Hilfereferenz](widgets/ContextHelp.md), [Kanten V-43–V-52](04-Verbindungsregister.md) und [Arbeitsakte mit Audit, Tests und Windows-Evidenz](../../../work/help-integration/AP-HELP-001/README.md).


## Implementierte Widget-Integration: ActionInspector

- [ActionInspector – implementierter Draft- und Hostvertrag](widgets/ActionInspector.md).
- [AP-INSP-001 – vollständiger Agentenauftrag](../../../work/planning/AP-INSP-001-native-action-inspector-v01.md) (**APPROVED, unabhängige Abnahme am 06.11.2026 erfolgt**).
- Die bereits abgenommene Hilfe aus AP-HELP-001 wurde **im gleichen Inspector-AP** mit eigenen Topics und echten F1-/Fokus-Integrationstests erweitert; beim Inspector kein späterer Hilfe-Nachrüstlauf.
- Erst nach AP-INSP-001: AP-INSP-002 – Actions neu anlegen/löschen und Referenzschutz. Bestehende Keypad-/ICT-Writer bleiben gesperrt.

## AP-INSP-001 – implementiert, APPROVED

Der [ActionInspector](widgets/ActionInspector.md) bearbeitet alle vier vorhandenen SDK-Aktionstypen einschließlich strukturierter Parameter, States, Adjustment, EditorControls/Filter und Asset-Referenzen. NativeAction ist weiter nur Leseprojektion. Ein defensiver Qt-freier ActionDraft hält Rohdaten und opake Baserevision; nur bewusst geänderte Felder werden gepatcht. ID und Typ bleiben fest, neue Actions und Folderänderungen bleiben ausgeschlossen.

Auswahl aus Explorer/Katalog beziehungsweise FolderEntry→Action wird vom Host in den permanenten Inspector-Tab projiziert. Katalog-Bearbeiten öffnet diesen Tab; Toolbar-Anzeigename bleibt QInputDialog. Apply führt über `StudioCoordinator.apply_action_edit` zu genau einem `NativeProjectSession.replace`, ohne Autosave. Undo/Redo/Save bleiben dieselbe Sessionhistory. Dirty-Drafts werden unabhängig von Session-Dirty geschützt; Cancel, stale Revision, DiskConflict und fehlgeschlagene Projektwechsel erhalten Eingaben. Alle Ansichten werden nach erfolgreichem Commit frisch projiziert; Dirty-Refresh überschreibt keine Felder.

Die eine bestehende Hilfe erhält Quelle inspector mit 13 Topics (55 insgesamt). Lokale `inspectorTopic`-Eigenschaften gelten auch für dynamische Zeilen/Filter; Host-F1/FocusIn/Pin/Related zeigen keine Rohdaten. [Register V-53–V-62](04-Verbindungsregister.md), [Arbeitsakte, Tests und Windows-Bilder](../../../work/action-inspector/AP-INSP-001/README.md). Unabhängige Abnahme am 06.11.2026 erfolgt; AP-INSP-002 bleibt Folgeplanung.

## Nachweis AP-INSP-001

Der ActionInspector v1 ist [unabhängig APPROVED](../../../work/acceptance/20261106-action-inspector/ABNAHME.md) mit 963 Gesamttests und 23 zusätzlichen Qt-Gegenprüfungen. Die [führende Komponentenreferenz](widgets/ActionInspector.md) und V-53–V-62 dokumentieren die tatsächliche Verdrahtung.


## Aktueller Ergänzungsstand AP-INSP-002 – IMPLEMENTIERT / APPROVED

[ActionLifecycle](widgets/ActionLifecycle.md) erweitert den abgenommenen v1-Inspector um Create für vier SDK-Typen, bestätigtes Delete ausschließlich unreferenzierter Actions, kompakte Accordiongruppen und frühzeitigen Stale-Status. Die früheren Create-/Delete-Sperraussagen dieses Dokuments bezeichnen die historische AP-INSP-001-Baseline. [Arbeitsakte und Nachweise](../../../work/action-inspector/AP-INSP-002/README.md), [V-63–V-70](04-Verbindungsregister.md). Die Erweiterung wurde am 06.11.2026 unabhängig abgenommen. Folder-/Handler-/Keypad-/ICT-Writer bleiben getrennte Folgearbeit.

## AP-INSP-002 – unabhängige Abnahme (06.11.2026)

**APPROVED:** [Reviewbericht mit Eigenprüfungen](../../../work/acceptance/20261106-action-lifecycle/ABNAHME.md). Der [ActionLifecycle-Vertrag](widgets/ActionLifecycle.md) ist implementiert; referenzierte und letzte Actions bleiben beim Löschen gesperrt. Preview/FolderEntry-/ICT-Writer sind weiterhin geplant bzw. gesperrt.


## AP-FOLDER-002 – integrierter FolderComposer (softwareseitig APPROVED am 07.11.2026)

Der vorhandene FolderComposer ist im nativen Studio als Tab **Virtuelle Ordner** integriert. NativeProjectSession bleibt alleiniger Writer des nativen Projekts; ExtensionStore verwaltet ausschließlich die pfadgebundene `.vfolders.json` daneben. Die Toolbar benennt beide Speicheraktionen und die aktuell aktive Undo-/Redo-History ausdrücklich. Projektwechsel/Reload validieren beide Kandidaten vor Dirty-Dialogen und nochmals danach. Cancel oder Savefehler erhalten alle noch nicht verworfenen Entwürfe.

Studio-Referenzschutz umfasst jetzt virtuelle Action-Platzierungen sowie native Undo-/Redo-Schritte. Verwaiste lokale Referenzen werden im integrierten Composer erhalten, diagnostiziert und können bewusst entfernt werden. Keine automatische Reparatur oder Kaskadenlöschung. [Vertrag](widgets/FolderComposer.md), [Register V-74–V-82](04-Verbindungsregister.md), [Arbeitsakte und tatsächliche Testzahlen](../../../work/studio-integration/AP-FOLDER-002/README.md). SDK-Runtime/Generator werden nach Prioritätsänderung von einem anderen Auftrag bearbeitet und sind kein Nachweis dieser Integration.

## 07.11.2026 – SDK-Build aus integrierter Folder-Extension

Der native Studio-Tab **Plugin-Build** reicht nach explizitem Klick den gespeicherten nativen Snapshot und optional die projektgebundene `.vfolders.json`-Extension an die vorhandene SDK-Projektion und den BuildWorker weiter. Ohne Sidecar bleibt der native Folderpfad erhalten; mit mehreren realen SDK-Foldern ist die Startknotenzuordnung explizit. Keine Installation, Profiländerung oder Dienstneustarts. [Build-Vertrag](NativeBuildIntegration.md) · [Register V-83–V-85](04-Verbindungsregister.md) · [Gemeinsame Reviewakte](../../../work/acceptance/20261107-joint-folder-build/ABNAHME.md).

## Schichtentrennung nach dem SDK-Audit 08.11.2026

`NativeStudioShell` darf weiterhin die optionale `virtual-folders-1`-Extension bedienen. Deren Runtime-Code und C#-Vorlage liegen jetzt ausschließlich unter `src/extensions/shared_folders/`, nicht in der generischen SDK-Bridge. [Grenzvertrag](../sdk-bridge-schichtentrennung.md) · [Python-API-Abdeckung](../../specifications/sdk-python-api-checklist.md). Die vorhandenen Studio-/Build-Tests gelten unverändert; ein Häkchen für C#-Generierung ist noch keine vollständige Python-SDK-API.

## 18.11.2026 – Geführter Ablauf AP-GUIDE-001 (READY_FOR_REVIEW)

Die native Shell besitzt eine abschaltbare Komfortschicht `workflow=True` (Programmeinstieg): sieben Schritte mit
Checkliste, Sichtbarkeit je Schritt, Führungsthemen, Build-Sperre und Expertenmodus. Neue Komponenten:
[WorkflowGuide](widgets/WorkflowGuide.md), [HandlerInspector](widgets/HandlerInspector.md),
[Wartung](widgets/Maintenance.md), Übersichten Zustände/Symbole. [Begriffsliste](Begriffe.md).
Verbindungen [V-90 bis V-107](04-Verbindungsregister.md). Kein neuer Writer; NativeProjectSession und ExtensionStore
bleiben alleinige Eigentümer ihrer Dateien.
