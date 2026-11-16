# RT-ADR-004 – Command-, Event- und Result-Semantik

**Status:** `ACCEPTED` (Runtime-Grundsatz, nicht vollständige technische Spezifikation)  
**Beschlossen:** 30.10.2026, im Architekturgespräch vorliegendem `RUN-AP-CORE-002-02`  
**Geltung:** fachneutraler Kern und generiertes Plugin V1, soweit nachstehend beschrieben

## Kontext

Die erste Runtime-Stufe AP-CORE-002 legte sechs Themen als Entscheidungsvorschläge vor. Der Nutzer hat die im Gespräch anhand konkreter Logitech-/Python-Situationen erläuterte und präzisierte Fassung T1–T6 ausdrücklich angenommen. Diese ADR kodifiziert **nur** die freigegebenen Grundsätze, nicht jede Detailoption aus dem vorherigen Agentenentwurf.

## Entscheidung

- `Command` fordert eine Handlung an; `Event` meldet ein Vorkommnis; `State` hält einen aktuellen Wert. Handler-Ergebnis, Event-Emission und State-Änderung sind getrennte Vorgänge. Ein angenommener Command ist nicht automatisch erfolgreich (P0-ADR-003).
- Commands benötigen im endgültigen Nachrichtenvertrag identifizierbare Requests und korrelierbare Ergebnisse. `Completed`, `Failed` und `UnknownOutcome` müssen unterscheidbar bleiben. Keine pauschale Exactly-once-Garantie (AR-012).
- Keine automatischen Wiederholungen **nicht-idempotenter** Commands. Eine spätere Wiederholungs-/Dedup-Policy ist explizit.
- Ein Event darf mehrere Empfänger besitzen. Ohne ausdrücklich normierte Reihenfolgeregel garantiert die Editor-Reihenfolge **keine** Handler-Ausführungsreihenfolge.
- Schema-/Endpunkt-/Handler-Fehler liefern strukturierte Diagnosen statt unbehandelter Exceptions. Der AP-CORE-002-Spike verwendet eine **nicht normative** lexikalische Binding-Reihenfolge und Reentrancy-Grenze.

## Folgen

Keine inoffizielle Festschreibung der Spike-internen `MAX_DEPTH` oder des temporären Handler-Rückgabeformats als öffentliche Python-API.

## Nicht beschlossen

Transportnachrichtenschema, endgültiges Dispatch-Ordering, Timeouts, Reentrancy-/Queue-Semantik, konkrete idempotency/dedup windows und Retry-Strategie.

## Architekturgrenzen und Nachweise

- Zusammenfassung/Querverweise: [Entscheidungsregister](../08_Entscheidungsregister.md), [Runtime-Kommunikation](../06_Kommunikation_und_Zustaende.md).
- Quelle des historischen Vorschlags: `work/runs/RUN-AP-CORE-002-01/06_runtime_vertragsentwurf.md` (`PROPOSED` zum Zeitpunkt der Erstellung); im Konfliktfall gilt **dieser beschlossene, präzisierte Text**.
- `ACCEPTED` bedeutet verbindliche Richtung, **nicht** fertig implementierter Runtime-Vertrag und kein Hardwaretest.
