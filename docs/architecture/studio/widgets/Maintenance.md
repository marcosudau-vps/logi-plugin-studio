# Wartung (MaintenanceDialog)

Stand: 18.11.2026 · AP-GUIDE-001 · Status: IMPLEMENTIERT / READY_FOR_REVIEW.

Nicht modales, **projektunabhängiges** Fenster. Erreichbar über *Werkzeuge → Wartung …* und die Startseite
des [geführten Ablaufs](WorkflowGuide.md). Deckt die Backlog-Punkte U-01 bis U-04 im sicher belegbaren Umfang ab.

## Funktionen

| Funktion | Umsetzung | Wirkt auf |
|---|---|---|
| Plugins anzeigen | vorhandenes `deployment.inventory()` + `installed_runtime_status()` | nur lesen; fremde Plugins grau, „fremd – wird nicht verändert“ |
| Plugin neu laden | vorhandenes `service.request_plugin_reload(name)` (SDK-Deep-Link) | nur das gewählte eigene Plugin |
| Protokoll anzeigen | vorhandenes `service.plugin_log_lines(name)`, letzte 24 Stunden | nur lesen |
| Deaktivieren | vorhandenes `workflow.uninstall(...)` mit Sicherungsbeleg; Eintrag in `deactivated.json` | eigenes Plugin; Bestätigung mit Options+-Hinweis |
| Reaktivieren | vorhandenes `restore_uninstalled(...)` aus dem Beleg, danach Reload nur dieses Plugins | eigenes Plugin |
| Voraussetzungen prüfen | vorhandenes `service.detect_prerequisites()` | nur lesen |

Alle Vorgänge laufen im vorhandenen `CallWorker` (kein Einfrieren der Oberfläche). Während eines Vorgangs
lässt sich das Fenster nicht schließen.

## Bewusst nicht enthalten

**Neustart des gesamten Logi Plugin Service.** Er beträfe alle Plugins und Geräte, und es gibt keinen belegten
sicheren Weg (das Studio beendet keine fremden Prozesse). Das Fenster sagt das ausdrücklich und verweist auf
„Plugin neu laden“ bzw. einen Neustart von Logi Options+ durch den Anwender.

## Eigentümer

| Wert | Eigentümer |
|---|---|
| Pluginordner, eigene Plugin-Dateien, Belege | vorhandene Installationsfunktionen (`deployment`, `directory_install`, `workflow`) |
| Liste deaktivierter Plugins | `studio.maintenance.model.DeactivationStore`, benutzerlokal `…\LogiPluginStudio\settings\deactivated.json`, Belege unter `…\maintenance-receipts\` |
| Installationsstatus des offenen Projekts | `DeploymentController`; die Wartung meldet Änderungen über `pluginChanged` |

Code: `src/studio/maintenance/{model,dialog}.py`, Host `workflow_controller.open_maintenance`. Kante V-107.
Tests: `tests/test_maintenance.py` (mit Attrappe der Installationsfunktionen) und
`tests/test_workflow_shell.py::test_v107…`. Die echten Installationsfunktionen sind durch ihre bestehenden Tests
und AP-RELEASE-FINAL-001/AP-POLISH-001 abgedeckt.
