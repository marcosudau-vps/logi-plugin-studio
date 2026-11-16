# AP-STUDIO-001 – NativeProjectSession v1
## Vollständiger Implementierungsauftrag – Qt-unabhängiger nativer Projektdokument-Owner

**Projekt:** `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture`  
**Status:** PREPARED – nicht gestartet; eigenständige Implementierung.  
**Ziel:** Die bereits definierte **Logitech-native Projektdatei** `logitech-native-1` sicher öffnen, bearbeiten, gegen `parse_native_project` validieren, rückgängig machen und konfliktgeschützt speichern. **Keine neue persistente Action- oder Profilsemantik bauen.**

## 1. Vorbereitung / verbindliche Lesepfade

Lies vor jeder Änderung vollständig:

1. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\docs\decisions\ARCH-ADR-001.md`
2. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\docs\specifications\logitech-profil-und-aktionsmodell-basis-v02.md`
3. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\work\planning\modell-und-parallelentwicklung-nach-ap-prof-001-v01.md`
4. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\adapters\logitech\native.py` – insbesondere `parse_native_project`, `NativeProject`, `NativeAction`, `NativeFolderEntry`, `NativeProjectError`.
5. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\native_ict_binding.py` – existierende optimistische SHA-256-Konfliktkontrolle, Save-Besonderheiten.
6. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\library\document.py` – `ProjectDocument` der **alten** `0.1-draft`-Welt: Inspiration für Sicherheitsprinzipien, **nicht** als native Schema- oder Fachdomäne nutzen.
7. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\examples\project_logitech_native_v1.json`
8. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\keypad_contract.py` – Revisionen und EditRequest: Host muss Änderungen validieren/committen.
9. `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\tests` – vorhandene native Parser- und Save-Regressionsfälle.

**Parallelität:** Ein zweiter Agent kann `AP-WIDGET-006` als reines ProjectExplorerWidget implementieren. Er darf das NativeSession-Modul **nicht** benötigen oder verändern. Du darfst die ProjectExplorer-Dateien, das Studio-Hauptfenster und das Forschungsrepository nicht anfassen.

## 2. Exakte Schreibgrenzen

Erlaubte **neue** Dateien:
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\src\studio\native_session.py`
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\tests\test_native_session.py`
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\tools\run_native_session_lab.py`
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\work\native-session\AP-STUDIO-001\README.md`
- `P:\LokaleProjekte\logi_actions_sdk\PluginStudioArchitecture\work\native-session\AP-STUDIO-001\evidence` (Tests/Logs/dokumentierte Testdaten; keine Originalprojekte verändert).

Zusätzliche private Hilfsfunktionen innerhalb `src/studio/native_session.py` sind erlaubt; keine weiteren Produktmodule verändern. Insbesondere **keine Änderungen** an `src/studio/app.py`, `src/studio/native_ict_binding.py`, `src/adapters/logitech/native.py`, `src/adapters/logitech/product.py`, `src/library/`, `src/runtime/`, `schemas/`, bestehende Widgets, bestehenden Tests, Projekte oder laufenden Logitech-Dateien. Keine Installation, kein Service-Neustart, kein SDK-/Hardware-Test nötig.

## 3. Konzept / Architekturvertrag

`NativeProjectSession` ist ein **technisches Qt-freies Dokument-/Transaktionsobjekt**, dessen Quelle das bisherige `logitech-native-1`-JSON ist.

- `parse_native_project` ist der **einzige** normative Parser/Validator für dieses Format; kein zweiter Datenmodell-Validator. Bestehende Parser-Fehler mitsamt Pfadangaben erhalten, in geeignete `NativeSessionError`-Meldungen kapseln.
- Der **unveränderte JSON-Dokumentbaum** bleibt intern die Schreibwahrheit; `NativeProject` ist ausschließlich eine geprüfte native **Leseprojektion**. Speichere nicht ein aus `dataclasses.asdict(NativeProject)` rekonstruiertes, potentiell verlustbehaftetes Dokument.
- Änderungen ausschließlich als **vollständiger vorgeschlagener neuer nativer JSON-Snapshot** plus `base_revision`; Host/Inspector wird später aus dem alten Snapshot einen neuen erstellen. Kein generisches SDK-unabhängiges Mutationsgraphmodell.
- Revision ist **flüchtig, opak, sessiongebunden** und ändert sich nach erfolgreichem Commit/Undo/Redo/Reload, nicht beim bloßen Anzeigen. Nicht `KeypadFrame.revision` als dauerhafte Dateiversion interpretieren.
- **Nur ein Dokument-Writer**: Die Session ist künftig Commit-Owner; andere Autoren-/ICT-Writes werden später über den Host auf dieselbe Session-/Konfliktstrategie koordiniert. **Heute keine Direktintegration** ins bestehende SymbolDesigner-Binding und keine Behauptung, eine gemeinsame Transaktion sei bereits implementiert.

## 4. Erwartete API (stabil, leicht nutzbar)

Empfohlene öffentliche Oberfläche:

```python
class NativeSessionError(ValueError): ...

class NativeRevisionConflict(NativeSessionError): ...

class NativeDiskConflict(NativeSessionError): ...

class NativeProjectSession:
    @classmethod
    def load(cls, path: str | Path) -> "NativeProjectSession": ...

    @classmethod
    def from_raw(cls, raw: dict) -> "NativeProjectSession": ...

    @property
    def path(self) -> Path | None: ...

    @property
    def revision(self) -> str: ...

    @property
    def dirty(self) -> bool: ...

    @property
    def can_undo(self) -> bool: ...

    @property
    def can_redo(self) -> bool: ...

    def snapshot(self) -> dict: ...  # tiefe defensive Kopie
    def native_project(self) -> NativeProject: ...  # geprüfte Projektion

    def replace(self, proposed: dict, *, base_revision: str) -> str:
        """Commit nur nach passender Revision und nativer Validierung; neue Revision zurückgeben."""

    def undo(self) -> bool: ...
    def redo(self) -> bool: ...

    def save(self) -> None:
        """Nur am ursprünglich geöffneten Pfad, ohne externen Konflikt zu übergehen."""
```

**Wichtig:** Kein obligatorischer neuer Schema-/Action-/Handler-/Folder-Datentyp. Von der Signatur darf minimal abgewichen werden, wenn im Abschluss ausdrücklich begründet, warum. Optional `save_new(target)` nur, wenn der Agent dafür Tests, sichere Nichtüberschreibung und klare Asset-/Portable-Path-Grenzen liefern kann. Sonst **nicht** bauen. Keine komplizierten Generics, Commands, Eventsourcing oder ORM.

### Revision und Undo

- `replace` gegen veraltete Revision → `NativeRevisionConflict`, keine Änderung.
- Fehlerhafter nativer Snapshot → `NativeSessionError`, aktuelle Session inklusive History/Dirty unverändert.
- Erfolgreicher Commit → Deepcopy, native Validierung, neuer Revisionswert, genau ein Undo-Eintrag, Redo verworfen.
- Gleicher Snapshot → No-op ohne unnötigen Revisions-/History-Schritt.
- Undo/Redo auf validierte Snapshots, bounded History (z. B. 50), Restore des vollständigen nativen JSON-Inhalts; `dirty` vergleicht gegen den zuletzt gespeicherten Inhalt, **nicht** nur den Undo-Stack.
- Reload oder Disk-Konflikt darf nicht heimlich lokale nicht gespeicherte Änderungen vernichten.

### Laden / Speichern

- `load` nur für JSON mit `schema_version == "logitech-native-1"`; eine `0.1-draft`-Datei muss ausdrücklich abgewiesen und auf den alten Kompatibilitätseditor verwiesen werden. **Keine implizite Migration.**
- Größenlimit (z. B. 16 MiB), UTF-8 mit optional BOM lesen; Fehlerfall freundlich, keine `eval`-/Pickle-Verarbeitung.
- Kein automatisches Anlegen von Dateien beim Lesen; kein Schreiben, solange Session nicht ausdrücklich `save()` erhält.
- **Schutz vor Fremdänderung:** SHA-256 der beim Laden gelesenen Rohbytes merken. Vor Speichern prüfen, ob die Zieldatei weiterhin byte-identisch ist; auch unmittelbar vor atomischem Ersetzen nochmals prüfen. Bei Abweichung mit `NativeDiskConflict` abbrechen, **niemals** still überschreiben.
- **Atomarer Austausch:** temporäre Datei im selben Verzeichnis, Flush/Fsync, dann `os.replace`; temporäre Dateien auf Fehlerpfaden entfernen. Keine unfertige Projektdatei zurücklassen. Falls dieselbe Ressource durch anderen Writer geändert wurde: diese Session kann **nur ihr eigenes Projektfile** schützen. Kein Multi-File-Transaktionsversprechen.
- Nach erfolgreichem Save: `dirty=False`, Disk-Bytes/Baseline aktualisieren. Originalschema und alle optional gültigen Felder bewahren.
- Projekt-Assets (`.ict`, `.svg`, `.png`) **nicht** verschieben, löschen, kopieren oder automatisch „reparieren“. Save-As mit relativen Assets nur als separat zu planende sichere Funktion.

## 5. Lab und praktische Funktionsprobe

`python tools/run_native_session_lab.py` soll ohne GUI, SDK-Dienst und Hardware funktionieren:

1. Beispielprojekt `examples/project_logitech_native_v1.json` **nur lesen**, für Tests in `tempfile.TemporaryDirectory` kopieren.
2. Neue Session öffnen, `NativeProject` anzeigen; mehrere native Actions, einen Handler und Folder-Entries anzeigen.
3. Auf Basis einer Kopie `display_name` einer Action ändern und per `replace(...,base_revision=...)` committen; Snapshot/NativeModel zeigen neuen Wert.
4. Undo/Redo und `dirty`-Werte demonstrieren; `save()` erzeugt gültiges natives JSON im TEMP-Verzeichnis.
5. Test für stale base revision und absichtliche externe Dateiveränderung → beide fail-closed, dokumentiertes Ergebnis.
6. Verifikation: Originalbeispieldatei im Projekt bleibt byte-identisch (SHA-256 vor/nach), keine Daten außerhalb TEMP und eigener Evidence-Verzeichnisse ändern.
7. Geeigneter Exitcode für automatisierten `--smoke`-Modus und reproduzierbare Ausgabe.

## 6. Tests und Qualitätsgates

Erstelle `tests/test_native_session.py` mit mindestens:
- gültiges natives Beispiel laden, eindeutiger SDK-Typ/Parameter/States/Folders erhalten;
- UTF-8/Umlaut, ungültige JSON, zu große Datei, Schema `0.1-draft`, fehlende Datei;
- `snapshot()` defensiv: mutierte Rückgabe darf die Session nicht ändern; NativeProject-Projektion nicht als Authoring-Wahrheit verwenden;
- gültiger Change, No-op, zwei aufeinanderfolgende Commits, Undo/Redo, Redo nach neuem Commit verworfen, Dirty vs gespeicherter Stand;
- ungültige Action-ID/Handler/Folders/Parameter/States werden über bestehenden Parser abgewiesen, danach unveränderte Session;
- stale Revision, externer gleichgroßer und/oder gleicher-mtime Dateibestand mit anderen Bytes → fail-closed, keine Überschreibung;
- atomare Save-Ergebnisse und Cleanup bei simuliertem Schreibfehler, keine Teil-Zieldatei, keine verwaiste temporäre Datei;
- vollständiger nativer JSON-Roundtrip ohne Verlust optionaler gültiger Eigenschaften (`icon_template`, `symbol`, `states`, `editor_controls`, `parameter_symbols`, `device_navigation`);
- ausschließlich Standardbibliothek; keine PySide6-Abhängigkeit im neuen Modul;
- kein unbeabsichtigtes Speichern bei Commit/Undo/Redo/Load.

Pflichttests:
`python -m unittest discover -s tests -p test_native_session.py -v`
`python -m unittest discover -s tests -q`
`python tools/run_native_session_lab.py --smoke`
`python tools/check_links.py`

Falls eine vorhandene Regression fehlschlägt: konkret reproduzieren und dokumentieren, bestehende fremde Dateien nicht eigenmächtig ändern.

## 7. Abschluss

Lieferung im eigenen `work/native-session/AP-STUDIO-001/`: Einstieg, API, tatsächliche Dateiliste/Diffs, Roundtrip-Evidenz, Konsolentestprotokolle, bewusst nicht implementierte Funktionen und klare Host-Integrationshinweise.

**Status maximal `READY_FOR_REVIEW`**, nicht `APPROVED`; unabhängige Abnahme folgt. **Kein** Produktions-Studio-Fenster umbauen und keine neue Logitech-Profil- oder SDK-Domäne erfinden.

Arbeite autonom bis zum bestmöglich vollständig testbaren Ergebnis, ohne nach jeder Methode rückzufragen; halte dich exakt an die erlaubten Schreibbereiche.
