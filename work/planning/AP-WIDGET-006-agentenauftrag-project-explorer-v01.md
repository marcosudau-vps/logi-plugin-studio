# AP-WIDGET-006 – NativeProjectExplorerWidget v1
## Vollständiger, unabhängig ausführbarer PySide6-Implementierungsauftrag

**Projekt:** `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture`  
**Status:** PREPARED – nicht gestartet.  
**Ziel:** Eigenständiger, ausschließlich lesender, filterbarer Qt-Projektbaum für **native SDK-Plugin-Projekte**, der über stabile IDs Auswahl-/Navigationsintents an einen späteren Host meldet. **Nicht** die Logitech-eigenen Anwendungsprofile (`ProfileInfo.json`) visualisieren.

## 1. Pflichtlektüre / konkreter Ist-Zustand

1. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\docs\decisions\ARCH-ADR-001.md` (Native First)
2. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\docs\specifications\logitech-profil-und-aktionsmodell-basis-v02.md` (Profil-/Action-Begriffe)
3. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\work\planning\modell-und-parallelentwicklung-nach-ap-prof-001-v01.md` (Reihenfolge und Grenzen)
4. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\work\planning\widget-gesamtarchitektur-und-schnittstellen-v01.md` (Projektbaumrolle; frühere Planungsstände im Konfliktfall nicht normativ)
5. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\adapters\logitech\native.py` (`NativeProject`, `NativeAction`, `NativeFolder`, `NativeFolderEntry`, `NativeParameter`, `NativeState`)
6. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\action_catalog\widget.py` (bestehender Katalog – **nicht duplizieren**)
7. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\keypad_contract.py` (Placements/IDs und transienter View-Zustand)
8. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\context_help\entries.py` (optionale HelpContext-IDs, kein Plugin-Modell)
9. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\examples\project_logitech_native_v1.json` (vier SDK-Action-Typen, ein Handler, ein NativeFolder mit Entries)
10. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\work\acceptance\20261104-keypad-catalog\ABNAHME.md` (Qt-Widget-Abnahmemuster)
11. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\app.py` (existierender generischer Baum des **0.1-draft**; darf nicht verändert werden).

Der unabhängige Agent **AP-STUDIO-001** kann gleichzeitig eine native Dokument-Session entwickeln. Dieses Widget darf **weder auf die künftige Session importieren noch deren Code bearbeiten**. Als Input reicht allein das bestehende `NativeProject`.

## 2. Exakte Schreibgrenzen

**Ausschließlich neue Dateien erstellen**:
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\native_project_explorer\__init__.py`
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\native_project_explorer\widget.py`
- falls nötig private Qt-Helpers im selben neuen Paket
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\tests\test_native_project_explorer_widget.py`
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\tools\run_native_project_explorer_lab.py`
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\work\widget-lab\native-project-explorer-v1\README.md`
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\work\widget-lab\native-project-explorer-v1\evidence` für Screenshots, Testprotokolle und nachvollziehbare UI-Belege.

**Verbotene Änderungen:** `src/studio/app.py`, `src/studio/native_session.py`, `src/adapters/`, `src/runtime/`, `src/library/`, `schemas/`, bestehende Widgets, `src/symbol_designer/`, bestehende Tests, Logitech-Service, `ProfileInfo.json`, Forschungsrepository. Kein SDK-Plugin erzeugen, starten oder installieren. Keine QML-Oberfläche, keine kommerziellen Abhängigkeiten.

## 3. Fachliche Verantwortung

- `ProjectExplorerWidget` zeigt **nur das aktuell vom Host gelieferte `NativeProject`** und verhält sich selbst rein lesend.
- Er liefert Überblick und Navigation: **Plugin → Aktionen, Handler, Dynamic Folders → Folder Entries**. Er ist **nicht** der Aktionskatalog; der `ActionCatalogWidget` bleibt Drag-Quelle/Picker.
- **Aktion vs. Platzierung:** eine `NativeAction` existiert einmal, kann aber in mehreren Folder Entries referenziert sein. Die Folder-Entry-ID ist `NativeFolderEntry.id`; eine geöffnete Folder-Entry-Zeile ist **keine neue Aktion**.
- **Handler:** `NativeAction.handler` referenziert den Handler-Datensatz mit `id`, `callback_id`. Keinen Python-Code introspektieren/ausführen.
- **SDK Dynamic Folder:** `NativeFolder` im Projektvertrag ist nicht Logitech `ProfileInfo.json`-`folderPages`; keine Workspaces/General-/App-Profile in diesen Baum erfinden.
- Als verlässliche IDs ausschließlich `NativeProject.plugin_id`, `NativeAction.id`, Handler-`id`, `NativeFolder.id`, `NativeFolderEntry.id` nutzen. Keine eigenständigen persistenten UUIDs, keine Positions-/String-IDs, keine selbst erfundene Geräteprofilzuordnung.

## 4. Widget-Schnittstelle

Erstelle folgende schmale öffentliche API:

```python
class NativeProjectExplorerWidget(QWidget):
    nodeSelected = Signal(str, str)
    # (node_kind, native_id) – NUR durch tatsächliche Benutzerauswahl.

    nodeActivated = Signal(str, str)
    # Doppelklick/Enter: ausdrücklicher Navigations-/Öffnen-Intent.

    def set_project(self, project: NativeProject | None, *, revision: str | None = None) -> None: ...
    def set_selection(self, node_kind: str, native_id: str) -> bool: ...
    def set_filter(self, text: str) -> None: ...
    def clear(self) -> None: ...
```

`node_kind`: `"plugin"`, `"action"`, `"handler"`, `"folder"`, `"folder_entry"`. Gruppenknoten (`Aktionen`, `Handler`, `Dynamic Folders`) sind optisch navigierbar, aber dürfen keinen falschen Entity-ID-Intent emittieren.

`revision` ist eine **opake Host-Angabe**, ausschließlich für spätere Korrelation/Anzeige, nicht aus dem SDK berechnet. Der Host/Coordinator verwaltet Revision und Navigationsziel – dieses Widget ruft keine anderen Widgets direkt auf. `set_project(None)` leert den Baum und jede veraltete Selektion.

Wenn `set_selection` auf eine nicht vorhandene ID zeigt, darf keine Phantom-Selektion entstehen und kein Signal emittiert werden. Programmgesteuertes Auffrischen/Filtern löst **keine** Benutzer-Navigationssignale aus. Für `set_project` dürfen vorhandene Baum-IDs und die sichtbare Auswahl bestmöglich erhalten bleiben.

## 5. Oberfläche und Verhalten

- Kompakter, schmaler Sidebar-Baum mit Filterfeld; geeignet für Windows-HiDPI und helles/dunkles Qt-Theme.
- Plugin-Wurzel mit Anzeigename und Native-Plugin-ID, strukturierte Bereiche Aktionen, Handler, Dynamic Folders.
- Action-Knoten zeigen Anzeigename, nativen `sdk_type`, optional Zuordnung zu Handler. Reihenfolge stabil (wie vom Projekt geliefert oder eindeutig sortiert; dokumentieren).
- Folder-Knoten zeigen `display_name`, `navigation`, Einträge/Placement-IDs sowie Aktionslabel anhand bereits vorhandener `NativeAction`-ID; **keine künstliche Folder-Seite** mit neun erfundenen Tasten erzeugen.
- Handler-Knoten zeigen `id` und `callback_id`. Niemals Handler ausführen.
- Suchfilter case-insensitive über Anzeigename, ID und sichtbare Fachbegriffe; Treffer im Teilbaum behalten die notwendigen Elternknoten sichtbar. Filtern darf nicht die Quelle ändern.
- Gut lesbare Tooltips, vollständiger Text trotz schmalem Layout; Tastaturnavigation (Pfeile, Enter, Esc je nach Qt-Konvention), Doppelklick, Fokus-/Auswahlzustand.
- **Kein** Hinzufügen, Löschen, Umordnen, Bearbeiten, Drag-and-Drop oder Dateischreiben. Auch kein optischer Eindruck, dass ein Klick einen SDK-Command ausführt.
- Leerzustand bei fehlendem Projekt oder Filter ohne Treffer; keine Fake-Profile. Actions des `0.1-draft` nur dann angezeigt, wenn der Host **explizit** über `legacy_project` eine NativeProject-Projektion liefert; keine eigene automatische Migration.
- Optional F1-Hilfeintents, wenn vollständig ohne Kopplung an `HelpCoordinator` realisierbar; **keine Pflicht**. Das spätere Studio verbindet Hilfe zentral.

## 6. Eigenständig startbares PySide6-Lab

`python tools/run_native_project_explorer_lab.py`

- Nutze das **reale Widget** in einem einfachen Testfenster, ohne `StudioWindow`.
- Im Lab das vorhandene native Beispiel `examples/project_logitech_native_v1.json` ausschließlich **lesen** und mit `parse_native_project` parsen. Das Widget liest **selbst keine Dateien**.
- Zeige alle vier SDK-Action-Typen, Handler, Folder, vier Entries; ermögliche UI-Auswahl und protokolliere `nodeSelected`/`nodeActivated` im Lab-Fenster.
- Schaltflächen zur **rein lokalen** Demonstration von Snapshotwechsel, leerem Projekt, Filter und erneutem Snapshot. Die originalen Beispieldateien bleiben unverändert.
- Screenshots für breiten/schmalen Sidebar-Modus, hell/dunkel, voller Baum, Filter und Leerzustand; tatsächliche visuelle Nachsicht (keine unlesbaren horizontalen Texte).
- Automatischer `--smoke`-Modus mit programmgesteuerten Qt-Benutzerinteraktionen (nicht bloß Methodenaufrufe), eindeutiger PASS-/FAIL-Ausgabe und Prozess-Exitcode. Er darf keine Logitech-Dienste oder Hardware ansprechen.

## 7. Prüfungen / Abnahmekriterien

Mindestens folgende Punkte nachweisen:

1. Reales natives Beispiel enthält im Baum genau einen Plugin-Knoten, vier SDK-Aktionsdefinitionen, einen Handler, einen Folder und vier separate Placement-Entries.
2. `set_project` nimmt ein `NativeProject` an; es gibt kein zweites persistentes Action-/Folder-/Profile-Schema im Paket.
3. Derselbe Action-ID-Bezug in mehreren Placements bleibt eine Action-Definition; die Einträge behalten ihre eindeutigen Placement-IDs.
4. Anwenderselektion emittiert genau ein `nodeSelected(kind,id)` mit der **richtigen nativen ID**; Enter/Doppelklick `nodeActivated` ohne ungewollte Duplikate.
5. `set_project`, `set_selection`, `set_filter`, `clear` erzeugen **keine** falschen Benutzer-Navigationssignale.
6. Neue/entfernte Objekte nach Snapshot-Austausch korrekt, keine Aktivierung veralteter Knoten.
7. Suchfilter case-insensitive, korrekte Elternsichtbarkeit, Unicode, lange Labels, NULL-Projekt, leere Folders/Actions-Listen soweit vom Nativen erlaubt.
8. Doppelte Anzeigenamen bleiben durch native IDs unterscheidbar, keine Schlüssel-Kollisionen oder falsche Selektion.
9. Reales Qt-Lab unter Windows 11 visuell geprüft (HiDPI) sowie offscreen automatisiert; keine Daten geschrieben oder Dienste gestartet.
10. Vollständige Testsuite bleibt unverändert grün.

Pflichtbefehle:
`python -m unittest discover -s tests -p test_native_project_explorer_widget.py -v`
`python -m unittest discover -s tests -q`
`python tools/run_native_project_explorer_lab.py --smoke`
`python tools/check_links.py`

**Wichtig:** Qt-Offscreen-Tests sind kein Ersatz für echte Windows-Screenshots. Screenshots dienen als zusätzliche UI-Evidenz, nicht als Beweis für native SDK-Laufzeitfunktion.

## 8. Abschluss / Integration danach

Schreibe `work/widget-lab/native-project-explorer-v1/README.md` mit:
- Öffentlicher Widget-API, ID-/Signalvertrag und Bedienung;
- exakter Liste der geänderten/neuen Dateien;
- reproduzierbaren Testlogs, GUI-Screenshots und Labevidenz;
- späterer Host-Integration: wie `NativeProjectSession.native_project()` den Projektbaum beliefern könnte, **ohne** die Session zu importieren;
- Grenzen und offene Punkte. Bestehender `StudioWindow`-Baum bleibt heute unangetastet.

**Abschlussstatus: `READY_FOR_REVIEW`**; unabhängige Abnahme später. Kein `APPROVED` durch Selbstbewertung, keine Umdeutung von SDK-Aktionen oder Logitech-Profilen.

Arbeite autonom bis zum bestmöglichen testbaren Ergebnis und halte dich an die erlaubten Schreibbereiche.
