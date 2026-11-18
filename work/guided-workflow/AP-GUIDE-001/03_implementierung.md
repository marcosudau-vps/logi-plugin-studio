# 03 – Implementierung

Je Stufe: was geändert wurde, warum es sicher ist und welche Entscheidungen fielen. Verbindungen stehen mit
Testfunktion im [Verbindungsregister](../../../docs/architecture/studio/04-Verbindungsregister.md).

## Grundprinzip

Der geführte Ablauf ist ein **Konstruktorschalter**: `NativeStudioShell(path, workflow=True)`. Nur
`studio.app.main --native` (und damit `LogiPluginStudio.exe`) schaltet ihn ein. Ohne den Schalter verhält sich
die Shell Byte für Byte wie in 1.0.0-rc1. Der Ablauf besitzt keine Projektdaten:

```text
NativeProjectSession / ExtensionStore / Problemliste / Build- und Installationszustand
        │  nur lesen
        ▼
WorkflowController.facts()  ──►  workflow.model.evaluate()  ──►  Schrittstatus
        │                                                           │
        ├─ Registerkarten, Seitenbereiche, Werkzeuge ein/aus         ├─ WorkflowRail (Anzeige)
        ├─ Führungsthemen → bestehende HelpRegistry (Quelle guide)   └─ offene Punkte → Problemliste (Quelle workflow)
        └─ Änderungen nur über vorhandene Shell-/Coordinator-Operationen
```

Benutzerlokal (`%LOCALAPPDATA%\LogiPluginStudio\settings\workflow.json`, Muster `build_mode_store.py`) werden nur
gemerkt: geführt/Expertenmodus, zuletzt aktiver Schritt, Pfad der Handlerdatei, bestätigter Gerätetest – je
Projektpfad und Plugin-ID. Die Projektdatei bleibt unverändert.

## Stufe 1+2 – Konzept und Gerüst

| Datei | Änderung |
|---|---|
| `docs/architecture/studio/widgets/WorkflowGuide.md` | neu: Schritte, Sichtbarkeitsmatrix, Kriterien, Bausteine |
| `src/studio/workflow/model.py` | neu, Qt-frei: `Facts`, `Step`, `Criterion`, `evaluate`, `guidance` |
| `src/studio/workflow/store.py` | neu: benutzerlokaler Ablaufzustand |
| `src/studio/workflow/facts.py` | neu: statische Handlerprüfung (AST, keine Ausführung), Bildreferenzen, Fingerabdruck, Handlervorlage |
| `src/studio/workflow/widget.py` | neu: `WorkflowRail` (Schrittknöpfe, nächster Handgriff, Zurück/Weiter, Checkliste, Expertenmodus) |
| `src/studio/workflow/start_page.py` | neu: Startseite für Schritt 1 |
| `src/studio/context_help/resources/guide_topics.de.json` | neu: zehn Führungsthemen |
| `src/studio/native_shell/workflow_controller.py` | neu: Host des Ablaufs |
| `src/studio/native_shell/window.py` | Schalter `workflow`, neue Operation `save_all()` |
| `src/studio/native_shell/build_controller.py` | leere Listen `guards`/`listeners` (ohne Einträge unverändertes Verhalten) |
| `src/studio/native_shell/delivery_panels.py` | `status_codes` (unveränderte Codes je Zeile) |
| `src/studio/app.py` | Programmeinstieg mit `workflow=True` |

Entscheidungen:

- **Build veraltet** wird über einen SHA-256-Fingerabdruck der gespeicherten Projektdatei, der `.vfolders.json`,
  der Handlerdatei und des Plugin-Typs erkannt. Der Fingerabdruck wird beim Buildstart genommen, nicht beim Ende.
- **Fehler, die den Build sperren**, sind nur Projektfehler (Quellen `native.validation`, `folders.references`).
  Bedienfehler früherer Aktionen (Quelle `open`, `save`, …) und die eigenen Hinweise (Quelle `workflow`) sperren
  nicht. Sonst könnte ein einmal fehlgeschlagener Build den nächsten dauerhaft blockieren.
- **Gerätetest** ist eine ausdrückliche Bestätigung des Anwenders, nie ein automatischer Nachweis. Sie gilt nur
  für den Build, der bei der Bestätigung installiert war.
- **Optionale Schritte** haben keine Pflichtkriterien und sind ohne Inhalt neutral („optional“). Ein eigener
  „Überspringen“-Knopf ist deshalb nicht nötig (Abweichung vom Plan, siehe unten).
- **Werkzeugleiste**: Standardbefehle mit Symbol (Neu, Öffnen, Alles speichern, Rückgängig, Wiederholen,
  Neu laden, Hilfe), die übrigen je Schritt. Die getrennten Befehle „Natives Projekt speichern“, „Extension
  speichern“ und „Neu laden“ erscheinen nur im Expertenmodus; im geführten Ablauf gibt es „Alles speichern“.

## Stufe 3a – HandlerInspector

Siehe [HandlerInspector.md](../../../docs/architecture/studio/widgets/HandlerInspector.md).
Neue Coordinator-Operationen `apply_handler_create`, `rename_handler`, `handler_delete_check`,
`delete_handler`: gleicher Guard wie bei Aktionen (Projekttoken, Revision, Disk-Baseline), genau ein
`NativeProjectSession.replace`. Die Handlerdatei wird nur einmal exklusiv angelegt (`open(..., "x")`).

## Stufe 3b – Übersichten

`src/studio/workflow/overviews.py`: Registerkarten **Zustände** (Schritt 3) und **Symbole** (Schritt 4), beide
nur lesend. Bearbeitet wird im vorhandenen Aktionsinspektor bzw. SymbolDesigner.

## Stufe 4 – Bauen und Installieren

- `DeploymentController.set_status_text()`: Der Ablauf schaltet deutsche Anzeigetexte ein; die Codes bleiben in
  `status_codes` und im Tooltip. Ohne Ablauf werden weiter die Codes gezeigt (Bestandstests unverändert).
- Beschriftungen „Installierte Plugins …“ und „Protokoll:“ über den bisher unbeschrifteten Bereichen (OP-11).
- Nach erfolgreichem Build eine verständliche Meldung statt `BUILD_PROVEN`; nach der Installation einmalig der
  Hinweis auf die Zuweisung in Logi Options+ und auf die Bestätigung des Gerätetests.

## Abweichungen vom Plan

| Plan | Umsetzung | Grund |
|---|---|---|
| Diagnose-Quelle `workflow.<schritt>` | eine Quelle `workflow` mit den offenen Punkten des aktiven Schritts | Die Problemliste soll zeigen, was jetzt zu tun ist, nicht alle künftigen Schritte. |
| Optionale Schritte ausdrücklich überspringen | ohne eigenen Knopf; optionale Schritte sperren nie | Ein Knopf ohne Wirkung wäre irreführend. |
