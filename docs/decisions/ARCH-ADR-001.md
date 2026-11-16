# ARCH-ADR-001 – Logitech-natives Modell als führende Semantik

- **Status:** `ACCEPTED / ARCHITEKTURRICHTUNG` (Nutzerentscheidung vom 03.11.2026)
- **Geltung:** Neues Zielmodell des Logitech Plugin Studio, künftige SDK-Funktionen, Bridge, Generator und Widgets.
- **Implementierungsstand (Fortschreibung 03.11.2026):** **SDK-nativer Softwarepfad implementiert und regressionsgeprüft; 15/17 Gaps IMPLEMENTED, NF-11/12 PARTIAL (NF-16 jetzt mit dem fertigen SymbolDesigner verbunden).** [Migrationsbericht](../../work/migrations/native-first-20261103/04_migrationsbericht.md). Das bisherige Projektformat bleibt kompatibel; Hardware-/Options+-Nachweise und eine unabhängige Produktabnahme stehen separat aus.
- **Vorrang:** Diese spätere Entscheidung ersetzt die frühere **SDK-unabhängige/fachneutrale Modellierung als primäres Produktziel** (insbesondere AR-007 und den entsprechend formulierten Teil von RT-ADR-006). Die übrigen Sicherheits-, Referenz-, Zustands- und Validierungsregeln früherer ADRs bleiben bis zu einer ausdrücklich beschlossenen, getesteten Ablösung in Kraft.

## 1. Anlass

Die bisherige Architektur wurde als unabhängig vom Logitech SDK gedachtes Komponenten-/Port-/Binding-/State-/Presentation-System entworfen, das erst nachträglich auf Logitech übersetzt wird. Dadurch besteht bei Erweiterungen um native Logitech-Merkmale die Gefahr konkurrierender Fachsemantik, redundanter State-Engines, verlustreicher Konvertierungen und umfangreicher Änderungen in Generator, Runtime und Widgets.

Die neue Entscheidung stellt das bestehende Logitech Actions SDK als **fachliches Referenzmodell** an die Spitze. Das Studio ist Werkzeug und Python-Anbindung für Logitech-Plugins; keine eigenständige universelle Plugin-Plattform.

## 2. Verbindlicher Grundsatz

**Native First – Minimal Bridge – Optional Extensions**

1. **Logitech bestimmt die Semantik.** Klassifikation, Parameter, Zustände, Identitäten, Darstellungs- und Navigationsmöglichkeiten werden zuerst anhand der tatsächlich installierten Logitech Actions SDK API, ihrer dokumentierten Verträge und überprüfter SDK-Beispiele bestimmt.
2. **So wenig eigene Abstraktion wie technisch möglich.** Nur die zur Überbrückung zwischen C#/.NET, Python, Datei-/Prozessgrenzen und Qt zwingend benötigten Transport-, Typ- und Lebenszyklusmechanismen werden im Bridge-Kern implementiert. Sie sind semantisch transparent, begründet und nachweisbar.
3. **Mehrwert ist kein Argument für ein alternatives Kernmodell.** Komfort, Vereinfachung, Vorlagen, Automatisierungen, Massenbearbeitung, UI-Workflows und andere eigene Funktionen gehören in eine **optionale, klar abtrennbare Schicht oberhalb** des SDK-nativen Vertrags. Native SDK-Funktionen bleiben auch ohne diese Schicht zugänglich.
4. **Keine stillen Umdeutungen oder verlustbehafteten Übersetzungen.** Ein SDK-Begriff darf nicht auf eine abweichende eigene Entität mit anderen Zustands-/Lebensdauerregeln reduziert werden. Nicht unterstützte Fälle werden als Capability-Gap ausgewiesen, nicht heimlich angepasst.
5. **Funktionen vor Abstraktionen.** Für jede neue Eigenschaft zuerst SDK/XML/DLL/Beispiel prüfen, dann die minimale Brücke, danach optional UI-Komfort. Keine generische Engine ohne durch SDK/Sprachgrenze belegte Notwendigkeit.
6. **Einen einzigen fachlichen Owner pro Wert oder Operation.** Keine konkurrierenden Autoritäten in C#, Python, Qt und Projektdatei. Bindings/Renderer/State-Synchronisation dürfen nicht unabhängig die gleiche Fachentscheidung treffen.
7. **Kompatibilität ist ein eigenes Gate.** Das bisherige Projektformat `0.1-draft`, P0-/RT-ADRs und abgenommene Codepfade bleiben bis zu einer separat geprüften Migration erhalten. Diese ADR ist **keine Freigabe**, sie ad hoc umzuschreiben.

## 3. Referenzkonzepte des Logitech SDK – nicht zu erfinden

Das genaue Inventar wird in [SDK-Mapping/Gaps](../specifications/sdk-native-modellabgleich-v01.md) geführt. Insbesondere:

- **Plugin / Action-Klassen:** `PluginDynamicCommand`, `PluginMultistateDynamicCommand`, `PluginDynamicAdjustment`, `PluginDynamicFolder` und andere durch die installierte API belegte Typen. Nicht alles unter einem zwangsläufig gleichen `core.command_action`-Mechanismus verstecken.
- **Action Parameters:** `actionParameter` beeinflusst Identität/Anzeige/State-Aufrufe; konkrete SDK-Semantik und Lebensdauer explizit erhalten.
- **Multistate Actions:** `AddState` registriert eine vorgegebene Anzahl 0-basiert nummerierter Zustände. Pro SDK-State können Anzeigename, Beschreibung, Grafik und LED-Farbe verschieden sein. `ToggleCurrentState()` ist nur für genau zwei registrierte Zustände zulässig. Der native State-Mechanismus ist **nicht identisch** mit einem beliebigen Python-Value-Store.
- **Dynamische Bilder:** Auch gewöhnliche Dynamic Commands können ein von Zustand/Parameter abhängiges `GetCommandImage()` zurückgeben und per `ActionImageChanged()` neu zeichnen. Multistate ist hierfür nicht in jedem Fall erforderlich.
- **Icon Templates:** `.ict` (Hintergrund + optionale Image-/Text-Elemente mit Layout, Schrift, Farben, Sichtbarkeit), PNG/SVG-Dateien und native Template-Priorität (**User > Action > Plugin > Global**) sind zu respektieren. Ein gerendertes PNG ist ein *Anzeigeprodukt*, nicht automatisch das native Editier-/Distributionsformat.
- **Folder / Navigation:** Die SDK-Device-/Navigation-Angaben regeln belegbare Tasten; eine 8+Back-Grafik ist keine universelle Hardwaregrenze. Paging und Back sind anhand der konkreten SDK-Navigation zu entscheiden.
- **SDK-Callbacks und Notifications:** Native Änderungen, etwa `ActionImageChanged()`, nicht durch willkürliche eigene Eventprotokolle ersetzen, sofern die API bereits eine direkte Lösung enthält.

Die tatsächliche installierte API und die zum Build eingesetzte DLL haben Vorrang vor Beispielen aus älteren Versionen oder reinen Dokumentationsannahmen. Nicht belegte Spezialsignaturen per Reflection/Build-/Hardwaretest absichern.

## 4. Modellierungs- und Bridge-Schichten

```text
PySide6 Studio, Autorentools, Vorschau und optionale Komfortfunktionen
                    |
       SDK-native Projekt-/Action-Semantik
                    |
       minimale Python <-> C# Bridge
       (Aufruf, Events, Datenwerte, sichere Kommunikation)
                    |
          Logitech Actions SDK / Plugin Service
```

Ein Python-Datentransferobjekt darf native SDK-Eigenschaften verlustfrei abbilden; sein Bestehen rechtfertigt **keine zweite Action-, State-, Folder- oder Grafiksemantik**.

Technisch notwendige Schutzfunktionen (Authentisierung, Fehlerbehandlung, Größenlimits, Reconnect, Threads und IPC) sind zulässig, solange sie die native Fachsemantik nicht ersetzen. Diese Schutzmechanismen sind keine zusätzlichen fachlichen Modelle.

**Zusatzfunktionen** liegen in separaten Modulen und sind umgehbar; sie dürfen native Daten lesen/anzeigen oder gezielt verändern, aber nicht zwangsläufig alle Logitech-Aktionen durch ein eigenes Binding-/State-/Layer-System zwingen.

## 5. State-Zuständigkeit – keine vorschnelle Verschmelzung

Folgende Dinge dürfen **nicht** als ein einziger State-Typ ausgegeben werden:

1. native Multistate-Action-Definition mit festen 0-basierten SDK-Indizes;
2. aktuell ausgewählter nativer SDK-State, ggf. pro `actionParameter`;
3. externe Python-Anwendungswerte und deren Zustandsautorität;
4. auswählbare grafische `Presentation`-Variante;
5. technische Replikqualität (`fresh/stale/unknown`) bzw. Connection-Health;
6. reine, nicht autoritative Studio-Designvorschau.

Für jeden Anwendungsfall ist der fachliche Owner zu definieren, bevor ein Mapping oder ein Adapter eingeführt wird. Eine native SDK-State-Anzeige kann direkt vom SDK verwaltet werden; ein externer Python-State kann mit minimaler Bridge gespiegelt werden. **Keine zweite unabhängige State-Maschine als Standard.**

Der bereits implementierte `StateStore` ist ein **kompatibel zu haltender Implementierungsstand**, keine automatische Vorgabe für alle künftigen SDK-Aktionstypen. Die bisherigen RT-ADR-Autoritäts-/Scope-/Revisionsregeln bleiben für diesen bestehenden Python-Host-Pfad erhalten, bis eine sichere Migrationsentscheidung getroffen und getestet ist.

## 6. Icons und gemeinsames Rendering

- Der Symbol-Designer bearbeitet natives `.ict` und native Bildquellen.
- Ein aufgelöster Anzeigestand kann als fertiges `QImage` an das Keypad-Widget übergeben werden; die QImage-Fläche ist *abgeleitete Ausgabe*, nicht Modellwahrheit.
- Eine **schmale gemeinsame Auswertungslogik** darf Layout/Varianten/Overrides konsistent auswählen; sie darf nicht zu einem eigenen dauerhaften Layerformat werden.
- Native `.ict`-Prioritäten und Benutzeranpassungen dürfen nicht durch stilles Flattening zu PNG unwirksam gemacht werden.
- `GetCommandDisplayName()` und in Bitmap gerenderter Text sind gesonderte SDK-Ausgabekanäle; doppelte LCD-Beschriftung vermeiden.
- Qt-, C#- und physische Ausgabe auf nachweisbare Unterschiede testen; keine automatische Pixelgleichheit behaupten.

## 7. Geltung bestehender freigegebener Regeln

**Weiter gültig, sofern nicht separat geändert:** stabile IDs und Referenzen (P0-ADR-001); dokumentierte Persistenz-/Runtime-Trennung (P0-ADR-002); Commands/Events/Results (P0-ADR-003); konservative Validierung für das bisherige Schema (P0-ADR-004/007); ein autoritativer Writer pro bestehendem Scoped State (P0-ADR-005, RT-ADR-002); Trennung von View/Placement und dynamischem Laufzeit-Istwert (P0-ADR-006); technische Snapshots/Health/Fehlerschutz auf dem bestehenden Hostweg (RT-ADR-001–005).

**In der Zielrichtung überholt:** Der *Anspruch*, das SDK-agnostische `ComponentType/Binding/StateDefinition/Presentation`-Metamodell sei fachlich führend und Logitech nur einer von beliebigen austauschbaren Adaptern (AR-007, betreffender Teil RT-ADR-006 sowie erläuternde Texte). Diese Teile sind nun **historischer IST-/Legacy-Vertrag**, nicht die Vorgabe für Neuentwicklungen.

Eine spätere Migration muss weiter beweisen, dass existierende Projekte und Host-/Hardwarepfade funktionieren. Ältere Abnahmeberichte werden nicht rückwirkend umgeschrieben.

## 8. Prüfregeln für neue Arbeitspakete

Vor Umsetzung jedes SDK-relevanten Features:

1. Verifizierte SDK-Klasse, Methode, Event, Format und Gerätefähigkeit benennen (lokale XML/DLL, Herstellerdokumentation, Beispiel).
2. Explizit festlegen, welcher Anteil native SDK-Funktion, welcher technische Python-/C#-Bridge, welcher optionale Komfort ist.
3. Bei eigenem DTO die **minimal erforderlichen Felder**, Semantik und Konvertierungsbelege dokumentieren.
4. State-/Parameter-Owner und Änderbarkeit vor Persistenz-/UI-Design klären.
5. Roundtrip, Capability-Grenzen, Migration und fehlendes Feature explizit testen; ohne Beleg keinen Logitech-Support behaupten.
6. Gemeinsame UI-Widgets bleiben möglichst nur Anzeige und Bedienung; sie führen keine zweite SDK-Entscheidungslogik.

## 9. Auswirkungen und offene Entscheidungen

Der konkrete Alt-/Neu-Abgleich und ein priorisiertes, noch nicht implementiertes Folgenregister stehen unter:
- [SDK-nativer Modellabgleich und Gaps](../specifications/sdk-native-modellabgleich-v01.md)
- [Änderungs- und Konsolidierungsprotokoll](../../work/planning/native-first-konsolidierung-20261103.md)

**Diese ADR allein erteilt keine Freigabe zur Umstellung der Codebase oder des gespeicherten Projektformats.** Eine solche Migration ist separat zu spezifizieren, zu testen und erst anschließend durchzuführen.

## 10. Quellen

- Installiert: `C:\Program Files\Logi\LogiPluginService\PluginApi.xml`; zugehörige SDK-DLL vor konkreten Multistate-Implementierungen per API-/Reflection-/Buildprobe prüfen.
- SDK-Dokumentation: `P:\LokaleProjekte\logi_actions_sdk\logi-actions-sdk-rec\docs-ai\logi-actions-sdk-llms-full.md`, Abschnitte *Multistate Plugin Actions*, *Icon Templates*, *Vector Images*, *Change a Button Image*.
- Derzeitiger eigener Code: `src/core/model.py`, `src/runtime/state_store.py`, `src/adapters/logitech/product.py`, `src/adapters/logitech/templates/Visuals.cs.in`, `src/studio/images.py`.

## Fortschreibung 08.11.2026 – konsequente Schichtentrennung

Die verbindliche Entscheidung **Native First – Minimal Bridge – Optional Extensions** bleibt unverändert. Bei der Umsetzung wurden die fachlichen `folder_runtime`-/`folder.layout`-Auswertungen aus der generischen C#-Bridge entfernt und der optionalen SharedFolder-Schicht zugeordnet; die Python-Projektion, Hostklasse und C#-Vorlage liegen jetzt unter `src/extensions/shared_folders/`. Die SDK-Actionklassen und der generische Python-Callbacktransport bleiben kompatibel. Die auf einzelne SDK-Signaturen bezogene [Python-API-Checkliste](../specifications/sdk-python-api-checklist.md) unterscheidet strikt C#-Implementierung, Python-Callback und direkte Python-API. Die vollständig erweiterungsfreie Native-Folder-Generierung ist ein noch offener Unterpunkt, keine stillschweigend erledigte Migration. [Schichtenvertrag](../architecture/sdk-bridge-schichtentrennung.md).
