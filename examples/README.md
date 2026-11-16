# Beispiele (unterschiedliche Reifegrade)

- [`beispiel_plugin_abstrakt_v0_2.json`](beispiel_plugin_abstrakt_v0_2.json): älteres illustratives Modell, **nicht** kompatibilitätsgeprüft gegen P0-Schema.
- [`project_v0_1_draft.json`](project_v0_1_draft.json): mit dem P0-Core-Spike geprüftes Projektbeispiel, dennoch Entwurf.

Keine der beiden Dateien ist ein fertiges Logitech-Plugin oder eine freigegebene Projektformatversion.

## Aktuelles Produktbeispiel

`first_plugin\project.json`: zwei frei bearbeitbare Aktionen, ein expliziter
Python-Handler, component-scoped State und zwei Views; die zweite View
verwendet zehn Placements derselben zwei Aktionen.
`first_plugin\host.py` ist ein eigenständiges vertrauenswürdiges Python-
Programm, kein aus dem JSON geladener Code.

Start: `python tools\run_studio.py examples\first_plugin\project.json`.
Build/Host/CLI-Press: [Benutzerhandbuch](../docs/13_Benutzerhandbuch.md).

## SDK-natives Beispiel

`project_logitech_native_v1.json` demonstriert die vier gegen die installierte
PluginApi gebauten Action-Typen, native Parameter, feste Multistate-Zustände,
Adjustment-Grenzen, ActionEditor-Felder sowie geräteabhängige
Folder-Navigation. Es lässt sich ohne Installation erzeugen und bauen:

```text
python tools/run_product.py generate --project examples/project_logitech_native_v1.json --out work/tmp/native-example --assembly NativeExample --build
```
Echte Prozess-/SDK-Buildprüfung; neue Hardwareausführung **HARDWARE_PENDING**.
