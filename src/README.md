# Implementierung

> **Zielarchitektur 03.11.2026:** [ARCH-ADR-001](../docs/decisions/ARCH-ADR-001.md) schreibt **SDK-native Fachsemantik und minimale Python↔C#-Bridge** für künftige Entwicklung vor. Die unten genannten Module beschreiben den bisherigen, weiterhin funktionsfähigen Implementierungsstand. [Mapping und Code-Gaps](../docs/specifications/sdk-native-modellabgleich-v01.md).

- [`core_spike/`](core_spike/README.md) – existierender **P0-Experimentcode**, nicht das P1-Produktmodell
- [`core/`](core/README.md) – statischer Core, unabhängig abgenommen
- [`runtime/`](runtime/README.md) – abgenommene Spikes/StateStore plus neue lokale Host-/Wire-Erweiterung
- [`library/`](library/README.md) – transaktionales Autorenmodell und Vorlagen
- [`studio/`](studio/README.md) – echte PySide6-Widgets-Oberfläche mit IO-Workern
- [`adapters/logitech/`](adapters/logitech/README.md) – alter BUILD_ONLY-Pfad plus Produktgenerator/Bridge/Deployment
- `delivery/` – fail-closed Review-Quellarchivexport, kein Vollprojektbackup
- [`symbol_designer/`](symbol_designer/README.md) – AP-WIDGET-001: eigenständiges `SymbolDesignerWidget` für native ICT-Icon-Vorlagen plus Symbol Designer Lab, READY_FOR_REVIEW

FINAL-PRODUCT-01 ist unabhängig für den Software-MVP freigegeben.
Neue Folgelieferung FINAL-PRODUCT-02 **READY_FOR_REVIEW**, Gesamtprojekt
**PARTIAL**, keine Selbstabnahme. [Benutzerhandbuch](../docs/13_Benutzerhandbuch.md).

Die funktionsfähigen SDK-Lab- und alten Studio-Implementierungen sind bewusst als historische Quellen unter `references/prototypes/` archiviert, damit die neue Architektur nicht mit den bisherigen Demo-Komponenten verwechselt wird.
