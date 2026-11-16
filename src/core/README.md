# P1 Core Model (`src/core`) — AP-CORE-001

> **Architektureinordnung 03.11.2026:** Dies ist die **implementierte und abgenommene Legacy-Core-Basis**, nicht das künftig fachlich führende Logitech-Modell. [ARCH-ADR-001](../../docs/decisions/ARCH-ADR-001.md) verlangt SDK-native Typen/Parameter/States bei neuen Funktionen. Code, Schema und vorhandene Testfreigaben bleiben ohne separate Migration unverändert.

**Status:** P1-Implementierung aus AP-CORE-001 (Lauf `RUN-AP-CORE-001-01`).
Statisches, SDK-/Qt-/transportunabhängiges Projektmodell; keine Runtime-Ausführung,
kein StateStore, kein Event-Routing, keine Logitech-/C#-Abhängigkeiten (nur Standardbibliothek).

## Geltungsgrundlage

P0-ADR-001, -002, -003, -004, -006, -007 (`ACCEPTED`); P0-ADR-005 nur als Grundsatz
(genau ein deklarierter Writer je State-Eintrag; keine Runtime-Scope-Durchsetzung).
Scope-/Authority-/Persistence-Wertemengen sind **DRAFT-Kandidaten**, keine finale Enum.

## Module

| Modul | Aufgabe |
|---|---|
| `ids.py` | ID-Regel `^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$` |
| `errors.py` | `Diagnostic{ code, path, message, severity }` |
| `model.py` | Typisierte statische Entitäten; `EndpointRef` abgeleitet; `MISSING`-Sentinel für `fallback` |
| `registry.py` | Typmanifeste per `(type_id, exakte Version)`; strukturierte Manifestfehler |
| `compat.py` | Konservativer Schema-/Kompatibilitätsprüfer (Subset von Draft 2020-12; fail closed) |
| `validate.py` | Projektvalidierung, deterministisch sortiert; `ERROR` blockiert, `WARNING` nicht |
| `io.py` | Laden/Dumpen mit Erhalt unbekannter Felder (`extra`); kanonische Ausgabe (`sort_keys`, UTF-8) |
| `cli.py` | `validate` / `inspect`; Exitcodes `0` gültig, `1` ungültig, `2` Nutzung/Lesefehler |

## CLI

```powershell
python tools/run_core.py validate examples/project_core_valid.json
python tools/run_core.py inspect examples/project_core_valid.json
```

Ausgabe: `{"valid": bool, "issues": [...]}` bzw. zusätzlich `project` + `counts`.
Exits: `0` gültig, `1` geprüft-und-ungültig, `2` Datei unlesbar (`PROJECT_UNREADABLE`).
Keine Nebenwirkungen auf Dienste, Plugins oder Hardware.

## Garantien seit Lauf 02 (RUN-AP-CORE-001-02)

- **Verlustfrei:** `project_to_dict(project_from_dict(raw)) == raw` für jede Eingabe;
  Gültigkeit entscheidet allein der Validator, `io` normalisiert nichts weg.
- **Absturzsicher:** Fehlgeformter Input ergibt strukturierte Diagnosen
  (`TYPE_SHAPE`, `ENDPOINT_SHAPE`, `VIEW_SHAPE`, `SCHEMA_INVALID`, …), nie Tracebacks.
- **Konservativ:** Payload-`compatible` nur bei beweisbarer Subsumption je Keyword;
  sonst `unknown` → `SCHEMA_NOT_PROVEN` (WARNING) bzw. `incompatible` →
  `PAYLOAD_INCOMPATIBLE` (ERROR). Diagnosen sind nach `(path, code, message)` sortiert.

## Bekannte Grenzen

- `SCHEMA_NOT_PROVEN` (WARNING): konservativ nicht beurteilbare Payload-Paare; kein impliziter Konverter.
- `CAPABILITY_DEFERRED` (WARNING): Geräteeignung ist gesonderte Adapterstufe (P0-ADR-007).
- Scope-/Authority-Auflösung nur deklarativ/referenziell; Writer-Durchsetzung und
  Runtime-Overrides sind P2 (siehe `work/runs/RUN-AP-CORE-001-01/04_offene_entscheidungen.md`).
