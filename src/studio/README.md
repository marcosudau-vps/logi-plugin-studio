# src/studio

Echte PySide6-Widgets-Autorenoberflaeche, READY_FOR_REVIEW; keine Selbstabnahme.

Start vom Projektroot: `python tools\run_studio.py`, optional Projektdatei.
Alternativ `.\start_studio.ps1`. [Benutzerhandbuch](../../docs/13_Benutzerhandbuch.md).

- `app.py`: Projektbaum, Eigenschaften, Layout/Bilder, Validierung,
  Build/Deployment, Host-Diagnose und expliziter Projekt-JSON-Editor.
- `fields.py`: Manifest-Konfiguration, State-/Binding-/Placement-/Varianten-
  Formulare; unbekannte Daten bleiben erhalten, Core-Fehler verlangen
  explizite JSON-Korrektur statt automatischer Normalisierung.
- `images.py`: proportionale transparente PNG-Exporte 50/80/116px und Preview.
- `workers.py`: begrenzte QThread-Build-/HTTP-/Dry-Run-/Rollback-/Export-Auftraege mit Signals.
- `native_ict_binding.py`: minimaler SDK-Action-/Keypad-Slot-zu-ICT-Koordinator;
  konfliktgeschützte native Vorlagenspeicherung, ohne zweites Projektmodell.
- `native_symbol_dialog.py`: integriert das fertige `SymbolDesignerWidget`
  im Studio als Vorschau (schreibgeschützt) mit explizitem Edit-Modus.
  [NF-16-Nachweise](../../work/migrations/nf16-symbol-integration-20261103/README.md).

FINAL-PRODUCT-02: speicherbare Dry-Runs, Pruefung vorhandener eigener Pakete,
Rollbackvorschau ohne Backupbytes und nur nach exakter ID plus Dateibestaetigung.
Build-/Deploymentauftraege werden nicht gleichzeitig auf Pakete losgelassen.
Alte Projektbuilds sind kein aktueller Projektdryrun. Der sichere Export ist
Review-Quellarchiv, kein Backup beliebiger geoeffneter Projekte.
Presentations unterstuetzen optional `image_fit` und `font_size`; alte
Projekte behalten ihre Standarddarstellung.

Das Studio verwendet `library.ProjectDocument` um das bestehende `core.Project`.
Keine QML-/Weboberflaeche, kein zweites Projektmodell und keine implizite
Script-/Serviceausfuehrung. Builds speichern zuerst den angewandten Entwurf,
verwenden dann einen unveraenderlichen Snapshot. Worker-Signals erreichen den
GUI-Thread; Schliessen waehrend IO verlangt dessen begrenzten Abschluss.

Tests: `python -m unittest discover -s tests -p test_studio_ui.py` sowie `python -m unittest discover -s tests -p test_nf16_symbol_integration.py`.
Headless Qt-Tests setzen `QT_QPA_PLATFORM=offscreen` und enthalten einen
echten SDK-Worker-Build inklusive exportiertem PNG. Ohne Qt/SDK explizite Skips.

`keypad_contract.py` enthält die transienten SDK-nativen DTOs für gemeldete
Content-/Navigation-Slots und die expliziten Modi `preview` (Standard, ohne
Editieren) und `edit`. Slotzahlen werden nicht als „8 plus Back“ geraten.
`images.py` leitet Qt-Previews ausschließlich aus dem transient aufgelösten
`ResolvedVisual` ab; es entsteht kein zweiter persistierter Darstellungszustand.

**NF-16: Symbol-Designer:** In der Studio-Toolbar „Native ICT / Symbol-Designer“
wählen, danach ein natives `logitech-native-1`-Projekt und die Aktion. Die
Vorlage öffnet zuerst schreibgeschützt; erst nach „Bearbeiten aktivieren“ wird
„ICT im Projekt speichern / zuordnen“ möglich. Alternativ:
`python tools/run_native_symbol_studio.py examples/project_logitech_native_v1.json`.
Die eingebettete Version nutzt das unveränderte `SymbolDesignerWidget` und
schreibt nur echte ICT-Dateien sowie erforderliche native Projektreferenzen.
Der bisherige Editor für `0.1-draft` bleibt separat und kompatibel.
