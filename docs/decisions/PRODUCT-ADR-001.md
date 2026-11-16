# PRODUCT-ADR-001: Lokale Host-Anbindung

> **Prüfvorbehalt 03.11.2026:** [ARCH-ADR-001](ARCH-ADR-001.md) stellt die spätere native SDK-Semantik über eigene Runtime-Modelle. Die hier beschriebene HTTP-/StateStore-Architektur ist aktueller **IST-/PROPOSED-Hostpfad**, kein universelles Pflichtformat jeder SDK-Action; Sicherheits- und Transportnachweise bleiben gültig.

Status: **PROPOSED**. Revidierbare Produktentscheidung im Autopilot-Auftrag;
keine unabhaengige Architekturabnahme. P0-/RT-ADRs bleiben unveraendert.

## Entscheidung und Alternativen

V1 nutzt authentisiertes HTTP auf IPv4-Loopback, getrennten Port und zufaelligen
256-Bit-Schluessel je Plugin-Installation. Der Python-Host besitzt StateStore
und Runtime-ID; C# ist ausschliesslich Leser/Command-Erzeuger.
Lab v0.1.4 belegt HTTP mit explizitem Content-Length sowie SDK-Callbacks.
Named Pipes waeren lokal restriktiver, benoetigen aber plattformspezifische
Python-Interop. WebSockets/Broker bringen hier unnoetige Abhaengigkeiten.
Das Fake-Envelope wird NICHT als Produkt-Wireformat uebernommen.

## Vertrauensmodell

Projektdaten enthalten keine Schluessel und keine ausfuehrbaren Callback-Skripte.
Handler sind explizit registrierte Python-Callables. Eine separate
`studio.connection.json` ist ein lokales Deployment-Geheimnis, keine zweite
Projektdefinition. Sie liegt spaeter neben der eigenen DLL und ist nicht zu
veroeffentlichen. Lokale Prozesse desselben Windows-Kontos mit Dateileserechten
sind nicht gegeneinander isolierbar; Administratoren ebenfalls nicht.
Loopback und HMAC schuetzen gegen fremde Ports, unbeabsichtigte LAN-Freigabe
und Teilnehmer ohne Schluessel, nicht gegen ein kompromittiertes Benutzerkonto.

Requests: HMAC-SHA256 ueber Pfad, zufaellige Nonce und exakte UTF-8-Bodybytes.
Responses: HMAC ueber Request-Nonce und exakte Antwortbytes. Der Client prueft
Antwortsignatur VOR Verwendung von Runtime-/Session-ID oder State.
Signierte Zeitfenster und Nonce-Cache verhindern Request-Replay; Plugin-ID,
Projektfingerprint und Installations-ID muessen uebereinstimmen.
Keine Authentisierung durch frei behauptete Host-/Session-Strings.

## Ablauf und Grenzen

Handshake erzeugt Session, nicht Runtime. Snapshot unter derselben Sperre wie
Writes/Journal liefert atomare Baseline mit Cursor. Bounded Journal, geordnete
Deltas und Gap-Pruefung; bei Verlust immer Vollsnapshot, kein Command-Replay.
HTTP 2 s, Command 5 s, Queue 64, 16 HTTP-Threads/Sessions, 1 MiB Response,
64 KiB Request, 32 JSON-Ebenen, maximal 4096 Command-IDs pro Runtime.
Kapazitaetsgrenze verweigert neue Commands statt alte Dedup-IDs zu vergessen.
Produktionshaertung dieses bewusst begrenzten Limits bleibt reviewbeduerftig.

Ein serieller Handler-Worker verwendet den bestehenden Dispatcher intern.
Oeffentlich: `fn(payload, CommandContext) -> JSON`; explizite States/Events.
Lexikalische Routingreihenfolge ist revidierbare Implementierungsentscheidung,
kein neuer ACCEPTED-Grundsatz. Ein Timeout eines laufenden Python-Callbacks
ist UNKNOWN_OUTCOME. Python-Threads werden nicht gewaltsam beendet; abgelaufene
Contexts duerfen nicht spaeter States schreiben. Fremde externe Effekte eines
vertrauenswuerdigen Callbacks sind nicht rueckgaengig zu machen.

Keine Persistenz von Ist-Werten, kein Multimaster, kein Remotebetrieb.
Ein Host ist ohne Studio lauffaehig. Unterschiedliche Plugins sind getrennt.

## Implementierungsfolgen und Nachweise

State-Writes pruefen ein konservatives 512-KiB-Snapshotbudget VOR Mutation.
Projektion/Assets/InitialStates muessen in den C#-Parse-Rahmen von 1 MiB
passen; diese Grenzen sind Ressourcenbudgets, keine 4/8-Aktionsgrenze.
CommandContext-Emissionen sind explizit und auf acht Verschachtelungen
begrenzt. Ein separater Observerthread darf den Deadline-Watchdog nicht
blockieren. Observer-Gaps/Ausnahmen werden protokolliert.

Der generierte Mirror prueft auch verschachtelte State-Wertvertraege:
enum/const/type, Laengen, Bereiche, Objektpflichtfelder/Extras und Arrayitems.
Integralwerte vergleichen bei Bereichen exakt per BigInteger; gemischte
numerische Vergleiche oberhalb endlicher Double-Praezision werden verweigert.
Das ist keine Behauptung eines vollstaendigen JSON-Schema-Validators.

Echte C#-/Python-Prozesspruefung belegt Handshake, State-Delta, stale,
Runtime-Neustart, fehlendes Replay und Recovery nach signiertem
ungueltigem Scope-Snapshot. Diese Negativpruefung fand einen echten
InvalidDataException-Reconnectfehler, der im Produkt-Template korrigiert wurde.
Kein SDK-Callback-/Display-/Hardware-PASS. Details:
`work/autopilot/FINAL-PRODUCT-01/04_tests_und_evidenz.md`.
