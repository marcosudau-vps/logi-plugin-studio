# Schichtentrennung: Original-SDK, Python-Bridge und optionale Shared-Folder-Funktionen

**Stand: 08.11.2026.** Verbindlich: [ARCH-ADR-001](../decisions/ARCH-ADR-001.md), **Native First – Minimal Bridge – Optional Extensions**. Der jeweils belegte Implementierungsstand ist in der [SDK-/Python-API-Checkliste](../specifications/sdk-python-api-checklist.md) erfasst.

## Eigentums- und Abhängigkeitsrichtung

```text
                     Optionales Produktkonzept
          src/extensions/shared_folders/   (eigene Fachlogik)
              |    nutzt SDK-native Action-Identitäten
              |    und neutrale, authentisierte Transportevents
              v
   Python: src/runtime/host.py + src/runtime/wire.py
              ^  (Aufrufe, Parameter, Zustände, Events,
              |   Auth, Reconnect, Resultate)
              v
   C#: Bridge.cs.in  (nur generisches IPC/Callback/State-Transport)
              ^
              |  native SDK-generierte Actionklassen
              v
             Logitech PluginApi.dll / Plugin Service
```

Das Studio und der Generator orchestrieren diese Komponenten. Das optionale SharedFolder-Modell darf die SDK-Action- und SDK-State-Autorität nicht ersetzen.

## Basis-Bridge: erlaubt und verboten

**Erlaubt:** Verbindung zum authentisierten Python-Host, Heartbeat/Poll, Snapshots, State-/Commandtransport, Original-Actionparameter, Adjustmentdiffs, Editor-Parameterwerte, Versions-/Sitzungs-/Revisionsschutz, C#-Ereignisse ohne spezielles fachliches Schema, Fehlermeldungen und Reconnect.

**Nicht in der Basis-Bridge:** `sdk-folders-1`, `folder_runtime`, `folder.layout`, virtuelle Knoten, Links, Seiten, Back-Stack, Fremdplugin-Discovery, Peer-Subscriptions, eigene Action-/State-Logik oder ein zweiter SDK-API-Ersatz.

Seit dieser Trennung bietet die C#-Basis `SnapshotReceived(runtimeId, response)` und `JournalEventReceived(runtimeId, event)` für **authentisierte, aber fachlich uninterpretiert transportierte** Nachrichten. Der normale `Bridge.Dispatch(...)`-Pfad und die C#-Action-Callbacks wurden nicht umdefiniert. Snapshotempfang bleibt vor dem Zustandscommit prüfbar; Journalereignisse werden nach dem geordneten Journal verarbeitet. Optionale Subscriber können ein ungültiges Layout ausdrücklich zurückweisen.

## Optionale Erweiterung: eigener Code-Owner

- `src/extensions/shared_folders/runtime_projection.py`: Qt-freie Validierung und Abbildung `virtual-folders-1` → `sdk-folders-1`; keine neue Actiondefinition.
- `src/extensions/shared_folders/host.py`: optionaler `FolderRuntimeHost`; nutzt den bestehenden signierten Python-Hosttransport. Kein zusätzlicher offener Port oder Pflichtdaemon.
- `src/extensions/shared_folders/templates/NativeFolders.cs.in`: FolderRuntimeHub, virtuelle Navigation, Membership-/Repaint-Notifications und das alleinige Auswerten von `folder_runtime` / `folder.layout`.
- `src/studio/virtual_folders/`: optionale Studio-/Autorenwerkzeuge für `.vfolders.json` mit separatem Writer.
- `src/adapters/logitech/folder_runtime.py` und `folder_host.py`: **nur rückwärtskompatible Re-Exports**, keine eigenständige Implementierung mehr.

Für native Plugins initialisiert `Plugin.Load()` den optionalen Folder-Empfänger **vor** dem generischen Bridge-Start. Dadurch werden Host-Snapshots/Events nicht wegen verzögerter statischer Initialisierung verpasst. Der Testhost verwendet denselben Bootstrap.

Die Native-Actionklasse besitzt weiterhin ihre SDK-State-Haltung; Folder-Aktionen delegieren an dieselben SDK-Actioninstanzen. `FolderCall` transportiert nur die aktuelle Placement-ID als technische Korrelation und verbleibt in der optionalen C#-Folder-Schicht.

## Ausdrückliche Kompatibilitätsgrenzen

1. **Keine stillschweigende API-Vollständigkeit:** Der derzeitige Python-Host transportiert ausgewählte SDK-Callbacks. Er stellt noch **keine vollständige öffentliche Python-Fassade** für jede öffentliche `PluginApi.dll`-Methode bereit. Die getrennte [Checkliste](../specifications/sdk-python-api-checklist.md) verhindert falsche Häkchen.
2. **SDK-Folder-Codegenerator noch nicht vollständig opt-in:** Aus Kompatibilitätsgründen erzeugt `generate_product` für jedes vorhandene `logitech-native-1`-Projekt weiterhin den SDK-Folder-Aufsatz. Ein gespeichertes virtuelles Sidecar ist dagegen optional, und das ältere `0.1-draft`-Format bleibt ohne Folder-Aufsatz. Für eine zukünftige tatsächlich **erweiterungsfreie native Folder-Generierung** ist ein gesonderter, SDK-nativer Basis-Foldergenerator mit identischem Actionverhalten/Tests erforderlich. **Nicht als bereits erledigt abhaken.**
3. **Keine Cross-Plugin-Föderation implementiert:** Discovery, Join/Leave, Peer-Invoke, Subscriptions und verteilte Ausfallprüfung gehören erst in die optionale Erweiterung, nicht in `Bridge.cs.in`.
4. **Keine volle Host-/Hardwarefreigabe:** SDK-Klassen sind softwareseitig gegen die installierte DLL testbar; ein echter Logitech-Geräte- und Service-Test bleibt gesondert.
5. **Altimporte bleiben gültig**, bis ihre externen Aufrufer umgestellt sind. Eine entfernte Kompatibilität wäre ein separates API-Breaking-Change.

## Prüfregeln

- `tests/test_sdk_bridge_separation.py` sperrt Folder-spezifische Symbole in der Basis-Bridge, prüft generierte SDK-/Legacyquellen und die Identität alter Python-Importe.
- `tests/test_review_folder_runtime.py` prüft dieselben nativen SDK-Aktionsinstanzen, Parameter, Multistate, Adjustment, C#-Snapshots/Notifications, Seiten, Back, Reconnect, Stale- und Fehlerfälle.
- `tests/test_native_folder_build_integration.py` prüft den Studio→Optional-Extension→SDK-Build über den wirklichen Worker und die lokal installierte DLL.
- Vollständige Suite: `$env:QT_QPA_PLATFORM='offscreen'; python tools/run_tests.py`.
- Vor jeder Erweiterung zuerst SDK-XML/DLL-Signatur, dann generische Python-API-Abbildung, anschließend optionale Komfortfunktion; Häkchen der Checkliste nur mit konkretem Code und Testnachweis setzen.
