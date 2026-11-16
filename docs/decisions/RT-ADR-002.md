# RT-ADR-002 – State-Scopes und eindeutige Schreibhoheit

> **Abgrenzung 03.11.2026:** [ARCH-ADR-001](ARCH-ADR-001.md) verlangt künftig die Unterscheidung zwischen **nativem Logitech-Multistate-Action-State** und den hier beschriebenen **Python-Host-/StateStore-Scopes**. Diese ADR bleibt für den bestehenden Hostpfad gültig; sie definiert nicht automatisch jedes native SDK-State-Verhalten.

**Status:** `ACCEPTED` (Runtime-Grundsatz, nicht vollständige technische Spezifikation)  
**Beschlossen:** 30.10.2026, im Architekturgespräch vorliegendem `RUN-AP-CORE-002-02`  
**Geltung:** fachneutraler Kern und generiertes Plugin V1, soweit nachstehend beschrieben

## Kontext

Die erste Runtime-Stufe AP-CORE-002 legte sechs Themen als Entscheidungsvorschläge vor. Der Nutzer hat die im Gespräch anhand konkreter Logitech-/Python-Situationen erläuterte und präzisierte Fassung T1–T6 ausdrücklich angenommen. Diese ADR kodifiziert **nur** die freigegebenen Grundsätze, nicht jede Detailoption aus dem vorherigen Agentenentwurf.

## Entscheidung

- Ein State ist fachneutral und besitzt einen typisierten Wert, eine konkrete Scope-Adresse und genau **einen maßgeblichen Writer**. Beliebig viele Leser oder Command-Erzeuger sind zulässig; eine Änderungsanforderung ist nicht automatisch eine bestätigte Wertänderung (P0-ADR-005).
- Für die Runtime V1 werden genau die drei fachlichen Scope-Kategorien vorgesehen: `runtime` (gemeinsam innerhalb einer Ausführung), `component` (für eine ComponentInstance innerhalb einer Ausführung) und `placement` (nur für eine konkrete Placement-Instanz innerhalb einer Ausführung).
- Der in bisherigen statischen Projekten benutzte Scope-Wert `project` bezeichnet für Laufzeitwerte den **runtimeweiten** Bereich dieser Projektausführung. Die Änderung des statischen JSON-Schemas oder eine Umbenennung des gespeicherten Werts ist **nicht** Teil dieser Entscheidung.
- `session` ist **kein regulärer fachlicher State-Scope** in V1. Technische Session-Daten gehören in Lifecycle/Health. Verbindungs-/Sessionwechsel übertragen keine automatische Writer-Autorität.
- Die vorgesehenen Autoritätsrollen sind `host` (primäre angebundene Anwendung), `component` (konkret adressierte ComponentInstance) und `runtime` (die Runtime als Besitzer). Autorität wird zur Laufzeit an eine stabile Identität gebunden, nicht nur an eine kurzlebige Session-ID.
- Eine nicht autorisierte, falsch typisierte oder nicht eindeutig adressierte Aktualisierung wird **ohne Zustandsänderung** mit strukturierter Diagnose zurückgewiesen. Kein implizites Last-Writer-Wins, kein Multi-Writer-Merge.
- Scope, Authority und Persistenz sind unabhängig. Daten aus einer Python-Anwendung dürfen nicht unbemerkt als dauerhaft gespeicherte Projektwerte behandelt werden.

## Folgen

Die konkrete Scope-Adresse ist intern eindeutig durch Runtime-Ausführung, State-ID und ggf. Komponenten-/Placement-ID zu bestimmen. Ein Test muss zwei unterschiedliche Placements derselben Komponente voneinander trennen können, wenn ein placementbezogener State verwendet wird; komponentenbezogene Werte bleiben geteilt.

## Nicht beschlossen

Exaktes JSON-Adressschema für scoped States, Delegation/Failover, Berechtigungsnachweis über Netzwerktransport, Persistenzimplementierung und die endgültige Migration der bisherigen Draft-Scope-Wertemenge. Die erste StateStore-Stufe arbeitet in-memory und darf keine neuen Felder stillschweigend in das statische Projektschema hineindefinieren.

## Architekturgrenzen und Nachweise

- Zusammenfassung/Querverweise: [Entscheidungsregister](../08_Entscheidungsregister.md), [Runtime-Kommunikation](../06_Kommunikation_und_Zustaende.md).
- Quelle des historischen Vorschlags: `work/runs/RUN-AP-CORE-002-01/06_runtime_vertragsentwurf.md` (`PROPOSED` zum Zeitpunkt der Erstellung); im Konfliktfall gilt **dieser beschlossene, präzisierte Text**.
- `ACCEPTED` bedeutet verbindliche Richtung, **nicht** fertig implementierter Runtime-Vertrag und kein Hardwaretest.
