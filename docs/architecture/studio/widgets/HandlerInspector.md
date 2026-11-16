# HandlerInspector

Stand: 16.11.2026 · AP-GUIDE-001 · Status: IMPLEMENTIERT / READY_FOR_REVIEW.

Registerkarte **Handler** (Schritt 2 des [geführten Ablaufs](WorkflowGuide.md)). Schließt die Lücke, dass
Handler bisher nur als Auswahlfeld im Aktionsinspektor existierten.

## Verhalten

- Tabelle aller Handler mit Verwendung („n Aktion(en)“) und Zustand in der Handlerdatei.
- **Neuer Handler**, **Umbenennen** (stellt alle Aktionen im selben Commit mit um), **Löschen** (nur
  unbenutzte Handler; der letzte Handler bleibt geschützt).
- **Handlerdatei aus Vorlage erzeugen**: legt `<Projektname>_handlers.py` neben dem Projekt an und ordnet sie zu.
  Eine vorhandene Datei wird nie überschrieben, sondern nur zugeordnet. Danach ändert das Studio die Datei nicht mehr.
- Statische Prüfung (AST, keine Ausführung): Die Datei muss `register(host)` enthalten. Registriert sie einen
  Handler, den keine Aktion verwendet, würde der Plugin-Host nicht starten (`HANDLER_ENDPOINT` in
  `runtime/host.py`) → **Fehler**, sperrt. Fehlt die Registrierung eines verwendeten Handlers → **Hinweis** mit
  einfügbarem Code-Abschnitt.

## Eigentümer

| Wert | Eigentümer |
|---|---|
| `handlers[]` und `actions[].handler` | `NativeProjectSession` über `StudioCoordinator.apply_handler_create / rename_handler / delete_handler` (je genau ein `replace`, Revisions-/Projekttoken-/Disk-Guard wie bei Actions) |
| Pfad der Handlerdatei für den Build | Feld im Tab Plugin-Build (`NativeBuildController.handler`); benutzerlokal je Projekt gemerkt (`WorkflowStore`) |
| Inhalt der Handlerdatei | der Anwender; Studio legt sie höchstens einmal neu an |

Code: `src/studio/handler_inspector/{lifecycle,widget}.py`, Host `src/studio/native_shell/workflow_controller.py`.
Kanten V-100 bis V-102 im [Verbindungsregister](../04-Verbindungsregister.md). Tests: `tests/test_handler_inspector.py`.
