# Logitech Plugin Studio – Widget-Landkarte und Schnittstellen v0.1

**Status: Architekturvorschlag zur gemeinsamen Freigabe, kein Codemigrationsauftrag.**
**Stand:** 04.11.2026.
**Projektroot:** `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture`

## 1. Richtungsentscheidung und tatsächlicher Ist-Stand

- Verbindlich: `docs/decisions/ARCH-ADR-001.md` – **Native First / Minimal Bridge / Optional Extensions**. Kein SDK-unabhängiges Pflichtmetamodell, keine doppelten SDK-States oder Renderer-Wahrheiten.
- SDK-nativer Softwarepfad: `src/adapters/logitech/native.py`, `src/adapters/logitech/product.py`, `src/runtime/`. `0.1-draft` bleibt als kompatibler Altbestand bestehen.
- Bereits vorhanden: `SymbolDesignerWidget` (`src/symbol_designer/widget.py`, natives ICT); die NF-16-Projektanbindung (`src/studio/native_ict_binding.py`, `native_symbol_dialog.py`); `src/studio/keypad_contract.py` mit `NavigationCapability`, `SlotData`, `KeypadFrame`, `KeypadViewState` und `preview` als Standard.
- Bestehendes `StudioWindow` (`src/studio/app.py`) hat bisher ein einfaches `render_preview` mit simuliertem 8+Back-Layout. Diese Simulation ist keine SDK-Capability und wird im späteren Integrationstask ersetzt, **nicht** von AP-WIDGET-002 unmittelbar umgebaut.
- Bisher noch **nicht** implementiert: isoliertes `KeypadPreviewWidget` und sein Lab. Originale 657×724-Keypad-PNGs sind in `assets/ui/keypad/logikeypad/` derzeit **nicht vorhanden**; technischer Entwurf/Koordinaten existieren jedoch unter `work/planning/keypad-preview-widget-technischer-entwurf-v01.md`. Deshalb Fallback zwingend; keine selbst erstellten Logitech-Markenbilder.
- Frühere Widget-/UI-Entwürfe bleiben Diskussionsgrundlage, sind kein konkurrierender nativer Vertrag.

## 2. Grundmodell: Hauptfenster + Koordinator + unabhängige Widgets

```text
StudioWindow / StudioShell – globale Navigation, Projekt, Arbeitsbereiche
├── linke Navigationsspalte
│   ├── ProjectExplorerWidget – Plugin → Folder / Action / Handler
│   └── ActionCatalogWidget – externe Action-Angebote, Suche, Drag-Quelle
├── zentrale Arbeitsfläche – nach Kontext austauschbare Widgets
│   ├── KeypadPreviewWidget – eine SDK-gemappte Seite, Tasteninteraktion
│   ├── SymbolDesignerWidget – native ICT-Bearbeitung (FERTIG)
│   ├── FolderEditorWidget – logische SDK-Ordner-/Placement-Liste
│   ├── ActionEditorDesignerWidget – SDK-native Action-Editor-Controls
│   └── optional: Connection/State-/Handler-Ansichten
├── rechter Kontext-Inspector
│   ├── ActionInspectorWidget – SDK-Action-Parameter und Eigenschaften
│   ├── StateInspectorWidget – nativer Multistate vs. externer Python-State
│   ├── HandlerInspectorWidget – Python-Callback, minimale Bridge
│   └── ContextHelpWidget – kontextabhängige Erklärung
└── unterer Statusbereich / eigene Arbeitsbereiche
    ├── ProblemsPanelWidget – Validierung mit navigierbarem Befund
    ├── BuildAndTestWidget – SDK-Build, Prozessprobe, Hardwarebelege
    └── PluginMaintenanceWidget – bewusst getrennte, abgesicherte Wartung

                   alle Anzeigen/Intents
                           │
                           ▼
     schlanke Studio-Koordination (kein Ersatzprojektmodell)
      ├── Auswahl und aktive SDK-Action-/Folder-Identität
      ├── gültige, unveränderte Daten-/Revision-Snapshots
      ├── Änderungsabsicht prüfen + echte Projekt-/ICT-Writer aufrufen
      ├── Gerät-/SDK-Capabilities, echte Page-/Slotzuordnung
      └── benötigte Widgets nach Commit gezielt aktualisieren
                           │
           ┌───────────────┴─────────────┐
           ▼                             ▼
  Logitech-native Verträge       optionale Python Host/Bridge
   / Datei / SDK-Generator       (nur für externe Handler/Statewerte)
```

Die Koordination ist zunächst ein **Verantwortungsschnitt**: nicht sofort ein eigenes Service-/Gateway-Framework erzeugen. Vorhandene Funktionen wiederverwenden und nur fehlende Anwendungskopplung ergänzen.

## 3. Widget-Inventar und Priorisierung

| Widget/Bereich | Verantwortet | Schnittstelle | Stand / Umsetzung |
|---|---|---|---|
| `SymbolDesignerWidget` | Native ICT (Text/Bild/Layout, Import/Export) | `load_template`, `apply`, `ict_bytes`; Studio-Binding übernimmt Persistenz | Vorhanden; NF-16 verbunden |
| `KeypadPreviewWidget` | Ein physisches Gerätebild, Slotanzeige, Hover/Press, Selektion, Edit-Kontextmenü, lokale Clipboard-Intents | `KeypadFrame`/`KeypadViewState`; typisierte `SlotAddress`/`EditRequest`-Signale | **Als nächstes AP-WIDGET-002** |
| `ActionCatalogWidget` | Vorhandene SDK-Aktionen suchen, auswählen, zum Keypad ziehen | flüchtiges `ActionOffer` (`action_id`, `action_parameter`, QImage), kein eigener Katalog-Owner | Danach |
| `ProjectExplorerWidget` | SDK-Plugin, Action, Folder, Handler navigieren | native IDs, Selektion | Bestehendes TreeWidget als Grundlage |
| `FolderEditorWidget` | Logische Placements/Folder, mehrere Seiten/Geräte, Sortierung | echter SDK-Folder-Descriptor, Bearbeitungsrequests | Danach |
| `ActionInspectorWidget` | Action-typbezogene Eigenschaften und native Parameter | SDK-`NativeAction`, geprüfte Update-Operation | Danach |
| `StateInspectorWidget` | Native Multistate-Definition separat vom Python-State anzeigen | State-Descriptor + optionale Runtime-Lesedaten | Danach |
| `HandlerInspectorWidget` | Python-Handlerzuordnung; Bridge-Status | vorhandene Handler-/Runtime-API | Danach |
| `ActionEditorDesignerWidget` | Native Options+-Konfigurationscontrols (NF-11 derzeit 7 Typen) | echte SDK-Editor-Controls; fehlende Special-Controls als Capability-Gap | Danach |
| `ProblemsPanelWidget` | Diagnostics, Navigation zu Action/Folder/Datei | bestehende Validator-Diagnostics | Bestehende Tabelle als Grundlage |
| `BuildAndTestWidget` | SDK-Build, Softwareprobe, Gerätebeleg, Export | bestehende Worker, kein Start durch Keypad-Klick | Bestehender Tab als Grundlage |
| `PluginMaintenanceWidget` | Eigene Plugin-Installationen, gesicherte Aktionen und Logs | bestehende abgesicherte Deployment-Operationen | Später, getrennt vom Autoreneditor |

**Kein künstlicher Pflicht-Inspector pro Property**: die Widgets in der rechten Spalte können als ein Kontext-Inspector mit austauschbaren Teilansichten realisiert werden. Ebenso kein großer Widget-Basisklassenbaum.

## 4. Verbindliche Datenfluss- und Eigentümergrenzen

```text
NativeProject/SDK + Projektdatei + Runtimewerte (falls relevant)
                        |
         Projekt-/Geräte-spezifischer Coordinator
                        |
       fertige, flüchtige KeypadFrame/SlotData/QImage
                        |
                KeypadPreviewWidget
              ⇢ slotSelected(SlotAddress)
              ⇢ pageRequested(page_index)
              ⇢ symbolEditRequested(SlotAddress)
              ⇢ editRequested(EditRequest)
                        |
              Koordinator validiert:
             SDK Action/Placement/Parameter,
             Revision, Ziel-Capabilities, erlaubte Operation
                        |
          zulässige native SDK-Projektoperation
             + neuer Frame/Revision ans Widget
```

- **Eine Action ist keine Taste:** `action_id` referenziert die native SDK-Aktion; `placement_id` referenziert genau ihre Position. Derselbe Action-/Parameterbezug kann mehrfach erscheinen, ohne die Action zu duplizieren.
- **`action_parameter` bleibt getrennt** von `action_id`, `placement_id` und physischer Taste. Es wird niemals still aus der Position abgeleitet.
- **`physical_index` ist keine logische Projektposition** und keine generell gültige 8+Back-Rechenregel. Gerät-/SDK-Navigation sowie Page-Mapping werden außerhalb des Widgets aufgelöst.
- **`KeypadFrame.revision` ist Host-/Projekt-Snapshot-Identität**, keine Version des SDK-State; nicht auf eigene Weise erzeugen oder direkt in die Projektdatei schreiben.
- **`tile_image: QImage` ist fertige Qt-Ausgabe**, keine persistierte Wahrheit. SymbolDesigner bleibt Eigentümer der ICT-Semantik; der SDK-Adapter besitzt native Bild-/Caption-Kanäle.
- **Widget hält lokale UI-Zustände**, z. B. Hover, Press, Selection, Cut/Copy-Clipboard. Niemals Projekt-/SDK-/Python-Host-State als zweite Autorität.
- **Host ist alleiniger Commit-Owner.** Kein Widget ruft `ProjectDocument.mutate`, `NativeIctCoordinator.save` oder SDK-Operationen automatisch. Ausnahme: der explizit als Editor geöffnete SymbolDesigner-Hostdialog hat seinen bereits bestehenden, bewusst sichtbaren Speichern-Knopf.
- **Kein Widget-to-Widget-Direktzugriff:** Keypad sendet `symbolEditRequested`; Host öffnet `NativeSymbolDesignerDialog.select_slot(...)` bzw. aktionsbasierten Editor.
- **Preview ist Standard und niemals mutierend.** Edit-Modus muss ausdrücklich gesetzt und separat vom Host erlaubt werden. Keine verborgenen Menu-/Keyboard-/Drop-Edits im Preview.

## 5. Konkreter AP-WIDGET-002-Schnittstellenvorschlag

**Bereits implementierte Eingangstypen beibehalten** (keine neuen parallelen DTO-Namen):
`src/studio/keypad_contract.py`:
`NavigationCapability(device_type,area,content_slots,navigation_slots)`;
`SlotData(physical_index,role,placement_id,action_id,action_parameter,label,tile_image,editable)`;
`KeypadFrame(context_id,view_id,revision,capability,slots)`;
`KeypadViewState(frame,mode="preview")`.

Kleine, **additive** Ergänzungen mit Standardwerten, nur falls direkt benötigt und regressionsgetestet:
- `KeypadFrame.page_index: int = 0`, `page_count: int = 1` für externe Navigation; `page_count >= 1`, `0 <= page_index < page_count`.
- `SlotData.logical_position: int | None = None`, `tooltip: str = ""`, damit Anzeige und Drop-Intents nicht Positionen erraten; nur Anzeige, nicht Pflicht für bestehende Aufrufer.
- `SlotAddress(view_id,page_index,physical_index,placement_id?)` als flüchtige Quell-/Zieladresse.
- `ActionOffer(action_id,display_name,action_parameter?,tile_image?)` nur für externen Action-Picker/Drag. In alten Entwürfen `component_id` genannt; **native Canonical-ID heißt jetzt `action_id`**.
- `EditRequest(request_id,base_revision,operation,source?,target?,action_id?,action_parameter?)`; Operation `move|copy|place|remove`. Kein `replace`/Swap ohne spätere Freigabe.

**Widget-Eingänge:** `set_frame(KeypadFrame)`, `set_mode("preview"|"edit")`, `set_edit_allowed(bool)`, `set_selection(SlotAddress|None)`, `set_skin(...)`, `set_motion_enabled(bool)`, optional `set_action_offers(...)`. Keine Projektdateipfade, Auth-Tokens oder Callback-Klassen.

**Widget-Ausgänge (PySide6 Signal(object)):**
`slotSelected(SlotAddress)`, `pageRequested(int)`,
`symbolEditRequested(SlotAddress)`, `editRequested(EditRequest)`,
`undoRequested()`, `redoRequested()`. Navigation ist eine Anfrage; neuer Frame kommt **vom Host**, nicht als lokale automatische Speicheränderung.

**Kontextmenü ist intern** (Edit-Modus): Ausschneiden, Kopieren, Einfügen, Löschen, „Symbol bearbeiten“, bei Bedarf Undo/Redo. **Nur „Symbol bearbeiten“** gibt einen Editor-Öffnen-Intent ab; alle Placement-Bearbeitungen gehören als UI-Funktionen ins Widget, werden aber durch `editRequested` **extern committed**. Cut/Copy sind zunächst lokale Markierungen; Cut ohne Paste löscht nichts. Ein belegtes Paste-Ziel wird nicht ohne Host-Freigabe überschrieben.

**Drei-Punkte-Menüs** nur sichtbar, wenn `mode=="edit"` und `edit_allowed==True` und der Slot fachlich bearbeitbar ist. Im Preview keine Cut/Copy/Paste/Delete-/Symbol-Edit-Tastenkürzel, kein Drop als Mutation.

**Drag & Drop:** intern Move, optional Copy mit Modifier; extern eine ActionOffer-Referenz `application/vnd.logi-plugin-studio.action-ref+json`, nur versionierte Datenreferenzen und Hostvalidierung. Keine Python-Pickles/exec/Callback-Objekte und keine stillen Deletes.

**Entscheidende Trennung:** Das Widget erzeugt pro Operation eine Anfrage mit `base_revision`; es zeigt den Zustand erst als übernommen, wenn ein neues `KeypadFrame` der zuständigen Koordination ankommt. Fehlgeschlagene/alte Anfragen ändern den autoritativen Frame nicht.

## 6. Darstellung, Skin und Pagination

- **Eine Seite, eine Geräteansicht** pro Widgetinstanz. Kein Picker links/rechts; Picker in separaten Widgets oder im Lab-Host.
- Neutraler 3×3-Skin **immer** verfügbar; 657×724-LogiKeypad-Skin nur, wenn echte Nutzerassets im Projekt vorhanden sind. Kein Marken-Asset nachbauen oder aus fremden Quellen herunterladen.
- Optionaler Skin nutzt die aus dem technischen Entwurf ermittelten neun Taste-Rechtecke (Alpha-Bounds, keine fertigen Hit-Polygone). Gehäuse über den eigenen Tastenebenen, Inhaltsbild innerhalb der inneren Anzeigefläche.
- Hover, Selektion, Druck, Fokus sind unabhängig; Taste samt Inhalt beim Press ca. `0.97` Skalierung um ihre eigene Mitte; das Gehäuse und andere Tasten bleiben ruhig. Ein Klick ist **niemals** ein SDK-Command.
- `NavigationCapability` bestimmt, welche physischen Indizes Inhalt bzw. SDK-Navigation tragen. `KeypadFrame` kann verschiedene Slots pro Device melden; unbekannte Slots nicht als editierbar annehmen. Keine Annahme „9 Inhaltsfelder“.
- Pagination kann angezeigt werden, solange `page_index/page_count` vom Host stammen. Klick auf nächste Seite sendet `pageRequested`; Widget berechnet **keine** nativen Placementpositionen aus `page_index`.
- Skript und Gerätedienst sind fürs Lab **nicht** erforderlich. Kein Login/Install/Keypad-Eingriff.

## 7. Zusammensetzung als Beispiel

```text
[ProjectExplorerWidget]     [KeypadPreviewWidget]        [ActionInspectorWidget]
[ActionCatalogWidget]       - aktueller Folder            - gewählte native Action
                             - Seite 2 / 3                 - Parameter, State
                             - neun sichtbare Tasten       - [Symbol bearbeiten]
                             - Bild / Hover / DnD          - Details / Hinweise
                                  |
                   symbolEditRequested(SlotAddress)
                                  |
                         Studio-Koordination
                                  |
                   NativeSymbolDesignerDialog (bereits fertig)
                        liest/ändert echte .ict
```

Spätere separate `KeypadLayoutHost/Coordinator`-Integration ersetzt nur die alte Studio-Vorschau und verbindet ProjectExplorer/ActionCatalog/Inspector. **AP-WIDGET-002 darf diese Komponenten noch nicht implementieren oder bestehendes `StudioWindow` refaktorieren.**

## 8. Parallelität, Prüf- und Dokumentationsregeln

- Vor Arbeiten Basis-Snapshot, Protokoll geänderter Dateien, keine Arbeiten in `src/symbol_designer/`, `src/adapters/logitech/`, `src/runtime/`, Projekt-Schemas oder Studio-Hauptfenster.
- Neues Widget + Lab unter `src/studio/keypad_preview/`, `tools/run_keypad_preview_lab.py`, `tests/test_keypad_preview_widget.py` und `work/widget-lab/keypad-preview-v1/`. Nur nötige additive DTO-Felder in `src/studio/keypad_contract.py`.
- Bestehende `tests/test_keypad_contract.py` und NF-16-Integrationstests müssen weiterhin grün sein.
- Abarbeitung in einem Agentenlauf bis `READY_FOR_REVIEW`; alle GUI-, DnD-, Kontextmenü-, Accessibility- und Fallback-Tests im Lab ausführen. Unabhängige Abnahme ist keine Eigenbewertung des Agenten.
- Wenn Nutzer-Skin-Dateien fehlen, neutraler Skin fertig implementieren und dokumentierte Option für echte PNG-Assets lassen. Nicht deshalb den restlichen Auftrag blockieren.

**Architekturreife:** Diese v0.1 ist eine konkrete Schnittstellenbasis für den isolierten Keypad-Agenten; die gesamte spätere Studio-Informationsarchitektur bleibt anpassbar, ohne den SDK-nativen Vertrag zu verändern.


> **Visuelle Erkenntnis vom 04.11.2026:** Die 657×724-Originalgrafiken liegen außerhalb des Studio-Projektroots unter `P:\LokaleProjekte\logi_actions_sdk\graphics_pictures\KeypadPreviewWidget\graphics_logi_keypad`; sie sind nicht generell fehlend. Siehe den [gezielten Nachbesserungsauftrag](AP-WIDGET-002-visuelle-korrektur-v02.md) zur realistischen Gehäuse-/Tasten-/Paginationdarstellung. Die neutrale Lab-Grafik ist nur Fallback und keine visuelle Produktabnahme.
