# Aktuelle Entwicklungsplanung – Native-First Plugin Studio

**Stand:** 05.11.2026, nach der unabhängigen Abnahme von AP-STUDIO-001 und AP-WIDGET-006. Diese Datei ist der **einzige aktive Einstiegsindex für neue Studio-Arbeitspakete**. Es gilt [ARCH-ADR-001](../../docs/decisions/ARCH-ADR-001.md) und die [Profil-/Aktionsmodell-Basis v0.2](../../docs/specifications/logitech-profil-und-aktionsmodell-basis-v02.md). Logitech-interne Profildateien sind nur empirische Quellen und **keine freigegebene Schreibschnittstelle**.

## Abgeschlossene aktuelle APs (unabhängig abgenommen)

| Arbeitspaket | Vollständiger Originalauftrag | Ziel | Prüfstand |
|---|---|---|---|
| **AP-STUDIO-001** | [NativeProjectSession v1](AP-STUDIO-001-agentenauftrag-native-session-v01.md) | Qt-freie, native Projektsitzung, sichere Revision/Undo/Redo/Save | **APPROVED am 05.11.2026** – [unabhängige Abnahme](../acceptance/20261105-native-session-explorer/ABNAHME.md) |
| **AP-WIDGET-006** | [NativeProjectExplorer v1](AP-WIDGET-006-agentenauftrag-project-explorer-v01.md) | nur lesender PySide6-Projektbaum | **APPROVED am 05.11.2026** – [unabhängige Abnahme](../acceptance/20261105-native-session-explorer/ABNAHME.md) |

**Beide Agentenläufe sind abgeschlossen und unabhängig abgenommen.** Die Module bleiben isoliert; weder das alte `StudioWindow` noch SDK-Adapter/Runtime/Service-Profile wurden von den beiden Arbeitspaketen integriert oder verändert. Die vollständige [Abnahme](../acceptance/20261105-native-session-explorer/ABNAHME.md) nennt die noch erforderlichen Host-Integrationsgrenzen.

## Aktuelle Folgeplanung

- [Modell- und Parallelentwicklungsplan nach AP-PROF-001](modell-und-parallelentwicklung-nach-ap-prof-001-v01.md): Projekt-Dokumentlebenszyklus, Referenzen, Handler, native und externe States, DynamicFolders, Asset-Priorität und späterer StudioCoordinator.
- [Widget-Landkarte und Schnittstellen v0.1](widget-gesamtarchitektur-und-schnittstellen-v01.md): **technische Vorgeschichte / Referenz**. Das Dokument enthält noch den Vor-Implementierungsstand von AP-WIDGET-002/003; dessen Statusaussagen sind heute überholt. Die aktuelle API ergibt sich aus dem realen Code und den Abnahmeberichten. Während AP-STUDIO-001/AP-WIDGET-006 liefen, wurde die verpflichtende Lektüre nicht umbenannt oder verändert. Eine Überarbeitung dieses Altentwurfs ist erst für einen separat geplanten Coordinator-Schritt sinnvoll.
- [UI-Verbesserungs-Backlog](studio-oberflaeche-verbesserungssammlung.md): reine Wunsch-/Beobachtungssammlung, noch **kein** pauschal beschlossener Designvertrag. Bereits fertiggestellte Probleme/Kontexthilfe nicht ein zweites Mal implementieren.
- [Native-First-Konsolidierung](native-first-konsolidierung-20261103.md): abgeschlossene Änderungs-/Herkunftshistorie, **kein weiterer offener Migrationsauftrag**.
- `native-first-snapshot-20261103-manifest.json` und `native-first-snapshot-20261103.zip`: technisch relevante Ausgangssnapshots; sie bleiben wegen existierender Hash-/Quellreferenzen am ursprünglichen Pfad.

## Abgenommen und abgeschlossen

- [AP-WIDGET-002 / AP-WIDGET-003 – KeypadPreview und ActionCatalog](../acceptance/20261104-keypad-catalog/ABNAHME.md): eigenständige Widgets **APPROVED**.
- [AP-WIDGET-004 – ProblemsPanel](../acceptance/20261105-problems-panel/ABNAHME.md): eigenständiges Widget **APPROVED**.
- [AP-WIDGET-005 – ContextHelp/Registry](../acceptance/20261105-context-help/ABNAHME.md): eigenständiges Widget **APPROVED**.
- **AP-PROF-001:** vollständig abgenommene Logitech-Profilrecherche; in `P:\LokaleProjekte\logi_actions_sdk\logi-actions-sdk-rec\work\archive\RUN-20261104-PROF001-01` archiviert und selektiv in die SDK-Wissensbasis übernommen. [Verbindliche Studio-Folgegrundlage](../../docs/specifications/logitech-profil-und-aktionsmodell-basis-v02.md).

Die abgeschlossenen Agentenprompts liegen unter [`../legacy/planning/completed-prompts/`](../legacy/README.md). Der frühere Studio-Forschungsentwurf AP-RESEARCH-001, die alte P0–P4-Roadmap, das frühere fachneutrale Widgetmodell und der frühe v0.1-Produktreifeplan liegen unter [`../legacy/`](../legacy/README.md). Sie sind **nicht erneut auszuführen**.

## Als Nächstes

1. **Erledigt:** AP-STUDIO-001 und AP-WIDGET-006 unabhängig geprüft und [abgenommen](../acceptance/20261105-native-session-explorer/ABNAHME.md); 27/27 + 31/31 gezielte Tests, 826/826 Regressionen und 16/16 zusätzliche gemeinsame Integrationschecks bestanden.
2. **Erledigt:** AP-STUDIO-002 – NativeStudioShell und StudioCoordinator sind [unabhängig APPROVED](../acceptance/20261106-studio-coordinator/ABNAHME.md).
3. SDK-nativer ActionInspector implementiert (AP-INSP-001, APPROVED); unabhängige Abnahme abgeschlossen.
4. Folder-/Placement-/Handler-/State- und Caption-/Icon-Owner nach echter SDK-Evidenz finalisieren, bevor die jeweiligen Editoren schreiben.

**Nicht geplant:** weiterer universeller Binding-/State-/Action-Kern, `ProfileInfo.json`-Writer oder ungetestete `.lp5`-Migration.

## AP-STUDIO-002 – unabhängige Abnahme (06.11.2026)

- **Status APPROVED.** [Abnahmebericht](../acceptance/20261106-studio-coordinator/ABNAHME.md),
  [Originalauftrag](AP-STUDIO-002-agentenauftrag-studio-coordinator-v01.md) und
  [Agenten-Arbeitsakte](../studio-integration/AP-STUDIO-002/README.md).
- Unabhängig reproduziert: 876/876 Regressionstests, 29/29 Coordinator-, 21/21 Shell-Tests,
  10/10 Smoke-Checks und 23/23 eigene Windows-Qt-Proben; alle 42 Verbindungen erfasst,
  davon 37 implementiert und geprüft, fünf aufgeschoben.
- Nächster Schwerpunkt: SDK-nativer **ActionInspector**. Folder-/Placement-/ICT-Writer-Verträge
  weiterhin getrennt absichern. Nicht-blockierender P2-Hinweis OBS-002-01 ist im Review erfasst.
- **Neue Agentenläufe startet der Benutzer selbst** nach Erhalt des vollständigen Prompts;
  keine automatische Überwachung oder CLI-Beauftragung.


## Kontext-Hilfe-Abdeckung – AP-HELP-001 (06.11.2026)

- **[AP-HELP-001 – vollständiger Agentenauftrag](AP-HELP-001-kontextabdeckung-und-widget-registrierung-v01.md)**: nach der abgenommenen Native-Shell-Integration die **fehlenden Hilfetexte und Fokus-/Selektion-/Zustandszuordnungen** der aktuell integrierten Widgets systematisch ergänzen. **Status APPROVED (06.11.2026)**; [unabhängige Abnahme](../acceptance/20261106-help-coverage/ABNAHME.md); [Arbeitsakte mit Coverage-Audit, Tests und Windows-Evidenz](../help-integration/AP-HELP-001/README.md). Die unabhängige Abnahme ist abgeschlossen (925 Gesamttests, 19 eigene Windows-Qt-Prüfungen).
- Bestehende `HelpRegistry`, `HelpCoordinator` und `ContextHelpWidget` bleiben maßgeblich; keine Neuimplementierung, kein Eingriff in SDK-/Service-/Keypad-Schreibpfade. Erster Schritt ist ein belegbarer UI-Coverage-Audit; neue Komponenten können sich anschließend mit eigenen Quellen in der Registry registrieren.
- Als eigenständiges AP **vor** einer breiteren ActionInspector-Integration möglich; nicht parallel mit einem Agenten starten, der gleichzeitig `native_shell/coordinator.py` oder `window.py` schreibt. Der Nutzer startet den Agenten nach Erhalt des Prompts selbst.


## Implementiert: AP-INSP-001 – SDK-nativer ActionInspector (06.11.2026)

- **[Vollständiger Agentenauftrag AP-INSP-001](AP-INSP-001-native-action-inspector-v01.md)** – **APPROVED; unabhängige Abnahme am 06.11.2026 erfolgt.** Bereits vorhandene native Actions aller vier SDK-Typen fachlich vollständig bearbeiten, inklusive Parameter, Multistate, Adjustment, Editor-Controls, Handler- und Asset-Referenzen. Ein flüchtiger Formulardraft erzeugt erst bei Apply genau einen validierten Session-Commit.
- **[Normative ActionInspector-Schnittstellenspezifikation](../../docs/architecture/studio/widgets/ActionInspector.md)** – Feldmatrix, Referenzschutz, Draft-Lebenszyklus, Help-Topics und Integrationsgrenzen. Das Katalog-Bearbeiten wird gezielt auf den Inspector geführt; Toolbar-Anzeigenamen-Schnelleditor bleibt erhalten.
- **Folgephase AP-INSP-002** erst nach unabhängiger Abnahme: neue Actions erstellen, vorhandene löschen und Referenzregeln absichern. Das ist **nicht Teil** des ersten Inspector-Pakets. Umsetzung und Evidenz stehen in der [Arbeitsakte](../action-inspector/AP-INSP-001/README.md). Keine Selbstfreigabe; unabhängige Abnahme separat.

## Unabhängige Freigabe AP-INSP-001 – 06.11.2026

**APPROVED**: [vollständige Reviewakte](../acceptance/20261106-action-inspector/ABNAHME.md). 963/963 Gesamttests, 17/17 Windows-Qt-Integrationstests, 23/23 zusätzliche unabhängige Qt-Prüfungen, 16 erlaubte Bestandsänderungen sowie 10 neue geprüfte V-IDs. Als nächstes AP-INSP-002: sichere Erstellung/Löschung nativer Actions; neue Agentensession startet ausschließlich der Nutzer.


## Implementiert: AP-INSP-002 – APPROVED (06.11.2026)

[Vollständiger unveränderter Auftrag](AP-INSP-002-native-action-lifecycle-und-inspector-ux-v01.md), [implementierter Lifecycle-Vertrag](../../docs/architecture/studio/widgets/ActionLifecycle.md), [Arbeitsakte mit Tests, Scope und Windows-Screenshots](../action-inspector/AP-INSP-002/README.md). Alle vier SDK-Typen erstellen; ausschließlich unreferenzierte Actions bestätigt löschen. Referenzierte/letzte Action bleibt geschützt. Kompakte Inspectorbereiche und proaktive Stale-Warnung umgesetzt; eine Session und eine Kontexthilfe. **APPROVED**, keine Selbstfreigabe als APPROVED. Unabhängige Abnahme vom 06.11.2026 ist dokumentiert. Keine neue Agentensession oder Automation angelegt.

## AP-INSP-002 – unabhängig APPROVED am 06.11.2026

[Vollständige unabhängige Abnahme](../acceptance/20261106-action-lifecycle/ABNAHME.md). 1.018/1.018 Gesamttests, 33/33 echte Windows-Qt-Modultests, 39/39 zusätzliche Reviewer-End-to-End-Prüfungen, 23/23 bestehende Quell-/Dokumentationsänderungen gegen SHA-256-Baseline, 6 neue Dateien, 8 belegte neue V-IDs und 65 eindeutige Hilfe-Topics. Folder-Referenzen geschützt; OBS-INSP-001/002 umgesetzt. Nächster Schritt eigener nativer FolderEditor/Placement-Vertrag. Kein Folgeagent gestartet.

## AP-GUIDE-001 – Geführter Ablauf (16.–18.11.2026, READY_FOR_REVIEW)

Plan, Auftrag, Fortschritt, Tests und Abschlussbericht: [Arbeitsakte](../guided-workflow/AP-GUIDE-001/README.md).
Umgesetzt: geführter Ablauf in sieben Schritten, HandlerInspector, Übersichten Zustände/Symbole, Wartung,
Begriffsliste. Der UI-Backlog [studio-oberflaeche-verbesserungssammlung.md](studio-oberflaeche-verbesserungssammlung.md)
ist damit in U-02 bis U-09 und E-01 bis E-12 weitgehend bedient; offen bleibt U-01 (Dienst-Neustart, bewusst nicht
umgesetzt). Nächster Schritt: Windows-Prüfung, Release-Build 1.0.0-rc2 und Benutzerabnahme durch den Auftraggeber.
