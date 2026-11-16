# Logitech Plugin Studio – Profil-, Aktions- und Layoutmodell
## Historische Begriffs- und Planungsbasis v0.1 mit Forschungsauftrag

> **Seit 05.11.2026 durch die [abgenommene Modellgrundlage v0.2](logitech-profil-und-aktionsmodell-basis-v02.md) für neue Planungen ersetzt.** Diese historische v0.1 bleibt als ursprüngliche Vor-Forschungs-Entscheidung und Referenz der Agentenakten unverändert nachvollziehbar. Die AP-PROF-001-Forschung ist vollständig abgenommen, archiviert und selektiv in der SDK-Wissensbasis übernommen.

**Stand:** 04.11.2026  
**Status:** **VERBINDLICH für die hier explizit entschiedenen Architekturgrundsätze und Begriffsabgrenzungen**; lokale Logitech-Formatdetails bleiben **vorläufige Forschungsbefunde** bis zur evidenzbasierten Verifikation.  
**Projekt:** `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture`  
**Übergeordnete Entscheidung:** [ARCH-ADR-001 – Native First / Minimal Bridge / Optional Extensions](../decisions/ARCH-ADR-001.md).  
**Priorität:** Bei widersprüchlichen Annahmen in älteren Widget- oder Planungsunterlagen gelten die hier festgelegten *Begriffe und Verantwortungsgrenzen* als neuere Planungsbasis. Bestehende SDK-/Laufzeit-/Formatverträge werden dadurch **nicht** rückwirkend geändert.

---

## 1. Anlass und Ziel

Die bisher entwickelten Widgets (SymbolDesigner, KeypadPreview und ActionCatalog) sind eigenständig und softwareseitig geprüft. Vor der endgültigen Definition von `ActionInspectorWidget`, `FolderEditorWidget`, möglichem `ProfileEditorWidget` und deren gemeinsamer Persistenz benötigen wir jedoch ein präziseres Bild der Logitech-eigenen Entitäten.

Das Produkt soll **nicht** aus einem selbst erfundenen generischen Action-/Profile-/State-Modell bestehen, das erst nachträglich in die Logitech-Welt übersetzt wird. Es soll die tatsächlich vorhandene Logitech-SDK- und Profilsemantik so weit wie möglich direkt verwenden.

**Entscheidung:** Bevor wir weitere fachlich führende Persistenzschemata oder größere Editoren festlegen, beauftragen wir eine getrennte, **ausschließlich lesende, evidenzorientierte Untersuchung** der tatsächlichen Logitech-Profile, Aktionsreferenzen, Workspaces, Seiten, Pakete und ihrer Beziehung zum SDK.

**Abgrenzung:** Dieses Dokument ist keine Behauptung, das undokumentierte interne Profilformat sei ein offizieller, stabiler SDK-Schreibvertrag. Es verbindet eine heute verbindliche konzeptionelle Linie mit einem präzisen Forschungsauftrag zur Prüfung offener Details.

## 2. Status- und Evidenzsprache

Jede technische Aussage in den späteren Forschungsresultaten erhält eine Kennzeichnung:

| Kennzeichen | Bedeutung |
|---|---|
| **ENTSCHEIDUNG** | Für unser Studio verbindlicher, bewusst gewählter Architekturgrundsatz |
| **SDK-BELEGT** | Durch öffentliche Logitech-SDK-Dokumentation oder die installierte SDK-DLL/XML nachvollziehbar |
| **LOKAL-BEOBACHTET** | An realen Dateien auf dem Benutzer-PC gelesen, mit belegter Quelle/JSON-Pfad |
| **DRITTQUELLE** | In einem externen Repository beschrieben, noch nicht zwingend lokal verifiziert |
| **HYPOTHESE** | Plausibel, aber nicht ausreichend belegt |
| **OFFEN** | Bewusst noch nicht entschieden/ausreichend ermittelt |

Nur **ENTSCHEIDUNG** und verifizierte **SDK-BELEGT**-Sachverhalte werden ungeprüft zu verbindlichen Verträgen. Ein internes `$type` aus JSON ist zunächst ein beobachteter Serialisierungs-Hinweis, **kein automatisch öffentlicher SDK-Klassenvertrag**.

## 3. Verbindliches Begriffsmodell

### 3.1 Aktion / SDK-Aktionsdefinition

Eine **Aktion** ist ein über das Logitech SDK bereitgestelltes oder referenziertes **Funktionselement**. Sie ist **nicht** identisch mit einem einzelnen Tastendruck, einer Taste oder einer Anzeigeänderung.

Wichtige native Beispiele: `PluginDynamicCommand`, `PluginMultistateDynamicCommand`, `PluginDynamicAdjustment`, `ActionEditorCommand` sowie SDK-belegte weitere Aktionsklassen.

- Eine Aktion kann für Benutzer in einem Katalog auswählbar sein, muss dies aber nicht in jedem Kontext.
- Eine Aktion kann mehrfach verwendet werden und parameterabhängige Varianten haben.
- Eine Aktion kann auf Benutzerbedienung reagieren; ihr Zustand/Bild kann auch aufgrund eines externen Ereignisses aktualisiert werden. Das Update allein erzeugt **keine neue Aktion**.
- Ein einzelner interner Python-Aufruf, `ActionImageChanged()`, ein SDK-State-Update oder `ButtonActionNamesChanged()` ist **nicht** automatisch eine zusätzliche Aktion.
- Nicht jeder interne Dynamic-Folder-Befehl muss im allgemeinen Logitech-Aktionskatalog erscheinen, kann aber trotzdem ein echter SDK-Command sein.

### 3.2 Aktionskatalog

**Aktionskatalog** bezeichnet eine **kontextabhängige Sammlung bzw. Ansicht verfügbarer Aktionen**. Wir führen **keinen** eigenen fachlichen Begriff oder persistenten Entitätstyp „Aktionsangebot“ ein.

Der Katalog kann nach Plugin, Anwendungsbezug, Gerät, Profil, nativen Capability-Bedingungen und weiteren belegten Regeln gefiltert sein. Was genau Logitech in welchem Profil anbietet, wird untersucht; es darf nicht pauschal aus einem selbst gebauten Filter abgeleitet werden.

`ActionCatalogWidget` ist eine UI zur Anzeige/Selektion/Drag-Quelle; die eigentliche Action-Definition bleibt im nativen SDK-/Projektvertrag.

### 3.3 Profil – Logitech-verwaltete Belegung

Ein **Profil** ist eine von Logitech bzw. Logi Options+ verwaltete Konfiguration für ein Gerät und einen Kontext, insbesondere mit Seiten, Bedienelementen und Zuordnungen zu Aktionen.

Zwei wichtige Anwendungsfälle:

1. **Allgemeines / Fallback-Profil (General):** Übliche benutzerkonfigurierte Belegung, wenn kein spezifischeres Anwendungsprofil greift. Es ist nicht automatisch ein technisches „Hauptmenü“ des gesamten SDK.
2. **Anwendungsbezogenes Profil:** Ebenfalls eine grundsätzlich benutzerkonfigurierbare Belegung für eine Anwendung; Logitech kann bei aktivierter Anpassung an die Anwendung (Adapt to App) darauf umschalten.

**ENTSCHEIDUNG:** Allgemeines Profil und Anwendungsprofil werden **nicht** als zwei inkompatible Profilmodelle entworfen. Sie sind Varianten/Kontexte der Logitech-seitig verwalteten Profile; konkrete Unterschiede werden anhand der echten Felder belegt.

Die Zuordnung eines Profils zu einer Anwendung ist von einer plugin-gesteuerten Dynamic-Folder-Belegung zu trennen.

### 3.4 Workspace, Layout-Mode, Page und Control

Ein **Workspace** ist im untersuchten Profilformat ein benannter Bereich, der auf Seiten verweist. Ein Workspace ist **nicht per se ein Dynamic Folder** und **nicht per se eine eigene Aktion**. Seine genaue Navigations-/Aktivierungssemantik wird weiter untersucht.

Ein `layoutMode` organisiert offenbar weitere Layoutbestandteile und Workspaces; bis zur Verifikation nicht als frei austauschbarer Begriff für Profil, Workspace oder Folder verwenden.

Eine **Page** ist eine Seite eines bestimmten Bedienelementtyps (z. B. `touchPages`, `encoderPages`, `wheelPages`); **Control** ist ein Bedienelement bzw. dessen Zuordnung und möglicher Ereigniskanal, nicht die Action selbst.

**ENTSCHEIDUNG:** Die Beziehungen zwischen Profil → Layout-Mode → Workspace → Page → Control → Aktionsreferenz sollen zunächst **beobachtet**, nicht durch ein eigenes vereinfachtes Pflichtschema ersetzt werden.

### 3.5 Dynamic Folder – plugin-gesteuerte Inhalte

Ein `PluginDynamicFolder` ist ein vom Plugin angebotener SDK-Funktionstyp, der in einem Logitech-verwalteten Profil erreichbar/zuweisbar sein kann. **Nach Öffnen verwaltet das Plugin die Inhalte des Dynamic Folders** – nicht der Benutzer über das gewöhnliche Logitech-Seitenbelegungs-UI.

- Die Außenplatzierung im Profil und die interne Plugin-Verwaltung haben unterschiedliche Eigentümer.
- Ein Dynamic Folder ist **kein dritter Profiltyp** und **nicht dasselbe wie ein Workspace**.
- Interne Befehle können native SDK-Aktionen sein, auch wenn sie nicht im allgemeinen Katalog auswählbar sind.
- Ob/wo Dynamic-Folder-Zustand, Seitenreferenzen und Navigation auf Datenträger persistiert werden oder nur zur Laufzeit geliefert werden, ist **OFFEN**.

### 3.6 Aktionsdefinition vs. Zuordnung/Belegung

Eine **Aktionsdefinition** beschreibt die Funktion; die **Zuordnung/Belegung** verbindet diese Funktion mit einer konkreten Taste/Seite/Control unter einem Eigentümer.

In bestehenden Studiomodulen bestehen dafür z. B. `action_id`, `action_parameter`, `placement_id`, `physical_index` – aber **das sind zunächst Studio-/SDK-Bridge-Begriffe**. Ob das interne Logitech-Profilmodell dieselben Identitäten und Feldnamen verwendet, muss geprüft werden.

Eine parametrisierte Aktion kann eine konkrete **Profilinstanz** mit gespeicherten Parametern erzeugen. Die offizielle SDK-Dokumentation nennt dies **Profile Actions**; wir dürfen diese Instanzen nicht still mit einer neuen globalen SDK-Aktionsdefinition gleichsetzen.

## 4. Beziehungen und Zuständigkeiten – Architekturdiagramm

```text
        Logitech SDK / Plugins
       ┌────────────────────────────┐
       │ SDK-Aktionsdefinitionen    │
       │ + native Parameter/States  │
       │ + ggf. PluginDynamicFolder │
       └───────────────┬────────────┘
                       │  verfügbar je nach Kontext
                       ▼
             ┌───────────────────┐
             │  Aktionskatalog   │  ← gefilterte Ansicht, kein eigener
             │  (kontextabhängig)│    persistenter Entitätstyp
             └─────────┬─────────┘
                       │ Benutzer ordnet zu
                       ▼
   ┌────────────────── Logitech-verwaltete Profile ──────────────────┐
   │                                                                  │
   │  Allgemeines/Fallback-Profil     Anwendungsprofil               │
   │  (General)                       (z.B. VSCode/Chrome)          │
   │         └──────────────┬───────────────────────┘                 │
   │                        │                                         │
   │            Layout-Mode / Workspaces                              │
   │                        │                                         │
   │           Touch-/Encoder-/Wheel-Seiten                           │
   │                        │                                         │
   │            Controls → Aktionsreferenzen                         │
   │                        │                                         │
   └────────────────────────┼─────────────────────────────────────────┘
                            │ Eine solche Zuordnung kann
                            │ einen Dynamic Folder öffnen
                            ▼
                ┌─────────────────────────┐
                │ PluginDynamicFolder     │
                │ plugin-eigene Inhalte   │
                │ SDK-Befehle, Navigation │
                │ dynamische Updates      │
                └─────────────────────────┘

   Externe Events / Python / SDK-State / Anzeige-Refresh
      → verändern ggf. Zustand/Bild/Folder-Inhalt
      → sind nicht automatisch neue SDK-Aktionen oder Profile.
```

Die Illustration zeigt eine **konzeptionelle Verantwortungsgrenze**, keine bereits bewiesene 1:1-Klassendarstellung des Logitech-Serialisierungsformats.

## 5. Bereits vorhandene Projekte und Widgets

| Komponente | Heutige Rolle | Konsequenz |
|---|---|---|
| `SymbolDesignerWidget` | Native `.ict`-Bearbeitung | Weiterverwenden, keine neue Bildsemantik |
| `KeypadPreviewWidget` v0.2 | Gerätedarstellung, lokale UI-Bearbeitungsintents | Snapshot-View, nicht der Owner eines Logitech-Profils |
| `ActionCatalogWidget` v1 | SDK-native Projektaktionen anzeigen, suchen, ziehen | Künftig kontextabhängige Quellen/Filter; kein zweites Action-Modell |
| `ActionInspectorWidget` (geplant) | Native SDK-Aktionsdefinitionen erstellen/bearbeiten | **Fachmodell bis zur Profilrecherche nicht endgültig einfrieren** |
| `FolderEditorWidget` (geplant) | Plugin-gesteuerte Folder-/Placement-Inhalte | Nicht mit einem ProfileEditor verwechseln |
| `ProfileExplorer/ProfileEditor` (mögliche spätere Widgets) | Lokal gespeicherte Logitech-Profile lesen und ggf. unterstützt importieren/exportieren | Schreibunterstützung erst nach Sicherheit/Formatnachweisen |
| `src/adapters/logitech/native.py` | Bestehender schmaler SDK-Projektvertrag | Als Ausgangspunkt bewahren, nicht zu `ProfileInfo.json` umdefinieren |
| `src/runtime/` | Minimal-Bridge für C#↔Python | Keine Profile als zweites Runtime-Modell erfinden |

**Bestandsstand:** [SDK-Migrationsbericht](../../work/migrations/native-first-20261103/04_migrationsbericht.md) sowie [unabhängige Keypad-/Katalogabnahme](../../work/acceptance/20261104-keypad-catalog/ABNAHME.md). Die beiden abgenommenen Widgets sollten nicht wegen noch ungeklärter Profile-Interna umgebaut werden.

## 6. Drei verschiedene Datei-/Artefaktfamilien

| Artefakt | Primärer Zweck | Status / wichtige Grenze |
|---|---|---|
| `Applications\<DeviceType>\<Application>\Profiles\<GUID>` | **Laufende lokale Profilablage** mit z. B. `ProfileInfo.json` | Lokal als Verzeichnisstruktur beobachtet; internes Format, **nicht als öffentliche Live-Schreib-API freigegeben** |
| `Applications.Backups\backup_*.zip` | Automatische **Sicherungen des Profilbaums** | Existenz lokal bestätigt; nicht mit Profil-Export gleichsetzen |
| `.lp4` / `.lp5` | Verteil-/Import-/Exportpakete für **Profile** | Hersteller dokumentiert Profile und `.lp5`; genaue Byte-/Archivstruktur an einem **echt exportierten** Exemplar verifizieren |
| `.lplug4` / `.lplug5` | Verteilpakete für **Plugins** | Nicht mit `.lp5` mischen |
| `PluginApi.dll` / SDK XML | Öffentliche, installierte Plugin-Laufzeit-/Action-API | Normative Basis für das, was wir mit unseren Plugins offiziell tun dürfen |

**Wichtig:** Aus der Tatsache, dass man eine `.lp5`-Datei als Archiv öffnen kann, folgt **nicht**, dass „Profilordner zippen und in `.lp5` umbenennen“ ein korrektes Paket erzeugt. Das externe Repository hat eine solche naive Paketbildung erprobt, aber gerade **keinen** erfolgreichen Import daraus nachweisen können.

## 7. Kurze Vorab-Lageeinschätzung (keine Forschungsanalyse)

### 7.1 Lokale Verzeichnisse – nur Ebene 1 angesehen

`C:\Users\marco\AppData\Local\Logi\LogiPluginService` enthält:
`Applications`, `Applications.Backups`, `Plugins`, `PluginData`,
`PluginSettings`, `PluginHosts`, `Media`, `Logs` und weitere Ordner.

Unter `Applications` sind aktuell die Geräteverzeichnisse
`Loupedeck10`, `15`, `20`, `30`, `40`, `50`, `60`, `70`, `71`, `72` vorhanden. **Das allein belegt weder ein angeschlossenes Gerät noch aktive Profile in jedem Verzeichnis.**

Unter `Applications.Backups` sind zahlreiche datierte ZIP-Snapshots vorhanden, darunter `backup_2026-11-04_00-23-24.zip` sowie `backup.date`/`backup.hash`. Es wurde **keine** systematische ZIP-Inhaltsanalyse durchgeführt.

### 7.2 Vom Benutzer geliefertes JSON-Beispiel

Die angehängte `ProfileInfo.json`-Struktur ist **valide JSON** und weist unter anderem auf:

- `$type = Loupedeck.Service.ApplicationProfile, LoupedeckService`
- `displayName = VSCode`, `applicationName = @_vscode`, `nativePluginName = VSCode`
- `deviceType = Loupedeck60` – **nicht** `Loupedeck70` (MX Creative Keypad)
- `layout.$type = ProfileLayout20`, `layoutModes[0].modeName = main`
- `touchPages` mit `ProfileLayoutButtonPage` und `pressAction`/`fnPressAction`
- `encoderPages` mit `rotateAction`/`fnRotateAction`
- `wheelPages` mit Template/Parameter-Struktur
- `workspaces` mit Verweisen auf Touch-/Encoder-/Wheel-Page-Namen sowie `homeWorkspaceName`
- `dynamicPageName`, `dynamicPagePluginName`, `dynamicPageNumber` als mögliche Hinweise auf dynamische Seitenbeziehungen;
- `macroCommands`, `macroAdjustments`, `profileCommands`, `profileAdjustments`, `profileActions` als separate Felder.

**Interpretationsgrenze:** In diesem konkreten Beispiel sind die aufgelisteten Aktionszuordnungen überwiegend `null`, die genannten Makro- und Profile-Action-Listen leer. Es liefert daher **keinen** belastbaren Beleg dafür, wie eine tatsächlich belegte Taste oder eine parametrisierte Profile Action im Detail serialisiert wird. Das muss der Forschungsagent an geeigneten belegten Profilen untersuchen.

Die Feldbezeichnung `dynamicPagePluginName` allein beweist noch **keine** Identität zwischen solchen Seiten und einem SDK-`PluginDynamicFolder`.

### 7.3 Externe Referenz – Drittquelle, keine Norm

[ssurmacz2-arch/logi-options-profiles](https://github.com/ssurmacz2-arch/logi-options-profiles) dokumentiert ein reales Profil-Sample und insbesondere:

- [Profilformat](https://github.com/ssurmacz2-arch/logi-options-profiles/blob/main/docs/profile-format.md)
- [Dateipfade](https://github.com/ssurmacz2-arch/logi-options-profiles/blob/main/docs/file-locations.md)
- [Profil- und Pluginpakete](https://github.com/ssurmacz2-arch/logi-options-profiles/blob/main/docs/package-formats.md)
- [Backups](https://github.com/ssurmacz2-arch/logi-options-profiles/blob/main/docs/backups.md)
- [Gerätetypen](https://github.com/ssurmacz2-arch/logi-options-profiles/blob/main/docs/device-types.md)

Das Repository basiert nach eigener Angabe auf **26 Profilen mehrerer Gerätetypen einer Windows-Installation (August 2026)**; interne Formate sind nicht als versionsstabil bewiesen. Es beschreibt u. a., dass fehlende externe Plugin-Abhängigkeiten eine eingelesene, aber funktionslose Profilbelegung verursachen können. **Unsere lokalen Beobachtungen müssen unabhängig dagegengeprüft werden.**

### 7.4 Offizielle Logitech-Referenzen

- [Actions SDK – Plugin Basics](https://logitech.github.io/actions-sdk-docs/plugin-basics/)
- [Default Application Profiles / .lp5](https://logitech.github.io/actions-sdk-docs/csharp/plugin-features/default-application-profiles/)
- [Profile Actions und Parametrisierung](https://logitech.github.io/actions-sdk-docs/csharp/plugin-features/profile-actions/)
- [Plugin Structure / Profiles](https://logitech.github.io/actions-sdk-docs/csharp/tutorial/plugin-structure/)

## 8. Warum der Forschungsauftrag jetzt Priorität hat

**Hoher Erkenntnisgewinn:**

1. Erklärt mit echten Daten die Trennung von Profil, Workspace, Page und Dynamic Folder.
2. Klärt, wie **Action-Referenzen**, konkrete Parameterwerte, Makros und plugin-eigene Actions gespeichert sind.
3. Verhindert eine falsche Entitätentrennung im kommenden ActionInspector und einem möglichen ProfileEditor.
4. Zeigt, ob und wie bestehende Profile **lesend** in unserem Studio visualisiert werden könnten.
5. Liefert eine belastbare Entscheidung, ob ein nativer Profilimport/-export später sinnvoll ist, ohne eine riskante „Live-JSON-Editor“-Abkürzung.

**Grenzen:** Das interne Profilformat liefert nicht automatisch eine sichere, offiziell unterstützte Schreibschnittstelle. Auch eine erfolgreiche Dekodierung berechtigt uns nicht, laufende Daten zu verändern. Umgekehrt brauchen wir für SDK-native Aktionen und Dynamic Folders nicht zwingend zuerst einen vollständigen eigenen ProfileEditor.

**Beschluss für die weitere Planung:** `ActionInspectorWidget`, `ProfileEditor`, zusätzliche native Katalogquellen und eine etwaige Profil-Persistenzschicht bleiben *fachlich anpassbar*, bis die Forschungsergebnisse bewertet sind. Abgenommene Keypad-/Katalog-/SymbolDesigner-Widgets können unabhängig weiterverwendet werden.

## 9. Forschungsfragen für den Agenten – nach Priorität

| ID | Priorität | Forschungsfrage |
|---|---|---|
| R-01 | P0 | Welche Entitätstypen/Klassen/Felder treten in `ProfileInfo.json` bei `Loupedeck70` (MX Keypad), `Loupedeck60` und anderen tatsächlich belegten Profilen auf? |
| R-02 | P0 | Wie verbinden Profile, `layoutModes`, Workspaces, `homeWorkspaceName`, Pages, Controls und Aktionsreferenzen einander? Identität über GUID, Name, `$type` oder andere Schlüssel? |
| R-03 | P0 | Wie sieht eine **nicht-null**-Belegung konkret aus? `pressAction`, `fnPressAction`, `rotateAction`, Makro-/Profile-Command-/Profile-Action-Verweise; welche Werte sind lokal und welche plugin-extern? |
| R-04 | P0 | Welche gespeicherten Parameter sind Werte einer **Profil-Action-Instanz** und welche Teil der allgemeinen SDK-Aktionsdefinition? |
| R-05 | P0 | Was unterscheidet Fallback- und anwendungsbezogene Profile in den lokalen Daten? Was ist rein UI-/Service-seitiger Umschaltkontext? |
| R-06 | P0 | Wie hängen Workspaces und `layoutModes` tatsächlich zusammen? Was bewirken `activationActions` und sonstige Navigationsreferenzen? |
| R-07 | P0 | Welche Beziehungen haben `dynamicPageName`, `dynamicPagePluginName`, `dynamicPageNumber` zu SDK-Dynamic-Folders? Nicht allein anhand des Namens gleichsetzen. |
| R-08 | P1 | Welche Gerätefähigkeiten/Seiten-/Control-Anzahlen sind wirklich gerätespezifisch (insb. 70/71/72 vs. 60)? |
| R-09 | P1 | Welche Dateien/Metadaten referenziert ein lokaler Profilordner außerdem? Rollen von `metadata/LoupedeckPackage.yaml`, Assets, Action Images, Package-Information. |
| R-10 | P1 | Was ist die belegbare Paketstruktur echter `.lp5`-Exporte im Vergleich zu `Applications.Backups`-ZIPs und lokalen Profilordnern? Keine Funktionsbehauptung aus Dateiendungen. |
| R-11 | P1 | Welche Profile referenzieren externe installierte Plugins? Wie lässt sich eine fehlende Abhängigkeit lesend feststellen? |
| R-12 | P1 | Welche Werte sind stabil, individuell/generiert oder versionsabhängig? Welche Felder können personenbezogene Daten/Dateipfade enthalten? |
| R-13 | P1 | Welche Begriffe unseres bisherigen SDK-nativen Projektvertrags sind deckungsgleich, nur analog oder klar inkompatibel mit Logitech-Profilserien? |
| R-14 | P2 | Welche datengetriebene lesende Vorschau oder ein späterer sicherer Import/Export wären realistisch, ohne direkt in laufende Logitech-Profile zu schreiben? |

**Priorität der Referenzfälle:** Zuerst `Loupedeck70` und bewusst **nichtleere** Profile, dann anwendungsbezogenes Profil und Fallbackprofil, dann andere Gerätetypen/Backupversionen. Leere Profile erklären die Struktur, aber nicht den Action-Verweis.

## 10. Entscheidungs- und Qualitätsgate nach der Untersuchung

Der Agent soll **keine** der folgenden Entscheidungen selbst „festlegen“, sondern evidenzbasiert zur Freigabe empfehlen:

- Brauchen wir zusätzlich zu `NativeAction` eine **separate, Logitech-native Profil-/Layout-Leseansicht**? (Vermutlich ja, aber Umfang offen.)
- Ist ein `ProfileExplorerWidget` sinnvoll und welche Quellen/Capabilities besitzt es?
- Wie würden ein zukünftiger `ProfileEditor` und `FolderEditor` sich unterscheiden?
- Welche Felder darf `ActionInspectorWidget` direkt verändern und welche gehören zur Profilinstanz?
- Wo ist eine nachgewiesen unterstützte Export-/Importmöglichkeit; wo wäre direkte Dateibearbeitung riskant?
- Müssen wir frühere Widgetpläne/DTOs korrigieren – **konkret welche und mit welchem Nachweis**?

**Fertig ist die Recherche**, wenn sie ein vollständiges beobachtetes **Entitäten-/Beziehungsdiagramm**, belegte JSON-Pfade für typische Referenzen, ein Quellenregister, Widersprüche/Unbekanntes und eine priorisierte Folgenanalyse liefert. Ein Text wie „Profil enthält Workspaces“ ohne tatsächlichen Referenznachweis genügt nicht.

---

## 11. Bewusst noch nicht festgeschriebene Punkte
- Kein neues allgemeines `Profile`-/`Action`-ORM als führende Produktdomäne.
- Keine Umdeutung von `PluginDynamicFolder` zu `Workspace` oder umgekehrt.
- Kein allgemeiner `ActionOffer`-Entitätstyp im Persistenzmodell.
- Kein stilles Ändern aktiver Logitech-Profile anhand von `ProfileInfo.json`.
- Kein `.lp5`-Writer/Installer aufgrund einer unbelegten ZIP-Vermutung.
- Kein automatisches Zusammenführen unterschiedlicher Geräte-`Layout`-Klassen.
- Kein Umbau der bereits abgenommenen Widget-Schnittstellen ohne klaren Nachweis, dass dies erforderlich ist.
- Kein endgültiger ActionInspector mit Pflichtfeldern, die nur aus einem einzelnen leeren `Loupedeck60`-Profil abgeleitet wurden.

**Zusammenfassung:** Wir haben die *fachlichen Grenzlinien* verbindlich entschieden; das undokumentierte *lokale Serialisierungsmodell* wird jetzt gezielt erforscht. Erst dann legen wir weitere Autoren- und Profileditor-Verträge endgültig fest.

## 12. Zugehöriger Forschungsauftrag

**Forschungsowner ist nun die bestehende separate SDK-Wissensbasis** unter `P:\LokaleProjekte\logi_actions_sdk\logi-actions-sdk-rec`. Der aktuelle, mit Run-Manifest und unveränderlichem Prompt vorbereitete Auftrag heißt **AP-PROF-001**; Originalprompt: `P:\LokaleProjekte\logi_actions_sdk\logi-actions-sdk-rec\work\runs\RUN-20261104-PROF001-01\01_original_prompt.md`. **Der Agent wurde nicht gestartet.** Er darf die aktiven Logitech-Verzeichnisse nur lesen und keine Produktquellen ändern. Der frühere [Studio-Entwurf AP-RESEARCH-001](../../work/planning/AP-RESEARCH-001-logitech-profilmodell.md) bleibt als nicht mehr zu startende Planungsfassung erhalten.
