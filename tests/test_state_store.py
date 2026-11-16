"""AP-CORE-003 StateStore tests (stdlib only, deterministic).

Covers the nine mandatory areas: valid runtime write; rejected wrong
writer (unchanged value/quality/revision); type/enum/unknown errors;
runtime/component/placement scopes incl. placement independence and
component sharing; two independent executions; fallback vs. live value
and stale semantics; revision/epoch incl. simulated writer restart;
snapshot isolation/determinism and untouched static project; explicit
dispatcher-to-store integration without implicit writes.
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.io import load_raw  # noqa: E402
from core.registry import load_manifests  # noqa: E402
from runtime.state_store import (  # noqa: E402
    ScopeAddress,
    StateStore,
    WriterIdentity,
    compare_positions,
)
from runtime.errors import STATE_EPOCH_REUSE, STATE_SCOPE_UNKNOWN  # noqa: E402


def fresh_registry():
    reg, errors = load_manifests(ROOT / "component_types")
    assert not errors, [e.as_dict() for e in errors]
    return reg


def base_raw():
    return load_raw(ROOT / "examples" / "project_core_valid.json")


def make_store(raw=None, registry=None, **kw):
    raw = base_raw() if raw is None else raw
    registry = fresh_registry() if registry is None else registry
    return StateStore.create(raw, registry, **kw)


def with_extra_states(*states):
    raw = base_raw()
    raw["states"] = list(raw.get("states", [])) + list(states)
    return raw


def component_state(sid="cstate.one", authority=None):
    return {
        "id": sid,
        "value_schema": {"type": "string"},
        "authority": authority or {"role": "component", "component": "action.primary"},
        "scope": "component",
        "persistence": "none",
    }


def placement_state(sid="pstate.one"):
    return {
        "id": sid,
        "value_schema": {"type": "string"},
        "authority": {"role": "host"},
        "scope": "placement",
        "persistence": "none",
    }


class TestRuntimeWrite(unittest.TestCase):
    def test_01_valid_host_write_fresh_and_revision(self):
        store, issues = make_store()
        self.assertIsNotNone(store, [i.as_dict() for i in issues])
        before = store.read("state.primary", ScopeAddress.runtime())
        self.assertEqual(before["status"], "OK")
        self.assertFalse(before["has_value"])
        self.assertEqual(before["quality"], "unknown")
        self.assertEqual(before["revision"], 0)
        res = store.write("state.primary", ScopeAddress.runtime(), "variant_1",
                          writer=WriterIdentity.host("app-main"))
        self.assertEqual(res["status"], "OK", res)
        self.assertEqual(res["revision"], 1)
        self.assertEqual(res["quality"], "fresh")
        after = store.read("state.primary", ScopeAddress.runtime())
        self.assertEqual(after["value"], "variant_1")
        self.assertEqual(after["quality"], "fresh")
        self.assertEqual(after["revision"], 1)
        # Fallback bleibt Konfiguration, kein Live-Wert.
        self.assertTrue(after["has_fallback"])
        self.assertEqual(after["fallback"], "variant_0")
        res2 = store.write("state.primary", ScopeAddress.runtime(), "variant_0",
                           writer=WriterIdentity.host("app-main"))
        self.assertEqual(res2["revision"], 2)


class TestWriterAuthority(unittest.TestCase):
    def test_02_wrong_role_identity_rejected_unchanged(self):
        store, _ = make_store()
        ok = store.write("state.primary", ScopeAddress.runtime(), "variant_1",
                         writer=WriterIdentity.host("app-main"))
        self.assertEqual(ok["status"], "OK")
        bad_writers = [
            WriterIdentity.component("action.primary"),
            WriterIdentity.runtime(store.runtime_instance_id),
            WriterIdentity.component("handler.primary"),
            WriterIdentity.host(""),  # leeres Handle
            {"role": "host", "session_id": "sess-1"},  # Session-String allein
            "host",
            None,
        ]
        for writer in bad_writers:
            with self.subTest(writer=writer):
                res = store.write("state.primary", ScopeAddress.runtime(),
                                  "variant_0", writer=writer)
                self.assertEqual(res["status"], "STATE_AUTH_VIOLATION", res)
                self.assertTrue(res["issues"])
        current = store.read("state.primary", ScopeAddress.runtime())
        self.assertEqual(current["value"], "variant_1")
        self.assertEqual(current["quality"], "fresh")
        self.assertEqual(current["revision"], 1)

    def test_02b_component_and_runtime_authority(self):
        raw = with_extra_states(component_state())
        store, issues = make_store(raw=raw)
        self.assertIsNotNone(store, [i.as_dict() for i in issues])
        addr = ScopeAddress.component("action.primary")
        # Falsche Komponente und fremde Rollen abgewiesen.
        for writer in (WriterIdentity.host("app-main"),
                       WriterIdentity.component("handler.primary"),
                       WriterIdentity.runtime(store.runtime_instance_id)):
            res = store.write("cstate.one", addr, "x", writer=writer)
            self.assertEqual(res["status"], "STATE_AUTH_VIOLATION", (writer, res))
        good = store.write("cstate.one", addr, "x",
                           writer=WriterIdentity.component("action.primary"))
        self.assertEqual(good["status"], "OK", good)


class TestValueErrors(unittest.TestCase):
    def test_03_type_enum_unknown_scope_no_exceptions(self):
        store, _ = make_store()
        bad_values = [123, True, None, ["variant_1"], {"v": "variant_1"},
                      "nope", memoryview(b"variant_1")]
        for value in bad_values:
            with self.subTest(value=type(value).__name__):
                res = store.write("state.primary", ScopeAddress.runtime(), value,
                                  writer=WriterIdentity.host("app-main"))
                self.assertNotEqual(res["status"], "OK", res)
                self.assertTrue(res["issues"])
        # Unbekannte State-ID, ungueltige Adressen, Scope-Mismatch.
        self.assertEqual(
            store.read("state.missing", ScopeAddress.runtime())["status"],
            "STATE_DEFINITION_UNKNOWN")
        self.assertEqual(
            store.write("state.missing", ScopeAddress.runtime(), "variant_1",
                        writer=WriterIdentity.host("h"))["status"],
            "STATE_DEFINITION_UNKNOWN")
        self.assertEqual(
            store.read("state.primary", ScopeAddress(kind="bogus"))["status"],
            "STATE_SCOPE_UNKNOWN")
        self.assertEqual(
            store.write("state.primary", ScopeAddress.component("action.primary"),
                        "variant_1", writer=WriterIdentity.host("h"))["status"],
            "STATE_SCOPE_MISMATCH")
        self.assertEqual(
            store.write("state.primary", ScopeAddress.component("no.such"),
                        "variant_1", writer=WriterIdentity.host("h"))["status"],
            "STATE_SCOPE_MISMATCH")  # Adressart geht vor Existenzpruefung
        self.assertEqual(
            store.write("state.primary", ScopeAddress.placement("no.such"),
                        "variant_1", writer=WriterIdentity.host("h"))["status"],
            "STATE_SCOPE_MISMATCH")  # Adressart geht vor Existenzpruefung
        # Unveraendert nach allen Ablehnungen.
        current = store.read("state.primary", ScopeAddress.runtime())
        self.assertFalse(current["has_value"])
        self.assertEqual(current["quality"], "unknown")
        self.assertEqual(current["revision"], 0)


class TestScopes(unittest.TestCase):
    def test_04_component_placement_scopes(self):
        raw = with_extra_states(component_state(), placement_state())
        store, issues = make_store(raw=raw)
        self.assertIsNotNone(store, [i.as_dict() for i in issues])
        host = WriterIdentity.host("app-main")
        comp_w = WriterIdentity.component("action.primary")
        # Komponenten-Scope: gleiche State-ID je Komponente unabhaengig.
        r1 = store.write("cstate.one", ScopeAddress.component("action.primary"),
                         "A", writer=comp_w)
        self.assertEqual(r1["status"], "OK", r1)
        other = store.read("cstate.one", ScopeAddress.component("handler.primary"))
        self.assertEqual(other["status"], "OK")
        self.assertFalse(other["has_value"])
        # Placement-Scope: zwei Placements derselben Komponente unabhaengig.
        p1 = store.write("pstate.one", ScopeAddress.placement("placement.main"),
                         "M", writer=host)
        self.assertEqual(p1["status"], "OK", p1)
        p2 = store.read("pstate.one", ScopeAddress.placement("placement.secondary"))
        self.assertEqual(p2["status"], "OK")
        self.assertFalse(p2["has_value"])
        self.assertEqual(
            store.read("pstate.one", ScopeAddress.placement("placement.main"))["value"], "M")
        # Unbekannte Owner-IDs bei passender Adressart.
        self.assertEqual(
            store.read("cstate.one", ScopeAddress.component("no.such"))["status"],
            "STATE_SCOPE_UNKNOWN")
        self.assertEqual(
            store.read("pstate.one", ScopeAddress.placement("no.such"))["status"],
            "STATE_SCOPE_UNKNOWN")
        # Komponenten-State ist pro Komponente genau ein Eintrag (geteilt ueber
        # Placements): erneutes Lesen derselben Adresse liefert denselben Wert.
        again = store.read("cstate.one", ScopeAddress.component("action.primary"))
        self.assertEqual((again["value"], again["revision"]), ("A", 1))
        # Falsche Adressart je Definition.
        self.assertEqual(
            store.read("cstate.one", ScopeAddress.runtime())["status"],
            "STATE_SCOPE_MISMATCH")
        self.assertEqual(
            store.read("pstate.one", ScopeAddress.component("action.primary"))["status"],
            "STATE_SCOPE_MISMATCH")

    def test_04b_session_scope_rejected_at_creation(self):
        raw = with_extra_states({
            "id": "sstate.one", "value_schema": {"type": "string"},
            "authority": {"role": "host"}, "scope": "session", "persistence": "none"})
        store, issues = make_store(raw=raw)
        self.assertIsNone(store)
        self.assertTrue(any(i.code == "STATE_SCOPE_UNSUPPORTED" and i.severity == "ERROR"
                            for i in issues), [i.as_dict() for i in issues])


class TestIsolation(unittest.TestCase):
    def test_05_two_executions_share_nothing(self):
        raw = base_raw()
        reg = fresh_registry()
        s1, i1 = StateStore.create(copy.deepcopy(raw), reg,
                                   runtime_instance_id="exec.one", epoch="ep-init-1")
        s2, i2 = StateStore.create(copy.deepcopy(raw), reg,
                                   runtime_instance_id="exec.two", epoch="ep-init-2")
        self.assertIsNotNone(s1, [i.as_dict() for i in i1])
        self.assertIsNotNone(s2, [i.as_dict() for i in i2])
        self.assertNotEqual(s1.runtime_instance_id, s2.runtime_instance_id)
        host = WriterIdentity.host("app-main")
        w1 = s1.write("state.primary", ScopeAddress.runtime(), "variant_1", writer=host)
        self.assertEqual(w1["status"], "OK")
        r2 = s2.read("state.primary", ScopeAddress.runtime())
        self.assertFalse(r2["has_value"])
        self.assertEqual(r2["quality"], "unknown")
        # Runtime-Writer ist an die eigene Ausfuehrung gebunden.
        raw_rt = with_extra_states({
            "id": "rstate.one", "value_schema": {"type": "string"},
            "authority": {"role": "runtime"}, "scope": "project", "persistence": "none"})
        a, _ = StateStore.create(copy.deepcopy(raw_rt), reg, runtime_instance_id="ra")
        b, _ = StateStore.create(copy.deepcopy(raw_rt), reg, runtime_instance_id="rb")
        ok = a.write("rstate.one", ScopeAddress.runtime(), "v",
                     writer=WriterIdentity.runtime("ra"))
        self.assertEqual(ok["status"], "OK", ok)
        cross = b.write("rstate.one", ScopeAddress.runtime(), "v",
                        writer=WriterIdentity.runtime("ra"))
        self.assertEqual(cross["status"], "STATE_AUTH_VIOLATION")


class TestFallbackStale(unittest.TestCase):
    def test_06_fallback_not_live_stale_keeps_value(self):
        store, _ = make_store()
        host = WriterIdentity.host("app-main")
        snap0 = store.snapshot()["states"]["state.primary@runtime"]
        self.assertEqual(snap0["quality"], "unknown")
        self.assertFalse(snap0["has_value"])
        store.write("state.primary", ScopeAddress.runtime(), "variant_1", writer=host)
        stale = store.mark_stale("state.primary", ScopeAddress.runtime())
        self.assertEqual(stale["status"], "OK", stale)
        self.assertEqual(stale["quality"], "stale")
        current = store.read("state.primary", ScopeAddress.runtime())
        self.assertEqual(current["value"], "variant_1")  # Wert unveraendert
        self.assertEqual(current["revision"], 1)
        # Stale ohne bekannten Wert ist ein strukturierter Fehler.
        raw = with_extra_states(component_state())
        store2, _ = make_store(raw=raw)
        no_val = store2.mark_stale("cstate.one", ScopeAddress.component("action.primary"))
        self.assertEqual(no_val["status"], "STATE_NO_VALUE")
        # Erneuter Write nach stale -> wieder fresh, Revision steigt.
        back = store.write("state.primary", ScopeAddress.runtime(), "variant_0", writer=host)
        self.assertEqual((back["status"], back["quality"], back["revision"]),
                         ("OK", "fresh", 2))


class TestRevisionEpoch(unittest.TestCase):
    def test_07_revision_epoch_and_simulated_restart(self):
        store, _ = make_store(runtime_instance_id="exec.epoch", epoch="ep.1")
        host = WriterIdentity.host("app-main")
        addr = ScopeAddress.runtime()
        for expect in (1, 2, 3):
            res = store.write("state.primary", addr, "variant_1", writer=host)
            self.assertEqual(res["revision"], expect)
            self.assertEqual(res["epoch"], "ep.1")
        pos_before = {"epoch": "ep.1", "epoch_seq": 0, "revision": 3}
        # Abgewiesenes Update veraendert weder Revision noch Epoche.
        rej = store.write("state.primary", addr, 123, writer=host)
        self.assertNotEqual(rej["status"], "OK")
        snap = store.snapshot()["states"]["state.primary@runtime"]
        self.assertEqual((snap["revision"], snap["epoch"], snap["epoch_seq"]), (3, "ep.1", 0))
        # Explizit simulierter Writer-Neustart: neue Epoche, Revision ab 0,
        # Wert/Qualitaet erhalten.
        rot = store.rotate_epoch("ep.2")
        self.assertEqual((rot["epoch"], rot["epoch_seq"]), ("ep.2", 1))
        after = store.read("state.primary", addr)
        self.assertEqual((after["value"], after["quality"], after["revision"],
                          after["epoch"], after["epoch_seq"]),
                         ("variant_1", "fresh", 0, "ep.2", 1))
        pos_after = {"epoch": "ep.2", "epoch_seq": 1, "revision": 0}
        self.assertEqual(compare_positions(pos_after, pos_before), "incomparable")
        self.assertEqual(compare_positions(pos_before, pos_before), "equal")
        pos_same_newer = {"epoch": "ep.2", "epoch_seq": 1, "revision": 0}
        pos_same_older = {"epoch": "ep.2", "epoch_seq": 1, "revision": 0}
        self.assertEqual(compare_positions(pos_same_newer, pos_same_older), "equal")
        w = store.write("state.primary", addr, "variant_0", writer=host)
        self.assertEqual((w["revision"], w["epoch"]), (1, "ep.2"))
        pos_w = {"epoch": "ep.2", "epoch_seq": 1, "revision": 1}
        self.assertEqual(compare_positions(pos_w, pos_after), "newer")
        self.assertEqual(compare_positions(pos_after, pos_w), "older")
        # Revisionen duerfen nicht numerisch ueber Epochen verglichen werden:
        # revision 1 (ep.2) ist nicht "aelter" als revision 3 (ep.1).
        self.assertEqual(compare_positions(pos_w, pos_before), "incomparable")


class TestScopeCanonicality(unittest.TestCase):
    """Regression R003-01: exklusive, gueltige Adressfelder je Scope-Kategorie."""

    def test_10_non_canonical_runtime_scope_rejected(self):
        store, _ = make_store()
        host = WriterIdentity.host("app-main")
        before = store.snapshot()
        bad_addresses = [
            ScopeAddress(kind="runtime", component_id="ghost"),
            ScopeAddress(kind="runtime", placement_id="ghost"),
            ScopeAddress(kind="runtime", component_id="ghost",
                         placement_id="placement.main"),
            ScopeAddress(kind="runtime", component_id="action.primary"),
        ]
        for addr in bad_addresses:
            with self.subTest(addr=addr):
                read = store.read("state.primary", addr)
                self.assertEqual(read["status"], STATE_SCOPE_UNKNOWN, read)
                self.assertTrue(read["issues"], read)
                write = store.write("state.primary", addr, "variant_1",
                                    writer=host)
                self.assertEqual(write["status"], STATE_SCOPE_UNKNOWN, write)
                self.assertTrue(write["issues"], write)
        # Keine Normalisierung, keine stille Wirkung auf den kanonischen Slot.
        self.assertEqual(store.snapshot(), before)
        canonical = store.read("state.primary", ScopeAddress.runtime())
        self.assertFalse(canonical["has_value"])
        self.assertEqual(canonical["revision"], 0)
        self.assertEqual(canonical["quality"], "unknown")

    def test_11_non_canonical_component_and_placement_rejected(self):
        raw = with_extra_states(component_state(), placement_state())
        store, issues = make_store(raw=raw)
        self.assertIsNotNone(store, [i.as_dict() for i in issues])
        before = store.snapshot()
        cases = [
            ("cstate.one", ScopeAddress(kind="component",
                                        component_id="action.primary",
                                        placement_id="placement.main"),
             WriterIdentity.component("action.primary")),
            ("cstate.one", ScopeAddress(kind="component",
                                        component_id="action.primary",
                                        placement_id="ghost"),
             WriterIdentity.component("action.primary")),
            ("cstate.one", ScopeAddress(kind="component", component_id=None),
             WriterIdentity.component("action.primary")),
            ("cstate.one", ScopeAddress(kind="component", component_id=""),
             WriterIdentity.component("action.primary")),
            ("pstate.one", ScopeAddress(kind="placement",
                                        placement_id="placement.main",
                                        component_id="action.primary"),
             WriterIdentity.host("app-main")),
            ("pstate.one", ScopeAddress(kind="placement",
                                        placement_id="placement.main",
                                        component_id="ghost"),
             WriterIdentity.host("app-main")),
            ("pstate.one", ScopeAddress(kind="placement", placement_id=None),
             WriterIdentity.host("app-main")),
            ("pstate.one", ScopeAddress(kind="placement", placement_id=""),
             WriterIdentity.host("app-main")),
        ]
        for state_id, addr, writer in cases:
            with self.subTest(state=state_id, addr=addr):
                read = store.read(state_id, addr)
                self.assertEqual(read["status"], STATE_SCOPE_UNKNOWN, read)
                write = store.write(state_id, addr, "x", writer=writer)
                self.assertEqual(write["status"], STATE_SCOPE_UNKNOWN, write)
        self.assertEqual(store.snapshot(), before)
        for addr in (ScopeAddress.component("action.primary"),
                     ScopeAddress.component("handler.primary"),
                     ScopeAddress.placement("placement.main"),
                     ScopeAddress.placement("placement.secondary")):
            with self.subTest(valid=addr):
                self.assertFalse(store.read(
                    "cstate.one" if addr.kind == "component" else "pstate.one",
                    addr)["has_value"])

    def test_12_canonicality_not_overridden_by_kind_mismatch(self):
        # Widerspruechliche Felder werden auch dann abgewiesen, wenn die
        # Adressart nicht zur State-Definition passt: keine Normalisierung
        # zuerst, keine Existenzpruefung, kein Schreiben.
        store, _ = make_store()
        addr = ScopeAddress(kind="component", component_id="action.primary",
                            placement_id="placement.main")
        res = store.write("state.primary", addr, "variant_1",
                          writer=WriterIdentity.host("app-main"))
        self.assertEqual(res["status"], STATE_SCOPE_UNKNOWN, res)
        self.assertEqual(store.read("state.primary",
                                    ScopeAddress.runtime())["revision"], 0)


class TestEpochRotation(unittest.TestCase):
    """Regression R003-02: kein Revisions-Reset unter wiederverwendetem Token."""

    def test_13_same_epoch_rejected_store_unchanged(self):
        store, _ = make_store(runtime_instance_id="exec.epoch", epoch="ep.1")
        host = WriterIdentity.host("app-main")
        addr = ScopeAddress.runtime()
        store.write("state.primary", addr, "variant_1", writer=host)
        store.write("state.primary", addr, "variant_0", writer=host)
        before = store.snapshot()
        res = store.rotate_epoch(store.epoch)
        self.assertEqual(res["status"], STATE_EPOCH_REUSE, res)
        self.assertTrue(res["issues"], res)
        self.assertEqual(res["epoch"], "ep.1")
        self.assertEqual(res["epoch_seq"], 0)
        self.assertEqual(store.snapshot(), before)
        current = store.read("state.primary", addr)
        self.assertEqual((current["value"], current["revision"], current["epoch"],
                          current["epoch_seq"]), ("variant_0", 2, "ep.1", 0))
        # Store bleibt voll funktionsfaehig; naechster Write zaehlt weiter.
        nxt = store.write("state.primary", addr, "variant_1", writer=host)
        self.assertEqual((nxt["status"], nxt["revision"], nxt["epoch"]),
                         ("OK", 3, "ep.1"))

    def test_14_previously_used_epoch_rejected(self):
        store, _ = make_store(epoch="ep.1")
        host = WriterIdentity.host("app-main")
        addr = ScopeAddress.runtime()
        store.write("state.primary", addr, "variant_1", writer=host)
        rot = store.rotate_epoch("ep.2")
        self.assertEqual((rot["status"], rot["epoch"], rot["epoch_seq"]),
                         ("OK", "ep.2", 1))
        store.write("state.primary", addr, "variant_0", writer=host)
        before = store.snapshot()
        for reused in ("ep.2", "ep.1"):
            with self.subTest(reused=reused):
                res = store.rotate_epoch(reused)
                self.assertEqual(res["status"], STATE_EPOCH_REUSE, res)
                self.assertEqual(store.snapshot(), before)
        current = store.read("state.primary", addr)
        self.assertEqual((current["revision"], current["epoch"], current["epoch_seq"]),
                         (1, "ep.2", 1))

    def test_15_distinct_tokens_rotate_and_generated_token_is_new(self):
        store, _ = make_store(epoch="ep.1")
        host = WriterIdentity.host("app-main")
        addr = ScopeAddress.runtime()
        store.write("state.primary", addr, "variant_1", writer=host)
        rot = store.rotate_epoch("ep.2")
        self.assertEqual((rot["status"], rot["epoch"], rot["epoch_seq"]),
                         ("OK", "ep.2", 1))
        self.assertEqual(store.read("state.primary", addr)["revision"], 0)
        self.assertEqual(store.read("state.primary", addr)["value"], "variant_1")
        seen = {"ep.1", "ep.2"}
        for expected_seq in (2, 3):
            res = store.rotate_epoch(None)
            self.assertEqual(res["status"], "OK", res)
            self.assertEqual(res["epoch_seq"], expected_seq)
            self.assertNotIn(res["epoch"], seen)
            seen.add(res["epoch"])
        empty = store.rotate_epoch("")
        self.assertEqual(empty["status"], "OK", empty)
        self.assertNotIn(empty["epoch"], seen)
        # Explizit gleicher Token danach wieder abgewiesen.
        self.assertEqual(store.rotate_epoch(store.epoch)["status"],
                         STATE_EPOCH_REUSE)


class TestSnapshot(unittest.TestCase):
    def test_08_snapshot_complete_isolated_deterministic(self):
        raw = base_raw()
        before_json = json.dumps(raw, sort_keys=True)
        store, _ = make_store(raw=raw)
        host = WriterIdentity.host("app-main")
        store.write("state.primary", ScopeAddress.runtime(), "variant_1", writer=host)
        s1 = store.snapshot()
        s2 = store.snapshot()
        self.assertEqual(s1, s2)
        self.assertEqual(json.dumps(s1, sort_keys=True), json.dumps(s2, sort_keys=True))
        self.assertEqual(s1["runtime_instance_id"], store.runtime_instance_id)
        self.assertIn("state.primary@runtime", s1["states"])
        self.assertEqual(s1["state_count"], len(s1["states"]))
        entry = s1["states"]["state.primary@runtime"]
        for key in ("state_id", "scope", "value", "has_value", "quality",
                    "revision", "epoch", "epoch_seq", "fallback", "has_fallback"):
            self.assertIn(key, entry)
        # Mutation des Snapshots wirkt nicht auf den Store zurueck.
        s1["states"]["state.primary@runtime"]["value"] = "MUTATED"
        s1["states"]["state.primary@runtime"]["quality"] = "MUTATED"
        s1["new_key"] = "MUTATED"
        current = store.read("state.primary", ScopeAddress.runtime())
        self.assertEqual((current["value"], current["quality"]), ("variant_1", "fresh"))
        s3 = store.snapshot()
        self.assertNotIn("new_key", s3)
        self.assertEqual(s3["states"]["state.primary@runtime"]["value"], "variant_1")
        # Statisches Projekt unveraendert.
        self.assertEqual(json.dumps(raw, sort_keys=True), before_json)


class TestIntegration(unittest.TestCase):
    def test_09_explicit_write_via_handler_no_implicit_write(self):
        from runtime.dispatcher import InMemoryRuntime
        from runtime.plan import compile_plan

        raw = base_raw()
        reg = fresh_registry()
        plan, plan_issues = compile_plan(copy.deepcopy(raw), reg)
        self.assertIsNotNone(plan, [i.as_dict() for i in plan_issues])
        store, store_issues = StateStore.create(copy.deepcopy(raw), reg)
        self.assertIsNotNone(store, [i.as_dict() for i in store_issues])
        host = WriterIdentity.host("app-main")
        addr = ScopeAddress.runtime()
        rt = InMemoryRuntime(plan)

        def writing_handler(payload, ctx):
            res = store.write("state.primary", addr, "variant_1", writer=host)
            return {"result": {"stored": res["status"] == "OK"}}

        rt.register_handler("handler.primary", "invoke", writing_handler)
        report = rt.dispatch_command("action.primary", "activated", {})
        self.assertEqual(report["deliveries"][0]["status"], "OK")
        self.assertEqual(report["deliveries"][0]["result"], {"stored": True})
        self.assertEqual(store.read("state.primary", addr)["value"], "variant_1")

        # Handler ohne expliziten Write aendert nichts (kein implizites Setzen).
        store2, _ = StateStore.create(copy.deepcopy(raw), reg)
        rt2 = InMemoryRuntime(plan)
        rt2.register_handler("handler.primary", "invoke",
                             lambda p, c: {"result": {"ok": True}})
        report2 = rt2.dispatch_command("action.primary", "activated", {})
        self.assertEqual(report2["deliveries"][0]["status"], "OK")
        untouched = store2.read("state.primary", addr)
        self.assertFalse(untouched["has_value"])
        self.assertEqual(untouched["quality"], "unknown")


class TestCreationGates(unittest.TestCase):
    def test_invalid_project_and_registry_block_creation(self):
        reg = fresh_registry()
        bad = base_raw()
        bad["bindings"][0]["target"] = {
            "owner_kind": "component", "owner_id": "handler.primary", "port": "missing.port"}
        store, issues = StateStore.create(bad, reg)
        self.assertIsNone(store)
        self.assertTrue(any(i.severity == "ERROR" for i in issues))
        store2, issues2 = StateStore.create("not-a-dict", reg)
        self.assertIsNone(store2)
        reg2 = fresh_registry()
        reg2.add_manifest({"type_id": "probe.bad", "version": "1.0.0", "ports": [
            {"id": "p", "direction": "sideways", "kind": "event",
             "payload_schema": {"type": "object"}}]}, origin="bad.json")
        store3, issues3 = StateStore.create(base_raw(), reg2)
        self.assertIsNone(store3)
        self.assertTrue(any(i.severity == "ERROR" for i in issues3))


if __name__ == "__main__":
    unittest.main()
