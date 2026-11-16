# Logitech Actions SDK → Python: API-Abdeckung und Umsetzungscheckliste

**Stand:** 08.11.2026 · **Ziel:** Möglichst **originalgetreue, schlanke Python-Nutzung** der tatsächlich belegten Logitech-C#-SDK-Funktionen. Dies ist eine **fortschreibbare Arbeitsliste** und keine Behauptung, die vollständige API sei schon übersetzt.

**Quellen (lokal geprüft):**
- Installierte Hersteller-XML: `C:\Program Files\Logi\LogiPluginService\PluginApi.xml` und zugehörige `PluginApi.dll`; Version 6.4.2.3414 im vorangegangenen SDK-Testbericht.
- `references/logitech-sdk/logi-actions-sdk-llms-full.md`, insbesondere C#-Kapitel *Dynamic Folders*, *Multistate Plugin Actions*, *Action Editor Actions*, *Managing Plugin Settings*, *Plugin Status*, *Icon Templates*, *Plugin Capabilities* und *Installation and Uninstallation*.
- Verbindliche Architektur: [ARCH-ADR-001](../decisions/ARCH-ADR-001.md) und [Schichtentrennung](../architecture/sdk-bridge-schichtentrennung.md).
- Tatsächliche Implementierung: `src/adapters/logitech/product.py`, `templates/Bridge.cs.in`, `src/runtime/host.py`, `src/extensions/shared_folders/`.

**Checkbox-Regeln (unbedingt einhalten):**
- **Jede Checkbox bezeichnet exakt die angegebene Schicht.** Ein Häkchen bei „C#“ bedeutet **nicht**, dass dieselbe Funktion Python-seitig direkt aufrufbar ist.
- **C#** = im aktuellen Generator/SDK-Host-Softwarepfad implementiert und regressionsgetestet; nicht automatisch Hardware-PASS.
- **Python** = über eine öffentliche, semantisch klar zuordenbare Python-Schnittstelle unmittelbar nutzbar. Ein empfangener Python-Callback zählt nur bei der ausdrücklich als „Callback“ bezeichneten Zeile.
- **Extension** = eigene, optionale Komfortfunktion; kein Teil der Original-SDK-API.
- **[ ]** = noch nicht nachgewiesen bzw. nicht vollständig verfügbar; nicht automatisch „SDK unmöglich“. Signatur und echte SDK-Fähigkeit vor Implementierung verifizieren.
- Die XML-Datei enthält nicht jede SDK-Klasse vollständig. Dokumentierte Methoden aus der Hersteller-Gesamtdokumentation sind als **SDK-Doku** vermerkt; ihr genauer Overload ist bei Bedarf mit der installierten DLL abzugleichen.

## 1. Plugin-Basis, Lebenszyklus und Identität

- [x] **C#**: `Plugin`-Unterklasse aus Projekt generieren und gegen `PluginApi.dll` kompilieren.
- [x] **C#**: `Plugin.Load()` / `Plugin.Unload()` – starten/stoppen den aktuellen sicheren Hosttransport.
- [ ] **Python**: optionale Python-Hooks `on_load` / `on_unload` für die *SDK*-Lebenszyklusereignisse, sauber synchronisiert (nicht bloß Hoststart).
- [x] **C#**: `Plugin.HasNoApplication` – Universal-Plugin konfiguriert.
- [x] **C#**: `Plugin.UsesApplicationApiOnly` – derzeit fest `true` (keine variable Python-Konfiguration).
- [ ] **Python**: `Plugin.SupportedDevices` inklusive `DeviceType`-Flags ohne Verlust konfigurierbar.
- [ ] **Python**: `Plugin.Name`, `Plugin.Info`, `Plugin.ClientApplication` als geeignete read-only SDK-Daten verfügbar.
- [ ] **Python**: `Plugin.CanLoad()`-Hook mit kontrollierter Lifecycle-Entscheidung.
- [ ] **Python**: `Plugin.Install/Uninstall` und `InstallAdmin/UninstallAdmin` – nur wenn wirklich gewünscht und zulässig; kein heimlicher Installer.
- [ ] **Python**: `Plugin.GetPluginDataDirectory()` als SDK-konforme Standortabfrage.
- [ ] **Python**: `Plugin.Log`-Schnittstelle (SDK-Plug-in-Log, getrennt vom Python-Protokoll).
- [ ] **SDK-Host**: echter Load-/Unload-Nachweis unter Options+ für die neue native Folder-Laufzeit.

## 2. Commands, Parameter, Status und Bildaktualisierungen

- [x] **C#**: `PluginDynamicCommand`-Klassen mit originalen SDK-Typen erzeugen.
- [x] **C#**: `PluginDynamicAction.OnLoad()` / `OnUnload()` für vorhandene Actionklassen.
- [x] **C#**: `PluginDynamicAction.RunCommand(string actionParameter)`; Parameternamen bleiben erhalten.
- [x] **Python-Callback**: Command-ID, `action_parameter` (inklusive `null`) und optionale Placement-ID kommen beim registrierten Python-Handler an.
- [ ] **Python**: öffentliche Python-Klassen/Funktionssignaturen für native `PluginDynamicCommand`-Definition und -Lifecycle, statt ausschließlicher JSON-/C#-Generierung.
- [x] **C#**: `PluginDynamicAction.AddParameter(...)` – deklarierte Parameter werden bei der Generierung registriert.
- [ ] **Python**: Parameter im laufenden Plugin über `ParametersChanged()` dynamisch hinzufügen/entfernen/aktualisieren.
- [ ] **Python**: `PluginDynamicAction.IsEnabled` aus Python gezielt setzen/lesen.
- [x] **C#**: `GetCommandDisplayName(actionParameter, imageSize)` im generierten/Folder-Pfad nutzbar.
- [x] **C#**: `GetCommandImage(actionParameter, imageSize)` im generierten/Folder-Pfad nutzbar.
- [x] **C#**: `ActionImageChanged()` und parametrische Bild-Notifications im bestehenden Generator/SDK-Laufzeitpfad verwendet.
- [ ] **Python**: explizite, getrennte `set_display_name`-/`set_image`- bzw. SDK-äquivalente Änderungs-API mit passender `ActionImageChanged(actionParameter)`-Benachrichtigung (nicht nur indirekter Python-Host-State).
- [ ] **Python**: `GetCommandDisplayName`-/`GetCommandImage`-Rückgaben als echte Python-Overrides je SDK-Action, ohne obligatorischen zusätzlichen State-/Renderer-Kern.
- [ ] **Python**: native `PluginImageSize`-Größen und SDK-`BitmapImage`-Rückgaben ausreichend verlustfrei definieren.
- [ ] **SDK-Host**: tatsächlicher parametrischer Image-/Text-Refresh auf MX-Keypad prüfen.

## 3. Multistate: SDK-Zustandsautorität erhalten

- [x] **C#**: `PluginMultistateDynamicCommand` aus nativer Definition generieren.
- [x] **C#**: `AddState` inklusive Reihenfolge (0-basierte Indizes), Anzeige und Beschreibung.
- [x] **C#**: `ToggleCurrentState(actionParameter)`, `IncrementCurrentState`, `DecrementCurrentState` je deklarierter Aktion.
- [x] **C#**: `GetCommandDisplayName(actionParameter, stateIndex, size)` und `GetCommandImage(actionParameter, stateIndex, size)` – zustandsabhängige SDK-Darstellung.
- [x] **SDK-Probe**: Direkter und Folder-Aufruf verwenden dieselbe native Multistate-Actioninstanz und liefern passende Statebilder.
- [ ] **Python**: natives `States`-/`TryGetCurrentState(actionParameter)`-Abfrageobjekt.
- [ ] **Python**: `SetCurrentState(actionParameter, index)` als expliziter SDK-nativer Owner-Aufruf.
- [ ] **Python**: `IncrementCurrentState`, `DecrementCurrentState`, `ToggleCurrentState` als explizit adressierbare SDK-Operationen.
- [ ] **Python**: SDK-State-Changed-Ereignisse/Callbacks getrennt von externem `StateStore` verfügbar.
- [ ] **C#/Python**: LED-Farben je SDK-State vollständig unterstützbar; aktueller Generator nennt hier ausdrücklich eine installierte SDK-Capability-Grenze.
- [ ] **SDK-Hardware**: State, Bild, LED und Parameter-Unabhängigkeit am Gerät nachweisen.

## 4. Adjustments / Encoder / Reset

- [x] **C#**: `PluginDynamicAdjustment` als eigener SDK-Typ generiert; Min/Max/Default/Format/Reset.
- [x] **C#**: `ApplyAdjustment(actionParameter, diff)` und `RunCommand(actionParameter)` für Reset.
- [x] **Python-Callback**: `operation='adjustment'`, `adjustment_diff`, `action_parameter` im Handler verfügbar; Reset separat als Command.
- [x] **C#**: `GetAdjustmentDoubleValue` bzw. SDK-Wert-/Format-Pfad im generierten Typ.
- [x] **C#**: `AdjustmentValueChanged` bei Änderungen im generierten Typ.
- [x] **SDK-Probe**: Direkter und Folder-Aufruf teilen denselben SDK-Adjustment-Wert; Encoderrotation und Reset getestet.
- [ ] **Python**: Wert über SDK-`GetAdjustmentValue(actionParameter)`/entsprechende native Numeric-/Display-Wertabfragen lesen.
- [ ] **Python**: native Adjustmentwerte setzen und exakt passende `AdjustmentValueChanged`-Notifications auslösen (ohne zweite Autorität).
- [ ] **Python**: native Reset-Metadaten `ResetDisplayName`, `ResetGroupName` verfügbar.
- [ ] **Python**: dynamische Adjustment-Parameter-/Enabled-/Display-/Image-API.
- [ ] **SDK-Hardware**: Encoder-Reaktion, Value-Label, Reset und andere Gerätebereiche praktisch prüfen.

## 5. ActionEditor (nicht mit eigenem Qt-Inspector verwechseln)

- [x] **C#**: `ActionEditorCommand` mit echten SDK-Controls generiert.
- [x] **C#**: `ActionEditorCheckbox`, `ActionEditorTextbox`, `ActionEditorTextArea`.
- [x] **C#**: `ActionEditorSlider`, `ActionEditorNumericUpDown`.
- [x] **C#**: `ActionEditorFileSelector`, `ActionEditorDirectorySelector`, Dateifilter/Dialogtitel gemäß dokumentiertem Generatorumfang.
- [x] **Python-Callback**: typisierte/namentliche Editorwerte werden im `editor_values`-Payload an Python transportiert; C#-SDK-Erzeugung softwaregeprüft.
- [ ] **Python**: ActionEditor-Definition/Controls über eine direkt nutzbare SDK-nahe Python-API registrieren, nicht nur via Autoren-JSON.
- [ ] **C#/Python**: `ActionEditorAdjustment`-Typ als eigener SDK-Pfad (Hersteller-Doku; noch nicht umgesetzt).
- [ ] **C#/Python**: `ActionEditorListbox` mit dynamischer Item-Population (Hersteller-Doku).
- [ ] **C#/Python**: `ActionEditorKeyboardKey`, `ActionEditorButton` und zugehörige Events (Hersteller-Doku).
- [ ] **C#/Python**: alle dokumentierten Editor-Lifecycle-/Value-Change-Events und SDK-Varianten.
- [ ] **Extension**: ActionEditor innerhalb virtueller Folder **bewusst gesperrt**, bis SDK-native Unterstützung eindeutig belegt ist. Diesen Schutz nicht als „fertige Folder-Ausführung“ abhaken.

## 6. PluginDynamicFolder / SDK-Navigation

- [x] **C#**: echte `PluginDynamicFolder`-Klassen, `Load/Unload` und mehrere reale Folder pro Plugin.
- [x] **C#**: `GetNavigationArea(DeviceType)` für `ButtonArea`, `EncoderArea`, `None`.
- [x] **C#**: `GetButtonPressActionNames`, `GetEncoderRotateActionNames`, `GetEncoderPressActionNames`.
- [ ] **C#/Python**: `GetWheelToolNames` und Wheel-Tool-Semantik (SDK-Doku, nicht im aktuellen Keypad-Scope implementiert).
- [x] **C#**: `CreateCommandName`, `CreateAdjustmentName` mit echten SDK-Namen.
- [x] **C#**: `ButtonActionNamesChanged()`, `EncoderActionNamesChanged()` bei Membership-Änderung (protected Host-Notification).
- [x] **C#**: `GetCommandDisplayName/GetCommandImage`, `GetAdjustmentDisplayName/GetAdjustmentImage` und `GetAdjustmentValue` aus SDK-Actioninstanzen.
- [x] **C#**: `RunCommand`, `ApplyAdjustment` an dieselbe SDK-native Actioninstanz delegiert.
- [x] **C#**: SDK-`NavigateUpActionName`, `NavigateLeftActionName`, `NavigateRightActionName` bei `None` berücksichtigt.
- [ ] **Python**: unabhängige direkte Python-SDK-Folder-API für native Membership/Notifications, ohne `virtual-folders-1` oder `sdk-folders-1` benutzen zu müssen.
- [ ] **Python**: originale SDK-Folder-`Activate/Deactivate`-Callbacks.
- [ ] **Python**: `GetButtonDisplayName` / `GetButtonImage` für den Folder-Öffner, als frei konfigurierbare API.
- [ ] **Python**: `Close()` des aktuellen SDK-Folders über eine explizit autorisierte SDK-Operation.
- [ ] **SDK**: generisches öffentliches programmatisches `Open()` **nicht belegt**; nicht implementieren/versprechen.
- [ ] **SDK-Hardware**: echtes Back, Requery/Cache, reale Navigation/Paging, physische Seitentasten, Multi-Device.

## 7. Grafiken, native Ressourcen und Ausgabe

- [x] **C#/Build**: PNG/SVG-Assets und native `.ict`-Dateien validieren und ohne Verlust in die passende Paketstruktur übernehmen.
- [x] **C#/Build**: `actionicons`, `actionsymbols`, `icontemplates`, `metadata/DefaultIconTemplate.ict` generieren.
- [x] **Studio/Lab**: eigenständiger SDK-ICT-SymbolDesigner sowie native Bindings/Projekt-Dialog vorhanden.
- [ ] **Python**: SDK-`BitmapImage`-/`PluginResources`-API direkt für Codecallbacks nutzbar, inklusive Größen-/Transparenzverträgen.
- [ ] **Python**: `PluginResources.FindFile/ReadImage` und ggf. `BitmapBuilder` als originalgetreue Funktionsoberfläche.
- [ ] **Python**: dynamischer Austausch von Bild-/Text-/ICT-Ressourcen zur Laufzeit mit korrekten SDK-Notifications ohne erzwungenes PNG-Flattening.
- [ ] **SDK-Hardware**: native Override-Priorität **User > Action > Plugin > Global** und tatsächliche Bildgrößen am Gerät abschließend testen.
- [ ] **Produkt**: native ICT-Dialogtransaktionen und KeypadPreview im Hauptfenster freischalten (separates UI-AP).

## 8. Einstellungen, Status, Modi und Anwendung

- [ ] **Python**: `Plugin.TryGetPluginSetting(name, out value)`.
- [ ] **Python**: `Plugin.SetPluginSetting(name, value, backupOnline)` (Cloud-Sicherung ausdrücklich opt-in).
- [ ] **Python**: `Plugin.DeletePluginSetting(name)`.
- [ ] **Python**: `Plugin.ListPluginSettings()`.
- [ ] **Python**: `Plugin.OnPluginStatusChanged(PluginStatus, message[, supportUrl, title])`.
- [ ] **Python**: `Plugin.ModeChanged` und `SetCurrentMode(modeName)`.
- [ ] **Python**: `Plugin.AddMode/RemoveMode/GetMode/GetSubMode`.
- [ ] **Python**: `Plugin.IsApplicationRunning/IsApplicationActive/IsApplicationInstalled`.
- [ ] **Python**: `ClientApplication.GetProcessName(s)`, `GetBundleName(s)`, `GetApplicationStatus` und passende Prozess-/Bundle-Checks.
- [ ] **Python**: SDK-`ClientApplication`-Methoden für Anwendungssteuerung nur nach konkreter XML-/DLL-Methode und Berechtigung erfassen; kein willkürliches universelles Automationsmodell.
- [ ] **Python**: Plugin-Logging über `Plugin.Log` und SDK-konforme Logging-Level.
- [ ] **Produkt**: lokale Plugin-Konfiguration und sichere Datenablage über den SDK-Datenordner statt stillschweigender neuer globaler State-Engine.

## 9. Geräte, Profile, Kompatibilität und zusätzliche SDK-Funktionen

- [x] **SDK-Nachweis**: `DeviceType.Loupedeck70` entspricht dem MX Creative Keypad; `PluginImageSize` und Gerätebereiche im nativen SDK bekannt.
- [ ] **Python**: Geräteinformationen, unterstützte Geräte und verfügbare Navigationsbereiche als neutraler SDK-Descriptor; keine feste Annahme „8+Back“.
- [ ] **SDK/Plugin**: Application-gebundene vs. universelle Profile und ihre tatsächlichen Host-Regeln vollständig abbilden.
- [ ] **Python**: Plugin-Localization/XLIFF, Parameter-Lokalisierung, Sprach-/Länderinformationen (Hersteller-Doku).
- [ ] **Python**: Profile Actions / Default Profiles nur auf belegter öffentlicher SDK-Schnittstelle, keine private `ProfileInfo.json`-/`.lp5`-Schreibtechnik.
- [ ] **Optional**: Action Ring, Haptik und zusätzliche Gerätefamilien separat als Capability-Paket prüfen, nicht automatisch als MX-Keypad-Funktion markieren.
- [ ] **Produkt**: Installations-/Uninstall-/Reload-/Rollback-Prozess für SDK-Plugins im nativen Studio vollständig integriert und am realen Service getestet.
- [ ] **Produkt**: Windows-Endnutzerpaket ohne Python-IDE und mit klaren SDK-/Runtime-Abhängigkeiten auf sauberem Rechner geprüft.

## 10. Aktuelle minimale Python-Bridge: bereits belegte Fähigkeiten

- [x] `PluginHost.register_handler(handler_id, port, callable)`: registriert vorhandene Python-Handler für NativeAction-Callbacks.
- [x] SDK-Command-Ausführung → Python-Handler, korrelierter `component_id`, `placement_id`, `action_parameter`, `operation`, `adjustment_diff`, `editor_values`.
- [x] Authentisierte C#↔Python-IPC mit Session-/Runtime-ID, Signatur, begrenzten JSON-Nachrichten, Duplicate-Key-/Stale-/Replay-Schutz.
- [x] State-/Command-Snapshot, Resultate, sequenzielles Eventjournal, Reconnect ohne automatisches Command-Replay im vorhandenen Python-Hostpfad.
- [x] Generisches C#-Bridge-Ereignis `SnapshotReceived` / `JournalEventReceived`, **ohne** Folder-spezifische Payload-Auswertung.
- [ ] Vollständige öffentliche Python-Nachbildung der relevanten SDK-Methoden und Properties, **pro SDK-Signatur**; durch vorhandene Callbacks **nicht** automatisch erreicht.
- [ ] Explizite API-Kompatibilitätstests für jede künftig ergänzte Python-Methode: Parameter (auch `null`), State-Owner, Overloads, Returnwerte, Exceptions und Capability-Grenzen.

## 11. Optionales Shared DynamicFolder – getrennt von SDK-Abdeckung

- [x] **Extension**: `virtual-folders-1`-Autorenmodell, reale Ordner/Links/Pages, separate Sidecar-Persistenz.
- [x] **Extension**: `sdk-folders-1`-Projektion mit Action-Referenzen, ohne zweite native Actiondefinition.
- [x] **Extension**: `FolderRuntimeHost` publiziert Full-Snapshots und Folgeevents über bestehenden signierten Hosttransport.
- [x] **Extension**: nur `src/extensions/shared_folders/templates/NativeFolders.cs.in` interpretiert `folder_runtime` / `folder.layout`; Basis-`Bridge.cs.in` enthält diese Begriffe nicht.
- [x] **Extension**: Studiobuild aus gespeicherter Folder-Extension; Rückwärtskompatibilität alter Imports.
- [ ] **Extension**: eigenständiger, vollständig erweiterungsfreier nativer SDK-Foldergenerator/Buildmodus (heute noch gemeinsam genutzter nativer Folderaufsatz; siehe [Schichtentrennung](../architecture/sdk-bridge-schichtentrennung.md)).
- [ ] **Extension**: Peer-Discovery/Join/Leave/Heartbeats zwischen unabhängigen Plugins.
- [ ] **Extension**: eigentümergebundene Cross-Plugin-ActionInvoke-API und gezielte Push-Subscriptions.
- [ ] **Extension**: Ausfallverdacht, gegenseitige Verbindungsprüfung, Rejoin mit neuer Instanzidentität.
- [ ] **Extension**: echte Geräte- und Multi-Plugin-Verifikationen.

## 12. Arbeitsreihenfolge und Abnahmekriterien

- [x] Architekturentscheidung `ARCH-ADR-001` verabschiedet; Basis-Bridge und optionale Folder-Domänenquellen strukturell getrennt.
- [x] Rückwärtskompatible Altimporte und vorhandene C#-/Python-Prozessregressionen als Tests vorhanden.
- [ ] **P0:** SDK-API-Inventar per Reflection der installierten DLL **vollständig** in eine versionierte Methodensignaturenliste übernehmen; diese Liste ist aktuell eine priorisierte, quellenbasierte Funktionscheckliste, kein vollständiger Reflection-Dump.
- [ ] **P0:** Prioritäten für eine neue schlanke Python-SDK-Fassade bestimmen (zunächst native Commands, Parameter, States, Adjustments und Anzeigeupdates).
- [ ] **P0:** Python-Fassade so entwerfen, dass SDK-Funktionen auch **ohne** `extensions.shared_folders` nutzbar sind.
- [ ] **P1:** Get/Set/Notify inklusive Rückgabetypen und SDK-Exceptions testen und Version-/Capability-Gates dokumentieren.
- [ ] **P1:** Settings, Modes, PluginStatus, Lifecycle und Application-Ereignisse nach Bedarf in Python freigeben.
- [ ] **P2:** Geräte-, Bild- und zusätzliche SDK-Funktionen abhängig vom tatsächlichen Hardware-/DLL-Support erweitern.
- [ ] **P2:** vollautomatisierte API-Coverage-Prüfung gegen DLL-Reflection einführen, die offene neue SDK-Funktionen meldet.
- [ ] **Release:** tatsächliche vollständige Python-/SDK-Funktionsabdeckung und Hardwaretests unabhängig freigeben.

**Hinweis:** Checkboxen für Studio-/C#-/Extension-Funktionen dürfen nicht als „Python-API vollständig“ aggregiert werden. Das Hauptziel bleibt die **dünne, semantisch transparente Python-SDK-Anbindung**, auf der jede optionale Erweiterung aufbaut.
