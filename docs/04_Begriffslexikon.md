# 04 – Begriffslexikon / kanonische Terminologie

> **Aktuelle Begriffshoheit:** [ARCH-ADR-001](decisions/ARCH-ADR-001.md). Bei Logitech-spezifischen Konzepten ist der SDK-Begriff maßgeblich. `ComponentInstance`, `StateDefinition`, `Binding` und `Presentation` sind derzeit zusätzlich Namen des vorhandenen Legacy-Core-Modells; sie sind nicht automatisch Synonyme für native SDK-Klassen.

**Status:** Arbeitsterminologie für die Architektur. Begriffe, die Teil des Metamodell-v0.2-Entwurfs sind, sind mit **[E]** gekennzeichnet; Konzepte der vereinbarten Baseline mit **[B]**. Namen konkreter APIs werden erst später stabilisiert.

**Verwendungsregel:** In Dokumentation und Code auf Englisch geschriebene technische Bezeichner beibehalten. Deutsche Erklärungen verwenden die hier definierten Bedeutungen. Nicht stillschweigend durch ähnliche Alltagssprache ersetzen.

## A. Modellierung und Identität

| Begriff | Präzise Bedeutung | Nicht verwechseln mit |
|---|---|---|
| **Project** [B] | gesamtes editierbares Plugin-Modell mit Identität, Referenzen und Metadaten | generierte DLL / laufende App |
| **Metamodel** [B] | Definition der erlaubten Modelltypen und Beziehungen | konkretes Projekt |
| **Project Model** [B] | konkretes, aus dem Metamodell aufgebautes Projekt | Metamodell |
| **Schema** [E] | maschinelle Struktur-/Typregeln für serialisierte Modelle | Runtime-Protokoll |
| **Component** [B] | allgemeiner zusammensetzbarer Baustein | ausschließlich C#-Klasse |
| **ComponentType** [E] | versionierter, wiederverwendbarer Typvertrag in Bibliothek | konkrete Instanz |
| **ComponentInstance** [E] | ein konkret konfigurierter Typ im Projekt, mit stabiler ID | Platzierung oder Runtime-Objekt |
| **RuntimeInstance** [E] | aktuell laufende Ausführung mit Session und Ist-Daten | ComponentInstance-Definition |
| **Configuration** [B] | projektseitig gesetzte, validierte Parameter | aktueller dynamischer State |
| **Property** [E] | deklarierte konfigurierbare Eigenschaft eines Typs | beliebiger JSON-Key |
| **ID** [B] | stabile maschinenlesbare Identität, Ziel für Referenzen | Anzeigename, Position, Label |
| **Display Name** [B] | für Menschen lesbare und änderbare Beschriftung | ID |
| **Dependency** [E] | benötigter ComponentType/Adapter mit Versionsanforderung | Binding |
| **Capability** [B] | deklarierte, validierbare Fähigkeit oder Grenze einer Komponente/eines Adapters | bereits getestete Hardwarefunktion |

## B. Kommunikation und Zustand

| Begriff | Präzise Bedeutung | Nicht verwechseln mit |
|---|---|---|
| **Port** [B] | typisierte und gerichtete logische Schnittstelle eines Bausteins | TCP-Port, USB-Anschluss |
| **PortDefinition** [E] | Portvertrag am ComponentType | konkret adressierter Endpoint |
| **Endpoint** [E] | adressierbarer Anschluss einer konkreten Instanz/eines Modellelements | HTTP-URL |
| **Binding** [B] | deklarative Verbindung kompatibler Endpoints, ggf. Mapping/Policy | Python-Callback selbst |
| **Command** [B] | adressierte Aufforderung, eine Operation auszuführen | Erfolg / Result / Event |
| **Command Result** [B] | Rückmeldung/Abschluss zu einem Command | Status-State |
| **Event** [B] | zeitbezogene Benachrichtigung über ein Vorkommnis | jederzeit abrufbarer State |
| **State** [B] | aktueller abfragbarer typisierter Wert | Event oder Connection-Health |
| **StateDefinition** [E] | Vertrag eines State: Typ, Autorität, Scope etc. | aktueller Wert |
| **State Value** [B] | der tatsächlich aktuell gehaltene Wert | StateDefinition |
| **Authority** [B] | wer den maßgeblichen State schreiben darf | wo ein Replik gespeichert ist |
| **Scope** [B] | für welche Identitätseinheit ein State gilt | Lebensdauer/Persistenz |
| **Lifetime** [E] | wie lange ein State bzw. eine Instanz gültig bleibt | Persistenz |
| **Persistence** [B] | wo ein Wert über Prozess-/Session-Grenzen aufbewahrt wird | Scope |
| **Revision** [B] | monoton geordneter Stand für das Erkennen neuer/veralteter Updates | Zeitstempel allein |
| **Quality** [E] | Aussage über Aktualität eines State-Replikats (`unknown/fresh/stale`) | Nutzwert selbst |
| **Snapshot** [B] | vollständiger autoritativer Zustandsstand eines festgelegten Scopes | einzelne Eventmeldung |
| **Reconciliation** [B] | Abgleich von Soll- und Ist-/Replikzustand | blinde Event-Wiederholung |
| **Lifecycle** [B] | technische Phasen von Start, Verbindung, Ready, Disconnect, Reconnect | fachliche Workflowzustände |
| **Liveness** [B] | ob ein Laufzeitteil noch erreichbar/funktionsfähig ist | ob Befehle angenommen werden können |
| **Readiness** [B] | ob ein Laufzeitteil bereit ist, verlässlich zu arbeiten | fachliche Aktion erfolgreich |
| **Heartbeat** [B] | technisches Lebenszeichen | fachlicher Start-/Stop-Callback |
| **Session** [B] | zusammengehöriger Laufzeit-/Verbindungskontext mit Kennung | persistentes Projekt |
| **Correlation ID** [E] | verknüpft Command und Antwort/Abschluss | Component-ID |
| **Idempotency** [B] | Wiederholung derselben Operation ohne zusätzliche unerwünschte Wirkung | Exactly Once |

## C. Darstellung und Geräte

| Begriff | Präzise Bedeutung | Nicht verwechseln mit |
|---|---|---|
| **View** [E] | logischer Anzeigecontainer / Ansichtsdefinition | genau neun physische Tasten |
| **Dynamic Folder** [B/E] | per SDK-Adapter darstellbare dynamische View mit variabler Mitgliedschaft | feste Demoansicht mit 4/8 Umschalter |
| **Placement** [E] | eine konkrete Platzierung / Referenz auf eine ComponentInstance in einer View | kopierte Action-Definition |
| **Presentation** [E] | visuelle Vorschrift: Varianten, Text, Farben, Assets, Zuordnung | ComponentInstance selbst |
| **Variant** [E] | auswählbare Darstellung innerhalb einer Presentation | automatisch eigener State |
| **Asset** [E] | referenzierte Datei/Bild/Icon mit Metadaten | laufend gerendertes Bild |
| **Runtime Override** [B/E] | erlaubte temporäre Änderung von Darstellung/Mitgliedschaft zur Laufzeit | gespeicherte Projektänderung |
| **Device Adapter** [B] | übersetzt neutrale Semantik in Logitech SDK-Calls | Runtime-Kern |
| **Host Adapter** [B] | verbindet externe Anwendung (z. B. Python/Qt) mit Runtime | Logitech-SDK-Adapter |
| **Logi Plugin Service** | Logitech-Hostprozess, der C#-Plugin lädt und Gerät bedient | Studio-Generator |
| **Device Capability** [B] | konkrete Hardware-/SDK-Funktion samt Limits | logische Freiheit des Projektmodells |

## D. Werkzeuge und Lieferobjekte

| Begriff | Präzise Bedeutung | Nicht verwechseln mit |
|---|---|---|
| **SDK Lab** [B] | Experimentier-/Hardware-Nachweisumgebung | produktives Studio |
| **Plugin Studio** [B] | Editor zum Erstellen und Verändern des Projekts | Laufzeit oder erstelltes Plugin |
| **Component Library** [B] | versionierte Typverträge und generische Implementierungen | bloßer Snapshot von Testcode |
| **Manifest** [E] | strukturierter Vertrag eines ComponentType inkl. Ports, Capabilities, Version | Logitech-Paketmanifest |
| **Generator** [B] | transformiert validiertes Modell plus Bibliothek in Code/Artefakte | Runtime-Interpreter |
| **Build** [B] | kompiliert und paketiert erzeugte Quellen | Aktivierung in Options+ |
| **Deployment** [B] | registriert/installiert/aktualisiert Plugin in Zielumgebung | Build selbst |
| **Module Lock** [B] | dokumentierte Auflösung konkreter Bibliotheksversionen/Hashes | SDK-Lizenzverwaltung |
| **Hardware Evidence** [B] | nachprüfbare reale Beobachtung auf Zielgerät mit Teststand | erfolgreiche Kompilierung |
| **Vertical Slice** [B] | minimaler End-to-End-Schnitt durch Editor → Modell → Runtime → Hardware | bloßer API-Mocktest |

## E. Begriffsregeln und erlaubte Synonyme

- **„Aktion“** ist als Nutzersprache erlaubt, im Modell aber mehrdeutig. Technisch immer spezifizieren: `ComponentInstance` eines Action-Typs, `Command`, `Event` oder `Placement`.
- **„Zustand“** meint je nach Kontext `StateDefinition`, `State Value`, `Quality` oder `Lifecycle Status` – in API/Dokumentation auseinanderhalten.
- **„Plugin“** meint entweder **Plugin-Projekt** oder **generiertes/installiertes Plugin**; beim Übergang den Zusatz nennen.
- **„Kontext“** ist bisher **kein eigener verabschiedeter universeller Metamodelltyp**. Je nach späterem Entwurf kann er eine State-Gruppe, ein Binding-Selector oder ein Views-Schalter sein. Nicht unbemerkt als Pflichtentität einführen.
- **„Callback“** ist eine mögliche konkrete Handler-Implementierung, **kein** Ersatz für den neutralen Port-/Command-Vertrag.
- **„KeepAlive“** ist technische Kommunikation, **kein** Pflicht-Callback jeder Action.
- **„Folder öffnen“** über eine zugewiesene Hardwareaktion ist etwas anderes als ein beliebiger programmatischer Befehl zum Öffnen aller Logitech-Folder; Adapter-Capabilities gesondert nachweisen.

## F. Begriffe, die bewusst **noch nicht** feststehen

`ActionDefinition` versus `ComponentInstance`, exakte Signatur von `on_command`, `set_state`, `set_folder_actions`, JSON-ID-Notation, erlaubte `scope`-Enums, vollständige Mapping-Sprache und transportseitiger Message Envelope. Eine spätere Freigabe sollte diese Begriffe entweder stabilisieren oder als explizite Aliase dokumentieren; bis dahin bleiben Beispielnamen Illustrationen.


## G. Ergänzende P0-Begriffe (`PROPOSED`, keine neue Baseline)

| Begriff | Bedeutung | Status |
|---|---|---|
| **Qualified Endpoint Reference** | Strukturierte Endpunktreferenz aus `owner_kind`, `owner_id`, `port` anstatt eines zu zerlegenden Strings | `PROPOSED`, P0-ADR-001 |
| **Virtual Port** | Modellseitig definierter Standardanschluss etwa `State/value` oder `Presentation/selector`; kein zusätzlicher Geräteport | `PROPOSED`, P0-ADR-003 |
| **Authority Generation** | Kennung einer Autoritäts-Inkarnation, die zusammen mit einer Revision Aktualitätsvergleiche nach Neustarts absichert | `PROPOSED` für P2, keine Spike-Funktion |
| **Core Validation** | Geräteunabhängige Prüfung eines Modellgraphen | `PROPOSED`, P0-ADR-007 |
| **Adapter Validation** | Prüfung konkreter Geräte-/SDK-Fähigkeiten vor einem Build/Deployment | `PROPOSED`, P0-ADR-007 |

Verbindliche Begriffs- und Statusquelle bleibt [08_Entscheidungsregister.md](08_Entscheidungsregister.md); alle P0-Vorschläge sind unter [decisions/](decisions/README.md) erfasst.

## Ergänzung – native Logitech-Begriffe (03.11.2026)

| SDK-Begriff | Abgrenzung zum bisherigen Core |
|---|---|
| `PluginDynamicCommand` | Native SDK-Aktionsklasse, nicht automatisch identisch mit jedem `ComponentInstance`-Typ. |
| `actionParameter` | SDK-Parameter eines konkreten Action-Aufrufs; muss auf der Python-Bridge erhalten bleiben, soweit vorgesehen. |
| `PluginMultistateDynamicCommand` | Native Action mit registrierten 0-basierten Zuständen; kein Synonym für `Presentation.variants`. |
| `AddState()` | SDK-Definition eines State mit Name/Beschreibung; nicht mit Runtime-`StateStore.write` verwechseln. |
| `PluginDynamicAdjustment` | Eigener nativer SDK-Aktionstyp; nicht notwendigerweise gewöhnlicher Command mit Parameter. |
| `PluginDynamicFolder` | Native Ordner-/Navigationsklasse; eine alte `View` ist nur bisherige Projektrepräsentation. |
| `.ict` | Native Icon-Template-Datei mit Layout/Positionen/Farben/Text/Bild; kein fertiges bitmapbasiertes State-Bild. |
| `GetCommandDisplayName()` | SDK-Beschriftung; kann von bereits ins Bild gerendertem Text verschieden sein. |
| `ActionImageChanged()` | Native Aufforderung zur Bildaktualisierung; keine eigene neue Action-State-Definition. |

Zusätzliche SDK-Merkmale sind zuerst aus der dokumentierten/installierten API zu übernehmen, nicht in neue Oberbegriffe zu übersetzen.
