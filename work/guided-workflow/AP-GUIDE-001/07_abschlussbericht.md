# 07 – Abschlussbericht AP-GUIDE-001

**Stand 18.11.2026 · Status: `READY_FOR_REVIEW`** – Quellstand für Release-Kandidat **1.0.0-rc2**. Keine
Selbstabnahme, kein Merge nach `main`, kein Release-Build. Die Prüfung unter Windows und die Benutzerabnahme
([outputs/BENUTZERABNAHME.md](outputs/BENUTZERABNAHME.md)) stehen aus.

## Ergebnis

Das native Studio führt jetzt in sieben Schritten vom Projekt bis zur getesteten Taste am Gerät:

**1 Projekt → 2 Handler → 3 Aktionen → 4 Darstellung → 5 Belegung → 6 Prüfen und Bauen → 7 Installieren und Testen**

Je Schritt sind nur die passenden Registerkarten, Seitenbereiche und Werkzeuge sichtbar. Jeder Schritt hat eine
Checkliste mit prüfbaren Kriterien; ein Schritt wird erst frei, wenn die vorherigen abgeschlossen sind. Die
bestehende Hilfe erklärt den nächsten Handgriff, offene Punkte erscheinen in der bestehenden Problemliste, der
Build startet nur bei gespeichertem und fehlerfreiem Stand, veraltete Builds und Installationen werden erkannt,
und der Gerätetest wird vom Anwender bestätigt. Der Expertenmodus stellt die freie Ansicht jederzeit her.

| Stufe | Ergebnis | Status | Commit auf `release/1.0.0` |
|---|---|---|---|
| 0 Ausgangsbasis | Repository, Branch-Schema, Start-Commit, Basislauf | SOFTWARE_VERIFIED | `3c7de52` |
| 1+2 Konzept und Gerüst | Spezifikation, Schrittmodell, Schrittleiste, Startseite, Sichtbarkeit, Führungsthemen, Menü, Symbolleiste, Alles speichern, Expertenmodus, Build-Sperre | SOFTWARE_VERIFIED | `636a9bb` |
| 3a HandlerInspector | Handler anlegen/umbenennen/löschen, Handlerdatei aus Vorlage, statische Prüfung | SOFTWARE_VERIFIED | `35f9436` |
| 3b Übersichten | Zustände (SDK- vs. Python-Zustand), Symbole | SOFTWARE_VERIFIED | `4ceb4ed` |
| 4 Bauen und Installieren | deutsche Statuswerte, beschriftete Bereiche, Options+-Hinweis, Gerätetest | SOFTWARE_VERIFIED | `1e78b76` |
| 3c Belegung | nur über virtuelle Ordner (Entscheidung 2) | SOFTWARE_VERIFIED | `f1b5102` |
| 5 Wartung | Plugins neu laden, deaktivieren, reaktivieren, Protokoll, Voraussetzungen | SOFTWARE_VERIFIED | `caf0a44` |
| 6 Abschluss | Begriffsliste, Handbuch, STATUS/CHANGELOG/README, Benutzerabnahme, Version 1.0.0-rc2, Zeilenenden korrigiert | SOFTWARE_VERIFIED | siehe [04](04_git_und_branches.md) |

## Architektur

Unverändert: ARCH-ADR-001 (Native First), `NativeProjectSession` und `ExtensionStore` bleiben alleinige Writer
ihrer Dateien, `StudioCoordinator` bleibt einziger Host, eine Hilfe, eine Problemliste. Der Ablauf ist ein
Konstruktorschalter (`workflow=True`), besitzt keine Projektdaten und berechnet den Schrittstatus bei jeder
Änderung neu. Benutzerlokal gemerkt werden nur Bedienzustände. Neue Projektänderungen (Handler) laufen über neue
Coordinator-Operationen mit demselben Guard und genau einem `replace` wie bei Aktionen. Bridge, Generator,
Projektformat, Laufzeit und Legacy-Editor sind unverändert. Neue Verbindungen V-90 bis V-107 stehen mit
Testfunktion im Verbindungsregister.

## Prüfstand

* Vollregression (Linux/offscreen): **1.256 Tests**, davon 48 neu. Fehlschlagliste **identisch mit der
  Ausgangsbasis** (43 rein umgebungsbedingte Abweichungen, siehe [05](05_tests_und_evidenz.md)); **0 neue
  Fehlschläge**. Evidenz: `evidence/tests/final_full.txt`, `final_failures.txt`.
* Angepasste Bestandstests: 4, jeweils nur die erwartete Formulierung (`test_v17…` geführter Programmeinstieg;
  drei Prüfungen auf „Action“ → „Aktion“ gemäß Begriffsliste).
* Sichtprüfung offscreen: `evidence/screenshots/` (Schritte 1–6, Expertenmodus, Wartung).

## Wichtigste Befunde

1. **Unbenutzte Handlerregistrierung bricht den Host.** `runtime/host.py` lehnt Handler ab, die keine Aktion
   verwendet. Die Vorlage registriert deshalb nur verwendete Handler, und eine Datei mit unbenutzten
   Registrierungen wird als Fehler gemeldet.
2. **Tastenvorschau zeigte bei neuen Projekten den nur lesbaren SDK-Folder.** Im Schritt Belegung stellt der
   Ablauf jetzt auf das bearbeitbare virtuelle Autorenmodell um.
3. **Extensionänderungen lösten keine Aktualisierung aus.** Der Schrittstatus folgt jetzt sofort.
4. **Zeilenenden.** In Stufe 2–5 wurden fünf CRLF-Quelldateien beim Bearbeiten auf LF umgestellt (große
   Schein-Diffs). In Stufe 6 auf die ursprünglichen CRLF-Zeilenenden zurückgesetzt; seither werden Dateien mit
   unverändertem Zeilenende bearbeitet. `.gitattributes` verhindert Umwandlungen durch Git.
5. **Dienst-Neustart.** Kein belegter sicherer Weg; bewusst nicht angeboten (siehe [06](06_offene_punkte.md)).

## Grenzen

* Kein Test unter Windows in dieser Sitzung (Qt-Darstellung, echter C#-Build, Installation, Tastendruck).
* Kein Release-Build 1.0.0-rc2 (benötigt Windows, PyInstaller, Inno Setup).
* Wartung mit Attrappe der Installationsfunktionen getestet; die Funktionen selbst sind unverändert.

## Nächste Schritte

1. Stand holen (GitHub `release/1.0.0` oder gespiegelter lokaler Projektordner) und unter Windows
   `python tools/run_tests.py` ausführen.
2. Benutzerabnahme nach [outputs/BENUTZERABNAHME.md](outputs/BENUTZERABNAHME.md).
3. Optional `python tools/packaging/build_release.py` für Setup und Portable 1.0.0-rc2.
4. Nach deiner Freigabe: Merge `release/1.0.0` → `main` als Release-Commit 1.0.0.
