# Logitech Plugin Studio – fachneutrales Architekturmodell v0.1

**Status:** Architektur-Baseline / konzeptioneller Entwurf (2026-10-29)  
**Geltungsbereich:** SDK Lab, wiederverwendbare Komponentenbibliothek, Plugin Studio, generierte Plugins und Python-Runtime.  
**Nicht enthalten:** Festlegung einer konkreten Fachanwendung, vollständiges JSON-Schema, Implementierung, finale SDK-Signaturen.

## 1. Leitentscheidung

Das System folgt standardmäßig einem **hybriden, zustandsorientierten und ereignisgetriebenen Modell**:

- **Commands:** adressierte Aufforderung, eine Operation auszuführen; eine Aufforderung ist noch kein bestätigtes Ergebnis.
- **Events:** Benachrichtigung, dass ein Ereignis eingetreten ist; Ereignisse sind zeitbezogen und besitzen keine automatische Dauer.
- **States:** abfragbare aktuelle Werte, die Änderungen und vollständige Snapshots unterstützen.
- **Snapshots:** vollständiges Abbild der autoritativen Zustände eines definierten Scopes für Initialisierung und Re-Synchronisation.
- **Health/Lifecycle:** technischer Zustand einer Verbindung oder Runtime; unabhängig von beliebigen Nutz-Zuständen.
- **Bindings:** deklarative Verknüpfungen zwischen Quellen, Signalen, Zieloperationen und Darstellungen.

Der Transport ist eine austauschbare Implementierungsentscheidung; die öffentliche fachneutrale API darf keine HTTP-, WebSocket- oder Logitech-spezifischen Annahmen erzwingen.

## 2. Schichten und Verantwortlichkeiten

1. **Projektdefinition (Design-Time):** beschreibt Elemente, Verträge, Verbindungen, Layouts und Darstellung. Deklarativ, versioniert, validierbar.
2. **Komponentenbibliothek:** enthält wiederverwendbare, konfigurierbare Implementierungen mit manifestierten Fähigkeiten, Parametern und Tests. Keine fest eingebauten Demonstrationsinhalte.
3. **Runtime-Kern:** hält die Verbindung, vermittelt Nachrichten, verwaltet den aktuellen replizierten Zustand, Versionen, Synchronisation und Lebenszeichen.
4. **Adapter:** koppeln den Runtime-Kern an Logitech-SDK-Geräte, Python-Anwendungen oder später andere Laufzeitumgebungen.
5. **Editor/Generator:** bearbeiten Definitionen und erstellen/bauen/installieren Artefakte. Das Studio selbst ist zur Laufzeit nicht erforderlich.

**Unverrückbare Trennung:** Ein Element in der Projektdefinition ist nicht identisch mit einem aktuell laufenden Element, und weder die Runtime noch die Hardware ist der Editor.

## 3. Fachneutrale Metamodell-Elemente

| Element | Bedeutung | Zentrale Attribute / Beziehungen |
|---|---|---|
| `Project` | Umfassende Plugin-Definition | schema_version, project_id, metadata, resources |
| `ComponentDefinition` | wiederverwendbarer Bausteintyp | type_id, version, capabilities, configurable_properties, ports |
| `ComponentInstance` | Verwendung eines Bausteins im Projekt | id, component_type, configuration, scope |
| `Port` | typisierte Ein- oder Ausgabeschnittstelle einer Komponente | id, direction, signal_kind, payload_schema |
| `Command` | auslösbare Operation mit optionalem Ergebnis | id, request_schema, response_schema, target |
| `Event` | zeitpunktbezogene Benachrichtigung | id, payload_schema |
| `State` | aktueller typisierter Wert | id, value_schema, default/unknown_policy, authority, scope |
| `Binding` | Routing/Transformation zwischen Ports/Elementen | id, from, to, optional_mapping, optional_condition |
| `View` | darstellbare Fläche oder Container | id, type, layout, children/placements |
| `Placement` | Verortung einer Aktion/Komponente in einer View | id, component_ref, position/order, visibility_binding |
| `Presentation` | visuelle Variante einer Instanz | id, text, icon, color, conditions/bindings |
| `RuntimeInstance` | lebender Ausführungskontext | instance_id, session_id, connection_status; **nicht** Teil der statischen Definition |

### Zentrale Differenzierungen

- **Action ≠ Placement:** Dieselbe Aktion darf in mehreren Views oder Ordnern erscheinen. Eine Platzierung ist eine eigene Entität.
- **Definition ≠ Ist-Zustand:** Ein Studio-Projekt beschreibt Möglichkeiten und Grundwerte; aktuelle Werte, aktuelle Folder-Mitglieder und Verbindungssitzungen liegen in der Runtime.
- **State ≠ Event:** Ein Event kann einen Wertwechsel ankündigen; maßgeblich bleibt ein explizit verwalteter aktueller Wert.
- **Command ≠ Result:** Ein ausgelöster Command beweist nicht seine erfolgreiche Ausführung.
- **ConnectionStatus ≠ State:** Offline bedeutet unbekannte Aktualität, nicht automatisch einen fachlichen Zielwert.
- **Callback ≠ Lifecycle:** Ein Callback ist ein austauschbarer Handler für einen Vertrag; sein Vorhandensein ist kein Lebenszeichen.

## 4. Signale und Verträge

### 4.1 Minimaler Nachrichtenumschlag

Konzeptionelle Pflichtfelder: `type`, `message_id`, `source`, `instance_id`, `session_id`, `timestamp`, `payload`. Ergänzungen nach Art: `correlation_id` bei Command/Result, `state_revision` bei State-Änderung und Snapshot, `schema_version` für die Nachrichtenkompatibilität.

Beispiel (absichtlich ohne Fachsemantik):

```json
{
  "type": "state.changed",
  "message_id": "msg-001",
  "source": "runtime.primary",
  "instance_id": "instance-01",
  "session_id": "session-01",
  "timestamp": "2026-10-29T12:00:00Z",
  "schema_version": "0.1",
  "payload": {
    "state_id": "state.primary",
    "value": true,
    "revision": 7
  }
}
```

### 4.2 Minimaler Operationsvertrag der Runtime

- `send_command(id, payload, correlation_id?)` – Operation anfordern.
- `on_command(id, handler)` – eingehende Anforderung behandeln.
- `emit_event(id, payload)` und `on_event(id, handler)` – Vorkommnisse veröffentlichen / abonnieren.
- `set_state(id, value)` und `on_state(id, handler)` – aktuelle Werte setzen / beobachten (entsprechend Authority-Policy).
- `get_snapshot(scope)` und `apply_snapshot(snapshot)` – vollständig synchronisieren.
- `on_connection_change(handler)` – technische Verbindung beobachten.

Diese Namen sind **logische Operationen**, noch keine endgültigen Python-Methodensignaturen. Die Transport-/Lebenszeichenverwaltung ist eine Runtime-Verantwortung; Anwendungen müssen nicht für jede Aktion eigene KeepAlive-Callbacks implementieren.

## 5. Regel für Zustandsautorität

Jeder State hat eine **konfigurierbare Autorität** (welche Laufzeitinstanz ist maßgeblich) sowie einen **Scope**. Als einfache Voreinstellung ist eine Autorität pro State vorgesehen, mit lesbaren Replikaten auf anderen Seiten. Bidirektional beschreibbare States oder Konfliktauflösung durch mehrere Writer sind nicht Teil des v0.1-Kerns; sie werden bei Bedarf als explizites Erweiterungsmodul eingeführt.

Bei fehlender Erreichbarkeit bleibt der zuletzt bekannte Wert als *last-known* verfügbar, wird aber mit **stale/unknown** markiert. Offline darf ihn nicht stillschweigend in einen frei erfundenen Wert umwandeln.

## 6. Lebenszyklus und Zuverlässigkeit

- **Connect:** Handshake mit Schema-/Capability-Versionen und eindeutiger `session_id`.
- **Synchronize:** Autoritativen Snapshot des benötigten Scopes abrufen/anwenden.
- **Ready:** Erst nach erfolgreicher Synchronisation gilt die Verbindung als bereit für verlässliche Zustandsdarstellung.
- **Live:** Zustandsänderungen und Events inkrementell verarbeiten; Revisionen auf veraltete Updates prüfen.
- **Disconnect:** Verbindung als offline markieren, letzte Werte als potenziell veraltet behandeln.
- **Reconnect:** neue Session etablieren und erneut vollständig synchronisieren, statt die Zustandskorrektheit von lückenlos empfangenen Events abhängig zu machen.

Health/Liveness und Readiness bleiben getrennt; Frequenzen und Timeouts sind konfigurierbare Policies, keine harten Protokollkonstanten.

Commands benötigen `message_id` und `correlation_id`, damit Ergebnisse zugeordnet und Duplikate erkennbar werden. Exakt-einmal-Ausführung wird **nicht** pauschal versprochen; Wiederholungsverhalten ist pro Command-Definition bzw. -Handler ausdrücklich festzulegen.

## 7. Dynamische Darstellung und Collections

Views und Placements sind datengetrieben. Ein `Folder` ist eine spezielle View, nicht ein fest mit vier oder acht Aktionen verdrahteter Algorithmus. Eine `View` kann 0..N Placements besitzen. Das Laufzeitsystem kann erlaubte Eigenschaften und Mitgliedschaften ändern, ohne das statische Projekt neu zu bauen, **soweit der jeweilige SDK-Adapter dies unterstützt**. Physische Kapazitäten, Positionsregeln und Editierbarkeit gehören zu den Capabilities des Adapters; der Editor validiert gegen sie.

`Presentation`-Bindings bilden Zustände oder andere Daten auf Text, Bilder, Farben und Sichtbarkeit ab. Benutzerdefinierte Varianten sind nicht mit spezifischen Statusnamen vorbelegt.

## 8. Minimaler neutraler Datenfluss

```text
[Hardware-Eingabe] --adapter--> [Command-Port] --binding--> [Handler]
                                                             |
                                             [Command-Result oder Event]
                                                             |
[Hardware-Anzeige] <--adapter-- [Presentation-Binding] <-- [State/Snapshot]
```

Ein Command kann zu einem Event oder State-Wechsel führen, **muss** es aber nicht. Ein Binding ist zunächst eine deklarative Zuordnung; beliebiger Python-Code in Expressions ist keine Voraussetzung für das Kernmodell.

## 9. Erstes freizuschaltendes vertikales Funktionsszenario (ohne Fachbezug)

1. Im Studio eine frei benannte `ComponentInstance` als Command-Quelle erstellen.
2. Einen benannten Handler-Port definieren und per `Binding` verbinden.
3. Eine beliebig benannte, typisierte `State`-Variable samt Autorität definieren.
4. Eine `Presentation` mit mindestens zwei Varianten an den State binden.
5. Eine `View` mit einer beliebig großen, adapterkonformen Aktionsliste erstellen.
6. Generiertes Plugin bauen und unter eigener Identität in Options+ installieren.
7. Hardware-Command an Python-Handler übertragen; Python setzt einen State; die konkrete Anzeige wechselt.
8. Den Plugin Service neu starten und einen korrekten Initial-Snapshot nachweisen.
9. Während der Laufzeit die Folder-Mitgliedschaft ändern und die Darstellung auf Hardware nachweisen.

Das ist der **erste Produktivpfad**. SDK-Lab-Tests sind die technische Quelle, aber weder die Oberfläche noch der Generator dürfen Demo-Inhalte fest verdrahten.

## 10. Jetzt entschieden / noch offen

### Als Baseline entschieden

- Fachneutrales Modell ohne feste Begriffe für konkrete Anwendungen.
- Hybrid: Commands + Events + abfragbare States + Snapshots.
- Health/Lifecycle getrennt von Nutz-Zuständen.
- Definition / Runtime / Adapter / Editor getrennt.
- Beliebige Anzahl projektdefinierter Aktionen; Platzierung ist unabhängig von der Aktion.
- Typisierte Ports und deklarative Bindings.
- Konfigurierbare, explizite State-Autorität und definierter Scope.
- Runtime erledigt Reconnect und Zustandsabgleich.
- Keine verpflichtende State Machine und keine verpflichtenden Start-/Stop-Callbacks.

### Für v0.2 der Modellierung zu entscheiden

1. Konkretes JSON-Schema mit IDs, Typen, Referenzen, Validierungen und Versionierungsregeln.
2. Katalog der primären ComponentTypes und ihrer Port-/Capability-Verträge.
3. Genaue Scopes (`plugin`, `view`, `action`, `session`, etc.) und Lifetime je Element.
4. Definition der erlaubten Binding-Mappings, Bedingungen und Prioritätsregeln.
5. Statische Projektwerte vs. dynamische Runtime-Overrides, inklusive Persistenzoptionen.
6. Exakte Python-API und Thread-/Async-Integration für PySide6.
7. Adapter-Mapping auf Logitech-SDK-Callbacks, View-Limits und Build-/Reload-Grenzen.
8. Sicherheits-/Prozessmodell: localhost IPC, Authentifizierung, parallele Instanzen, Port-/Endpoint-Vergabe.

## 11. Umsetzungsvorgehen

**Schritt 1 – Kernmodell-Schema:** IDs, Elementtypen, Portverträge und Bindings definieren; Validator und Round-Trip-Tests erstellen. Keine neue Oberfläche vor stabiler Serialisierung.  
**Schritt 2 – Runtime-Verträge:** Command/Event/State/Snapshot/Health mit Test-Doppelinstanzen (ohne Logitech-Gerät).  
**Schritt 3 – Logitech-Adapter:** Nachgewiesene Lab-Funktionen als generische Adapter implementieren; keine fest programmierten Demo-Aktionen.  
**Schritt 4 – Erster Studio-Editor:** Projekt, Aktionen, Bindings, Zustände, Layout, Darstellung; mit einem konkreten End-to-End-Abnahmetest.  
**Schritt 5 – Ausbau:** Multistate, Action Editor, frei definierte Assets, komplexere Regeln und weitere Gerätefähigkeiten als optionale Erweiterungen.

## 12. Kompatibilität mit vorhandenem DevKit

Der vorhandene SDK-Lab-Stand und die funktionierende bidirektionale Bridge bleiben als technische Referenz erhalten. Das v0.2-Studio-Datenmodell mit Demo-Checkboxen wird **nicht** als produktives Kernschema übernommen; stattdessen ist eine klare Neuimplementierung des Modell-/Generatorvertrags erforderlich. Eine Migration von Prototyp-Projekten ist für diese Architektur-Baseline nicht verpflichtend.
