# Dauerhafte Architekturdokumentation

> **Neue verbindliche Zielrichtung:** [ARCH-ADR-001 – SDK Native First](decisions/ARCH-ADR-001.md). Alte fachneutrale Darstellungen in diesem Dokumentationspaket sind im Konfliktfall historische IST-/Entwurfsbeschreibungen; die Core-/Runtime-Implementierung wird nicht durch den Dokumentationswechsel migriert.

**Einzige kanonische Dokumentationslinie.** Keine Agentenprompts, Run-Logs oder Arbeitsaufträge in diesem Ordner. Änderungen der Architektur führen die normativen Statusangaben im [Entscheidungsregister](08_Entscheidungsregister.md) fort.

| Reihenfolge | Dokument | Schwerpunkt |
|---|---|---|
| 01 | [Systemidee](01_Systemidee.md) | Historisches Core-Zielbild, aktualisierte SDK-native Zielrichtung |
| 02 | [Ebenen und Verantwortung](02_Ebenen_und_Verantwortung.md) | Design-/Build-/Runtime-Schichten |
| 03 | [Metamodell](03_Metamodell.md) | Entitäten, Relationen, Port- und Binding-Graph |
| 04 | [Begriffslexikon](04_Begriffslexikon.md) | kanonische technische Terminologie |
| 05 | [Vom Projekt zum Plugin](05_Vom_Projekt_zum_Plugin.md) | durchgehender Generierungs-/Ausführungsprozess |
| 06 | [Kommunikation und Zustände](06_Kommunikation_und_Zustaende.md) | Command/Event/State/Snapshot/Health |
| 07 | [Studio, Bibliothek und Adapter](07_Studio_Bibliothek_und_Adapter.md) | Werkzeugverantwortlichkeiten, Erweiterbarkeit |
| 08 | [Entscheidungsregister](08_Entscheidungsregister.md) | **normative Statusquelle** |
| 09 | [Nachweise und Abnahme](09_Nachweise_und_Abnahme.md) | reale Hardwarebelege, Evidenzkriterien |
| 10 | [Quellen und Herkunft](10_Quellen_und_Herkunft.md) | Provenienz und Geltungsbereich |
| 11 | [P0-Präzisierungen](11_P0_Praezisierungen.md) | Historischer P0-Review aus v0.4; Einzel-ADRs inzwischen freigegeben |
| 12 | [P0-Beschlussprotokoll](12_P0_Freigabe_2026-10-30.md) | Verbindliche Freigabe und Grenzen vom 30.10.2026 |
| 13 | [Benutzerhandbuch](13_Benutzerhandbuch.md) | Aktueller Editor-/Host-/Build-/Dry-Run-Startweg, Evidenzgrenzen |

Ergänzungen: [ADR-Einzeldokumente](decisions/README.md) und [Spezifikationsindex](specifications/README.md). Die Arbeitsplanung liegt ausschließlich unter [`work/`](../work/README.md).

**Freigabehinweis:** [Einzel-ADRs](decisions/README.md) – sechs ohne Änderung übernommen, ADR-005 eingeschränkt; darüber hinausgehende MM-Detailregeln und das finale Projektformat bleiben offen.

## Aktuelle SDK-native Referenzen

- [ARCH-ADR-001 – SDK-native Zielarchitektur](decisions/ARCH-ADR-001.md) – verbindliche Richtung.
- [SDK-Modellabgleich, Gaps und offene Migration](specifications/sdk-native-modellabgleich-v01.md) – IST, Ziel und technische Prüfgates.
- [Änderungsregister 03.11.2026](../work/planning/native-first-konsolidierung-20261103.md) – alle Dokumentationsänderungen und Folgen.

Die historischen P0-/RT-ADRs und Abnahmeakten sind keine heimlich umgeschriebenen neuen SDK-Mappings.

## Aktuelle Profildaten-/Modellforschung (04.11.2026)

- [Verbindliche Profil-/Aktions-Begriffsbasis v0.1](specifications/logitech-profil-und-aktionsmodell-basis-v01.md): Trennung von Action, Katalog, General-/App-Profilen, Workspaces, Pages/Controls und plugin-gesteuertem Dynamic Folder. Die noch undokumentierten `ProfileInfo.json`-Details bleiben Forschungsbefunde und keine Produkt-Schreibverträge.


## Aktuelle Profil- und Aktionsgrundlage (05.11.2026)

- [**Verbindliche Modellbasis v0.2**](specifications/logitech-profil-und-aktionsmodell-basis-v02.md) – nach unabhängig abgenommener Logitech-Profilforschung; konsequente Trennung von SDK-Aktionsdefinition, Profilinstanz, Placement, Workspace, Profilfolder und SDK Dynamic Folder.
- [Historische Vor-Forschungsbasis v0.1](specifications/logitech-profil-und-aktionsmodell-basis-v01.md) – für Nachvollziehbarkeit erhalten.
- Die Untersuchung `AP-PROF-001` ist im Schwesterprojekt `logi-actions-sdk-rec` archiviert und selektiv in dessen `sources/`, `catalog/`, `docs/` sowie `research/current-logitech-profiles/` übernommen. Das interne `ProfileInfo.json`-Format bleibt **keine** freigegebene Schreib-API.


## Studio-Komponentenarchitektur und tatsächliche Widget-Verdrahtung (06.11.2026)

- [**Komponentenarchitektur – Hauptindex**](architecture/studio/README.md): je Widget eine eigene Schnittstellenreferenz, außerdem NativeProjectSession und geplanter StudioCoordinator.
- [**Gesamtkarte IST/SOLL**](architecture/studio/00-Gesamtkarte.md): Mermaid-Datenflüsse und fachliche Eigentümer.
- [**Verbindungsregister**](architecture/studio/04-Verbindungsregister.md): stabile V-IDs, Sender/Empfänger, Payloads, Validierungsregeln und später je Verbindung ein konkreter Integrationstest.
- **AP-STUDIO-002 unabhängig abgenommen:** [Abnahmebericht](../work/acceptance/20261106-studio-coordinator/ABNAHME.md) und [tatsächliche Widget-Verdrahtung](architecture/studio/README.md). NativeStudioShell und StudioCoordinator sind im v1-Umfang APPROVED; Keypad-/ICT-Schreibfunktionen weiterhin aufgeschoben.


## Nächster fachlicher Studio-Baustein (06.11.2026)

- [SDK-nativer ActionInspector – Feld- und Schnittstellenspezifikation](architecture/studio/widgets/ActionInspector.md), Status **GEPLANT**.
- [Implementierungsauftrag AP-INSP-001](../work/planning/AP-INSP-001-native-action-inspector-v01.md), Status **PREPARED**, nicht gestartet. Der Inspector arbeitet nur auf existierenden NativeActions, mit Action-ID/SDK-Typ read-only und einer einzigen Session als Schreibautorität.
