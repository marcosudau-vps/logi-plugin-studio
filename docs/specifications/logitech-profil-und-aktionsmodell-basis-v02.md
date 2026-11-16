# Logitech Plugin Studio – Profil-, Aktions- und Layoutmodell (v0.2)

**Stand:** 05.11.2026 · **Status:** **VERBINDLICHE PLANUNGSGRUNDLAGE**, soweit als **Studio-Entscheidung** gekennzeichnet.  
**Ersetzt für neue Planungen:** [Begriffsbasis v0.1](logitech-profil-und-aktionsmodell-basis-v01.md); v0.1 bleibt als historische Ausgangslage erhalten.  
**Höher priorisierte Architekturentscheidung:** [ARCH-ADR-001 – Native First](../decisions/ARCH-ADR-001.md).  
**Forschungsbasis:** vollständig abgenommenes AP-PROF-001 in `P:\LokaleProjekte\logi_actions_sdk\logi-actions-sdk-rec`. Original-Evidenz: `work/archive/RUN-20261104-PROF001-01/outputs/evidence.jsonl`; unabhängige Abnahme: `reviews/evidence/AP-PROF-001-nachabnahme-20261105.md`.

Dieses Dokument unterscheidet ausdrücklich **Entscheidungen für unser Studio**, **öffentlich SDK-belegte Eigenschaften**, **empirische Logitech-Profilbeobachtungen** und **ungeklärte Punkte**. Ein lokal beobachtetes JSON-Feld ist **kein offizieller SDK-Schreibvertrag**.

## 1. Verbindliche Begriffe

| Studio-Begriff | Verbindliche Bedeutung | Datenherr |
|---|---|---|
| **Aktion / SDK-Aktionsdefinition** | Über das Logitech Actions SDK vom Plugin bereitgestelltes Funktionselement (Command, Adjustment, ggf. parametrisierbar); nicht der Tastendruck oder eine Anzeigeänderung | Plugin / SDK |
| **Aktionskatalog** | Kontextabhängige Sammlung/Ansicht momentan verfügbarer SDK-Funktionen; **kein** zusätzlicher fachlicher Typ „Aktionsangebot“ | Ansicht / Host, Quelle SDK |
| **Profil** | Vom Logitech Service verwaltete Belegung für Gerät und Anwendungskontext; Allgemein-/Fallback- und Anwendungsprofile sind Kontexte desselben prinzipiellen Eigentümers | Logitech Service / Benutzer |
| **Profile Action (Profilinstanz)** | In einem Profil gespeicherte konkrete, möglicherweise parametrisierte Aktionsinstanz (`profileActions[]`); keine neue SDK-Klassendefinition | Logitech-Profil |
| **LayoutMode / Workspace / Page / Control** | Logitech-Dienst-interne Struktur der Profilbelegung; ihre Serialisierung unterscheidet sich nach Gerätefamilie | Logitech Service / Benutzer |
| **SDK Dynamic Folder** | Vom Plugin angebotener dynamischer Funktionsbereich; im Logitech-Profil kann der Zugang platziert sein, den Inhalt besitzt das Plugin | Plugin, innerhalb des Folders |
| **Profil-UI-Folder** | Ein über `folderPages`/`@OpenFolder` repräsentierter profilseitiger Ordner (lokal insbesondere beim Actions Ring beobachtet) | Logitech-Service-Profil |
| **Ereignis/Status/Bildaktualisierung** | Verarbeitung und Darstellung einer bereits vorhandenen Funktion, **nicht automatisch** eine weitere Aktion | Plugin- oder Host-Runtime |

**Entscheidung:** Es gibt keine zweite parallele `Action`-Domäne neben der SDK-nativen. Insbesondere die Profilinstanz `profileActions[]` wird nicht in `NativeAction` umgedeutet.

## 2. Entitäten- und Verantwortungsmodell

```text
Plugin-Projekt: NativeAction / NativeFolder / Handler
    | [SDK-Aktionsdefinition]                [nur Definition]
    v
SDK / Plugin Service: Aktionen verfügbar je nach Kontext
    | [Aktionskatalog: Sicht, keine unabhängige Entität]
    v
Logitech-verwaltete Profile:
    Allgemein (General) ODER anwendungsbezogen (App)
    | LayoutMode → Workspace / Page / Control
    | Control → Action-Referenz (entweder direkte Plugin-Action
    |                            oder lokale ProfileAction/Macro/Folder-Ref)
    +--> optional: platzierte SDK PluginDynamicFolder-Action
                      | öffnet
                      v
            Plugin-eigene dynamische Inhalte/Navigation

Softwareevent / Python-Callback / State-Update
    → ändert ggf. vorhandenen Action-State, Bild oder Folder-Inhalt
    → erzeugt nicht automatisch ein neues Element im Aktionskatalog.
```

**Entscheidung:** Allgemeines Profil und Anwendungsprofil sind **keine zwei incompatible Studio-Profiltypen**. Beide sind primär Logitech-eigene, benutzerkonfigurierbare Belegungen; der PluginDynamicFolder ist **kein** dritter Profiltyp.

## 3. Was AP-PROF-001 tatsächlich belegt hat

**Lokale Erhebung, keine SDK-Vertragszusage:** 95 Profile, 88 Anwendungsdefinitionen, 675 Control-Action-Referenzen, 21 mit Plugins gelieferte `.lp5`-Pakete und 25 Backup-Dateien. Es wurden drei unterschiedliche Formatfamilien gefunden:

| Familie | Geräte | Unterschied |
|---|---|---|
| `ProfileLayout7` | `Loupedeck70/71/72` | Workspaces enthalten `pressPages`/`rotatePages` inline; Controls haben `controlId` |
| `ProfileLayout20` | `Loupedeck20–60` | Seiten liegen am LayoutMode; Workspace enthält Namen-Referenzen; `roundPage`/`squarePage` separat |
| `ProfileLayout10` | `Loupedeck10/15` | Workspaces enthalten `pressActions[127]`/`rotateActions[127]` statt Page-Objekten |

`Loupedeck70` ist das **Logitech MX Creative Keypad**; das zuvor betrachtete `Loupedeck60`-VSCode-Profil betrifft den **Razer Stream Controller X** und darf nicht als Keypad-Profilvorlage verwendet werden.

**Wichtige Kontrastfälle:** `profileActions[]` enthält Profilinstanzen mit `templateActionName`/`actionParameters`; `macroCommands[]` enthalten profil-lokale Sequenzen; `folderPages` bezeichnet Profil-UI-Ordner und nicht SDK Dynamic Folders. Direkte Control-Referenzen sind String-Werte, kein eigenständiges Aktionsobjekt. Dies legitimiert eine **separate lesende Profilansicht**, aber keine Änderung der SDK-Projekt-Modelle.

**Evidenz:** AP-PROF-001: E-002–E-006, E-012, E-031, E-040, E-046, E-052, E-055–E-058, E-066–E-069. Kuratierte Sekundärübersicht: `logi-actions-sdk-rec/docs/10-konzepte/profil-und-aktionsmodell.md` und `docs/20-referenzen/lokale-profilformate.md`.

## 4. Konsequenzen für vorhandene und geplante Studio-Widgets

| Komponente | Fachverantwortung | Entscheidung nach Forschung |
|---|---|---|
| **ActionCatalogWidget** | verfügbare SDK-Aktionsdefinitionen/Varianten als Auswahl anbieten | bleibt Katalogansicht; kein profilbezogenes `profileActions`-Modell darin |
| **ActionInspectorWidget** (geplant) | native SDK-Aktionsdefinition bearbeiten, parametrisierte Typen/States, Icons, Handlerzuordnung | **Kann weitergeplant werden**, ohne auf ProfileExplorer warten zu müssen; Profilinstanzwerte sind eigener Kontext |
| **KeypadPreviewWidget** | transienten `KeypadFrame`/Slots darstellen, Editierintents liefern | nicht zur `ProfileLayout7/20/10`-Persistenzschicht machen |
| **FolderEditorWidget** (geplant) | plugin-gesteuerte SDK `NativeFolder`-Inhalte bearbeiten | niemals Logitech `folderPages` als dasselbe Modell behandeln |
| **ProblemsPanelWidget** | Diagnosen ansehen, filtern und Navigationsintents melden | unabhängig; keine neue Action-/Profilsemantik |
| **ContextHelpWidget** (geplant) | Hilfeeinträge registrieren/nach Kontext darstellen | unabhängig; kein SDK-Entitätsmodell notwendig |
| **ProfileExplorer** (optional, separat) | empirische Logitech-Profile, Referenzen, Abhängigkeiten **nur lesen** | separate Adapter-/Leseansicht, gerätefamilienbewusst, datenschutzfreundlich |
| **ProfileEditor** (später optional) | normale Logitech-Profilbelegung ändern | **NICHT freigegeben**: kein offiziell bestätigter Schreibweg, kein getesteter Import/Export |

**Entscheidung:** Abgenommene Widgets bleiben unverändert. Eine mögliche profilbezogene Vorschau könnte später in der Host-/Adapter-Schicht in transienten `KeypadFrame` umgewandelt werden, ohne den vorhandenen UI-Vertrag zu einem Logitech-Profilschema umzudefinieren.

## 5. Aktuell offene, explizit nicht zu implementierende Annahmen

1. `dynamicPageName`, `dynamicPagePluginName`, `dynamicPageNumber`: in 170/305 lokalen Pages vorhanden und immer `null/null/0`, Bedeutung **UNKNOWN**.
2. `activationActions`: nur bei 42 Layout20-Workspaces gefunden, sämtlich leer; Aktivierungssemantik **UNKNOWN**.
3. `.lp5`: 21 mitgelieferte Default-Profilpakete sind ZIP-lesbar, doch **kein** Benutzerexport-/Import- oder Roundtrip-Test liegt vor. Paket-/Live-GUID-Zuordnungen sind nur beobachtete Korrelationen.
4. Einige externe Aktionsreferenzen sind lediglich deklariert oder statisch nicht auflösbar; sie dürfen nicht automatisch als ungültig markiert werden.
5. Keine Live-Schreiboperationen an `C:\Users\marco\AppData\Local\Logi\LogiPluginService\Applications` und kein `.lp5`-Writer aus der bloßen Archivkenntnis ableiten.

**Freigegeben für nächste APs:** SDK-nativer ActionInspector oder ein separat abgegrenzter **read-only** ProfileExplorer.  
**Nicht freigegeben:** Direktes Editieren laufender Logitech-Profile, Profile-Import-/Export-Code, neue führende Action-/Profile-Persistenzmodelle.

## 6. Historie und Referenzen

- Frühere Planungsbasis [v0.1](logitech-profil-und-aktionsmodell-basis-v01.md): Grundbegriffe und Forschungsauftrag, weiterhin als Historie lesbar.
- Hauptentscheid [ARCH-ADR-001](../decisions/ARCH-ADR-001.md): Native First bleibt unverändert maßgeblich.
- Forschungseigentümer: `P:\LokaleProjekte\logi_actions_sdk\logi-actions-sdk-rec`.
- Kuratierte Forschung: `research/current-logitech-profiles/befunde-ap-prof-001.md`; importierte Fachartikel `docs/10-konzepte/profil-und-aktionsmodell.md` und `docs/20-referenzen/lokale-profilformate.md`.
- Original-Run: `work/archive/RUN-20261104-PROF001-01/` (archiviert, `COMPLETE`); selbstständiger Review `reviews/evidence/AP-PROF-001-nachabnahme-20261105.md`.
- Katalog-/Source-IDs: `CON-0001`–`CON-0008`, `FMT-0001`–`FMT-0004`, `SRC-0012`–`SRC-0016`; offene Punkte `ISS-0001`–`ISS-0004`.

**Gültigkeit:** Die Modell- und Eigentumsgrenzen dieses Dokuments sind verbindlich für neue Planungen. Konkrete beobachtete interne Logitech-JSON-Felder bleiben versionsgebundene Forschungsergebnisse – niemals ohne weitere Evidenz zu allgemeinen Schreib- oder Kompatibilitätsversprechen erheben.
