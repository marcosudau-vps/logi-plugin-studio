# Geführter Ablauf (WorkflowGuide)

Stand: 16.11.2026 · AP-GUIDE-001 · Status: IMPLEMENTIERT / READY_FOR_REVIEW (keine Selbstabnahme).

Der geführte Ablauf macht aus der freien Tab-Sammlung des nativen Studios einen Prozess in sieben
Schritten. Er ist eine **optionale Komfortschicht oberhalb des SDK-nativen Modells**
([ARCH-ADR-001](../../../decisions/ARCH-ADR-001.md), Punkt 3) und besitzt keine Projektdaten.

## Grundsätze

- **Kein neues Fachmodell.** Der Schrittstatus wird bei jeder Änderung aus Fakten berechnet, die der Host aus
  den bestehenden Eigentümern liest. Er wird nie in der Projektdatei oder der `.vfolders.json` gespeichert.
- **Schreibhoheit unverändert.** `NativeProjectSession` bleibt einziger Writer des nativen Projekts,
  `ExtensionStore` der Extension. Der Ablauf ruft ausschließlich vorhandene Host-Operationen auf.
- **Eine Hilfe, eine Problemliste.** Führungstexte sind Themen der Quelle `guide` in der bestehenden
  `HelpRegistry`; nicht erfüllte Kriterien erscheinen als Quelle `workflow` in der bestehenden Problemliste.
- **Abschaltbar.** `NativeStudioShell(path)` verhält sich ohne das Argument `workflow=True` exakt wie bisher
  (alle bisherigen Tests, Labs und die Automatisierung). Die Programmeinstiege starten mit `workflow=True`.
- **Expertenmodus.** Im Ablauf lässt sich jederzeit auf die freie Ansicht umschalten; native Funktionen
  bleiben damit auch ohne Komfortschicht erreichbar. Die Wahl wird benutzerlokal gemerkt.

## Schritte, Sichtbarkeit und Abschlusskriterien

| Nr. | Schritt | Registerkarten | Seitenbereiche | Sperrende Kriterien |
|---|---|---|---|---|
| 1 | Projekt | Start, Hilfe | – | Projekt geöffnet; Plugin-ID und Anzeigename vergeben |
| 2 | Handler | Handler, Probleme, Hilfe | Projektübersicht | mindestens ein Handler; Handlerdatei zugeordnet und gültig |
| 3 | Aktionen | Aktionsinspektor, Zustände, Details, Probleme, Hilfe | Projektübersicht, Aktionskatalog | mindestens eine Aktion; jede Aktion mit gültigem Handler; kein offener Entwurf |
| 4 | Darstellung (optional) | Symbole, Aktionsinspektor, Probleme, Hilfe | Aktionskatalog | keine (fehlende Bilder sind Hinweise) |
| 5 | Belegung (optional) | Keypad, Virtuelle Ordner, Probleme, Hilfe | Aktionskatalog | keine verwaisten Platzierungen; Extension gespeichert |
| 6 | Prüfen und Bauen | Probleme, Plugin-Build, Hilfe | – | alles gespeichert; 0 Fehler; Voraussetzungen vorhanden; Build erfolgreich und aktuell |
| 7 | Installieren und Testen | Installation, Shared-Peers (nur Plugin-Typ Shared), Hilfe | – | Paket gültig; installiert und aktuell; geladen und verbunden; Gerätetest bestätigt |

Regeln:

- Ein Schritt ist erst erreichbar, wenn alle vorherigen abgeschlossen sind. Zurück geht es jederzeit.
- Status je Kriterium und Schritt: erfüllt, offen, Hinweis, Fehler, veraltet, optional, gesperrt – immer als
  Text und Zeichen, nie nur als Farbe.
- Eine spätere Änderung löscht nichts. Weicht der gespeicherte Stand vom gebauten ab, wird der Build
  „veraltet“; ist ein älterer Build installiert, wird die Installation „veraltet“.
- Optionale Schritte haben keine Pflichtkriterien und sperren nur bei echten Fehlern.
- **Belegung nur über virtuelle Ordner** (Entscheidung vom 16.11.2026): Im geführten Ablauf zeigt die
  Tastenvorschau ausschließlich das virtuelle Autorenmodell; die Quellenauswahl ist gesperrt, und beim Betreten
  von Schritt 5 ist „Bearbeiten“ eingeschaltet. Native SDK-Folder des Projekts bleiben unverändert und sind im
  Expertenmodus als Anzeige erreichbar. Es gibt keinen Editor für native Platzierungen.
- Im geführten Modus verweigert „SDK-Plugin bauen“ den Start, solange „Alles gespeichert“ oder
  „Keine Fehler“ nicht erfüllt ist.

## Bausteine

| Baustein | Code | Aufgabe |
|---|---|---|
| Schrittmodell | `src/studio/workflow/model.py` | Qt-frei: `Facts` → `evaluate()` → `StepState` mit `Criterion` |
| Benutzerlokaler Zustand | `src/studio/workflow/store.py` | Modus, zuletzt aktiver Schritt, Handlerdatei, bestätigter Gerätetest je Projektpfad und Plugin-ID |
| Schrittleiste | `src/studio/workflow/widget.py` | Sieben Schritte mit Status, Checkliste des aktiven Schritts, nächster Handgriff, Zurück/Weiter |
| Startseite | `src/studio/workflow/start_page.py` | Einstieg: Neues Projekt, Projekt öffnen, Projektangaben |
| Host | `src/studio/native_shell/workflow_controller.py` | Fakten lesen, Sichtbarkeit setzen, Hilfe und Problemliste versorgen |

Fakten und ihre Quelle: Projekt/Handler/Aktionen aus `NativeProjectSession.snapshot()`; Entwurf aus dem
Aktionsinspektor; verwaiste Platzierungen aus `ExtensionStore.document.missing_actions()`; Fehlerzahl aus der
Problemliste (ohne Quelle `workflow`); Voraussetzungen aus `NativeBuildController.quick_prerequisites()`;
Build aus `NativeBuildController.last_result` mit Fingerabdruck der gespeicherten Dateien; Installation aus
`DeploymentController.state`.

## Verbindungen

Die Kanten V-90 bis V-106 stehen mit Testfunktion im [Verbindungsregister](../04-Verbindungsregister.md).
