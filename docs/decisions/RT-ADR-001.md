# RT-ADR-001 – Runtime- und Sitzungsidentitaet

**Status:** `ACCEPTED` (Runtime-Grundsatz, nicht vollständige technische Spezifikation)  
**Beschlossen:** 30.10.2026, im Architekturgespräch vorliegendem `RUN-AP-CORE-002-02`  
**Geltung:** fachneutraler Kern und generiertes Plugin V1, soweit nachstehend beschrieben

## Kontext

Die erste Runtime-Stufe AP-CORE-002 legte sechs Themen als Entscheidungsvorschläge vor. Der Nutzer hat die im Gespräch anhand konkreter Logitech-/Python-Situationen erläuterte und präzisierte Fassung T1–T6 ausdrücklich angenommen. Diese ADR kodifiziert **nur** die freigegebenen Grundsätze, nicht jede Detailoption aus dem vorherigen Agentenentwurf.

## Entscheidung

- `Project` ist die dauerhaft gespeicherte Definition, mit stabiler Projekt-ID und identifizierbarer Projektfassung. Eine daraus erzeugte Logitech-Plugin-Installation ist keine Runtime-Ausführung.
- Jede tatsächlich gestartete Ausführung erhält eine eigene `runtime_instance_id`. Ein Restart des Prozesses, **der diese Runtime enthält**, erzeugt eine neue Runtime-ID. Ein bloßer Verbindungsabbruch ohne Runtime-Neustart tut das nicht.
- Eine Kommunikationsverbindung zu einer laufenden Runtime ist eine `Session` mit `session_id`. Nach einer Neuverbindung entsteht eine neue Session. Das logische Modell kann mehrere Sessions unterscheiden, ohne damit mehreren Teilnehmern Schreibrechte zu geben.
- V1-Betriebsmodell des **generierten** Plugins: eine primäre steuernde Anwendung je Plugin-Installation; mehrere unterschiedliche generierte Plugins dürfen parallel betrieben werden. Eine Plugin-Installation muss keinen Dynamic Folder und keine Starttaste besitzen, sondern kann beliebige vom SDK abbildbare Aktionstypen enthalten.
- Mehrfaches paralleles Ausführen derselben Plugin-Definition und ein Multi-App-Plugin sind **keine Produktanforderungen in V1**. Der fachneutrale Kern darf solche Ausführungen nicht versehentlich durch globale Singletons unmöglich machen. Physische Ressourcen werden gesondert vom Adapter kontrolliert.
- Placement-Identitäten und ComponentInstance-Identitäten sind von Runtime- und Session-IDs getrennt (P0-ADR-002/006).

## Folgen

Tests: Runtime-Neustart vs. Reconnect, unterschiedliche Plugins gleichzeitig, getrennte Runtime-Werte, mehrfach platzierte Komponenten ohne Identitätsduplikat. Eine optionale dauerhafte `deployment_id` bleibt ein späterer Entwurfsgegenstand.

## Nicht beschlossen

UUID-Variante, Revisionshash, dauerhaftes Deployment-Format, Session-Epoch-Protokoll und konkrete Mehrinstanz-Hosting-Strategie.

## Architekturgrenzen und Nachweise

- Zusammenfassung/Querverweise: [Entscheidungsregister](../08_Entscheidungsregister.md), [Runtime-Kommunikation](../06_Kommunikation_und_Zustaende.md).
- Quelle des historischen Vorschlags: `work/runs/RUN-AP-CORE-002-01/06_runtime_vertragsentwurf.md` (`PROPOSED` zum Zeitpunkt der Erstellung); im Konfliktfall gilt **dieser beschlossene, präzisierte Text**.
- `ACCEPTED` bedeutet verbindliche Richtung, **nicht** fertig implementierter Runtime-Vertrag und kein Hardwaretest.
