# 09 – Technischer Ist-Stand, Evidenz und Abnahmeregeln

**Zweck:** Keine unbegründeten Aussagen wie „funktioniert“ ohne Angabe von Testobjekt, Versionsstand und Prüfumgebung. Dieses Dokument ist der Nachweisindex, **kein Ersatz für Original-Logs**.

## 1. Bekannte historische Stände

| Teilprojekt | Stand | Was er repräsentiert | Was er **nicht** repräsentiert |
|---|---|---|---|
| SDK Lab | v0.1.4 | auf MX Creative Keypad getestete C#↔Python-Bridge und Live-Folder-Veränderungen | produktive generische Modell-Runtime |
| Plugin Studio | v0.2 im `Logi_SDK_DevKit_v0.2.zip` | Projektgenerator, PySide6-UI, Build-/Link-Deployment, Bibliothekssnapshots | freie Aktions-/State-/Layoutmodellierung nach diesem Entwurf |
| Architekturmodell | v0.1 | akzeptierte fachneutrale Baseline | endgültiges JSON-Schema |
| Metamodell | v0.2-Draft | konkrete Entitäten und Bindings als Vorschlag | freigegebener Klassen-/API-Vertrag |
| Dieses Paket | v0.3 Dokumentation | strukturierte Übergabe und Terminologie | zusätzliche Implementierung oder neu geprüfte Hardware |

## 2. Belegte Lab-Funktionen

Die folgende Matrix basiert auf den Nutzerrückmeldungen und der vorhandenen DevKit-Feature-Matrix. Der Nutzer hat die relevanten Funktionen auf seinem MX Creative Keypad selbst ausprobiert; Originalausgaben/Screenshots können in einer separaten Arbeitsakte archiviert werden.

| Fähigkeit | Lab-Gerätestatus | Studio-generisch | Kommentar |
|---|---|---|---|
| Plugin in Options+ sichtbar und Aktionen belegbar | bestätigt | Studio-Generator: Registrierung/Build gemeldet | nicht gleich eine frei entworfene Aktion |
| `RunCommand`-Callback / Keypad→C# | bestätigt | generischer Adapter offen | C#-Log zeigt `CALLBACK: action=ping` |
| C#→Python-HTTP-POST | bestätigt | generische Host-API offen | v0.1.3 HTTP-413-Fehler behoben |
| Python→C#-Zustandsabfrage | bestätigt | Snapshot-API offen | `GET /state` / Revisionen geloggt |
| Dynamic Folder betreten/verlassen | bestätigt | generisches View-Modell offen | Gerätetest Nutzer |
| Live-Änderung 4↔8 Folder-Aktionen | bestätigt in Lab v0.1.4 | beliebige logische Collection offen | dynamische Refresh-Notifications |
| Kontext-/Farbwechsel | bestätigt | freie Presentation-Varianten offen | Demo-Statusnamen noch nicht generalisiert |
| Counteränderungen | bestätigt | typisierter beliebiger State offen | Persistenzgrenze beachten |
| Counter über LPS-Neustart | bestätigt, solange Python lief | allgemeiner Recovery-Test offen | kein Nachweis über Python-Restart |
| Native Adjustment-Werte | Callback/Übertragung bestätigt | gerätespezifische Eingabearten offen | im Log `dial_delta` mit pos./neg. Werten |
| Multistate Commands | nicht abgenommen | nicht verfügbar | eigenständiger Lab-Test nötig |
| Action Editor | nicht abgenommen | nicht verfügbar | eigenständiger Lab-Test nötig |

## 3. Wichtiges Gegenbeispiel aus der Historie

- **Vor v0.1.3:** `POST /event` schlug mit HTTP 413 fehl, obwohl Logitech-Callbacks im C#-Log eindeutig ankamen. Ursache war die unpassende Behandlung von HTTP-Body-Längen/Chunked-Übertragung zwischen Client und Python-Server.
- **v0.1.3:** `POST /event` liefert `200 OK`; Python-Diagnose zeigte mehrere empfangene Events, u. a. `ping` und `dial_delta`.
- **v0.1.4:** Die Live-Aktualisierung des Dynamic Folders funktionierte nach zusätzlichen Diagnose-/Refresh-Anpassungen. Der Benutzer bestätigte anschließend alle vier GUI-Steueroptionen einschließlich Farbe, Kontext, 4↔8 und Counter.

**Lehre:** Ein SDK-Callback, ein HTTP-Response, eine Python-Vorschau, eine tatsächliche Geräteanzeige und ein persistierter Wert sind **verschiedene Nachweiskategorien**.

## 4. Freigabestufen je Bibliothekstyp

1. `idea`: fachneutrales Ziel definiert.
2. `lab_implemented`: SDK-Code, automatisch testbar.
3. `lab_hardware_verified`: konkrete Version auf realem Gerät mit Schritten/Logs/Ergebnis geprüft.
4. `generalized`: Demo-Konstanten durch validierte Konfiguration ersetzt; Typ-/Portvertrag definiert.
5. `library_frozen`: unveränderliche Version, SHA-256, Abhängigkeiten, Evidenz.
6. `studio_generated`: aus einem konkreten Modell erfolgreich generiert und gebaut.
7. `studio_hardware_verified`: **genau dieses generierte Plugin** auf Gerät getestet.
8. `reusable_stable`: dokumentierte Wiederholung, Upgrades, Fehlerfälle, Sicherheits-/Lifecycle-Abnahme.

„Lab-Hardware-PASS“ darf nicht automatisch zu „Studio-Hardware-PASS“ vererbt werden. Ein Komponentenmanifest sollte die Evidenzdatei referenzieren.

## 5. Minimaler Hardware-Abnahmeplan für den ersten Core-Model-Vertical-Slice

| Test-ID | Test | Erwartung / Ergebnisbedingung |
|---|---|---|
| V-001 | eigenes Plugin mit eigener ID aus Projekt generieren | Build, Registrierung, Options+-Sichtbarkeit |
| V-002 | drei beliebig benannte CommandActions konfigurieren | keine Demo-Konstanten in öffentliches Verhalten geleakt |
| V-003 | Aktion in zwei Views platzieren | gleiche ComponentInstance, getrennte Placements, korrektes Verhalten |
| V-004 | Taste drücken | exakte Action-ID und Payload beim Host-Handler |
| V-005 | Host ändert typisierten State | Runtime-Replik und Presentation folgen ohne Build |
| V-006 | Host wählt andere Icon-/Textvariante | Hardware zeigt eindeutig neue Variante |
| V-007 | Dynamic Folder Mitgliedschaft N→M→N ändern | Ergebnis auf Gerät, keine kaputte Callback-Zuordnung |
| V-008 | Logitech-Service neu starten | neue Session, Snapshot, Anzeige konsistent |
| V-009 | Python-Host unterbrechen/wiederverbinden | Health/Quality sichtbar; nach Reconnect korrekt synchronisiert |
| V-010 | ungültiges Modell (ID doppelt, falscher Typ, fehlender Port) | Validator blockiert Build mit präziser Diagnose |
| V-011 | zwei Plugins parallel mit verschiedenen Identitäten | kein Port-/Registry-/State-Konflikt |
| V-012 | Plugin neu generieren/aktualisieren | bestehende stabile Action-IDs/Bindings bleiben erhalten oder bewusste Migrationswarnung |

Die tatsächlichen Tests werden erst nach Implementierung ausgeführt; diese Tabelle ist **Plan**, nicht Ergebnis.

## 6. Evidenzvorlage

Siehe `../work/templates/TESTNACHWEIS_VORLAGE.md`. Ein Nachweis hält mindestens Version/Hash, Gerät, Logi Options+/SDK-Version (soweit ermittelt), Schritte, erwartete und tatsächliche Ergebnisse, Logs, Pass/Fail und Grenzen fest.


## Abgrenzung der P0-Spike-Tests

Die P0-v0.4-Tests prüfen ausschließlich ein minimales Python-Validator-Modell, keine neue Logitech-Hardwarefunktion. Die Quellcodeübernahme in `src/core_spike/` und die Tests unter `tests/` dienen als **experimentelle Referenz**, nicht als freigegebene Implementierung des neuen Cores. Siehe [P0-Präzisierungen](11_P0_Praezisierungen.md).
