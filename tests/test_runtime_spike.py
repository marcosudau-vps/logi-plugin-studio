"""AP-CORE-002 In-Memory spike tests (stdlib only, deterministic).

Covers: fan-out over identical port types; command/event separation; valid vs.
mismatched payloads; unknown endpoints; invalid and SCHEMA_NOT_PROVEN-only
projects; missing/faulty handlers; deterministic repeat; no runtime states in
the project; no automatic success events; explicit handler-emitted events;
result-schema validation; SPIKE_ONLY lexical ordering; correlation-id
pass-through.
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
from core.registry import TypeRegistry, load_manifests  # noqa: E402
from core.validate import is_valid  # noqa: E402
from runtime.dispatcher import InMemoryRuntime  # noqa: E402
from runtime.plan import compile_plan  # noqa: E402


def fresh_registry() -> TypeRegistry:
    reg, errors = load_manifests(ROOT / "component_types")
    assert not errors, [e.as_dict() for e in errors]
    return reg


def base_project() -> dict:
    return load_raw(ROOT / "examples" / "project_core_valid.json")


def compile_base(registry=None, **kw):
    registry = registry or fresh_registry()
    raw = base_project()
    plan, issues = compile_plan(raw, registry, **kw)
    return raw, plan, issues


def probe_registry() -> TypeRegistry:
    reg = fresh_registry()
    reg.add_manifest({
        "type_id": "probe.source_cmd", "version": "1.0.0",
        "config_schema": {"type": "object"},
        "ports": [{"id": "go", "direction": "out", "kind": "command",
                   "payload_schema": {"type": "object",
                                      "properties": {"name": {"type": "string"}},
                                      "required": ["name"],
                                      "additionalProperties": False}}],
    })
    reg.add_manifest({
        "type_id": "probe.target_cmd", "version": "1.0.0",
        "config_schema": {"type": "object"},
        "ports": [{"id": "run", "direction": "in", "kind": "command",
                   "payload_schema": {"type": "object",
                                      "properties": {"name": {"type": "string"}},
                                      "required": ["name"],
                                      "additionalProperties": False},
                   "result_schema": {"type": "object",
                                     "properties": {"ok": {"type": "boolean"}},
                                     "required": ["ok"],
                                     "additionalProperties": False}}],
    })
    reg.add_manifest({
        "type_id": "probe.both", "version": "1.0.0",
        "config_schema": {"type": "object"},
        "ports": [
            {"id": "invoke", "direction": "in", "kind": "command",
             "payload_schema": {"type": "object", "properties": {},
                                "additionalProperties": False}},
            {"id": "changed", "direction": "out", "kind": "event",
             "payload_schema": {"type": "object", "properties": {},
                                "additionalProperties": False}},
        ],
    })
    reg.add_manifest({
        "type_id": "probe.cmd_src", "version": "1.0.0",
        "config_schema": {"type": "object"},
        "ports": [{"id": "fire", "direction": "out", "kind": "command",
                   "payload_schema": {"type": "object", "properties": {},
                                      "additionalProperties": False}}],
    })
    assert not reg.issues, [e.as_dict() for e in reg.issues]
    return reg


def probe_project() -> dict:
    return {
        "schema_version": "0.1-draft",
        "project": {"id": "probe.spike", "display_name": "Probe"},
        "dependencies": [
            {"type": "probe.source_cmd", "version": "1.0.0"},
            {"type": "probe.target_cmd", "version": "1.0.0"},
        ],
        "components": [
            {"id": "src.one", "type": "probe.source_cmd", "version": "1.0.0", "config": {}},
            {"id": "dst.one", "type": "probe.target_cmd", "version": "1.0.0", "config": {}},
        ],
        "states": [],
        "bindings": [
            {"id": "b.cmd", "kind": "command",
             "source": {"owner_kind": "component", "owner_id": "src.one", "port": "go"},
             "target": {"owner_kind": "component", "owner_id": "dst.one", "port": "run"}},
        ],
        "presentations": [],
        "assets": [],
        "views": [],
    }


class TestCompileGates(unittest.TestCase):
    def test_valid_example_compiles_state_binding_ignored(self):
        raw, plan, issues = compile_base()
        self.assertIsNotNone(plan)
        self.assertTrue(all(c.kind in ("command", "event") for c in plan.connections))
        self.assertIn("binding.visual_state", list(plan.ignored_state_binding_ids))
        self.assertFalse(plan.provisional)
        self.assertEqual(plan.quarantined_binding_ids, ())

    def test_invalid_project_refused(self):
        reg = fresh_registry()
        raw = base_project()
        raw["bindings"][0]["target"] = {
            "owner_kind": "component", "owner_id": "handler.primary", "port": "missing.port"}
        plan, issues = compile_plan(raw, reg)
        self.assertIsNone(plan)
        self.assertTrue(any(i.severity == "ERROR" for i in issues))

    def test_unproven_blocked_by_default(self):
        reg = fresh_registry()
        reg.add_manifest({"type_id": "probe.u_src", "version": "1.0.0", "ports": [
            {"id": "s", "direction": "out", "kind": "event",
             "payload_schema": {"type": "object"}}]})
        reg.add_manifest({"type_id": "probe.u_dst", "version": "1.0.0", "ports": [
            {"id": "t", "direction": "in", "kind": "event",
             "payload_schema": {"type": "object", "required": ["x"],
                                "properties": {"x": {"type": "string"}},
                                "additionalProperties": True}}]})
        raw = base_project()
        raw["dependencies"] = [{"type": "probe.u_src", "version": "1.0.0"},
                               {"type": "probe.u_dst", "version": "1.0.0"}]
        raw["components"] = [
            {"id": "u.src", "type": "probe.u_src", "version": "1.0.0", "config": {}},
            {"id": "u.dst", "type": "probe.u_dst", "version": "1.0.0", "config": {}}]
        raw["states"] = []
        raw["presentations"] = []
        raw["views"] = []
        raw["bindings"] = [{"id": "b.unproven", "kind": "event",
                            "source": {"owner_kind": "component", "owner_id": "u.src", "port": "s"},
                            "target": {"owner_kind": "component", "owner_id": "u.dst", "port": "t"}}]
        plan, issues = compile_plan(raw, reg)
        self.assertIsNone(plan)
        self.assertTrue(any(i.code == "RUNTIME_UNPROVEN_BLOCKED" and i.severity == "ERROR"
                            for i in issues), [i.as_dict() for i in issues])

    def test_unproven_provisional_quarantine_never_dispatches(self):
        reg = fresh_registry()
        reg.add_manifest({"type_id": "probe.u_src", "version": "1.0.0", "ports": [
            {"id": "s", "direction": "out", "kind": "event",
             "payload_schema": {"type": "object"}}]})
        reg.add_manifest({"type_id": "probe.u_dst", "version": "1.0.0", "ports": [
            {"id": "t", "direction": "in", "kind": "event",
             "payload_schema": {"type": "object", "required": ["x"],
                                "properties": {"x": {"type": "string"}},
                                "additionalProperties": True}}]})
        raw = base_project()
        raw["dependencies"] = [{"type": "probe.u_src", "version": "1.0.0"},
                               {"type": "probe.u_dst", "version": "1.0.0"}]
        raw["components"] = [
            {"id": "u.src", "type": "probe.u_src", "version": "1.0.0", "config": {}},
            {"id": "u.dst", "type": "probe.u_dst", "version": "1.0.0", "config": {}}]
        raw["states"] = []
        raw["presentations"] = []
        raw["views"] = []
        raw["bindings"] = [{"id": "b.unproven", "kind": "event",
                            "source": {"owner_kind": "component", "owner_id": "u.src", "port": "s"},
                            "target": {"owner_kind": "component", "owner_id": "u.dst", "port": "t"}}]
        plan, issues = compile_plan(raw, reg, allow_unproven=True)
        self.assertIsNotNone(plan)
        self.assertTrue(plan.provisional)
        self.assertIn("b.unproven", list(plan.quarantined_binding_ids))
        self.assertEqual([c.binding_id for c in plan.connections], [])
        rt = InMemoryRuntime(plan)
        calls: list = []
        rt.register_handler("u.dst", "t", lambda p, c: calls.append(p))
        report = rt.dispatch_event("u.src", "s", {"x": "ok"})
        self.assertEqual(report["status"], "REJECTED")
        self.assertTrue(any(d["code"] == "RUNTIME_UNPROVEN_BLOCKED"
                            for d in report["diagnostics"]))
        self.assertEqual(calls, [])


class TestDispatch(unittest.TestCase):
    def test_fanout_same_port_types(self):
        reg = fresh_registry()
        raw = base_project()
        raw["components"].append(
            {"id": "handler.second", "type": "core.host_handler",
             "version": "1.0.0", "config": {"callback_id": "handler.second"}})
        raw["bindings"].append(
            {"id": "binding.command.b", "kind": "command",
             "source": {"owner_kind": "component", "owner_id": "action.primary", "port": "activated"},
             "target": {"owner_kind": "component", "owner_id": "handler.second", "port": "invoke"}})
        plan, issues = compile_plan(raw, reg)
        self.assertIsNotNone(plan, [i.as_dict() for i in issues])
        rt = InMemoryRuntime(plan)
        seen: list = []
        rt.register_handler("handler.primary", "invoke", lambda p, c: seen.append(("a", p)))
        rt.register_handler("handler.second", "invoke", lambda p, c: seen.append(("b", p)))
        report = rt.dispatch_command("action.primary", "activated", {})
        self.assertEqual(report["status"], "DISPATCHED")
        self.assertEqual([d["status"] for d in report["deliveries"]], ["OK", "OK"])
        self.assertEqual([d["binding_id"] for d in report["deliveries"]],
                         sorted(d["binding_id"] for d in report["deliveries"]))
        self.assertEqual(sorted(seen), [("a", {}), ("b", {})])

    def test_command_event_separation(self):
        reg = fresh_registry()
        raw = base_project()
        raw["dependencies"].extend([
            {"type": "test.event_emitter", "version": "1.0.0"},
            {"type": "test.state_consumer", "version": "1.0.0"}])
        raw["components"].extend([
            {"id": "emitter.one", "type": "test.event_emitter",
             "version": "1.0.0", "config": {"display_name": "E"}},
            {"id": "consumer.one", "type": "test.state_consumer",
             "version": "1.0.0", "config": {"display_name": "C"}}])
        raw["bindings"].append(
            {"id": "binding.event", "kind": "event",
             "source": {"owner_kind": "component", "owner_id": "emitter.one", "port": "fired"},
             "target": {"owner_kind": "component", "owner_id": "consumer.one", "port": "trigger"}})
        plan, issues = compile_plan(raw, reg)
        self.assertIsNotNone(plan, [i.as_dict() for i in issues])
        rt = InMemoryRuntime(plan)
        cmd_seen, evt_seen = [], []
        rt.register_handler("handler.primary", "invoke", lambda p, c: cmd_seen.append(p))
        rt.register_handler("consumer.one", "trigger", lambda p, c: evt_seen.append(p))
        cmd_report = rt.dispatch_command("action.primary", "activated", {})
        self.assertEqual(len(cmd_report["deliveries"]), 1)
        self.assertEqual(cmd_seen, [{}])
        self.assertEqual(evt_seen, [])
        evt_report = rt.dispatch_event("emitter.one", "fired", {})
        self.assertEqual(len(evt_report["deliveries"]), 1)
        self.assertEqual(evt_seen, [{}])
        self.assertEqual(cmd_seen, [{}])
        # cross-kind dispatch on a valid port is a structured mismatch
        mismatch = rt.dispatch_command("emitter.one", "fired", {})
        self.assertEqual(mismatch["status"], "REJECTED")
        self.assertTrue(any(d["code"] == "RUNTIME_KIND_MISMATCH"
                            for d in mismatch["diagnostics"]))

    def test_valid_and_mismatched_payloads(self):
        reg = probe_registry()
        raw = probe_project()
        plan, issues = compile_plan(raw, reg)
        self.assertIsNotNone(plan, [i.as_dict() for i in issues])
        rt = InMemoryRuntime(plan)
        seen: list = []
        rt.register_handler("dst.one", "run", lambda p, c: seen.append(p) or {"result": {"ok": True}})
        ok_report = rt.dispatch_command("src.one", "go", {"name": "ada"})
        self.assertEqual(ok_report["deliveries"][0]["status"], "OK")
        self.assertEqual(seen, [{"name": "ada"}])
        bad_report = rt.dispatch_command("src.one", "go", {"name": 123})
        self.assertEqual(bad_report["status"], "REJECTED")
        self.assertTrue(any("payload" in d["path"].lower() or d["code"].startswith("VALUE_")
                            for d in bad_report["diagnostics"]))
        self.assertEqual(len(seen), 1)  # handler not called for invalid payload

    def test_unknown_endpoints_structured(self):
        raw, plan, issues = compile_base()
        self.assertIsNotNone(plan)
        rt = InMemoryRuntime(plan)
        report = rt.dispatch_command("no.such", "nope", {})
        self.assertEqual(report["status"], "REJECTED")
        self.assertTrue(any(d["code"] == "RUNTIME_ENDPOINT_UNKNOWN"
                            for d in report["diagnostics"]))
        report2 = rt.dispatch_command("action.primary", "missing.port", {})
        self.assertEqual(report2["status"], "REJECTED")

    def test_missing_and_faulty_handler(self):
        raw, plan, issues = compile_base()
        rt = InMemoryRuntime(plan)
        no_handler = rt.dispatch_command("action.primary", "activated", {})
        self.assertEqual(no_handler["deliveries"][0]["status"], "RUNTIME_NO_HANDLER")

        def boom(payload, ctx):
            raise RuntimeError("boom-fault")
        rt.register_handler("handler.primary", "invoke", boom)
        err_report = rt.dispatch_command("action.primary", "activated", {})
        self.assertEqual(err_report["deliveries"][0]["status"], "RUNTIME_HANDLER_ERROR")
        self.assertIn("boom-fault", err_report["deliveries"][0]["issues"][0]["message"])
        # no exception escapes dispatch
        self.assertEqual(err_report["status"], "DISPATCHED")

    def test_result_schema_validation(self):
        reg = probe_registry()
        raw = probe_project()
        plan, issues = compile_plan(raw, reg)
        self.assertIsNotNone(plan, [i.as_dict() for i in issues])
        rt = InMemoryRuntime(plan)
        rt.register_handler("dst.one", "run", lambda p, c: {"result": {"bad": 1}})
        bad = rt.dispatch_command("src.one", "go", {"name": "x"})
        self.assertEqual(bad["deliveries"][0]["status"], "RUNTIME_RESULT_INVALID")
        rt.register_handler("dst.one", "run", lambda p, c: {"result": {"ok": True}})
        good = rt.dispatch_command("src.one", "go", {"name": "x"})
        self.assertEqual(good["deliveries"][0]["status"], "OK")
        self.assertEqual(good["deliveries"][0]["result"], {"ok": True})

    def test_no_automatic_success_event_and_explicit_emit(self):
        reg = probe_registry()
        raw = {
            "schema_version": "0.1-draft",
            "project": {"id": "probe.emit", "display_name": "Probe"},
            "dependencies": [
                {"type": "probe.cmd_src", "version": "1.0.0"},
                {"type": "probe.both", "version": "1.0.0"},
                {"type": "test.state_consumer", "version": "1.0.0"},
            ],
            "components": [
                {"id": "cmd.src", "type": "probe.cmd_src", "version": "1.0.0", "config": {}},
                {"id": "mid.one", "type": "probe.both", "version": "1.0.0", "config": {}},
                {"id": "sink.one", "type": "test.state_consumer", "version": "1.0.0",
                 "config": {"display_name": "S"}},
            ],
            "states": [],
            "bindings": [
                {"id": "b.cmd", "kind": "command",
                 "source": {"owner_kind": "component", "owner_id": "cmd.src", "port": "fire"},
                 "target": {"owner_kind": "component", "owner_id": "mid.one", "port": "invoke"}},
                {"id": "b.evt", "kind": "event",
                 "source": {"owner_kind": "component", "owner_id": "mid.one", "port": "changed"},
                 "target": {"owner_kind": "component", "owner_id": "sink.one", "port": "trigger"}},
            ],
            "presentations": [],
            "assets": [],
            "views": [],
        }
        plan, issues = compile_plan(raw, reg)
        self.assertIsNotNone(plan, [i.as_dict() for i in issues])
        rt = InMemoryRuntime(plan)
        sink_seen: list = []
        rt.register_handler("sink.one", "trigger", lambda p, c: sink_seen.append(p))
        rt.register_handler("mid.one", "invoke", lambda p, c: {"result": {"done": True}})
        plain = rt.dispatch_command("cmd.src", "fire", {})
        self.assertEqual(plain["deliveries"][0]["status"], "OK")
        self.assertEqual(plain["deliveries"][0]["emitted"], [])
        self.assertEqual(sink_seen, [])

        rt.register_handler(
            "mid.one", "invoke",
            lambda p, c: {"result": {"done": True},
                          "emit": [{"port": "changed", "payload": {}}]})
        chained = rt.dispatch_command("cmd.src", "fire", {})
        self.assertEqual(chained["deliveries"][0]["status"], "OK")
        self.assertEqual(len(chained["deliveries"][0]["emitted"]), 1)
        self.assertEqual(sink_seen, [{}])

    def test_deterministic_repeat_and_payload_isolation(self):
        raw, plan, issues = compile_base()
        rt = InMemoryRuntime(plan)
        calls: list = []

        def handler(payload, ctx):
            calls.append(copy.deepcopy(payload))
            payload["mutated"] = True  # must not leak into sibling/other dispatches
            return {"result": {"n": 1}}

        rt.register_handler("handler.primary", "invoke", handler)
        first = rt.dispatch_command("action.primary", "activated", {}, correlation_id="c.1")
        second = rt.dispatch_command("action.primary", "activated", {}, correlation_id="c.1")
        self.assertEqual(first, second)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertEqual(calls, [{}, {}])

    def test_ordering_is_lexical_by_binding_id_spike_only(self):
        reg = fresh_registry()
        raw = base_project()
        raw["components"].append(
            {"id": "handler.second", "type": "core.host_handler",
             "version": "1.0.0", "config": {"callback_id": "handler.second"}})
        # project array order is zzz-before-aaa; spike order must still be lexical
        raw["bindings"] = [
            {"id": "b.zzz", "kind": "command",
             "source": {"owner_kind": "component", "owner_id": "action.primary", "port": "activated"},
             "target": {"owner_kind": "component", "owner_id": "handler.second", "port": "invoke"}},
            {"id": "b.aaa", "kind": "command",
             "source": {"owner_kind": "component", "owner_id": "action.primary", "port": "activated"},
             "target": {"owner_kind": "component", "owner_id": "handler.primary", "port": "invoke"}},
        ]
        plan, issues = compile_plan(raw, reg)
        self.assertIsNotNone(plan, [i.as_dict() for i in issues])
        self.assertEqual([c.binding_id for c in plan.connections], ["b.aaa", "b.zzz"])
        rt = InMemoryRuntime(plan)
        order: list = []
        rt.register_handler("handler.primary", "invoke", lambda p, c: order.append(c["binding_id"]))
        rt.register_handler("handler.second", "invoke", lambda p, c: order.append(c["binding_id"]))
        report = rt.dispatch_command("action.primary", "activated", {})
        self.assertEqual(order, ["b.aaa", "b.zzz"])
        self.assertEqual([d["binding_id"] for d in report["deliveries"]], ["b.aaa", "b.zzz"])

    def test_correlation_id_passthrough(self):
        raw, plan, issues = compile_base()
        rt = InMemoryRuntime(plan)
        seen: list = []
        rt.register_handler("handler.primary", "invoke",
                            lambda p, c: seen.append(c.get("correlation_id")))
        report = rt.dispatch_command("action.primary", "activated", {},
                                     correlation_id="corr.001")
        self.assertEqual(report["correlation_id"], "corr.001")
        self.assertEqual(seen, ["corr.001"])

    def test_no_runtime_states_written_to_project(self):
        raw = base_project()
        before = json.dumps(raw, sort_keys=True)
        plan, issues = compile_plan(raw, fresh_registry())
        self.assertIsNotNone(plan)
        self.assertFalse(hasattr(plan, "state_store"))
        rt = InMemoryRuntime(plan)
        self.assertFalse(hasattr(rt, "state_store"))
        self.assertFalse(hasattr(rt, "snapshot"))
        rt.register_handler("handler.primary", "invoke", lambda p, c: {"result": {"ok": True}})
        rt.dispatch_command("action.primary", "activated", {})
        after = json.dumps(raw, sort_keys=True)
        self.assertEqual(before, after)
        self.assertNotIn("runtime", before.lower().replace("handler.primary", ""))

    def test_handler_returning_bare_value_is_result(self):
        raw, plan, issues = compile_base()
        rt = InMemoryRuntime(plan)
        rt.register_handler("handler.primary", "invoke", lambda p, c: {"ok": True})
        report = rt.dispatch_command("action.primary", "activated", {})
        self.assertEqual(report["deliveries"][0]["status"], "OK")
        self.assertEqual(report["deliveries"][0]["result"], {"ok": True})
        self.assertEqual(report["deliveries"][0]["emitted"], [])


class TestReviewR002Regressions(unittest.TestCase):
    """Permanent regressions for review findings R002-01..R002-03."""

    def _emit_project(self):
        # probe_registry() = shipped manifests + probe types (no duplicates:
        # test.* manifests already ship in component_types/ and re-adding
        # them would be a registry ERROR that now correctly blocks compile).
        reg = probe_registry()
        raw = {
            "schema_version": "0.1-draft",
            "project": {"id": "probe.emit", "display_name": "Probe"},
            "dependencies": [
                {"type": "probe.cmd_src", "version": "1.0.0"},
                {"type": "probe.both", "version": "1.0.0"},
                {"type": "test.event_emitter", "version": "1.0.0"},
                {"type": "test.state_consumer", "version": "1.0.0"},
            ],
            "components": [
                {"id": "cmd.src", "type": "probe.cmd_src", "version": "1.0.0", "config": {}},
                {"id": "mid.one", "type": "probe.both", "version": "1.0.0", "config": {}},
                {"id": "sink.one", "type": "test.state_consumer", "version": "1.0.0",
                 "config": {"display_name": "S"}},
            ],
            "states": [],
            "bindings": [
                {"id": "b.cmd", "kind": "command",
                 "source": {"owner_kind": "component", "owner_id": "cmd.src", "port": "fire"},
                 "target": {"owner_kind": "component", "owner_id": "mid.one", "port": "invoke"}},
                {"id": "b.evt", "kind": "event",
                 "source": {"owner_kind": "component", "owner_id": "mid.one", "port": "changed"},
                 "target": {"owner_kind": "component", "owner_id": "sink.one", "port": "trigger"}},
            ],
            "presentations": [],
            "assets": [],
            "views": [],
        }
        plan, issues = compile_plan(raw, reg)
        self.assertIsNotNone(plan, [i.as_dict() for i in issues])
        return plan

    def test_R002_01_malformed_emit_ports_structured(self):
        plan = self._emit_project()
        for bad_port in ([], {}, None, 123, "unknown.port", ""):
            with self.subTest(port=bad_port):
                rt = InMemoryRuntime(plan)
                sink_calls: list = []
                rt.register_handler("sink.one", "trigger",
                                    lambda p, c: sink_calls.append(p))
                rt.register_handler(
                    "mid.one", "invoke",
                    lambda p, c, bp=bad_port: {"emit": [{"port": bp, "payload": {}}]})
                report = rt.dispatch_command("cmd.src", "fire", {})
                delivery = report["deliveries"][0]
                self.assertEqual(delivery["status"], "RUNTIME_EMIT_INVALID")
                self.assertTrue(delivery["issues"])
                self.assertTrue(all(i["code"] == "RUNTIME_EMIT_INVALID"
                                    for i in delivery["issues"]))
                self.assertEqual(delivery["emitted"], [])
                self.assertEqual(sink_calls, [])

    def test_R002_01_valid_emit_still_dispatched(self):
        plan = self._emit_project()
        rt = InMemoryRuntime(plan)
        sink_calls: list = []
        rt.register_handler("sink.one", "trigger", lambda p, c: sink_calls.append(p))
        rt.register_handler("mid.one", "invoke",
                            lambda p, c: {"emit": [{"port": "changed", "payload": {}}]})
        report = rt.dispatch_command("cmd.src", "fire", {})
        self.assertEqual(report["deliveries"][0]["status"], "OK")
        self.assertEqual(sink_calls, [{}])

    def test_R002_02_non_copyable_inbound_payload_rejected(self):
        raw, plan, issues = compile_base()
        self.assertIsNotNone(plan)
        rt = InMemoryRuntime(plan)
        calls: list = []
        rt.register_handler("handler.primary", "invoke",
                            lambda p, c: calls.append(p))
        report = rt.dispatch_command("action.primary", "activated", memoryview(b"bad"))
        self.assertEqual(report["status"], "REJECTED")
        self.assertTrue(report["diagnostics"])
        self.assertEqual(calls, [])
        # bytes is deepcopyable but not schema-valid: still structured, no crash
        report2 = rt.dispatch_command("action.primary", "activated", b"bad")
        self.assertEqual(report2["status"], "REJECTED")
        self.assertTrue(report2["diagnostics"])
        self.assertEqual(calls, [])

    def test_R002_02_non_copyable_handler_result_and_emit(self):
        plan = self._emit_project()
        rt = InMemoryRuntime(plan)
        sink_calls: list = []
        rt.register_handler("sink.one", "trigger", lambda p, c: sink_calls.append(p))
        rt.register_handler("mid.one", "invoke",
                            lambda p, c: {"result": memoryview(b"bad")})
        bad_result = rt.dispatch_command("cmd.src", "fire", {})
        self.assertEqual(bad_result["deliveries"][0]["status"], "RUNTIME_RESULT_INVALID")
        self.assertTrue(bad_result["deliveries"][0]["issues"])
        rt.register_handler("mid.one", "invoke",
                            lambda p, c: {"emit": [{"port": "changed",
                                                    "payload": memoryview(b"bad")}]})
        bad_emit = rt.dispatch_command("cmd.src", "fire", {})
        delivery = bad_emit["deliveries"][0]
        self.assertEqual(delivery["status"], "RUNTIME_EMIT_INVALID")
        self.assertTrue(any(i["code"] == "RUNTIME_EMIT_INVALID" for i in delivery["issues"]))
        self.assertEqual(sink_calls, [])

    def test_R002_03_registry_error_blocks_compilation(self):
        reg, _ = load_manifests(ROOT / "component_types")
        reg.add_manifest({"type_id": "probe.bad", "version": "1.0.0", "ports": [
            {"id": "p", "direction": "sideways", "kind": "event",
             "payload_schema": {"type": "object"}}]}, origin="bad_manifest.json")
        self.assertTrue(any(i.severity == "ERROR" for i in reg.issues))
        raw = base_project()
        plan, issues = compile_plan(raw, reg)
        self.assertIsNone(plan)
        self.assertTrue(any(i.severity == "ERROR" for i in issues))
        # allow_unproven must not override a registry ERROR gate
        plan2, issues2 = compile_plan(raw, reg, allow_unproven=True)
        self.assertIsNone(plan2)
        self.assertTrue(any(i.severity == "ERROR" for i in issues2))

    def test_R002_03_clean_registry_still_compiles(self):
        raw, plan, issues = compile_base()
        self.assertIsNotNone(plan, [i.as_dict() for i in issues])


if __name__ == "__main__":
    unittest.main()
