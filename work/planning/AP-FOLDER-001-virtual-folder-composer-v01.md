# AP-FOLDER-001 – Virtueller FolderComposer: echte Hierarchie + Verknüpfungen + Seiten

**Auftrag für Codex: jetzt implementieren, nicht nur konzipieren.**

Projektroot: `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture`
Arbeitsakte: `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\work\virtual-folders\AP-FOLDER-001\`
Keine weiteren Agenten starten. Keine Logitech-Service-/Profil-/Hardwareänderungen, kein automatischer Merge.

## Verbindliche Lektüre

1. `docs/decisions/ARCH-ADR-001.md` – Native First, Minimal Bridge, Optional Extensions.
2. `docs/specifications/logitech-profil-und-aktionsmodell-basis-v02.md` – native Folder ≠ Profilordner.
3. `work/research/20261106-dynamicfolder-sdk-bestandsaufnahme.md` – SDK-Lage und offene Hardwarefragen.
4. `src/adapters/logitech/native.py`, `src/adapters/logitech/product.py` und `examples/project_logitech_native_v1.json`.
5. `src/studio/native_session.py`, `src/studio/native_shell/window.py`, `src/studio/native_shell/coordinator.py`, vorhandene Inspector-/Widget-Tests.
6. `docs/architecture/studio/04-Verbindungsregister.md` und `docs/architecture/studio/widgets/ActionLifecycle.md`.
7. `references/logitech-sdk/logi-actions-sdk-llms-full.md`, Abschnitt Dynamic Folders.

## Maßgebliche Produktentscheidung

Der optionale **Shared DynamicFolder** basiert auf dem nativen SDK-`PluginDynamicFolder` und bietet eigene virtuelle Navigation. **Standard: genau ein echter SDK-DynamicFolder als Plugin-Root-Einstieg**, aber die native SDK-Freiheit, mehrere echte Folder zu definieren, darf NIEMALS verboten werden. Jede Plugininstanz bleibt ohne andere Plugins voll funktionsfähig.

Die virtuellen Ordner sollen **gleichzeitig zwei Ordnungsformen** unterstützen, analog Windows Explorer:

- **Echter Ordner / Contains:** Ein virtueller Ordner hat eine eindeutige stabile ID, einen Plugin-Owner und maximal **einen echten Parent**. Das ist seine eigene, hierarchische Position. Mehrere Roots sind für verschiedene Autorenkontexte möglich, ein konfigurierte Plugin-Root bestimmt den SDK-Einstieg.
- **Verknüpfung / Link:** Ein beliebiger weiterer Ordner kann eine Verknüpfung zum selben Ziel enthalten; der Zielordner erhält dadurch keinen zweiten Parent. Verknüpfungen zwischen A und B, später auch zwischen unterschiedlichen Plugins, sind zulässig.
- **Neuer Ordner:** erzeugt neuen Node samt Parent.
- **Verschieben:** verändert den echten Parent/das Placement, **behält** die Node-ID und alle auf diesen Node zeigenden Links.
- **Kopieren:** erzeugt **neue** IDs. Bei Kopie eines enthaltenen Teilbaums werden dessen echte Kindordner unabhängig dupliziert; externe/verlinkte Zielordner nicht heimlich kopieren.
- **Verknüpfung erstellen:** erzeugt nur neuen Link/Placement und erhält die ID des Ziels.
- **Entfernen eines Links:** löscht NIE das Ziel. **Entfernen einer Action-Platzierung:** löscht NIE die Actiondefinition. Echtes Löschen von Ordnern darf keine fremden Ressourcen heimlich löschen; Referenzen und Nachfolger defensiv behandeln.
- **Echte Elternbeziehungen dürfen keine Zyklen bilden.** Link-Zyklen sind als explizite Referenzen zulässig, aber die Darstellung/Navigation darf keine rekursiven Endlosschleifen verursachen.
- **Back-Navigation:** Muss den vom Benutzer **tatsächlich beschrittenen Weg** (Stack von Link-/Placement-IDs) berücksichtigen, nicht nur den echten Parent. Dadurch führt ein Link aus B in einen Ordner von A beim Zurück wieder nach B.
- **Aktionen:** Jedes Action-Placement referenziert weiterhin eine einzelne SDK-native Actiondefinition. Eine Action darf in vielen virtuellen Ordnern/Seiten erscheinen, ohne ihre Definition zu kopieren. Remote Actions über namespaced IDs, keine Mutation des fremden Providers. Keine zweite Actiondomäne erfinden.

**Mehrseitigkeit je virtuellem Ordner optional:** Single Page / Auto-Paging / Manual Pages. Seiten haben stabile Identitäten; ein Seitenwechsel ist KEIN virtueller Ordnerwechsel und verändert den Back-Stack nicht. Bei Auto-Paging darf die Slotanzahl nur aus einer expliziten Capability stammen. **Kein 8-/9-Tasten-Limit erfinden.** SDK-Funktionen `GetNavigationArea`, `NavigateLeftActionName` und `NavigateRightActionName` bleiben verfügbar. Die zwei vom Benutzer erwähnten Hardware-Seitentasten am MX Keypad sind **HARDWARE_PENDING** und dürfen nicht ohne Test festverdrahtet werden.

**Shared/Join-&-Leave gehört konzeptionell zum Folder-Pattern**, nicht zu einer zwingenden zentralen Zusatzruntime. Jedes Plugin funktioniert allein; lokale Actions immer ohne Peer-Netzwerk. Für dieses AP aber KEIN vollständiges Discovery-/Heartbeat-/IPC-System implementieren: wichtiger ist der funktionierende FolderComposer. Stelle lediglich eine schmale Provider-/Reference-Schnittstelle für späteren dezentralen Austausch bereit. Später: Discovery für angebotene Aktionen; Dauer-Subscriptions nur für wirklich referenzierte Fremd-Actions, unabhängig von Sichtbarkeit, Initial-Snapshot und Änderungen per Push; Owner führt aus; Rejoin wie neuer Join. Keine verteilte Datenbank, kein zentraler Prozess.

## IMPLEMENTIERUNG – in dieser Reihenfolge

### 1. Qt-freier virtueller Folder-Kern (P0)

Implementiere ein kleines klar abgegrenztes Modul, vorzugsweise `src/studio/virtual_folders/`, mit:
- stabilen Identitäten: Plugin-/Node-ID, echter Parent/Ownership, separate Placement-ID, Action-ID, Folder-Link-Ziel, Page-ID, Seitenmodus/Position.
- validierbarem Modell; pure Mutationen/Copy-on-Write oder Draft, nachvollziehbaren Fehlern.
- create/rename/move/copy/delete für echte Folder; create/remove Link; add/remove/reorder Action-Placement; add/remove/reorder Page; navigate/open/back, next/previous page.
- Validierung gegen Containment-Zyklen, Duplikate, fehlende Ziele, ungültige Positionen; Extern-Referenzen dürfen bei Provider-Offline nicht gelöscht werden.
- Aktionen werden aus dem nativen Snapshot referenziert, **nicht als neue Definitionsobjekte kopiert**.
- Namensraum für externe Referenzen und eine kleine API für in Zukunft push-basiert aktualisierbare Darstellungs-/Verfügbarkeitsdaten; keine unnötige Peer-Implementierung.

### 2. Tatsächlich bedienbare PySide6-Editoroberfläche (P0)

Ein FolderComposer-Widget, vorzugsweise `src/studio/virtual_folders/widget.py`:
- linke echte Ordnerhierarchie, separat gekennzeichnete Verknüpfungen;
- zentral aktuell gewählter Ordner + Seiten, Einträge, Actions, Reihenfolge;
- Bedienelemente: Neuer Ordner, Link, Kopieren, Verschieben, Umbenennen, Entfernen; Action hinzufügen/entfernen, Seitenmodus, Seiten hinzufügen/wechseln/löschen;
- sichtbare Vorschau/Simulation der Navigation samt Back und Seitenwechsel, ohne unbelegtes hardwaregenaues Keypad-Frame;
- vorhandene SDK-Actiondefinitionen über bestehenden NativeProjectSession-Snapshot als Auswahlquelle, keine neuen SDK-Typen erfinden;
- Fehlermeldungen und leere Zustände; klares visuelles Unterscheiden von "Ordner", "Link", "Action", "Seite", "nicht verfügbar".
- Eine eigenständig startbare Demo muss ohne Hardware möglich sein und A/B mit mehrfach referenziertem Ordner darstellen.

### 3. Sichere Persistenz und Shell-Integration (P1, nach funktionsfähigem P0)

Das bestehende Schema `logitech-native-1` und `NativeProjectSession` **nicht heimlich erweitern/umschreiben**. Für virtuelle Komfortdaten darf ein **klar getrenntes optionales Extension-JSON** als autoritativer Owner vorgesehen werden; eindeutiger Codec, Validierung, atomare Speicherung, explizites Import/Export/Speichern und kein automatisches Überschreiben vorhandener Dateien. Keine konkurrierende SDK-Action-Datenbank. Projektidentität/Plugin-ID beim Laden prüfen. Wenn Persistenz in der verfügbaren Zeit nicht sicher ist: zuverlässigen Codec + Import/Export im Lab implementieren und Grenze dokumentieren.

Wenn ohne Regression möglich, den Composer als eigenständigen Tab in `NativeStudioShell` einbinden. Draftschutz, Projektwechsel, Undo/Redo und Disk-Conflict-Konventionen beachten. Neue Hostverbindungen fortlaufend ab **V-71** in `docs/architecture/studio/04-Verbindungsregister.md` mit Sender/Empfänger/Payload/Guard/Test dokumentieren. Bestehende V-IDs unverändert lassen. Bei unsicherer Shell-Integration zunächst **vollständigen eigenständig benutzbaren Composer** bevorzugen.

### 4. SDK-nahe Projektionsprobe (P2)

Prüfe offline `src/adapters/logitech/product.py::_folder`: existierende `CreateCommandName(placement_id)` → `RunCommand` → `Bridge.Dispatch`-Kette. Dokumentiere, wie unsere aktuelle virtuelle Seite auf echte Folder-Actions projiziert würde. Gegenwärtig statische Placements und Bildrefresh dürfen nicht als dynamisches `ButtonActionNamesChanged` ausgegeben werden. Wenn ohne Geräte-/Servicezugriff möglich, einen kleinen isolierten Generator-/Adapter-Test ergänzen. Keine spekulative SDK-Open-Funktion, keine HID-Emulation, keine echten Profilwriter.

## Pflicht-Tests / Akzeptanz

1. A besitzt echte Unterordner A_01 → A_01_01 → A_01_01_02. B enthält **Link** auf A_01_01_02. Back kehrt korrekt nach B zurück.
2. Zwei Links auf denselben Ordner sehen dieselben Änderungen; Link-Löschung löscht keinen Zielordner.
3. Copy erzeugt neue IDs und unabhängige echte Unterbäume; Move behält IDs; Containment-Zyklen verboten.
4. Action A_01 in mehreren Ordnern/Seiten platziert: Removing Placement löscht keine NativeAction.
5. Page-Modes Single/Auto/Manual. Wechsel zwischen Seiten verändert nicht Navigation-Stack; auto nur mit expliziter Capability.
6. Offline-Provider-Referenz bleibt sichtbar/gespeichert; fehlerhafte IDs, fehlende Targets, zyklische Links, JSON-Roundtrip, invalid JSON und Version werden defensiv behandelt.
7. PySide6 GUI-Tests mit `QT_QPA_PLATFORM=offscreen` sowie Windows-Qt-Smoketest soweit möglich; echte Buttonbedienung und nicht nur Constructor-Test.
8. Vollständige Regression: `python -m unittest discover -s tests -p "test_*.py"`; dokumentierte Exitcodes/Logs; neue Tests `tests/test_virtual_folder_*.py`. Bestehende abgenommene Funktionalität darf nicht brechen.

## Sicherheits-/Qualitätsgrenzen

Keine Options+-Service-Neustarts; keine Gerätetests, Logitech-Live-Profile, `.lp5`- oder `ProfileInfo.json`-Writes. Keine unnötige Änderung von SDK-Parser/Schemas, keine QML, keine kostenpflichtigen Services. Keine unautorisierten Commits/Merges. Vorhandene AP-INSP-002-Evidenz unverändert lassen. Bei offenen Hardwarefunktionen **HARDWARE_PENDING** vermerken statt sie zu erfinden. Priorität strikt **funktionierender Folder-Kern → bedienbares Widget → Persistenz/Integration → SDK-Forschung**, nicht umgekehrt.

## Arbeitsakte und Abschluss

Im Verzeichnis `work/virtual-folders/AP-FOLDER-001/` erstellen:
- `01_original_prompt.md`: dieser Prompt unverändert;
- `02_verlauf.md`: Arbeit, Entscheidungen;
- `03_ergebnisse.md`: implementierte Funktionen mit Tests;
- `04_abschlussbericht.md`: COMPLETE/PARTIAL, getrennte Hardwaregates und konkrete Restpunkte;
- `05_evidenz/`: Testlogs, Quellcode-Änderungsliste, gegebenenfalls UI-Screenshot und Demo-Anleitung;
- `README.md`: kompakter Startpunkt für unabhängige Abnahme.

**Zum Schluss:** Startbefehl für interaktive Demo nennen; den Testfall „echter Ordner vs. Link vs. Kopie“ nachweisen; neue Dateiliste; UI- und Gesamttests mit Zahlen/Exitcodes; offene Hardware-/Profilfragen. **Nicht auf weitere Rückfragen warten: die beschriebenen Produktentscheidungen gelten für diesen Lauf als getroffen.**
