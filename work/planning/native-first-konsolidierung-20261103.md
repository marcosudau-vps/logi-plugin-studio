# SDK-native Architekturkonsolidierung – Änderungsprotokoll 03.11.2026

**Historischer Stand dieser Dokumentationsrunde:** Architektur korrigiert, Migration damals noch nicht ausgeführt. **Fortschreibung desselben Tages:** [Software-Migrationslauf umgesetzt](../migrations/native-first-20261103/04_migrationsbericht.md), 15/17 Themen IMPLEMENTED und 2 PARTIAL (NF-11/12); nativer SDK-Build und 369 Regressionstests erfolgreich, einschließlich NF-16-SymbolDesigner-Anbindung. Der Vorher-Snapshot dieser Dokumentationsrunde bleibt unverändert.

**Verbindlich:** [ARCH-ADR-001 – Logitech-natives Modell als führende Semantik](../../docs/decisions/ARCH-ADR-001.md).  
**Technisch:** [SDK-nativer Modellabgleich und 17 Gaps](../../docs/specifications/sdk-native-modellabgleich-v01.md).  
**Originaldateien:** [gesichertem Original-ZIP](native-first-snapshot-20261103.zip) mit [Manifest/Hashes](native-first-snapshot-20261103-manifest.json).

## 1. Geänderte Architekturentscheidung

- **Früher:** SDK-unabhängiges, fachneutral definiertes Core-/Binding-/State-/Presentation-Metamodell fachlich führend; Logitech ist nachgeschalteter Adapter.
- **Jetzt:** Native Logitech-SDK-Konzepte sind **fachlich führend**; **nur technisch notwendige** Python↔C#-Bridge; zusätzliche selbst entwickelte Funktionen ausschließlich als **optionale Komfort-/Erweiterungsschicht**.
- **Historie:** P0/RT-ADRs, frühere Reviews, Snapshots und Tests bleiben historisch richtig. Nur die **Zielrichtung** fachneutraler SDK-Abstraktionen wurde durch spätere ADR ersetzt; konkrete Kompatibilitäts- und Sicherheitsregeln werden erst nach Migration angepasst.
- **Nicht durchgeführt:** Keine Änderung von `src/*.py`, C#-Generatorvorlagen, `schemas/*.json`, bestehenden `project.json`, Nutzerdaten, Logitech-Plugin-Service, installierten Plugins oder Hardware.

## 2. Neue Dokumente

| Datei | Funktion |
|---|---|
| [docs/decisions/ARCH-ADR-001.md](../../docs/decisions/ARCH-ADR-001.md) | Führende Architekturentscheidung mit Vorrang, Randbedingungen, Scope und Migrationsgate |
| [docs/specifications/sdk-native-modellabgleich-v01.md](../../docs/specifications/sdk-native-modellabgleich-v01.md) | SDK-/Code-Abgleich, 17 konkrete Gaps, Zustands-/Parameter-/ICT-Risiken und Migrationsschritte |
| [work/planning/native-first-konsolidierung-20261103.md](native-first-konsolidierung-20261103.md) | Dieses vollständige Änderungs-/Betroffenheitsregister |
| [work/planning/native-first-snapshot-20261103-manifest.json](native-first-snapshot-20261103-manifest.json) | Vorher-/Nachher-Hashes und Ursprungsdateien aller 37 inhaltlich geänderten Bestandsdateien |

## 3. Alle geänderten Bestandsdateien

Die Tabelle ist automatisch aus dem gesicherten Änderungsmanifest erzeugt. Sie enthält **jede** geänderte Bestandsdatei und die vorgenommenen Korrekturen.

| Datei | Konkrete Änderungen |
|---|---|
| [CHANGELOG.md](../../CHANGELOG.md) | Änderungshistorie um neue Architekturrevision ergänzt |
| [component_types/README.md](../../component_types/README.md) | Typkatalog nicht mehr als neue fachliche SDK-Quelle dargestellt |
| [docs/01_Systemidee.md](../../docs/01_Systemidee.md) | Systemidee neu ausgerichtet; Frühere Core-Ausrichtung nicht mehr als neue SDK-Zielregel präsentiert; Explizites aktuelles Zielbild ergänzt |
| [docs/02_Ebenen_und_Verantwortung.md](../../docs/02_Ebenen_und_Verantwortung.md) | Schichtdiagramm als IST statt SDK-neutrale Sollvorgabe eingeordnet; Schichtenverantwortung native-first erläutert |
| [docs/03_Metamodell.md](../../docs/03_Metamodell.md) | Metamodell als Legacy-IST mit SDK-native Zielrichtung eingeordnet; Entscheidenden Kernvertrag auf neue native-first Zielregel umgestellt; Veraltete Scope-Aussage gegen freigegebene RT-ADR-002 korrigiert; SDK-Typabbildung als offene Lücke festgehalten |
| [docs/04_Begriffslexikon.md](../../docs/04_Begriffslexikon.md) | Begriffslexikon native Begriffe als führend definiert; SDK-nahe Terminologie ergänzt |
| [docs/05_Vom_Projekt_zum_Plugin.md](../../docs/05_Vom_Projekt_zum_Plugin.md) | Buildprozess nicht mehr als native Soll-Semantik missverstehen; Dokumenttitel als Bestandsprozess markiert |
| [docs/06_Kommunikation_und_Zustaende.md](../../docs/06_Kommunikation_und_Zustaende.md) | Host-/Runtime-States von nativen Multistate-States abgegrenzt |
| [docs/07_Studio_Bibliothek_und_Adapter.md](../../docs/07_Studio_Bibliothek_und_Adapter.md) | Studio-/Bibliothekskonzept als bestehender Vorschlag mit neuer Priorität eingeordnet; Direkt widersprechenden Satz in SDK-Kapitel ersetzt; Eigenen Binding-Graph nicht als universell führend dargestellt |
| [docs/08_Entscheidungsregister.md](../../docs/08_Entscheidungsregister.md) | Neue normative Priorität am Entscheidungsregister angegeben; AR-007 als durch spätere ADR überholte Zielregel markiert; Runtime-T6-Darstellung im Register präzisiert; Neue verbindliche ADR samt Geltungsgrenzen eingetragen; Statuswert SUPERSEDED auf bestehenden Registerstatus normalisiert |
| [docs/11_P0_Praezisierungen.md](../../docs/11_P0_Praezisierungen.md) | Historisches P0-Review vor Fehlinterpretation geschützt |
| [docs/12_P0_Freigabe_2026-10-30.md](../../docs/12_P0_Freigabe_2026-10-30.md) | Historische P0-Freigabe zeitlich gegen neue ADR eingeordnet |
| [docs/decisions/P0-ADR-002.md](../../docs/decisions/P0-ADR-002.md) | P0-ADR-002 als bestandsgültigen, nicht zwangsläufig zukunftsführenden Vertrag markiert |
| [docs/decisions/PRODUCT-ADR-001.md](../../docs/decisions/PRODUCT-ADR-001.md) | Produkt-ADR für SDK-native Zielrichtung eingeordnet |
| [docs/decisions/README.md](../../docs/decisions/README.md) | Neue ADR gegenüber älteren freigegebenen Entscheidungen eingeordnet; ARCH-ADR-001 in ADR-Index eingetragen |
| [docs/decisions/RT-ADR-002.md](../../docs/decisions/RT-ADR-002.md) | Python StateStore und native SDK-States klar abgegrenzt |
| [docs/decisions/RT-ADR-006.md](../../docs/decisions/RT-ADR-006.md) | Normativen Widerspruch RT-ADR-006 gegen spätere ADR direkt am Original geklärt |
| [docs/README.md](../../docs/README.md) | Geltungsvorrang SDK-nativ dokumentiert; Dokumentationsindex korrigiert; SDK-Mapping und Änderungsregister verlinkt |
| [docs/specifications/README.md](../../docs/specifications/README.md) | SDK-Mapping im Spezifikationsindex prominent verlinkt |
| [README.md](../../README.md) | Neue SDK-native Architekturleitlinie am Einstieg verankert; Bestehendes Projektmodell als IST/Kompatibilität statt Zielmodell erläutert |
| [schemas/README.md](../../schemas/README.md) | Schemas als IST und Migration als offen markiert |
| [src/adapters/logitech/README.md](../../src/adapters/logitech/README.md) | Generator-README zeigt SDK-Lücken, keine implizite Vollständigkeit |
| [src/core/README.md](../../src/core/README.md) | SDK-fachneutraler Core als IST, nicht Soll, dokumentiert |
| [src/library/README.md](../../src/library/README.md) | Autorenmodell als Legacy-Kompatibilität eingeordnet |
| [src/README.md](../../src/README.md) | Code-Index zwischen IST und neuer Zielarchitektur unterschieden |
| [src/runtime/README.md](../../src/runtime/README.md) | Runtime-Schicht zu nativem Multistate abgegrenzt |
| [STATUS.md](../../STATUS.md) | Statusdatei ergänzt um neuen, nicht implementierten Architekturstand; Aktuellen Architektur- und Umsetzungsstatus präzise ergänzt |
| [work/planning/gemeinsame-symbol-und-state-darstellung-v01.md](../../work/planning/gemeinsame-symbol-und-state-darstellung-v01.md) | Abgeleiteten Renderingwert statt neuen Pflicht-Fachkerns geklärt; Maskierte Markdown-Backticks aus früherem Entwurf repariert |
| [work/planning/keypad-preview-eingabeschema-v01.md](../../work/planning/keypad-preview-eingabeschema-v01.md) | Keypad DTO nativem SDK untergeordnet; ActionOffer berücksichtigt bislang fehlenden SDK-actionParameter; SlotData um möglichen nativen actionParameter ergänzt; EditRequest erhält nativen actionParameter statt Informationsverlust; Kein implizites selbstverwaltetes Multistate-Modell im Keypad; Versioniertes Drag-MIME-Beispiel um action_parameter ergänzt |
| [work/planning/keypad-preview-widget-technischer-entwurf-v01.md](../../work/planning/keypad-preview-widget-technischer-entwurf-v01.md) | Betriebsartenwiderspruch in altem Keypad-Entwurf deutlich geklärt; Veralteten Default-Bearbeitungsmodus klar gekennzeichnet; Testmodus als künftige übergeordnete App-Funktion statt Widget-Modus markiert; Frühere maskierte Markdown-Backticks für korrekte Vorschau bereinigt |
| [work/planning/Logitech_Plugin_Studio_Produktreife_Fahrplan_v01.md](../../work/planning/Logitech_Plugin_Studio_Produktreife_Fahrplan_v01.md) | Produktreife-Fahrplan auf führende SDK-Semantik ausgerichtet; Frühere maskierte Markdown-Backticks für korrekte Vorschau bereinigt |
| [work/planning/README.md](../../work/planning/README.md) | Planungsindex mit SDK-nativer Leitentscheidung aktualisiert; Falschen aktuellen nächsten AP-CORE-001-Auftrag korrigiert |
| [work/planning/roadmap.md](../../work/planning/roadmap.md) | Historische generische Roadmap als zeitlich überholt gekennzeichnet; Alte Einleitung nicht als heutige Entwicklungsstrategie stehen gelassen |
| [work/planning/studio-bedienkonzept-entwurf-v01.md](../../work/planning/studio-bedienkonzept-entwurf-v01.md) | UX-Entwurf nicht als modellführende Quelle gelassen; Frühere maskierte Markdown-Backticks für korrekte Vorschau bereinigt |
| [work/planning/widget-schnittstellen-grundentwurf-v01.md](../../work/planning/widget-schnittstellen-grundentwurf-v01.md) | Widget-Schnittstellen vor Implementierung unter SDK-nativen Vorbehalt gestellt |
| [work/product-readiness/INDEX.md](../../work/product-readiness/INDEX.md) | Produktreife-Register um ADR und offene Migration ergänzt |
| [work/README.md](../../work/README.md) | Historische Arbeitsakten von aktueller Architektur getrennt |

## 4. Technische Konsequenzen – für den nächsten Schritt

| ID(s) | Betroffene Bereiche | Was noch zu entscheiden/implementieren ist |
|---|---|---|
| NF-01, NF-14 | `core.model`, `schemas`, `component_types`, Bibliothek | Native SDK-Action-Klassen als maßgebliche Modellstruktur; kompatibles Migrationsformat statt generischer Pflicht-Components |
| NF-02 | `adapters/logitech/product.py`, C#-Templates, Bridge/Wire, Host, Tests | `actionParameter` über gesamte Aufruf- und Bild-/State-Kette erhalten; mögliche Revisions-/Auth-Konsequenzen prüfen |
| NF-03, NF-04, NF-08, NF-12 | `StateStore`, Handler, Generator, Studio-State-Editor | Native `PluginMultistateDynamicCommand`-States vs. Python-Value-State; feste Indizes/Anzahl, Scope, Owner, LED und Parametersemantik |
| NF-05, NF-07 | `Visuals.cs.in`, `src/studio/images.py` | Bereits funktionierenden normalen Dynamic-Command-Image-Refresh erhalten; Caption-/Render-Doppelungen reduzieren |
| NF-06, NF-13 | `src/symbol_designer/`, SDK-Generator, Asset-/Paketbauer | Native ICT-/SVG-/PNG-Precedence und Resources; keine verlustbehaftete PNG-Standardkonvertierung |
| NF-09 | KeypadPreviewWidget, Studio-Vorschau, `PluginDynamicFolder` | SDK-Navigation/Back/Pagination als Fähigkeiten abbilden, nicht UI-8+Back fest codieren |
| NF-10, NF-11 | Generator, Aktionstypen, Editoren | Native Adjustments und Action Editor / SDK-Parametererzeugung verifizieren |
| NF-15 | Python↔C#-Host-/Bridge-Implementierung | Sicherheits-/Transportfunktionen erhalten, keine fachlichen Doppel-State-/Action-Systeme |
| NF-16 | SymbolDesigner, Keypad Preview, andere Studio-Widgets | SDK-nahe DTO-/View-Daten; Widget nur für Darstellung/Bedienung, Komfort separat; laufende Agentenaufträge auf neue ADR hinweisen |
| NF-17 | Projekte, Migration, Validierung, CLI, Tests, Build, Hardware | Golden-/Roundtrip-/Integrations-/Hardwaretests und Rückwärtskompatibilität vor produktiver Umstellung |

**Priorisierung für die Folgenanalyse:** Erst **SDK-Reflection/API-Matrix** und **native Daten-/State-Mapping-Regeln**, danach Format-/Bridge-Entscheidung, dann Renderer/Generator, zuletzt Widget-Einbau. Umfang und Migrationsreihenfolge bleiben zur nächsten Entscheidung offen.

## 5. Bereits direkt behobene Dokumentationsmängel

1. AR-007 als in der **Zielrichtung superseded** markiert; Status im Register ist `SUPERSEDED`, keine neue spontane Statuskategorie.
2. Widersprüchlichen SDK-unabhängigen Sollsatz im Metamodell ersetzt.
3. Historisch überholte `session`-Scope-Aussage im Metamodell anhand RT-ADR-002 berichtigt.
4. `PluginMultistateDynamicCommand` vom Python-`StateStore` abgegrenzt.
5. Neun Tasten ≠ pauschal neun nutzbare oder pauschal nur acht Slots: SDK-Device-Navigation bleibt externe Capability.
6. Keypad: **Preview als nicht editierbarer Standard, Edit ausdrücklich zuschaltbar**; alten „Bearbeiten als Standard“-Entwurf sichtbar entkräftet.
7. `ActionOffer`, `SlotData`, `EditRequest` und Drag-MIME-Beispiel für `action_parameter` dokumentarisch ergänzt.
8. `ResolvedVisual` nur als abgeleiteter Qt-Vorschauwert, nicht als eigenständiges neues fachliches Pflichtformat eingeordnet.
9. Historische Roadmap und alten „AP-CORE-001 ist als nächstes auszuführen“-Hinweis korrigiert.
10. Neue ADR-/Gap-Querverweise in Einstiegsdateien, Architektur, Runtime, Generator, Bibliothek, Widgetplanungen, Status, Glossar und Changelog ergänzt.

## 6. Bewusst **nicht** umgeschrieben

- Historische Arbeitsakten unter `work/runs`, abgeschlossene `work/packages`, `work/autopilot`, abgenommene Berichte und Snapshots unter `references`.
- Bestands-Testprojekte, XML-Schemas, Quelldateien, Runtime-/Host-/SDK-Generierung.
- Laufende parallele Implementierungen im SymbolDesigner.
- Kein Start/Restart/Installation von Logitech-Diensten oder Änderungen an Benutzertasten.

Ein älterer Text in diesen historischen Sammlungen ist eine **damalige Aussage**, keine neuere Norm. Die aktuellen Einstiegspunkte `README.md`, `docs/README.md`, `docs/08_Entscheidungsregister.md`, `STATUS.md`, `work/planning/README.md` verweisen auf den aktuell gültigen Beschluss.

## 7. Nachweisgrenzen

- Geänderte Bestandsdateien besitzen im Manifest jeweils `sha256_before`, `sha256_after`, Begründungen und ein Original-Backup.
- Neue Architekturentscheidung und SDK-Abgleich sind **Dokumentation**, kein Beleg einer erfolgten SDK-API-/Hardware-Migration.
- Native Multistate-Methode und `actionParameter` müssen an der *installierten* Logitech-DLL vor neuen Generatorversprechen geprüft werden.
- Änderungen an `*.py`-/C#-Funktionen sind gesondert zu planen, weil die bereits belegte Hardware-/Hostfunktion erhalten bleiben muss.

**Nächster Schritt:** Dieses Änderungsregister und NF-01…17 nach betroffenen Modulen priorisieren, Umsetzungspakete und Migrationsgates festlegen.

## 8. Durchgeführte Prüfung am 03.11.2026

- **Markdown-Linkprüfung über das Projekt:** `python tools/check_links.py` → **416 geprüfte lokale Links, 0 fehlende Ziele**.
- **Regressionssuite:** `python -m unittest discover -s tests -q` → **345 Tests in 24,420 Sekunden, OK**. Die dabei erwarteten Negativtest-Diagnosemeldungen sind keine fehlgeschlagene Testzusammenfassung.
- **Archivprüfung:** 37 Originaldateien plus Manifest im ZIP, ZIP-CRC bestanden; SHA-256 jedes Originals und jeder aktuell bearbeiteten Datei stimmt mit dem Manifest überein.
- **Geänderter und neuer Dokumentationsstand:** 40 Markdown-Dateien auf vorhandene Verweise und Formatierung überprüft.
- **Code-/SDK-/Hardware-Migration:** nicht durchgeführt; diese Prüfungen bestätigen nur den bestehenden Teststand und die Konsolidierung.

