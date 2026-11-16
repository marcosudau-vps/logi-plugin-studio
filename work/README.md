# Arbeitsbereich – aktueller Einstieg (05.11.2026)

**Maßgebliche Zielrichtung:** [ARCH-ADR-001 – Native First](../docs/decisions/ARCH-ADR-001.md) und [Profil-/Aktionsmodell v0.2](../docs/specifications/logitech-profil-und-aktionsmodell-basis-v02.md). Fachliche Entscheidungen liegen in `docs/`; `work/` führt Planung, Ausführung und überprüfbare Nachweise.

## Wo ist was?

| Bereich | Heutige Rolle | Status |
|---|---|---|
| [`planning/`](planning/README.md) | **Aktueller Plan**, nächste Agentenaufträge und Abhängigkeiten | Aktiv |
| [`acceptance/`](acceptance/20261105-context-help/ABNAHME.md) | Unabhängig abgenommene, nachprüfbare Widgetergebnisse | Anerkannte Evidenz |
| [`widget-lab/`](widget-lab/context-help-v1/README.md) | Eigenständige Widget-Implementierungs-/GUI-Labs | Abgeschlossene Labs, vollständig abgenommen im vereinbarten Umfang |
| `native-session/` | AP-STUDIO-001: abgeschlossener Agentenlauf zur nativen Autorenprojekt-Session | **APPROVED (isoliert)** – [Abnahme](acceptance/20261105-native-session-explorer/ABNAHME.md) |
| `widget-lab/native-project-explorer-v1/` | AP-WIDGET-006: abgeschlossener Agentenlauf zum rein lesenden nativen Projektbaum | **APPROVED (isoliert)** – [Abnahme](acceptance/20261105-native-session-explorer/ABNAHME.md) |
| [`migrations/`](migrations/native-first-20261103/04_migrationsbericht.md) | Umsetzungs-/Migrationsnachweise zur nativen Architektur | Anerkannte Historie / Belege |
| [`product-readiness/`](product-readiness/INDEX.md) | UX-/Scope- und Hardware-Prüfergebnisse; ältere Statusregister sind **Zeitstände** | Evidenz + offene v1-Ziele |
| [`templates/`](templates/README.md) | Arbeitsakten-/Abnahmevorlagen | Wiederverwendbar |
| [`legacy/`](legacy/README.md) | Frühere Übergaben, durch spätere Entscheidungen überholte Planungen, fertige Promptfassungen | **Nicht neu ausführen** |
| [`packages/`](packages/README.md), [`runs/`](runs/README.md) | Frühere AP-CORE-/AP-LOGI-Aufträge und zugehörige Arbeitsakten | **Historische, weiterhin referenzierte Kompatibilitätsbelege** |
| `autopilot/`, `agent_bridge/` | Frühere Produkt-/Agentenarbeitsakten und Tests; von weiteren Berichten/Tools referenziert | **Historische Nachweise, stabile Pfade** |
| [`housekeeping/`](housekeeping/20261105/ANALYSE.md) | Dokumentierter Dateiaudit und reversible Umzugszuordnung | Organisatorisch |

**Warum nicht alles alte unter `legacy/` liegt:** Einige abgeschlossene Arbeitsakten und Hardwarebelege werden noch von Tests, Generatorberichten, Dashboard oder ADRs unter ihren ursprünglichen Pfaden referenziert. Sie bleiben daher **bewusst ortsstabil**; „historisch“ bedeutet nicht „entbehrlich“. Die nachweisbar überholten *Planungsversionen* und *Übergaben* wurden dagegen ausgelagert.

## Die eine aktuelle Planungslinie

1. **Erledigt und unabhängig APPROVED:** [AP-STUDIO-001 NativeProjectSession](planning/AP-STUDIO-001-agentenauftrag-native-session-v01.md) und [AP-WIDGET-006 NativeProjectExplorer](planning/AP-WIDGET-006-agentenauftrag-project-explorer-v01.md). [Gemeinsamer Abnahmebericht](acceptance/20261105-native-session-explorer/ABNAHME.md).
2. **Architektur/Abhängigkeiten:** [Modell- und Parallelentwicklungsplan nach AP-PROF-001](planning/modell-und-parallelentwicklung-nach-ap-prof-001-v01.md).
3. **Erledigt:** [StudioCoordinator und NativeStudioShell v1](acceptance/20261106-studio-coordinator/ABNAHME.md) unabhängig APPROVED; Keypad-/ICT-Write weiterhin gesperrt.
4. **Anschließend:** ActionInspector und die fachlichen Referenz-/Handler-/State-/Folder-Verträge gezielt vervollständigen, nicht durch eine SDK-unabhängige zweite Fachdomäne ersetzen.
5. **Spätere Sonderfälle:** Logitech-Profile aus `Applications/ProfileInfo.json` nur lesend; kein unbestätigter Editor oder `.lp5`-Writer.

## Historie und Abnahme

Die bereits abgenommenen Widget-Läufe werden **nicht erneut gestartet**. Historische Agentenprompts liegen unter `legacy/planning/completed-prompts/`; ihre Abnahmeberichte bleiben unverändert unter `acceptance/`. Die alte P0–P4-Roadmap, fachneutralen Widgetmodelle und älteren Übergaben liegen unter `legacy/`.

Die Details jeder Umordnung stehen in [Umzugsmanifest und Prüfbericht](housekeeping/20261105/ANALYSE.md). Während der beiden mittlerweile abgeschlossenen Agentenläufe wurden ihre Arbeitsdateien nicht durch das Housekeeping verändert. Dessen **organisatorische Dateiverschiebungen vom 05.11.2026** sind bei historischen Workspace-Snapshot-Vergleichen als externe Änderungen zu behandeln, nicht als Eigenänderungen der Entwicklungsagenten.

## Arbeits- und Freigaberegeln

Neue Agentenläufe: unveränderten Originalauftrag, eigenen Schreibbereich und vollständige Test-/Reviewakte führen. `READY_FOR_REVIEW` ist keine unabhängige Abnahme. Keine produktiven Änderungen an Logitech-Profilen/Service ohne dafür gesondert freigegebenes Paket. Bei einer neuen Entscheidung stets `docs/` konsistent fortschreiben und keinen alten Legacy-Prompt zur zweiten Norm machen.

## Letzte unabhängige Abnahme – AP-STUDIO-002 (06.11.2026)

Die NativeStudioShell/StudioCoordinator-v1-Integration ist
[unabhängig APPROVED](acceptance/20261106-studio-coordinator/ABNAHME.md):
876 Gesamtregressionen, 23 eigene Windows-/Qt-/Session-Checks, 37 implementierte
Hostverbindungen mit Tests und fünf sicher aufgeschobene Kanten.
Nächster Schwerpunkt ist der SDK-native ActionInspector; weitere Agentensessions
startet der Benutzer nach Erhalt eines vollständigen Prompts selbst.

## Neueste unabhängige Abnahme – AP-HELP-001 (06.11.2026)

Die [Kontexthilfe-Integration](acceptance/20261106-help-coverage/ABNAHME.md) ist **APPROVED**. Insgesamt 42 deutsche Themen mit 44 geprüften aktiven Kontextzuordnungen; Keypad und ICT bewusst nicht freigeschaltet. Nächster großer Studio-Schritt: nativer ActionInspector. Neue Agentensessions startet der Benutzer selbst.

## Abnahme AP-INSP-001 – 06.11.2026

[ActionInspector v1](acceptance/20261106-action-inspector/ABNAHME.md) unabhängig **APPROVED**. Die vorhandenen vier nativen Actiontypen sind editierbar; nächstes gesondertes AP-INSP-002 für Action-Erstellung und -Löschung. Keine Agentensession automatisch gestartet.

## Letzte unabhängige Studio-Abnahme: AP-INSP-002 (06.11.2026)

[ActionLifecycle und Inspector-UX](acceptance/20261106-action-lifecycle/ABNAHME.md) unabhängig **APPROVED**: neue native Actions aller vier SDK-Typen, unreferenzierte Actions nach Bestätigung löschen, Folder-/Letzte-Action-Schutz, Undo/Redo/Save, kompakte Accordion-Editoren, proaktive Stale-Warnung und eigene Kontexthilfe. Folgeaufgaben FolderEditor/Placement und SDK-Capability-Mapping getrennt.
