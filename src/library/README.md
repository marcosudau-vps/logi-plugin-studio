# src/library

> **Architekturziel 03.11.2026:** [ARCH-ADR-001](../../docs/decisions/ARCH-ADR-001.md). Die vorhandenen Projekt- und Autorenmodelle gelten als Kompatibilitätsbasis; künftige Fachsemantik kommt aus nativen Logitech-Verträgen und nicht aus eigenständigen abstrahierten Pflichtentitäten.

Autorenmodell und Projektvorlagen auf dem bestehenden `core.Project`.

`document.py`: transaktionale Aenderungen, stabile referenzielle ID-Renames,
referenzgeschuetzte Loeschung, View-Duplikation mit neuen Placement-IDs,
Undo/Redo, atomare JSON-Saves und erkennbare externe Diskkonflikte.
Unbekannte/ungueltige Felder werden nicht still entsorgt. Kein zweites
Projektformat; das Schema bleibt `0.1-draft`.

`templates.py`: neutrales Callback-Projekt mit zwei frei umbenennbaren
Aktionen, Hosthandler, component-scoped State und Presentation. Die konkrete
Toggle-Anwendung ist ausschliesslich `examples\first_plugin\host.py`;
Projektdaten fuehren keine Skripte aus.

Komponententypen kommen aus `component_types`; neue SDK-Typen benoetigen
ausser einem Manifest eine passende Adapterimplementierung.

`presentation.py`: optionale, adapterunterstuetzte Presentation-Einstellungen
`image_fit` (stretch/contain) und `font_size` (Ganzzahl 6..48 bei 116px).
Qt-Preview und Produktgate teilen den Vertrag; das alte Projektformat und
bei fehlenden Feldern die alte Darstellung bleiben erhalten.

Tests: `python -m unittest discover -s tests -p test_studio_document.py`.
