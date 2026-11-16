# 08 – Architekturentscheidungen, Entwurfsstatus und offene Fragen

> **Vorrangige Entscheidung 03.11.2026:** [ARCH-ADR-001 – SDK Native First](decisions/ARCH-ADR-001.md) ersetzt die frühere *SDK-agnostische Core-Semantik als führende Zielarchitektur* (insbesondere AR-007 / betreffender Teil RT-ADR-006). Die Tabellen mit älteren Baselines dokumentieren die damaligen Entscheidungen und ihren Bestandscode. [SDK-Abgleich](specifications/sdk-native-modellabgleich-v01.md).

**Dies ist die normative Statusquelle dieses Dokumentationspakets.** Andere Dateien erläutern Konzepte; hier wird festgehalten, ob sie bereits als Baseline vereinbart, nur vorgeschlagen oder noch offen sind.

## 1. Statuswerte

| Status | Bedeutung |
|---|---|
| `BASELINE` | ausdrücklich vereinbart; umfasst auch verabschiedete ADRs (kein Beleg einer Implementierung) |
| `ACCEPTED` | Verabschiedete Einzel-ADR mit Baseline-Wirkung |
| `ACCEPTED_WITH_SCOPE_LIMIT` | Einzel-ADR: nur die im Entscheidungstext abgegrenzten Grundsätze verbindlich |
| `PROPOSED` | konkreter Entwurf, zur gesonderten Abnahme vorgelegt |
| `OPEN` | noch nicht entschieden; keine stillschweigende Implementierungsannahme |
| `OBSERVED` | technische Tatsache aus dokumentierten bisherigen Tests, ggf. nur auf dem benannten Teststand |
| `SUPERSEDED` | frühere Idee, durch neue Entscheidung ersetzt; Historie erhalten |

## 2. Baseline – bereits vereinbarte Systemprinzipien

| ID | Entscheidung | Status | Konsequenz |
|---|---|---|---|
| AR-001 | Fachneutraler Kern; keine eingebauten Nutz-Zustände wie Recording/Listening | `BASELINE` | Anwendungssemantik ausschließlich in Projekt/Host |
| AR-002 | Hybrid aus Commands, Events und abfragbaren States | `BASELINE` | getrennte Signalsemantiken |
| AR-003 | Snapshot + inkrementelle Updates + Reconnect/Re-Sync | `BASELINE` | kein Vertrauen auf lückenlose Eventfolgen |
| AR-004 | Health/Lifecycle unabhängig von Benutzerzuständen | `BASELINE` | KeepAlive nicht als obligatorischer Action-Callback |
| AR-005 | Definition, Konfiguration, Platzierung und Runtime-Ist-Zustand getrennt | `BASELINE` | mehrfach nutzbare Actions und Replikation |
| AR-006 | Komponierbare Bausteine mit typisierten Ports/Bindings | `BASELINE` | Bindings vor Ausführung validieren |
| AR-007 | SDK- und hostunabhängiger Kern als fachlich führendes Produktmodell (historischer Beschluss) | `SUPERSEDED` durch [ARCH-ADR-001](decisions/ARCH-ADR-001.md) | bestehender `0.1-draft`-Code bleibt vorerst kompatibel; native Logitech-Semantik ist künftig maßgeblich |
| AR-008 | Deklaratives, versionierbares Plugin-Projekt | `BASELINE` | Studio ist Editor, nicht Runtime-Owner |
| AR-009 | Beliebige Aktionsanzahl **logisch**, physische Anzeige nach Adapter-Capabilities | `BASELINE` | keine strukturelle 4/8-Grenze |
| AR-010 | Runtime übernimmt Health und Synchronisation; State Machine nur optional | `BASELINE` | einfache Komponenten bleiben einfach |
| AR-011 | SDK Lab, Bibliothek und Studio bleiben getrennte Verantwortungsbereiche | `BASELINE` | Demo-Code nicht als generische Bibliotheksfunktion ausgeben |
| AR-012 | Kein pauschales Exactly Once, keine implizite Command→Success-Gleichsetzung | `BASELINE` | Result/Retry müssen explizit sein |

## 3. v0.2-Metamodell – unabhängige Entwürfe und bereits durch P0-ADRs abgedeckte Teilregeln

**Abgrenzung:** Die Freigabe der sieben ADRs genehmigt **nicht automatisch** `MM-001..MM-010` als Gesamtmodell. Wo eine Zeile denselben Grundsatz betrifft, gilt dafür verbindlich die **präzisere verlinkte P0-ADR**; verbleibende Detailfragen sind weiterhin offen. Die `PROPOSED`-Markierung bedeutet in solchen Zeilen: *Gesamtvorschlag noch nicht separat verabschiedet*, nicht: die entsprechende Einzel-ADR sei weiterhin offen.

| ID | Vorschlag | Status | Review-Frage |
|---|---|---|---|
| MM-001 | Entitäten `Project`, `ComponentType`, `ComponentInstance`, `PortDefinition`, `Endpoint`, `StateDefinition`, `Binding`, `View`, `Placement`, `Presentation`, `Asset`, `RuntimeInstance`, `Capability` | `PROPOSED` | fehlen/überlappen Entitäten? |
| MM-002 | `command`, `event`, `state` als Port-Signalkategorien | `BASELINE` für Kategorien durch P0-ADR-003 | Ergebnis-/Fehlerrückkanal im Detail noch offen |
| MM-003 | Nur `out→in`, keine stillschweigende Signalkonversion | `BASELINE` durch P0-ADR-004 | ausdrückliche Konverter und Ausführung noch offen |
| MM-004 | Ein autoritativer Writer je konkret instanziiertem State-Scope | `BASELINE` nur als Grundsatz durch P0-ADR-005 | Scope-Instanziierung / Authority-Rollen / Delegation `OPEN` |
| MM-005 | State-Qualität `unknown/fresh/stale` vom Nutzwert getrennt | `PROPOSED` | zusätzliche Qualitätsstufen nötig? |
| MM-006 | View enthält 0..N Placements; Action-Reuse erlaubt | `BASELINE` durch P0-ADR-006 | weitere View-/Layout-Scope-Regeln offen |
| MM-007 | Presentations als wiederverwendbare, variantengesteuerte Objekte | `PROPOSED` | Vererbungs-/Override-Regeln? |
| MM-008 | Laufzeitänderungen als separate Overrides, keine automatische Projektmutation | `BASELINE` durch P0-ADR-006 | atomare Operationen, Persistenz-/Rollback-Policy offen |
| MM-009 | ComponentType-Manifest mit Config, Ports, Capabilities, Editor-Metadaten, Nachweisen | `PROPOSED` | Manifest-Schema und Versionierungsregeln? |
| MM-010 | Deklarative Mapping-Basics (`identity`, `constant`, `field_select`, `lookup`) ohne beliebiges `eval` | `PROPOSED` | welche minimale Ausdrucksmenge? |

## 4. Noch offene technische Festlegungen

| ID | Frage | Status | Benötigte Entscheidung / erstes Testmittel |
|---|---|---|---|
| OP-001 | ID-/Namespace-/Referenz-/Rename-Details | `OPEN` (teilweise durch ADR-001 entschieden) | JSON-Objekt als Referenz verbindlich; konkrete Rename-Transaktion/Fehlerpolitik verbleibt |
| OP-002 | JSON-Schema-Dialekt und vollständige Typbibliothek | `OPEN` (teilweise durch ADR-004 entschieden) | Draft 2020-12 als Dialekt fest; finale Projektschema-Version, Kompatibilitätssemantik offen |
| OP-003 | State-Scopes und ihre Zuordnung zu Runtime-IDs | `OPEN` | Test mehrerer Instanzen und Sessions |
| OP-004 | Binding-Conditions, Mapping, Abarbeitungsreihenfolge und Fehlerpolitik | `OPEN` | typisierte Graphen und Zyklentests |
| OP-005 | Revisionen und atomare dynamische View-Updates | `OPEN` | parallele Änderungen und Reconnect |
| OP-006 | Grenzen von static config / deploy config / Runtime Override | `OPEN` | Definition einer klaren Deployment-Policy |
| OP-007 | Exakte Python-API und Qt-Kompatibilität | `OPEN` | Runtime-Contract-Test ohne SDK |
| OP-008 | Transport, Port-/Prozess-Discovery, lokale Authentisierung | `OPEN` | Security-Konzept und Multiprozesstests |
| OP-009 | Welche SDK-Möglichkeiten benötigen Build/Reload; welche sind live? | `OPEN` | separate Lab-/Gerätetests |
| OP-010 | Dynamischer Katalog von SDK-Actions jenseits der einmal registrierten Typen | `OPEN` | SDK-Schnittstellenanalyse / PoC |
| OP-011 | Komponentenversionierung und Projektmigrationen | `OPEN` | Lock-/Compatibility-Tests |
| OP-012 | Speicherung über Python-Neustart hinweg | `OPEN` | Persistenz-Szenarien mit eindeutigem Owner |

## 5. Technische Beobachtungen, keine Modell-Freigaben

| ID | Beobachtung | Status | Geltung |
|---|---|---|---|
| EV-001 | C#-Plugin lädt auf Windows nach Build mit `net10.0` / PluginApi 6.4.2.3414 | `OBSERVED` | konkreter Nutzer-PC und damaliger SDK-Stand |
| EV-002 | Keypad-Commands erreichen C#; `POST /event` erreicht Python; `GET /state` funktioniert | `OBSERVED` | SDK Lab v0.1.3/v0.1.4 |
| EV-003 | Dynamic Folder öffnet und schließt auf dem MX Creative Keypad | `OBSERVED` | SDK Lab Hardwaretest |
| EV-004 | Vier-↔-acht-Mitglieder, Kontext/Farben und Zähleränderungen auf Gerät sichtbar | `OBSERVED` | SDK Lab v0.1.4 Nutzertest |
| EV-005 | Counter überlebt Neustart **nur des Logitech Plugin Service**, während Python läuft | `OBSERVED` | keine garantierte Datenträgerpersistenz |
| EV-006 | Erstes Plugin Studio erstellt/buildet Plugins, die in Options+ verfügbar sind | `OBSERVED` | Benutzerbericht; Funktionsumfang des generierten Plugins nur begrenzt nachgewiesen |

## 6. Änderungen der bisherigen Richtung

| ID | Vorher | Nachher | Status |
|---|---|---|---|
| CH-001 | Studio v0.2 mit Demo-Checkboxen als künftiges Produktmodell | wird als technischer Prototyp archiviert; generisches Core Model statt dessen | `SUPERSEDED` |
| CH-002 | Lab-Quell-Snapshots direkt als produktive Auswahlmodule | künftig generalisierte ComponentTypes mit eigenem Vertrag, Version und Hardwareabnahme | `SUPERSEDED` |

## 7. Regel für spätere Änderungen

Neue Festlegungen als ADR (`../work/templates/ADR_VORLAGE.md`) mit eigener ID, Status, Anlass, Alternativen, Entscheidung, Auswirkungen, Tests und betroffenen Dokumenten erfassen. Erst nach ausdrücklicher Abnahme den Status auf `BASELINE` setzen; bestehende Einträge nicht einfach überschreiben. Folgeentscheidungen können ältere als `SUPERSEDED` markieren und darauf verlinken.


## 8. Freigegebene P0-ADRs – Beschluss vom 30.10.2026

Der Nutzer hat sechs ADRs ohne Änderung und ADR 005 **mit ausdrücklich begrenzter Reichweite** freigegeben; die sechs sind 001, 002, 003, 004, 006 und 007. Der Wortlaut der jeweiligen Einzel-ADR ist maßgeblich. Die frühere Warnung „noch nicht abgenommen“ aus v0.5 ist durch diese Freigabe ersetzt.

| Entscheidung | Thema | Status | Volltext |
|---|---|---|---|
| P0-ADR-001 | IDs und strukturierte Referenzen | `ACCEPTED` | [ADR](decisions/P0-ADR-001.md) |
| P0-ADR-002 | Persistierte Entitäten und Laufzeitobjekte | `ACCEPTED` | [ADR](decisions/P0-ADR-002.md) |
| P0-ADR-003 | Signalkategorien und Result | `ACCEPTED` | [ADR](decisions/P0-ADR-003.md) |
| P0-ADR-004 | Datentypen und Binding-Validierung | `ACCEPTED` | [ADR](decisions/P0-ADR-004.md) |
| P0-ADR-005 | Eindeutige Writer-Hoheit; **Runtime-Scope-Regeln offen** | `ACCEPTED_WITH_SCOPE_LIMIT` | [ADR](decisions/P0-ADR-005.md) |
| P0-ADR-006 | Views und Runtime-Overrides | `ACCEPTED` | [ADR](decisions/P0-ADR-006.md) |
| P0-ADR-007 | Zweistufige Validierung | `ACCEPTED` | [ADR](decisions/P0-ADR-007.md) |

**Reichweite:** Dieses P0-Paket verabschiedet kein finales `project.json`-Schema und keine Runtime-/Transport-API. Weitere MM-Vorschläge bleiben im nicht abgedeckten Umfang `PROPOSED`; OP-Fragen bleiben offen, soweit ihre Teilaspekte nicht durch die P0-ADRs ausdrücklich festgelegt wurden. [Datiertes Beschlussprotokoll](12_P0_Freigabe_2026-10-30.md).


## 9. Runtime-Grundsatzbeschlüsse T1–T6 (30.10.2026)

Der Nutzer hat nach gemeinsamer fachneutraler Erklärung der sechs Themen **T1–T6 angenommen**. Die maßgeblichen, präzisierten Volltexte liegen in [RT-ADR-001–006](decisions/README.md). Der ältere Agentenentwurf `RUN-AP-CORE-002-01/06_runtime_vertragsentwurf.md` bleibt historische Entscheidungsgrundlage und wird nicht umetikettiert.

| Thema | Verbindlicher Grundsatz | Noch offen |
|---|---|---|
| T1 | Projekt ≠ Runtime ≠ Session; ein generiertes Plugin mit beliebigen SDK-Aktionen und einer primären Host-Anwendung in V1 | IDs/Formate, Deployment, Produkt-Mehrinstanzbetrieb |
| T2 | runtime-/component-/placementbezogene States und `host/component/runtime`-Autorität, genau ein Writer | konkrete Adressierung, Transportautorisierung, Persistenz |
| T3 | Snapshot + Deltas + Re-Sync; Authority-Epoch/Revision; `unknown/fresh/stale` | Wire-Format, Snapshot-/Queue-Algorithmus |
| T4 | Command/Event/State getrennt, explizite Results, keine automatischen unsafe Retries | Ordering, Queue, Timeout, Dedup |
| T5 | technische Verbindung/Health/Readiness getrennt vom Nutzwert | konkrete Timer, Security, Reconnect-Policy |
| T6 | Historischer RT-ADR-006-Stand: fachneutraler Core, SDK-Capabilities über Adapter; **für neue SDK-Modellierung vorrangig ARCH-ADR-001** | SDK-Capability-Katalog, Legacy-Kompatibilität, native SDK-/Python-Abbildung |

**Nicht als beschlossen ausgeben:** das vollständige JSON-Projektschema, exakte Python-Runtime-API, Transport, StateStore-Implementierung und Spike-Dispatch-Details. `MM`-Grundvorschläge bleiben außerhalb der ADR-Reichweite `PROPOSED`.

## 10. Neue Produktentscheidung FINAL-PRODUCT-01

[PRODUCT-ADR-001](decisions/PRODUCT-ADR-001.md) ist **PROPOSED**:
revidierbares lokales HTTP-/Authentisierungs-/Snapshot-/Command-Protokoll
mit expliziten Ressourcenlimits. Implementiert und intern geprüft, aber
nicht unabhängig als Architektur oder Produkt abgenommen. OP-007/008 sind
damit technisch bearbeitet, nicht pauschal verbindlich geschlossen.
Alle bestehenden ACCEPTED-Einzel-ADRs bleiben unverändert.

## 11. SDK-native Folgeentscheidung – 03.11.2026

| ID | Entscheidung | Status | Konsequenz |
|---|---|---|---|
| [ARCH-ADR-001](decisions/ARCH-ADR-001.md) | **Native First – Minimal Bridge – Optional Extensions** | `ACCEPTED / ARCHITEKTURRICHTUNG` | Native Logitech-Semantik ist führend; eigene Abstraktion nur technisch bedingt; Mehrwert separat und optional. |

**Vorrang:** ARCH-ADR-001 ersetzt die bisherige SDK-unabhängige Core-Philosophie **als Zukunftsmodell**, besonders AR-007 und den betreffenden Teil von RT-ADR-006. Sie ersetzt **nicht automatisch** die bestehenden Project-/StateStore-/Binding-Schemas, P0/RT-Sicherheitsverträge oder bereits unabhängigen Abnahmen. Die Migrationsarbeit ist `OPEN` und wird im [SDK-nativen Modellabgleich](specifications/sdk-native-modellabgleich-v01.md) geführt. Historische Beschlüsse bleiben als solche nachvollziehbar.


## 11. Profil-, Aktions- und Layoutbegriffe – Basis vom 04.11.2026

**Referenz:** [Logitech-Profil- und Aktionsmodell v0.1](specifications/logitech-profil-und-aktionsmodell-basis-v01.md). Die folgenden **Begriffs- und Zuständigkeitsregeln** sind `BASELINE`; undokumentierte Detailfelder von `ProfileInfo.json` bleiben `OPEN`/Beobachtungsstand.

| ID | Grundsatz / Frage | Status | Konsequenz |
|---|---|---|---|
| PA-001 | Aktion = SDK-natives Funktionselement; weder einzelner Tastendruck noch isoliertes Anzeige-/State-Update | `BASELINE` | ActionInspector betrifft SDK-Aktionsdefinitionen |
| PA-002 | Aktionskatalog = kontextabhängige Sammlung/Ansicht; kein neuer eigenständiger „Aktionsangebot“-Entitätstyp | `BASELINE` | Gleiche Aktion kann je nach Plugin-/App-/Geräteprofil verfügbar oder ausgeblendet sein |
| PA-003 | General-/Fallback- und anwendungsbezogene Profile gehören zur Logitech-verwalteten Profilwelt | `BASELINE` | Nicht mit plugin-gesteuertem Dynamic Folder gleichsetzen |
| PA-004 | Workspace, Layout-Mode, Page, Control und Aktionszuordnung sind getrennt zu untersuchende Begriffe; Dynamic Folder ≠ Workspace ≠ Profil | `BASELINE` | Keine voreilige Vereinheitlichung im Studio |
| PA-005 | SDK-Aktionsdefinition ≠ Profile-Action-Instanz mit konkreten Profilparametern ≠ Platzierung/Control-Referenz | `BASELINE` | Autorität und Identität differenzieren |
| PA-006 | Struktur/Schreibbarkeit von `ProfileInfo.json` und echten `.lp5`-Paketen | `OPEN` | Nur lesende Forschung; keine Live-Profil-Editor-Freigabe |
| PA-007 | Beziehung `dynamicPage*` zu `PluginDynamicFolder`, konkrete Action-Referenztypen und versions-/gerätespezifische Unterschiede | `OPEN` | [AP-RESEARCH-001](../work/planning/AP-RESEARCH-001-logitech-profilmodell.md) vor endgültigem Profile-/Inspector-Persistenzvertrag |


## 12. Profil- und Aktionsmodell nach AP-PROF-001 (05.11.2026)

**Freigabe:** Die Forschung `AP-PROF-001` wurde unabhängig nachgeprüft und vom Benutzer zur Übernahme freigegeben. Verbindliche Planungsgrundlage ist jetzt [v0.2](specifications/logitech-profil-und-aktionsmodell-basis-v02.md); die bisherige [v0.1](specifications/logitech-profil-und-aktionsmodell-basis-v01.md) ist historisch.

| ID | Stand nach dem Forschungsabschluss | Status / Folge |
|---|---|---|
| PA-001/PA-002 | SDK-Aktionsdefinition und kontextabhängiger Aktionskatalog bleiben eigenständig; Katalog ist **eine Ansicht**, kein neuer persistenter Entitätstyp. | `BASELINE` bestätigt |
| PA-003 | General-/Fallback- und anwendungsbezogene Profile sind Logitech-verwaltete Belegungskontexte; interne DynamicFolder-Inhalte besitzt das Plugin. | `BASELINE` bestätigt |
| PA-004/PA-005 | SDK-Action-Definition, `profileActions`-Instanz, Control-Referenz/Placement, Workspace, `folderPages` und `PluginDynamicFolder` sind zu unterscheiden. | `BASELINE` durch AP-PROF-001 gestützt |
| PA-006 | Drei empirische Profil-Layoutfamilien und 21 echte `.lp5`-Default-Pakete untersucht. **Schreibzugriff/Export-/Importverhalten bleiben ausdrücklich offen.** | `PARTIALLY_OBSERVED / WRITE_OPEN` |
| PA-007 | 675 Control-Refs und 175 lokale Referenzauflösungen beobachtet. Semantik von `dynamicPage*` (170 Felder führende Pages, alles Default) und `activationActions` (42 leere Workspace-Arrays) **bleibt offen**. | `PARTIALLY_CONFIRMED / SEMANTICS_OPEN` |

**Quelle und Geltung:** `P:\LokaleProjekte\logi_actions_sdk\logi-actions-sdk-rec\work\archive\RUN-20261104-PROF001-01`; unabhängige Reviewakte `reviews/evidence/AP-PROF-001-nachabnahme-20261105.md`, importierter Fachkatalog `CON-0001`–`CON-0008` und `FMT-0001`–`FMT-0004`. Keine Änderung an ARCH-ADR-001 oder an bereits implementierten Studio-Widgets, keine direkte Logitech-Live-Profiländerung und keine `.lp5`-Writer-Freigabe.

**Planungsfreigabe:** SDK-nativer ActionInspector darf mit seiner ursprünglichen Zuständigkeit weitergeplant werden. Ein separater **read-only** ProfileExplorer ist optional. Ein schreibender ProfileEditor bedarf einer neuen, belegten Entscheidung.
