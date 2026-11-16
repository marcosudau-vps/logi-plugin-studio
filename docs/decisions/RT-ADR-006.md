# RT-ADR-006 – Kern-, Bibliotheks- und Adaptergrenzen

> **Folgeentscheidung 03.11.2026:** [ARCH-ADR-001](ARCH-ADR-001.md) ersetzt für die künftige Produktarchitektur die hier früher angenommene **SDK-unabhängige/fachneutral führende Kernmodell-Ausrichtung**. Der folgende Originalbeschluss bleibt als historischer Text und als Vertrag des bestehenden Core-/Runtime-Pfads erhalten; er ist **keine** Anweisung, neue Logitech-Fähigkeiten erneut in ein proprietäres Fachmodell umzubauen.

**Status:** `ACCEPTED` (Runtime-Grundsatz, nicht vollständige technische Spezifikation)  
**Beschlossen:** 30.10.2026, im Architekturgespräch vorliegendem `RUN-AP-CORE-002-02`  
**Geltung:** fachneutraler Kern und generiertes Plugin V1, soweit nachstehend beschrieben

## Kontext

Die erste Runtime-Stufe AP-CORE-002 legte sechs Themen als Entscheidungsvorschläge vor. Der Nutzer hat die im Gespräch anhand konkreter Logitech-/Python-Situationen erläuterte und präzisierte Fassung T1–T6 ausdrücklich angenommen. Diese ADR kodifiziert **nur** die freigegebenen Grundsätze, nicht jede Detailoption aus dem vorherigen Agentenentwurf.

## Entscheidung

- Der **Core** kennt fachneutrale Definitionen, Komponenten, Ports, Bindings, States, Identität, Diagnosen und allgemeine Laufzeitverträge. Keine Demo-Fachbegriffe, keine Logitech- oder Qt-Abhängigkeit.
- **Komponentenbibliothek** stellt versionierte, generische Typen mit Config-, Port- und Capability-Verträgen bereit; keine 4/8-Demo-Hardcodings als Produktkomponenten.
- **Logitech-Adapter** übersetzt Runtime-Operationen in das tatsächliche Actions SDK und meldet Gerätefähigkeiten und SDK-Grenzen, einschließlich Build-/Reload-abhängiger Änderungen. Das Studio soll die unterstützten SDK-Action-Typen möglichst vollständig abbilden und nicht ein Workspace-/Starttastenmodell erzwingen.
- **Python-/Qt-Integration** verbindet konkrete Anwendungen, Callbacks und Threading sicher mit der Runtime. Eine einzelne Host-Anwendung ist V1-Standard pro Plugin, nicht Bestandteil eines zwangsweise fest verdrahteten Fachworkflows.
- **Studio** bearbeitet deklarative Projektdefinitionen; Runtime-Overrides, Zustände und Verbindungen sind nicht automatisch Design-JSON.

## Nicht beschlossen

Vollständiger SDK-Capability-Katalog, Generator-API, Transportprotokoll, Prozessverwaltung und konkrete Editorseiten. Zukünftiges universelles Multi-App-Plugin bleibt ein separates Vorhaben.

## Architekturgrenzen und Nachweise

- Zusammenfassung/Querverweise: [Entscheidungsregister](../08_Entscheidungsregister.md), [Runtime-Kommunikation](../06_Kommunikation_und_Zustaende.md).
- Quelle des historischen Vorschlags: `work/runs/RUN-AP-CORE-002-01/06_runtime_vertragsentwurf.md` (`PROPOSED` zum Zeitpunkt der Erstellung); im Konfliktfall gilt **dieser beschlossene, präzisierte Text**.
- `ACCEPTED` bedeutet verbindliche Richtung, **nicht** fertig implementierter Runtime-Vertrag und kein Hardwaretest.
