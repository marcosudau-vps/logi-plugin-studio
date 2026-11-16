# AP-INSP-002 – Native Actions erstellen/löschen und Inspector-UX verbessern

**Vollständiger, eigenständiger Agentenauftrag (keine Kenntnis vorheriger Sessions erforderlich).**  
**Projektroot, verbindlich:** `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture`  
**Datum:** 06.11.2026  
**Status:** PREPARED, nicht gestartet. **Agentenabschluss: READY_FOR_REVIEW**, nicht APPROVED; unabhängige Abnahme durch den Auftraggeber.  
**Architekturlinie:** SDK Native First / Minimal Bridge. Projektdateien nur über die vorhandene `NativeProjectSession` und den `StudioCoordinator` mutieren.

## A. Zuerst vollständig lesen und die wirkliche Baseline aufnehmen

1. `docs/decisions/ARCH-ADR-001.md`
2. `docs/specifications/logitech-profil-und-aktionsmodell-basis-v02.md` und `docs/specifications/sdk-native-modellabgleich-v01.md`
3. `docs/architecture/studio/README.md`, `00-Gesamtkarte.md`, `01-Daten-und-Transaktionen.md`, `02-StudioCoordinator.md`, `03-Geplante-Editoren.md` und `04-Verbindungsregister.md`
4. **Neue normative Lifecycle-Spezifikation:** `docs/architecture/studio/widgets/ActionLifecycle.md`
5. **Freigegebener Inspector v1:** `docs/architecture/studio/widgets/ActionInspector.md` und `work/acceptance/20261106-action-inspector/ABNAHME.md`, insbesondere OBS-INSP-001 und OBS-INSP-002
6. `work/acceptance/20261106-help-coverage/ABNAHME.md` und `work/acceptance/20261106-studio-coordinator/ABNAHME.md`
7. `docs/architecture/studio/widgets/{ActionCatalog,NativeProjectExplorer,ContextHelp,ProblemsPanel}.md` und `docs/architecture/studio/services/NativeProjectSession.md`
8. Vollständig `src/adapters/logitech/native.py`, insbesondere `ACTION_TYPES`, `parse_native_project`, `_states`, `_editor_controls` und die FolderEntry-Referenzprüfung; `src/core/ids.py`, `schemas/logitech_native_v1.schema.json`
9. `src/studio/native_session.py`, `src/studio/action_inspector/{__init__,draft,widget}.py`, `src/studio/native_shell/{coordinator,window,help_bindings}.py`, `src/studio/action_catalog/widget.py`
10. `src/studio/context_help/{registry,coordinator,entries,widget}.py`, alle `src/studio/context_help/resources/*topics.de.json`
11. `examples/project_logitech_native_v1.json`
12. `tests/test_action_inspector_{draft,widget,integration}.py`, `tests/test_native_studio_shell.py`, `tests/test_studio_coordinator.py`, `tests/test_native_help_coverage.py`, `tools/run_action_inspector_lab.py`

Zuerst die projektspezifischen Konventionen lesen. **Vor der ersten Quelländerung** eine SHA-256-Dateibaseline der vorhandenen Projektdateien im eigenen Runverzeichnis sichern; ein aktives Git-Repo im Projektroot wird **nicht vorausgesetzt**. Existierende geprüfte Produktdateien nicht mit historischen Lab-Snapshots überschreiben.

Arbeitsakte **genau unter:** `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\work\action-inspector\AP-INSP-002\`.

Pflichtartefakte: `README.md`, `01_original_prompt.md` (vollständiger unveränderter Wortlaut), `02_verlauf.md`, `03_ergebnisse.md`, `04_abschlussbericht.md`, `baseline-before.json`, `scope-after.json`, `test-results.json`, `coverage-after.json`, Windows-Screenshots, Testlogs und Exitcodes. Nur Originaldateien des aktuellen Projekts als Autorität verwenden, keine separate Schattenimplementierung.

## B. Konkretes Produktziel

Das bisher abgenommene Studio kann vorhandene native Actions aller vier SDK-Typen bearbeiten, aber `+ Neue Aktion` ist in der NativeShell absichtlich dauerhaft gesperrt und eine Action kann nicht gelöscht werden. **Dieses AP implementiert beides produktiv** sowie die zwei im letzten Review dokumentierten P2-Verbesserungen:

- **OBS-INSP-001:** sehr hohe, vollständig aufgeklappte Formulare werden zu sinnvollen einklappbaren Abschnitten mit kompakten editierbaren Listenübersichten.
- **OBS-INSP-002:** bei einem zwischenzeitlichen Host-/Session-Commit ist der offene Draft sofort sichtbar als stale markiert, nicht erst nach erfolglosem Apply.

Das Ziel ist **keine** allgemeine UI-Neugestaltung, kein neues Format und kein FolderEditor. Alle Änderungen verbleiben innerhalb derselben NativeStudioShell.

## C. Etappe 1 – Qt-freie, sichere Action-Lifecycle-Mutationen

Neue, eng abgegrenzte Hilfsfunktionen unter `src/studio/action_inspector/lifecycle.py` (oder analog innerhalb desselben Moduls), **ohne Qt und ohne Dateiwrites**. Sie erhalten eine defensive aktuelle Raw-Snapshot-Kopie und erstellen einen neuen Raw-Snapshot für einen expliziten Hostcommit. Sie dürfen `NativeProjectSession` nicht selbst instanziieren, speichern oder mit ungeprüften Files schreiben.

**Create:**
- Genau vier `ACTION_TYPES`, ID gemäß `src/core/ids.py` und eindeutig innerhalb der aktuellen `actions[]`; kein Umbenennen/Typwechsel vorhandener IDs. Anzeigevorschläge dürfen aus Text entstehen, aber `action.id` bleibt vor dem Commit **sichtbar und editierbar**; eine eindeutige ID darf nicht still nach der Nutzerbestätigung verändert werden.
- Handler muss unter den vorhandenen `handlers[].id` existieren. **Kein** Erstellen/Löschen von Handlerobjekten. Keine Änderung von Folder/Handler/Plugin/sonstigen Actions.
- Pro SDK-Typ **gültiges, ausdrücklich getestetes, einfaches Startobjekt**, ohne erfundene SDK-Felder:
  1. `PluginDynamicCommand` – minimale Pflichtfelder; Parameter optional.
  2. `PluginMultistateDynamicCommand` – zwei States (Index 0/1, eindeutige Namen), zulässiger state_change; optional Bilder nur als referenzierte relative Pfade.
  3. `PluginDynamicAdjustment` – `adjustment: {}` oder gültig initialisierte numerische Optionen.
  4. `ActionEditorCommand` – mindestens ein gültiger Control-Eintrag (z. B. `textbox`), niemals leerer `editor_controls[]`-Array als Pflichtstarter.
- Entwürfe können zusätzliche gemeinsame und typspezifische Felder **mit den bereits vorhandenen Inspector-Feldeditoren** bearbeiten. Die normale `ActionDraft` validiert momentan nur bereits bestehende Actions; diesen Unterschied korrekt modellieren (z. B. kleiner Qt-freier CreateDraft oder temporäre Validierungsprojektion), **nicht** die Produktions-Session manipulieren, um einen Draft vorzutäuschen.
- Ungültige/duplizierte ID, leerer Anzeigename, unbekannter Handler, invalides State-/Controlobjekt → gezielte Diagnose, **kein** Commit.
- Unveränderte Projektdatei bis zum ausdrücklichen späteren Save.

**Delete:**
- Nur eine existierende Action per **stabiler ID** aus der aktuellen Sessionrevision entfernen.
- Bevor die UI überhaupt eine bestätigende Löschung zulässt: alle `folders[*].entries[*].action` prüfen. **Referenzierte Actions dürfen in AP-INSP-002 nicht gelöscht werden**; Liste der betroffenen Folder-/Placement-IDs bzw. Anzahl darstellen. Keine stille Kaskade, keine selbstständige Änderung an FolderEntries. Eine neu erzeugte unreferenzierte Action lässt sich dagegen löschen.
- Letzte Action nicht entfernen, weil `parse_native_project` eine nichtleere `actions[]` verlangt. Beweis- und Negativtest.
- Handler-Daten **niemals** automatisch bereinigen, selbst wenn unbenutzt; restliche Actions/Plugin/Folders/Lizenzen/Assetbezüge unverändert.
- Fehler bei stale `base_revision`, verlorener ID, extern veränderter Datei oder parserungültigem Ergebnis → kein Commit, keine Umdeutung auf andere Action gleichen Anzeigenamens.
- Jeder erfolgreiche Create- oder Delete-Benutzerintent: **exakt ein** `NativeProjectSession.replace(proposed,base_revision=...)`, **kein** Auto-Save. Bestehende Host-Wrapper dürfen eine lesende Disk-Konfliktprüfung mit der bereits vorhandenen Sessionbaseline verwenden, aber keine eigene zweite Writerautorität errichten.

**Pflicht-Negativtests:** ID-Kollision, ID-Regel, unbekannter Handler, unzulässige Typklasse, Parserfehler, letzte Action, referenzierte Action, falsches Projekt/Revision, absichtlich extern veränderte Projektdatei; kein Snapshot-/History-/Dateidiff bei Ablehnung.


## D. Etappe 2 – echte Create/Delete-Bedienung in der NativeShell

**Katalog-Create**:
- Das vorhandene `ActionCatalogWidget.createActionRequested()` mit einem Hostslot verbinden. Das Catalog-Widget hat bereits `+ Neue Aktion` und dieses Signal. In `StudioCoordinator.__init__` gibt es bisher bewusst einen `EnabledChange`-Filter, der den Button selbst nach jedem Catalog-Refresh deaktiviert. **Den Filter nur zusammen mit funktionsfähigem Create-Hostvertrag** entfernen bzw. durch verlässliche Projekt-/Lifecycle-Aktivierung ersetzen; ohne geöffnetes Projekt bleibt Create deaktiviert, mit gültigem geladenem Projekt funktioniert es auch nach Filtern/Sortieren/Undo/Redo.
- Bei Klick einen verständlichen **Erstellungsmodus** als Tab/Panel oder Dialog anbieten: SDK-Typ wählen, stabile Action-ID eingeben, Name, bestehenden Handler wählen, die bestehenden gemeinsamen und typspezifischen Formularbereiche nutzen. Keine generische JSON-Rohtexteingabe als Ersatz. Anzeigename und ID sichtbar, Typ klar beschrieben. Bei Bedarf die bestehenden Qt-Formulare so erweitern, dass Creation und Edition dieselben Komponenten verwenden.
- Der Create-Draft hat einen **separaten Dirty-Status** und eine opake Baserevision plus Projekttoken. Kein neuer persistenter Store. Vor Apply existiert die Action **nicht** in der Session und weder im Katalog noch im Explorer. Cancel/Verwerfen/Projektwechsel/Schließen behandeln den Create-Draft genauso zuverlässig wie einen Edit-Draft. Wenn ein neuer Create-Befehl bei anderem Dirty-Draft kommt, zuerst Apply/Verwerfen/Abbrechen und vorherige Auswahl bei Cancel erhalten.
- Erfolgreiches Create: ein validierter Commit, neue Action-ID zuverlässig selektiert, Inspector im **Edit-Modus** dieser gespeicherten Action; Katalog/Explorer/Details/Probleme/Hilfe/Dirty/Undo synchron. Die Action ist **unplatziert**: kein FolderEntry, keine Keypad-Belegung, kein Placebo-Preview. Kurzer deutscher Hinweis dazu in UI/Hilfe.

**Action-Delete**:
- Für die selektierte Action einen gut auffindbaren **Löschen**-Befehl im Inspector oder in der Shell integrieren, eindeutige Action-ID vor Ausführung sichtbar; wenn nur eine FolderEntry selektiert ist, darf Delete nicht versehentlich diese Placement-Struktur verändern.
- Aktuelle Löschbarkeit ermitteln; bei Referenzen/letzter Action klar **deaktivieren mit Erklärung oder einen erklärenden nicht destruktiven Dialog** anzeigen. Eine Bestätigung darf nur bei tatsächlich erlaubter Löschung erscheinen; ID und Anzeigename konkret nennen, Default **Cancel**, keine Bestätigung aus einem vorherigen Popup übernehmen.
- Bei erfolgreicher Löschung: genau ein Session-Commit, gültige Auswahl, keine stale `ActionOffer`-Objekte, kein Inspector-Draft, der auf die gelöschte Action verweist; Undo/Redo/Save/Reload erhalten korrekte Zustände. Keine Löschung des Handlers und keine Folder-Mutation.
- Vor Create/Delete muss ein vorhandener Dirty-Draft (auch ein Create-Draft) mit **Übernehmen / Verwerfen / Abbrechen** behandelt werden. Bei Cancel **absolut keine Mutation oder Selection Change**. Fehlgeschlagenes externes Laden darf einen zuvor zu schützenden Dirty-Draft nicht verlieren.

**Keine Änderung am Legacy-`0.1-draft`-Einstieg**; der neue Command-/Delete-Workflow gehört ausschließlich zur nativen Shell.

## E. Etappe 3 – die beiden P2-Verbesserungen verbindlich umsetzen

**OBS-INSP-001: Formulare lesbarer und kompakter machen.**

- `ActionInspectorWidget`, `ObjectForm` und `RowsEditor` nur soweit umbauen, wie nötig. Allgemein, Handler, Parameter, Parameter-Symbole, Asset-Referenzen, States, Adjustment und EditorControls als **logische einklappbare Gruppen** darstellen. Für Listen prägnante **Einzeilen-Zusammenfassungen** mit Name, Typ/State-Index und ggf. Fehlersymbol; pro Eintrag vollständige Detailfelder ein-/ausklappbar. Nicht benötigte Details nicht dauernd in voller Höhe zeigen.
- Add/Remove/Reorder und alle sieben Control-Typen, Filter, optionale Null-/Nichtgesetzt-Felder und Fehlermeldungen bleiben weiter bedienbar. Bei Validierungsfehler betreffende Gruppe und Zeile öffnen oder unübersehbar kennzeichnen; der Nutzer muss die fehlerhafte Stelle finden können.
- **Kritisch:** Collapse/Expand, Fensterresize, Themen-Fokus, Scrollen oder Öffnen/Schließen anderer Zeilen dürfen **keine** Formulardaten ändern, `ActionDraft` invalidieren oder `session.replace` auslösen. Auch ein ungültiger Draft muss beim Wiederöffnen **unverändert** sein; verschwundene Eingaben sind abnahmeverhindernd.
- Tab-/Keyboard-Navigation, F1 und Screenreader-Labels für dynamische Buttons/Zeilen beibehalten; 150-%-DPI, Windows hell/dunkel, schmal/breit visuell prüfen. Keine neue externe UI-Bibliothek oder QML.

**OBS-INSP-002: Stale-Status proaktiv sichtbar machen.**

- Sobald die Sessionrevision von `draft.base_revision` oder der aktuelle Projekttoken vom Draft-Projekttoken abweicht, ein **deutliches, nicht modales Statusband** direkt im Inspector zeigen, selbst wenn der Benutzer noch kein Apply versucht hat.
- Die Warnung unterscheidet **„Formular geändert, aber noch nicht übernommen“** von **„Formular basiert auf einer veralteten Sessionrevision“**. Bei Stale darf Apply nicht mehr erfolgreich sein, eine Projekt-Save-Aktion darf kein verdecktes Rebase vornehmen. Bestehende Formulareingaben erhalten; verständliche Aktionen **„Entwurf verwerfen / aktuelle Daten neu laden“** und **„Im Entwurf bleiben“**, keine aufdringlichen Loop-Dialoge.
- Auf die schon bestehenden Hostsignale `StudioCoordinator.changed` / `selectionChanged` und Sessionrevision reagiert der Inspector zeitnah, ohne eine neue parallele Revisionsquelle. Veränderungen über Toolbar-Schnellrename, Undo/Redo, anderswo ausgeführten gültigen Sessioncommit, Projektwechsel und externe Dateikonflikte testen. **Nur Save ohne Revisionwechsel darf keinen falschen Stale-Status auslösen.**
- Wenn ein Projektwechsel mit Dirty-Draft bewusst abgebrochen wird, müssen Projekt-/Action-Identität, Originalrevision, Formulardaten und Warnstatus konsistent bleiben. Keine heimliche Übernahme eines Stale-Drafts.
- Ein kleines, von Nutzer ausgelöstes Discard/Refresh setzt den Draft auf die aktuelle Sessionrevision, falls die Action noch existiert; bei gelöschter Action einen erklärten Leer-/Fehlerzustand darstellen. Kein Versuch, alten Draft auf eine andere Action mit gleichem Anzeigenamen umzuhängen.

## F. Etappe 4 – Kontexthilfe, Dokumentation und Qualität

**Kontexthilfe ist Bestandteil dieses AP, nicht ein Folgeprojekt.** Die geprüfte Registry/HelpCoordinator/ContextHelpWidget-Infrastruktur unverändert wiederverwenden. Die bestehende `inspector_topics.de.json` mit **quelleneigenen** deutschen Topics erweitern für Creation, Action-ID, SDK-Typ, bestehender Handler, unplatzierte neue Action, Delete und Folder-Referenzschutz, letzte Action, kompakte Abschnittsbedienung, Stale-Draft und Refresh. Über `NativeHelpBindings` alle aktiven Controls mit F1/FocusIn/Pin/Related erreichen. Keine zweite Help-Registry, keine direkten UI-zu-Help-Widget-Schreibzugriffe; keine sensitiven Benutzereingaben, absoluten Pfade, Tokens oder privaten Diagnosewerte in Help-Facts.

**Architektur- und Komponentenreferenzen zwingend aktualisieren:**
- `docs/architecture/studio/widgets/ActionLifecycle.md` – GEPLANT → tatsächlicher IMPLEMENTIERT-Stand, präzise neue Signale/Hostmethoden und Datenfelder (nur bestätigte, getestete Kanten).
- `docs/architecture/studio/widgets/ActionInspector.md` – neue Create/Edit-Modi, Accordion-Vertrag und proaktive Stale-Anzeige.
- `docs/architecture/studio/widgets/ActionCatalog.md` – freigeschaltete Create-Hostroute, Auswahl- und Filter-Verhalten.
- `docs/architecture/studio/widgets/ContextHelp.md` – neue Topics, Focus/Pin für Creation/Delete.
- `docs/architecture/studio/README.md`, `00-Gesamtkarte.md`, `01-Daten-und-Transaktionen.md`, `02-StudioCoordinator.md`, `03-Geplante-Editoren.md`, `04-Verbindungsregister.md`.
- `work/planning/README.md` – Status `READY_FOR_REVIEW`, kein vorgetäuschtes APPROVED.
- Neue Host-Kanten **ab V-63**, jede nur dann mit IMPLEMENTIERT, wenn tatsächlicher Codepfad, Signal-/Methodenvertrag, Datenpayload, Guard und spezifischer bestandener Integrationstest genannt werden. Keine Umnummerierung der bestehenden V-01–V-62. Neue UX-Funktionen ohne Kante als Widgetverhalten dokumentieren, keine erfundenen V-IDs.

**Coverage-Register** mit konkreten UI-Objekten/Topics/Testfunktionen und nachgewiesenem Status, nicht nur Gesamtzahl. Fehlende oder deaktivierte Funktionen ausdrücklich kennzeichnen.

## G. Erlaubte und verbotene Änderungen

**NEUE Produktdateien:** `src/studio/action_inspector/lifecycle.py` und bei Bedarf sehr kleine Qt-Teilmódüle innerhalb `src/studio/action_inspector/` (keine anderen neuen produktiven Domänen). Vollständige Lifecycle-Verträge innerhalb `src/studio/action_inspector/` dokumentieren.

**Minimal editierbar:** `src/studio/action_inspector/{draft,widget,__init__}.py`, `src/studio/native_shell/{coordinator,window,help_bindings}.py`, `src/studio/context_help/resources/inspector_topics.de.json`. Weitere Dateien nur nach nachgewiesener Notwendigkeit und im Schlussbericht mit Scopeabweichung markieren.

**Neue Tests (exakte Zielpfade):**
- `tests/test_action_lifecycle_mutations.py`
- `tests/test_action_lifecycle_widget.py`
- `tests/test_action_lifecycle_integration.py`
- `tests/test_action_inspector_ux.py`
- `tools/run_action_lifecycle_lab.py` mit `--smoke` und `--evidence <dir>`.

**Bestehende Tests:** Änderungen nur dort, wo die nun absichtlich implementierte Create-Verbindung und kompaktere Struktur die frühere **bewusst gesperrte** Funktion oder konkrete UI-Assertions ändern. Auf keinen Fall bestehende Tests deaktivieren/entfernen, um Regressionen zu verstecken. Vorherige 963 Tests müssen weiterhin fachlich gelten. Neue Negativfälle ausdrücklich **zusätzlich** abdecken.

**Nicht verändern:** `src/studio/app.py` (Legacy), `src/studio/native_session.py` (Writer/API), `src/adapters/logitech/native.py` (SDK-Parser), `src/core/ids.py`, `schemas/`, `src/studio/native_ict_binding.py`, wiederverwendbare Widgetimplementierungen `src/studio/action_catalog/widget.py`, `src/studio/native_project_explorer/widget.py`, `src/studio/problems_panel/widget.py`, `src/studio/keypad_preview/widget.py`, ursprüngliche Hilfe-Kernklassen, `src/runtime/`, `src/core/`, Logitech-/Service-/Profil-Dateien und frühere Abnahmeakten. Keine externen SDK-Installationen, keine Gerätebefehle, keine kostenpflichtigen Tools.

**Hinweis:** Der gesondert dokumentierte ältere Hinweis `OBS-002-01` (doppelte selectionChanged-Emission bei direkter Aktivierung) ist **nicht** eine der beiden AP-INSP-001-UX-Aufgaben. Keine allgemeine Signalarchitektur-Überarbeitung. Falls der vorhandene Fehler Create-/Delete-Selection konkret gefährdet, kleinsten Fix mit reproduzierendem Test separat und als Scopeausnahme dokumentieren.


## H. Abnahmefähige End-to-End-Tests (verpflichtend)

Alle Tests gegen echte `logitech-native-1`-Snapshots mit dem vorhandenen Parser, UI über PySide6 auf echter Windows-Qt-Plattform. Tests und Lab **nur mit temporären Kopien** des SDK-Beispiels; Originaldateien, bisherige Userprofile, Plugin-Service und echte Geräte bleiben unverändert.

**H1 – Create in allen SDK-Typen:**
1. Für `PluginDynamicCommand`, `PluginMultistateDynamicCommand`, `PluginDynamicAdjustment` und `ActionEditorCommand` jeweils eine neue Action über die echte GUI anlegen, mindestens ein Common- und ein typspezifisches Feld bearbeiten, Apply, Undo, Redo, Save, Datei erneut mit `NativeProjectSession.load` lesen.
2. Jede neue ID eindeutig, vor Apply editierbar, danach readonly, gültig gemäß `is_valid_id`. Die neuen Actions sind **unplatziert** (Folderlisten und Placement-IDs byte-/wertgleich), aber im Katalog und Explorer verfügbar.
3. Wiederholtes Klicken auf Apply erzeugt nicht doppelte Actions/Historyeinträge. No-op/Cancel/ungültiger Draft ändert weder Sessionrevision noch Datei.
4. Doppelte ID, ungültige ID, fehlender Handler, leerer Name, ungültiges Toggle-/State-/EditorControl-Schema verweigern Create, erhalten Nutzereingaben und zeigen Feldfehler.

**H2 – referenzsicheres Delete:**
1. Jede im Originalbeispiel platzierte Action kann wegen `folders[*].entries[*].action`-Referenz **nicht** gelöscht werden; die UI erklärt Anzahl und passende Folder-/Placement-IDs. Nach Fehlversuch unveränderte Session/History/Datei.
2. Eine selbst neu angelegte, **unplatzierte** Action lässt sich nach expliziter Bestätigung löschen. Vor der Löschung offene Formularentwürfe sicher behandeln (Cancel/Discard/Apply). Undo/Redo/Save/Reload reproduzieren exakte vorher/nachher-Snapshots.
3. Die letzte Action wird durch das aktuelle Parserminimum geschützt, auch wenn sie unplatziert ist. Handler werden nie automatisch gelöscht, alte Folder-/Placement-Daten bleiben unverändert.
4. Externe Dateiveränderung, veraltete Revision, verlorene Action-ID, vorherige Auswahl mit gleicher Display-Name-Kollision, Quick Rename während des Drafts: fail-closed, keine fehlgeleitete Löschung.

**H3 – Draft-/Session-Lebenszyklus:**
1. Bei offenem Create- oder Edit-Draft Auswahlwechsel, Open, Reload, Close, Undo/Redo, Save, Create und Delete je mit **Übernehmen / Verwerfen / Abbrechen** prüfen. Cancel erhält Projekt, Selektion und sämtliche Formularwerte.
2. Ein fehlgeschlagenes Öffnen einer neuen Projektdatei darf den alten, noch nicht wirksam verworfenen Draft nicht zerstören; bei bestätigter Verwerfung zuerst Laden/Validieren und erst bei Erfolg den Wechsel finalisieren.
3. Simulierter paralleler Sessioncommit bei offenem Edit-/Create-Draft zeigt das Stale-Warnband **vor Apply**, bewahrt alle Felder, schreibt nicht und erzeugt keine Modal-Loop. Ein anschließender expliziter Discard/Refresh zeigt aktuellen Inhalt. Ein bloßes Save ohne Revisionswechsel erzeugt keinen falschen Stale-Status.

**H4 – kompakter Inspector und Kontexthilfe:**
1. Akkordeon-Abschnitte für alle vier SDK-Typen; Zeilen-Zusammenfassungen für Parameter, States und EditorControls; alle sieben unterstützten Control-Typen und File-Selector-Filter weiterhin bedienbar.
2. Collapse/Expand und Fenstergrößenwechsel verändern **keine** Draftdaten, Formatierungen oder Sessionrevision; mit invaliden Eingaben wiederholen. Fehler sollen Zielgruppe/Zeile sichtbar machen.
3. F1/Pin/Related für Create, Create-ID/Typ, Delete/Referenzkonflikte, Stale-Warnung, Accordion und dynamische Zeilen; eindeutige Registry-Owner, keine doppelten Topics.
4. Windows-Evidenz bei 150 % DPI: helle breite Ansicht, dunkle schmale Ansicht, mindestens eine neu angelegte Action je SDK-Typ, kompakte Liste aufgeklappt/zugeklappt, Löschverweigerung wegen Folder-Referenz, erfolgreiche unreferenzierte Löschung, Stale-Warnung und Draft-Verlustschutz. Keine Offscreenaufnahme als Windows-Screenshot ausgeben.
5. Ein eigener Create→Edit→Delete-End-to-End-Lauf **ohne originalen Projektdatei-Write**, mit tatsächlichem Qt-Klick auf `+ Neue Aktion` und Delete-Bestätigung; die zwei transaktionalen Commits und Historie separat kontrollieren.

**Pflichtbefehle aus dem Projektroot; mit Exitcode und Logdatei protokollieren:**

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m unittest discover -s tests -p test_action_lifecycle_mutations.py -v
python -m unittest discover -s tests -p test_action_lifecycle_widget.py -v
python -m unittest discover -s tests -p test_action_lifecycle_integration.py -v
python -m unittest discover -s tests -p test_action_inspector_ux.py -v
python -m unittest discover -s tests -q
python tools/run_action_lifecycle_lab.py --smoke
python tools/check_links.py
```

Für den tatsächlichen Windows-GUI-Nachweis zusätzlich `QT_QPA_PLATFORM=windows` und `python tools/run_action_lifecycle_lab.py --evidence work/action-inspector/AP-INSP-002/screenshots`. Laufende Programm-/Agentenprozesse nicht mit dem automatischen Testlauf konkurrieren lassen.

**Bestehende 963 Baseline-Tests** müssen weiter inhaltlich abgedeckt sein. Wo ein Test das frühere bewusst deaktivierte Create-Feature erwartet, die Änderung nachvollziehbar belegen und durch mindestens gleichwertige neue GUI-Tests ersetzen; keine pauschale Löschung alter Tests.

## I. Dokumentation, technische Grenzen und Abschlussstatus

- `work/action-inspector/AP-INSP-002/README.md` wird zum Einstieg in die vollständige Arbeitsakte. Ursprünglichen unveränderten Auftrag, die Laufchronik, `scope-after.json` mit SHA-256-Delta (inklusive expliziter Reviewer-geschützter Dateien), Testlogs, Exitcodes, Screenshotmanifest, Help-Coverage, V-ID-Kanten und finalen Abschlussbericht ablegen.
- Testfälle müssen dokumentieren, welche **echten SDK-Parser-/Folder-/Session-Invarianten** sie nachweisen, nicht nur, dass eine Funktion existiert.
- In den Studio-Architekturdokumenten IST und SOLL sorgfältig unterscheiden. Neue V-IDs nur implementiert nennen, wenn tatsächliche Sender/Empfänger/Signal/API/Payload und konkrete Testfunktion zugeordnet sind.
- Neuen Autorentext **auf Deutsch**, konkrete Beispiele ohne erfundene Logitech-SDK-Funktionen und ohne Nutzung von Drittanbieter-KI-/Cloud-Abhängigkeiten.
- Eine Undo/Redo- oder Speicherfunktion ist nur dann abgenommen, wenn dieselbe NativeProjectSession mit unverändertem ursprünglichen Dateipfad verwendet wird und der Write ausschließlich bei ausdrücklichem Save erfolgt.
- Wenn ein isolierter Codepfad **außerhalb des ausdrücklich erlaubten Schreibbereichs** zwingend geändert werden müsste, die Notwendigkeit reproduzierbar belegen; eine externe Blockade nur als BLOCKED behandeln, wenn keine technisch zulässige Korrektur innerhalb des Scopes möglich ist. Keine unbefugten Profile/Service/HID-Schreibzugriffe.
- Zum Ende Status **READY_FOR_REVIEW**, ausdrücklich **keine Selbstfreigabe als APPROVED**. Bericht mit neuer Testanzahl, Scope-Differenzen, Fehler-/Restrisikoregister, Architektur-/Help-ID-Register sowie genauer Beschränkung „referenzierte Action nicht löschen“. Unabhängige Abnahme durch den Auftraggeber folgt separat.
- **Keine neue Agentensession starten, keine Monitoring-Automation anlegen, kein späterer Hintergrundauftrag.** Der Nutzer beauftragt den Agenten selbst.

**Definition of Done:** Alle vier SDK-Typen **neu erstellen und sofort mit demselben Inspector bearbeiten**, unreferenzierte Actions **bestätigt löschen**, referenzierte/letzte Action **fail-closed ablehnen**, Roundtrip/Undo/Redo, kompakter Inspector, frühzeitige Stale-Warnung, eine zentrale Kontexthilfe, 100 % nachgewiesene neue aktive Kanten und grüne gesamte Regression.
