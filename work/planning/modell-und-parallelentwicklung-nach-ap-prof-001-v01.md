# Plugin Studio – Modell- und Parallelentwicklungsplan nach AP-PROF-001

**Stand:** 05.11.2026  
**Status:** Planung; vorgeschlagene nächste Implementierungspakete sind ausdrücklich voneinander isoliert.  
**Verbindliche Grundlage:** [ARCH-ADR-001](../../docs/decisions/ARCH-ADR-001.md), [Profil- und Aktionsmodell v0.2](../../docs/specifications/logitech-profil-und-aktionsmodell-basis-v02.md).  
**Ausgangslage:** SDK-native Projektklassen existieren in `src/adapters/logitech/native.py`, Generator in `src/adapters/logitech/product.py`. Das Hauptfenster `src/studio/app.py` bearbeitet noch überwiegend `0.1-draft`. Eigenständige Widgets KeypadPreview, ActionCatalog, ProblemsPanel und ContextHelp sind abgenommen. Native ICT-Binding ist vorhanden. **Keine** pauschale SDK-native Studio-Gesamtintegration behaupten.

## 1. Leitlinie

**Nicht** noch ein eigenes Aktions-, Profil- oder State-Metamodell entwickeln. Die verbleibende Arbeit ist überwiegend die saubere **Beziehung zwischen vorhandenen Originalmodellen**, ihre **Lebensdauer und Bearbeitungsautorität** und ihre **Benutzeroberfläche**.

```text
 SDK-native Autorenprojektdatei (logitech-native-1)
           |
           v
 NativeProjectSession   ← neuer technischer Transaktions-/Dateiowner
     |          |
     |          +→ parse_native_project (bestehende Validierung)
     |          +→ konfliktgeschütztes Save / Undo / Redo
     |
     +→ NativeProject snapshot
                   |
                Host / StudioCoordinator (danach; keine Parallelmodelle)
                   |
        ┌──────────┼────────────┬───────────────┬───────────────┐
        ▼          ▼            ▼               ▼               ▼
   ProjectExplorer ActionCatalog  ActionInspector FolderEditor  ContextHelp
       (view)       (view)         (später)        (später)      (view)
                   |
                   v
             KeypadPreview
          (transienter Frame)
                   |
                   v
       EditRequest / Intent → Host → Session-Commit → neuer Snapshot
```

**Separater Bereich:** Logitech-serviceverwaltete `ProfileInfo.json`-Profile, `profileActions`-Instanzen und `folderPages` aus AP-PROF-001 sind **keine** SDK-Projekt-Entitäten. Falls später gewünscht: optionaler **read-only ProfileExplorer**, klar getrennt vom SDK-Projektbaum.

## 2. Vor weiterer Fach-UI gezielt durchzudenkende Modelle/Verträge

| Vertrag / Modellbereich | Bestehende Grundlage | Noch zu entscheiden / prüfen | Reihenfolge |
|---|---|---|---|
| SDK-natives **Projekt-/Dokumentleben** | `NativeProject`, `parse_native_project`; `ProjectDocument` nur für 0.1-draft | Laden, Commit, Dirty, Undo/Redo, Revision, Save-Konflikt, atomare Persistenz, Verlustfreiheit | **P0: jetzt** |
| **Referenzen und Identitäten** | `NativeAction.id`, `handler`, `NativeFolderEntry.id/action/position` | Update-/Löschregeln, Reorder, stabile IDs, verwaiste Bezüge; `action_parameter` ist getrennt vom Action-ID | **P0: parallel als Vertrag** |
| **Handlerzuordnung / Python-Callback** | `NativeProject.handlers` + `NativeAction.handler`; Runtime/Bridge besteht | Callback-ID, Lifecycle, Signatur, Erfolg/Fehler, Python-init/stop, SDK-Event-Abbildung; keine zweite Action | **P0/P1: gezielt klären** |
| **SDK-State vs. externer Python-State** | `NativeState`, `state_change`, Runtime-StateStore | Owner/Lebensdauer, actionParameter-Scope, Aktualisierung/Notifications, Display-Kanäle, stale/fresh | **P1: vor StateInspector** |
| **DynamicFolder-Platzierung und Navigation** | `NativeFolder`, `NativeFolderEntry`, `KeypadFrame` | Page-Zuordnung, device_navigation, Positions-/Button-Capabilities, Varianten/Parameter pro Placement im heutigen Contract nicht persistent | **P1: vor FolderEditor** |
| **Darstellung/Asset-Verwendung** | native `.ict`, `NativeAction.icon`, `icon_template`, `symbol`; SymbolDesigner | Bildpriorität, Caption, Parameterbilder, Zustand-/Live-Refresh, Assetkonflikte; keine zweite Bild-Domäne | **P1: kontrolliert** |
| **Build/Deploy & Capability-Anzeige** | `product.py` + bestehende Worker/Deploy-Prüfungen | echte Fähigkeiten und deren Evidenz, Entwicklungs-/Build-/Teststatus getrennt, nicht aus alten `capabilities.py`-Texten pauschal ableiten | **P1/P2: UI danach** |
| **Logitech-Service-Profilmodell** | AP-PROF-001, drei interne Layoutfamilien | read-only Explorer optional; Writer/LP5-Import/Export weiterhin ungeprüft | **Optional, später** |

**Keine Architekturvermehrung:** \"Modell\" bedeutet hier oft nur einen stabilen Vertrag zwischen bestehenden Originalobjekten und Editor-/Runtime-Werten. Nicht alle Zeilen verdienen neue persistente Klassen.

## 3. Konkrete Umsetzung in Etappen

**Etappe A – jetzt parallel, ohne Konflikte:**
- [AP-STUDIO-001 – NativeProjectSession v1](AP-STUDIO-001-agentenauftrag-native-session-v01.md): einziges neues nicht-Qt-Modul für sichere Bearbeitung vorhandener nativer Projekt-JSONs; ohne Hauptfensterumbau.
- [AP-WIDGET-006 – NativeProjectExplorerWidget v1](AP-WIDGET-006-agentenauftrag-project-explorer-v01.md): eigenständiger navigierbarer, rein lesender SDK-Projektbaum mit Qt-Lab und Tests; kein ProfileInfo-Explorer.

**Etappe B – nach unabhängiger Abnahme von A:**
- `StudioCoordinator` und sukzessive **produktive** Integration in `StudioWindow`: Projekt öffnen → NativeSession → ProjectExplorer/ActionCatalog/KeypadPreview → ausgewählte Action; ProblemsPanel und ContextHelp in die Shell. Keine automatische Aktion bei UI-Klicks.
- Integrationstests einer echten Benutzerreise, nicht nur isolierter Widgets. Das `0.1-draft`-Studio bleibt kompatibel und darf nicht still entfernt werden.
- Vor dem ersten schreibenden ActionInspector die kleinen Commit-Operationen je nativem Action-Typ und die Referenzänderungsregeln entscheiden.

**Etappe C – Fach-Editoren:**
- ActionInspector (erste vollständige native Kommando-Änderungsreise), anschließend Handler-/State-Bereiche und FolderEditor in getrennten APs.
- Vollständiger End-to-End-Pfad mit SDK-Generator, Tests und Geräteabnahme, ohne bisherige Lab-Belege rückwirkend umzudeuten.

## 4. Bewusst nicht parallel starten

- `ProfileInfo.json`-Writer und `.lp5`-Installer: keine gesicherte öffentliche Schreib-API.
- Einen neuen allgemeinen State-/Event-/Binding-Graphen: ARCH-ADR-001 verbietet eine zweite führende Fachsemantik.
- Umbau von `src/studio/app.py`, `native.py` oder `product.py` durch beide Etappe-A-Agenten.
- FolderEditor, wenn noch unklar ist, wie `NativeFolderEntry` Parameter-/Seiten-/Positionssemantik für reale Geräte trägt.
- Mehrere Agenten gleichzeitig an derselben Hauptfensterdatei, Projektpersistenz oder Icon-/ICT-Commitlogik.

## 5. Abnahmeregeln

Agenten arbeiten in **getrennten Verzeichnissen/Dateien**. Je Agent: vollständiger Agentenprompt, unabhängiges Lab, gezielte Tests, gesamte Regression, nachvollziehbarer Änderungsbericht, keine Selbstabnahme, Abschluss `READY_FOR_REVIEW`. Ein unabhängiger Review gibt `APPROVED` oder einen konkreten Nachbesserungsauftrag.

**Fachentscheidung für spätere Zusammenarbeit:** NativeProjectSession ist der technische Commit-Owner des nativen Autorenprojekts. Der StudioCoordinator verbindet dessen Snapshots mit den passiven Widgets und SDK-Capabilities. Der Projektbaum ist eine Anzeige; seine Klicks erzeugen weder eine Ausführung noch einen Projekt-Commit.
