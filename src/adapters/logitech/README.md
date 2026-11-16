# src/adapters/logitech — Logitech-SDK-Adapter

> **Neue Architekturleitlinie 03.11.2026:** Das Logitech SDK ist künftig fachlich maßgeblich ([ARCH-ADR-001](../../../docs/decisions/ARCH-ADR-001.md)). Der nachfolgend beschriebene Code ist der **bisherige generische Adapter-/Generator-IST-Stand**; fehlende Action-Parameter, Multistate, ICT und andere native SDK-Funktionen stehen im [Gap-Register](../../../docs/specifications/sdk-native-modellabgleich-v01.md). Keine automatische Umstellung durch diese Dokumentation.

## Aktuelle Produkterweiterung FINAL-PRODUCT-01

`product.py` baut auf dem unabhaengig abgenommenen BUILD_ONLY-Pfad auf,
ersetzt dessen APIs/Tests aber nicht. `tools\run_product.py` ist der neue
Produkt-Einstieg; `tools\run_logitech_adapter.py` bleibt der alte Pfad.

| Neue Funktion | Evidenz / Grenze |
|---|---|
| Authentisierte C#-HTTP-Bridge und State-Mirror | echte C#-/Python-Prozesse inkl. stale, Restart, malformed Snapshot, kein Replay |
| LCD-Text, PNG, Varianten und SDK-Notifications | echte SDK-Signaturen/Builds; Anzeige am Geraet HARDWARE_PENDING |
| Views/Placements/DynamicFolder | alle logischen Mitglieder, SDK-ButtonArea-Pagination; Geraet HARDWARE_PENDING |
| Eigener Development-Link und byteidentischer Rollback | Fake-Verzeichnis-Tests; reale Installation NICHT ausgefuehrt |
| Parameter, Adjustments, Multistate, Runtime-Membership | NOT_YET_SUPPORTED, explizite Capability-Gates |

`templates` enthaelt generierten Transport, SDK-Darstellung und Testgegenstand.
Produktbuilds verifizieren bekannte Sourcebytes, deaktivieren fremde ancestor-
Build-Imports und Wildcard-C#-Includes. Private Verbindung erst nach dem Build
provisionieren; sie ist kein Projektfeld und kein Quellarchivbestandteil.
Development-Pakete enthalten eigene DLL, Connection, SDK-Metadaten und
Ownership-/Hashmarker. Fremde/veraenderte/unklare Inhalte blockieren.

[Benutzerhandbuch](../../../docs/13_Benutzerhandbuch.md) und
[PROPOSED-Produktentscheidung](../../../docs/decisions/PRODUCT-ADR-001.md).
Keine Service-/Profilsteuerung und keine Selbstabnahme.

---

## Historischer AP-LOGI-001 BUILD_ONLY-Pfad

Dieser Adapter übersetzt **validierte** `core.command_action`-Instanzen eines
Projekts in ein minimales C#-Quellprojekt für das Logitech Plugin SDK und baut
es gegen die real installierte `PluginApi.dll`.

**Grenze des Laufs:** `BUILD_ONLY` / `CALLBACK_PENDING`. Es wird gebaut, nicht
installiert. Es gibt keinen Transport, keine Authentisierung, keinen
Dienst-Neustart und keine Registrierung (`.link`).

## Fähigkeitsmatrix (ehrlich getrennt)

| Fähigkeit | Status | Beleg |
| --- | --- | --- |
| `Plugin`-Klasse (`HasNoApplication`, `UsesApplicationApiOnly`, `Load`/`Unload`) | `BUILD_PROVEN` | `dotnet build`, 0 Warnungen/0 Fehler, RUN-AP-LOGI-001-01 |
| statisches `PluginDynamicCommand` je `core.command_action` | `BUILD_PROVEN` | dito, 1-Aktion- und 4-Aktionen-Projekt |
| `RunCommand` → lokaler `IActionDispatch`-Hook | `CALLBACK_PENDING` | Hook protokolliert nur (`Debug.WriteLine`), kein Transport |
| `metadata/LoupedeckPackage.yaml` | `LAB_OBSERVED` | Form aus dem SDK-Lab übernommen; wird erzeugt, **nicht** installiert |
| `supportedDevices: LoupedeckExtendedFamily` | `LAB_OBSERVED` | Platzhalter aus dem Lab, **kein** Hardware-Nachweis |
| Installation / `.link` / Service-Neustart | `NOT_YET_SUPPORTED` | bewusst nicht implementiert |
| `PluginDynamicFolder`, Views, Placements, Präsentationen | `NOT_YET_SUPPORTED` | nur im Manifest als „nicht erzeugt“ vermerkt |
| `PluginDynamicAdjustment` (Drehregler) | `NOT_YET_SUPPORTED` | – |
| Kommandoparameter, `GetCommandImage`, Assets, Lokalisierung | `NOT_YET_SUPPORTED` | – |
| Anwendungs-Plugins (`ClientApplication`) | `NOT_YET_SUPPORTED` | – |
| echte Hardware-Ausführung einer Aktion | `HARDWARE_PENDING` | nie behauptet |
| Host-Transport (HTTP/IPC/Socket), Authentisierung | `NOT_YET_SUPPORTED` | – |

Die Matrix steht als Code in [`capabilities.py`](capabilities.py) und wird in
jedes `generated.manifest.json` geschrieben.

## Aufbau

| Modul | Aufgabe |
| --- | --- |
| `gate.py` | Validierungsgate + Auswahl: lädt über `core.io`, prüft mit `core.registry`/`core.validate`, wählt `core.command_action` |
| `naming.py` | deterministische C#-Bezeichner, Namespaces, escaped Literale (C#/YAML) |
| `codegen.py` | reine Planung + sicheres Schreiben des Quellbaums |
| `build.py` | isolierter `dotnet build`, verweigert Installationsprojekte |
| `cli.py` | `capabilities`, `inspect`, `generate [--build]` |

Es gibt **kein zweites Projektmodell und kein zweites Schema**: das Gate ruft
ausschließlich die bestehenden `core`-Funktionen auf.

## Benutzung

```text
python tools/run_logitech_adapter.py capabilities
python tools/run_logitech_adapter.py inspect   --project tests/fixtures/logitech/project_four_actions.json
python tools/run_logitech_adapter.py generate  --project <projekt.json> \
    --plugin-id studio.example --assembly StudioExample \
    --out work/tmp/studio-example --build
```

## Garantien des Generators

* **Determinismus:** keine Zeitstempel, keine Zufallswerte, sortierte
  Dateireihenfolge. Derselbe Input erzeugt byte-identische Quellen; ein zweiter
  Build derselben erzeugten Quellen liefert im Nachweis dieselbe DLL-SHA-256.
* **Eindeutige Namen:** `<Präfix>_<LesbarerStamm>_<sha256-8>` je Objekt-ID.
  Der Digest hängt nur an der ID, nicht am Umfeld; ähnliche IDs (`action.a-b`,
  `action.a_b`, `action.a.b`) kollidieren daher nie.
* **Escaping:** jede Zeichenkette erreicht C# nur über `csharp_literal`
  (Anführungszeichen, Backslash, CR/LF/Tab, Steuerzeichen, U+2028/U+2029,
  unpaarige Surrogate). Unicode bleibt UTF-8. Längen werden nur bei
  *Bezeichnern* gekappt, nie bei Anzeigenamen.
* **Injektionsschutz:** IDs werden auf `[A-Za-z0-9_]` gefaltet, Freitext nur
  als Literal eingesetzt; Shell-Aufrufe gibt es nicht (`subprocess` ohne
  `shell=True`, ausschließlich `dotnet`).
* **Kein stiller Verlust:** alles, was nicht erzeugt wird (Views, Placements,
  Präsentationen, Assets, Bindings, States, fremde Komponententypen), steht im
  Manifest unter `not_generated`.

## Pfad- und Installationsschutz

`check_output_dir` verweigert Laufwerkswurzeln, das Home-Verzeichnis, das
Projektwurzelverzeichnis und dessen Vorfahren, `src/`, `tests/`,
`component_types/`, `schemas/`, `docs/`, `references/`, jeden Pfad mit dem
Segment `LogiPluginService` sowie `%LOCALAPPDATA%\Logi`, `%APPDATA%\Logi`,
`%PROGRAMDATA%\Logi`, `%PROGRAMFILES%\Logi` und `%PROGRAMFILES(X86)%\Logi`.
Ein vorhandenes, nicht leeres Zielverzeichnis wird nur akzeptiert, wenn es ein
Generator-Marker mit derselben Plugin-ID enthält; alte, nicht mehr erzeugte
Dateien werden vorher entfernt.

`build.py` verweigert jedes Projekt mit `InstallDevelopmentPlugin`,
`WriteLinesToFile`, `$(PluginDir)`, `LocalAppData`, `.link` oder irgendeinem
MSBuild-`<Target>`-Element, bevor `dotnet` gestartet wird.

## Native-First-Vertrag

`native.py` validiert `logitech-native-1` und projiziert nur für den bestehenden
Python-Host auf den technischen Core-Graphen. Der Generator erzeugt aus dem
Originaldokument SDK-native Commands, Multistate-States, Adjustments,
ActionEditor-Controls und Folder. Der native Action Editor generiert derzeit Textbox,
Checkbox, TextArea, FileSelector, DirectorySelector, Slider und NumericUpDown;
dynamische Listbox-Callbacks und Spezialcontrols bleiben gesonderte Capability-Gaps. `RunCommand(String actionParameter)` reicht
den Parameter getrennt von `placement_id` durch den signierten Host-Wire.

Native PNG-/SVG-/ICT-Quellen und Lizenzen werden nach validierter relativer
Quelle in die SDK-Paketpfade geschrieben; Multistate-Bilder werden als
Assembly-Ressourcen eingebettet. Die installierte SDK-Version besitzt an
`PluginMultistateDynamicCommandState` keinen öffentlichen LED-Farb-Setter.
Nicht-leere `led_color`-Angaben werden deshalb mit einer expliziten
Capability-Meldung abgewiesen, statt eine nicht vorhandene API zu erfinden.
Der Generator installiert nichts und startet keinen Logitech-Dienst neu.
