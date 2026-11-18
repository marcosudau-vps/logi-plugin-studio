# Benutzerabnahme – Logitech Plugin Studio 1.0.0-rc2 (geführter Ablauf)

Diese Abnahme ist **deine** praktische Bewertung unter Windows. Sie ist nicht vorab ausgefüllt und gilt erst nach
deiner Durchführung. Sie ersetzt für den neuen Ablauf die Abnahme von 1.0.0-rc1
(`work/polish/AP-POLISH-001/outputs/BENUTZERABNAHME.md`); deren Schritte zu Installation, Pairing und Rollback
gelten weiter und sind hier in Schritt 9–12 aufgenommen.

**Vorbereitung**

* Stand holen: Branch `release/1.0.0` aus `https://github.com/marcosudau-vps/logi-plugin-studio` (oder der
  gespiegelte lokale Projektordner, siehe Abschlussbericht).
* Entwicklerstart: `python tools/run_studio.py --native` (Python 3.12, `requirements-dev.txt`).
* Optional zuerst die Tests unter Windows: `python tools/run_tests.py` – erwartet: **alle Tests bestanden**
  (1.256; unter Windows entfallen die 43 rein umgebungsbedingten Linux-Abweichungen).
* Optional Release-Build: `python tools/packaging/build_release.py` (PyInstaller, Inno Setup) → Setup und Portable 1.0.0-rc2.
* MX Creative Keypad angeschlossen, Logi Options+ läuft. Notizen in der Spalte „Notizen“; Stichworte genügen.

Bewertung je Abschnitt (optional): **++** sehr gut · **+** gut · **o** geht so · **–** umständlich · **– –** blockiert.

---

## 1. Start ohne Projekt

* **Tun:** Studio starten.
* **Erwartet:** Menüleiste (Datei, Bearbeiten, Ablauf, Werkzeuge, Hilfe), Schrittleiste mit sieben Schritten, nur
  Schritt 1 bedienbar, Registerkarten nur „Start“ und „Hilfe“. Startseite mit „Neues Projekt …“, „Vorhandenes
  Projekt öffnen …“ und „Wartung …“.
* **Achte auf:** Ist sofort klar, wo man beginnt? Passt das Fenster auf den Bildschirm?

| Bewertung | Notizen |
|---|---|
| | |

## 2. Schritt 1 – Projekt anlegen

* **Tun:** „Neues Projekt …“ → Plugin-ID (z. B. `mein.testplugin`), Anzeigename, Speicherort.
* **Erwartet:** Schritt 1 ✔, das Studio springt zu Schritt 2 „Handler“. Links die Projektübersicht.
* **Achte auf:** Versteht man „Plugin-ID“ ohne Vorwissen?

| Bewertung | Notizen |
|---|---|
| | |

## 3. Schritt 2 – Handler

* **Tun:** Checkliste lesen. „Handlerdatei aus Vorlage erzeugen“. Danach einen weiteren Handler anlegen,
  umbenennen und wieder löschen.
* **Erwartet:** Datei `<Projekt>_handlers.py` liegt neben dem Projekt; Checkliste ✔; „Weiter →“ wird aktiv.
  Ein Handler, den eine Aktion verwendet, lässt sich nicht löschen (Tooltip erklärt warum).
* **Achte auf:** Ist erklärt, was ein Handler ist und was in die Datei gehört? Die Datei in einem Editor öffnen:
  verständlich?

| Bewertung | Notizen |
|---|---|
| | |

## 4. Schritt 3 – Aktionen

* **Tun:** „Weiter →“. „+ Neue Aktion“ → Typ und Namen wählen → „Übernehmen“. Registerkarte „Zustände“ ansehen.
  Einen Entwurf im Aktionsinspektor ändern und **nicht** übernehmen.
* **Erwartet:** Solange ein Entwurf offen ist, zeigt die Checkliste „Kein offener Entwurf“ als offen und „Weiter →“
  ist gesperrt. Nach „Übernehmen“ wieder frei. „Zustände“ zeigt z. B. „0 Aus, 1 An“.
* **Achte auf:** Begriffe einheitlich („Aktion“)? Unterschied „Übernehmen“ / „Alles speichern“ klar?

| Bewertung | Notizen |
|---|---|
| | |

## 5. Schritt 4 – Darstellung (optional)

* **Tun:** „Weiter →“. In „Symbole“ eine Aktion wählen → „Im SymbolDesigner bearbeiten …“ → Symbol gestalten,
  speichern, schließen.
* **Erwartet:** Die Zeile zeigt „eigene Symbolvorlage“. Ohne Symbol ist der Schritt „optional“ und sperrt nichts.

| Bewertung | Notizen |
|---|---|
| | |

## 6. Schritt 5 – Belegung (optional)

* **Tun:** „Weiter →“. Im „Keypad“ eine Aktion aus dem Katalog auf den freien Platz ziehen. Dann „Virtuelle
  Ordner“ ansehen. Danach **Strg+S**.
* **Erwartet:** „Bearbeiten“ ist schon eingeschaltet, die Quellenauswahl zeigt „Virtuelle Ordner (Autorenmodell)“
  und ist gesperrt. Vor dem Speichern ist „Ordner und Belegung gespeichert“ offen, danach ✔.
* **Achte auf:** Ist die Vorschau verständlich? Fehlt die Bearbeitung der SDK-Folder (Expertenmodus) jemandem?

| Bewertung | Notizen |
|---|---|
| | |

## 7. Schritt 6 – Prüfen und Bauen

* **Tun:** „Weiter →“. Plugin-Typ wählen, „Voraussetzungen prüfen“, Werkzeug „SDK-Plugin bauen“. Danach den
  Anzeigenamen einer Aktion ändern, Strg+S, Schritt 6 erneut ansehen.
* **Erwartet:** Meldung „Build erfolgreich … weiter mit Schritt 7“. Nach der Änderung steht „Plugin erfolgreich
  gebaut“ auf ↻ veraltet und Schritt 7 ist gesperrt, bis neu gebaut wurde. Mit ungespeicherter Änderung verweigert
  das Studio den Build mit einer verständlichen Meldung.

| Bewertung | Notizen |
|---|---|
| | |

## 8. Schritt 7 – Installieren und Testen

* **Tun:** „Weiter →“ → „Plan anzeigen“ → „Installieren / Aktualisieren …“ → „Ladezustand prüfen“. Den Hinweis im
  Protokoll befolgen: in Logi Options+ eine Aktion auf eine Taste legen und drücken. **Studio schließen**, Taste
  erneut drücken. Studio öffnen, in der Checkliste „Am Gerät getestet und bestätigt“ doppelklicken.
* **Erwartet:** Statuswerte auf Deutsch („installiert“, „geladen“, „aktiv“); nach der Bestätigung „am Gerät
  bestätigt“ und alle sieben Schritte ✔; der Hinweis „Fertig“.
* **Achte auf:** Ist der Schritt „in Options+ zuweisen“ ausreichend angeleitet?

| Bewertung | Notizen |
|---|---|
| | |

## 9. Wartung

* **Tun:** *Werkzeuge → Wartung …*. Das eigene Plugin wählen: „Protokoll anzeigen“, „Plugin neu laden“,
  „Deaktivieren …“, danach „Reaktivieren“. Ein fremdes Plugin wählen.
* **Erwartet:** Nach dem Deaktivieren steht das Plugin auf „deaktiviert“ und Schritt 7 im Hauptfenster wird wieder
  offen; nach dem Reaktivieren ist es zurück. Fremde Plugins: keine Knöpfe aktiv.
* **Achte auf:** Fehlt der Neustart des ganzen Dienstes, oder reicht „Plugin neu laden“?

| Bewertung | Notizen |
|---|---|
| | |

## 10. Expertenmodus

* **Tun:** Häkchen „Expertenmodus“. Alle Registerkarten durchsehen; einen SDK-Folder in der Keypad-Quellenauswahl
  wählen. Häkchen wieder entfernen. Studio neu starten.
* **Erwartet:** Alles gleichzeitig erreichbar, Schrittstatus weiter sichtbar. Nach dem Ausschalten wieder
  geführt; die Wahl bleibt nach dem Neustart erhalten.

| Bewertung | Notizen |
|---|---|
| | |

## 11. Weitermachen nach Neustart

* **Tun:** Studio schließen, wieder öffnen, dasselbe Projekt öffnen.
* **Erwartet:** Das Studio steht im zuletzt aktiven Schritt; die Handlerdatei ist zugeordnet. Die Projektdatei
  enthält keine Ablaufdaten.

| Bewertung | Notizen |
|---|---|
| | |

## 12. Aus 1.0.0-rc1 übernommen

Rollback/Deinstallation (rc1 Schritt 15) und – optional – Shared-Plugin mit Pairing (rc1 Schritt 12–13; die
Registerkarte „Shared-Peers“ erscheint in Schritt 7, wenn der Plugin-Typ „Shared DynamicFolder“ gewählt ist).

| Bewertung | Notizen |
|---|---|
| | |

---

## Gesamtfragen

| Frage | Antwort |
|---|---|
| Fühlt man sich durch die Plugin-Erstellung geführt? | |
| Sind die Sperren nachvollziehbar, oder stören sie? | |
| Sind Schrittleiste und Checkliste verständlich? | |
| Erklärt die Hilfe („Mehr dazu“, F1) den nächsten Schritt ausreichend? | |
| Sind die Begriffe einheitlich und verständlich? | |
| Was würdest du intuitiv anders erwarten? | |
| Freigabe für den Merge von `release/1.0.0` nach `main`? | |
