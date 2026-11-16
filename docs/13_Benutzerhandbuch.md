# Plugin Studio: Benutzerhandbuch

Folgelieferung FINAL-PRODUCT-02: READY_FOR_REVIEW, keine Selbstabnahme.
FINAL-PRODUCT-01 ist unabhaengig als Software-MVP / PROCESS_PROVEN freigegeben.
Gesamtumfang PARTIAL; echte Keypad-Ausfuehrung HARDWARE_PENDING.

## 1. Umgebung und Start

Nur CSL-DESKTOP-PC, kein VPS. Aktive Projektwurzel:

```powershell
Set-Location 'P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture'
python tools\run_studio.py examples\first_plugin\project.json
```

Ohne Argument startet ein neues leeres Projekt. Alternativ
`.\start_studio.ps1` verwenden; falls lokale PowerShell-Skriptregeln dies
verweigern, den Python-Start nutzen, keine globale Policy aendern.

Voraussetzungen: Python 3.12, PySide6 Widgets, .NET 10 SDK. Diese waren beim
Lauf vorhanden; keine Pakete wurden nachinstalliert. Die echte SDK-DLL ist
`C:\Program Files\Logi\LogiPluginService\PluginApi.dll`.

Der fruehere Pfad `C:\Users\marco\.openchamber\logi_actions_sdk` in
Abnahmeakten bezeichnet den Stand vor dem Umzug. Nicht dorthin zurueckkopieren.
Historische Berichte und ACCEPTED-ADRs bleiben unveraendert.

## 2. Ein eigenes Plugin erstellen

1. **Callback-Vorlage** waehlen. Vorhandene ungespeicherte Entwuerfe zuerst
   speichern, verwerfen oder den Wechsel abbrechen.
2. Projektwurzel im Baum auswaehlen; eigene stabile Plugin-ID und Anzeigenamen
   bearbeiten, **Eigenschaften uebernehmen**.
3. Komponenten auswaehlen und Anzeigenamen/IDs anpassen. Die Vorlage besitzt
   zwei unabhaengige Aktionen, einen explizit registrierten `toggle`-Handler
   und einen component-scoped State `state.mode`.
4. **Speichern unter**: etwa `work\mein-plugin\project.json`.
5. Im Tab **Build / Deployment** Assembly-Namen festlegen und
   **Validieren, generieren und bauen** ausloesen.

IDs: Kleinbuchstaben, Ziffern und `.`, `_`, `-` als Trenner; mit Buchstaben
beginnen. Beispiele `action.meine-taste`, `state.mode`, `view.main`.
Anzeigenamen sind keine Identitaeten und duerfen frei formuliert werden.
Rename von Komponenten/States/Presentations/Assets aktualisiert bekannte
Referenzen transaktional. Referenzierte Objekte werden nicht still geloescht.
Eine duplizierte View erhaelt neue Placement-IDs.

Die Standardausgabe liegt unter
`work\generated\<Plugin-ID>\<Projektfingerprint>`. Nach Projektaenderungen
entsteht eine neue Revision; alte Verbindungseinstellungen werden nicht
heimlich passend gemacht. Generiertes C# nicht von Hand editieren.

## 3. Modellobjekte wirklich bearbeiten

| Objekt | Bedienung und Bedeutung |
|---|---|
| Komponenten | Hinzufuegen ueber Typmanifest; Konfiguration und Portvertraege im Eigenschaften-Tab |
| States | Wertvertrag als JSON, Scope, Authority, Persistenzdeklaration, optionaler Fallback |
| Bindings | Signalart und strukturierte Quelle/Ziel ueber Port-Auswahl; Kompatibilitaet live validiert |
| Views | Logischer Folder/Grid; Placements mit eigener ID, Component, Presentation und Position |
| Presentations | Variantenschluessel, Text, Vorder-/Hintergrund, PNG-Asset-ID, optional Bildmodus und Schriftgroesse |
| Assets | Projekt-relative PNG-Pfade; Import/Export ueber den Toolbar-Eintrag |

Commands, Events und States sind getrennt. Ein COMPLETED-Command bedeutet
ausgefuehrten Handler, nicht automatisch einen State-Wechsel oder fachlichen
Erfolg. `state.mode` aendert sich im Beispiel nur durch den expliziten Write.
Andere Callback-IDs oder fachliche States verlangen eine passende,
vertrauenswuerdige Python-Registrierung; der Generator erfindet keine Handler.

Scope `project` bedeutet runtimeweit innerhalb dieser Host-Ausfuehrung.
`component` und `placement` bleiben getrennt. Fallback ist Designkonfiguration,
kein bestaetigter Ist-Wert. `runtime_local`/`external` deklarieren eine
Persistenzabsicht; diese Lieferung speichert aktuelle Werte nicht automatisch.
`session` als fachlicher State-Scope ist nicht unterstuetzt.

Formulare behalten unbekannte Felder. Bei Core-Fehlern ist das strukturierte
Formular deaktiviert; Objekt-/Projekt-JSON bleibt zur expliziten Korrektur
verfuegbar. Fehler werden nicht still normalisiert. JSON-Entwuerfe explizit
uebernehmen, damit sie Modell und Build erreichen. Syntaxfehler koennen beim
Schliessen trotzdem verworfen werden. Externe Dateiaenderungen blockieren
das Ueberschreiben; neu laden oder unter anderem Namen speichern.

## 4. Layout, Bilder und groessere Views

Eine Aktion kann mehrfach platziert werden, ohne eine neue fachliche
Komponente zu erzeugen. Es gibt kein globales Vier-/Acht-Aktionslimit.
Die Design-Vorschau zeigt pro Seite acht Inhalte plus SDK-Back-Bereich.
Das ist eine markierte Vorschaukonvention, keine vermessene Hardwaregarantie.
Der generierte DynamicFolder gibt alle logischen Placements an die
SDK-eigene ButtonArea-Navigation/Pagination weiter.

Import: PNG, JPEG, BMP oder WebP bis 8 MiB und maximal 4096px Seitenlaenge.
Export: transparenter 116px-PNG mit proportionaler Skalierung/Letterboxing.
Die Entwicklerfunktion unterstuetzt ausserdem 50 und 80px. Laut echter
SDK-XML bedeutet `Width60` 50px und `Width90` 80px; `Width116` bedeutet 116px.
Der Generator prueft PNG-Signatur, CRC, vollstaendige Chunk-Grenzen,
8-Bit-RGB/RGBA ohne Interlacing, Raster-Dekompression und Scanline-Filter.
PNG maximal 1 MiB und 1024px Seitenlaenge; andere PNG-Formate im Studio
neu exportieren. Assets bleiben innerhalb des Projektordners.

Pro Variante sind **Bildmodus** `stretch` oder `contain` und **Schrift px / 116**
(Ganzzahl 6..48) optional einstellbar. `contain` zentriert rechteckige PNGs
proportional statt sie auf ein Quadrat zu verzerren; Transparenz bleibt erhalten.
Die Schriftgroesse skaliert auf 50/80px mit. Leere Felder bewahren den bisherigen
MVP-Standard, kein stiller Austausch der Darstellung alter Projekte.
Import erzeugt bereits ein quadratisches, proportional gefuelltes PNG; fuer
rechteckige eigene PNGs den validierten Asset-Pfad projekt-relativ deklarieren.
Modellwerte `image_fit`/`font_size` bleiben im bestehenden Presentation-Objekt,
kein neues Projektformat. Falsche Typen/Werte blockieren den Produktbuild.

Die Preview-Variantenauswahl aendert keinen Runtime-State. Default verwendet
den konfigurierten State-Fallback, sonst die erste Variantenschluessel-Sortierung.
Ohne Placement benutzt eine Standalone-Aktion die lexikografisch erste eigene
Placement-ID als Designreferenz. Bei Fehlern wird kein Hardware-PASS angezeigt.

## 5. Sofort nutzbares Beispiel: Host ohne Studio

Der Lauf liefert ein bereits gegen die echte SDK-DLL gebautes Beispielpaket:

```powershell
python examples\first_plugin\host.py --connection work\autopilot\FINAL-PRODUCT-02\example-build\bin\Debug\studio.connection.json
```

Der Host meldet `HOST_READY`; mit **Strg+C** sauber stoppen. Das Studio muss
nicht laufen. Der Beispielhost laedt ausschliesslich sein festes,
vertrauenswuerdiges Python-Programm, keinen Code aus Projekt-JSON.
Bei einem eigenen Projekt zusaetzlich `--project <eigene Projektdatei>`
und den zum neuen Build gehoerenden Connection-Pfad angeben.
Die Vorlage muss ihre `state.mode`-/`toggle`-Vertraege behalten; frei
umbenannte Aktionen funktionieren weiterhin ueber ihren CommandContext.

In einem zweiten PowerShell-Fenster:

```powershell
python tools\run_product.py diagnose --connection work\autopilot\FINAL-PRODUCT-02\example-build\bin\Debug\studio.connection.json
python tools\run_product.py press --connection work\autopilot\FINAL-PRODUCT-02\example-build\bin\Debug\studio.connection.json --action action.first --placement placement.first
python tools\run_product.py press --connection work\autopilot\FINAL-PRODUCT-02\example-build\bin\Debug\studio.connection.json --action action.second --placement placement.second
```

Das sind **simulierte Tasteneingaben ueber echtes authentisiertes HTTP**,
keine SDK-/Hardware-Callbacks. Die Ausgabe zeigt Command-Result und den
component-scoped State der jeweiligen Aktion. Zweiter Druck toggelt zurueck.
Die zehn Placements im zweiten Folder verwenden dieselben beiden Aktionen.

Neubau des Beispiels:

```powershell
python tools\run_product.py generate --project examples\first_plugin\project.json --assembly FirstStudioPlugin --out work\generated\first-plugin --build
```

Dann den Connection-Pfad dieser neuen Ausgabe verwenden. Das Tool erzeugt
Quellen, DLL, private Verbindung und `development-package`; es installiert
nichts. `new <Datei> --id <ID>` erstellt dieselbe Callback-Vorlage per CLI.

**Geheimnis:** `studio.connection.json` enthaelt den lokalen HMAC-Schluessel.
Nicht veroeffentlichen, nicht in Quellarchive aufnehmen. Prozesse desselben
Windows-Kontos mit Leserechten sowie Administratoren sind keine getrennte
Sicherheitszone. Mehrere Plugins verwenden getrennte IDs/Ports/Schluessel.

## 6. Optionale eigene Installation: erst Dry-Run

Echte Installation wurde in dieser Lieferung **nicht ausgefuehrt**.
Sie ist eine gesonderte Nutzerhandlung. Zuerst das gebaute Paket pruefen:

Im Studio: **Eigene Installation: Dry-Run** prueft das aktuelle Build.
**Dry-Run als neue Datei speichern** schreibt den geprueften Plan im Worker,
ohne bestehende Dateien zu ueberschreiben. **Vorhandenes Paket: Dry-Run**
prueft nach erneutem Studio-Start ein bewusst ausgewaehltes eigenes
`development-package`. Ein Build einer anderen Projektrevision wird nicht
als aktueller Projekt-Dry-Run verwendet.

```powershell
python tools\run_product.py plan-install --package work\generated\first-plugin\development-package --save work\generated\first-plugin\deployment-plan.json
```

Der Dry-Run prueft Dateien/Hashes und nur den beabsichtigten eigenen Link
unter `%LOCALAPPDATA%\Logi\LogiPluginService\Plugins\<Plugin-ID>.link`.
Er schreibt keinen Vendor-Link und startet keinen Service.
Unklare/fremde Kollisionen, veraenderte Pakete und fremde Zusatzdateien blockieren.

**Nur nach eigener Pruefung und bewusster Freigabe** die CLI verwenden:

```text
python tools\run_product.py install --plan <deployment-plan.json> --confirm-plugin-id <exakte ID aus Dry-Run> --receipts <neuer projektlokaler Receipt-Ordner>
python tools\run_product.py rollback --receipt <Receipt-Datei> --confirm-plugin-id <dieselbe exakte ID>
```

Die spitzen Klammern sind Platzhalter. Receipt vor Verlust schuetzen.
Rollback entfernt nur den eigenen neu erstellten Link oder stellt dessen
vorherige exakte Bytes wieder her. Nach externen Linkaenderungen verweigert
es den Eingriff. Pakete bleiben erhalten; keine Profile/Services werden
gesteuert. Hash-Rechecks und atomare Writes reduzieren Dateirennen, sind
keine vollstaendige Isolation gegen zeitgleich handelnde Prozesse desselben Kontos.

Nach einer bewusst genehmigten Installation im Studio den privaten Beleg
waehlen und **Rollback nur pruefen**. Erst nach exakter Plugin-ID-Eingabe
und gesonderter Dateiaenderungsbestaetigung wird das eigene Rollback
ausgefuehrt; der Worker prueft Ziel/Hashes/Backup erneut. Abbrechen, falsche
ID, geaenderter Beleg/Link oder fehlendes Paket veraendern nichts.
Der Log zeigt keine privaten Backupbytes. Keine Installation aus einem
blossen erfolgreichen Build heraus; keinen Service-/Profil-PASS unterstellen.

Plugin-Service-Reload/Neustart und Profilzuweisung ausschliesslich bewusst
durch den Nutzer in der Logitech-Umgebung. Erst danach physische Taste,
Display-Refresh, beide Aktionen, grosse Folder und Back/Pagination pruefen.
Notieren: Software-/Geraeteversion, Aktion, beobachtete Anzeige und Fehler.
Bis zu dieser Beobachtung bleibt der Produktstand HARDWARE_PENDING.

## 7. Fehler und sichere Wiederaufnahme

| Meldung/Situation | Handlung |
|---|---|
| Fehlendes PySide6 | Passende Python-Umgebung verwenden; Editor benoetigt PySide6 Widgets |
| SDK-DLL fehlt / dotnet fehlt | Buildpfad und lokale Installation pruefen; keine Hardwarefunktion behaupten |
| HOST_PORT_BUSY | Nur eigenen konkurrierenden Host beenden oder neues Paket mit `generate --port <freier Port>` erzeugen |
| PROJECT_MISMATCH / PLUGIN_MISMATCH | Projekt, Build und private Verbindung derselben Revision verwenden |
| HOST_UNTRUSTED | Falsche private Verbindung/Key/Port; nicht Authentisierung abschalten |
| HOST_HANDSHAKE / CONNECTION_* | Falsche ID-Typen/Schluesselform oder ungueltige signierte Serverantwort; passende Verbindung und Host pruefen |
| SAFE_EXPORT_REFUSED | Quellen nur lokal pruefen; kein Vollprojekt-ZIP als Ersatz teilen |
| Offline / stale | Host starten und Diagnose pruefen; Wert bleibt stale bis Vollsnapshot/Delta bestaetigt ist |
| STREAM_GAP / falscher Snapshot | Bridge verwirft ungueltige Daten und fordert Vollsnapshot an, kein Command-Replay |
| UNKNOWN_OUTCOME | Handler kann externe Effekte bereits ausgefuehrt haben; nicht blind erneut senden |
| COMMAND_CAPACITY / HOST_BUSY | Expliziten eigenen Host-Neustart bzw. Session-Timeout abwarten; keine alten Command-IDs vergessen |
| SCHEMA_NOT_PROVEN | Konservative Core-Portvertraege angleichen; keine ungeschuetzte Freigabe erzwingen |
| Disk-/Paketkonflikt | Neue Ausgabe/Datei verwenden oder bewusst neu laden, fremde Inhalte nicht loeschen |
| Plugin-Service zeigt nichts | Build, eigene Registrierung, Host und Profil getrennt pruefen; keine automatischen Serviceeingriffe |

Command-Deadline 5s, HTTP 2s, Queue 64, 16 Sessions/HTTP-Threads, Journal
1024 Records, 4096 Command-IDs pro Runtime, JSON-Tiefe 32, Request 64 KiB,
Response 1 MiB; Snapshot-Writes nutzen ein konservatives 512-KiB-Budget.
Groessere Projekte/Assets koennen diese expliziten Ressourcenlimits treffen.
Das ist kein geratebedingtes Vier-/Acht-Aktionslimit.

## 8. Evidenz und offene Capabilities

| Funktion | Erreichte Evidenz | Nicht behauptet |
|---|---|---|
| Core/Dispatcher/StateStore/Fake und alter Generator; FINAL-PRODUCT-01 Software-MVP | unabhaengige Abnahmen / PROCESS_PROVEN | Freigabe neuer Folgeaenderungen |
| C#-Bridge -> Python-Callback -> State-Delta | echte lokale Prozesse, Reconnect/stale, kein Replay, malformed Snapshot abgewiesen | echte SDK-Callbackausfuehrung |
| PySide6-Editor/Forms/Persistenz/PNG/Worker | Qt-Tests, nativer Windows-Workflow, realer Worker-SDK-Build | subjektive Nutzer-/Geraeteabnahme |
| SDK-Text/Bilder/DynamicFolder | echte SDK-Signaturen, kompilierte DLLs und echte Bitmap-Render-Probe 50/80/116px | LCD-Verhalten/Pagination am MX Keypad |
| Eigener Link und Rollback | Dry-Run; Install-/Rollbacktests nur in temporaeren Fake-Verzeichnissen | echte Logi-Installation/Service-Reload |
| Parameter/Adjustments/Multistate/Runtime-Membership | NOT_YET_SUPPORTED | stilles Ignorieren im Produktpfad |

Zusatztypen koennen im Editor ueber Manifeste sichtbar werden, brauchen aber
eine passende Produktimplementierung; unbekannte SDK-Typen werden explizit
blockiert. Live-View-Membership-Overrides, Action Editor, Profile-/Foreground-
Kontext, automatische Statepersistenz, Installer/Exe-Buendelung und externe
Anbindung sind nicht Teil des erreichten Durchstichs.

Entwickler-API: `src\runtime\README.md`. Tests, Exitcodes und lokale Hashes:
`work\autopilot\FINAL-PRODUCT-02\03_tests_und_evidenz.md`.

## 9. Sichere Reviewlieferung und isoliertes Hardwaregate

Im Build-Tab **Sicheres Review-Quellarchiv** verwenden oder
`python tools\package_result.py`. Nur das bereinigte `delivery\source-snapshot.zip`
und dessen Hashindex/SHA weitergeben. Der Export ist fuer Projektquellen und
geschriebene Reviewevidenz bestimmt, kein allgemeines Backup eines beliebigen
geoeffneten Benutzerprojekts. Verbindungen, Builds, Vendor-DLLs und private
Belege bleiben lokal. [Sicherer Export und kontrollierter Keywechsel](14_Sichere_Projektuebergabe.md).

Reproduzierbarer Drei-Aktions-Workflow:
`python tools\run_studio_workflow.py --out work\autopilot\FINAL-PRODUCT-02\mein-neuer-workflow`.
Das Ziel muss neu sein. Er bearbeitet echte Widgets und prueft generierte SDK-Bilder
und C#-Commands mit dem festen vertrauenswuerdigen Beispielhost.
Das vorbereitete Gate liegt unter `work\autopilot\FINAL-PRODUCT-02\hardware-test`.
Installationsplan, Beforekontrolle, Backup-/Rollbackweg und
[Beobachtungsanleitung](../work/autopilot/FINAL-PRODUCT-02/hardware-test/README.md)
sind vorbereitet, aber weder Registrierung noch Reload oder Hardwaretest freigegeben.
