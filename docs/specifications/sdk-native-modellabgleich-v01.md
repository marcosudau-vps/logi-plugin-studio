# SDK-nativer Modellabgleich und Gap-Register v0.1

**Stand:** 03.11.2026 · **Status:** ursprüngliche IST-/SOLL-Analyse vor der Implementierung; **Ergebnisfortschreibung:** [SDK-native Migration NF-01–17](../../work/migrations/native-first-20261103/04_migrationsbericht.md). Diese Gap-Beschreibungen sind die ursprüngliche Ausgangslage, nicht der aktuelle unerledigte Status sämtlicher Punkte.  
**Vorrangige Entscheidung:** [ARCH-ADR-001](../decisions/ARCH-ADR-001.md).  
**Grundregel:** Logitech-Semantik ist führend, Python-/C#-Abstraktion nur bei technischer Notwendigkeit, Komfort als optionale Oberschicht.

## 1. Referenzbasis und Befundgrenze

Geprüft: `src/core/model.py`, `src/core/validate.py`, `src/runtime/state_store.py`, `src/library/document.py`, `src/library/presentation.py`, `src/studio/images.py`, `src/adapters/logitech/product.py`, `src/adapters/logitech/templates/Visuals.cs.in`; vorhandenes HW-01-Projekt und Ergebnisberichte; lokale SDK-Langdokumentation mit *Multistate Plugin Actions* / *Icon Templates* / *Vector Images* / *Change a Button Image* sowie installierte `PluginApi.xml`.

**Beleggrenzen:** Keine vollständige Reflection der installierten SDK-DLL und keine neue Geräteprobe in dieser Dokumentationsrunde. Lokale Beispiele und SDK-Dokumentation sind keine Bestätigung, dass jede Methode bei der installierten Plugin-Service-Version identisch arbeitet. Status `DOKUMENTIERT` ist von `IMPLEMENTIERT` und `HARDWARE_PASS` getrennt.

## 2. SDK → heutiger IST-Stand → native Sollrichtung

| ID | SDK-Konzept | Heutiger Stand | Ziel-/Prüfrichtung | Priorität |
|---|---|---|---|---|
| NF-01 | Plugin, SDK-Action-Typen | Generator erzeugt hauptsächlich `PluginDynamicCommand` und `PluginDynamicFolder`; generische `core.command_action`-Typen | SDK-Typen/Fähigkeiten zuerst explizit modellieren; keine generische Pflicht-Action, die nativen Typunterschied verdeckt | P0 |
| NF-02 | `actionParameter` | C# `RunCommand(String actionParameter)` wird auf `Bridge.Dispatch(ComponentId)` projiziert; Parameter nicht weitergegeben | Parameter-Identität und Kontext bis Python/SDK-Bild/State erhalten, incl. leer/null und Aktualisierungsgrenzen | P0 |
| NF-03 | `PluginMultistateDynamicCommand` / `AddState` | Kein nativer Multistate-Generator; Studio besitzt eigene StateDefinitions und Presentation.variants | Native 0-basierte States, feste Zustandsanzahl, State-Text/Bild/LED, parameterabhängige APIs gesondert modellieren | P0 |
| NF-04 | Native State-Steuerung | `StateStore` und Host-Replik in Python führen externe States | Für jeden Action-Typ SDK-owned vs Python-owned ausdrücklich entscheiden; kein doppelter Owner | P0 |
| NF-05 | Gewöhnliche dynamische Bildwechsel | `Visuals.Variant` + `ActionImageChanged()` im Generator vorhanden | Bestehendes `PluginDynamicCommand`-Verhalten erhalten; nicht jedes grafische Toggle als nativer Multistate deklarieren | P0 |
| NF-06 | `.ict`-Layout / Precedence | Neuer SymbolDesignerWidget im separaten AP; bisher C#-BitmapBuilder und Qt-Renderer unabhängig, keine durchgängige ICT-Pipeline | Native ICT samt Bildquelle/Text und User > Action > Plugin > Global respektieren; kein eigenes Layer-Persistenzformat | P0 |
| NF-07 | Bild-/Textausgabe | `render_tile` rendert Preview-Badge; `Visuals.Render` rendert Bitmap/Text und Qualitätsbadge | Einmalige Varianten-/Layoutentscheidung; Qt/SDK getrennte technische Ausgabe, keine doppelten Captions | P0 |
| NF-08 | Zustand/Scope/Quality | `StateDefinition` + `StateStore` mit runtime/component/placement und fresh/stale/unknown | Als vorhandenen Python-Host-Pfad erhalten, *nicht* pauschal auf native SDK-State-Indizes umetikettieren; native Grenzen messen | P0 |
| NF-09 | Dynamic Folder / Navigation | `View` + `Placement`, C# `PluginDynamicFolder` mit `ButtonArea`, UI 8+Back-Simulation | Physische Navigationsart und verfügbare LCD-Slots nach SDK-Descriptor, nicht durch statische Vorschau ableiten | P1 |
| NF-10 | `PluginDynamicAdjustment` | Kein entsprechender Produktgenerator nachgewiesen | Native Adjustment-Eigenschaften/Callbacks separat als erstklassige SDK-Fähigkeit prüfen | P1 |
| NF-11 | Action Editor / Parameter UI | Vorhandener generischer JSON-/Config-Editor, keine native ActionEditor-Entsprechung | SDK-Editor/Parameter-Verträge direkt abbilden; UX-Assistenten optional | P1 |
| NF-12 | LED-/State-Metadaten | Grafik-/Textvarianten, keine vollständigen nativen `AddState`-Metadaten | Per SDK-State Name, Description, Button-Image und LED-Farbe transportieren | P1 |
| NF-13 | `ActionIcons` / `ActionSymbols` / ICT-Auslieferung | PNG-Assetpfad im Generator; native Vorlagen/Icons noch nicht durchgängig | SDK-Paketstrukturen und Lookup-Namen nutzen; Datei-/Ressourcenrechte und Overrides bewahren | P1 |
| NF-14 | Projektmodell als *eigene* generische Wahrheit | `ComponentType`, `Binding`, `StateDefinition`, `Presentation` als primäre Core-Entitäten | Einmalig SDK-nativen Projektvertrag definieren, bestehenden `0.1-draft`-Bestand kompatibel migrieren; Komfortgraph optional | P0 |
| NF-15 | Python Bridge | Authentisierter Host, Commands, States, Reconnect und Snapshot implementiert | Technische IPC-/Sicherheitsfunktion erhalten; auf native SDK-Operationen/Events begrenzen, API-Mapping transparent dokumentieren | P0 |
| NF-16 | Widgets als Anzeige oder eigene Fachlogik | SymbolDesigner und Keypad-Lab eigenständige APs; Keypad-Draft mit Platzierungsoperationsdaten | Widgets nur native / aufgelöste Daten und Intents; keine eigene persistierte Action-/State-Semantik | P0 |
| NF-17 | Kompatibilität / Abnahme | `0.1-draft`, zahlreiche bereits abgenommene Core-/Runtime-/Host-Prüfungen | Migrationsplan, Import/Export, Golden-Tests, generierter C#-Build, Host-/Hardware-Evidenz vor Ersetzung | P0 |

**P0** bedeutet *zuerst konzeptionell und für Integrationsplanung klären*, **nicht** unmittelbar alles implementieren. **P1** bedeutet darauf aufbauend prüfen.

## 3. Besonders wichtige Konflikte im IST-Code

### 3.1 Ein Kommando verliert das SDK-`actionParameter`

In `src/adapters/logitech/product.py` wird für das erzeugte `PluginDynamicCommand` derzeit sinngemäß

```csharp
protected override void RunCommand(String actionParameter) => Bridge.Dispatch(ComponentId);
```

generiert. Der native Parameter wird nicht an die Python-Seite weitergegeben. Dies ist keine vollständige SDK-nahe Abbildung. **Kein stilles Fixen:** Eine Änderung betrifft Wire-Contract, CommandContext, Validierung, Logs, bestehende Bindings und Regressionstests.

### 3.2 Zwei voneinander unabhängige Bild-Renderer

`src/studio/images.py::render_tile` zeichnet über `QPainter`; `Visuals.cs.in` zeichnet mit `BitmapBuilder`. Unterschiedliche Font-/Fit-/Badge-/State-Qualitätsregeln können divergierende Bilder erzeugen. Native `.ict`-Layoutverträge werden nicht durchgängig übernommen.

Vor dem Austausch einen gemeinsamen **semantischen** Resolver und konkrete Tests des SDK-Verhaltens festlegen; nicht automatisch das generierte SDK-Bild zu QImage oder umgekehrt machen.

### 3.3 Presentation.variants ist nicht `AddState()`

Heute wählt `Visuals.Variant()` anhand des Python-Host-States oder eines Fallbacks einen Variantenschlüssel. Das ist ein grafischer Selektor, **keine** registrierte native SDK-Multistate-Action.

Nicht durch eine automatische Zuordnung von alphabetisch sortierten Variantennamen zu 0-basierten SDK-State-Indizes „lösen“. Der State-Vertrag muss native Reihenfolge, Ownership, `actionParameter`, Anzahl und das Änderungsverhalten berücksichtigen.

### 3.4 8+Back ist UI-Konvention

Die aktuelle `StudioWindow.render_preview`-Vorschau zeigt einen simulierten Back-Slot plus acht Inhalte. Dies ist **kein SDK-Beleg**, dass niemals neun LCD-Aktionen möglich sind. SDK-Navigationsart und Gerätecababilities im separaten Device-Descriptor prüfen.

## 4. Vorschlag zum Ziel-Datenfluss (noch kein fertiges Schema)

```text
SDK Action / Parameter / registrierte States / Folder / Icon Template
        |                         |
        |                  externe Python Werte (nur falls nötig)
        |                         |
        +----> minimaler Bridge-/Präsentationsvertrag
                           |
            native SDK-Darstellung / Gerät
                           |
          optionale Autoren- und Qt-Vorschau
```

Das bereits existierende `ComponentInstance`/`Placement`/`Presentation`-Schema kann während der Migration eine **Kompatibilitätsrepräsentation** bleiben. Ob einzelne Konzepte beibehalten, umbenannt oder durch native SDK-Modelle ersetzt werden, muss **pro Funktion** nach verlustfreier Mapping-Probe entschieden werden.

**Keine automatische Umwandlung der bisherigen `StateDefinition` in native SDK-Multistate-Klassen.** Ein externer Python-State mit typisierten Werten und Reconnect ist ein anderes Problem als ein per `AddState` definierter Action-State.

## 5. Fragen vor einer Code-/Projektformatmigration

1. Welche nativen Action-Klassen und API-Methoden bietet die *installierte* DLL konkret (Reflection-Matrix)?
2. Ist `actionParameter` eindeutig pro Action, pro Placement, pro dynamischer Command-Instanz oder abhängig vom API-Typ? Welche Overloads besitzen State-/Image-APIs?
3. Wie werden native States in Logitech angelegt, geändert, angezeigt, persistiert und mit Python-Callbacks synchronisiert, falls gewünscht?
4. Welche Felder und Prioritäten aus `.ict` und User-Overrides müssen verlustfrei erhalten werden? Welche Bitmap-/SVG-Kanäle überschreiben welche?
5. Wie wird SDK-Navigation (ButtonArea/EncoderArea) am tatsächlichen MX Keypad für unterschiedliche Profile/Folder dargestellt?
6. Wie lassen sich bestehende Projektdateien und alle aktuellen Runtime-/Hardware-Nachweise ohne Datenverlust migrieren bzw. parallel verwenden?
7. Welche Komfortfunktionen (`Binding`-Graph, State-Mapping, Templates, Bulk-Actions) sind optional und dürfen nicht die SDK-Semantik bestimmen?

## 6. Empfohlener Prüf- und Migrationspfad

- **M0 – Vertrag:** Installierte SDK API reflektieren, native Typ-/Methodenmatrix und konkrete Minimalbeispiele erzeugen.
- **M1 – Mapping:** Für jede IST-Entität eine native Zielabbildung oder nachweislich notwendige Python-Sprachgrenzenbrücke festhalten.
- **M2 – Kompatibilität:** Neuen Vertrag *neben* bestehenden `0.1-draft`-Projektpfad stellen; Roundtrip-/Migrationsnachweise, keine produktive Umschaltung.
- **M3 – Visuals und States:** Native `.ict`-/Multistate-Proben, State-Owner festlegen, Qt-/SDK-Ausgabe vergleichen.
- **M4 – Generator/Bridge:** Native Action/Parameter/State-Generierung mit regressionssicherem Migrationstestsatz.
- **M5 – Studio/Widgets:** Nach stabiler API Adapter anpassen, Komfortschicht optional anbinden.
- **M6 – Hardware:** Back/Paging, Multi-State, State-Wechsel, Restart/Reconnect und Benutzersicht gesondert abnehmen.

**Nächster Schritt:** Abhängigkeiten und Betroffenheit dieser Einträge im Folgegespräch entscheiden; keine umfassende Code-Migration ohne eigenständige Freigabe.
