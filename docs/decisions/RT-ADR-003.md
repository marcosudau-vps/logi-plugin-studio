# RT-ADR-003 – Zustandssynchronisierung und Qualitaet

**Status:** `ACCEPTED` (Runtime-Grundsatz, nicht vollständige technische Spezifikation)  
**Beschlossen:** 30.10.2026, im Architekturgespräch vorliegendem `RUN-AP-CORE-002-02`  
**Geltung:** fachneutraler Kern und generiertes Plugin V1, soweit nachstehend beschrieben

## Kontext

Die erste Runtime-Stufe AP-CORE-002 legte sechs Themen als Entscheidungsvorschläge vor. Der Nutzer hat die im Gespräch anhand konkreter Logitech-/Python-Situationen erläuterte und präzisierte Fassung T1–T6 ausdrücklich angenommen. Diese ADR kodifiziert **nur** die freigegebenen Grundsätze, nicht jede Detailoption aus dem vorherigen Agentenentwurf.

## Entscheidung

- Standard ist der bereits vereinbarte hybride Ablauf: **aktuellen Snapshot beziehen → inkrementelle Änderungen verarbeiten → bei Lücke, Unterbrechung oder unklarem Ursprung erneut synchronisieren**.
- Jede autorisierte Zustandsaktualisierung trägt einen eindeutigen Ordnungsbezug innerhalb einer **Authority-Epoch** und eine Revision. Eine neue Authority-Epoch verhindert, dass ein nach Writer-Neustart erneut beginnender Zähler als alte Revision interpretiert wird.
- Ohne verifizierte aktuelle Authority-Epoch und Sequenz darf ein Replikat keinen älteren Stand stillschweigend als aktuell überschreiben.
- Wert und Qualitätsmarkierung sind getrennt: `unknown`, `fresh`, `stale`. `stale` ändert den fachlichen Wert nicht; beispielsweise darf ein Verbindungsabbruch nicht implizit `false` setzen.
- Snapshots müssen eine konsistente Ausgangsbasis beschreiben. Ein Re-Sync nach Neuverbindung darf nicht unterstellen, dass sämtliche dazwischenliegenden Events angekommen sind.

## Folgen

Ein geräteunabhängiger In-Memory-StateStore kann als nächster Schritt Revisions-/Epochenmetadaten und einen konsistenten Snapshot seiner eigenen Werte nachweisen. Transport, Host-Replikation und Handshake folgen erst danach.

## Nicht beschlossen

Wire-Format, globale vs. scopebezogene Snapshot-Revision, Snapshot-Puffer-/Atomizitätsalgorithmus beim **Transport**, Delta-Replay, ACK, Epoch-Bildung, Überlauf und Größenlimits. Der Spike muss keine verteilte Synchronisation simulieren, wenn der Vertrag dafür noch nicht präzisiert ist.

## Architekturgrenzen und Nachweise

- Zusammenfassung/Querverweise: [Entscheidungsregister](../08_Entscheidungsregister.md), [Runtime-Kommunikation](../06_Kommunikation_und_Zustaende.md).
- Quelle des historischen Vorschlags: `work/runs/RUN-AP-CORE-002-01/06_runtime_vertragsentwurf.md` (`PROPOSED` zum Zeitpunkt der Erstellung); im Konfliktfall gilt **dieser beschlossene, präzisierte Text**.
- `ACCEPTED` bedeutet verbindliche Richtung, **nicht** fertig implementierter Runtime-Vertrag und kein Hardwaretest.
