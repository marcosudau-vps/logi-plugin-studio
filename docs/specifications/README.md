# Spezifikationen und Entwurfsstatus

> **Aktuell:** [SDK-nativer Modellabgleich v0.1](sdk-native-modellabgleich-v01.md) bewertet den bestehenden Core gegen das führende Logitech-Modell gemäß [ARCH-ADR-001](../decisions/ARCH-ADR-001.md). Dies ist ein Analyse-/Migrationsdokument, kein neues Projektschema.

Die maschinenlesbaren Artefakte liegen absichtlich zentral unter [`schemas/`](../../schemas/) und [`component_types/`](../../component_types/) statt als unsichtbare Beilagen in Agenten-Arbeitsakten.

- [`project_v0_1_draft.schema.json`](../../schemas/project_v0_1_draft.schema.json): P0-Entwurf, **kein freigegebenes Format**.
- [`project_v0_1_draft.json`](../../examples/project_v0_1_draft.json): zum Entwurf passende Beispielinstanz.
- [`beispiel_plugin_abstrakt_v0_2.json`](../../examples/beispiel_plugin_abstrakt_v0_2.json): historisches Konzeptbeispiel, **nicht identisch mit dem aktuellen Schema**.
- [`component_types/`](../../component_types/README.md): Entwurfsmanifeste; keine freigegebenen produktiven Module.

Änderungen an den Entwurfsregeln erfordern Aktualisierung des [Entscheidungsregisters](../08_Entscheidungsregister.md), der ADRs und passender Tests.

## Logitech-Profil- und Aktionsmodell (aktualisiert 05.11.2026)

- **Aktuelle verbindliche Planungsgrundlage:** [Modell v0.2 nach AP-PROF-001-Abnahme](logitech-profil-und-aktionsmodell-basis-v02.md). Sie trennt native SDK-Definition, profilbezogene Instanz, Katalogansicht, Workspace, Profilordner und plugin-gesteuerten Dynamic Folder. **Interne Profildateien bleiben nur empirisch belegt und sind keine freigegebene Schreib-API.**
- [Frühere Modellbasis v0.1](logitech-profil-und-aktionsmodell-basis-v01.md): historische Begriffs- und Forschungsplanung.
- Die Forschung ist **COMPLETE**, unabhängig abgenommen und im Schwesterprojekt `P:\LokaleProjekte\logi_actions_sdk\logi-actions-sdk-rec\work\archive\RUN-20261104-PROF001-01` archiviert. Der alte [AP-RESEARCH-001-Entwurf](../../work/planning/AP-RESEARCH-001-logitech-profilmodell.md) ist **nicht** erneut auszuführen.
