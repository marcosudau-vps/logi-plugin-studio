# SDK-native DynamicFolder Runtime und Studio-Übergabe

Stand: 06.11.2026 · Implementierung REVIEW-FIX-20261106 · READY_FOR_REVIEW, keine Selbstabnahme.

## Quellen und Grenzen

Die Implementierung folgt [ARCH-ADR-001](../decisions/ARCH-ADR-001.md), der [Profil-/Aktionsmodellbasis](../specifications/logitech-profil-und-aktionsmodell-basis-v02.md), dem Abschnitt Dynamic Folders in `references/logitech-sdk/logi-actions-sdk-llms-full.md` und der lesend geprüften Forschung `logi-actions-sdk-rec/work/runs/RUN-20261106-FOLDERRESEARCH-01/outputs/frageantwort-matrix.md`. Installierte SDK-Signaturen sind in der Reviewakte als `evidence/sdk-signatures.txt` erfasst. Forschung und SDK-Root wurden nicht verändert.

Öffentliche SDK-Aufrufe: `Plugin.GetActions`, `PluginDynamicAction.TryRunCommand`, `TryGetCommandImage`, `TryGetCommandDisplayName`, `PluginDynamicAdjustment.TryApplyAdjustment`, `TryGetAdjustmentValue` sowie die entsprechenden Adjustment-Ausgaben. Folder erzeugen ihre lokalen Callbacknamen mit `CreateCommandName`/`CreateAdjustmentName`. `ExecuteGenericAction` wird nicht verwendet.

## Ausführungs- und Datenherrschaft

Der Generator erzeugt für jede native Folderdefinition eine eigene `NativeFolderBase`-Unterklasse. Die Auflösung sucht ausschließlich im eigenen Plugin die bereits vom SDK verwaltete generierte Actioninstanz anhand ihres exakten C#-Typs. Es werden keine zusätzlichen Actioninstanzen und keine zweite State-Engine erzeugt.

Ein Folder-Callback wird gegen die aktuelle Membership und seinen Generationstoken geprüft. Anschließend ruft der Adapter die öffentliche SDK-Methode derselben Actioninstanz auf. Ein kurzlebiger `AsyncLocal`-Kontext transportiert dabei die stabile Placement-ID in den bestehenden Bridge-Aufruf. Action-ID, Placement-ID und Actionparameter bleiben getrennt. Volle vom eigenen Folder erzeugte Callbacknamen und ihre lokalen Parameter werden akzeptiert; beliebige Präfixe oder alte Tokens werden abgelehnt.

- DynamicCommand: Button-Action, Parameter unverändert.
- Multistate: dieselbe SDK-Statehaltung, Mutation und State-Bild-/Namensauflösung wie beim direkten Action-Aufruf. Die Folder-Ansichten werden bei Änderung neu gezeichnet.
- DynamicAdjustment: Encoder-Rotation; Reset bei `has_reset=true` über Encoder-Press. Reset setzt den SDK-nativen lokalen Wert auf den Default und meldet einen normalen Command an Python; Rotation meldet `operation=adjustment` samt Diff. Bei `EncoderArea` werden Encoder-Actions ausdrücklich blockiert, weil dieser Bereich für SDK-Navigation reserviert ist.
- ActionEditorCommand: als Folder-Inhalt gesperrt (`FOLDER_ACTION_EDITOR_UNSUPPORTED`); der native SDK-Katalogeintrag bleibt unverändert verfügbar. Keine erfundenen Editorwerte.
- Fremde Plugin-/Profil-Actions: keine Ausführung. Optional erhaltene externe Referenzen erscheinen als `unavailable`.

Native `NativeFolderEntry` unterstützt optional `action_parameter`. Fehlend bzw. null hält den bisherigen unparametrisierten Vertrag. Ein ausdrücklich gesetzter Wert muss ein deklarierter Parameter der referenzierten Action sein. Das Legacy-Format bleibt unverändert.

## Übergabeformat `sdk-folders-1`

Eine vollständige, abgeleitete Anzeige-/Navigationsprojektion, keine Actiondefinition:

```json
{
  "version": "sdk-folders-1",
  "plugin_id": "sample.native",
  "revision": 1,
  "folders": [{
    "id": "folder.main",
    "start": "folder.b",
    "nodes": [{
      "id": "folder.b",
      "label": "B",
      "pages": [{
        "id": "page.b",
        "entries": [{
          "id": "placement.link",
          "kind": "link",
          "label": "A / Unterordner",
          "target_id": "folder.a.leaf"
        }]
      }]
    }, {
      "id": "folder.a.leaf",
      "label": "Unterordner in A",
      "pages": [{
        "id": "page.leaf",
        "entries": [{
          "id": "placement.shared",
          "kind": "action",
          "label": "Befehl",
          "action_id": "action.command",
          "action_parameter": "second"
        }]
      }]
    }]
  }]
}
```

Feldregeln:

- Root exakt `version`, `plugin_id`, `revision`, `folders`. Revision ist ein monoton steigender Integer von 0 bis 2^53−1 pro Publisherlauf. Snapshot umfasst jede native Folder-ID exakt einmal, auch leere Folder.
- Folder: `id` ist die native SDK-Folder-ID, `start` eine vorhandene virtuelle Node-ID. `nodes` ist eine nicht leere Liste. Mehrere reale Folder dürfen dieselbe virtuelle Hierarchie mit unterschiedlichen Startpunkten projizieren.
- Node: stabile `id`, nicht leeres `label`, nicht leere `pages`-Liste. Page: stabile `id`, geordnete `entries`-Liste. Page-/Placement-IDs sind innerhalb einer realen Folderprojektion eindeutig. Dasselbe Placement in mehreren realen Foldern muss dieselbe Action-/Parameterbindung haben.
- Action-Entry: `id`, `kind=action`, `label`, `action_id`, optional `action_parameter`. Die native Actiondatei bleibt einzige Definitionsquelle.
- Folder-/Link-Entry: `id`, `kind=folder` bzw. `link`, `label`, `target_id`. Ziel muss im selben Graph vorhanden sein. Back speichert den tatsächlich genommenen Placement-/Origin-/Seitenpfad, nicht den Containment-Parent.
- Offline-Entry: `id`, `kind=unavailable`, `label`, `reason`; keine ausführbare Actionbindung.
- Maximal 48 KiB als JSON, begrenzte Tiefe, keine doppelten Schlüssel oder unbekannten Felder. Ungültige Updates ersetzen den bisherigen gültigen Stand nicht.

Die bestehenden Single-/Auto-/Manual-Seiten werden als bereits aufgelöste Page-Liste übernommen. Die Runtime erfindet keine Geräteslotzahl und berechnet keine Hardwarekapazität. Überlauf einer gelieferten virtuellen Seite bleibt der dokumentierten SDK-Pagination überlassen.

## Konkrete Python-Schnittstelle für AP-FOLDER-002

```python
from dataclasses import asdict
from adapters.logitech.folder_runtime import project_virtual_folders
from adapters.logitech.product import generate_product

# Nur defensive Snapshotdaten übergeben; keine Änderung an den Studio-Ownern.
payload = project_virtual_folders(
    native_snapshot, asdict(extension_store.document),
    entrypoints={"folder.main": extension_store.document.root_id},
    revision=1,
)
plan = generate_product(project_path, output_dir=build_directory,
                        assembly_name="MyPlugin", folder_runtime=payload)
```

`entrypoints` muss jede native Folderdefinition explizit abdecken. Es werden keine SDK-Öffner automatisch erzeugt. Verwaiste lokale Actionreferenzen blockieren diese Laufzeitprojektion; das Studio darf sie weiterhin zur Reparatur erhalten. Externe Referenzen werden als Offlineeinträge erhalten. Ein zusätzlicher Studio-Schreibpfad ist nicht nötig.

## Laufende Updates über den vorhandenen Host

```python
from adapters.logitech.folder_host import FolderRuntimeHost

host = FolderRuntimeHost(project_path, settings, folder_runtime=payload)
host.register_handler("handler.main", "invoke", trusted_handler)
host.start()
# Vollständiger neuer Snapshot; Revision muss steigen.
host.replace_folder_layout(next_payload)
```

Der optionale Host erweitert ausschließlich seine abgeleitete Placement-Zulassungsliste. Er sendet den Layoutstand im signierten Snapshot als `folder_runtime` sowie Folgeänderungen über den bereits vorhandenen Eventjournaltyp `event`, `port=folder.layout`, `report=<payload>`. Es gibt keinen neuen ungeschützten HTTP-Endpunkt. Reconnect erhält den aktuellen vollständigen Stand. Commands werden dadurch nicht erneut ausgeführt.

Für einen rein C#-lokalen vertrauenswürdigen Publisher existiert `FolderRuntimeHub.Replace(json, stream)`. Pro Betrieb genau einen Publisher wählen; `stream` ist dessen Laufidentität, kein Pluginzustand. Gleiche Revision und gleiche Daten sind ein No-op; wiederverwendete Revision mit anderen Daten und rückläufige Revisionen werden abgelehnt. Der Pythonweg ist für externe Aktualisierungen vorzuziehen.

Native JSON und optionale Extensiondatei bleiben Eigentum ihrer bestehenden Sessions. Layoutrevision und Navigation sind flüchtige Transport-/Anzeigezustände. Keine automatische Persistenz von SDK-Actionwerten.

## Membership, Repaint und Navigation

Strukturelle Änderungen rufen `ButtonActionNamesChanged` und `EncoderActionNamesChanged` auf. Bild-/Label-/Wertänderungen rufen ausschließlich die jeweiligen Image-/Value-Notifications auf. Generationstokens ändern sich bei veränderter Membership, Folder-/Seitenwechsel oder ungültig gewordenen Navigationspfaden. Ein reiner Repaint invalidiert keine Tastennamen.

Virtuelles Back, Previous und Next sind eigene sichtbare Folder-Commands. Seitenwechsel verändert den Back-Stack nicht. Bei `None` kommen die dokumentierten SDK-Namen für Up/Left/Right hinzu; das SDK verarbeitet seine Navigation selbst. Bei ButtonArea/EncoderArea bleibt die SDK-Back-Erzeugung beim Host. Virtuelles Back und SDK-Back sind deshalb getrennte Funktionen.

Die SDK-Folderinstanz besitzt ihren Navigationspfad. Die SDK-Doku beschreibt Aktivierung für erste/letzte sichtbare Instanz und liefert in `RunCommand` keine Geräte-ID. Es wird daher keine unabhängige gerätebezogene Navigation behauptet. Load/Unload melden Handler an/ab; Konfiguration im Konstruktor führt keine Dienste aus.

## Verbleibende Hardwareprüfung

Softwaretests verwenden echte generierte Klassen und die installierte SDK-DLL, einschließlich State-/Bildvergleich und beobachteter SDK-Notifications. Sie öffnen keinen realen Folder in Options+. Noch HARDWARE_PENDING: tatsächliche Host-Requery-/Cache-/Seitenindexeffekte nach Membershipwechsel, konkrete Slotgeometrie, zwei physische Seitentasten, mehrere reale Geräte und User-/Plugin-/Global-ICT-Prioritäten in der realen Anzeige. Keine öffentliche Open-API, kein Cross-Plugin-Invoke und keine private HID-/Serviceinjektion werden behauptet.

## 08.11.2026 – Zuordnung zur optionalen Schicht

Diese `sdk-folders-1`-Laufzeit ist eine **optionale Erweiterung**, keine neue SDK- oder Python-Bridge-Semantik. Die Implementierungen `runtime_projection.py` und `host.py` befinden sich unter `src/extensions/shared_folders/`; die C#-Templatequelle ist `src/extensions/shared_folders/templates/NativeFolders.cs.in`. Ehemalige `adapters.logitech.folder_runtime`- und `folder_host`-Pfade sind nur noch kompatible Re-Exports. Der SDK-Generator importiert die optionale Implementierung ausdrücklich. Das allgemeine `Bridge.cs.in` transportiert jetzt nur generische authentisierte `SnapshotReceived`-/`JournalEventReceived`-Benachrichtigungen; erst die Extension interpretiert `folder_runtime` beziehungsweise `folder.layout`.

Die projektspezifische Autoren-Extension bleibt weiterhin optional; der aktuelle Native-Generator nutzt zur Wahrung des Softwarevertrags noch den gemeinsamen Folderaufsatz. [Vollständige Schichtengrenzen](sdk-bridge-schichtentrennung.md) · [API-Abdeckung und ausstehende reine Python-Methoden](../specifications/sdk-python-api-checklist.md).
