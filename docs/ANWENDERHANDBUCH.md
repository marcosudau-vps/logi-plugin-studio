# Logitech Plugin Studio – Anwenderhandbuch (Release-Kandidat 1.0.0-rc1)

Dieses Handbuch beschreibt die Arbeit mit dem Studio, ohne dass interne Projektdateien von Hand bearbeitet werden müssen.

## 1. Voraussetzungen, Fassungen und Start

| Wofür | Was wird benötigt | Mitgeliefert? |
|---|---|---|
| Studio bedienen, Projekte bearbeiten, Symbole gestalten | nichts weiter | ja (Setup und Portable) |
| Plugins bauen | **.NET SDK 8 oder neuer** (kostenlos von Microsoft) und **Logi Options+** (liefert `PluginApi.dll`) | nein – wird lokal erkannt |
| Plugins installieren und am Gerät nutzen | Logi Options+ mit laufendem Logi Plugin Service | nein |
| Python-Handler und Shared-Plugins ausführen | nichts: jedes gebaute Plugin enthält seine eigene geprüfte Host-Laufzeit | ja |

Es gibt zwei gleichwertige Fassungen mit identischem Programminhalt:

* **Setup** – `LogiPluginStudio-Setup-1.0.0-rc1.exe` installiert ohne Administratorrechte nach `%LOCALAPPDATA%\Programs\LogiPluginStudio` (anderer Ordner wählbar), legt einen Startmenüeintrag (optional Desktop) und einen Eintrag unter „Apps & Features“ an. Eine neuere Version wird einfach darüber installiert; dieselbe Version erneut installieren repariert die Programmdateien.
* **Portable** – `LogiPluginStudio-Portable-1.0.0-rc1.zip` entpacken und `LogiPluginStudio.exe` starten. Kein Setup, keine Adminrechte. Der Ordner darf jederzeit verschoben werden; das Studio ermittelt seinen Ort beim Start selbst.

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
| Gemerkter Plugin-Typ je Projekt | `%LOCALAPPDATA%\LogiPluginStudio\settings` | bleiben |
| Installierte Plugins samt eigener Host-Laufzeit | `%LOCALAPPDATA%\Logi\LogiPluginService\Plugins\<Name>` | bleiben und laufen weiter |

Die Portable-Fassung ist deshalb **nicht rückstandsfrei**: Die Benutzerdaten oben bleiben erhalten, bis Sie sie selbst löschen. Weder Setup noch Studio schreiben in den Programmordner.

## 2. Projekt erstellen oder öffnen

* **Neues Projekt …** (Strg+N): Plugin-ID (z. B. `meinname.meinplugin`), Anzeigename und Speicherort angeben. Es entsteht ein gültiges SDK-natives Projekt mit einem Befehl, einem Schalter und einem SDK-Ordner.
* **Nativ öffnen** (Strg+O): vorhandenes `logitech-native-1`-Projekt öffnen.
* **Natives Projekt speichern** (Strg+S) speichert das Projekt; **Extension speichern** speichert die virtuellen Ordner (`<projekt>.vfolders.json`). Beide werden getrennt gespeichert; ungespeicherte Änderungen werden beim Schließen abgefragt.

## 3. Actions bearbeiten

* Links die Projektübersicht und den Aktionskatalog verwenden; Doppelklick öffnet den **Aktionsinspektor**.
* SDK-Actiontypen: Befehl (`PluginDynamicCommand`), Mehrzustand (`PluginMultistateDynamicCommand`), Einstellung/Drehregler (`PluginDynamicAdjustment`), Action-Editor (`ActionEditorCommand`). Parameter, Zustände, Reset und Editor-Felder werden im Inspektor gepflegt.
* **Anzeigename**, **Rückgängig/Wiederholen** und **Neu laden** stehen in der Werkzeugleiste.

## 4. KeypadPreview und virtuelle Ordner

* Tab **Keypad**: zeigt die SDK-nahe Tastenvorschau (Seiten, Ordner, Zurück). Freie Tasten können direkt belegt werden. Die Vorschau ist eine Autorenansicht; die echte Darstellung bestimmt Logi Options+.
* Tab **Virtuelle Ordner**: Ordner, Unterordner, Links, Seiten und Action-Platzierungen anlegen. **Externe Action-Referenz …** fügt eine Action eines anderen eigenen Plugins ein (Format `plugin.id::action.id`); sie bleibt sichtbar, auch wenn das andere Plugin gerade fehlt.

## 5. Symbole bearbeiten

**SymbolDesigner …** öffnet den Designer für die ausgewählte Action: Hintergrund, Text, Bild/Symbol und Layout. Gespeichert wird als SDK-Icon-Template (`.ict`) im Projektordner; das Studio übernimmt die Verknüpfung im Projekt.

## 6. Plugin bauen – Plugin-Typ wählen

Tab **Plugin-Build**:

| Plugin-Typ | Wann verwenden |
|---|---|
| **Kompatibel (Standard)** | bisheriges Verhalten; SDK-Actions plus virtuelle Ordner aus der `.vfolders.json` |
| **Nativ – reines SDK-Plugin** | nur originale Logitech-SDK-Funktionen und SDK-Ordner, keine Folder-/Peer-Runtime (virtuelle Ordner werden nicht ausgeliefert) |
| **Shared DynamicFolder** | virtuelle Ordner mit Actions **anderer eigener Plugins**; diese werden beim jeweiligen Owner-Plugin ausgeführt |

Der gewählte Plugin-Typ wird **je Projekt benutzerlokal gemerkt** und beim nächsten Öffnen wiederhergestellt. Er wird nicht in die Projektdatei geschrieben. Ein verschobenes oder kopiertes Projekt beginnt wieder mit „Kompatibel“.

Optional eine **Python-Handler**-Datei im Projektordner wählen (muss `register(host)` enthalten). Ohne Handler protokolliert der Host jeden Tastendruck in `callbacks.jsonl`.
**Voraussetzungen prüfen** zeigt fehlende Bausteine. **SDK-Plugin bauen** erzeugt Quellen, kompiliert gegen die lokale `PluginApi.dll` und erstellt ein geprüftes Paket mit allen Icons, Symbolen, Icon-Templates und der **pluginlokalen Host-Laufzeit** (`bin\hostruntime-<id>`, rund 25 MB, jede Datei mit SHA-256 geprüft). **Build abbrechen** stoppt nach dem laufenden Schritt. Das Projekt wird durch den Build nie verändert.

## 7. Plugin installieren, prüfen, aktualisieren

Tab **Installation** (nach erfolgreichem Build):

1. **Plan anzeigen** – Probelauf: Art der Installation, Ziel, Neuinstallation oder Aktualisierung, Host-Laufzeit, gesicherte Vorversion.
2. **Installieren / Aktualisieren …** – nach Bestätigung wird das geprüfte Paket als **Verzeichnis-Installation** in den Studio-eigenen Ordner `Plugins\<Pluginname>` kopiert (die vorherige eigene Version wird vorher gesichert), genau dieses Plugin wird neu geladen und der Ladezustand geprüft. Schlägt das Laden fehl, wird automatisch auf den vorherigen Zustand zurückgerollt. Ein Neustart von Logi Options+ ist nicht nötig.
3. **Ladezustand prüfen** – Plugin-Service-Protokoll und Verbindung zum Python-Host.
4. **Test-Host starten** – startet den Host der Build-Ausgabe zum Testen **vor** der Installation. Installierte Plugins starten ihren Host selbst; der Knopf ist dafür nicht nötig.

Installierte Plugins laufen **ohne geöffnetes Studio** – auch wenn der Studio-Ordner verschoben, aktualisiert oder deinstalliert wird. Die Statusübersicht zeigt: Build, Paket, Installiert, Plugin geladen, Verbindung, Hardwareprüfung, Rollback.
Aktualisieren = neu bauen und erneut installieren; die eigenen Dateien werden einzeln atomar ersetzt, die Vorversion bleibt im Beleg für ein Rollback erhalten. Läuft das Plugin währenddessen, werden noch benutzte Laufzeitdateien beiseitegelegt und nach dem Neuladen entfernt.
**Belegung in Options+:** Ordner/Actions des Plugins in Logi Options+ einer Taste zuweisen (Drag & Drop). Das Studio verändert keine Profile.

Der frühere **Entwicklungs-Link** (`<plugin-id>.link`) wird nur noch für Altinstallationen angezeigt; der Logi Plugin Service liest solche Links erst beim nächsten Dienststart.

## 8. Rollback und Entfernen

* **Zurückrollen …** stellt die exakte vorherige eigene Version wieder her (bzw. entfernt eine Neuinstallation) und lädt das Plugin neu.
* **Deinstallieren …** entfernt nur die eigenen Plugindateien einschließlich der pluginlokalen Host-Laufzeit (gesichert im Beleg); **Deinstallation rückgängig** stellt sie wieder her. Vom Plugin selbst geschriebene Daten (z. B. `callbacks.jsonl`) bleiben.
* **Wichtig:** Tastenbelegungen des Plugins in Ihrem Logi-Options+-Profil werden vom Studio nicht verändert. Sie können nach der Deinstallation auf dem Keypad sichtbar bleiben und müssen dann in Logi Options+ entfernt werden.
* **Installierte Plugins** listet Plugin-Verzeichnisse und Entwicklungs-Links samt Zustand der Host-Laufzeit; fremde Plugins werden nur angezeigt und niemals verändert.

## 9. Shared-Plugins: Pairing und Berechtigungen

Tab **Shared-Peers**:

1. Zwei eigene Plugins wählen (Plugin A / Plugin B) → **Paaren**. Paaren erzeugt einen geheimen Schlüssel für genau dieses Paar, erlaubt aber **noch keine** fremde Ausführung.
2. Freigabe als Owner (das geöffnete Projekt): Empfänger, Action/Parameter oder Ordner und erlaubte Operation (**Ausführen**, **Drehen**) wählen → **Freigeben**. Ordnerfreigaben sind nur lesend.
3. **Widerrufen** entfernt eine markierte Freigabe; **Entpaaren …** entfernt Paar und alle Freigaben; **Neu verschlüsseln** ersetzt den Schlüssel (auch die Abhilfe, wenn ein Schlüssel nicht mehr entschlüsselt werden kann).
4. **Verbindungsdiagnose** zeigt je Plugin: online, SDK verbunden, Policy gültig, Peers verbunden/getrennt. Die Spalte **Schlüsselablage** zeigt „DPAPI-geschützt“.
5. Änderungen wirken beim nächsten Plugin-Start: **Plugin neu laden (Resync)**.

Schlüssel liegen nur in `%LOCALAPPDATA%\LogiPluginStudio\SharedFolders\config`, sind mit Windows-DPAPI an Ihr Windows-Konto gebunden und stehen nie im Projekt, Paket oder Protokoll. Ältere Klartext-Schlüssel werden beim Öffnen des Tabs automatisch geschützt – außer für Plugins, die noch mit einer Studio-Version vor 1.0 gebaut und installiert sind (diese lesen nur Klartext): erst neu bauen und aktualisieren. Fällt ein Peer aus, bleiben lokale Actions nutzbar; fremde Einträge erscheinen als „[unavailable]“ und kehren nach dem Neustart automatisch zurück.

## 10. Fehler diagnostizieren

| Symptom | Ursache / Lösung |
|---|---|
| „Voraussetzung fehlt: PluginApi.dll …“ | Logi Options+ installieren bzw. reparieren |
| „.NET SDK … fehlt“ | .NET SDK 8+ installieren, Studio neu starten |
| Plugin geladen = `ALREADY_LOADED_RELOAD_REQUIRED` | Plugin war schon geladen; „Ladezustand prüfen“ nach kurzem Warten oder Plugin neu laden |
| Plugin geladen = `LOAD_FAILED` | Details im Installations-Log; automatisches Rollback ist erfolgt |
| Verbindung = `HOST_NOT_RUNNING` | Plugin neu laden; Inventar „Installierte Plugins“ und Hostprotokoll `%LOCALAPPDATA%\LogiPluginStudio\HostLogs\<plugin>.log` prüfen |
| Inventar: „Laufzeit BESCHÄDIGT – neu installieren“ | Eine Datei der pluginlokalen Laufzeit wurde verändert; das Plugin startet seinen Host aus Sicherheitsgründen nicht. Erneut installieren |
| Inventar: „ALTER absoluter Hostpfad“ | Plugin wurde vor 1.0 gebaut und hängt vom Studio-Ordner ab: im Studio neu bauen und aktualisieren (Migration auf pluginlokale Laufzeit) |
| Fremde Action bleibt „[unavailable]“ | Owner nicht gestartet, nicht gepaart oder Action nicht freigegeben (Tab Shared-Peers → Verbindungsdiagnose); Hostprotokoll `%LOCALAPPDATA%\LogiPluginStudio\SharedFolders\logs\<plugin>.log` |
| „Geschützter Schlüssel … kann nicht entschlüsselt werden“ | Anderes Windows-Konto oder beschädigt: Paar „Neu verschlüsseln“ |

`Diagnose.cmd` schreibt einen Bericht nach `%TEMP%\LogiPluginStudio-diagnose.txt`.

## 11. Automatisierung (optional)

Für Skripte und Prüfabläufe bietet `LogiPluginStudio.exe` dieselben Abläufe wie die Oberfläche:

```
LogiPluginStudio.exe --build <projekt.json> --mode native|compatible|shared [--handler datei.py] --out bericht.json
LogiPluginStudio.exe --install <paketordner> --confirm <plugin-id> --out bericht.json
LogiPluginStudio.exe --uninstall <plugin-id> --confirm <plugin-id> --name <SdkName> --out bericht.json
LogiPluginStudio.exe --diagnose --out bericht.txt
```

Installation und Deinstallation verlangen die ausdrückliche Bestätigung der Plugin-ID und arbeiten nur mit Studio-eigenen Plugins.
