# Logitech Plugin Studio – Sammlung von UI-, Bedienungs- und Wartungsverbesserungen

**Ursprungsstand:** 01.11.2026 · **Aktuelle Einordnung:** 05.11.2026.  
**Status:** OFFENES UX-BACKLOG / NUR IDEEN UND BEOBACHTUNGEN; **keine** neue SDK-native Implementierungsfreigabe. U-07 (Probleme) und die Kontext-Hilfe-Aspekte aus U-06 sind bereits als **eigenständige Widgets** abgenommen (AP-WIDGET-004/005), aber **noch nicht im Hauptfenster integriert**. Ältere Begriffe wie `ComponentInstance`, `Binding` und `Presentation` beschreiben nur das alte `0.1-draft`-Modell; für neue Arbeit gilt [ARCH-ADR-001](../../docs/decisions/ARCH-ADR-001.md), [Modellbasis v0.2](../../docs/specifications/logitech-profil-und-aktionsmodell-basis-v02.md) und der [aktuelle Plan](README.md). Kein generisches Binding-/State-Metamodell wieder einführen. Übrige UX-Wünsche sind weiterhin Kandidaten und werden erst im jeweiligen Integrations-AP entschieden.  
**Zweck:** Benutzerbeobachtungen, Codebefunde und weitere Ideen an einer Stelle erfassen. Anschließend die Punkte gemeinsam besprechen, präzisieren, zusammenführen oder verwerfen und **erst danach** priorisieren und planen.

**Quellen:** Gespräch vom 01.11.2026; lesende Prüfung der vorhandenen PySide6-Oberfläche unter `src/studio/app.py`, `src/studio/fields.py` und `docs/13_Benutzerhandbuch.md`. Ein Codebefund bestätigt nur den aktuell untersuchten Quellstand, nicht jede reale Benutzerinteraktion.

## A. Beobachtungen und Wünsche des Nutzers

### U-01 – Logitech Plugin Service direkt im Studio neu starten
- Einen verständlichen Button für einen gezielten Neustart des Logitech Plugin Service anbieten.
- Besser dort, wo auch Installation, Aktivierung und Diagnose verwaltet werden, als versteckt in einem Entwicklerwerkzeug.
- Vor dem Neustart Wirkung auf andere Plugins/offene Nutzung erklären und bewusst bestätigen lassen; Ergebnis und Fehler sichtbar machen.
- **Offen:** sichere und verlässliche Windows-Neustartmethode sowie nötige Rechte später technisch prüfen. Keine pauschalen Prozess-Kills als ungeprüfte Standardlösung.

### U-02 – Übersicht über verknüpfte / registrierte Plugins
- Eine zentrale Ansicht der in Logi Options+ registrierten Entwicklungsplugins.
- Vorhandene .link-Verknüpfungen, zugeordnete Projekt-/Paketpfade und aktuellen Zustand anzeigen.
- Ziel: keine wachsende Ansammlung alter oder überholter Plugin-Einträge in Options+.
- **Offen:** Umgang mit fremden/nicht vom Studio erstellten Plugins.

### U-03 – Aktivieren, Deaktivieren und dauerhaft Entfernen
- Drei gut unterscheidbare Verwaltungsaktionen für Plugins.
- Vorläufige Begriffsabgrenzung: **Aktivieren** stellt die registrierte Plugin-Verknüpfung bereit; **Deaktivieren** nimmt sie aus der aktiven Registrierung, behält aber alle Projekt-/Build-Daten und die Möglichkeit zur Reaktivierung; **Dauerhaft entfernen** beseitigt die Registrierung endgültig und ggf. ausdrücklich ausgewählte studioeigene Installationsartefakte.
- **Wichtig und offen:** Das Löschen eines Studio-Quellprojekts ist **nicht automatisch** Teil von „Plugin dauerhaft entfernen“. Sicherheitsabfrage, Besitz-/Kollisionsprüfung und Wiederherstellbarkeit gemeinsam definieren.
- Statusänderungen können erst nach Logitech-Service-Reload sichtbar werden; Ablauf besprechen.

### U-04 – „Wartung“ statt separater schwer verständlicher Betriebsfunktionen
- Einen Hauptbereich **„Wartung“** erwägen.
- Darin mögliche Teilansichten: **Installierte Plugins**, **Dienstverwaltung**, **Diagnose**, ggf. **Protokolle/Fehler**.
- Aktuelle Diagnose nicht ersatzlos entfernen, sondern in einen verständlichen Ablauf einbinden.
- **Offen:** Welcher Teil gehört zu *Projekt erstellen/builden*, welcher zu *lokal installierte Plugins betreiben*?

### U-05 – Alle sichtbaren Beschriftungen auf Verständlichkeit prüfen
- Entwickler-/Implementierungsjargon aus dem Standard-UI entfernen oder erläutern: z. B. „Authentisierte Host-Diagnose im Worker“, „kein Hardware-PASS“, „kein Service-Neustart“, „Assembly-ID“, „Dry-Run“, „BUILD_PROVEN“, „PROCESS_PROVEN“.
- Stattdessen verständliche Zustands- und Handlungstexte; technische Details bei Bedarf über einen erweiterten Bereich.
- Konsistentes Deutsch, eindeutige Benennungen und einheitliche Begriffe; Bezeichnungen nicht nur kosmetisch ändern, sondern an die Nutzeraufgabe knüpfen.
- Alle Dialoge, Fehlermeldungen, Platzhalter, Tabs, Statusmeldungen und Tooltips einbeziehen.

### U-06 – Zentrale Fachbegriffe und ihr Zusammenspiel erklären
- Erklärungen für **Komponenten, Aktionen, Bindings/Verbindungen, States/Zustände, Views/Ansichten/Ordner, Presentations/Darstellungen, Assets/Bilder**.
- Zusätzlich sichtbar machen, wie das zusammenhängt: **Tastendruck → Aktion → Verbindung/Handler → Zustandsänderung → passende Darstellung auf einer Taste**.
- Möglichst kurze Hilfetexte am konkreten Feld; ausführlichere Beispiele/„Mehr erfahren“ nur auf Wunsch, ohne das Hauptfenster zu überladen.
- Begriffsklärung nicht mit der späteren exakten Editor-/Datenmodellarchitektur verwechseln.

### U-07 – Sichtbare Fehler müssen nachvollziehbar sein
- Aktuell kann unten in der Statusleiste eine Fehleranzahl stehen, ohne dass dort ersichtlich wird, was genau falsch ist oder wo man die Ursache findet.
- Fehlerübersicht mit Klartext, betroffenem Objekt/Feld, Ursache und möglichst Lösungshinweis; direkt zum Problem springen.
- Statusleiste/Fehlerzähler sollte anklickbar sein und den entsprechenden Fehlerbereich öffnen.
- Fehler beim Build, Host, Plugin Service und Projektvalidierung sinnvoll unterscheiden.

### U-08 – Permanente Checkliste für ein vollständiges Plugin
- Kompakter eigener Bereich unten in der linken Sidebar (optional ein-/ausblendbar).
- Ungefähr 10–15 praxisnahe Voraussetzungen/Schritte, mit Status je Punkt: **Grün = erfüllt**, **Neutral = noch nicht erledigt / nicht geprüft**, **Gelb = Warnung**, **Rot = konkreter Fehler**.
- Checklistenpunkte bei Anklicken zu ihrer Ursache/Projektstelle bzw. zum nächsten Arbeitsschritt führen. Für Rot/Gelb verständliche Meldung samt Details.
- Nicht nur eine Zahl oder ein Ampelbild: Text, Icon und Zustand müssen auch ohne Farben unterscheidbar sein.
- **Offen:** Checkliste für *Projektvollständigkeit* vs. *Build/Installation/Hardwarebereitstellung*; diese Stufen besser nicht vermischen.

### U-09 – Hauptmenü und echte Symbol-Toolbar
- Standardaktionen „Neu“, „Öffnen“, „Speichern“, „Speichern unter“, „Rückgängig“, „Wiederholen“ etc. in eine klassische Menüleiste verschieben.
- Darunter eine übersichtliche Symbol-Toolbar für häufig verwendete Funktionen, mit Tooltips und optionaler Textanzeige.
- „Callback-Vorlage“ eher als **„Neues Projekt aus Vorlage …“** oder als eigener Schnellstart statt beliebiger Menüeintrag.
- Menühierarchie und bevorzugte Schnellaktionen gemeinsam ausarbeiten.

## B. Ergänzende Beobachtungen bei der Codeprüfung

### E-01 – Es gibt bereits Fehlerdetails, sie sind nur schlecht auffindbar
- **Codebefund:** `src/studio/app.py::validate_live` füllt eine Tabelle im Tab „Validierung“ mit Schweregrad, Code, Modellpfad und Meldung. `_navigate_diagnostic` navigiert per Doppelklick zum Objekt, soweit der Pfad zuordenbar ist.
- **Codebefund:** `statusBar().showMessage` zeigt nur „N Fehler | Projektpfad“, ohne Sprung zur Liste.
- **Sammlungsidee:** eine gemeinsame, direkt erreichbare Problemzentrale, an die Statusleiste, Checkliste und Formularmeldungen gekoppelt sind; vorhandene Validierung wiederverwenden statt doppelt implementieren.

### E-02 – Build, Installation, Aktivierung, Host-Verbindung und Hardwaretest sind verschiedene Zustände
- Derzeit werden Betriebs-/Evidenztexte teilweise im UI vermischt. Ein Benutzer sollte auf einen Blick wissen, ob er gerade **am Projekt arbeitet**, **den Code gebaut**, **das Plugin registriert**, **den Plugin Service neu geladen**, **einen Python-Host verbunden** oder **eine Taste tatsächlich geprüft** hat.
- Idee: verständliche kleine Statusanzeige je Phase; keine vermeintliche „grüne Gesamtabnahme“, solange nachgelagerte Phasen offen sind.

### E-03 – Die bestehende „Build / Deployment“-Seite ist mit Fachaktionen überfüllt
- **Codebefund:** viele Buttons für Build, Dry-Run, Paketprüfung, Quellarchiv, Receipt und Rollback sowie ein gemischter Ausgabelog stehen auf einer Seite.
- Idee: **Projekt erstellen → Bauen → Installieren/Verknüpfen → Testen** als verständliche Aufgabenfolge; fortgeschrittene Werkzeuge bei Bedarf ausklappen. Sicherer Source-Export und Rollback können in ein Menü bzw. den Wartungsbereich wechseln.

### E-04 – Status- und Fehlertexte sollten handlungsorientiert sein
- Statt „BUILD_PROVEN“ beispielsweise „Plugin erfolgreich erstellt“ und bei Bedarf „Noch nicht in Logi Options+ aktiviert“.
- Statt eines rohen Adapter-Codes möglichst Problemtitel, betroffene Stelle und nächster Schritt; technische Details weiterhin zugänglich.
- Fehler nicht nur als `QMessageBox` oder Loganhang behandeln, sondern bei Bedarf dauerhaft nachvollziehbar protokollieren.

### E-05 – Formulare zeigen teils interne Schema-/JSON-Begriffe
- **Codebefund:** `src/studio/fields.py::ConfigForm` nutzt technische Property-Namen als Feldlabels und setzt als Tooltip den JSON-Schemavertrag.
- Idee: beschreibende, fachliche Labels, kurze Beispiele und passende Eingabewidgets; bei Bedarf ausklappbare erweiterte Felder. Interne IDs/JSON-Ansicht für Experten verfügbar halten.

### E-06 – „Eigenschaften übernehmen“ vs. „Projekt speichern“ ist erklärungsbedürftig
- **Codebefund:** Änderungen werden im Objekteditor erst übernommen, bevor sie mit Speichern auf die Datei geschrieben werden. Ein JSON-Entwurf hat zusätzlich eine explizite Übernahme.
- Idee: sichtbarer Änderungszustand je Ebene, konsistente Schaltflächen und Warnungen bei unübernommenen Änderungen. Diskutieren, ob automatisches Übernehmen bei Objektwechsel der bessere Regelfall ist, ohne unbeabsichtigte Datenänderungen zu riskieren.

### E-07 – Navigation und Anordnung sollten einer Benutzeraufgabe folgen
- Aktuelle Objektkategorien dienen dem Datenmodell; Einsteiger denken eher in „Was soll die Taste machen?“, „Was zeigt sie an?“, „Auf welcher Seite liegt sie?“
- Idee: aufgabenorientierte Hauptnavigation und bei Bedarf eine technische Expertenansicht. Eventuell kontextabhängige Seitenleiste und resizierbare Bereiche statt permanent vieler sichtbarer Register.
- **Offen:** Ob echtes Docking (z. B. QtAds) später Mehrwert hat; zunächst eine konsistente Informationsarchitektur festlegen.

### E-08 – Eigener „Startpunkt“ für neue Projekte und Vorlagen
- Sinnvoll könnten ein nachvollziehbarer Schnellstart und verständliche Standardvorlagen sein: Projektname, erste Aktion, Beschriftung/Bild, erste Ansicht, Test.
- Kein Pflicht-Assistent für erfahrene Benutzer; Vorlagen sollten nachträglich ohne Spezialwissen bearbeitbar bleiben.

### E-09 – Plugin-Verwaltung muss Besitz und Sicherheit unterscheiden
- Aktuell existieren bereits `.link`-Dateien, die **nicht** vom Studio verwaltet werden. Anzeige solcher Einträge kann lesend erfolgen; unbewiesene Fremd-Registrierungen dürfen nicht durch „Entfernen“ oder „Deaktivieren“ beschädigt werden.
- Vor Aktionen: Plugin-ID, Pfad, Zuordnung/Installationsbeleg, Änderungsfolgen, ggf. Rollback klar anzeigen.
- Reaktivierbarkeit verlangt eine nachvollziehbare, lokal gespeicherte Verwaltung des deaktivierten Zustands.

### E-10 – Betrieb/Diagnose: Software- und Gerätefehler auseinanderhalten
- Diagnostik sollte zeigen, **welche Verbindungskette funktioniert**: Studio-Projekt, generierter Adapter, Registrierung, Logitech Plugin Service, Python-Host, Geräte-Callback und LCD-Aktualisierung.
- Ein „Dienst läuft“-Status allein belegt keine Plugin-Ladung und erst recht keine physische Taste.
- Vorschlag: Diagnoseabläufe mit „Was wurde geprüft?“ und „Was wird als Nächstes benötigt?“ statt eines pauschalen PASS.

### E-11 – Kontext, Auffindbarkeit und Hilfe
- Suche/Baumfilter auf Modellobjekte ist vorhanden. Ergänzende Ideen: Aktionen nach Fachbezeichnung auffinden, zu referenzierten Objekten springen, von Bindings zur Quell-/Zielaktion navigieren, Tooltips und kurze Hilfebeispiele.
- Fachbegriffe an **einer** Stelle konsistent definieren, nicht pro Tab leicht unterschiedlich.

### E-12 – Fehlerliste, Ereignisprotokoll und Projekt-Checkliste auseinanderhalten
- **Checkliste:** Was muss noch erstellt oder eingestellt werden?
- **Problemliste:** Was ist jetzt tatsächlich falsch oder problematisch?
- **Betriebs-/Build-Protokoll:** Was ist zuletzt passiert?
- Vorschlag: eine gemeinsame Oberfläche mit klar unterscheidbaren Blickwinkeln, statt dieselben Informationen an mehreren Stellen widersprüchlich zu melden.

## C. Mögliche Checklistenpunkte zur Diskussion (keine endgültige Liste)

Die Punkte **nicht sofort implementieren**; erst zwischen Entwurfsqualität, Buildbereitschaft und realem Betrieb unterscheiden:

1. Projektname und eindeutige Plugin-ID vorhanden.
2. Projektdatei gespeichert; keine unübernommenen oder fehlerhaften Änderungen.
3. Aktionen/Komponenten definiert.
4. Aktionen an die gewünschten Python-Handler gebunden.
5. Zustände und zustandsabhängige Darstellungen sinnvoll definiert, soweit benötigt.
6. Ansichten/Ordner und Tastenplätze zugeordnet.
7. Referenzen und Typverträge im Projekt gültig.
8. Verwendete Bilder/Assets vorhanden und im unterstützten Format.
9. Python-Host/Handler-Konfiguration passend zum Projekt.
10. Projekt technisch erfolgreich validiert.
11. Aktueller Projektstand erfolgreich gebaut (nicht nur ein alter Build).
12. Eigene Plugin-Verknüpfung gültig registriert bzw. gewollt deaktiviert.
13. Logitech Plugin Service hat die aktuelle Registrierung übernommen (sofern nachweisbar).
14. Python-Host ist erreichbar und dem Plugin zugeordnet (sofern relevant).
15. Geräte-/LCD-Funktion real geprüft bzw. bewusst als ungeprüft gekennzeichnet.

**Offen:** Welche dieser Punkte sind echte Pflicht, welche optional, welche nur eine Betriebsprüfung? Neutrale Zustände dürfen nicht als Fehler erscheinen, wenn eine Funktion bewusst nicht verwendet wird.

## D. Offene Designfragen für das spätere Gespräch

- Wie unterscheiden wir künftig **Studio-Projekt**, **gebautes Plugin**, **registriertes Plugin** und **aktiv laufendes Plugin** in Sprache und UI?
- Soll „Dauerhaft entfernen“ nur die Options+-Registrierung beseitigen oder wahlweise eigene Builds/Artefakte? Projektquellen niemals still löschen.
- Welche Diagnose-/Wartungsfunktionen werden global (für alle Plugins), welche projektbezogen angezeigt?
- Wie weit darf der Studio-Button den Logitech Plugin Service kontrollieren; sind Start/Stop neben Neustart überhaupt erforderlich?
- Wie viel Expertenwissen soll standardmäßig verborgen bleiben, ohne den freien deklarativen Editor einzuschränken?
- Soll die Seitenleiste stets die Checkliste zeigen oder zwischen Projektbaum, Checkliste und Fehlern wechseln?
- Braucht es getrennte Checklisten für **Projekt erstellen** und **Plugin in Betrieb nehmen**?
- Welche Standardaktionen gehören dauerhaft in die Toolbar, welche nur ins Menü?

## E. Weitere Sammlung / Änderungsprotokoll

Neue Beobachtungen fortlaufend mit Herkunft (Nutzerwunsch / Codebefund / Idee) ergänzen. Keine Priorität, kein Aufwand, keine AP-Nummer und keine automatische Umsetzungsfreigabe bis zur gemeinsamen Durchsprache.

---

**Bis auf Weiteres keine Änderungen an `src/`, `tools/`, `tests/`, Logitech-Links oder Diensten aus diesem Dokument ableiten.** Dieses Dokument ist ausschließlich eine Diskussions- und Sammlungsvorlage.
