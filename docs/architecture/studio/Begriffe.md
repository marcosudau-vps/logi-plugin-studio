# Begriffsliste der Oberfläche

Stand: 18.11.2026 · AP-GUIDE-001. Ein Wort je Sache in allen sichtbaren Texten (Beschriftungen, Meldungen,
Hilfe). Technische SDK-Namen bleiben dort stehen, wo sie die native Semantik bezeichnen (ARCH-ADR-001), und
werden beim ersten Auftreten erklärt.

| Sache | Begriff in der Oberfläche | Nicht mehr verwenden | Technischer Name (bleibt in Code, Dateien, Tooltips) |
|---|---|---|---|
| Plugin-Funktion, die auf eine Taste gelegt wird | **Aktion** (Mehrzahl Aktionen), **Aktions-ID** | Action, Action-ID | `NativeAction`, `actions[]`, `action.id` |
| Aktionstypen | **Befehl**, **Schalter mit Zuständen**, **Regler**, **Aktion mit Einstelldialog** | Mehrzustand, Action-Editor | `PluginDynamicCommand`, `PluginMultistateDynamicCommand`, `PluginDynamicAdjustment`, `ActionEditorCommand` |
| Python-Einsprungpunkt | **Handler**, **Handlerdatei** | Callback-Vorlage | `handlers[]`, `register(host)` |
| Datei des Projekts | **Projekt** | natives Projekt (in Befehlen) | `logitech-native-1` |
| Datei der virtuellen Ordner | **Ordner** (in Befehlen: „Ordner speichern“, „Rückgängig (Ordner)“) | Extension (in Befehlen) | `<Projekt>.vfolders.json`, `ExtensionStore` |
| Beide Dateien speichern | **Alles speichern** | – | `NativeStudioShell.save_all` |
| Zustand eines Schalters | **SDK-Zustand** | State | `states[]`, `state_change` |
| Vom eigenen Code geführter Wert | **Python-Zustand** | – | Laufzeitwerte, nicht im Projekt |
| Bildvorlage einer Taste | **Symbol**, **Symbolvorlage** | Icon (in Texten) | `.ict`, `icon_template` |
| Status der Installation | deutsche Statuswerte, z. B. „installiert“, „geladen“, „aktiv“, „noch nicht am Gerät getestet“ | `INSTALLED`, `LOADED`, `ACTIVE`, `HARDWARE_PENDING` (nur im Tooltip) | `DeploymentController.status_codes` |
| Ergebnis des Builds | „Build erfolgreich“, „veraltet“ | `BUILD_PROVEN` | Build-Ergebnis |
| Freie Ansicht | **Expertenmodus** | – | `WorkflowController.expert` |

## Umgesetzt

- Sichtbare Texte des nativen Studios: „Action“ → „Aktion“ in Meldungen, Beschriftungen und in den Hilfethemen
  (Feldbeschreibungen; Themen-IDs unverändert). Befehle: „Projekt öffnen …“, „Projekt speichern“,
  „Ordner speichern“, „Rückgängig/Wiederholen (Projekt|Ordner)“, „Anzeigename ändern“.
- Statuswerte der Installation und Build-Meldung im geführten Ablauf auf Deutsch.

## Bewusst unverändert

- Der Aktionskatalog zeigt unter jeder Aktion weiter den SDK-Typnamen (z. B. `PluginDynamicCommand`). Er ist Daten-
  und Filtergrundlage des abgenommenen Widgets; die Klartextnamen stehen in der Registerkarte „Zustände“, im
  Handbuch und in der Hilfe „Schritt 3: Aktionen“.
- „SDK-Folder“, „DynamicFolder“, „Shared DynamicFolder“: Namen der nativen SDK-Konzepte.
- Der Legacy-Editor (`0.1-draft`) bleibt sprachlich unverändert.
