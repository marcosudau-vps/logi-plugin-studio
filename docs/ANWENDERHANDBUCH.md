# Logitech Plugin Studio – Anwenderhandbuch (Release-Kandidat 1.0.0-rc2)

Dieses Handbuch beschreibt die Arbeit mit dem Studio, ohne dass interne Projektdateien von Hand bearbeitet werden müssen.

## 1. Voraussetzungen, Fassungen und Start

| Wofür | Was wird benötigt | Mitgeliefert? |
|---|---|---|
| Studio bedienen, Projekte bearbeiten, Symbole gestalten | nichts weiter | ja (Setup und Portable) |
| Plugins bauen | **.NET SDK 8 oder neuer** (kostenlos von Microsoft) und **Logi Options+** (liefert `PluginApi.dll`) | nein – wird lokal erkannt |
| Plugins installieren und am Gerät nutzen | Logi Options+ mit laufendem Logi Plugin Service | nein |
| Python-Handler und Shared-Plugins ausführen | nichts: jedes gebaute Plugin enthält seine eigene geprüfte Host-Laufzeit | ja |

Es gibt zwei gleichwertige Fassungen mit identischem Programminhalt:

* **Setup** – `LogiPluginStudio-Setup-1.0.0-rc2.exe` installiert ohne Administratorrechte nach `%LOCALAPPDATA%\Programs\LogiPluginStudio` (anderer Ordner wählbar), legt einen Startmenüeintrag (optional Desktop) und einen Eintrag unter „Apps & Features“ an. Eine neuere Version wird einfach darüber installiert; dieselbe Version erneut installieren repariert die Programmdateien.
* **Portable** – `LogiPluginStudio-Portable-1.0.0-rc2.zip` entpacken und `LogiPluginStudio.exe` starten. Kein Setup, keine Adminrechte. Der Ordner darf jederzeit verschoben werden; das Studio ermittelt seinen Ort beim Start selbst.

Beide Programme sind nicht digital signiert; Windows SmartScreen kann deshalb beim ersten Start bzw. bei der Installation warnen („Weitere Informationen“ → „Trotzdem ausführen“).

`Diagnose.cmd` (bzw. Startmenü „Diagnose“) prüft alle Voraussetzungen, zeigt Version, Fassung, Programmordner sowie die Host-Laufzeit installierter Plugins. `Selbsttest.cmd` baut probeweise ein natives und ein Shared-Testplugin in einem temporären Ordner (keine Installation).

**Entwicklerfassung:** `python tools/run_studio.py --native [projekt.json]` (Python 3.12 + `requirements-dev.txt`).

### Wo liegen welche Daten?

| Daten | Ort | Bei Studio-Deinstallation/Löschen des Portable-Ordners |
|---|---|---|
| Programmdateien | Setup-Zielordner bzw. Portable-Ordner | entfernt |
| Ihre Projekte, Symbole, `.vfolders.json` | dort, wo Sie sie speichern | bleiben |
| Builds, Pakete, Installationsbelege | `%LOCALAPPDATA%\LogiPluginStudio\builds` | bleiben |
| Pairing-/Berechtigungsdaten (Schlüssel DPAPI-geschützt), Peer-Status, Shared-Host-Protokolle | `%LOCALAPPDATA%\LogiPluginStudio\SharedFolders` | bleiben |
| Protokolle der Plugin-Hosts | `%LOCALAPPDATA%\LogiPluginStudio\HostLogs` | bleiben |
| Gemerkter Plugin-Typ, Ablaufschritt, Handlerdatei und Gerätetest je Projekt; Liste deaktivierter Plugins | `%LOCALAPPDATA%\LogiPluginStudio\settings` | bleiben |
| Sicherungsbelege deaktivierter Plugins (Wartung) | `%LOCALAPPDATA%\LogiPluginStudio\maintenance-receipts` | bleiben |
| Installierte Plugins samt eigener Host-Laufzeit | `%LOCALAPPDATA%\Logi\LogiPluginService\Plugins\<Name>` | bleiben und laufen weiter |

Die Portable-Fassung ist deshalb **nicht rückstandsfrei**: Die Benutzerdaten oben bleiben erhalten, bis Sie sie selbst löschen. Weder Setup noch Studio schreiben in den Programmordner.

## 2. Der geführte Ablauf

Das Studio führt in **sieben Schritten** vom leeren Projekt bis zur getesteten Taste am Gerät:

**1 Projekt → 2 Handler → 3 Aktionen → 4 Darstellung → 5 Belegung → 6 Prüfen und Bauen → 7 Installieren und Testen**

* **Schrittleiste (oben):** zeigt jeden Schritt mit Zeichen und Text: ✔ erfüllt, ○ offen, ! Hinweis, ✖ Fehler, ↻ veraltet, – optional, 🔒 gesperrt. Ein Schritt wird frei, sobald alle vorherigen abgeschlossen sind; zurück geht es immer.
* **Nächster Handgriff:** Die Zeile unter der Schrittleiste sagt, was jetzt zu tun ist. **Weiter →** ist erst möglich, wenn der Schritt abgeschlossen ist. **Mehr dazu** öffnet die ausführliche Anleitung des Schritts in der Hilfe.
* **Checkliste:** listet die Kriterien des aktuellen Schritts. Doppelklick (oder Eingabetaste) springt zur betroffenen Stelle bzw. führt den passenden Befehl aus (z. B. „Alles speichern“, „Bauen“). Offene Punkte stehen zusätzlich in der Problemliste.
* **Je Schritt nur das Nötige:** Registerkarten, Seitenbereiche und Werkzeuge, die im aktuellen Schritt nichts zu suchen haben, sind ausgeblendet.
* **Alles speichern** (Strg+S, im Expertenmodus Strg+Umschalt+S, oder Symbol in der Werkzeugleiste) schreibt das Projekt und die Ordner/Belegung in ihre Dateien. Der Build verwendet nur den gespeicherten Stand.
* **Expertenmodus** (Häkchen rechts in der Schrittleiste oder Menü *Ablauf*): alle Bereiche sind gleichzeitig erreichbar, der Schrittstatus bleibt sichtbar, sperrt aber nichts. Die Wahl wird gemerkt und ändert das Projekt nicht.
* **Menüleiste:** *Datei* (Neu, Öffnen, Speichern, Beenden), *Bearbeiten* (Rückgängig, Wiederholen, Anzeigename), *Ablauf* (Schritte, Expertenmodus), *Werkzeuge* (SymbolDesigner, Bauen, Wartung), *Hilfe*.
* Der aktive Schritt wird je Projekt gemerkt; beim nächsten Öffnen geht es dort weiter.

## 3. Schritt 1 – Projekt

* **Neues Projekt …** (Strg+N): Plugin-ID (z. B. `meinname.meinplugin`), Anzeigename und Speicherort angeben. Es entsteht ein gültiges Projekt mit einem Befehl, einem Schalter und einem SDK-Ordner. Die Plugin-ID ist die dauerhafte Kennung in Logi Options+ und sollte später nicht mehr geändert werden.
* **Vorhandenes Projekt öffnen …** (Strg+O): vorhandenes `logitech-native-1`-Projekt öffnen.
* Ungespeicherte Änderungen werden beim Öffnen eines anderen Projekts und beim Schließen abgefragt.

## 4. Schritt 2 – Handler

Ein **Handler** ist die Stelle in deinem Python-Code, die aufgerufen wird, wenn eine Aktion ausgelöst wird. Registerkarte **Handler**:

* **+ Neuer Handler …**, **Umbenennen …** (stellt alle Aktionen mit um), **Löschen …** (nur Handler, die keine Aktion verwendet; der letzte Handler bleibt).
* **Handlerdatei aus Vorlage erzeugen** legt `<Projektname>_handlers.py` neben dem Projekt an. Sie registriert jeden verwendeten Handler und ist sofort lauffähig; den eigentlichen Code ergänzt du in einem Editor deiner Wahl. Eine vorhandene Datei wird nie überschrieben. Alternativ **Vorhandene Datei auswählen …**.
* Das Studio führt die Datei nie aus, sondern prüft sie nur: Sie muss `register(host)` enthalten. Fehlt die Registrierung eines verwendeten Handlers, zeigt die Registerkarte den einzufügenden Code. Registriert die Datei einen Handler, den keine Aktion verwendet, würde das Plugin nicht starten – dann diese Zeilen entfernen.

Abgeschlossen: mindestens ein Handler, Handlerdatei zugeordnet und gültig.

## 5. Schritt 3 – Aktionen

* Links Projektübersicht und Aktionskatalog. **+ Neue Aktion** legt eine Aktion an; Auswahl oder Doppelklick öffnet den **Aktionsinspektor**.
* Aktionstypen: Befehl (`PluginDynamicCommand`), Schalter mit Zuständen (`PluginMultistateDynamicCommand`), Regler (`PluginDynamicAdjustment`), Aktion mit Einstelldialog (`ActionEditorCommand`). Parameter, Zustände, Reset, Editor-Felder und der zuständige Handler werden im Inspektor gepflegt. **Übernehmen** schreibt den Entwurf ins Projekt, **Alles speichern** in die Datei.
* Registerkarte **Zustände**: SDK-Zustände je Aktion in Klartext (z. B. „0 Aus, 1 An“, Wechsel „umschalten“). Werte, die dein Python-Code selbst führt, gehören nicht zum Projekt und erscheinen dort nicht.

Abgeschlossen: mindestens eine Aktion, jede mit gültigem Handler, kein offener Entwurf.

## 6. Schritt 4 – Darstellung (optional)

Registerkarte **Symbole**: je Aktion, ob ein eigenes Symbol, ein Bild oder die Standardvorlage verwendet wird, und welche Dateien fehlen. **Im SymbolDesigner bearbeiten …** (oder Doppelklick, F2, *Werkzeuge → SymbolDesigner*) öffnet den Designer: Hintergrund, Text, Bild/Symbol und Layout. Gespeichert wird als SDK-Icon-Template (`.ict`) im Projektordner; das Studio übernimmt die Verknüpfung im Projekt. Ohne eigenes Symbol zeigt das Gerät den Anzeigenamen. Fehlende Bilddateien sind ein Hinweis, keine Sperre.

## 7. Schritt 5 – Belegung (optional)

* Registerkarte **Keypad**: Tastenvorschau des virtuellen Ordners. „Bearbeiten“ ist eingeschaltet; Aktionen aus dem Aktionskatalog am nächsten freien Platz ablegen, verschieben, kopieren oder entfernen. Die Vorschau ist eine Autorenansicht; die echte Darstellung bestimmt Logi Options+.
* Registerkarte **Virtuelle Ordner**: Ordner, Unterordner, Links, Seiten und Aktionsplatzierungen anlegen. **Externe Aktionsreferenz …** fügt eine Aktion eines anderen eigenen Plugins ein (Format `plugin.id::action.id`).
* Im geführten Ablauf wird die Belegung nur in den virtuellen Ordnern bearbeitet. Die SDK-Ordner des Projekts zeigt der Expertenmodus an.
* Dieser Schritt ist freiwillig: Aktionen lassen sich auch einzeln in Logi Options+ auf Tasten legen.

Abgeschlossen: keine Platzierung verweist auf eine fehlende Aktion, Ordner gespeichert.

## 8. Schritt 6 – Prüfen und Bauen

Registerkarte **Plugin-Build**. Der Build startet im geführten Ablauf nur, wenn alles gespeichert ist und die Problemliste keine Fehler enthält.

| Plugin-Typ | Wann verwenden |
|---|---|
| **Kompatibel (Standard)** | bisheriges Verhalten; SDK-Actions plus virtuelle Ordner aus der `.vfolders.json` |
| **Nativ – reines SDK-Plugin** | nur originale Logitech-SDK-Funktionen und SDK-Ordner, keine Folder-/Peer-Runtime (virtuelle Ordner werden nicht ausgeliefert) |
| **Shared DynamicFolder** | virtuelle Ordner mit Actions **anderer eigener Plugins**; diese werden beim jeweiligen Owner-Plugin ausgeführt |

Der gewählte Plugin-Typ wird **je Projekt benutzerlokal gemerkt** und beim nächsten Öffnen wiederhergestellt. Er wird nicht in die Projektdatei geschrieben. Ein verschobenes oder kopiertes Projekt beginnt wieder mit „Kompatibel“.

Das Feld **Python-Handler** zeigt die in Schritt 2 zugeordnete Handlerdatei. **Voraussetzungen prüfen** zeigt fehlende Bausteine. **SDK-Plugin bauen** erzeugt Quellen, kompiliert gegen die lokale `PluginApi.dll` und erstellt ein geprüftes Paket mit allen Icons, Symbolen, Icon-Templates und der **pluginlokalen Host-Laufzeit** (`bin\hostruntime-<id>`, rund 25 MB, jede Datei mit SHA-256 geprüft). **Build abbrechen** stoppt nach dem laufenden Schritt. Das Projekt wird durch den Build nie verändert.

Ändert sich danach etwas am gespeicherten Projekt, an den Ordnern, an der Handlerdatei oder am Plugin-Typ, gilt der Build als **veraltet** (↻) und muss wiederholt werden.

## 9. Schritt 7 – Installieren und Testen

Registerkarte **Installation** (nach erfolgreichem Build); die Statuswerte erscheinen auf Deutsch (der technische Code steht im Tooltip):

1. **Plan anzeigen** – Probelauf: Art der Installation, Ziel, Neuinstallation oder Aktualisierung, Host-Laufzeit, gesicherte Vorversion.
2. **Installieren / Aktualisieren …** – nach Bestätigung wird das geprüfte Paket als **Verzeichnis-Installation** in den Studio-eigenen Ordner `Plugins\<Pluginname>` kopiert (die vorherige eigene Version wird vorher gesichert), genau dieses Plugin wird neu geladen und der Ladezustand geprüft. Schlägt das Laden fehl, wird automatisch auf den vorherigen Zustand zurückgerollt. Ein Neustart von Logi Options+ ist nicht nötig.
3. **Ladezustand prüfen** – Plugin-Service-Protokoll und Verbindung zum Python-Host.
4. **In Logi Options+ zuweisen:** Logi Options+ öffnen, das Gerät wählen, das Plugin in der Aktionsliste suchen und eine Aktion auf eine Taste ziehen. Das Studio verändert keine Profile.
5. **Am Gerät testen:** Taste drücken. Hat sie wie erwartet reagiert, in der Checkliste **„Am Gerät getestet und bestätigt“** doppelklicken und bestätigen. Damit ist der Ablauf abgeschlossen.

**Test-Host starten** startet den Host der Build-Ausgabe zum Testen **vor** der Installation. Installierte Plugins starten ihren Host selbst und laufen **ohne geöffnetes Studio** – auch wenn der Studio-Ordner verschoben, aktualisiert oder deinstalliert wird.
Aktualisieren = neu bauen und erneut installieren; die eigenen Dateien werden einzeln atomar ersetzt, die Vorversion bleibt im Beleg für ein Rollback erhalten.

Der frühere **Entwicklungs-Link** (`<plugin-id>.link`) wird nur noch für Altinstallationen angezeigt; der Logi Plugin Service liest solche Links erst beim nächsten Dienststart.

## 10. Rollback und Entfernen

* **Zurückrollen …** stellt die exakte vorherige eigene Version wieder her (bzw. entfernt eine Neuinstallation) und lädt das Plugin neu.
* **Deinstallieren …** entfernt nur die eigenen Plugindateien einschließlich der pluginlokalen Host-Laufzeit (gesichert im Beleg); **Deinstallation rückgängig** stellt sie wieder her. Vom Plugin selbst geschriebene Daten (z. B. `callbacks.jsonl`) bleiben.
* **Wichtig:** Tastenbelegungen des Plugins in Ihrem Logi-Options+-Profil werden vom Studio nicht verändert. Sie können nach der Deinstallation auf dem Keypad sichtbar bleiben und müssen dann in Logi Options+ entfernt werden.
* **Installierte Plugins** listet Plugin-Verzeichnisse und Entwicklungs-Links samt Zustand der Host-Laufzeit; fremde Plugins werden nur angezeigt und niemals verändert.

## 11. Wartung

*Werkzeuge → Wartung …* oder **Wartung …** auf der Startseite – auch ohne geöffnetes Projekt:

* Liste aller Plugins im Pluginordner des Logi Plugin Service mit Zustand (aktiv, deaktiviert, fremd), Art und Host-Laufzeit. Plugins anderer Hersteller werden nur angezeigt und nie verändert.
* **Plugin neu laden** lädt nur das gewählte eigene Plugin neu. **Protokoll anzeigen** zeigt die Einträge des Logi Plugin Service zu diesem Plugin aus den letzten 24 Stunden.
* **Deaktivieren …** entfernt ein eigenes Plugin mit einer Sicherung; **Reaktivieren** stellt es daraus unverändert wieder her und lädt es neu. Tastenbelegungen in Logi Options+ bleiben dabei unberührt.
* **Voraussetzungen prüfen** wie im Build-Schritt.
* Ein Neustart des gesamten Logi Plugin Service wird bewusst nicht angeboten, weil er alle Plugins und Geräte betrifft. Falls nötig, Logi Options+ selbst beenden und neu starten.

## 12. Shared-Plugins: Pairing und Berechtigungen

Die Registerkarte **Shared-Peers** erscheint im geführten Ablauf in Schritt 7, wenn als Plugin-Typ „Shared DynamicFolder“ gewählt ist (im Expertenmodus immer).



1. Zwei eigene Plugins wählen (Plugin A / Plugin B) → **Paaren**. Paaren erzeugt einen geheimen Schlüssel für genau dieses Paar, erlaubt aber **noch keine** fremde Ausführung.
2. Freigabe als Owner (das geöffnete Projekt): Empfänger, Action/Parameter oder Ordner und erlaubte Operation (**Ausführen**, **Drehen**) wählen → **Freigeben**. Ordnerfreigaben sind nur lesend.
3. **Widerrufen** entfernt eine markierte Freigabe; **Entpaaren …** entfernt Paar und alle Freigaben; **Neu verschlüsseln** ersetzt den Schlüssel (auch die Abhilfe, wenn ein Schlüssel nicht mehr entschlüsselt werden kann).
4. **Verbindungsdiagnose** zeigt je Plugin: online, SDK verbunden, Policy gültig, Peers verbunden/getrennt. Die Spalte **Schlüsselablage** zeigt „DPAPI-geschützt“.
5. Änderungen wirken beim nächsten Plugin-Start: **Plugin neu laden (Resync)**.

Schlüssel liegen nur in `%LOCALAPPDATA%\LogiPluginStudio\SharedFolders\config`, sind mit Windows-DPAPI an Ihr Windows-Konto gebunden und stehen nie im Projekt, Paket oder Protokoll. Ältere Klartext-Schlüssel werden beim Öffnen des Tabs automatisch geschützt – außer für Plugins, die noch mit einer Studio-Version vor 1.0 gebaut und installiert sind (diese lesen nur Klartext): erst neu bauen und aktualisieren. Fällt ein Peer aus, bleiben lokale Actions nutzbar; fremde Einträge erscheinen als „[unavailable]“ und kehren nach dem Neustart automatisch zurück.

## 13. Fehler diagnostizieren

| Symptom | Ursache / Lösung |
|---|---|
| „Voraussetzung fehlt: PluginApi.dll …“ | Logi Options+ installieren bzw. reparieren |
| „.NET SDK … fehlt“ | .NET SDK 8+ installieren, Studio neu starten |
| Ein Schritt bleibt gesperrt | Die Checkliste des vorherigen Schritts zeigt den offenen Punkt; Doppelklick führt zur Stelle |
| „Build verweigert: Alles gespeichert …“ | *Alles speichern* wählen; ein offener Entwurf im Aktionsinspektor muss erst übernommen oder verworfen werden |
| Plugin geladen = `ALREADY_LOADED_RELOAD_REQUIRED` | Plugin war schon geladen; „Ladezustand prüfen“ nach kurzem Warten oder Plugin neu laden |
| Plugin geladen = `LOAD_FAILED` | Details im Installations-Log; automatisches Rollback ist erfolgt |
| Verbindung = `HOST_NOT_RUNNING` | Plugin neu laden; Wartung bzw. Inventar „Installierte Plugins“ und Hostprotokoll `%LOCALAPPDATA%\LogiPluginStudio\HostLogs\<plugin>.log` prüfen |
| Inventar: „Laufzeit BESCHÄDIGT – neu installieren“ | Eine Datei der pluginlokalen Laufzeit wurde verändert; das Plugin startet seinen Host aus Sicherheitsgründen nicht. Erneut installieren |
| Inventar: „ALTER absoluter Hostpfad“ | Plugin wurde vor 1.0 gebaut und hängt vom Studio-Ordner ab: im Studio neu bauen und aktualisieren (Migration auf pluginlokale Laufzeit) |
| Fremde Action bleibt „[unavailable]“ | Owner nicht gestartet, nicht gepaart oder Action nicht freigegeben (Tab Shared-Peers → Verbindungsdiagnose); Hostprotokoll `%LOCALAPPDATA%\LogiPluginStudio\SharedFolders\logs\<plugin>.log` |
| „Geschützter Schlüssel … kann nicht entschlüsselt werden“ | Anderes Windows-Konto oder beschädigt: Paar „Neu verschlüsseln“ |

`Diagnose.cmd` schreibt einen Bericht nach `%TEMP%\LogiPluginStudio-diagnose.txt`.

## 14. Automatisierung (optional)

Für Skripte und Prüfabläufe bietet `LogiPluginStudio.exe` dieselben Abläufe wie die Oberfläche:

```
LogiPluginStudio.exe --build <projekt.json> --mode native|compatible|shared [--handler datei.py] --out bericht.json
LogiPluginStudio.exe --install <paketordner> --confirm <plugin-id> --out bericht.json
LogiPluginStudio.exe --uninstall <plugin-id> --confirm <plugin-id> --name <SdkName> --out bericht.json
LogiPluginStudio.exe --diagnose --out bericht.txt
```

Installation und Deinstallation verlangen die ausdrückliche Bestätigung der Plugin-ID und arbeiten nur mit Studio-eigenen Plugins.
