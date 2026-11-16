# FolderComposer – AP-FOLDER-001

Stand: 06.11.2026. Implementiert und lokal getestet; keine unabhängige Abnahme oder Gerätefreigabe.

## Owner und Grenzen

`studio.virtual_folders` ist eine optionale Komfortschicht. `Document` besitzt ausschließlich virtuelle Ordner, Seiten und Platzierungen. Native Actions gehören weiter zu `logitech-native-1` / `NativeProjectSession`. Es gibt weder ein weiteres Actiondefinitionsformat noch einen Logitech-Profilwriter. Der bestehende Generator und die bestehenden Shell-/Inspectorverträge bleiben unverändert.

Standard ist ein konfigurierter virtueller Plugin-Root als künftiger Einstieg innerhalb eines echten SDK-DynamicFolders. Weitere Autoren-Roots sind erlaubt. Das native Modell darf weiterhin mehrere echte SDK-Folder definieren; dies wird separat getestet. Die Extension erzeugt noch keine SDK-Klassen.

## Kernvertrag

`Document`, `Folder`, `Page`, `Placement`, `Reference` und `PagingCapability` sind unveränderliche Dataclasses. Mutationen liefern neue, validierte Snapshots. Create-/Copy-/Add-Operationen liefern zusätzlich die neue ID. Node-, Page- und Placement-IDs stammen aus UUIDs; Anzeigenamen sind keine Identitäten.

- `Folder.parent_id` und genau eine `contains`-Platzierung stimmen für jeden Nicht-Root überein. Containment bleibt azyklisch.
- `link` hat eine eigene Placement-ID und behält das namespaced Ziel `plugin.id::resource.id`. Links werden strukturell niemals rekursiv verfolgt.
- `copy_folder` dupliziert ausschließlich den echten Teilbaum inklusive eigener Seiten und Platzierungen. Alle Links behalten ihre exakten ursprünglichen Ziele, auch Links in denselben Teilbaum. Action-Referenzen bleiben Referenzen.
- `move_folder` behält Node-ID und eine vorhandene Contains-Placement-ID. Verschieben zu einem Autoren-Root entfernt nur das eingehende Contains-Placement. Eingehende Links bleiben gültig.
- `delete_folder` blockiert den konfigurierten Root, echte Kinder und eingehende Links. Bei erlaubtem Löschen verschwinden nur der Node, seine Seiten und seine eigenen Platzierungen; keine Zielordner oder Actiondefinitionen.
- `remove_placement` entfernt Links oder Action-Platzierungen; Contains erfordert ausdrücklich Move/Delete.
- Seitenpositionen sind je Seite lückenlos, eindeutig und 0-basiert. Seite hinzufügen, umbenennen, umordnen und leere zusätzliche Manual-Seite löschen sind unterstützt. Nichtleere Seiten zuerst explizit leeren/umhängen.
- Single führt Einträge unter Beibehaltung ihrer Placement-IDs auf der ersten Seite zusammen. Manual behält explizite Seiten. Auto erfordert `PagingCapability(slots, source)`, erhält die IDs überlebender Seiten und legt zusätzliche Seiten nach Bedarf an. Die GUI fragt die Slotanzahl ausdrücklich als Simulations-Capability ab. Kein Hardwarestandardwert wird angenommen.

`Navigation` speichert `Step(placement_id, origin_id, origin_page_id, target_id)`. Open erlaubt nur Einträge der aktuellen Seite; Back kehrt zur tatsächlichen Herkunft inklusive Seite zurück. Seitenwechsel verändern den Stack nicht. Autorenauswahl im Baum startet bewusst einen neuen Simulationsweg. Entfernte/umgehängte Wegplatzierungen invalidieren den alten Stack; erhaltene Zielordner bleiben geöffnet. Auch explizite Linkzyklen erzeugen nur einzelne Schritte pro Benutzeraktion.

`validate()` prüft die interne Struktur. `validate_native(snapshot)` prüft beim Attach/Import zusätzlich Plugin-ID und lokale Actionziele gegen den normativen nativen Parser. Fremde IDs dürfen offline bleiben. Später aus der Quelle entfernte lokale Actions bleiben als nicht verfügbare Platzierungen sichtbar; kein Providerrefresh bereinigt Autorendaten.

## Referenzen und Provider

`ReferenceProvider` beschreibt Initial-Snapshot plus Subscription auf eine Menge tatsächlich referenzierter IDs. `ReferenceHub` hält nur flüchtige Namen, SDK-Typangaben und Verfügbarkeit. `push`, `offline`, `snapshot`, `subscribe`/Release sind lokal testbar. Der Composer abonniert seine referenzierten externen Ziele und Action-IDs unabhängig von der sichtbaren Seite.

Kein Discovery-, Heartbeat-, IPC-, Remote-Invoke- oder fremder Ordnergraph wird implementiert. Ein externer Ordnerlink bleibt sichtbar/gespeichert; Open liefert eine verständliche Verfügbarkeitsgrenze. Spätere Adapter müssen Aufrufe zum Owner führen und Pushs auf dem UI-Thread zustellen. Lokale Actions und Autorenoperationen benötigen keinen Peer.

## Extension-Persistenz

`virtual-folders-1`, Dateisuffix `.vfolders.json`, maximal 4 MiB. JSON enthält ausschließlich `version`, `project_id`, `plugin_id`, `root_id`, `folders` und `placements`. Codec verweigert unbekannte Felder/Versionen, doppelte Schlüssel, Nicht-JSON-Zahlen und ungültige Struktur, statt sie zu reparieren.

Das native Schema hat keine separate Projekt-UUID. Der Labhost verwendet deshalb `project.<sha256(casefold(canonical_source_path))>` und prüft zusätzlich Plugin-ID. Unterschiedliche Dateien mit gleicher Plugin-ID werden nicht verwechselt. Ein verschobenes/umbenanntes Projekt benötigt künftig einen expliziten Rebind; es erfolgt kein stiller Import in einen anderen Kontext.

`ExtensionStore` ist der einzige Writer dieser Datei, mit eigener, auf 50 Schritte begrenzter History. Import wird vor einer Discardentscheidung vollständig validiert. Export publiziert eine gestagte, geflushte Datei per exklusivem Hardlink: ein existierender Zielpfad wird auch bei konkurrierender Erstellung niemals überschrieben. Save schreibt ausschließlich die zuvor explizit geladene/exportierte Extension; Bytebaseline wird vor und nach Staging geprüft, anschließend `os.replace`. Das Dateisystem muss Hardlinks im Zielverzeichnis unterstützen. Unkoordinierte Änderungen im letzten Check/Replace-Zeitfenster sind wie bei der vorhandenen NativeSession kein OS-Compare-and-Swap; ein koordinierter Writer je Extension bleibt Voraussetzung.

## UI und Host

`FolderComposer` bietet echte Hierarchie, als Links gekennzeichnete Blätter, Seiten-/Eintragslisten, sämtliche Mutationsbuttons, native Action-/Parameterauswahl sowie Open/Back und Seitenvorschau ohne Hardwareframe. Fehler und leere Seiten werden sichtbar erklärt. Actionaktivierung simuliert nur; sie ruft keinen Handler auf.

Der eigenständige `ComposerWindow` lädt eine NativeProjectSession nur lesend, übergibt defensive Snapshots und schützt Projektwechsel/Close mit Save/Discard/Cancel. Neue Projekte werden vollständig vorbereitet, bevor der alte Composer ersetzt wird. Bei fehlgeschlagenem Import/Open, Cancel oder Disk-Conflict bleibt der alte Entwurf erhalten. Modale Mutationen prüfen nach dem Dialog die Identität des Ausgangssnapshots. Der Baumrefresh erfolgt nach dem nativen Klick-Handler über einen fenstereigenen Single-Shot-Timer, um keine noch von Qt verwendeten Items zu löschen.

Kein Tab in `NativeStudioShell` in diesem AP-Lauf: die ausdrücklich erlaubte vollständige Standalone-/Labroute wird geliefert. Deren Extension-Undo/Save sind getrennt von der nativen Shellhistory. Hostkanten V-71–V-73 sind im [Verbindungsregister](../04-Verbindungsregister.md) dokumentiert.

Start und Tests: [Arbeitsakte](../../../../work/virtual-folders/AP-FOLDER-001/README.md).


## AP-FOLDER-002: bedienbare NativeStudioShell-Integration

Die oben genannten Standalone-Grenzen beschreiben den AP-FOLDER-001-Stand. Aktuell existiert zusätzlich ein vollwertiger Tab **Virtuelle Ordner** in der NativeStudioShell. Der unveränderte Standalone-Launcher bleibt verfügbar. Keine konkurrierende FolderEditor-Implementation.

Die Shell stellt den geladenen `ExtensionStore` über `FolderComposer(..., store=..., import_as_document=True)` bereit. Die integrierte Importfunktion prüft die kanonische Projektidentität und übernimmt nur das Document in diesen Store. Ein Kopie-Export erzeugt eine neue Datei ohne Umleitung des Studiospeicherziels. Der erste explizite Save publiziert exklusiv die Sidecar-Datei neben dem nativen Projekt; spätere Saves verwenden den bestehenden DiskConflict-Schutz.

Mehrfachplatzierungen verwenden dieselbe native Action-ID. Der Button **Im Aktionsinspektor öffnen** navigiert nur für verfügbare lokale Actions über den vorhandenen Coordinator-/Draftguard. Remote- oder fehlende Referenzen sind keine ausführbaren Actions. Entfernen eines Placements löscht niemals die native Definition. Das integrierte Studio lädt verwaiste lokale Referenzen bewusst mit `require_available=False`; Liste und ProblemsPanel erklären die Verfügbarkeitslücke. Bewusstes Entfernen erfolgt über den vorhandenen Placementbutton; andere Daten bleiben bestehen. Der separate Labimport bleibt konservativ streng.

Neue Signale `actionEditRequested(str)` und `errorOccurred(str)` verbinden vorhandenen Inspector und ProblemsPanel. Die Hilfe registriert `folders.studio` im vorhandenen Registry-/Coordinator-System einschließlich modaler Composer-Dialoge. Dirty-Status zeigt native und Extensionänderungen getrennt. Undo/Redo folgt dem aktiven Editorbereich mit ausdrücklicher Beschriftung; natives Speichern und Extension speichern sind getrennte Aktionen.

Referenzschutz, stale Dialoge, Cancel nach vorheriger Discardentscheidung, Konflikte und Teil-Saves sind durch echte Shelltests abgesichert. [V-74–V-82](../04-Verbindungsregister.md), [Windows-Qt-Evidenz und Grenzen](../../../../work/studio-integration/AP-FOLDER-002/README.md). Keine SDK-/Hardwarefreigabe durch diesen Integrationsnachweis.
