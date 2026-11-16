# RT-ADR-005 – Lifecycle, Health und Zustandsaktualitaet

**Status:** `ACCEPTED` (Runtime-Grundsatz, nicht vollständige technische Spezifikation)  
**Beschlossen:** 30.10.2026, im Architekturgespräch vorliegendem `RUN-AP-CORE-002-02`  
**Geltung:** fachneutraler Kern und generiertes Plugin V1, soweit nachstehend beschrieben

## Kontext

Die erste Runtime-Stufe AP-CORE-002 legte sechs Themen als Entscheidungsvorschläge vor. Der Nutzer hat die im Gespräch anhand konkreter Logitech-/Python-Situationen erläuterte und präzisierte Fassung T1–T6 ausdrücklich angenommen. Diese ADR kodifiziert **nur** die freigegebenen Grundsätze, nicht jede Detailoption aus dem vorherigen Agentenentwurf.

## Entscheidung

- Verbindungszustand, Erreichbarkeit, Bereitschaft und fachlicher State werden **unabhängig voneinander** behandelt. Ein Heartbeat ist kein domänenspezifischer Start-/Stop-/KeepAlive-Callback.
- Die Runtime kennt die technischen Phasen `disconnected`, `connecting`, `synchronizing`, `ready`, `degraded` als Architekturkonzept; `ready` bedeutet technische Bereitschaft im vereinbarten Funktionsumfang, nicht fachlichen Erfolg.
- `unknown`, `fresh`, `stale` kennzeichnen die **Aktualitätsqualität einzelner Werte**, nicht deren fachliche Semantik. Ein letzter Wert kann sichtbar bleiben, obwohl `stale` gilt.
- Heartbeat, Reconnect und Timeout werden zentral durch Runtime-/Transportanbindung organisiert, nicht verpflichtend für jede ComponentInstance einzeln.

## Nicht beschlossen

Timeout-/Heartbeat-Defaults, Prozessstartverhalten, Backoff, Qt-Threading, Transport-Discovery und Authentisierung. Optionen zum automatischen Starten einer Python-Anwendung sind **optionale Plugin-Konfiguration**, keine verpflichtende Funktionsart.

## Architekturgrenzen und Nachweise

- Zusammenfassung/Querverweise: [Entscheidungsregister](../08_Entscheidungsregister.md), [Runtime-Kommunikation](../06_Kommunikation_und_Zustaende.md).
- Quelle des historischen Vorschlags: `work/runs/RUN-AP-CORE-002-01/06_runtime_vertragsentwurf.md` (`PROPOSED` zum Zeitpunkt der Erstellung); im Konfliktfall gilt **dieser beschlossene, präzisierte Text**.
- `ACCEPTED` bedeutet verbindliche Richtung, **nicht** fertig implementierter Runtime-Vertrag und kein Hardwaretest.
