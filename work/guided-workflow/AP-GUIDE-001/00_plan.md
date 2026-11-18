> Kopie des freigegebenen Projektdokuments `claude/plan-gefuehrter-ablauf-2026-11-16.md` (Stand der Freigabe
> am 16.11.2026, 23:25). Die Entscheidungen in Abschnitt 6 sind in [01_auftrag.md](01_auftrag.md) festgehalten.
> Abweichungen bei der Umsetzung stehen in [03_implementierung.md](03_implementierung.md), Abschnitt „Abweichungen vom Plan“.

# Plan: Geführter Ablauf und Fertigstellung des Plugin Studios (16.11.2026)

## 1. Ziel

Das native Studio wird von einer freien Tab-Sammlung zu einem mehrschrittigen, geführten Prozess. In jedem Schritt sind nur die passenden Elemente sichtbar und bedienbar, die Hilfe erklärt den nächsten Handgriff, und jeder Schritt hat prüfbare Abschlusskriterien. Die fehlenden Widgets werden in der Reihenfolge gebaut, in der ein Anwender sie im Ablauf braucht.

## 2. Architekturentscheidungen, die unverändert bleiben

- ARCH-ADR-001 (Native First, Minimal Bridge, Optional Extensions): Der geführte Ablauf ist eine optionale Komfortschicht oberhalb des nativen Modells, kein neues Fachmodell.
- Ein Eigentümer je Wert: `NativeProjectSession` bleibt einziger Writer des nativen Projekts, `ExtensionStore` der `.vfolders.json`. Der Ablauf schreibt nichts in diese Dateien.
- `StudioCoordinator` bleibt der einzige Host; keine Widget-zu-Widget-Direktzugriffe, kein Autosave.
- Eine Hilfe (`HelpRegistry`/`HelpCoordinator`/`ContextHelpWidget`), eine Problemliste (`ProblemsPanelWidget`). Führungstexte und Schrittprüfungen werden dort als neue Quellen registriert.
- Jede neue Verbindung: Eintrag im Verbindungsregister mit eigenem Test, eigene `widgets/<Name>.md`, Hilfethemen im selben Arbeitsschritt.
- Bridge, Generator, Projektformat, Legacy-Editor (`0.1-draft`) und Profile (`ProfileInfo.json`, `.lp5`) bleiben unangetastet.

## 3. Zielbild: sieben Schritte

| Nr. | Schritt | Sichtbar und bedienbar | Abschlusskriterium |
|---|---|---|---|
| 1 | Projekt | Startseite: Neues Projekt, Öffnen, Plugin-ID, Anzeigename | Gültiges natives Projekt geladen und gespeichert |
| 2 | Handler | Handler-Bereich (neu) | Mindestens ein Handler, Handlerdatei zugeordnet und vorhanden |
| 3 | Aktionen | Aktionskatalog, Aktionsinspektor | Mindestens eine Aktion, jede mit gültigem Handler, Parser fehlerfrei, kein offener Entwurf |
| 4 | Darstellung (optional) | SymbolDesigner, Bildfelder | Referenzierte Symbole vorhanden; fehlende sind Warnung, keine Sperre |
| 5 | Belegung (optional) | Keypad, Virtuelle Ordner | Keine verwaisten Referenzen, Extension gespeichert |
| 6 | Prüfen und Bauen | Probleme, Plugin-Build | 0 Fehler, alles gespeichert, Build erfolgreich und passend zum gespeicherten Stand |
| 7 | Installieren und Testen | Installation | Installiert, geladen, Verbindung aktiv; Gerätetest vom Anwender bestätigt |

Außerhalb der Schrittfolge: „Shared-Peers“ (nur beim Plugin-Typ Shared sichtbar) und „Wartung“ (global, projektunabhängig).

### Regeln

- Vorwärts nur bei erfüllten Abschlusskriterien; zurück jederzeit.
- Eine Änderung in einem früheren Schritt löscht nichts, markiert aber spätere Ergebnisse als veraltet (Build, Installation).
- Optionale Schritte lassen sich ausdrücklich überspringen und erscheinen dann neutral, nicht als Fehler.
- Statusanzeige je Schritt mit Text und Symbol: erfüllt, offen, Warnung, Fehler, veraltet.
- Der Schrittstatus wird bei jedem Aufruf aus den echten Daten berechnet (Session, Extension, Diagnosen, Build- und Installationsergebnis) und nie im Projekt gespeichert. Benutzerlokal gemerkt werden nur Oberflächenzustände (aktiver Schritt, übersprungene Schritte, Modus), nach dem Muster von `build_mode_store.py`.

### Technische Bausteine

| Baustein | Art | Aufgabe |
|---|---|---|
| WorkflowModel | Qt-frei, neu | Schrittdefinitionen und reine Funktionen: Fakten → Schrittstatus |
| Schrittleiste mit Checkliste | Widget, neu | Zeigt die sieben Schritte mit Status und Unterpunkten; Klick springt zur Ursache (deckt U-08) |
| Schritt-Steuerung in der Shell | Erweiterung `native_shell` | Blendet Tabs und Werkzeugleisten-Einträge je Schritt ein oder aus |
| Führungsthemen | Hilfe-Quelle `guide` | „Was ist jetzt zu tun“ je Schritt im bestehenden Hilfe-Widget, Knopf „Weiter“ |
| Schrittprüfungen | Diagnose-Quelle `workflow.<schritt>` | Nicht erfüllte Kriterien als Einträge in der Problemliste |

## 4. Reihenfolge der Arbeit

### Stufe 0: Ausgangsbasis sichern
- Vollständigen Testlauf auf dem jetzigen Stand ausführen und als Referenz festhalten.
- Sicherung des Quellstands (Git oder ZIP, siehe Entscheidung 3).
- Klären, welche Prüfungen ohne Windows-Rechner laufen und welche nur dort (C#-Build, Logi Plugin Service, Keypad).

### Stufe 1: Konzept festschreiben
- `docs/architecture/studio/widgets/WorkflowGuide.md`: Schritte, Kriterien, Sichtbarkeitsmatrix je Tab und Werkzeugleisten-Eintrag.
- Begriffsliste: ein Wort je Sache (Aktion statt Action/Aktion, deutsche Statuswerte).

### Stufe 2: Gerüst mit den vorhandenen Widgets
- WorkflowModel, Schrittleiste mit Checkliste, Schritt-Steuerung, Führungsthemen, Startseite.
- Menüleiste und aufgeräumte Werkzeugleiste (U-09), ein Befehl „Alles speichern“, der beide Speichervorgänge nacheinander auslöst.

### Stufe 3: Lücken in Ablaufreihenfolge schließen
- 3a HandlerInspector: Handler anlegen, umbenennen, löschen mit Referenzschutz; Handlerdatei aus Vorlage erzeugen.
- 3b Zustandssicht im Aktionsschritt: SDK-States und Python-State getrennt anzeigen.
- 3c Belegung: je nach Entscheidung 2 nur Vereinheitlichung auf virtuelle Ordner oder zusätzlich Bearbeiten nativer Platzierungen.

### Stufe 4: Prüfen, Bauen, Installieren im Ablauf
- Build erst bei 0 Fehlern und gespeichertem Stand; Erkennung veralteter Builds.
- Installationstab: beschriftete Bereiche, deutsche Statuswerte, Anleitung zur Zuweisung in Options+, Bestätigung des Gerätetests.

### Stufe 5: Wartung
- Eigener Bereich: installierte Plugins, Aktivieren/Deaktivieren, Protokolle, Dienst-Neustart (U-01 bis U-04).
- Vorab technische Prüfung, wie sich der Logi Plugin Service sicher neu starten lässt.
- „Shared-Peers“ wird aus der Tab-Leiste hierher bzw. hinter den Plugin-Typ Shared verlegt.

### Stufe 6: Abschluss
- Handbuch und veraltete Dokumente angleichen, Benutzerabnahme-Skript auf den neuen Ablauf umschreiben.
- Vollregression, neuer Release-Kandidat, deine Benutzerabnahme inklusive Tastendruck am Keypad.

### Bewusst zurückgestellt
- ActionEditorDesigner (visueller Designer für Options+-Dialoge): die Zeilenbearbeitung im Inspector genügt für den Ablauf.
- ProfileExplorer, Python-SDK-API-Checkliste, Code-Signierung.

## 5. Prüfung je Stufe

- Reine Tests für das WorkflowModel (Fakten → Status), Qt-Tests für Ein-/Ausblenden und Sperren.
- Die bestehenden 1.208 Tests bleiben grün. Viele davon setzen frei erreichbare Tabs voraus; deshalb wird die Schritt-Steuerung als abschaltbare Schicht gebaut.
- Sichtprüfung unter Windows durch dich am Ende jeder Stufe; keine Selbstabnahme.

## 6. Offene Entscheidungen

1. Expertenmodus: geführter Ablauf als Standard mit umschaltbarer freier Ansicht (Empfehlung) oder ausschließlich geführt.
2. Ordner: nur virtuelle Ordner als Bearbeitungsweg, native SDK-Folder bleiben Anzeige (Empfehlung), oder zusätzlich ein Editor für native Platzierungen.
3. Sicherung: Git-Repository im Projektordner anlegen oder weiter ZIP-Sicherungen.
