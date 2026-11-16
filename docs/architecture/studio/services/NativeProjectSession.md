# NativeProjectSession – technischer Projekt-/Commit-Vertrag

**Status:** eigenständig APPROVED (AP-STUDIO-001); zentrale Studio-Writerrouting-Verbindung **IMPLEMENTIERT in AP-STUDIO-002; unabhängig APPROVED am 06.11.2026**.  
**Code:** `src/studio/native_session.py`; Parser: `src/adapters/logitech/native.py:parse_native_project`. Abnahme: `work/acceptance/20261105-native-session-explorer/ABNAHME.md`.

## Öffentliche API

| Methode/Eigenschaft | Vertrag |
|---|---|
| `load(path)` | nur gültiges `logitech-native-1` mit Disk-Baseline |
| `from_raw(raw)` | Memory-Session ohne Saveziel |
| `snapshot()` | defensive Tiefenkopie des vollständigen ursprünglichen JSON |
| `native_project()` | geprüfte defensive `NativeProject`-Projektion |
| `revision`, `dirty`, `can_undo`, `can_redo`, `path` | lesender Sessionstatus |
| `replace(proposed, *, base_revision)` | validiert vollständigen vorgeschlagenen JSON-Snapshot und Commit nur mit aktueller Revision |
| `undo()`, `redo()` | geprüfte, begrenzte History, neue opake Revision |
| `save()` | Rohbyte-/SHA-256-Diskkonfliktcheck, temp+fsync+os.replace im gleichen Verzeichnis |

Exceptions: `NativeSessionError`, `NativeRevisionConflict`, `NativeDiskConflict`.

## Sicherheitsgrenzen

Kein Auto-Save, kein Save-As, keine stille `0.1-draft`-Migration, keine Asset-/ICT-Dateiverwaltung. `NativeProjectSession` ist keine transaktionale Multi-File-Datenbank und bietet keinen OS-weiten Compare-and-Swap-Lock. `NativeIctCoordinator` besitzt momentan einen separaten Speicherpfad in dieselbe Autorenprojektdatei.

## Host-Vertrag

**IMPLEMENTIERT:** V-01, V-02, V-15, V-16, V-32, V-33, V-36, V-37. Der `StudioCoordinator` besitzt die einzige schreibende Session und liefert aktuelle, defensive Projekt-Snapshots an die UI. Alle Änderungen laufen über `snapshot → gezielte Mutation → replace(base_revision) → validieren → neue UI-Snapshots`. Speichern bleibt ein expliziter Vorgang. ICT-/SymbolDesigner-Operationen bleiben bis zur gesondert abgesicherten Writerkoordinierung in der nativen Shell deaktiviert. Projektwechsel mit Dirty-Session besitzt einen Dialog mit Cancel/Save/Discard und geprüften DiskConflict-Pfaden.

[Gesamtkarte](../00-Gesamtkarte.md) · [Transaktionsregeln](../01-Daten-und-Transaktionen.md)

## Tatsächliche zentrale Writerintegration

`src/studio/native_shell/coordinator.py` besitzt pro geöffnetem Projekt genau eine NativeProjectSession. V-01/V-02 liefern defensive Projektionen; V-15 ändert ausschließlich display_name im vollständigen Rohsnapshot und ruft einmal replace mit vorher erfasster base_revision. V-16 Undo, V-36 Redo, V-37 Save, V-32 Reload und V-33 Dirty-Schließen sind separat im [Register](../04-Verbindungsregister.md) nachgewiesen. Das Sessionmodul selbst wurde für AP-STUDIO-002 nicht verändert.

Ein gültiger Kandidat ersetzt die Session erst nach dem Dirty-Guard. Direkter Coordinatorwechsel mit Dirty-Session wird ohne explizites discard verweigert. Bei DiskConflict bleiben externe Bytes und lokale Änderungen erhalten; keine automatische erneute Überschreibung. Falsches Schema, verlorene Entity, ungültiger Action-/Handlerverweis und stale Revision sind Fail-closed-Tests der neuen Hostintegration. Save-As, OS-weites Lock und koordinierte Multi-File-/ICT-Transaktion bleiben außerhalb dieses AP. Die Shell besitzt keinen alternativen Dateiwriter.
