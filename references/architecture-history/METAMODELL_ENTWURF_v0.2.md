# Logitech Plugin Studio – Fachneutrales Metamodell v0.2 (Vorschlag)

**Status:** Diskussions- und Architekturentwurf, noch nicht final freigegeben  
**Grundlage:** `ARCHITEKTURMODELL_v0.1.md` vom 29.10.2026  
**Geltungsbereich:** Projektdefinition, Komponentenbibliothek, Binding-Modell, Darstellung, Runtime-Verträge und Adapter; keine Anwendungsspezifik.  
**Bewusst nicht enthalten:** Festlegung einer Fachdomäne, produktive Python-API-Signaturen, vollständiges JSON Schema, konkretes Transportprotokoll, fertige Studio-Oberfläche.

## 1. Ziel und Leitprinzipien

Das Metamodell beschreibt **wie beliebige Plugins modelliert werden können**, nicht, welche Funktionen ein konkretes Plugin ausführt. Es ist ein abstraktes Autorenmodell; eine konkrete Projektdatei ist eine Instanz dieses Modells.

Verbindliche Vorgaben aus v0.1:

- Hybridmodell aus **Commands**, **Events**, **States** mit Snapshots und inkrementellen Änderungen.
- Technischer **Lifecycle/Health** unabhängig von beliebigen Anwendungszuständen.
- **Definition, Konfiguration, Platzierung und Runtime-Instanz** sind verschiedene Begriffe.
- **Keine SDK-spezifischen Annahmen im Kernmodell**; Geräte- und Host-Unterschiede werden über Adapter/Capabilities gekapselt.
- Der Stand einer Python-Anwendung oder eines Geräts wird **nicht aus einem einzelnen Event geraten**. Fachliche Zustände haben einen benannten autoritativen Eigentümer.
- Komponenten mit **typisierten Ports** und **deklarativen Bindings**. Eine State Machine ist optional.

Zusätzliche Leitplanken dieses Entwurfs:

1. Eine Komponente kann beliebig oft konfiguriert werden, und eine konfigurierte Aktion kann an mehreren Stellen dargestellt werden.
2. Die Bibliothek enthält generische Mechanismen, keine fest eingebauten Demo-Aktionen, Statusnamen oder 4/8-Tasten-Grenzen.
3. Jede Beziehung wird über **stabile IDs** statt UI-Positionen oder Anzeigenamen referenziert.
4. Projektänderungen und Laufzeitänderungen werden strikt unterschieden; Live-Unterstützung ist eine explizite Capability.
5. Der Studio-Editor ist ein Client des Modells, nicht dessen Eigentümer. Generierte Plugins laufen ohne das Studio.

## 2. Begriffe und Entitäten

| Entität | Definition | Eigentümer / Speicherort |
|---|---|---|
| `Project` | Wurzel eines editierbaren Plugin-Projekts; Identität, Metadaten, Referenzen auf Elemente | Studio-Projektdatei |
| `ComponentType` | Versionierter wiederverwendbarer Bausteintyp mit Konfigurationsschema, Ports und Fähigkeiten | Komponentenbibliothek |
| `ComponentInstance` | Konfigurierte Verwendung eines ComponentType innerhalb eines Projekts | Studio-Projektdatei |
| `PortDefinition` | Am ComponentType deklarierte, typisierte und gerichtete Schnittstelle | Komponentenbibliothek |
| `Endpoint` | Adressierter Port einer konkreten Instanz bzw. ein definierter virtueller Port anderer Elemente | abgeleitet / referenziert |
| `StateDefinition` | Deklaration eines aktuellen Werts samt Schema, Autorität, Scope, Validität und Lebensdauer | Studio-Projektdatei |
| `Binding` | Typisierte Verbindung von einem quellseitigen zu einem zielseitigen Endpoint | Studio-Projektdatei |
| `View` | Logische Anzeigefläche / Container, etwa Seite oder Ordner | Studio-Projektdatei |
| `Placement` | Eigenständige Verortung einer Komponente in einer View | Studio-Projektdatei |
| `Presentation` | Wiederverwendbare Darstellungsvorschrift und Varianten, optional daten-/zustandsgebunden | Studio-Projektdatei |
| `Asset` | Referenzierte Datei oder Ressource mit Medienmetadaten und Integritätsinformationen | Projektressourcen |
| `RuntimeInstance` | Tatsächlich gestartete Instanz mit Session, Verbindungszustand, Caches und konkreten Wertständen | Runtime, nicht Projektdatei |
| `Capability` | Vom Baustein/Adapter deklarierte, prüfbare Fähigkeit oder Einschränkung | Bibliothek / Adapter |

**Wichtig:** `Command`, `Event` und `State` sind **keine austauschbaren Typen**. Command/Event bezeichnen zeitbezogene **Signalverträge**. Eine `StateDefinition` beschreibt ein adressierbares, abfragbares Wertobjekt, das über State-Endpoints gelesen beziehungsweise nach Autoritätsregel aktualisiert werden kann.

### 2.1 Komponenten besitzen definierte Ports

Ein ComponentType kann z. B. folgende Ports deklarieren:

- `activated`: `direction=out`, `kind=command`, `payload_schema={...}`
- `invoke`: `direction=in`, `kind=command`, `payload_schema={...}`
- `occurred`: `direction=out`, `kind=event`, `payload_schema={...}`
- `visual_key`: `direction=in`, `kind=state`, `value_schema={type:string}`

Die `ComponentInstance` übernimmt diese Portverträge vom gebundenen ComponentType. Sie konfiguriert Werte, darf aber **keine beliebigen Ports erfinden**, es sei denn, der Typ erlaubt dies ausdrücklich über ein deklariertes Erweiterungsmodell (z. B. dynamische Parameter).

Ports sind technisch, nicht fachlich: `activated` kann später von einer Aufnahmetaste, einer Lichtsteuerung oder einer ganz anderen Aktion verwendet werden.

### 2.2 Adressierbare State-Endpoints

Damit alle Bindings demselben Graphmodell folgen, besitzt eine `StateDefinition` logische Endpoints, z. B.:

- `state:state.primary/value` – lesbarer aktueller Wert / State-Output.
- `state:state.primary/set` – optionale Schreiboperation; nur für die autorisierte Runtime verfügbar.

Die tatsächliche Schreib-API muss nicht als frei verfügbarer Binding-Port implementiert werden. **Das Autoritätsmodell ist zwingend durchzusetzen**; das Schema allein genügt nicht.

Auch eine `Presentation` kann definierte Eingänge besitzen, z. B. `presentation:visual.primary/selector`. Diese sind keine beliebigen, unkontrollierten Eigenschaftspfade, sondern deklarierte bzw. aus dem Typ ableitbare Endpoints.

## 3. Drei Signalarten

| Art | Semantik | Mögliche Form | Verlässlichkeit |
|---|---|---|---|
| `command` | Ein adressierter Wunsch nach Ausführung | Request, optional Ack/Result/Failure | Command darf nicht als bereits erfolgreich gelten; Wiederholung per Policy |
| `event` | Ein tatsächlich eingetretenes Vorkommnis | Event-Payload | Zeitbezogen; muss nicht dauerhaft gespeichert werden |
| `state` | Ein aktueller, abfragbarer Wert | Value + Revision + Qualität | Initial-Snapshot, Änderungen und Re-Sync |

Ein `command` darf zu einem `event` oder einer `state`-Änderung führen; ein solches Ergebnis ist **nicht automatisch** impliziert.

`command`-Endpunkte besitzen einen Request-Vertrag und können optional einen Result-Vertrag deklarieren. Ein lang laufender Command kann z. B. als angenommen und später als abgeschlossen gemeldet werden; beides ist vom Fachzweck unabhängig.

`event`-Signale haben einen Nutzdatenvertrag und eine Emittentenidentität; sie sind keine dauerhaften Zustandsbehälter.

`state`-Verbindungen verteilen aktuellen Wert, Revision und Qualität. Die Runtime hat eine Read-/Snapshot-Schnittstelle auch dann, wenn aktuell keine Änderung ausgelöst wird.

## 4. Bindings: Das allgemeine Verbindungselement

**Definition:** Ein `Binding` verbindet **einen Quell-Endpoint mit einem Ziel-Endpoint**.

Minimalfelder:

| Feld | Bedeutung |
|---|---|
| `id` | Stabile Identität der Verbindung |
| `source` | ID eines existierenden Ausgangs-Endpoints |
| `target` | ID eines existierenden Eingangs-Endpoints |
| `kind` | `command`, `event`, `state` (muss dem Portvertrag entsprechen) |
| `enabled` | Optionaler boolescher Konfigurationswert |
| `mapping` | Optional, nur deklarative, typgeprüfte Transformation |
| `condition` | Optional, explizit deklarierte Bedingung ohne beliebige Skriptausführung |
| `policy` | Optional, etwa Fehler- und Wiederholungsverhalten |

**Vorschlag für v0.2:**

- Nur `out -> in`; Referenzen müssen auflösbar sein.
- Kein stilles `command -> event` oder `event -> state`; dafür muss ein expliziter Adapter-/Transformationsbaustein eingesetzt werden.
- Nutzdaten-Schemas müssen kompatibel sein oder ein Mapping muss eine valide Transformation definieren.
- Vorerst nur `identity`, `constant`, `field_select` und `lookup` als standardisierte Mappings. Keine beliebigen Python-Ausdrücke in Projekt-JSON.
- Bedingungen mit einer kleinen typisierten Ausdruckssprache (Vergleich, boolesche Verknüpfung), nicht `eval`.
- Direkte Kombinationszyklen ohne Zustand oder Verzögerung werden durch den Validator abgewiesen. Später kann es ausdrücklich definierte Feedback-/Delay-Komponenten geben.
- Ein Quellport kann mehrere Bindings bedienen. Anforderungen an mehrere Zielports und Konflikte werden über explizite Policies behandelt.

## 5. StateDefinition: Autorität, Scope, Lebensdauer, Qualität

Ein State ist ein deklarierter Wert **mit Vertrag**, nicht bloß ein Key in einem beliebigen Python-Dictionary.

Vorgeschlagene Felder:

| Feld | Bedeutung |
|---|---|
| `id` | Stabile State-ID |
| `value_schema` | JSON-Schema-kompatibler Typ, ggf. Enum/Grenzen |
| `authority` | Explizite verantwortliche Runtime-Rolle oder Instanz |
| `scope` | Identitätsraum des Werts, z. B. `project`, `component`, `placement`, `session` |
| `lifetime` | Wie lange der Zustand gültig bzw. aufbewahrbar sein soll |
| `persistence` | `none`, `runtime_local`, `external` (konzeptionell) |
| `fallback` | Darstellungswert, falls noch kein autoritativer Wert vorliegt |
| `stale_policy` | Kennzeichnung und Verhalten bei veralteter Replik |

**Scope ist nicht Persistence.** Ein projektweit geteilter State kann flüchtig sein; ein instanzbezogener State kann dauerhaft gespeichert werden.

**Regel im Basismodell:** Genau ein autoritativer Writer pro State und Gültigkeitsscope. Andere Teilnehmer lesen replizierte Werte. Multi-Writer-Konflikte und CRDTs sind keine Grundfunktion der ersten Version.

Die Qualität eines replizierten Zustands ist separat vom Wert: mindestens `unknown`, `fresh`, `stale`. **Eine unterbrochene Verbindung darf nicht automatisch den fachlichen Wert überschreiben.**

Bei Initialisierung ist ein Fallback **kein bestätigter Ist-Wert**. Erst ein autoritativer Snapshot kann eine replizierte Anzeige als synchronisiert kennzeichnen.

## 6. Views, Placements und Presentations

Diese drei Dinge sind strikt getrennt:

- **View:** Ein logischer Container (z. B. Folder, Seite, Aktionsgruppe). Der Adapter setzt ihn auf einem Zielgerät um, sofern unterstützt.
- **Placement:** Verbindet eine Aktion bzw. eine darstellbare Komponente mit einem Platz/Index in einer View. Eine Komponente kann in mehreren Placements erscheinen.
- **Presentation:** Regeln für Text, Farbe, Bild, Zustandsvarianten und Sichtbarkeit. Sie kann von mehreren Placements verwendet oder pro Placement überschrieben werden.

Beispiel: Die eine `ComponentInstance` `action.primary` erscheint in `view.main` und in `view.secondary`. Beide Placements verweisen auf dieselbe Aktion. Ihre Zustände sind grundsätzlich **geteilt**; ein Placement hat nur dann eigenen Zustand, wenn es ausdrücklich einen eigenen State-Scope/StateDefinition verwendet.

Die Views dürfen **0..N Elemente** im logischen Modell enthalten. Gerätelimits, Seitenzahl, Paging, Encoder-Bereich und Fähigkeiten zur Live-Änderung stammen aus einem **Adapter-Capability-Manifest** und werden bei der Zielgeräte-Validierung geprüft. Daraus folgt **keine Garantie**, dass jedes Logitech-Gerät unbegrenzt gleichzeitig sichtbare Tasten unterstützt.

Wird eine Ordnerliste zur Laufzeit geändert, handelt es sich um ein **Runtime-Override** einer erlaubten View-Collection, nicht zwingend um eine Änderung der Studio-Projektdatei. Ob und wie Overrides dauerhaft gespeichert werden, ist eine getrennte Policy.

`Presentation` ist nicht mit einem einzelnen Event gekoppelt: Ein Variantenauswahleingang kann an einen State gebunden sein. Neue Snapshots reproduzieren dann automatisch das passende Bild und den Text.

## 7. ComponentType-Vertrag der Bibliothek

Jeder wiederverwendbare Baustein erhält ein versioniertes **Manifest**:

```text
ComponentType
 ├── type_id + version
 ├── config_schema           (welche Einstellungen gibt es?)
 ├── ports[]                 (welche Ein- und Ausgänge?)
 ├── capabilities_required[] (welche Adapter-Fähigkeiten benötigt er?)
 ├── capabilities_provided[] (welche Funktionen stellt er bereit?)
 ├── runtime_bindings        (welche Host-/Adapter-Komponenten werden benötigt?)
 ├── editor_schema           (welche Standardeditoren können generiert werden?)
 └── tests / evidence        (welcher Teil wurde wie nachgewiesen?)
```

Das `editor_schema` soll Standardwidgets aus Typen/Constraints ableiten können. Für spezielle Darstellungen (z. B. 3×3-Layout oder Icon-Editor) darf eine eigene Editor-Komponente registriert werden; sie ändert **nicht** den semantischen Vertrag.

**Bibliotheksmodule sind Mechanismen, nicht Demo-Konfigurationen**. Ein generischer Folder-Baustein hat keinen fest einprogrammierten Wechsel zwischen 4 und 8 Mitgliedern.

## 8. Runtime-Modell und Lifecycle

Für jede laufende Instanz existieren `runtime_instance_id`, `session_id`, technische Verbindungsinformationen, aktuelle replizierte States, ggf. Overrides und Event-/Command-Diagnosewerte.

Standardablauf:

1. **Connect** – Versionen, Rollen und Capabilities austauschen; Session identifizieren.
2. **Snapshot** – autoritative Werte und erlaubte dynamische Collections abgleichen.
3. **Ready** – verwendete Werte sind synchronisiert oder ausdrücklich als unbekannt gekennzeichnet.
4. **Live** – Commands vermitteln, Events verteilen, State-Revisionen fortschreiben.
5. **Disconnect/Degraded** – Verbindungsqualität markieren; keine implizite Änderung der fachlichen Werte.
6. **Reconnect** – neue Session und Re-Synchronisierung. Veraltete Updates ignorieren.

Das Metamodell definiert die Semantik; die Ausführung über HTTP, WebSocket oder IPC ist Adapter-/Transportaufgabe. Die Runtime verwaltet Heartbeats und Reconnects selbst. Anwendungen müssen **keine obligatorischen Start-, Stop- oder KeepAlive-Callbacks pro Aktion** implementieren.

Commands werden mit IDs und Korrelationsinformationen verfolgt. Die Runtime garantiert **nicht pauschal Exactly Once**; Deduplication und Retry müssen zu den Vertragsregeln des jeweiligen Commands passen.

## 9. Welche Änderungen sind statisch, welche dynamisch?

| Änderung | Grundsatz |
|---|---|
| Plugin-ID / Paketname / SDK-Klassengerüst | statisch; gewöhnlich Build/Reload |
| Neues, auf oberster Ebene registriertes SDK-Action-Schema | adapterabhängig; kann Reload erfordern |
| Beschriftung, Icon, Farbe, Enabled-Zustand | live, sofern Adapter capability erfüllt |
| Aktuelle State-Werte | live über State-API |
| Dynamic-Folder-Mitglieder und ihre Reihenfolge | live, wenn Adapter entsprechendes SDK-Verhalten unterstützt |
| Studio-Layoutdefinition | Projektkonfiguration; Änderungen werden nach Deployment-Regeln aktiviert |
| Laufzeit-Override eines Layouts | live; getrennt von gespeichertem Layout |

Diese Liste enthält allgemeine **Designabsichten**, keine pauschale Zusicherung für jeden SDK-Adapter oder jede Hardware-Firmware.

## 10. Fachneutraler Beispielablauf

Ein Projekt deklariert:

- Ein `CommandAction`-Exemplar `action.primary`, mit Ausgang `activated`.
- Ein externes Handler-Exemplar `handler.primary`, mit Eingang `invoke`.
- Einen State `state.primary` mit Enum `variant_0 | variant_1` und Host-Autorität.
- Ein Binding `action.primary/activated -> handler.primary/invoke`.
- Eine `Presentation` `visual.primary`, deren `selector` durch `state.primary/value` gespeist wird.
- Eine `View` `view.main`, in der `action.primary` über `placement.primary` sichtbar ist.

Wenn die Taste gedrückt wird, sendet das Action-Exemplar einen Command. Der Host-Handler entscheidet, was er damit macht. Aktualisiert der Host `state.primary`, repliziert die Runtime den State und die `Presentation` wählt automatisch die passende visuelle Variante. Nach einem Plugin-Service-Neustart stellt ein Snapshot die Anzeige wieder her. Der Beispiel-Handler besitzt **keine fest einprogrammierte Anwendungssemantik**.

Die vollständige Beispiel-JSON-Datei ist `beispiel_plugin_abstrakt.json` (illustrierend, noch kein formell validiertes Schema).

## 11. Validierungsregeln als Abnahmekriterien

Ein Projekt ist strukturell ungültig, wenn:

- IDs doppelt vorkommen oder Referenzen auf unbekannte Komponenten/Ports/States/Views zeigen.
- Ein Binding inkompatible Signalkategorien oder Nutzdaten-Schemas ohne expliziten Adapter verbindet.
- Ein State keine valide Autorität oder ungültige Default-/Fallback-Werte hat.
- Ein Placement auf ein nicht darstellbares Element zeigt oder Positionen gemäß Layout-Policy kollidieren.
- Ein benötigter ComponentType fehlt oder eine inkompatible Version verwendet wird.
- Benötigte Adapter-Capabilities nicht bereitstehen.
- Ein rein kombinatorischer Bindungszyklus ohne definiertes Feedback vorliegt.

Die generierte Plugin-Registrierung allein belegt nicht, dass alle dynamischen Fähigkeiten auf realer Hardware funktionieren. Modulverträge enthalten deshalb separat **Unit-Test, Integrations-Test und Hardware-Nachweis**.

## 12. Verbindliche Basis und noch zu entscheiden

### Bereits durch v0.1 vereinbart / beizubehalten

Hybridkommunikation; State-Snapshots; Life-/Health-Entkopplung; kompositionelle Komponenten und Bindings; Fachneutralität; Runtime-/Editor-/Adapter-Trennung; frei definierbare Aktionsanzahl im Modell.

### Hiermit als konkrete v0.2-Entscheidung vorgeschlagen

- `Project`, `ComponentType`, `ComponentInstance`, `PortDefinition`, `Endpoint`, `StateDefinition`, `Binding`, `View`, `Placement`, `Presentation`, `Asset`, `RuntimeInstance` als Entitäten.
- Port-Signalarten `command`, `event`, `state`; keine implizite Wandlung zwischen Signalarten.
- Configured Component vs Placement vs Runtime-State sind getrennte Identitäten.
- Type-Manifeste mit Versions-/Capability-/Editor-Vertrag.
- Ein autoritativer Writer pro State-Scope; `unknown/fresh/stale` getrennt vom Wert.
- Standardbindings als deklarativer Graph; beliebiger Quellcode ist keine Bedingung für das Projektmodell.
- Projektreferenzen über stabile IDs; dynamische Änderungen als erlaubte Overrides.

### Für den folgenden Schema-/Runtime-Entwurf zu präzisieren

- Syntax, Namespace und Unveränderlichkeit der IDs; Objekt- und Port-Referenzformat.
- Endgültige JSON-Schema-Ausprägung des Typensystems (JSON Schema als Grundlage empfohlen).
- Exakte Zustands-Scopes/Lifetime/Persistence-Policies und Auflösung von Autoritätsrollen.
- Reihenfolgen und Konflikt-/Fehlerregeln bei mehreren Bindings.
- Minimale dynamische View-Operationen (Set, Insert, Remove, Move, Replace) und ihre Revisionssemantik.
- Grenzziehung zwischen kompilierter Plugin-Definition, deploybarer Runtime-Konfiguration und transienten Runtime-Overrides.
- Adapter-Limits und tatsächliche SDK-Signaturen; Testnachweise sind geräteabhängig.
- Separater Sicherheitsentwurf für Authentisierung und nur lokal gebundene Kommunikationsendpunkte.

## 13. Nächster konkreter Arbeitsstand

Zunächst nur ein kleiner **Core-Model-Prototyp ohne Logitech-Plugin und ohne GUI**:

- Typisierte Python-Datenklassen/Objekte für das Projektmodell.
- JSON-Schema und Validator, deterministische Ein-/Ausgabe (Round-Trip).
- Referenz- und Typprüfung von Bindings, Capability-Validierung.
- Unittests für Action-Reuse, mehrfache Placements, generische States und fehlerhafte Modelle.
- Kleiner In-Memory-Runtime-Test für Command -> Handler -> State -> Presentation inklusive Snapshot-/Reconnect-Simulation.

Erst danach SDK-Adapter und mehrseitiges Studio an dieses definierte Modell binden. Das erhaltene SDK Lab v0.1.4 bleibt der Hardware-Nachweis und Regressionstest.
