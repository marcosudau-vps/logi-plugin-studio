# 01 – Auftrag AP-GUIDE-001

Auftraggeber: Marco (Projektinhaber). Ausführung: Claude im claude.ai-Projekt „logitech_actions_sdk_plugin_studio“.
Diese Datei hält die Aufträge fest, aus denen das Arbeitspaket entstanden ist. Wörtliche Zitate sind
unverändert; das Branch-Schaubild ist zusammengefasst.

## 16.11.2026, 22:52 – Planungsauftrag

> Bitte erstelle dir einen Plan, wie du die Punkte in welcher Reihenfolge am besten strukturiert abarbeitest.
> Dabei sollen bereits getroffene Architekturentscheidungen beibehalten werden. Allerdings soll insbesondere auf
> die Benutzererfahrung Wert gelegt werden, dass man zum Beispiel durch die Hilfe, so gesehen durch die Erstellung
> eines Plugins geführt wird. Das beinhaltet auch, dass quasi in den richtigen Phasen die richtigen Elemente
> eingeblendet werden und die anderen nicht verfügbar sind, sodass man da so einen eindeutigen Weg hat, wie man was
> zu welchem Zeitpunkt verfügbar ist und wie das Ganze auch validiert wird. Das soll nicht mehr so frei sein,
> sondern das soll wie so ein mehrschrittiger Prozess werden. Bitte erstell dazu erstmal den Plan.

Ergebnis: Plan „Geführter Ablauf und Fertigstellung des Plugin Studios“ (Projektdokument
`claude/plan-gefuehrter-ablauf-2026-11-16.md`, Kopie: [`00_plan.md`](00_plan.md)).

## 16.11.2026, 23:25 – Freigabe und Umsetzungsauftrag

> Super, der Plan ist soweit abgenommen. Bitte beginne jetzt damit, ihn vollständig an einem Stück umzusetzen.
> Dokumentiere deine Arbeit im work Verzeichnis wie dort üblicherweise Arbeitsakten geführt werden.
> Unterbrich deine Arbeit nicht für Fragen, sondern entscheide selbst im Sinne des Projektes.
> Bei den offenen Entscheidungen folgen wir Nummer 1 und 2 deinen Empfehlungen.

Damit gelten:

| Nr. | Entscheidung |
|---|---|
| 1 | Geführter Ablauf ist Standard; der **Expertenmodus** (freie Ansicht) ist jederzeit umschaltbar. |
| 2 | Bearbeitet wird die Belegung nur über **virtuelle Ordner**; native SDK-Folder bleiben Anzeige. Kein nativer FolderEditor. |
| 3 | Git-Repository auf GitHub: `https://github.com/marcosudau-vps/logi-plugin-studio` mit dem Branch-Schema unten. |

### Branch-Schema des Auftraggebers (zusammengefasst)

- `main`: je fertiger Release-Version **genau ein Commit**. Darf vorab nur mit einer README initialisiert werden.
- Release-Branch: zweigt von `main` ab und enthält **je Feature einen Commit**. Der Ausgangsstand kommt als
  Start-Commit auf den Release-Branch; bereits fertige Features werden nicht einzeln aufgeteilt.
- Feature-Branches zweigen vom Release-Branch ab; darunter Arbeitspaket-Branches (und beliebige weitere
  Arbeits-Branches), die in den Feature-Branch gemergt werden.
- Erst nach Freigabe und eigenen Tests durch den Auftraggeber wird der Release-Branch in `main` gemergt.

Umsetzung des Schemas: [04_git_und_branches.md](04_git_und_branches.md).

## 18.11.2026, 02:14 – Fortsetzung

> Bitte Jetzt die restlichen Stufen umsetzen. Bitte denke dran, eine Arbeitsakte wie im Ordner Work in diesem
> Projekt üblich zu führen und den Fortschritt fortlaufend zu dokumentieren, sodass dieser stets nachverfolgbar
> bleibt.
