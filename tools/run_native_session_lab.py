"""Standalone AP-STUDIO-001 lab: only TEMP project copies, no Qt/SDK/service."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

# Running this lab must not create __pycache__ outside TEMP/evidence either.
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adapters.logitech.native import parse_native_project
from studio.native_session import NativeDiskConflict, NativeProjectSession, NativeRevisionConflict

EXAMPLE = ROOT / "examples" / "project_logitech_native_v1.json"
EVIDENCE = ROOT / "work" / "native-session" / "AP-STUDIO-001" / "evidence"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_lab(*, evidence: bool = False) -> dict:
    original = EXAMPLE.read_bytes()
    report = {"schema": "logitech-native-1", "example_sha256_before": sha(original), "checks": []}
    documents = {}

    def check(name: str, ok: bool) -> None:
        report["checks"].append({"name": name, "ok": bool(ok)})
        print(("OK   " if ok else "FAIL ") + name)
        if not ok:
            raise RuntimeError(name)

    try:
        with tempfile.TemporaryDirectory(prefix="native-session-lab-") as directory:
            target = Path(directory) / "project.json"
            target.write_bytes(original)
            session = NativeProjectSession.load(target)
            initial = session.snapshot()
            initial_revision = session.revision
            model = session.native_project()
            print("NativeProject:", model)
            for action in model.actions:
                print(f"Action {action.id}: {action.sdk_type}; {action.display_name}")
            print("Handler:", json.dumps(model.handlers, ensure_ascii=False, sort_keys=True))
            for folder in model.folders:
                print(f"Folder {folder.id} ({folder.navigation}): " + ", ".join(
                    f"{entry.id} -> {entry.action}@{entry.position}" for entry in folder.entries))
            check("Load: clean, no history, original TEMP bytes intact",
                  not session.dirty and not session.can_undo and not session.can_redo
                  and target.read_bytes() == original)
            proposed = session.snapshot()
            proposed["actions"][0]["display_name"] = "Geänderter nativer Befehl – Größe"
            changed_revision = session.replace(proposed, base_revision=initial_revision)
            committed = session.snapshot()
            check("Commit: raw and NativeProject show changed display_name; dirty=True",
                  committed == proposed and session.native_project().actions[0].display_name
                  == proposed["actions"][0]["display_name"] and session.dirty
                  and changed_revision != initial_revision and target.read_bytes() == original)
            proposed["actions"][0]["display_name"] = "Foreign mutation of caller copy"
            check("Caller snapshot cannot mutate the committed document", session.snapshot() == committed)
            check("Undo: original full JSON, dirty=False", session.undo()
                  and session.snapshot() == initial and not session.dirty)
            check("Redo: changed full JSON, dirty=True", session.redo()
                  and session.snapshot() == committed and session.dirty)
            revision_before_save = session.revision
            session.save()
            saved = target.read_bytes()
            check("Save: native parser + fresh session roundtrip, dirty=False",
                  json.loads(saved) == committed and parse_native_project(json.loads(saved))
                  == session.native_project() and NativeProjectSession.load(target).snapshot() == committed
                  and not session.dirty and session.revision == revision_before_save)
            check("Undo after save: dirty=True", session.undo() and session.dirty)
            check("Redo to saved content: dirty=False", session.redo() and not session.dirty)
            before = (session.snapshot(), session.revision, session.dirty, session.can_undo, session.can_redo)
            try:
                session.replace(initial, base_revision=initial_revision)
            except NativeRevisionConflict as exc:
                print("Expected revision conflict:", exc)
                revision_conflict = True
            else:
                revision_conflict = False
            check("Stale revision: fail-closed, session and disk unchanged", revision_conflict
                  and before == (session.snapshot(), session.revision, session.dirty,
                                 session.can_undo, session.can_redo) and target.read_bytes() == saved)
            local = session.snapshot()
            local["actions"][0]["display_name"] = "Unsaved local edit"
            session.replace(local, base_revision=session.revision)
            before = (session.snapshot(), session.revision, session.dirty, session.can_undo, session.can_redo)
            external = saved.replace(b"sample.native", b"extern.native")
            stat = target.stat()
            target.write_bytes(external)
            os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            try:
                session.save()
            except NativeDiskConflict as exc:
                print("Expected disk conflict:", exc)
                disk_conflict = True
            else:
                disk_conflict = False
            check("External bytes, same size/mtime: fail-closed, local edit retained", disk_conflict
                  and len(saved) == len(external) and target.stat().st_mtime_ns == stat.st_mtime_ns
                  and target.read_bytes() == external and before == (
                      session.snapshot(), session.revision, session.dirty, session.can_undo, session.can_redo))
            check("No orphan staging files", not list(Path(directory).glob(".native-session-*")))

            # Full optional JSON roundtrip on another TEMP file; no asset I/O.
            rich = copy.deepcopy(initial)
            rich["plugin"]["default_icon_template"] = "assets\\default.ict"
            rich["licenses"] = ["licenses/LICENSE.md"]
            rich["actions"][0].update(icon="assets/command.png", icon_template="assets\\command.ict",
                                      symbol="assets/command.svg", parameter_symbols={"first": "assets\\first.svg"})
            rich["actions"][1]["states"][0].update(image="assets\\off.svg", led_color=None)
            rich["actions"][3]["editor_controls"].append({
                "type": "slider", "name": "Level", "label": "Stärke", "minimum": 0,
                "maximum": 10, "step": 0.5, "default": 2.5, "format_string": "{0}%"})
            rich_target = Path(directory) / "optional.json"
            rich_target.write_text(json.dumps(rich, ensure_ascii=False), encoding="utf-8")
            rich_session = NativeProjectSession.load(rich_target)
            rich_session.save()
            rich_reloaded = NativeProjectSession.load(rich_target)
            rich_after = rich_reloaded.snapshot()
            check("Optional fields roundtrip: exact JSON values, including raw backslashes/null",
                  rich_after == rich and parse_native_project(rich_after) == rich_session.native_project())
            check("Asset references are preserved without creating or repairing files",
                  sorted(p.name for p in Path(directory).iterdir()) == ["optional.json", "project.json"])
            report["optional_roundtrip"] = {
                "equal": rich_after == rich,
                "fields": ["default_icon_template", "licenses", "icon", "icon_template", "symbol",
                           "states", "editor_controls", "parameter_symbols", "device_navigation"],
                "before_sha256": sha(json.dumps(rich, sort_keys=True, ensure_ascii=False).encode()),
                "after_sha256": sha(json.dumps(rich_after, sort_keys=True, ensure_ascii=False).encode()),
            }
            documents = {"lab-initial.json": initial, "lab-committed.json": committed,
                         "roundtrip-before.json": rich, "roundtrip-after.json": rich_after}
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        print("FAIL", report["error"])
    finally:
        after = EXAMPLE.read_bytes()
        report["example_sha256_after"] = sha(after)
        unchanged = after == original
        report["checks"].append({"name": "Original example byte-identical", "ok": unchanged})
        print(("OK   " if unchanged else "FAIL ") + "Original example byte-identical: " + sha(after))
        report["passed"] = "error" not in report and all(item["ok"] for item in report["checks"])
        if evidence:
            EVIDENCE.mkdir(parents=True, exist_ok=True)
            for name, raw in documents.items():
                (EVIDENCE / name).write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (EVIDENCE / "lab-report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="Automated full walkthrough; exit 0 only on success")
    parser.add_argument("--evidence", action="store_true", help="Write report only to this AP's fixed evidence directory")
    args = parser.parse_args(argv)
    report = run_lab(evidence=args.evidence)
    print(f"NativeSession lab: {'PASS' if report['passed'] else 'FAIL'}; "
          f"{sum(item['ok'] for item in report['checks'])}/{len(report['checks'])} checks")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
