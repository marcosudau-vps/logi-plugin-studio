# Architekturentscheidungen (ADR) – verabschiedete P0-Baseline

> **Vorrangige Folgerichtung (03.11.2026):** [ARCH-ADR-001](ARCH-ADR-001.md) ist als **SDK-native Zielarchitektur** beschlossen. Sie überholt insbesondere die frühere, fachlich führende SDK-unabhängige Core-Ausrichtung. P0-/RT-ADRs bleiben als historische, nach ihrem jeweiligen Geltungsbereich weiterhin relevante Beschlüsse erhalten; keine stillschweigende Code- oder Projektformatmigration.

**Freigabe am 30.10.2026:** Der Nutzer hat ausdrücklich alle sieben P0-ADRs angenommen: **001–004 und 006–007 ohne inhaltliche Änderung, 005 mit eingeschränktem Geltungsbereich**. Entscheidend ist jeweils der Volltext der verlinkten ADR einschließlich ihrer Grenzen.

| ID | Gegenstand | Status |
| --- | --- | --- |
| [P0-ADR-001](P0-ADR-001.md) | Stabile IDs und strukturierte Referenzen | `ACCEPTED` |
| [P0-ADR-002](P0-ADR-002.md) | Persistierte Entitäten versus Runtime | `ACCEPTED` |
| [P0-ADR-003](P0-ADR-003.md) | Command/Event/State und Result-Semantik | `ACCEPTED` |
| [P0-ADR-004](P0-ADR-004.md) | JSON Schema Draft 2020-12, konservative Portprüfung | `ACCEPTED` |
| [P0-ADR-005](P0-ADR-005.md) | Ein autoritativer Writer je konkretem State-Scope; Runtime-Scope-Details offen | `ACCEPTED_WITH_SCOPE_LIMIT` |
| [P0-ADR-006](P0-ADR-006.md) | Views/Placements und Runtime-Overrides | `ACCEPTED` |
| [P0-ADR-007](P0-ADR-007.md) | Core-/Adaptervalidierung und strikte Fehler | `ACCEPTED` |

**Statussemantik:** `ACCEPTED` = Architektur-Baseline, kein Implementierungsnachweis; `ACCEPTED_WITH_SCOPE_LIMIT` = nur ausdrücklich aufgelistete Grundsätze verbindlich. Das Metamodell `MM-001..010` ist dadurch **nicht pauschal angenommen**. Das konkrete Austauschformat unter `schemas/` bleibt `DRAFT`.

Freigabe, Alternativen und Folgen: [Beschlussprotokoll](../12_P0_Freigabe_2026-10-30.md). Zentrale Statusquelle: [Entscheidungsregister](../08_Entscheidungsregister.md). Neue oder ersetzende ADRs bleiben abnahmebedürftig; [Vorlage](../../work/templates/ADR_VORLAGE.md).

## Freigegebene Runtime-Grundsatzentscheidungen (30.10.2026)

| ADR | Gegenstand | Status |
| --- | --- | --- |
| [RT-ADR-001](RT-ADR-001.md) | Runtime-/Session-Identität und V1-Plugin-Betrieb | `ACCEPTED` |
| [RT-ADR-002](RT-ADR-002.md) | Runtime-/Component-/Placement-Scopes; ein Writer | `ACCEPTED` |
| [RT-ADR-003](RT-ADR-003.md) | Snapshot, Deltas, Epoch/Revision, Wertqualität | `ACCEPTED` |
| [RT-ADR-004](RT-ADR-004.md) | Commands, Events, Results, sichere Fehlerbehandlung | `ACCEPTED` |
| [RT-ADR-005](RT-ADR-005.md) | Lifecycle/Health getrennt von fachlichen States | `ACCEPTED` |
| [RT-ADR-006](RT-ADR-006.md) | Fachneutraler Core, Bibliothek, SDK-/Python-Adapter | `ACCEPTED` |

**Präzisierung:** P0-ADR-005 gilt weiterhin; durch RT-ADR-002 sind die drei fachlichen V1-Scopes und Rollen nun als Grundsatz geklärt. Konkrete Scope-Adressen, Persistenz- und verteilte Autoritätsprotokolle bleiben separate technische Spezifikationsarbeit. Das bisherige Metamodell und das Projektformat sind dadurch nicht vollständig freigegeben.

## Neue Produktentscheidungen: nicht unabhängig abgenommen

| ADR | Gegenstand | Status |
|---|---|---|
| [PRODUCT-ADR-001](PRODUCT-ADR-001.md) | Lokales HTTP, Authentisierung, Snapshot/Command-Lifecycle, Ressourcenlimits | `PROPOSED` |

Diese Implementierung ersetzt keine ACCEPTED-ADR. Aktueller Produktumfang
und Nachweise stehen im [Benutzerhandbuch](../13_Benutzerhandbuch.md).

## Neuere übergeordnete Architekturentscheidung

| ADR | Gegenstand | Status |
|---|---|---|
| [ARCH-ADR-001](ARCH-ADR-001.md) | Native Logitech-SDK-Semantik als fachliche Quelle, minimale Python↔C#-Bridge, optionale Komfortschicht | `ACCEPTED / ARCHITEKTURRICHTUNG` |

**Vorrang gilt der SDK-nativen Zielrichtung, nicht einer bereits bewiesenen vollständigen Migration.** Details des Umbaus stehen im [SDK-Modellabgleich](../specifications/sdk-native-modellabgleich-v01.md).
