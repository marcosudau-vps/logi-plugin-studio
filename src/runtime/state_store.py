"""Fachneutraler In-Memory-StateStore (AP-CORE-003, RT-ADR-002/003/005).

Minimal viable store for one runtime execution: typed, canonically checked
scope addresses (no silent normalization), single authoritative writer per
concrete scope, conservative value validation, separated quality
(unknown/fresh/stale), writer-epoch plus monotonic revision (epoch tokens are
never reused after a revision reset), and internally consistent snapshots.

Ausdrücklich keine Transport-/Reconnect-/Persistenz-Implementierung
(AP-CORE-004), keine Netzwerk-Authentisierung, kein Event-Sourcing, keine
impliziten State-Sets durch Command-Dispatch (RT-ADR-004). Standardbibliothek
plus ``core.*`` (Validator, ``check_value``, IDs) wie der Rest von
``src/runtime``.
"""
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Any

from .errors import (
    STATE_AUTH_VIOLATION,
    STATE_DEFINITION_UNKNOWN,
    STATE_EPOCH_REUSE,
    STATE_NO_VALUE,
    STATE_OK,
    STATE_SCOPE_MISMATCH,
    STATE_SCOPE_UNKNOWN,
    STATE_SCOPE_UNSUPPORTED,
    STATE_VALUE_INVALID,
)

SCOPE_KINDS = ("runtime", "component", "placement")
WRITER_ROLES = ("host", "component", "runtime")
QUALITIES = ("unknown", "fresh", "stale")

# Draft-Scope (statisches Projekt, P1) -> Laufzeit-Scope-Kategorie (RT-ADR-002).
# ``session`` ist in V1 kein regulaerer fachlicher State-Scope und wird als
# STATE_SCOPE_UNSUPPORTED abgewiesen; es werden keine Owner-IDs erfunden.
_DRAFT_TO_KIND = {"project": "runtime", "component": "component", "placement": "placement"}


def _new_token() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True)
class ScopeAddress:
    """Typisierte In-Memory-Scope-Adresse (RT-ADR-002).

    - ``runtime``: projektweit gueltig innerhalb genau einer Ausfuehrung.
    - ``component``: genau eine existierende ComponentInstance.
    - ``placement``: genau ein existierendes Placement (unterscheidet
      Mehrfachplatzierungen derselben Komponente).
    """

    kind: str
    component_id: str | None = None
    placement_id: str | None = None

    @classmethod
    def runtime(cls) -> "ScopeAddress":
        return cls(kind="runtime")

    @classmethod
    def component(cls, component_id: str) -> "ScopeAddress":
        return cls(kind="component", component_id=component_id)

    @classmethod
    def placement(cls, placement_id: str) -> "ScopeAddress":
        return cls(kind="placement", placement_id=placement_id)

    def canonical_problem(self) -> str | None:
        """Prueft die exklusive Feldbelegung je Scope-Kategorie.

        Gibt ``None`` fuer eine kanonische Adresse zurueck, sonst eine
        Beschreibung der unzulaessigen Felder. Es wird bewusst **nicht**
        normalisiert: Aufrufer muessen eine nicht-kanonische Adresse
        strukturiert abweisen (R003-01).
        """
        if self.kind == "runtime":
            if self.component_id is not None or self.placement_id is not None:
                return ("runtime scope carries no owner fields "
                        f"(component_id={self.component_id!r}, "
                        f"placement_id={self.placement_id!r})")
            return None
        if self.kind == "component":
            if not isinstance(self.component_id, str) or not self.component_id:
                return "component scope requires a non-empty component_id"
            if self.placement_id is not None:
                return ("component scope carries no placement_id "
                        f"(placement_id={self.placement_id!r})")
            return None
        if self.kind == "placement":
            if not isinstance(self.placement_id, str) or not self.placement_id:
                return "placement scope requires a non-empty placement_id"
            if self.component_id is not None:
                return ("placement scope carries no component_id "
                        f"(component_id={self.component_id!r})")
            return None
        return f"unknown scope kind {self.kind!r}"

    def key(self) -> tuple:
        if self.kind == "runtime":
            return ("runtime",)
        if self.kind == "component":
            return ("component", self.component_id)
        if self.kind == "placement":
            return ("placement", self.placement_id)
        return ("invalid", self.kind, self.component_id, self.placement_id)

    def key_string(self, state_id: str) -> str:
        if self.kind == "runtime":
            return f"{state_id}@runtime"
        if self.kind == "component":
            return f"{state_id}@component:{self.component_id}"
        if self.kind == "placement":
            return f"{state_id}@placement:{self.placement_id}"
        return f"{state_id}@invalid:{self.kind}"

    def as_dict(self) -> dict:
        out: dict[str, Any] = {"kind": self.kind}
        if self.kind == "component":
            out["component_id"] = self.component_id
        elif self.kind == "placement":
            out["placement_id"] = self.placement_id
        return out


@dataclass(frozen=True)
class WriterIdentity:
    """Explizite Caller-Identitaet fuer Schreibversuche (RT-ADR-002).

    Test-Handles der ersten In-Memory-Stufe; keine Netzwerk-Authentisierung.
    Eine Session-ID allein autorisiert niemals: die API besitzt ueberhaupt
    keinen Session-Parameter, Autorisierung erfolgt ausschliesslich ueber
    dieses Handle-Objekt plus deklarierte Authority-Rolle.
    """

    role: str
    identity: str

    @classmethod
    def host(cls, handle: str) -> "WriterIdentity":
        return cls(role="host", identity=handle)

    @classmethod
    def component(cls, component_id: str) -> "WriterIdentity":
        return cls(role="component", identity=component_id)

    @classmethod
    def runtime(cls, runtime_instance_id: str) -> "WriterIdentity":
        return cls(role="runtime", identity=runtime_instance_id)


def _issue(code: str, path: str, message: str) -> dict:
    return {"code": code, "path": path, "message": message}


def _safe_copy(value: Any) -> tuple[bool, Any]:
    try:
        return True, copy.deepcopy(value)
    except Exception:
        return False, None


def compare_positions(a: dict, b: dict) -> str:
    """Vergleicht zwei (epoch, epoch_seq, revision)-Positionen.

    Gibt ``"newer"`` / ``"older"`` / ``"equal"`` zurueck, oder
    ``"incomparable"`` bei verschiedenen Epochen-Token: Revisionen duerfen
    nicht numerisch ueber Epochen-Grenzen hinweg verglichen werden
    (RT-ADR-003). Innerhalb derselben Epoche entscheidet die Revision.
    """
    if a.get("epoch") != b.get("epoch"):
        return "incomparable"
    if a.get("revision", 0) > b.get("revision", 0):
        return "newer"
    if a.get("revision", 0) < b.get("revision", 0):
        return "older"
    return "equal"


@dataclass
class _Entry:
    value: Any = None
    has_value: bool = False
    quality: str = "unknown"
    revision: int = 0
    epoch: str = ""
    epoch_seq: int = 0


class StateStore:
    """In-Memory-StateStore genau einer Runtime-Ausfuehrung."""

    def __init__(self) -> None:
        raise TypeError("Use StateStore.create(raw, registry, ...) instead")

    @classmethod
    def _blank(cls) -> "StateStore":
        obj = cls.__new__(cls)
        return obj

    @classmethod
    def create(cls, raw: Any, registry: Any, *,
               runtime_instance_id: str | None = None,
               epoch: str | None = None):
        """Baut einen Store aus einem validierten P1-Projekt.

        Gibt ``(store_oder_None, issues)`` zurueck (sortiert wie der Core).
        Jeder ``ERROR`` (Projektvalidierung, Registry, Session-Scope,
        unbekannte Authority-Rolle) verweigert die Erstellung. Das ``raw``-
        Dokument wird nie mutiert; Schemas/Fallbacks werden deep-kopiert.
        """
        from core.validate import is_valid, validate_project
        from core.errors import Diagnostic

        def diag(code: str, path: str, message: str, severity: str = "ERROR") -> Diagnostic:
            return Diagnostic(code, path, message, severity)

        if not isinstance(raw, dict):
            return None, [diag("PROJECT_SHAPE", "/", "Root must be an object")]

        issues: list = list(getattr(registry, "issues", []) or [])
        try:
            core_issues = validate_project(raw, registry)
        except Exception as exc:  # fail closed, nie Traceback
            return None, sorted(
                [*issues, diag("RUNTIME_COMPILE_ERROR", "/", f"Validator raised: {exc}")],
                key=lambda d: d.sort_key(),
            )
        issues.extend(core_issues)
        if not is_valid(issues):
            return None, sorted(issues, key=lambda d: d.sort_key())

        components: set[str] = set()
        for comp in raw.get("components", []) if isinstance(raw.get("components"), list) else []:
            if isinstance(comp, dict) and isinstance(comp.get("id"), str):
                components.add(comp["id"])
        placements: dict[str, str] = {}
        for view in raw.get("views", []) if isinstance(raw.get("views"), list) else []:
            if not isinstance(view, dict):
                continue
            pls = view.get("placements")
            if not isinstance(pls, list):
                continue
            for pl in pls:
                if isinstance(pl, dict) and isinstance(pl.get("id"), str) \
                        and isinstance(pl.get("component"), str):
                    placements[pl["id"]] = pl["component"]

        definitions: dict[str, Any] = {}
        for idx, state in enumerate(raw.get("states", []) if isinstance(raw.get("states"), list) else []):
            if not isinstance(state, dict) or not isinstance(state.get("id"), str):
                continue  # Formfehler waere oben bereits ERROR gewesen
            sid = state["id"]
            draft_scope = state.get("scope")
            if draft_scope == "session" or draft_scope not in _DRAFT_TO_KIND:
                # "session" passiert den Draft-Core-Validator, ist aber in V1
                # kein regulaerer State-Scope (RT-ADR-002): kein stilles
                # Umdeuten, keine erfundenen Owner-IDs.
                return None, sorted(
                    [*issues, diag(
                        STATE_SCOPE_UNSUPPORTED, f"/states/{idx}/scope",
                        f"State {sid!r}: draft scope {draft_scope!r} is not a "
                        "supported V1 runtime scope (RT-ADR-002: runtime, "
                        "component, placement only).")],
                    key=lambda d: d.sort_key())
            role = state.get("authority", {}).get("role") \
                if isinstance(state.get("authority"), dict) else None
            if role not in WRITER_ROLES:
                return None, sorted(
                    [*issues, diag(
                        STATE_AUTH_VIOLATION, f"/states/{idx}/authority",
                        f"State {sid!r}: unsupported authority role {role!r} "
                        "(RT-ADR-002: host, component, runtime only).")],
                    key=lambda d: d.sort_key())
            ok, schema = _safe_copy(state.get("value_schema", {}))
            if not ok:
                return None, sorted(
                    [*issues, diag(
                        STATE_VALUE_INVALID, f"/states/{idx}/value_schema",
                        f"State {sid!r}: value_schema is not processable.")],
                    key=lambda d: d.sort_key())
            ok, fallback = _safe_copy(state.get("fallback"))
            has_fallback = "fallback" in state and ok
            definitions[sid] = {
                "value_schema": schema,
                "authority_role": role,
                "authority_component": state.get("authority", {}).get("component")
                if isinstance(state.get("authority"), dict) else None,
                "draft_scope": draft_scope,
                "kind": _DRAFT_TO_KIND[draft_scope],
                "fallback": fallback if has_fallback else None,
                "has_fallback": has_fallback,
                "state_index": idx,
            }

        store = cls._blank()
        store._runtime_instance_id = runtime_instance_id or _new_token()
        store._project_id = raw.get("project", {}).get("id") \
            if isinstance(raw.get("project"), dict) else ""
        store._epoch = epoch or _new_token()
        store._epoch_seq = 0
        store._epoch_history = {store._epoch}
        store._definitions = definitions
        store._components = components
        store._placements = placements
        # Vollstaendige Vorab-Materialisierung aller gueltigen Kombinationen:
        # project -> je 1 Eintrag; component -> je Komponente; placement ->
        # je Placement. Dadurch ist jeder gueltige Snapshot "vollstaendig";
        # ungueltige Kombinationen existieren gar nicht erst.
        store._entries: dict[tuple, _Entry] = {}
        for sid, spec in definitions.items():
            if spec["kind"] == "runtime":
                store._entries[(sid, ("runtime",))] = _Entry(
                    epoch=store._epoch, epoch_seq=0)
            elif spec["kind"] == "component":
                for cid in sorted(components):
                    store._entries[(sid, ("component", cid))] = _Entry(
                        epoch=store._epoch, epoch_seq=0)
            else:
                for pid in sorted(placements):
                    store._entries[(sid, ("placement", pid))] = _Entry(
                        epoch=store._epoch, epoch_seq=0)
        return store, sorted(issues, key=lambda d: d.sort_key())

    # -- Eigenschaften ---------------------------------------------------
    @property
    def runtime_instance_id(self) -> str:
        return self._runtime_instance_id

    @property
    def epoch(self) -> str:
        return self._epoch

    @property
    def epoch_seq(self) -> int:
        return self._epoch_seq

    @property
    def state_ids(self) -> tuple:
        return tuple(sorted(self._definitions))

    # -- interne Pruefung --------------------------------------------------
    def _resolve(self, state_id: Any, scope: Any):
        """Prueft State-ID, Scope-Adresse und Scope-Kompatibilitaet.

        Gibt ``(spec, scope_key, scope_string, entry, issues)`` zurueck;
        ``entry`` ist None bei Fehler (issues nicht leer).
        """
        from core.ids import is_valid_id

        if not isinstance(state_id, str) or not is_valid_id(state_id) \
                or state_id not in self._definitions:
            return None, None, "", None, [_issue(
                STATE_DEFINITION_UNKNOWN, f"/states/{state_id}",
                f"Unknown state {state_id!r}.")]
        spec = self._definitions[state_id]
        if not isinstance(scope, ScopeAddress) or scope.kind not in SCOPE_KINDS:
            return None, None, "", None, [_issue(
                STATE_SCOPE_UNKNOWN, f"/states/{state_id}/scope",
                f"Invalid scope address {scope!r}; expected runtime, "
                "component or placement ScopeAddress.")]
        problem = scope.canonical_problem()
        if problem:
            # Keine stille Normalisierung: Adressen mit fremden oder
            # widerspruechlichen Feldern werden strukturiert abgewiesen
            # (Review R003-01), unabhaengig von der State-Definition.
            return None, None, "", None, [_issue(
                STATE_SCOPE_UNKNOWN, f"/states/{state_id}/scope",
                f"Non-canonical scope address {scope!r} rejected: {problem}.")]
        if scope.kind != spec["kind"]:
            return None, None, "", None, [_issue(
                STATE_SCOPE_MISMATCH, f"/states/{state_id}/scope",
                f"State {state_id!r} is {spec['kind']}-scoped "
                f"(draft: {spec['draft_scope']!r}); address kind "
                f"{scope.kind!r} does not match.")]
        if scope.kind == "component":
            if not isinstance(scope.component_id, str) \
                    or scope.component_id not in self._components:
                return None, None, "", None, [_issue(
                    STATE_SCOPE_UNKNOWN, f"/states/{state_id}/scope",
                    f"Unknown component {scope.component_id!r} for "
                    f"component-scoped state {state_id!r}.")]
            key = (state_id, ("component", scope.component_id))
        elif scope.kind == "placement":
            if not isinstance(scope.placement_id, str) \
                    or scope.placement_id not in self._placements:
                return None, None, "", None, [_issue(
                    STATE_SCOPE_UNKNOWN, f"/states/{state_id}/scope",
                    f"Unknown placement {scope.placement_id!r} for "
                    f"placement-scoped state {state_id!r}.")]
            key = (state_id, ("placement", scope.placement_id))
        else:
            key = (state_id, ("runtime",))
        entry = self._entries.get(key)
        if entry is None:  # defensive: Kombination wurde nie materialisiert
            return None, None, "", None, [_issue(
                STATE_SCOPE_UNKNOWN, f"/states/{state_id}/scope",
                f"Scope combination for state {state_id!r} is not instantiated.")]
        addr = ScopeAddress(kind=scope.kind, component_id=scope.component_id,
                            placement_id=scope.placement_id)
        return spec, key, addr.key_string(state_id), entry, []

    def _authorized(self, spec: Any, state_id: str, writer: Any):
        """Prueft Rolle und Identitaet gegen die deklarierte Authority."""
        if not isinstance(writer, WriterIdentity) or writer.role not in WRITER_ROLES \
                or not isinstance(writer.identity, str) or not writer.identity:
            return [_issue(
                STATE_AUTH_VIOLATION, f"/states/{state_id}/authority",
                "Write requires an explicit WriterIdentity (host, component "
                "or runtime with non-empty handle); session IDs alone never "
                "authorize (RT-ADR-002).")]
        declared = spec["authority_role"]
        if writer.role != declared:
            return [_issue(
                STATE_AUTH_VIOLATION, f"/states/{state_id}/authority",
                f"Writer role {writer.role!r} does not match declared "
                f"authority role {declared!r} for state {state_id!r}; value, "
                "quality and revision unchanged.")]
        if declared == "component":
            expected = spec["authority_component"]
            if writer.identity != expected:
                return [_issue(
                    STATE_AUTH_VIOLATION, f"/states/{state_id}/authority",
                    f"Component writer {writer.identity!r} is not the declared "
                    f"authority {expected!r} for state {state_id!r}.")]
        elif declared == "runtime":
            if writer.identity != self._runtime_instance_id:
                return [_issue(
                    STATE_AUTH_VIOLATION, f"/states/{state_id}/authority",
                    f"Runtime writer identity does not match this execution "
                    f"({self._runtime_instance_id!r}); cross-runtime writes "
                    "are rejected.")]
        # declared == "host": jede explizite Host-Handle-Identitaet ist im
        # In-Memory-Testmassstab zulaessig (V1: eine primaere Anwendung);
        # Netzwerk-Nachweis ist ausserhalb dieses Auftrags (RT-ADR-002).
        return []

    # -- oeffentliche Operationen ------------------------------------------
    def read(self, state_id: Any, scope: Any) -> dict:
        """Liest einen Eintrag; nie Exception bei fehlerhafter Adresse."""
        spec, _key, scope_str, entry, problems = self._resolve(state_id, scope)
        if problems:
            return {"status": problems[0]["code"], "issues": problems,
                    "state_id": state_id if isinstance(state_id, str) else "",
                    "scope": {}, "has_value": False, "quality": "unknown",
                    "revision": 0, "epoch": self._epoch, "epoch_seq": self._epoch_seq}
        ok, value = _safe_copy(entry.value) if entry.has_value else (True, None)
        ok_fb, fallback = _safe_copy(spec["fallback"]) if spec["has_fallback"] else (True, None)
        return {"status": STATE_OK, "issues": [],
                "state_id": state_id, "scope": ScopeAddress(
                    kind=scope.kind, component_id=scope.component_id,
                    placement_id=scope.placement_id).as_dict(),
                "scope_key": scope_str,
                "value": value if ok else None, "has_value": entry.has_value and ok,
                "quality": entry.quality, "revision": entry.revision,
                "epoch": entry.epoch, "epoch_seq": entry.epoch_seq,
                "fallback": fallback if ok_fb else None,
                "has_fallback": spec["has_fallback"] and ok_fb}

    def write(self, state_id: Any, scope: Any, value: Any, *, writer: Any) -> dict:
        """Autorisierter Schreibversuch; Ablehnung aendert nichts."""
        from core.compat import check_value

        spec, _key, scope_str, entry, problems = self._resolve(state_id, scope)
        if problems:
            return {"status": problems[0]["code"], "issues": problems,
                    "revision": 0, "epoch": self._epoch, "epoch_seq": self._epoch_seq}
        auth_problems = self._authorized(spec, state_id, writer)
        if auth_problems:
            return {"status": STATE_AUTH_VIOLATION, "issues": auth_problems,
                    "revision": entry.revision, "epoch": entry.epoch,
                    "epoch_seq": entry.epoch_seq}
        ok, staged = _safe_copy(value)
        if not ok:
            return {"status": STATE_VALUE_INVALID, "issues": [_issue(
                STATE_VALUE_INVALID, f"/states/{state_id}/value",
                "Value is not processable; only JSON-compatible values are "
                "accepted. Nothing changed.")],
                "revision": entry.revision, "epoch": entry.epoch,
                "epoch_seq": entry.epoch_seq}
        violations = check_value(staged, spec["value_schema"])
        if violations:
            # Fail closed: unbekannte/nicht unterstuetzte Constraints
            # (SCHEMA_*) wie Wertfehler behandeln; nie speichern.
            return {"status": STATE_VALUE_INVALID, "issues": [
                {"code": code, "path": f"/states/{state_id}/value", "message": detail}
                for code, detail in violations],
                "revision": entry.revision, "epoch": entry.epoch,
                "epoch_seq": entry.epoch_seq}
        entry.value = staged  # bereits isolierte Kopie
        entry.has_value = True
        entry.quality = "fresh"
        entry.revision += 1
        entry.epoch = self._epoch
        entry.epoch_seq = self._epoch_seq
        return {"status": STATE_OK, "issues": [], "scope_key": scope_str,
                "revision": entry.revision, "epoch": entry.epoch,
                "epoch_seq": entry.epoch_seq, "quality": entry.quality}

    def mark_stale(self, state_id: Any, scope: Any) -> dict:
        """Simulierter lokaler Qualitaetswechsel (z. B. nach Verbindungsabbruch).

        Aendert den fachlichen Wert nicht (RT-ADR-003/005); setzt nur
        ``fresh`` -> ``stale``. Ohne bekannten Wert strukturierter Fehler.
        """
        spec, _key, scope_str, entry, problems = self._resolve(state_id, scope)
        if problems:
            return {"status": problems[0]["code"], "issues": problems}
        if not entry.has_value:
            return {"status": STATE_NO_VALUE, "issues": [_issue(
                STATE_NO_VALUE, f"/states/{state_id}",
                "No confirmed live value; quality stays unknown. "
                "Fallback is config, not a live value.")]}
        if entry.quality == "fresh":
            entry.quality = "stale"
        return {"status": STATE_OK, "issues": [], "scope_key": scope_str,
                "quality": entry.quality, "revision": entry.revision,
                "epoch": entry.epoch, "epoch_seq": entry.epoch_seq}

    def rotate_epoch(self, new_epoch: str | None = None) -> dict:
        """Explizit simulierter lokaler Writer-Neustart (kein Failover-Protokoll).

        Neue Epochenkennung, Revisionszaehler je Eintrag zurueck auf 0;
        Werte und Qualitaet bleiben erhalten. Danach duerfen Positionen
        unterschiedlicher Epochen-Token nicht mehr numerisch verglichen
        werden (siehe :func:`compare_positions`).

        Ein bereits verwendeter Epochen-Token (insbesondere der aktuelle)
        wird strukturiert mit ``STATE_EPOCH_REUSE`` abgewiesen und aendert
        Store, Revisionen und ``epoch_seq`` nicht (Review R003-02). Wird kein
        Token uebergeben, wird garantiert ein bisher unbenutzter erzeugt.
        """
        if isinstance(new_epoch, str) and new_epoch:
            if new_epoch == self._epoch or new_epoch in self._epoch_history:
                return {"status": STATE_EPOCH_REUSE, "issues": [_issue(
                    STATE_EPOCH_REUSE, "/epoch",
                    f"Epoch token {new_epoch!r} was already used by this store; "
                    "reusing it after a revision reset would make positions "
                    "ambiguous. Store, epoch and revisions unchanged.")],
                    "epoch": self._epoch, "epoch_seq": self._epoch_seq}
            token = new_epoch
        else:
            token = _new_token()
            while token == self._epoch or token in self._epoch_history:
                token = _new_token()
        self._epoch = token
        self._epoch_history.add(token)
        self._epoch_seq += 1
        for entry in self._entries.values():
            entry.epoch = self._epoch
            entry.epoch_seq = self._epoch_seq
            entry.revision = 0
        return {"status": STATE_OK, "issues": [], "epoch": self._epoch,
                "epoch_seq": self._epoch_seq}

    def snapshot(self) -> dict:
        """Vollstaendiger, intern konsistenter In-Memory-Snapshot.

        Deep-Kopien ohne mutierbare Aliase zum Store; wiederholte Snapshots
        ohne Zwischenaenderung sind gleich. Kein Transport-Nachweis.
        """
        states: dict[str, dict] = {}
        for (sid, _k) in sorted(self._entries, key=lambda t: self._scope_string(t)):
            entry = self._entries[(sid, _k)]
            spec = self._definitions[sid]
            addr = self._address_of(sid, _k)
            ok_v, value = _safe_copy(entry.value) if entry.has_value else (True, None)
            ok_f, fallback = _safe_copy(spec["fallback"]) if spec["has_fallback"] else (True, None)
            states[addr.key_string(sid)] = {
                "state_id": sid, "scope": addr.as_dict(),
                "value": value if ok_v else None,
                "has_value": entry.has_value and ok_v,
                "quality": entry.quality, "revision": entry.revision,
                "epoch": entry.epoch, "epoch_seq": entry.epoch_seq,
                "fallback": fallback if ok_f else None,
                "has_fallback": spec["has_fallback"] and ok_f,
            }
        return {"status": STATE_OK, "issues": [],
                "runtime_instance_id": self._runtime_instance_id,
                "project_id": self._project_id,
                "epoch": self._epoch, "epoch_seq": self._epoch_seq,
                "state_count": len(states), "states": states}

    # -- Hilfen --------------------------------------------------------------
    def _scope_string(self, key_tuple: tuple) -> str:
        sid, sk = key_tuple
        addr = self._address_of(sid, sk)
        return addr.key_string(sid)

    def _address_of(self, sid: str, sk: tuple) -> ScopeAddress:
        if sk[0] == "runtime":
            return ScopeAddress.runtime()
        if sk[0] == "component":
            return ScopeAddress.component(sk[1])
        return ScopeAddress.placement(sk[1])
