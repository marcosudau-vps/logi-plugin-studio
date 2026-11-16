# Projektautorität, Identität und Transaktionen

Stand: 06.11.2026 · AP-STUDIO-002 implementiert, unabhängig APPROVED am 06.11.2026.

`NativeProjectSession` besitzt das vollständige ursprüngliche `logitech-native-1`-JSON. `parse_native_project` ist der normative Validator. Native Dataclasses sind defensive Leseprojektionen; kein Dataclass-zu-JSON-Rewriter und keine zweite persistente Domäne.

## Implementierter Änderungspfad

```mermaid
sequenceDiagram
    participant UI as NativeStudioShell
    participant H as StudioCoordinator
    participant S as NativeProjectSession
    participant P as parse_native_project
    UI->>UI: Anzeigenamendialog; Revision vor Eingabe erfassen
    UI->>H: rename_action(id,name,base_revision)
    H->>H: aktuelle Revision und native ID prüfen
    H->>S: snapshot()
    H->>H: nur actions[id].display_name verändern
    H->>S: replace(proposed,base_revision)
    S->>P: vollständiges vorgeschlagenes JSON validieren
    P-->>S: NativeProject oder Fehler
    S-->>H: neue Revision bei echtem Commit
    H-->>UI: frische Projektionen; Dirty / History
```

Leerer Anzeigename, stale Revision, verlorene ID oder ungültiger Handler-/Actionverweis ändern weder JSON noch History. Inhaltsgleiche Namen bleiben Session-No-op. ActionInspector ergänzt AP-INSP-001; keine Erstellung, Assetbearbeitung oder Platzierungsänderung.

## Auswahl / Lebensdauer

`(node_kind,native_id)` identifiziert die native Entity. Eine FolderEntry-ID bleibt eine Platzierung, ihre referenzierte Action wird im Katalog nur als Definition markiert. `action_parameter` ist exakt `NativeParameter.name`, nicht der Anzeigetext. Ein Baumknoten ohne Parameterinformation erfindet keine Variante. Katalog-Elternknoten werden über dessen tatsächliche `itemSelectionChanged`-Route erkannt. Der Host synchronisiert mit `_syncing`; die Views erhalten ausschließlich stille Setter. Explizite Auswahl macht das Gegenstück sichtbar; ein Filter, der die aktuelle Auswahl ausblendet, leert auch die Hostauswahl.

Projektwechsel lädt zunächst eine gültige Kandidatensession. Erst danach werden Projekttoken, Auswahl, Katalogbilder/-Nutzungswerte, Filter, Diagnosequellen und Hilfepin/-fakten zurückgesetzt. Gleiche Plugin-/Action-IDs in einer anderen Datei sind kein Grund, den alten Parameterkontext zu behalten. Asynchrone Diagnosequellen müssen `project_token` und aktuelle `base_revision` liefern. Es gibt derzeit keine asynchronen Auswahl-/Commitquellen.

## Speichern / Verwerfen / Konflikte

Nur explizites Save ruft `Session.save()` auf. Undo/Redo laufen in derselben Session. Save verwendet deren ursprünglichen Pfad und exakte Byte-/Hashbaseline, Staging, fsync und atomaren Replace. Kein Save-As und kein globaler OS-Dateilock: das bestehende finale Check/Replace-Racefenster bleibt dokumentiert.

Vor Öffnen, Reload und Schließen: Save / Discard / Cancel, Standard Cancel. Bei Savefehler oder DiskConflict bleibt das alte Projekt samt Dirty-Inhalt offen; die externen Bytes werden nicht überschrieben. Discard wird nur beim tatsächlich erfolgreichen Laden oder bestätigten Schließen wirksam. Auch ein fehlgeschlagenes Öffnen nach Discard erhält die alte Session. Der Coordinator verweigert direkten Dirty-Projektwechsel ohne ausdrückliches `discard=True`; die Shell setzt dieses Flag erst nach dem Dialog.

Fehler erscheinen als echte `Diagnostic` in getrennten Kanälen (`open`, `edit`, `save`, `native.validation`). Der Parser liefert bisher Text statt strukturierter Pointer: Hostdiagnosen verwenden `/`. Weder Indexpfad noch Text wird als Entity-ID interpretiert. Bei Commit/Undo/Redo werden veraltete Diagnosesnapshots entfernt und die gültige native Projektion neu verteilt.

## Harte Grenzen

NativeIctCoordinator/SymbolDesigner bleiben gesperrt, solange die gemeinsame JSON-/Multi-File-Writerhoheit nicht unabhängig abgesichert ist. Kein Previewframe ohne belegte Capability, keine Logitech-Service-/ProfileInfo-/LP5-Writes. Das alte `0.1-draft`-Fenster bleibt über den Standardlauncher unverändert erreichbar; `--native` aktiviert ausschließlich die neue Shell.

[Verbindungsregister samt einzelnen Integrationstests](04-Verbindungsregister.md) · [Sessionreferenz](services/NativeProjectSession.md)

## AP-INSP-001 – implementiert, APPROVED

Der [ActionInspector](widgets/ActionInspector.md) bearbeitet alle vier vorhandenen SDK-Aktionstypen einschließlich strukturierter Parameter, States, Adjustment, EditorControls/Filter und Asset-Referenzen. NativeAction ist weiter nur Leseprojektion. Ein defensiver Qt-freier ActionDraft hält Rohdaten und opake Baserevision; nur bewusst geänderte Felder werden gepatcht. ID und Typ bleiben fest, neue Actions und Folderänderungen bleiben ausgeschlossen.

Auswahl aus Explorer/Katalog beziehungsweise FolderEntry→Action wird vom Host in den permanenten Inspector-Tab projiziert. Katalog-Bearbeiten öffnet diesen Tab; Toolbar-Anzeigename bleibt QInputDialog. Apply führt über `StudioCoordinator.apply_action_edit` zu genau einem `NativeProjectSession.replace`, ohne Autosave. Undo/Redo/Save bleiben dieselbe Sessionhistory. Dirty-Drafts werden unabhängig von Session-Dirty geschützt; Cancel, stale Revision, DiskConflict und fehlgeschlagene Projektwechsel erhalten Eingaben. Alle Ansichten werden nach erfolgreichem Commit frisch projiziert; Dirty-Refresh überschreibt keine Felder.

Die eine bestehende Hilfe erhält Quelle inspector mit 13 Topics (55 insgesamt). Lokale `inspectorTopic`-Eigenschaften gelten auch für dynamische Zeilen/Filter; Host-F1/FocusIn/Pin/Related zeigen keine Rohdaten. [Register V-53–V-62](04-Verbindungsregister.md), [Arbeitsakte, Tests und Windows-Bilder](../../../work/action-inspector/AP-INSP-001/README.md). Unabhängige Abnahme am 06.11.2026 erfolgt; AP-INSP-002 bleibt Folgeplanung.

## Lifecycle-Transaktionen AP-INSP-002 – APPROVED

Die aktuelle Erweiterung erlaubt Create/Delete über denselben Writer. `propose_create` hängt ausschließlich eine kopierte Action an; `propose_delete` entfernt ausschließlich die aktuelle stabile ID nach Existenz-, Folderreferenz- und Mindestanzahlprüfung. Jede erfolgreiche Operation führt exakt einen replace mit vorher korrelierter Baserevision und Projekttoken aus. `_lifecycle_guard` prüft lesend dieselbe Sessiondiskbaseline; Save bleibt ausdrücklich separat. Handler/Folders/Plugin/Lizenzen/andere Actions bleiben wertgleich.

CreateDraft hält einen echten ursprünglichen Projektsnapshot ohne neue Action und validiert über eine vorübergehende reine Parserprojektion. Keine Sessioninstanz/-history wird zum Entwurf vorgetäuscht. Ein aktiver Createentwurf ist separat dirty. Open/Reload verschieben Discard bis zu erfolgreichem Load; fehlgeschlagene Ziele erhalten alle Eingaben. Die Deletebestätigung gilt nur für ihre erfasste ID/Revision/Token; paralleler Commit/Projektwechsel scheitert vor jedem weiteren Commit. Keine automatische Kaskade: **referenzierte Action nicht löschen**. Die letzte Action bleibt gemäß Parserminimum erhalten.

Stale-Warnung ist rein transient: Änderungen aus Hostsignalen oder dem 350-ms-Kontextbeobachter erhalten die ursprüngliche Draftbasis. Save ohne Revisionwechsel ist kein Rebase. Accordionaktionen serialisieren und committen nichts. [Vertrag und Negativtests](widgets/ActionLifecycle.md), [Arbeitsakte](../../../work/action-inspector/AP-INSP-002/README.md).


## AP-FOLDER-002: zwei koordinierte Lebenszyklen, zwei Writer

Der native kanonische Projektpfad bindet die Extension über die bereits bestehende `project.<sha256(casefold(canonical_path))>`-Identität. Gemeinsame Helper stehen in `virtual_folders/binding.py`; der eigenständige Host reexportiert `project_identity` kompatibel. Standarddatei ist `native_path.with_suffix('.vfolders.json')`. Keine native Schemaänderung und keine automatische Wiederbindung gleicher Plugin-IDs.

`prepare_project` lädt und validiert NativeSession sowie vorhandene Sidecar-Extension vor jedem Dirty-Dialog. Die Shell fragt Inspectorentwurf, native Änderungen und Folderänderungen separat ab. Discard bleibt bis zum erfolgreichen Gesamtablauf aufgeschoben. Nach den Dialogen werden beide Kandidaten nochmals eingelesen; dies berücksichtigt auch Saves des alten Projekts beim Reload. Fehlgeschlagener zweiter Save lässt den bereits erfolgreichen ersten Save bestehen und bewahrt den verbleibenden Dirty-Stand. Das ist ausdrücklich keine Gesamttransaktion.

`ExtensionStore.revision` ist ein opakes flüchtiges Token, das nur bei echtem Commit/Undo/Redo wechselt, nicht bei Save oder No-op. Modale Composerintents prüfen Store, Document, nativen Snapshot, NativeSessionrevision und Extensionrevision gegen ihren Ausgangsstand (einschließlich Undo-zurück-zum-selben-Snapshot). Vor Foldermutation/History werden native und vorhandene Extension-Diskbaselines geprüft. Import übernimmt nach Identitäts-/Strukturprüfung nur das Document in den bestehenden Store; Export einer Kopie lenkt den Studio-Writer nicht um.

`Document.validate_native(snapshot, require_available=True)` behält den konservativen ursprünglichen Strict-Vertrag. Der integrierte Studiohost verwendet ausdrücklich `require_available=False`: Struktur und Plugin-ID bleiben verpflichtend, fehlende Actiondefinitionen sind externe Verfügbarkeit. `missing_actions(snapshot)` liefert die erhaltenen betroffenen Placements. Bestehender Standalone-Import bleibt standardmäßig strikt. Referenzen auf nicht verfügbare fremde Plugins bleiben erhalten.

Native Löschen und native History schützen gegen neu erzeugte verwaiste Studio-Platzierungen. Extension-Undo darf bewusst eine inzwischen verwaiste Platzierung wiederherstellen; die Diagnose erscheint unmittelbar. Es gibt keine zweite Action- oder native Historydatenbank. Der lesende History-Preflight verwendet derzeit die bestehenden Sessionstacks `_undo`/`_redo`; eine optionale öffentliche Peek-Schnittstelle ist im [Übergabevertrag](../../../work/studio-integration/AP-FOLDER-002/07_schnittstellen_uebergabe.md) vorgeschlagen.
