# 11 – Quellen, Provenienz und Abgrenzung der Aussagen

**Zweck:** Leser können unabhängig vom ursprünglichen Chat rekonstruieren, was Primärmaterial, frühere Planung, Nutzerbeobachtung, neue Ableitung und ungeprüfter Entwurf ist.

## 1. Im Paket liegende Originalmaterialien

| Pfad | Herkunft | Typische Verwendung | Wichtige Grenze |
|---|---|---|---|
| `../references/logitech-sdk/logi-actions-sdk-llms-full.md` | vom Nutzer hochgeladene SDK-Referenz | SDK-Typen, Dynamic Folder, Commands, Paketstruktur, Profile, Action Editor | Herstellerdokumentation ist **nicht** automatisch Nachweis auf Gerät |
| `../references/logitech-sdk/PluginApi.xml` | vom Nutzer hochgeladene XML-API-Dokumentation | Konstruktoren/Overrides, `RunCommand`, `ActionImageChanged`, Geräte-Enums | XML enthält nur Teil der SDK-Typen; konkrete DLL kann zusätzliche API enthalten |
| `../references/architecture-history/ARCHITEKTURMODELL_v0.1.md` | gemeinsam erarbeitete Architektur-Baseline | fest vereinbarte Prinzipien | kein finales Schema |
| `../references/architecture-history/METAMODELL_ENTWURF_v0.2.md` | gemeinsam erarbeiteter Entwurf | genaueres Entitäten-/Binding-Modell | **nicht final abgenommen** |
| `../examples/beispiel_plugin_abstrakt_v0_2.json` | konzeptionelles Beispiel der v0.2 | Testfall/Lesebeispiel | kein formal validiertes oder lauffähiges Schema |
| `../references/prototypes/Logi_SDK_DevKit_v0.2.zip` | bisheriger Studio-/Lab-Quellstand | Code- und Testreferenz | **nicht** Umsetzung des neuen Metamodells |

## 2. Welche Aussagen kommen woher?

| Behauptung | Evidenzkategorie | Verlässlicher Geltungsbereich |
|---|---|---|
| SDK besitzt DynamicCommand und Methoden zur Bildaktualisierung | XML/SDK-Dokumentation | angebotene SDK-Oberfläche |
| SDK Lab zeigt live geänderte Folder-Mitglieder | Nutzer-Gerätetest / Lab-Implementierung | MX Creative Keypad, Lab v0.1.4 |
| C#-Plugin/HTTP-Bridge funktionieren | Nutzer-Diagnoselogs | damalige PluginApi und Windows-Installation |
| Das Studio v0.2 besitzt Demo-/Checkbox-Konfiguration | vorhandener DevKit-Quellstand | damaliger Generator, kein neues Produktmodell |
| Metamodell kann fachneutral alle Aktionen mit Ports/Bindings repräsentieren | Architekturableitung | theoretischer Entwurf, erst Validator/Runtime beweisen es |
| beliebig viele Aktionen sind in **einem** Dynamic Folder physisch sichtbar | **nicht belegt** | physische Plätze und Navigationsmechanismus adapterabhängig |
| genau dieses generierte Produktplugin funktioniert auf Hardware nach P3/P4 | **nicht belegt** | zukünftiger Abnahmetest |

## 3. Historische Abfolge – relevant für spätere Entscheidungen

1. SDK-Dokumentation und XML-Schnittstellenreferenz untersucht; Logitech-Plugin als C#-Adapter und Python als Host vorgezogen.
2. SDK Lab v0.1: C#-Plugin und PySide6-Window entwickelt; Build zunächst durch .NET-8/.NET-10-Konflikt blockiert.
3. Projekt auf `.NET 10` gestellt; Plugin wurde geladen und in Logi Options+ angezeigt.
4. Erste POST-Events scheiterten mit `HTTP 413`; ab v0.1.3 erfolgreich. Debug-Selftest, PID- und Versionsinformationen eingeführt.
5. Dynamic Folder und Python-Steueroptionen auf Gerät getestet; live 4↔8, Farbe, Kontext, Counter mit v0.1.4 bestätigt.
6. Ein erstes Studio mit Generator entstand; Build/Options+-Registrierung funktionierten, aber Konfiguration und Bibliothek enthielten zu viele Demo-Festlegungen.
7. Entscheidung: SDK Lab weiter als Nachweisplattform; neues Studio als **generischer visueller Autoreneditor** und echte Typbibliothek.
8. Architekturmodell v0.1 als Baseline; Metamodell v0.2 als Entwurf; dieses Dokumentationspaket systematisiert beide für die Übergabe.

## 4. Was man zur Verifikation tun sollte

- SDK-spezifische Aussagen anhand der hier enthaltenen Originalquellen und der **lokal installierten `PluginApi.dll`** prüfen, nicht allein aus Beispielcode ableiten.
- Versions-/Hardwareansprüche nur mit reproduzierbarem Build, Logs und realem Gerät als `passed` markieren.
- Bei neuer Architektur-Implementierung selbst JSON-Schema-, Validator- und Runtime-Tests erstellen. Die vorhandenen Studio-Tests beweisen die neue Architektur nicht.
- Unklare Architekturbegriffe als `OPEN` im [Entscheidungsregister](08_Entscheidungsregister.md) führen; keine neuen „Fakten“ durch Wiederholung von Beispielen erzeugen.


## 5. Neu integrierter P0-Stand v0.4

Die früher gesondert veröffentlichte Ergänzung liegt nun als [P0-Präzisierungen](11_P0_Praezisierungen.md), sieben [ADR-Vorschläge](decisions/README.md), [Schemaentwurf](../schemas/project_v0_1_draft.schema.json), [Manifestbeispiele](../component_types/README.md), [Projektbeispiel](../examples/project_v0_1_draft.json) und ausführbarer [Core-Spike](../src/core_spike/README.md) in dieser Gesamtfassung. Unveränderte Ursprungs-ZIPs sind in `references/package-history/` archiviert.
