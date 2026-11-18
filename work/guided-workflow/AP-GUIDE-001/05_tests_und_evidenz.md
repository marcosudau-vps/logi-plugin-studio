# 05 – Tests und Evidenz

Alle Läufe stammen aus dieser Arbeitssitzung. Ausführungsumgebung: Linux-Arbeitsumgebung von Claude
(Python 3.13, PySide6 6.12.0, Qt-Plattform `offscreen`, `LOCALAPPDATA` auf ein temporäres Verzeichnis gesetzt).
Unter Windows lief in dieser Sitzung **kein** Test; die Windows-Prüfungen sind Teil der Benutzerabnahme
([outputs/BENUTZERABNAHME.md](outputs/BENUTZERABNAHME.md)).

Aufruf: `tools/run_tests.py` (unverändert), Vergleich gegen die Ausgangsbasis über die sortierte Liste der
fehlgeschlagenen Tests (`evidence/tests/*_failures.txt`).

## Ausgangsbasis (Stufe 0)

Lauf auf dem unveränderten Start-Commit `3c7de52`: **1.208 Tests, 11 Fehlschläge, 32 Fehler, 37 übersprungen**
(`evidence/tests/baseline_linux_full.txt`). Unter Windows bestand derselbe Stand laut AP-POLISH-001 mit
1.208/1.208. Die 43 Abweichungen sind ausnahmslos durch die Linux-Umgebung bedingt:

| Anzahl | Ursache | Testmodule |
|---|---|---|
| 28 | Windows-Pfad der `PluginApi.dll` (`C:\Program Files\…`) gilt unter Linux nicht als absolut | `test_logitech_adapter`, `test_nf16_symbol_integration`, `test_review_folder_runtime`, `test_sdk_bridge_separation` |
| 8 | DPAPI-Schlüsselschutz bzw. Laufwerkswurzel nur unter Windows | `test_ap_polish_001`, `test_release_final_delivery_ui`, `test_release_final_pairing`, `test_logitech_adapter` |
| 4 | Windows-Python `python.exe` erwartet | `test_ap_polish_001` |
| 1 | Windows-asyncio-Modul `_overlapped` fehlt | `test_ap_polish_001` |
| 1 | Linkprüfung: historische Arbeitsakten unter `work/` sind (gewollt) nicht im Repository | `test_ap_polish_001` |
| 1 | Logitech-Installation und .NET fehlen | `test_native_folder_build_integration` |

**Abnahmeregel dieses Arbeitspakets:** Kein Test darf neu fehlschlagen. Jede neue Stufe wird gegen
`evidence/tests/baseline_linux_failures.txt` verglichen.

Ohne gesetztes `LOCALAPPDATA` scheitern unter Linux zusätzlich rund 200 Shell-Tests beim Anlegen des
`PairingStore`; das ist ebenfalls umgebungsbedingt und betrifft Windows nicht.

## Läufe je Stufe

| # | Stand | Tests | Neu fehlgeschlagen | Evidenz |
|---|---|---|---|---|
| T0 | Start-Commit `3c7de52` | 1.208 · 11 F · 32 E · 37 S | – (Basis) | `evidence/tests/baseline_linux_full.txt` |
| T1 | Stufe 1+2 (`feat/gefuehrter-ablauf`) | 1.235 | 1 → behoben (`test_v17…`: Programmeinstieg startet jetzt geführt; Test angepasst) | Konsolenausgabe, siehe Chronik |
| T2 | Stufe 4 (`97b98e6`) | 1.247 · 11 F · 32 E · 37 S | **0** | `evidence/tests/stufe4_full.txt`, `stufe4_failures.txt` |
| T3 | Stufe 3c + 5 (`feat/wartung`) | 1.256 · 11 F · 32 E · 37 S | **0** | `evidence/tests/stufe5_full.txt`, `stufe5_failures.txt` |
| T4 | Stufe 6 nach Begriffsliste, vor Testanpassung | 1.256 · 13 F · 32 E · 37 S | 2 (alter Wortlaut „letzte Action“) → Erwartung angepasst | Konsolenausgabe |
| T5 | Stufe 6 (`feat/abschluss-dokumentation`) | 1.256 · 11 F · 32 E · 37 S | 0 – identisch mit T0 | (überschrieben durch T6) |
| **T6** | **Endstand** nach Nachtrag (`feat/nachtrag-abschluss`) | **1.258 · 11 F · 32 E · 37 S** | **0** – Fehlschlagliste identisch mit T0 | `evidence/tests/final_full.txt`, `final_failures.txt` |

Neue Tests insgesamt: 50 (1.208 → 1.258). Angepasste Bestandstests: 4, nur erwartete Formulierungen.

## Neue Testmodule

| Modul | Inhalt | Tests |
|---|---|---|
| `tests/test_workflow_model.py` | Qt-frei: Fakten → Schrittstatus, Sperren, Veralten, benutzerlokaler Speicher | 14 |
| `tests/test_workflow_shell.py` | echte Shell: Sichtbarkeit je Schritt, Expertenmodus, Build-Sperre, Checkliste, Hilfe, Problemliste, Übersichten, Belegung, Wartung, Gerätetest | 19 |
| `tests/test_handler_inspector.py` | Handler-Lebenszyklus Qt-frei und in der Shell, Handlerdatei aus Vorlage | 10 |
| `tests/test_maintenance.py` | Wartung mit Attrappe der Installationsfunktionen: Zeilen, Deaktivieren/Reaktivieren, Fenster | 5 |
| `tests/test_workflow_qt_free.py` | Qt-freie Module ohne PySide6 importierbar; Ordnerregel gleich `build_mode_store` | 2 |

## Sichtprüfung

Bildschirmfotos aus der Offscreen-Darstellung (Schriftart und Stil weichen von Windows ab) unter
`evidence/screenshots/`. Sie belegen Aufbau und Sichtbarkeit, nicht das Windows-Erscheinungsbild.
