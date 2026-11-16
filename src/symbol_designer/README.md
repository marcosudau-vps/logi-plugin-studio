# src/symbol_designer

AP-WIDGET-001, READY_FOR_REVIEW; keine Selbstabnahme. Vollständige Dokumentation, Tests und
Einschränkungen: [`work/widget-lab/icon-designer-v1/README.md`](../../work/widget-lab/icon-designer-v1/README.md).

Start: `python tools\run_symbol_designer_lab.py [vorlage.ict] [--output DIR] [--library DIR]`.

- `ict.py`: GUI-freies natives ICT-Modell (verlustfreies Laden/Speichern inkl. Formatierung, unbekannte
  Felder bleiben erhalten), Layoutvorlagen, Stilübertragung ohne Inhaltsänderung, Bildklassifikation.
- `render.py`: ein Renderer für Zeichenfläche, PNG 50/80/116 und SVG; Action-Symbol-Export; Bildimport
  mit nachvollziehbarer Konvertierung.
- `library.py`: GUI-freier, nur lesender Scanner für Logitech-Icon-Pakete (`LOGI_ICON_LIBRARY_ROOT`).
- `widget.py`, `canvas.py`, `library_panel.py`, `dialogs.py`, `ui.py`: das wiederverwendbare
  `SymbolDesignerWidget`.
- `lab.py`: Symbol Designer Lab – Testhülle ohne eigene Designerlogik.

Kein eigenes Ebenenformat, keine Änderung an `core`, `library` oder am C#-Generator.
Tests: `python -m unittest discover -s tests -p "test_symbol_designer_*.py"`.
