# Agentenbrücke – Paseo/OpenCode (lokaler Prototyp)

**Stand:** 30.10.2026. Verwendet nur Python-Standardbibliothek und bereits installierte Paseo CLI v0.12.0 / OpenCode v2.0.18. Das Projektmodell, SDK Lab und Runtime werden nicht verändert.

## Zweck

`hin.py` erzeugt eine nachvollziehbare Auftragsdatei und startet **nur mit explizitem `--start`** einen neuen Paseo-Agenten oder sendet einen Korrekturauftrag an die bestehende Paseo-Agent-ID. Paseo steuert den ausgewählten Agentenprovider, standardmäßig `opencode/opencode/deepseek-v4.1-flash-free` (im aktuellen Paseo-Modellkatalog als Free ausgewiesen). Die Angabe kann für bewusst ausgewählte vorhandene Modelle überschrieben werden.

`zurueck.py` wird vom ausführenden Agenten nach seinem Abschluss aufgerufen: Bei `REVIEW_READY` werden die Delta-ZIP, das eingebettete CHANGESET.json, ZIP-CRC und sämtliche SHA-256-Dateihashes geprüft. Der Rückgabestatus wird im Projekt unter `work/agent_bridge/results/<RUN-ID>.json` abgelegt.

Das Browser-Cockpit unter http://127.0.0.1:18766 zeigt diese Ergebnisse und stellt eine Schaltfläche zum Kopieren der Review-Anfrage bereit.

**Wichtig:** Kein lokales Programm besitzt derzeit eine freigegebene Schnittstelle, mit der es ohne Nutzeraktion eine neue Nachricht in exakt diese bestehende ChatGPT-Unterhaltung einfügen könnte. Die Brücke stellt deshalb keine automatische Chat-Nachricht oder Hintergrundabnahme in Aussicht.

## Beispiele (aus Projektroot)

Trockenlauf, **startet keinen Agenten**:

```powershell
python tools/agent_bridge/hin.py --run-id RUN-AP-CORE-003-02 --prompt-file work/packages/AP-CORE-003/05_nachbesserungs_prompt_RUN02.md
```

Neuen Agenten für ein **neues** Arbeitspaket wirklich starten (erst, wenn dessen Prompt vorhanden und freigegeben ist):

```powershell
python tools/agent_bridge/hin.py --run-id RUN-AP-CORE-004-01 --prompt-file work/packages/AP-CORE-004/02_agentenprompt.md --provider opencode/opencode/deepseek-v4.1-flash-free --start
```

Korrekturlauf **in derselben Paseo-Agent-Session**:

```powershell
python tools/agent_bridge/hin.py --run-id RUN-AP-CORE-003-02 --prompt-file work/packages/AP-CORE-003/05_nachbesserungs_prompt_RUN02.md --resume-id DEINE-PASEO-AGENT-ID --start
```

Agent ruft bei Abschluss auf:

```powershell
python tools/agent_bridge/zurueck.py --run-id RUN-AP-CORE-003-02 --status REVIEW_READY --zip work/runs/RUN-AP-CORE-003-02/outputs/RUN-AP-CORE-003-02.zip
```

Bei Blockade: `python tools/agent_bridge/zurueck.py --run-id RUN-AP-CORE-003-02 --status BLOCKED`.

Bestehende ZIP **ohne dauerhafte Rückmeldung prüfen**:

```powershell
python tools/agent_bridge/zurueck.py --run-id RUN-AP-CORE-003-01 --status REVIEW_READY --zip work/runs/RUN-AP-CORE-003-01/outputs/RUN-AP-CORE-003-01.zip --check-only
```

## Regeln

- Ein neuer AP erhält eine neue Agenten-Session, Korrekturen innerhalb desselben AP nutzen möglichst `--resume-id`. Eine bisher nur manuell gestartete Session kann nur fortgesetzt werden, wenn ihre **Paseo-Agent-ID** bekannt und dort registriert ist.
- `--start` ist absichtlich verpflichtend. Vorbereiten bedeutet **niemals** automatisch ausführen.
- Keine SDK-Lab-Veränderungen, keine unkontrollierten Änderungen bereits abgenommener Architektur.
- Das Agentenergebnis ist **nur REVIEW_READY**, niemals eine unabhängige Abnahme.
- Bei `BLOCKED` bleibt ein vollständiger Abschlussbericht erforderlich, aber kein Ergebnis-ZIP.
- Die Brücke überträgt keine Dateien nach außen. In den JSON-Dateien liegen nur lokale Pfade, Hashes und Status.
- Bei Fehlern wird keine erfolgreiche Rückmeldung erzeugt. Laufende Agenten können über `paseo ls --json` / `paseo inspect --json <id>` geprüft werden.

## Ordner

`work/agent_bridge/requests/`: Aufträge und die von der Brücke verwendeten kurzen Übergabeprompts.

`work/agent_bridge/results/`: lokale Inbox für Ergebnis-Rückmeldungen.

Dies ist ein isolierter Infrastruktur-Prototyp und **kein neues AP-CORE-Arbeitspaket**.
