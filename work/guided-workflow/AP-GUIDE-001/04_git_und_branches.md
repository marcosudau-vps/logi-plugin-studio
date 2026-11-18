# 04 – Git und Branches

Repository: `https://github.com/marcosudau-vps/logi-plugin-studio` (öffentlich). Schema laut Auftrag
([01_auftrag.md](01_auftrag.md)).

## Branches

| Branch | Zweig von | Inhalt | Merge-Ziel |
|---|---|---|---|
| `main` | – | Ein Commit „Repository initialisieren“ (nur README). Je fertiger Release-Version genau ein weiterer Commit. | – |
| `release/1.0.0` | `main` | Start-Commit „Ausgangsstand 1.0.0-rc1“, danach **je Feature ein Commit** (Squash des Feature-Branches) | `main`, **erst nach deiner Freigabe** |
| `feat/gefuehrter-ablauf` | `release/1.0.0` | Feature „Geführter Ablauf“ | `release/1.0.0` |
| `ap/GUIDE-01-konzept-und-modell` | `feat/gefuehrter-ablauf` | Spezifikation, Schrittmodell, Speicher | `feat/gefuehrter-ablauf` (Merge-Commit) |
| `ap/GUIDE-02-schrittleiste-und-shell` | `feat/gefuehrter-ablauf` | Schrittleiste, Startseite, Shell-Steuerung | `feat/gefuehrter-ablauf` (Merge-Commit) |
| `feat/handler-inspector` | `release/1.0.0` | Feature „HandlerInspector“ | `release/1.0.0` |
| `feat/uebersichten-zustaende-symbole` | `release/1.0.0` | Feature „Übersichten Zustände und Symbole“ | `release/1.0.0` |
| `feat/bauen-und-installieren-gefuehrt` | `release/1.0.0` | Feature „Bauen und Installieren im Ablauf“ | `release/1.0.0` |
| `feat/belegung-virtuelle-ordner` | `release/1.0.0` | Feature „Belegung über virtuelle Ordner“ | `release/1.0.0` |
| `feat/wartung` | `release/1.0.0` | Feature „Wartung“ | `release/1.0.0` |
| `feat/abschluss-dokumentation` | `release/1.0.0` | Feature „Begriffe, Dokumentation und Abschluss“ | `release/1.0.0` |

Weitere Feature-Branches werden hier ergänzt.

Die Arbeitsakte wird auf dem jeweils laufenden Feature-Branch fortgeschrieben und gelangt mit dessen
Feature-Commit auf den Release-Branch. So zeigt jeder Feature-Commit auch den zugehörigen Aktenstand.

Die Feature-Branches bleiben nach dem Squash auf dem Release-Branch erhalten; sie enthalten die einzelnen
Arbeitsschritte. Der Release-Branch zeigt je Feature genau einen Commit.

## Was im Repository liegt und was nicht

Das Repository ist öffentlich. Deshalb ergänzt `.gitignore`:

- **Logitech-Herstellerdokumentation** `references/logitech-sdk/PluginApi.xml` und
  `logi-actions-sdk-llms-full.md` bleibt lokal (keine Weiterverteilung fremder Dokumentation).
- **Historische Arbeitsakten** unter `work/` bleiben lokal (Evidenz, Protokolle, Rechner- und Gerätedaten,
  rund 1,5 GB). Versioniert sind nur `work/README.md`, `work/templates/`, `work/planning/` und ab diesem
  Arbeitspaket `work/guided-workflow/`.
- `.gitattributes` schaltet die Zeilenende-Umwandlung ab, weil viele Dateien per SHA-256 referenziert sind.

Vor dem Start-Commit wurden alle Dateien mit den Erkennungsmustern des sicheren Exports
(`src/delivery/export.py`) auf Geheimnisse geprüft: kein Fund (einziger Namenstreffer ist das Quellmodul
`secret_store.py` selbst).

## Commits auf `release/1.0.0`

| Commit | Inhalt |
|---|---|
| `3c7de52` | Ausgangsstand 1.0.0-rc1 (AP-POLISH-001) |
| `636a9bb` | Feature: Geführter Ablauf in sieben Schritten |
| `35f9436` | Feature: HandlerInspector |
| `4ceb4ed` | Feature: Übersichten Zustände und Symbole |
| `1e78b76` | Feature: Bauen und Installieren im Ablauf (mit Anlage dieser Arbeitsakte) |

| `f1b5102` | Feature: Belegung über virtuelle Ordner |
| `caf0a44` | Feature: Wartung |
| (letzter Commit) | Feature: Begriffe, Dokumentation und Abschluss – enthält den Endstand dieser Akte |

Der Merge nach `main` erfolgt erst nach deiner Freigabe (siehe [07_abschlussbericht.md](07_abschlussbericht.md)).
