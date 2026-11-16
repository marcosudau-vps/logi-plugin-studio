# Native Keypad-Vorschau und ICT-Bearbeitung

AP-STUDIO-FINAL-001 · Softwareintegration der nativen PySide6-Shell.

Starte die Shell mit `python tools/run_studio.py --native [Projekt.json]`. Der Tab **Keypad** zeigt ohne Sidecar zunächst einen nativen SDK-Folder, mit Sidecar zunächst das virtuelle Autorenmodell. Die Quellenauswahl bietet beide Sichten. Der ActionInspector aktualisiert die Vorschau nach **Übernehmen**. Im virtuellen Modus zeigt dieselbe Navigation wie im FolderComposer den Ordnerpfad, seine Seiten und Links. Ein Action-Klick wählt die Definition beziehungsweise die native Platzierung. Ein lokaler Ordner-Link navigiert nur im Studio.

**Bearbeiten** schaltet das Slotmenü und F2 für ICT frei. Auf nicht automatisch paginierten virtuellen Seiten kann man lokale Button-Actions am nächsten freien Platz ablegen, verschieben, kopieren und entfernen. Das Autorenmodell speichert eine lückenlose Reihenfolge; es gibt keine freien Lücken oder stilles Ersetzen. Das Plus im Pager steht für Seiten im manuellen Modus. Automatische Umverteilung, übervolle Seiten und strukturelle Ordneränderungen bleiben beim FolderComposer. Die Toolbar führt Undo/Redo je nach sichtbarer Quelle an den vorhandenen Writer. Der SymbolDesigner ist auch über die Toolbar für die gewählte Action/Variante erreichbar.

| Wert | Führende Quelle | Vorschau |
|---|---|---|
| Native Action, Parameter, Platzierung und Navigationsbereich | `NativeProjectSession`, `NativeFolder.device_navigation["Loupedeck70"]` vor `navigation` | Aufgelöste Reihenfolge, native IDs und Parameter, bei Multistate State 0 als Autorenansicht |
| Virtuelle Folder, Seiten und Links | `FolderComposer` und `ExtensionStore` | Aktueller Navigationspfad; separates, optionales Sidecar |
| Gerät und sichtbare LCD-Geometrie | Installierte SDK-XML (`DeviceType.Loupedeck70`); [Widget-Abnahme](../../../work/acceptance/20261104-keypad-catalog/ABNAHME.md) | Neun LCD-Flächen aus dem bestehenden Skin; neutrale Ansicht bei fehlenden lokalen Originalgrafiken |
| ICT und Bildressourcen | Referenzen des nativen Projekts, lokale Assets, bestehender SymbolDesigner-Renderer | Action- vor Plugin-ICT, darstellbare lokale PNG/SVG-Bilder und explizites State-0-Bild; keine User-/Global-ICTs oder Live-Runtime |

Die dargestellte Position ist die **Autorenreihenfolge**. Es gibt keine bestätigte Options+-Tastenzuteilung oder Hardware-Pagination; größere Seiten sind vollständig als nummerierte Ausschnitte einsehbar. Es werden keine reservierten physischen SDK-Navigationsslots behauptet. ActionEditor im DynamicFolder, Encoder-Adjustments am Keypad und externe/offline Referenzen sind als nicht bedienbar markiert. SVG-Dateien unter `actionsymbols` sind im SDK Katalogsymbole und keine separate ICT pro Parameter. F2 gibt die korrekte Parameteridentität an den Dialog weiter; die gespeicherte Vorlage gilt für die Action.

**SymbolDesigner:** Der Dialog startet bei Aufruf über die Toolbar schreibgeschützt. Vor dem Wechsel der Action, Schließen und bei Escape werden Entwürfe geschützt. Der modale Dialog sperrt Projektwechsel, Fensterschließen und Build. Ein privates, bereits gespeichertes Asset wird konfliktgeprüft atomar ersetzt. Für geerbte, geteilte oder noch nicht gespeicherte Referenzen wird eine private ICT exklusiv angelegt und der Link über die aktuelle native Session gespeichert. Der Dialog nennt die Mitspeicherung bereits offener nativer Änderungen beim Zuordnen. Externe Änderungen bleiben erhalten. Details zu Rollback und Grenzen stehen im [Integrationsvertrag](../../../work/studio-final/AP-STUDIO-FINAL-001/outputs/integration_contract.md).

Zum Bauen bleiben native JSON und Extension explizit zu speichern. Der bestehende [SDK-Build](NativeBuildIntegration.md) verarbeitet die gespeicherten Eingaben und validiert die nativen ICTs. Die Gerätedarstellung sowie die Einbindung der Ressourcen in eine installierte Hostumgebung sind keine Softwareabnahme dieses Arbeitspakets.
