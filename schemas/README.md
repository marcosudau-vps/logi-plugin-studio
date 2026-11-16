# Schemaentwürfe

> **Wichtig 03.11.2026:** Die heutigen Projektschemas sind **historisch implementierte Draft-/Kompatibilitätsverträge**, keine bereits verabschiedete SDK-native Modellierung. Neuer Vorrang: [ARCH-ADR-001](../docs/decisions/ARCH-ADR-001.md), offene Migration: [SDK-Abgleich](../docs/specifications/sdk-native-modellabgleich-v01.md).

`project_v0_1_draft.schema.json` ist ein P0-Entwurf zu JSON Schema Draft 2020-12. Die P0-Validatorimplementierung in Python deckt **nicht** das gesamte JSON-Schema ab und sollte nicht als vollständiger Konformitätsvalidator angesehen werden. Statusdetails: [Entscheidungsregister](../docs/08_Entscheidungsregister.md).

`project_v0_1_core.schema.json` ist der P1-Core-Arbeitsentwurf aus AP-CORE-001 (Lauf `RUN-AP-CORE-001-01`), ebenfalls **DRAFT, kein freigegebenes Austauschformat**. Scope-/Authority-Enums darin sind ausdrücklich nur Kandidaten (P0-ADR-005 mit Reichweitenbegrenzung); keine Migration ohne eigene Entscheidung.

`logitech_native_v1.schema.json` beschreibt den schmalen, SDK-nativen
Projektvertrag der Native-First-Migration. Er bildet direkt
`PluginDynamicCommand`, `PluginMultistateDynamicCommand`,
`PluginDynamicAdjustment`, `ActionEditorCommand`, Parameter, feste
Multistate-Indizes und Folder-Navigation ab. Die Python-Validierung in
`src/adapters/logitech/native.py` bleibt die ausführbare Referenz. Bestehende
`0.1-draft`-Dateien werden nicht umgeschrieben und bleiben gültige Eingaben.
