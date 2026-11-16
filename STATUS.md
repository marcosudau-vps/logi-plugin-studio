# Aktueller Projektstatus – 09.11.2026

**AP-POLISH-001 · READY_FOR_REVIEW (technischer Release-Kandidat 1.0.0-rc1).** Zwei gleichwertige Windows-Fassungen aus einem Release-Befehl: `LogiPluginStudio-Setup-1.0.0-rc1.exe` (Inno Setup, ohne Adminrechte) und `LogiPluginStudio-Portable-1.0.0-rc1.zip` mit identischem Programminhalt. Jedes gebaute Plugin (nativ, kompatibel, Shared) startet seinen Python-Host jetzt selbst aus einer **pluginlokalen, SHA-256-geprüften Host-Laufzeit** – ohne Studio, ohne Python, unabhängig vom Studio-Ort. Pairing-Schlüssel sind DPAPI-geschützt, der Plugin-Typ wird je Projekt gemerkt. Vollregression **1.208/1.208, Exit 0**; Pflichttest Verschieben/Reload/Rejoin im **echten Logi Plugin Service 11/11 PASS**. Keine Veröffentlichung, keine Selbstabnahme.

[Abschlussbericht](work/polish/AP-POLISH-001/10_abschlussbericht.md) · [Tests und Evidenz](work/polish/AP-POLISH-001/08_tests_und_evidenz.md) · [Benutzerabnahme](work/polish/AP-POLISH-001/outputs/BENUTZERABNAHME.md)

## Stand 08.11.2026 (historisch)


**AP-RELEASE-FINAL-001 · READY_FOR_REVIEW.** Die native Studio-Oberfläche bietet die drei Buildmodi, Shared-Pairing mit gezielten Berechtigungen sowie Installation, Update und Rollback. Der portable Windows-Kandidat bestand den Selbsttest auf dem Entwickler-PC und in der Windows Sandbox. Die Gesamtsuite bestand mit **1.180/1.180, Exit 0**.

Am MX Creative Keypad sind native Actions, Parameterbeschriftung, Ordnernavigation, Shared-Owner-Aufruf, Fernbild, Ausfall und Wiederverbindung sowie Live-Update und Rollback belegt. Die drei Testplugins sind deinstalliert, die fünf vorhandenen Links sind bytegleich mit den Sicherungen. Die Testbelegungen blieben nach der Deinstallation sichtbar und verschwanden nach dem Entfernen der vier Belegungen in Options+.

[Abschlussbericht](work/release-final/AP-RELEASE-FINAL-001/09_abschlussbericht.md) · [Hardwareprotokoll](work/release-final/AP-RELEASE-FINAL-001/06_hardwaretests.md) · [Release-Manifest](work/release-final/AP-RELEASE-FINAL-001/outputs/release_manifest.json)

## Historischer Stand – 07.11.2026

Die früheren Root-Statusfassungen bleiben in der Reviewakte unter `evidence/STATUS-before.md.snapshot` erhalten. [Architekturentscheidung Native First](docs/decisions/ARCH-ADR-001.md)

| Bereich | Aktueller Stand und Grenze |
|---|---|
| Legacy-Core/Runtime/Studio | Kompatibler bisheriger Pfad; frühere unabhängige Softwareabnahmen bleiben in ihrem Scope gültig |
| Native Session, Coordinator, Inspector/Lifecycle | Implementiert; vorhandene unabhängige Einzelabnahmen unter `work/acceptance/` |
| AP-FOLDER-002 Studiointegration | **APPROVED / CLOSED im Softwareumfang (07.11.2026)**: eigenständige unabhängige Gesamtprüfung einschließlich neuer Studio-Build-Kante. Keine Hardwarefreigabe |
| R2 – native Validierung | FIXED: Action-/Handler-ID-Kollisionen und doppelte Folderpositionen zentral abgewiesen; Session/Lifecycle und Projektion regressionsgeprüft |
| R3 – sicherer Export | FIXED: reales Quellarchiv CRC-/SHA-verifiziert, frisch entpackt und 1.126 Tests ohne Fehler geprüft; sieben externe Grafikvergleiche übersprungen |
| R1 – native Foldersemantik | **APPROVED im SDK-Softwareumfang**: dieselben SDK-Actioninstanzen für Command, Parameter, Multistate und Encoder-Adjustment; ActionEditor im Folder explizit gesperrt |
| Dynamische SDK-Folder-Runtime | **APPROVED im SDK-Softwareumfang**: validierte Membershipsnapshots, SDK-Notifications, virtuelle Folder/Links/Back/Pages, mehrere echte Folder, stale Callbackschutz, signierter Hostanschluss |
| R4 – Reproduzierbarkeit | PREPARED: .gitignore, gepinnte direkte Python-Abhängigkeiten und Entwicklungsanleitung; keine Git-Initialisierung/Commits; Clean-Windows-Distribution weiterhin offen |
| Hardwarebelege | HW-01 dokumentiert reale Inputs/States für den damaligen Produktpfad. Neue Folder-Runtime sowie vollständige Navigation/Restart/Multi-Device nicht am Gerät abgenommen |
| Native Build aus Studio | **IMPLEMENTIERT / SOFTWARE_TESTED (07.11.2026)**: gespeichertes Sidecar → SDK-Laufzeitprojektion → echter C#-Build und lokales Paket. Keine Installation/Hardwarefreigabe |
| Gesamtprodukt | PARTIAL; beide jüngsten Agentenlieferungen im Softwareumfang unabhängig abgenommen, kein v1.0-Release |

[SDK-Vertrag und Übergabeformat](docs/architecture/sdk-dynamic-folders.md) · [Arbeitsakte REVIEW-FIX-20261106](work/reviews/REVIEW-FIX-20261106/README.md) · [Tests](tests/README.md).

Noch offen: gemeinsame ICT-/JSON-Assettransaktionen, native Keypaddarstellung, native Installation/Reload/Rollback-Bedienung, Hardwareabnahme und Endnutzerpaket. Die automatische Composer→SDK-Build-Projektion ist seit 07.11.2026 implementiert (individuelle Einstiege bei mehreren SDK-Foldern werden abgefragt). Nicht unterstützte SDK-Funktionen werden ausdrücklich diagnostiziert; es gibt keinen Cross-Plugin-Invoke, keinen Profilwriter und keine erfundene Folder-Open-API.

## 08.11.2026 – schlanke Bridge / optionales SharedFolder

Die C#-Basis-Bridge wertet keine `folder_runtime`-/`folder.layout`-Domänendaten mehr selbst aus. Neutrale, authentisierte Snapshot-/Journalbenachrichtigungen werden von `src/extensions/shared_folders/` optional konsumiert; SDK-native Actionsemantik und Python-Handler bleiben unverändert. Die alten `adapters.logitech.folder_runtime/folder_host`-Importe sind Kompatibilitätsfassaden. **Python-SDK-Fassade noch nicht vollständig**; Ist-/Sollstatus je SDK-Methode: [API-Checkliste](docs/specifications/sdk-python-api-checklist.md). Der Native-Foldergenerator verwendet derzeit weiterhin einen gemeinsamen Folderaufsatz (separates Opt-in-Gap). Neue getrennte Regression in `work/acceptance/20261108-bridge-separation/`.

## 08.11.2026 – unabhängige Abnahme der beiden FINAL-Implementierungspakete

- **AP-STUDIO-FINAL-001: APPROVED / CLOSED (Softwareumfang).** KeypadPreview und SymbolDesigner/ICT im nativen Hauptstudio integriert, Writer-/History-/Asset- und Buildpfade unabhängig geprüft.
- **AP-SHARED-FINAL-001: APPROVED / CLOSED (Peer-/SDK-Softwareumfang).** Native-/Shared-Generatormodi, pro Plugin eingebettete Peer-Zipapp, echte A/B/C-Prozesskommunikation, Owner-Aufruf, Push, Partitions-/Rejoin- und Sicherheitsprüfungen belegt.
- **Gemeinsame unabhängige Regression: 1.157/1.157 PASS, 0 Fehler, Exit 0**, nach Anpassung dreier historischer Tests, die ausdrücklich die ehemals deaktivierten Studiofunktionen erwarteten.
- [Vollständige unabhängige Doppelabnahme](work/acceptance/20261108-two-final-packages/GEMEINSAME-ABNAHME.md) und dortige Testlogs.

**Gesamtprodukt weiterhin PARTIAL.** Noch erforderlich: `folder_mode=shared`-Auswahl und Pairing-/Scope-Bedienung im Studio; Delivery der nativen ICT-/Bildressourcen und Remote-Bitmapübertragung; Installation, Reload, Rollback, Windows-Endnutzerpaket und echte MX-Keypad-/Options+-Prüfungen. Die SDK-Bridge bleibt schlank, vollständige Python-SDK-Abdeckung wird **nur dokumentiert, nicht als aktuelles Studioarbeitspaket durchgeführt**.

## 08.11.2026 – unabhängige AP-RELEASE-FINAL-001-Abnahme

**AP-RELEASE-FINAL-001: APPROVED / CLOSED für den beauftragten Software- und dokumentiert hardwaregetesteten RC-Umfang.** Unabhängige Gesamtsuite **1.180/1.180 PASS (Exit 0)**, echte Windows-Qt-Stichprobe 6/6 PASS, Release-ZIP 907/907 SHA-256-verified und Geräte-/Installationsnachweise geprüft. Ausgangssicherung bestätigt die **bytegleiche** generische SDK-Bridge und Transportmodule. Der Agenten-Hardwaretest umfasst 22 PASS / 1 FAIL (verbleibende Options+-Profilbelegung bis zur manuellen Entfernung) / 2 zunächst unklare Mehrfachdrucke, anschließend erfolgreich wiederholt. Die drei Testplugins und Test-Peerfreigaben wurden zurückgebaut.

[Unabhängiger Prüfbericht mit Logs](work/acceptance/20261108-release-final/ABNAHME.md). **Produktstatus: geprüfter privater RC 0.9.0-rc1, keine pauschale öffentliche v1.0-Freigabe.** Kleinere Restbefunde: vier defekte relative Links in der portablen `component_types/README.md`, überholte Linkmodus-Dialogtexte, nicht signierte EXE, DPAPI-/Portabilitätsgrenzen und Options+-Profilbelegungen nach Plugin-Deinstallation. Vollständige Python-SDK-API-Abdeckung bleibt außerhalb dieses Projektschritts.
