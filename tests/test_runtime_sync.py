"""AP-CORE-004 snapshot/delta/reconnect spike tests (stdlib only, deterministic).

Covers the eleven mandatory areas of the run: initial snapshot; accepted delta;
lost delta / gap with safe resync; duplicate/late/reordered messages; disconnect
stale and reconnect with a new session; authority-epoch switch with revision
reset; two isolated runtime instances plus wrong origin/generation; malformed
frames and fake writer handles; defensive copies; explicit dispatcher
integration without implicit state or automatic retry; and the manual
snapshot/delta race. No network, threads, timers or persistence.
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
from runtime.dispatcher import InMemoryRuntime  # noqa: E402
from runtime.fake_transport import (  # noqa: E402
    FakeTransport,
    FakeTransportTrust,
    SYNC_SCHEMA_VERSION,
    TRANSPORT_EMPTY,
    TRANSPORT_FRAME_INVALID,
)
from runtime.plan import compile_plan  # noqa: E402
from runtime.state_store import (  # noqa: E402
    ScopeAddress,
    StateStore,
    WriterIdentity,
)
from runtime.sync import (  # noqa: E402
    SYNC_DELTA_APPLIED,
    SYNC_DUPLICATE,
    SYNC_EPOCH_MISMATCH,
    SYNC_FRAME_INVALID,
    SYNC_GENERATION_MISMATCH,
    SYNC_NOT_READY,
    SYNC_ORIGIN_MISMATCH,
    SYNC_REVISION_GAP,
    SYNC_SESSION_MISMATCH,
    SYNC_SNAPSHOT_APPLIED,
    SYNC_STALE_IGNORED,
    SYNC_STREAM_GAP,
    SYNC_UNTRUSTED,
    SYNC_UPDATE_MISMATCH,
    SyncLink,
)

HOST = WriterIdentity.host("app-main")


def fresh_registry():
    reg, errors = load_manifests(ROOT / "component_types")
    assert not errors, [e.as_dict() for e in errors]
    return reg


def base_raw():
    return load_raw(ROOT / "examples" / "project_core_valid.json")


def component_state(state_id="cstate.sync", component="action.primary"):
    return {
        "id": state_id,
        "value_schema": {"type": "string"},
        "authority": {"role": "component", "component": component},
        "scope": "component",
        "persistence": "none",
    }


def placement_state(state_id="pstate.sync"):
    return {
        "id": state_id,
        "value_schema": {"type": "string"},
        "authority": {"role": "host"},
        "scope": "placement",
        "persistence": "none",
    }


def object_state(state_id="ostate.sync"):
    return {
        "id": state_id,
        "value_schema": {
            "type": "object",
            "properties": {"n": {"type": "integer"}},
            "required": ["n"],
            "additionalProperties": False,
        },
        "authority": {"role": "host"},
        "scope": "project",
        "persistence": "none",
    }


def raw_with(*states):
    raw = base_raw()
    raw["states"] = list(raw.get("states", [])) + [copy.deepcopy(s) for s in states]
    return raw


def make_store(raw=None, *, runtime_instance_id="exec.sync.one",
               epoch="ep.sync.one"):
    raw = base_raw() if raw is None else raw
    store, issues = StateStore.create(
        copy.deepcopy(raw), fresh_registry(),
        runtime_instance_id=runtime_instance_id, epoch=epoch,
    )
    assert store is not None, [i.as_dict() for i in issues]
    return store


def connect(link, session_id="session.one"):
    report = link.connect(session_id)
    assert report["handshake"]["status"] == "TRANSPORT_ENQUEUED", report
    delivered = link.deliver_all()
    return report, delivered


def write(store, state_id, scope, value, writer=HOST):
    result = store.write(state_id, scope, value, writer=writer)
    assert result["status"] == "OK", result
    return result


def publish(link, state_id, scope, value, *, expect_enqueued=True):
    result = write(link.source.store, state_id, scope, value)
    report = link.source.publish_update(state_id, scope, write_result=result)
    if expect_enqueued:
        assert report["status"] == "TRANSPORT_ENQUEUED", report
    return result, report["frame"]


class TestInitialSnapshot(unittest.TestCase):
    def test_01_snapshot_ready_scopes_values_revision_epoch(self):
        raw = raw_with(component_state(), placement_state())
        store = make_store(raw)
        write(store, "state.primary", ScopeAddress.runtime(), "variant_1")
        write(store, "cstate.sync", ScopeAddress.component("action.primary"),
              "component-value", writer=WriterIdentity.component("action.primary"))
        write(store, "pstate.sync", ScopeAddress.placement("placement.main"),
              "placement-value")
        link = SyncLink(store)
        report, delivered = connect(link)

        self.assertEqual([d["status"] for d in delivered],
                         ["SYNC_HANDSHAKE_ACCEPTED", SYNC_SNAPSHOT_APPLIED])
        snap = link.mirror.snapshot()
        self.assertEqual(snap["lifecycle"], "ready")
        self.assertFalse(snap["needs_resync"])
        self.assertEqual(snap["origin"], store.runtime_instance_id)
        self.assertEqual(snap["session_id"], "session.one")
        self.assertEqual(snap["epoch"], "ep.sync.one")
        self.assertEqual(snap["epoch_seq"], 0)
        self.assertEqual(snap["state_count"], 5)  # runtime, 2 components, 2 placements

        runtime_entry = snap["states"]["state.primary@runtime"]
        self.assertEqual(runtime_entry["value"], "variant_1")
        self.assertTrue(runtime_entry["has_value"])
        self.assertEqual(runtime_entry["quality"], "fresh")
        self.assertEqual(runtime_entry["revision"], 1)
        self.assertEqual(runtime_entry["epoch"], "ep.sync.one")

        comp_entry = snap["states"]["cstate.sync@component:action.primary"]
        self.assertEqual(comp_entry["scope"],
                         {"kind": "component", "component_id": "action.primary"})
        self.assertEqual(comp_entry["value"], "component-value")
        placement_entry = snap["states"]["pstate.sync@placement:placement.main"]
        self.assertEqual(placement_entry["scope"],
                         {"kind": "placement", "placement_id": "placement.main"})
        self.assertEqual(placement_entry["value"], "placement-value")

        # Unwritten component slot stays explicitly unknown, never fallback/fresh.
        unknown = snap["states"]["cstate.sync@component:handler.primary"]
        self.assertFalse(unknown["has_value"])
        self.assertEqual(unknown["quality"], "unknown")
        self.assertEqual(unknown["revision"], 0)

        # Provisional frame metadata, explicitly marked SPIKE_ONLY.
        frames = [report["handshake"]["frame"], report["snapshot"]["frame"]]
        self.assertTrue(all(f["spike_only"] is True for f in frames))
        self.assertTrue(all(f["schema_version"] == SYNC_SCHEMA_VERSION for f in frames))
        self.assertEqual([f["stream_seq"] for f in frames], [1, 2])


class TestAcceptedDelta(unittest.TestCase):
    def test_02_confirmed_write_delta_exact_mirror(self):
        store = make_store()
        write(store, "state.primary", ScopeAddress.runtime(), "variant_0")
        link = SyncLink(store)
        connect(link)
        self.assertEqual(
            link.mirror.read("state.primary", ScopeAddress.runtime())["value"],
            "variant_0")

        result, frame = publish(link, "state.primary", ScopeAddress.runtime(),
                                "variant_1")
        self.assertEqual(result["revision"], 2)
        delivery = link.deliver_next()
        self.assertEqual(delivery["status"], SYNC_DELTA_APPLIED)
        read = link.mirror.read("state.primary", ScopeAddress.runtime())
        self.assertEqual((read["value"], read["revision"], read["quality"]),
                         ("variant_1", 2, "fresh"))
        self.assertEqual(read["epoch"], "ep.sync.one")
        self.assertEqual(frame["payload"]["value"], "variant_1")
        self.assertEqual(frame["payload"]["revision"], 2)
        self.assertEqual(frame["type"], "delta")
        self.assertEqual(frame["payload"]["scope"], {"kind": "runtime"})
        # Mirror is a replica; the source store remains the only authority.
        self.assertEqual(
            store.read("state.primary", ScopeAddress.runtime())["revision"], 2)
        self.assertEqual(link.transport.pending, 0)


class TestGaps(unittest.TestCase):
    def test_03_lost_delta_gap_and_safe_resync(self):
        store = make_store()
        write(store, "state.primary", ScopeAddress.runtime(), "variant_0")
        link = SyncLink(store)
        connect(link)
        _, frame1 = publish(link, "state.primary", ScopeAddress.runtime(),
                            "variant_1")
        _, frame2 = publish(link, "state.primary", ScopeAddress.runtime(),
                            "variant_0")
        self.assertEqual(frame2["stream_seq"], frame1["stream_seq"] + 1)
        dropped = link.transport.drop_next()
        self.assertEqual(dropped["dropped"], 1)

        delivery = link.deliver_next()
        self.assertEqual(delivery["status"], SYNC_STREAM_GAP)
        self.assertTrue(link.mirror.needs_resync)
        self.assertEqual(link.mirror.lifecycle, "degraded")
        # No stale overwrite through the gap.
        current = link.mirror.read("state.primary", ScopeAddress.runtime())
        self.assertEqual((current["value"], current["revision"], current["quality"]),
                         ("variant_0", 1, "fresh"))

        resync = link.resync()
        self.assertEqual(resync["status"], "TRANSPORT_ENQUEUED")
        delivery = link.deliver_next()
        self.assertEqual(delivery["status"], SYNC_SNAPSHOT_APPLIED)
        current = link.mirror.read("state.primary", ScopeAddress.runtime())
        self.assertEqual((current["value"], current["revision"], current["quality"]),
                         ("variant_0", 3, "fresh"))
        self.assertFalse(link.mirror.needs_resync)


class TestDuplicatesLateReordered(unittest.TestCase):
    def test_04_never_applies_old_values_as_fresh(self):
        store = make_store()
        write(store, "state.primary", ScopeAddress.runtime(), "variant_0")
        link = SyncLink(store)
        connect(link)

        # Duplicate delivery: first applies, second is a duplicate.
        _, delta1 = publish(link, "state.primary", ScopeAddress.runtime(),
                            "variant_1")
        link.transport.duplicate_next()
        first = link.deliver_next()
        second = link.deliver_next()
        self.assertEqual(first["status"], SYNC_DELTA_APPLIED)
        self.assertEqual(second["status"], SYNC_DUPLICATE)
        current = link.mirror.read("state.primary", ScopeAddress.runtime())
        self.assertEqual((current["value"], current["revision"]), ("variant_1", 2))

        # Late message with a fresh stream position but an old revision.
        _, delta3 = publish(link, "state.primary", ScopeAddress.runtime(),
                            "variant_0")
        self.assertEqual(delta3["payload"]["revision"], 3)
        link.transport.drop_next()  # lose the real revision 3
        late = copy.deepcopy(delta1)
        late["message_id"] = "msg.late"
        late["stream_seq"] = delta3["stream_seq"]  # matches the expected position
        late["payload"]["revision"] = 1            # older than the known revision 2
        late["payload"]["value"] = "variant_0"
        late = link.trust.sign_frame(late)
        link.transport.inject(late)
        delivery = link.deliver_next()
        self.assertEqual(delivery["status"], SYNC_STALE_IGNORED)
        current = link.mirror.read("state.primary", ScopeAddress.runtime())
        self.assertEqual((current["value"], current["revision"]), ("variant_1", 2))

        # Reordered messages: newer first, older second; neither is applied.
        _, delta4 = publish(link, "state.primary", ScopeAddress.runtime(),
                            "variant_0")
        _, delta5 = publish(link, "state.primary", ScopeAddress.runtime(),
                            "variant_1")
        self.assertEqual(delta5["payload"]["revision"], 5)
        link.transport.swap_next_two()
        gap = link.deliver_next()
        self.assertEqual(gap["status"], SYNC_STREAM_GAP)
        late_delivery = link.deliver_next()
        self.assertEqual(late_delivery["status"], SYNC_NOT_READY)
        current = link.mirror.read("state.primary", ScopeAddress.runtime())
        self.assertEqual((current["value"], current["revision"]), ("variant_1", 2))

        link.resync()
        self.assertEqual(link.deliver_next()["status"], SYNC_SNAPSHOT_APPLIED)
        current = link.mirror.read("state.primary", ScopeAddress.runtime())
        self.assertEqual((current["value"], current["revision"]), ("variant_1", 5))

    def test_04b_revision_gap_requires_resync_without_apply(self):
        store = make_store()
        write(store, "state.primary", ScopeAddress.runtime(), "variant_0")
        link = SyncLink(store)
        connect(link)
        _, delta3 = publish(link, "state.primary", ScopeAddress.runtime(),
                            "variant_1")
        self.assertEqual(delta3["payload"]["revision"], 2)
        link.transport.drop_next()
        skipped = copy.deepcopy(delta3)
        skipped["message_id"] = "msg.revision-gap"
        skipped["payload"]["revision"] = 5  # expected after known revision is 2
        skipped = link.trust.sign_frame(skipped)
        link.transport.inject(skipped)
        delivery = link.deliver_next()
        self.assertEqual(delivery["status"], SYNC_REVISION_GAP)
        self.assertTrue(link.mirror.needs_resync)
        current = link.mirror.read("state.primary", ScopeAddress.runtime())
        self.assertEqual((current["value"], current["revision"]), ("variant_0", 1))

        link.resync()
        self.assertEqual(link.deliver_next()["status"], SYNC_SNAPSHOT_APPLIED)
        current = link.mirror.read("state.primary", ScopeAddress.runtime())
        self.assertEqual((current["value"], current["revision"]), ("variant_1", 2))


class TestDisconnectReconnect(unittest.TestCase):
    def test_05_stale_keeps_value_new_session_snapshot_fresh(self):
        store = make_store(raw_with(component_state()))
        write(store, "state.primary", ScopeAddress.runtime(), "variant_1")
        link = SyncLink(store)
        connect(link, "session.one")
        first_generation = link.source.stream_generation
        unknown_before = link.mirror.read(
            "cstate.sync", ScopeAddress.component("action.primary"))
        self.assertFalse(unknown_before["has_value"])
        self.assertEqual(unknown_before["quality"], "unknown")

        disconnect = link.disconnect()
        self.assertEqual(disconnect["mirror"]["lifecycle"], "disconnected")
        self.assertEqual(link.mirror.lifecycle, "disconnected")
        stale = link.mirror.read("state.primary", ScopeAddress.runtime())
        self.assertEqual((stale["value"], stale["quality"]), ("variant_1", "stale"))
        unknown_after = link.mirror.read(
            "cstate.sync", ScopeAddress.component("action.primary"))
        self.assertFalse(unknown_after["has_value"])
        self.assertEqual(unknown_after["quality"], "unknown")

        # Source changes while disconnected; nothing is queued on a dead link.
        _, frame = publish(link, "state.primary", ScopeAddress.runtime(),
                           "variant_0", expect_enqueued=False)
        self.assertIsNone(frame)
        self.assertEqual(link.transport.pending, 0)

        reconnect = link.reconnect("session.two")
        self.assertEqual(reconnect["handshake"]["status"], "TRANSPORT_ENQUEUED")
        self.assertEqual(link.source.stream_generation, first_generation + 1)
        reports = link.deliver_all()
        self.assertEqual(reports[-1]["status"], SYNC_SNAPSHOT_APPLIED)
        current = link.mirror.read("state.primary", ScopeAddress.runtime())
        self.assertEqual((current["value"], current["revision"], current["quality"]),
                         ("variant_0", 2, "fresh"))
        self.assertEqual(link.mirror.session_id, "session.two")
        self.assertEqual(link.mirror.stream_generation, first_generation + 1)
        self.assertEqual(link.mirror.origin, store.runtime_instance_id)
        self.assertFalse(link.mirror.needs_resync)


class TestEpochSwitch(unittest.TestCase):
    def test_06_new_authority_epoch_revision_reset_needs_resync(self):
        store = make_store()
        write(store, "state.primary", ScopeAddress.runtime(), "variant_0")
        write(store, "state.primary", ScopeAddress.runtime(), "variant_1")
        write(store, "state.primary", ScopeAddress.runtime(), "variant_0")
        link = SyncLink(store)
        connect(link)
        before = link.mirror.read("state.primary", ScopeAddress.runtime())
        self.assertEqual((before["revision"], before["epoch"]), (3, "ep.sync.one"))

        rotation = store.rotate_epoch("ep.sync.two")
        self.assertEqual((rotation["status"], rotation["epoch_seq"]), ("OK", 1))
        # New epoch resets the numeric revision to 1 on the next write; a pure
        # numeric comparison would wrongly treat it as older than revision 3.
        publish(link, "state.primary", ScopeAddress.runtime(), "variant_1")
        delivery = link.deliver_next()
        self.assertEqual(delivery["status"], SYNC_EPOCH_MISMATCH)
        self.assertTrue(link.mirror.needs_resync)
        unchanged = link.mirror.read("state.primary", ScopeAddress.runtime())
        self.assertEqual((unchanged["value"], unchanged["revision"],
                          unchanged["epoch"]), ("variant_0", 3, "ep.sync.one"))

        link.resync()
        self.assertEqual(link.deliver_next()["status"], SYNC_SNAPSHOT_APPLIED)
        after = link.mirror.read("state.primary", ScopeAddress.runtime())
        self.assertEqual((after["value"], after["revision"], after["epoch"],
                          after["epoch_seq"]), ("variant_1", 1, "ep.sync.two", 1))
        self.assertFalse(link.mirror.needs_resync)


class TestIsolationAndOrigin(unittest.TestCase):
    def test_07_two_runtimes_never_mix_wrong_origin_generation(self):
        raw = base_raw()
        shared_trust = FakeTransportTrust.create(writer_id="fake.writer.shared")
        store1 = make_store(raw, runtime_instance_id="exec.one",
                            epoch="ep.one")
        store2 = make_store(raw, runtime_instance_id="exec.two",
                            epoch="ep.two")
        link1 = SyncLink(store1, trust=shared_trust)
        link2 = SyncLink(store2, trust=shared_trust)
        connect(link1, "session.one")
        connect(link2, "session.two")
        publish(link1, "state.primary", ScopeAddress.runtime(), "variant_1")
        publish(link2, "state.primary", ScopeAddress.runtime(), "variant_0")
        link1.deliver_all()
        link2.deliver_all()
        self.assertEqual(
            link1.mirror.read("state.primary", ScopeAddress.runtime())["value"],
            "variant_1")
        self.assertEqual(
            link2.mirror.read("state.primary", ScopeAddress.runtime())["value"],
            "variant_0")
        self.assertNotEqual(link1.mirror.origin, link2.mirror.origin)

        # A valid signed frame from the other runtime is rejected and wipes the
        # old mirror provenance instead of mixing values.
        cross = link2.source.start_session("session.cross")
        link1.transport.inject(cross["frame"])
        delivery = link1.deliver_next()
        self.assertEqual(delivery["status"], SYNC_ORIGIN_MISMATCH)
        self.assertTrue(delivery["mirror"]["invalidated"])
        self.assertEqual(link1.mirror.snapshot()["states"], {})
        self.assertIsNone(link1.mirror.origin)
        self.assertEqual(link2.mirror.snapshot()["states"]["state.primary@runtime"]["value"],
                         "variant_0")

        # Reinitialize the mirror from its own runtime by handshake + snapshot.
        link1.mirror.connect()
        link1.source.start_session("session.one.b")
        link1.source.send_snapshot()
        reports = link1.deliver_all()
        self.assertEqual(reports[-1]["status"], SYNC_SNAPSHOT_APPLIED)
        self.assertEqual(
            link1.mirror.read("state.primary", ScopeAddress.runtime())["value"],
            "variant_1")

        # A correctly signed frame with a stale generation is rejected without
        # applying the value; its stream position is the same one the valid
        # frame would have used (the valid frame is dropped on purpose).
        _, valid = publish(link1, "state.primary", ScopeAddress.runtime(),
                           "variant_0")
        link1.transport.drop_next()
        stale_generation = copy.deepcopy(valid)
        stale_generation["message_id"] = "msg.gen"
        stale_generation["stream_generation"] = valid["stream_generation"] - 1
        stale_generation = shared_trust.sign_frame(stale_generation)
        link1.transport.inject(stale_generation)
        delivery = link1.deliver_next()
        self.assertEqual(delivery["status"], SYNC_GENERATION_MISMATCH)
        self.assertEqual(
            link1.mirror.read("state.primary", ScopeAddress.runtime())["value"],
            "variant_1")

        # A correctly signed frame with a wrong session string is rejected too.
        _, valid2 = publish(link1, "state.primary", ScopeAddress.runtime(),
                            "variant_0")
        link1.transport.drop_next()
        wrong_session = copy.deepcopy(valid2)
        wrong_session["message_id"] = "msg.sess"
        wrong_session["session_id"] = "session.spoofed"
        wrong_session = shared_trust.sign_frame(wrong_session)
        link1.transport.inject(wrong_session)
        delivery = link1.deliver_next()
        self.assertEqual(delivery["status"], SYNC_SESSION_MISMATCH)
        self.assertEqual(
            link1.mirror.read("state.primary", ScopeAddress.runtime())["value"],
            "variant_1")


class TestMalformedFrames(unittest.TestCase):
    def test_08_structured_errors_without_mirror_mutation(self):
        store = make_store()
        write(store, "state.primary", ScopeAddress.runtime(), "variant_0")
        link = SyncLink(store)
        connect(link)
        baseline = link.mirror.snapshot()
        trust = link.trust

        def signed(frame):
            return trust.sign_frame(frame)

        valid_header = {
            "schema_version": SYNC_SCHEMA_VERSION,
            "spike_only": True,
            "type": "handshake",
            "message_id": "msg.case",
            "stream_seq": link.transport.next_stream_seq(),
            "runtime_instance_id": store.runtime_instance_id,
            "session_id": "session.one",
            "stream_generation": link.source.stream_generation,
            "epoch": store.epoch,
            "epoch_seq": store.epoch_seq,
            "payload": {"source": "fake.inmemory"},
        }
        cases = [
            ("not-a-frame", SYNC_FRAME_INVALID),
            (signed({}), SYNC_FRAME_INVALID),
            (signed({**valid_header, "schema_version": "wire-1.0"}),
             SYNC_FRAME_INVALID),
            (signed({**valid_header, "type": "command"}), SYNC_FRAME_INVALID),
            (signed({**valid_header, "stream_seq": 0}), SYNC_FRAME_INVALID),
        ]
        for frame, expected in cases:
            with self.subTest(expected=expected, frame=str(frame)[:60]):
                link.transport.inject(frame)
                delivery = link.deliver_next()
                self.assertEqual(delivery["status"], expected, delivery)
                self.assertEqual(link.mirror.snapshot(), baseline)

        # Valid delta header, three malformed payloads (signed correctly).
        _, base_delta = publish(link, "state.primary", ScopeAddress.runtime(),
                                "variant_1")
        link.transport.drop_next()  # keep mirror ready at the baseline

        def delta_with(mutator):
            frame = copy.deepcopy(base_delta)
            frame["message_id"] = "msg.malformed"
            frame["stream_seq"] = link.transport.next_stream_seq()
            mutator(frame)
            return trust.sign_frame(frame)

        malformed = [
            delta_with(lambda f: f["payload"].update({"state_id": "Bad Id!"})),
            delta_with(lambda f: f["payload"].update({
                "scope": {"kind": "runtime", "component_id": "action.primary"}})),
            delta_with(lambda f: f["payload"].update({"revision": "1"})),
            delta_with(lambda f: f["payload"].update({"has_value": False})),
            delta_with(lambda f: f["payload"].update({"quality": "stale"})),
        ]
        for frame in malformed:
            with self.subTest(state_id=frame["payload"].get("state_id")):
                link.transport.inject(frame)
                delivery = link.deliver_next()
                self.assertEqual(delivery["status"], SYNC_FRAME_INVALID, delivery)
                self.assertEqual(link.mirror.snapshot(), baseline)

        # Fake writer handle / wrong trust token: never authorizes a frame.
        attacker = FakeTransportTrust.create(
            writer_id=trust.writer_id, token="attacker-token")
        forged = attacker.sign_frame({**valid_header,
                                      "stream_seq": link.transport.next_stream_seq()})
        link.transport.inject(forged)
        self.assertEqual(link.deliver_next()["status"], SYNC_UNTRUSTED)

        # Spoofed session/host/writer fields without a fake transport tag.
        spoof = copy.deepcopy({**valid_header,
                               "stream_seq": link.transport.next_stream_seq()})
        spoof.pop("transport_auth", None)
        spoof["session_id"] = "session.trusted"
        spoof["host_id"] = "host.trusted"
        spoof["writer_handle"] = "writer.trusted"
        link.transport.inject(spoof)
        self.assertEqual(link.deliver_next()["status"], SYNC_UNTRUSTED)
        self.assertEqual(link.mirror.snapshot(), baseline)


class TestDefensiveCopies(unittest.TestCase):
    def test_09_source_frame_and_mirror_reads_are_isolated(self):
        raw = raw_with(object_state())
        store = make_store(raw)
        value = {"n": 1}
        link = SyncLink(store)
        connect(link)

        result, frame = publish(link, "ostate.sync", ScopeAddress.runtime(), value)
        self.assertEqual(result["status"], "OK")
        value["n"] = 99                     # caller alias after write
        frame["payload"]["value"]["n"] = 77  # returned frame alias after enqueue
        delivery = link.deliver_next()
        self.assertEqual(delivery["status"], SYNC_DELTA_APPLIED)
        self.assertEqual(
            link.source.store.read("ostate.sync", ScopeAddress.runtime())["value"],
            {"n": 1})
        self.assertEqual(
            link.mirror.read("ostate.sync", ScopeAddress.runtime())["value"],
            {"n": 1})

        # Mutating a source snapshot must not change the store.
        snap = link.source.store.snapshot()
        snap["states"]["ostate.sync@runtime"]["value"]["n"] = 42
        self.assertEqual(
            link.source.store.read("ostate.sync", ScopeAddress.runtime())["value"],
            {"n": 1})

        # Mutating mirror reads/snapshots must not change the mirror.
        read = link.mirror.read("ostate.sync", ScopeAddress.runtime())
        read["value"]["n"] = 55
        view = link.mirror.snapshot()
        view["states"]["ostate.sync@runtime"]["value"]["n"] = 66
        view["states"]["ostate.sync@runtime"]["quality"] = "stale"
        self.assertEqual(
            link.mirror.read("ostate.sync", ScopeAddress.runtime())["value"],
            {"n": 1})
        self.assertEqual(
            link.mirror.snapshot()["states"]["ostate.sync@runtime"]["quality"],
            "fresh")

        # Mutating a staged transport frame before delivery stays isolated.
        publish(link, "ostate.sync", ScopeAddress.runtime(), {"n": 2})
        peeked = link.transport.peek_next()
        peeked["frame"]["payload"]["value"]["n"] = 123
        link.deliver_next()
        self.assertEqual(
            link.mirror.read("ostate.sync", ScopeAddress.runtime())["value"],
            {"n": 2})


class TestCommandIntegration(unittest.TestCase):
    def test_10_command_result_state_separate_no_auto_retry(self):
        raw = base_raw()
        registry = fresh_registry()
        plan, issues = compile_plan(copy.deepcopy(raw), registry)
        self.assertIsNotNone(plan, [i.as_dict() for i in issues])
        store = make_store(raw)
        link = SyncLink(store)
        connect(link)
        runtime = InMemoryRuntime(plan)
        writes: list[dict] = []

        def writing_handler(payload, ctx):
            result = store.write("state.primary", ScopeAddress.runtime(),
                                 "variant_1", writer=HOST)
            writes.append(result)
            return {"result": {"ok": result["status"] == "OK"}}

        runtime.register_handler("handler.primary", "invoke", writing_handler)
        report = runtime.dispatch_command("action.primary", "activated", {})
        self.assertEqual(report["deliveries"][0]["status"], "OK")
        self.assertEqual(report["deliveries"][0]["result"], {"ok": True})
        # Command result alone changes nothing in the mirror and emits nothing.
        self.assertEqual(link.transport.pending, 0)
        self.assertFalse(
            link.mirror.read("state.primary", ScopeAddress.runtime())["has_value"])
        # A command result is not a confirmation and can never be published.
        rejected = link.source.publish_update(
            "state.primary", ScopeAddress.runtime(),
            write_result={"status": "DISPATCHED", "result": {"ok": True}})
        self.assertEqual(rejected["status"], "SYNC_UPDATE_NOT_CONFIRMED")
        self.assertEqual(link.transport.pending, 0)
        # Only the explicit confirmation may become a delta.
        publish_report = link.source.publish_update(
            "state.primary", ScopeAddress.runtime(), write_result=writes[0])
        self.assertEqual(publish_report["status"], "TRANSPORT_ENQUEUED")
        self.assertEqual(link.deliver_next()["status"], SYNC_DELTA_APPLIED)
        self.assertEqual(
            link.mirror.read("state.primary", ScopeAddress.runtime())["value"],
            "variant_1")

        # Handler returning a result without writing changes no state and
        # enqueues nothing.
        runtime.register_handler("handler.primary", "invoke",
                                 lambda payload, ctx: {"result": {"ok": True}})
        report2 = runtime.dispatch_command("action.primary", "activated", {})
        self.assertEqual(report2["deliveries"][0]["status"], "OK")
        self.assertEqual(link.transport.pending, 0)
        self.assertEqual(
            link.mirror.read("state.primary", ScopeAddress.runtime())["revision"],
            1)

        # A failing, non-idempotent command is delivered exactly once: no
        # automatic retry and no state mutation.
        calls: list[int] = []

        def failing_handler(payload, ctx):
            calls.append(1)
            raise RuntimeError("non-idempotent failure")

        before = store.snapshot()
        runtime.register_handler("handler.primary", "invoke", failing_handler)
        failed = runtime.dispatch_command("action.primary", "activated", {})
        self.assertEqual(failed["deliveries"][0]["status"], "RUNTIME_HANDLER_ERROR")
        self.assertEqual(len(calls), 1)
        self.assertEqual(store.snapshot(), before)
        self.assertEqual(link.transport.pending, 0)


class TestSnapshotDeltaRace(unittest.TestCase):
    def test_11_manual_drop_at_snapshot_delta_transition(self):
        store = make_store()
        write(store, "state.primary", ScopeAddress.runtime(), "variant_0")
        link = SyncLink(store)
        link.connect("session.race")
        # Drop the initial snapshot while it is still in flight.
        handshake = link.deliver_next()
        self.assertEqual(handshake["status"], "SYNC_HANDSHAKE_ACCEPTED")
        publish(link, "state.primary", ScopeAddress.runtime(), "variant_1")
        self.assertEqual(link.transport.pending, 2)  # snapshot + delta
        dropped = link.transport.drop_next()
        self.assertEqual(dropped["dropped"], 1)
        delta_delivery = link.deliver_next()
        self.assertEqual(delta_delivery["status"], SYNC_NOT_READY)
        self.assertFalse(
            link.mirror.read("state.primary", ScopeAddress.runtime())["has_value"])
        # A manual snapshot (taken after the delta) recovers the latest value
        # without replaying the lost delta.
        link.resync()
        self.assertEqual(link.deliver_next()["status"], SYNC_SNAPSHOT_APPLIED)
        recovered = link.mirror.read("state.primary", ScopeAddress.runtime())
        self.assertEqual((recovered["value"], recovered["revision"]), ("variant_1", 2))

        # Drop a delta immediately after the snapshot: the next delta proves
        # the gap instead of silently overwriting.
        publish(link, "state.primary", ScopeAddress.runtime(), "variant_0")
        link.transport.drop_next()
        publish(link, "state.primary", ScopeAddress.runtime(), "variant_1")
        gap = link.deliver_next()
        self.assertEqual(gap["status"], SYNC_STREAM_GAP)
        self.assertTrue(link.mirror.needs_resync)
        self.assertEqual(
            link.mirror.read("state.primary", ScopeAddress.runtime())["revision"],
            2)
        link.resync()
        self.assertEqual(link.deliver_next()["status"], SYNC_SNAPSHOT_APPLIED)
        final = link.mirror.read("state.primary", ScopeAddress.runtime())
        self.assertEqual((final["value"], final["revision"]), ("variant_1", 4))


class TestReviewR004Regressions(unittest.TestCase):
    """Regression tests for the three independently reproduced RUN-01 findings."""

    def test_R004_01_snapshot_preserves_authoritative_quality_across_reconnect(self):
        raw = raw_with(component_state())
        store = make_store(raw)
        write(store, "state.primary", ScopeAddress.runtime(), "variant_1")
        write(store, "cstate.sync",
              ScopeAddress.component("action.primary"), "component-value",
              writer=WriterIdentity.component("action.primary"))
        self.assertEqual(
            store.mark_stale("state.primary", ScopeAddress.runtime())["status"],
            "OK")

        link = SyncLink(store)
        connect(link, "session.one")
        primary = link.mirror.read("state.primary", ScopeAddress.runtime())
        self.assertEqual((primary["value"], primary["quality"]),
                         ("variant_1", "stale"))
        fresh = link.mirror.read("cstate.sync",
                                 ScopeAddress.component("action.primary"))
        self.assertEqual((fresh["value"], fresh["quality"]),
                         ("component-value", "fresh"))
        unknown = link.mirror.read("cstate.sync",
                                   ScopeAddress.component("handler.primary"))
        self.assertEqual((unknown["has_value"], unknown["quality"]),
                         (False, "unknown"))

        # A reconnect snapshot is not a confirmation of freshness. The source
        # store still marks the value stale, so the mirror must keep it stale.
        link.disconnect()
        link.reconnect("session.two")
        reports = link.deliver_all()
        self.assertEqual(reports[-1]["status"], SYNC_SNAPSHOT_APPLIED)
        after = link.mirror.read("state.primary", ScopeAddress.runtime())
        self.assertEqual((after["value"], after["revision"], after["quality"]),
                         ("variant_1", 1, "stale"))

    def test_R004_01_inconsistent_snapshot_quality_fails_closed(self):
        store = make_store()
        write(store, "state.primary", ScopeAddress.runtime(), "variant_1")
        link = SyncLink(store)
        link.connect("session.bad")
        self.assertEqual(link.deliver_next()["status"], "SYNC_HANDSHAKE_ACCEPTED")
        snapshot = link.transport.peek_next()["frame"]
        link.transport.drop_next()
        key = "state.primary@runtime"
        before = link.mirror.snapshot()

        cases = (
            (False, "fresh", None),
            (True, "unknown", "variant_1"),
        )
        for has_value, quality, value in cases:
            with self.subTest(has_value=has_value, quality=quality):
                malformed = copy.deepcopy(snapshot)
                entry = malformed["payload"]["states"][key]
                entry["has_value"] = has_value
                entry["quality"] = quality
                entry["value"] = value
                link.transport.inject(link.trust.sign_frame(malformed))
                result = link.deliver_next()
                self.assertEqual(result["status"], SYNC_FRAME_INVALID)
                self.assertEqual(link.mirror.snapshot(), before)
                self.assertEqual(link.transport.pending, 0)

    def test_R004_02_confirmation_is_bound_to_exact_slot(self):
        store = make_store(raw_with(object_state()))
        address = ScopeAddress.runtime()
        confirmation_of_a = write(store, "state.primary", address, "variant_1")
        write(store, "ostate.sync", address, {"n": 7})
        link = SyncLink(store)
        connect(link)
        before = link.mirror.snapshot()
        pending_before = link.transport.pending

        wrong = link.source.publish_update(
            "ostate.sync", address, write_result=confirmation_of_a)
        self.assertEqual(wrong["status"], SYNC_UPDATE_MISMATCH)
        self.assertEqual(wrong["issues"][0]["path"], "/write_result/scope_key")
        self.assertEqual(link.transport.pending, pending_before)
        self.assertEqual(link.mirror.snapshot(), before)
        self.assertEqual(store.read("ostate.sync", address)["revision"], 1)

        missing_slot = {
            "status": "OK", "revision": 2, "epoch": store.epoch,
            "epoch_seq": store.epoch_seq, "quality": "fresh",
        }
        missing = link.source.publish_update(
            "ostate.sync", address, write_result=missing_slot)
        self.assertEqual(missing["status"], SYNC_UPDATE_MISMATCH)
        self.assertEqual(missing["issues"][0]["path"], "/write_result/scope_key")
        self.assertEqual(link.transport.pending, pending_before)

        # Positive control: the confirmation for the requested slot is emitted
        # and applied exactly.
        confirmed_b = write(store, "ostate.sync", address, {"n": 8})
        sent = link.source.publish_update(
            "ostate.sync", address, write_result=confirmed_b)
        self.assertEqual(sent["status"], "TRANSPORT_ENQUEUED")
        delivery = link.deliver_next()
        self.assertEqual(delivery["status"], SYNC_DELTA_APPLIED)
        current = link.mirror.read("ostate.sync", address)
        self.assertEqual((current["value"], current["revision"],
                          current["quality"]), ({"n": 8}, 2, "fresh"))

    def test_R004_03_noncopyable_injection_is_rejected_without_mutation(self):
        transport = FakeTransport(FakeTransportTrust.create())
        self.assertEqual(
            transport.send({"probe": "queued"})["status"], "TRANSPORT_ENQUEUED")
        before = transport.peek_next()["frame"]

        report = transport.inject(memoryview(b"invalid frame"))
        self.assertEqual(report["status"], TRANSPORT_FRAME_INVALID)
        self.assertIsNone(report["frame"])
        self.assertEqual(transport.pending, 1)
        self.assertEqual(transport.peek_next()["frame"], before)

        nested = transport.inject({"payload": memoryview(b"nested")})
        self.assertEqual(nested["status"], TRANSPORT_FRAME_INVALID)
        self.assertEqual(transport.pending, 1)
        self.assertEqual(transport.peek_next()["frame"], before)

        delivered = transport.deliver_next()
        self.assertEqual(delivered["status"], "TRANSPORT_DELIVERED")
        self.assertEqual(delivered["frame"], before)
        self.assertEqual(transport.pending, 0)
        self.assertEqual(transport.peek_next()["status"], TRANSPORT_EMPTY)
        self.assertEqual(
            transport.inject(memoryview(b"still invalid"))["status"],
            TRANSPORT_FRAME_INVALID)
        self.assertEqual(transport.pending, 0)


if __name__ == "__main__":
    unittest.main()
