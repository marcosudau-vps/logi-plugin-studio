# Änderungshistorie der kanonischen Gesamtfassung

> **Architekturentscheidung 03.11.2026:** [ARCH-ADR-001](docs/decisions/ARCH-ADR-001.md), [SDK-Modellabgleich](docs/specifications/sdk-native-modellabgleich-v01.md), [Konsolidierungslog](work/planning/native-first-konsolidierung-20261103.md). **Dokumentationsänderung; kein SDK-/Projektformatumbau.**

## 18.11.2026 – AP-GUIDE-001 Geführter Ablauf, Release-Kandidat 1.0.0-rc2, READY_FOR_REVIEW

- Geführter Ablauf in sieben Schritten als abschaltbare Komfortschicht (`NativeStudioShell(..., workflow=True)`; Programmeinstieg startet geführt): Schrittleiste mit Checkliste und nächstem Handgriff, Startseite, Sichtbarkeit je Schritt, Führungsthemen in der bestehenden Hilfe, offene Punkte in der Problemliste, Build-Sperre bei ungespeichertem oder fehlerhaftem Stand, Erkennung veralteter Builds, bestätigter Gerätetest. Expertenmodus für die freie Ansicht.
- Neu: HandlerInspector, Übersichten Zustände und Symbole, Wartungsfenster, Menüleiste, Symbolleiste, „Alles speichern“ (Strg+S im geführten Ablauf), deutsche Statuswerte, Begriffsliste (`docs/architecture/studio/Begriffe.md`).
- Belegung im geführten Ablauf nur über virtuelle Ordner; native SDK-Folder bleiben Anzeige (Entscheidung des Auftraggebers).
- Kein neues Fachmodell, kein neuer Writer; Ablaufzustand nur benutzerlokal. Verbindungen V-90 bis V-107.
- Git-Repository mit Release-Branch `release/1.0.0`; Herstellerdokumentation und historische Arbeitsakten bleiben lokal.
- 3 Bestandstests nur im erwarteten Wortlaut angepasst (Begriffsliste), 1 Bestandstest für den geführten Programmeinstieg. Details: `work/guided-workflow/AP-GUIDE-001/07_abschlussbericht.md`.

## 09.11.2026 – AP-POLISH-001 Release-Kandidat 1.0.0-rc1, READY_FOR_REVIEW

- Ein Release-Befehl (`tools/packaging/build_release.py`) erzeugt Setup (Inno Setup) und Portable aus demselben Payload; zentrale Version `src/studio/version.py`; Manifest, Hashlisten, Lizenzhinweise, Verifikation.
- Pluginlokale Host-Laufzeit (`bin/hostruntime-<id>`, Record `studio-host-runtime-2`, neue Vorlage `HostChild.cs.in`): native/kompatible/Shared-Plugins starten ihren Host selbst; Integritätsprüfung ohne Fallback; Sperrbehandlung bei Updates; Migration alter absoluter Hostpfade beim nächsten Update.
- DPAPI-geschützte Pairing-Schlüssel mit Migration; Plugin-Typ je Projekt benutzerlokal gemerkt; Installationstexte (Verzeichnis/Link), Options+-Hinweis; Links an der Quelle korrigiert.
- Befunde behoben: Host lehnte ab Befehl 4.097 alles ab (`runtime/host.py`, begründet); gefrorener Runner importierte `_asyncio` vor `asyncio` (Shared-Peers verbanden sich unter dem Runner nie); Mindestfensterbreite 1.621 → 1.311 px.
- 28 neue Tests; Gesamtregression 1.208/1.208. Details: `work/polish/AP-POLISH-001/10_abschlussbericht.md`.

## 03.11.2026 – AP-WIDGET-001 SymbolDesignerWidget v1, READY_FOR_REVIEW

- Neues Paket `src/symbol_designer/`: natives ICT-Bearbeitungs-Widget (Bibliothek, Zeichenfläche mit
  Anfassern, Eigenschaften, Undo/Redo, Layoutvorlagen, „Für mehrere übernehmen“), Export ICT/PNG/SVG/
  Action-Symbol, nur lesende Einbindung installierter Logitech-Icon-Pakete, Symbol Designer Lab.
- 31 neue Tests; Gesamtregression 346/346. Kein Gerätetest, keine Installation, Projektmodell und
  C#-Generator unverändert. Nachtrag: Absturz durch doppelt freigegebene Bibliotheks-Ziehdaten behoben,
  Lab mit Diagnoseprotokoll. Details: `work/widget-lab/icon-designer-v1/README.md`.

## 01.11.2026 – FINAL-PRODUCT-02, Folgelieferung READY_FOR_REVIEW

- Unabhängige Software-MVP-/PROCESS_PROVEN-Abnahme von FINAL-PRODUCT-01
  eingeordnet; ursprüngliche Akten und akzeptierte Architektur unverändert.
- Fail-closed Quellarchivexport mit Scope-, Secret-, Symlink-/Junction-,
  CRC-/SHA- und Ausgabe-Ownership-Gates. Kein Vollprojekt-ZIP als sichere Lieferung.
- 29 neue Regressionstests; 310/310 einschließlich der 281 bisherigen Tests.
- Native Drei-Aktions-Editor→SDK→Standalone-Python→C#-Kette, referenzielles
  Rename, zwei Views und wiederverwendete Placements ohne Demo-Mengenlimit.
- Bestätigte Connection-Typ-, Handshake-, stale-Build- und Previewwechsel-
  Fehler abgesichert. Keine Abschwächung der Core-/Scope-/Nicht-Replay-Verträge.
- Studio: speicherbarer Dry-Run, vorhandene Paketprüfung, read-only
  Rollbackvorschau, exakte ID-/Dateibestätigung und sicherer Export-Worker.
- Optionale proportionale PNG-Darstellung und skalierbare Schriftgrößen,
  reale SDK-Signaturen und Bitmaprender-Probe 50/80/116px.
- Isoliertes Paket studio.mx.keypad02 mit realem SDK-Build, Prozessprüfung,
  exaktem Installationsdryrun, Beforekontrolle und vorbereitetem Rollback.
  Keine Registrierung, kein Logitech-Reload, keine Profil-/Hardwarefreigabe.
- Gesamtprodukt bleibt PARTIAL / HARDWARE_PENDING; keine Selbstabnahme.

## 31.10.2026 – FINAL-PRODUCT-01, Entwicklungslieferung READY_FOR_REVIEW

- Authentisierte lokale Python-Host-API und generierte C#-Bridge auf den
  bestehenden Core-/Dispatcher-/StateStore-Schichten.
- Snapshot/Deltas, expiring CommandContext, explizite Events/States,
  Dedup/Timeouts, stale, Host-Neustart und Recovery ohne Replay.
- SDK-Projektion von freien Actions, Placements, DynamicFolders, Text/PNG/
  Varianten sowie capability-gegatete zusätzliche Funktionen.
- Transaktionales Autorenmodell und echte PySide6-Widgets-Anwendung mit
  Manifestformularen, Save/Rename/Undo, Validierung, Preview und IO-Workern.
- Private Entwicklungspakete, eigener Dry-Run und expliziter byteidentischer
  Link-Rollback; keine reale Installation oder Service-Steuerung.
- Benutzerhandbuch, eigenständiges Beispiel, Start-/Prüfwerkzeuge und lokale
  Abschlussakte. Projektumzug auf P: dokumentiert, historische C:-Akten bewahrt.
- 281/281 automatisierte Tests und echte Prozess-/SDK-Buildbelege.
  Neue PRODUCT-ADR-001 bleibt PROPOSED; Gesamtprojekt PARTIAL wegen
  Hardware-/Zusatzfunktionsgrenzen. Keine Selbstabnahme.

## v0.5.1 – 30. Oktober 2026 (P0-ADRs freigegeben; **kein Software-Release**)

- Ausdrückliche Freigabe aller sieben P0-ADRs dokumentiert: sechs ohne Änderung, ADR 005 mit eingeschränkter Scope-Reichweite.
- Einzel-ADRs, Entscheidungsregister, Metamodell, Projektstatus, Roadmap und Übergabehinweis konsistent aktualisiert.
- Eigenes [P0-Beschlussprotokoll](docs/12_P0_Freigabe_2026-10-30.md) mit Geltungsgrenzen und offenen Punkten hinzugefügt.
- `work/packages/AP-CORE-001` von „unter Entscheidungsvorbehalt“ auf `READY_TO_START` gehoben; vollständigen Agentenprompt mit festen Pfaden und Abnahmetests überarbeitet.
- Produktiver Core weiterhin **nicht implementiert**; das vorhandene Draft-Schema und der P0-Spike sind keine implizite Produktfreigabe.


## v0.5 – 30. Oktober 2026 (Konsolidierung, **keine neue Softwareversion**)

- Ausführliche v0.3-Dokumente als **kanonische Linie `docs/`** übernommen, nicht verworfen.
- Quell- und Begriffsverweise in die neue Verzeichnisstruktur übertragen.
- P0 v0.4 als `docs/11_P0_Praezisierungen.md` und **sieben eigenständige ADR-Beschlussvorlagen** integriert, durchgehend `PROPOSED`.
- Normatives v0.3-Entscheidungsregister mit der neuen ADR-Liste ergänzt, bestehende `AR`, `MM` und `OP`-Statuswerte nicht hochgestuft.
- Roadmap aus `docs/10` nach `work/planning`, Agentenprompt aus v0.4 nach `work/packages/AP-CORE-001` verschoben und **auf einen einzigen Projektroot umgeschrieben**.
- `work/runs/` als separate Ablage eingeführt; kein Agentenlauf fingiert.
- P0-Schemaentwurf, Beispielmanifeste, Beispielprojekt und Spike-Quellen in technische Verzeichnisse übertragen; Tests nur für `src/`-Importweg angepasst.
- Historische Entwürfe, Herstellerquellen und Original-ZIPs in `references/` erhalten.
- Technische Validierungs-Skripte für den übernommenen P0-Spike ergänzt.

## v0.4 (historisches Quellpaket)

P0-Review, sieben vorgeschlagene ADRs, Draft-Schema, Core-Spike mit 14 Tests und AP-CORE-001-Prompt. Quelle: `references/package-history/Logi_Architektur_P0_v0.4.zip`.

## v0.3 (historisches Quellpaket)

Zwölf ausführliche Architektur- und Übergabedokumente inklusive Glossar/Ebenenmodell und technischer Nachweise. Quelle: `references/package-history/Logi_Plugin_Architecture_Handoff_v0.3.zip`.


## 30.10.2026 – Runtime-Grundsatzfreigabe und AP-CORE-002-Abnahme

- Nach unabhängiger Nachprüfung: AP-CORE-002/RUN-02 als begrenzter synchroner Command-/Event-Spike `APPROVED` (131/131 Tests, 3/3 Reviewrepros).
- T1–T6 als sechs Runtime-Grundsatz-ADRs `RT-ADR-001..006` beschlossen, inklusive der ausdrücklich offenen Implementierungsdetails.
- AP-CORE-003 als nächster separater Agentenauftrag für den In-Memory-StateStore vorbereitet; **noch nicht ausgeführt**.
- Diese Lieferung ist ein Delta aus neuen und geänderten Dateien, kein neues Gesamtpaket.
