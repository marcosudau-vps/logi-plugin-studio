# src/runtime

> **SDK-native Einordnung 03.11.2026:** Der bestehende Runtime-/StateStore-Pfad ist die technische Python-Host-Implementierung. Er ersetzt **nicht** automatisch native Logitech-Multistate-Aktionen. Die künftige Trennung und Eigentümerschaft bestimmt [ARCH-ADR-001](../../docs/decisions/ARCH-ADR-001.md); bestehende Runtime-Tests/Abnahmen bleiben davon unberührt.

## Aktuelle lokale Host-Erweiterung: READY_FOR_REVIEW

`host.py` verwendet den vorhandenen Dispatcher/StateStore, `wire.py` stellt
das separate authentisierte Loopback-HTTP-Protokoll `studio-local-1` bereit.
Core und Runtime bleiben fachneutral, Standardbibliothek-only und ohne Qt.
Die unten dokumentierten Spikes/Abnahmen bleiben eigenstaendige Grundlagen.
Neue Produktentscheidung: [PRODUCT-ADR-001](../../docs/decisions/PRODUCT-ADR-001.md),
**PROPOSED**, keine Selbstabnahme.

```python
from runtime.host import PluginHost
from runtime.state_store import ScopeAddress
from runtime.wire import ConnectionSettings

host = PluginHost(project_path, ConnectionSettings.load(connection_path))

def on_command(payload, context):
    context.set_state("state.mode", "active",
                      ScopeAddress.component(context.component_id))
    return {"ok": True}

host.register_handler("handler.toggle", "invoke", on_command)
with host:
    run_your_application()  # trusted application code, not project JSON
```

Handler vor `start` registrieren. Oeffentlicher Vertrag:
`fn(payload, CommandContext) -> JSON`; Command-/Event-Payloads folgen dem
Typmanifest. Kein automatischer State-Write/Success-Event. `context.emit`
emittiert ausschliesslich einen eigenen deklarierten Event-Port, verschachtelt
maximal achtmal. `context.set_state` benutzt die deklarierte Component-Authority
oder die Host-Identitaet. Die fachliche Quellaktion steht in `component_id`,
das anvisierte Handlerobjekt in `target_component`; Placement ist optional.

Externe autoritative Anwendung: `host.set_state`, `read_state`, `snapshot`,
`diagnostics`; Handler muessen ihren zeitlich begrenzten Context verwenden.
`observe(callback)` vor Start registriert Journalbeobachter auf einem
eigenen Hintergrundthread, niemals direkt Widgets aendern. Langsame Observer
blockieren nicht den Command-Watchdog; Journal-Gaps werden geloggt und
verlangen einen Snapshot. Observerausnahmen werden explizit protokolliert.

`close()` liefert Namen eventuell noch laufender vertrauenswuerdiger
Callbacks; diese werden nicht gewaltsam beendet. Abgelaufene Contexts
koennen keine spaeten States/Events schreiben. Bereits ausgefuehrte externe
Effekte sind bei UNKNOWN_OUTCOME nicht rueckgaengig zu machen.
Es gibt keine aktuelle Statepersistenz, kein Command-Replay und keinen
Remotebetrieb. Private Connection-Dateien niemals veroeffentlichen.

Beispiel/Start/Diagnose: [Benutzerhandbuch](../../docs/13_Benutzerhandbuch.md).
Pruefer: `tools\run_product_checks.py`, `tools\run_example_checks.py`.

---

# Historisch: AP-CORE-002 In-Memory-Spike (experimentell)

**Status:** `SPIKE_ONLY` — ausdrücklich **nicht normativ**. Der Spike dient der
Vorbereitung von Runtime-Vorverträgen; er trifft keine verbindlichen
State-Scope-/Writer-Entscheidungen (P0-ADR-005-Gate).

## Umfang

- Statische Kompilierung bereits validierter P1-Projekte in einen
  In-Memory-Verbindungsplan (`plan.py` — nutzt `core.validate` als einzige
  Wahrheitsquelle, keine neue Endpunktnotation).
- Synchroner, deterministischer Command-/Event-Dispatch (`dispatcher.py`).
- Strukturierte Fehler/Ergebnisse (`errors.py`); keine ungefangenen
  Tracebacks für fehlerhafte Eingaben.

## Ausdrückliche Nicht-Ziele in diesem Lauf

Kein `StateStore`, kein autoritativer Writer, keine Snapshots/Resync/Heartbeat,
kein WebSocket/HTTP/IPC, kein PySide6, kein C#, keine Logitech-Anbindung.
`state`-Bindings werden als `ignored_state_binding_ids` erfasst und nie
dispatcht. Command-Result bleibt strikt von Event und State getrennt; es gibt
keine automatischen Success-Events und keine impliziten State-Sets.

## SPIKE_ONLY-Festlegungen (nicht normativ, Trade-offs in `06_runtime_vertragsentwurf.md`)

1. **Dispatch-Reihenfolge:** lexikalisch nach `binding_id`.
2. **Handler-Vertrag:** `fn(payload, ctx) -> None | {"result": ..., "emit": [...]}`.
   `emit` darf nur `out`/`event`-Ports der eigenen Komponente adressieren.
3. **Reentrancy-Schranke:** max. 8 verschachtelte Emissionen (`MAX_DEPTH`).
4. **`SCHEMA_NOT_PROVEN`:** default Block (`RUNTIME_UNPROVEN_BLOCKED`); explizit
   `allow_unproven=True` kompiliert provisorisch, quarantänierte Bindings
   bleiben blockiert (kein ungeschützter Durchlauf).

## Verwendung (Tests)

```python
from runtime.plan import compile_plan
from runtime.dispatcher import InMemoryRuntime

plan, issues = compile_plan(raw_project, registry)
runtime = InMemoryRuntime(plan)
runtime.register_handler("handler.primary", "invoke", lambda payload, ctx: {"result": {"ok": True}})
report = runtime.dispatch_command("action.primary", "activated", {})
```

Core bleibt Standardbibliothek-only; der Spike importiert nur `core.*`.

---

# AP-CORE-003 – In-Memory-StateStore (MVP, RT-ADR-001..006)

**Status:** MVP gemaess verbindlichen RT-ADRs; kein Transport-, Reconnect-
oder Persistenz-Nachweis (AP-CORE-004). Scope-Adressen und Schlüssel-
repräsentation sind interne In-Memory-Formen, kein Wire-/Projektformat.

## Umfang (`state_store.py`)

- `ScopeAddress` (`runtime` / `component` / `placement`) + `StateStore.create`
  aus validiertem P1-Projekt (Core-Validator als einzige Wahrheitsquelle;
  Draft-`project` → laufzeitweite Adresse; `session`-Scope wird als
  `STATE_SCOPE_UNSUPPORTED` abgewiesen, keine erfundenen Owner-IDs).
  Adressen werden kanonisch geprüft: `runtime` trägt keine Owner-Felder,
  `component` nur eine gültige `component_id`, `placement` nur eine gültige
  `placement_id`; widersprüchliche/fremde Felder → `STATE_SCOPE_UNKNOWN`
  ohne stille Normalisierung (Review R003-01).
- Genau ein maßgeblicher Writer je konkret adressiertem Scope
  (`WriterIdentity`: `host`/`component`/`runtime`); falsche Rolle/Identität →
  `STATE_AUTH_VIOLATION` ohne Wert-/Revisionsänderung. Session-IDs
  autorisieren nichts (kein Session-Parameter in der API).
- Wertprüfung via `core.compat.check_value` (fail closed, inkl.
  `SCHEMA_*`-Diagnosen); defensive Kopien ein/aus; `fallback` bleibt
  Konfiguration, nie automatisch `fresh`.
- Qualität `unknown`/`fresh`/`stale` strikt getrennt vom Wert; Epochenkennung
  + monotone Revision je akzeptiertem Update; `rotate_epoch()` simuliert
  explizit einen lokalen Writer-Neustart (Revisionen ab 0, Vergleich nur per
  `compare_positions`, nie rein numerisch über Epochen hinweg). Ein bereits
  verwendeter Epochen-Token wird mit `STATE_EPOCH_REUSE` abgewiesen und
  ändert Store/Revisionen nicht (Review R003-02); ohne Argument wird ein
  garantiert unbenutzter Token erzeugt.
- `snapshot()` liefert vollständigen, isolierten (deep-copy) Snapshot;
  keine Runtime-Daten im statischen Projekt.

## Integrationsmuster (intern, ohne Dispatcher-Umbau)

Der Dispatcher schreibt **nie** implizit States (RT-ADR-004). Ein als
autorisierter Writer laufender Command-Handler überführt seine bestätigte
Statusänderung explizit in den Store:

```python
from runtime.state_store import ScopeAddress, StateStore, WriterIdentity

store, issues = StateStore.create(raw_project, registry)

def on_command(payload, ctx):
    new_value = ...  # fachliche Verarbeitung, keine Demo-Hardcodings
    res = store.write("state.primary", ScopeAddress.runtime(),
                      new_value, writer=WriterIdentity.host("app-main"))
    return {"result": {"ok": res["status"] == "OK"}}
```

`dispatcher.py`/`plan.py` bleiben deshalb unverändert: Result und State
sind getrennte Vorgänge; der Store ist die einzige writer-geprüfte
Schreibstelle.

---

# AP-CORE-004 – Snapshot-/Delta-Sync über Fake-Transport (SPIKE_ONLY)

**Status:** experimenteller In-Memory-Nachweis der RT-ADR-003-Grundsätze.
**Kein** Wire-Protokoll, **kein** ACK/Retry/Timeout/Backoff, **keine** echte
Netzwerk-Authentisierung und keine Persistenz. Frame-Felder, Message-IDs,
Stream-Zähler und Fehlercodes sind lokale Testkonstrukte.

## Umfang

- `fake_transport.py`: `FakeTransportTrust` (injiziertes Fake-Vertrauensobjekt,
  HMAC-Testtag) und `FakeTransport` (FIFO-Queue, manuell: enqueue, deliver,
  drop, duplicate, swap, disconnect/reconnect). Kein Thread/Timer/Socket.
- `sync.py`: `SyncSource` liest ausschließlich den bestehenden `StateStore`
  (Snapshot bzw. explizit bestätigter `write`-Rückgabewert), `SyncMirror` ist
  ein schreibgeschütztes, nicht autoritatives Replikat, `SyncLink` verdrahtet
  beide über einen `FakeTransport`.

## Spiegelregeln (nachgewiesen)

1. Handshake (explizit als Fake markiert) → vollständiger Store-Snapshot →
   `ready`; erst danach werden Deltas akzeptiert. Der Snapshot übernimmt die
   autoritative `quality` exakt (`fresh`/`stale`, ohne Wert `unknown`).
   Widersprüchliche Kombinationen (`has_value=false` + `fresh`, `has_value=true`
   + `unknown`) werden fail-closed abgewiesen und ersetzen keine Baseline.
2. Deltas müssen zu Runtime-Instanz, Session, Stream-Generation,
   Authority-Epoch/`epoch_seq`, erwarteter Stream-Position und Revision passen.
3. Lücke, Revisionssprung, Epoch-Wechsel, fremder Ursprung oder fehlende
   Baseline führen zu einer strukturierten Reject-/Resync-Entscheidung; alte
   Werte werden nie rückwirkend als `fresh` überschrieben.
4. Disconnect setzt bekannte Werte auf `stale` (Wert bleibt), unbekannte
   bleiben `unknown`; Reconnect öffnet eine neue Session/Generation und
   initialisiert per Snapshot neu.
5. Fremder Runtime-Ursprung invalidiert die alte Mirror-Herkunft explizit;
   Werte zweier Runtime-Instanzen derselben Definition werden nie gemischt.
6. Alle Payloads, Snapshots und Mirror-Lesergebnisse sind defensive Kopien.
7. `publish_update` akzeptiert nur den `OK`-Rückgabewert eines expliziten
   Store-Writes **für denselben kanonischen Slot** (`scope_key`); Command-Results
   werden nicht umgedeutet, es gibt keinen automatischen nicht-idempotenten
   Retry. `FakeTransport.inject` weist nicht kopierbare Frames strukturiert ab,
   ohne die Queue zu verändern.

Tests: `tests/test_runtime_sync.py` (16 deterministische Fälle, inklusive vier
Regressionsfällen zu den Review-Findings R004-01..03). Vollständige Grenzen und
offene Wire-/ACK-/Auth-/Queue-Fragen:
`work/runs/RUN-AP-CORE-004-01/06_sync_vertragsvorschlag.md` sowie der
Nachtrag `work/runs/RUN-AP-CORE-004-02/06_sync_vertragsvorschlag.md`.

## Native Callback-Felder

Der signierte Command-Wire transportiert optional `action_parameter`,
`operation`, `adjustment_diff` und `editor_values`. `action_parameter` ist der
unveränderte Wert aus Logitechs `RunCommand(String actionParameter)` und wird
niemals aus der Folder-`placement_id` abgeleitet. Fehlende Felder bleiben für
ältere Clients zulässig. Replay-, Deadline-, Auth- und Non-Retry-Regeln gelten
unverändert; die zusätzlichen Felder sind Teil des Request-Fingerprints.
