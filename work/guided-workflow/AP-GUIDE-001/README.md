# AP-GUIDE-001 – Geführter Ablauf und Fertigstellung des Plugin Studios

**Status: IN_ARBEIT** (wird bei Abschluss auf `READY_FOR_REVIEW` gesetzt; keine Selbstabnahme).
Beginn: 16.11.2026 · Ausführung: Claude · Repository: `marcosudau-vps/logi-plugin-studio`, Branch `release/1.0.0`.

Das native Studio führt den Anwender in sieben Schritten von der Projektanlage bis zum getesteten Plugin am
Gerät. Je Schritt sind nur die passenden Bereiche sichtbar, jeder Schritt hat prüfbare Abschlusskriterien, und
die Hilfe erklärt den nächsten Handgriff. Fehlende Widgets (HandlerInspector, Übersichten, Wartung) werden in
Ablaufreihenfolge ergänzt. Alle Architekturentscheidungen bleiben unverändert (ARCH-ADR-001, ein Writer je Datei).

| Datei | Inhalt |
|---|---|
| [00_plan.md](00_plan.md) | Freigegebener Plan |
| [01_auftrag.md](01_auftrag.md) | Aufträge im Wortlaut, Entscheidungen, Branch-Schema |
| [02_fortschritt.md](02_fortschritt.md) | **Laufende Checkliste und Chronik** |
| [03_implementierung.md](03_implementierung.md) | Was wo geändert wurde, Entscheidungen, Abweichungen vom Plan |
| [04_git_und_branches.md](04_git_und_branches.md) | Branches, Commits, was nicht im Repository liegt |
| [05_tests_und_evidenz.md](05_tests_und_evidenz.md) | Testläufe, Ausgangsbasis, Evidenz |
| [06_offene_punkte.md](06_offene_punkte.md) | Grenzen und offene Punkte nach Priorität |
| [07_abschlussbericht.md](07_abschlussbericht.md) | Abschlussbericht (bei Abschluss) |
| [outputs/BENUTZERABNAHME.md](outputs/BENUTZERABNAHME.md) | Abnahmeskript für den neuen Ablauf (bei Abschluss) |

Fachliche Verträge: [WorkflowGuide](../../../docs/architecture/studio/widgets/WorkflowGuide.md),
[HandlerInspector](../../../docs/architecture/studio/widgets/HandlerInspector.md),
[Verbindungsregister V-90 ff.](../../../docs/architecture/studio/04-Verbindungsregister.md).
