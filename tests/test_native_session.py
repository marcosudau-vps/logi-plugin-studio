"""AP-STUDIO-001: transaction, lossless JSON and fail-closed filesystem tests."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adapters.logitech.native import NativeProjectError, parse_native_project
from studio import native_session
from studio.native_session import (
    NativeDiskConflict, NativeProjectSession, NativeRevisionConflict, NativeSessionError,
)

EXAMPLE = ROOT / "examples" / "project_logitech_native_v1.json"


def sample() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def rich_sample() -> dict:
    raw = sample()
    raw["plugin"]["default_icon_template"] = "assets\\default.ict"
    raw["licenses"] = ["licenses/LICENSE.md"]
    raw["actions"][0].update(
        icon="assets/command.png", icon_template="assets\\command.ict",
        symbol="assets/command.svg", parameter_symbols={"first": "assets\\first.svg"})
    raw["actions"][0]["parameters"][0]["super_group_name"] = "Übergeordnet"
    raw["actions"][1]["states"][0].update(image="assets\\off.svg", led_color=None)
    raw["actions"][3]["editor_controls"].extend([
        {"type": "slider", "name": "Level", "label": "Stärke", "minimum": 0,
         "maximum": 10, "step": 0.5, "default": 2.5, "format_string": "{0}%"},
        {"type": "file_selector", "name": "File", "label": "Datei", "description": "",
         "dialog_title": "Öffnen", "initial_directory": "images",
         "filters": [{"pattern": "*.png", "label": "Bilder"}]},
    ])
    raw["folders"][0]["device_navigation"]["Loupedeck60"] = "EncoderArea"
    return raw


class NativeSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-session-test-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / "project.json"
        self.original = EXAMPLE.read_bytes()
        self.path.write_bytes(self.original)
        self.session = NativeProjectSession.load(self.path)

    def change(self, name="Geändert", session=None):
        session = session or self.session
        raw = session.snapshot()
        raw["actions"][0]["display_name"] = name
        return session.replace(raw, base_revision=session.revision)

    def state(self):
        s = self.session
        return s.snapshot(), s.native_project(), s.revision, s.dirty, s.can_undo, s.can_redo

    def assert_no_temporary(self):
        self.assertEqual([], list(self.directory.glob(".native-session-*")))

    def test_load_preserves_sdk_types_parameters_states_handlers_and_folders(self):
        s = self.session
        self.assertEqual(s.path, self.path.resolve())
        self.assertEqual(s.snapshot(), sample())
        model = s.native_project()
        self.assertEqual([a.sdk_type for a in model.actions], [
            "PluginDynamicCommand", "PluginMultistateDynamicCommand",
            "PluginDynamicAdjustment", "ActionEditorCommand"])
        self.assertEqual([p.name for p in model.actions[0].parameters], ["first", "second"])
        self.assertEqual([state.index for state in model.actions[1].states], [0, 1])
        self.assertEqual(model.actions[2].adjustment_default, 50)
        self.assertEqual(model.actions[3].editor_controls[1].default, True)
        self.assertEqual(model.handlers[0]["callback_id"], "handler.main")
        self.assertEqual([e.position for e in model.folders[0].entries], [0, 1, 2, 3])
        self.assertEqual(model.folders[0].device_navigation, {"Loupedeck70": "None"})
        self.assertFalse(s.dirty or s.can_undo or s.can_redo)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_utf8_bom_and_umlauts_are_read_without_writing(self):
        raw = sample()
        raw["actions"][0]["display_name"] = "Größe, Öl & süß 🎚"
        content = b"\xef\xbb\xbf" + json.dumps(raw, ensure_ascii=False).encode("utf-8")
        self.path.write_bytes(content)
        s = NativeProjectSession.load(str(self.path))
        self.assertEqual(s.snapshot(), raw)
        self.assertEqual(self.path.read_bytes(), content)
        s.save()
        self.assertEqual(NativeProjectSession.load(self.path).snapshot(), raw)

    def test_bad_json_encoding_duplicates_nonfinite_and_root_fail_friendly(self):
        for data in (b"{", b"\xff", b"[]", b"null", b'{"x":1,"x":2}', b'{"x":NaN}'):
            with self.subTest(data=data):
                self.path.write_bytes(data)
                with self.assertRaises(NativeSessionError):
                    NativeProjectSession.load(self.path)
                self.assertEqual(self.path.read_bytes(), data)
                self.assert_no_temporary()

    def test_schema_legacy_explicitly_rejected_without_migration(self):
        self.path.write_text('{"schema_version":"0.1-draft"}', encoding="utf-8")
        before = self.path.read_bytes()
        with self.assertRaisesRegex(NativeSessionError, "0.1-draft.*Kompatibilitätseditor"):
            NativeProjectSession.load(self.path)
        self.assertEqual(before, self.path.read_bytes())
        raw = sample()
        raw["schema_version"] = "future"
        with self.assertRaisesRegex(NativeSessionError, "/schema_version"):
            NativeProjectSession.from_raw(raw)

    def test_missing_directory_and_oversized_files_do_not_create_anything(self):
        missing = self.directory / "absent" / "project.json"
        with self.assertRaises(NativeSessionError):
            NativeProjectSession.load(missing)
        self.assertFalse(missing.parent.exists())
        with self.assertRaises(NativeSessionError):
            NativeProjectSession.load(self.directory)
        with self.path.open("wb") as stream:
            stream.truncate(native_session.MAX_PROJECT_BYTES + 1)
        with self.assertRaisesRegex(NativeSessionError, "16 MiB"):
            NativeProjectSession.load(self.path)
        self.assert_no_temporary()

    def test_input_snapshot_and_projection_are_all_defensive(self):
        raw = rich_sample()
        original = copy.deepcopy(raw)
        s = NativeProjectSession.from_raw(raw)
        raw["actions"][0]["parameters"][0]["name"] = "foreign"
        snap = s.snapshot()
        snap["folders"][0]["entries"].clear()
        model = s.native_project()
        model.handlers[0]["callback_id"] = "foreign"
        model.actions[0].parameter_symbols.clear()
        model.folders[0].device_navigation.clear()
        self.assertEqual(s.snapshot(), original)
        self.assertEqual(s.native_project(), parse_native_project(original))
        self.assertEqual(s.snapshot()["actions"][0]["icon_template"], "assets\\command.ict")
        self.assertEqual(s.native_project().actions[0].icon_template, "assets/command.ict")
        self.assertIn("led_color", s.snapshot()["actions"][1]["states"][0])
        self.assertFalse(s.dirty)

    def test_from_raw_has_no_implicit_save_target(self):
        s = NativeProjectSession.from_raw(sample())
        self.assertIsNone(s.path)
        self.assertFalse(s.dirty)
        self.change(session=s)
        before = (s.snapshot(), s.revision, s.dirty)
        with self.assertRaisesRegex(NativeSessionError, "Pfad"):
            s.save()
        self.assertEqual((s.snapshot(), s.revision, s.dirty), before)

    def test_commits_undo_redo_and_empty_history_revisions(self):
        s = self.session
        r0 = s.revision
        self.assertFalse(s.undo())
        self.assertFalse(s.redo())
        self.assertEqual(s.revision, r0)
        r1 = self.change("Erste")
        first = s.snapshot()
        r2 = self.change("Zweite")
        second = s.snapshot()
        self.assertTrue(s.dirty and s.can_undo)
        self.assertFalse(s.can_redo)
        revisions = [r0, r1, r2]
        for expected in (first, sample()):
            self.assertTrue(s.undo())
            revisions.append(s.revision)
            self.assertEqual(s.snapshot(), expected)
            self.assertEqual(s.native_project(), parse_native_project(expected))
        self.assertFalse(s.dirty or s.can_undo)
        for expected in (first, second):
            self.assertTrue(s.redo())
            revisions.append(s.revision)
            self.assertEqual(s.snapshot(), expected)
        self.assertFalse(s.can_redo)
        self.assertEqual(len(set(revisions)), len(revisions))
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_commit_takes_a_defensive_copy(self):
        proposed = self.session.snapshot()
        proposed["actions"][0]["display_name"] = "Committed"
        self.session.replace(proposed, base_revision=self.session.revision)
        proposed["actions"][0]["display_name"] = "Later mutation"
        self.assertEqual(self.session.snapshot()["actions"][0]["display_name"], "Committed")
        self.session.undo()
        self.session.redo()
        self.assertEqual(self.session.native_project().actions[0].display_name, "Committed")

    def test_noop_retains_revision_history_and_redo_even_if_keys_reordered(self):
        self.change()
        self.session.undo()
        before = self.state()
        raw = dict(reversed(list(self.session.snapshot().items())))
        self.assertEqual(self.session.replace(raw, base_revision=self.session.revision), before[2])
        self.assertEqual(self.state(), before)
        self.assertTrue(self.session.redo())

    def test_new_commit_discards_redo(self):
        self.change("First")
        self.change("Second")
        self.session.undo()
        self.change("Branch")
        self.assertFalse(self.session.can_redo)
        self.assertFalse(self.session.redo())
        self.session.undo()
        self.assertEqual(self.session.native_project().actions[0].display_name, "First")

    def test_bounded_history(self):
        for number in range(55):
            self.change(str(number))
        count = 0
        while self.session.undo():
            count += 1
        self.assertEqual(count, 50)
        self.assertEqual(self.session.native_project().actions[0].display_name, "4")
        self.assertTrue(self.session.dirty)
        count = 0
        while self.session.redo():
            count += 1
        self.assertEqual(count, 50)
        self.assertEqual(self.session.native_project().actions[0].display_name, "54")

    def test_dirty_compares_saved_content_not_history_and_save_retains_revision(self):
        s = self.session
        self.change("Saved")
        revision = s.revision
        s.save()
        saved_bytes = self.path.read_bytes()
        self.assertFalse(s.dirty)
        self.assertTrue(s.can_undo)
        self.assertEqual(s.revision, revision)
        s.undo()
        self.assertTrue(s.dirty)
        self.assertEqual(self.path.read_bytes(), saved_bytes)
        s.redo()
        self.assertFalse(s.dirty)
        self.change("Other")
        self.change("Saved")
        self.assertFalse(s.dirty)
        s.save()  # A second save uses the refreshed byte baseline.
        self.assertEqual(self.path.read_bytes(), saved_bytes)

    def test_invalid_native_changes_preserve_state_history_and_parser_paths(self):
        self.change("First")
        self.change("Second")
        self.session.undo()  # Failure must also preserve an existing redo branch.
        mutations = [
            lambda r: r["actions"][0].update(id="INVALID ID"),
            lambda r: r["actions"][0].update(handler="handler.missing"),
            lambda r: r["handlers"][0].update(callback_id=""),
            lambda r: r["folders"][0]["entries"][0].update(action="action.missing"),
            lambda r: r["folders"][0]["entries"][0].update(position=-1),
            lambda r: r["actions"][0]["parameters"][0].update(name=""),
            lambda r: r["actions"][1]["states"][0].update(index=10),
            lambda r: r["actions"][3]["editor_controls"][0].update(type="invented"),
            lambda r: r["actions"][0].update(parameter_symbols={"unknown": "image.svg"}),
        ]
        for mutate in mutations:
            raw = self.session.snapshot()
            mutate(raw)
            with self.subTest(raw=raw):
                before = self.state()
                with self.assertRaises(NativeProjectError) as parser_error:
                    parse_native_project(raw)
                with self.assertRaises(NativeSessionError) as error:
                    self.session.replace(raw, base_revision=self.session.revision)
                self.assertIsInstance(error.exception.__cause__, NativeProjectError)
                self.assertIn(str(parser_error.exception), str(error.exception))
                self.assertEqual(self.state(), before)
        self.assertTrue(self.session.redo())
        self.assertEqual(self.session.native_project().actions[0].display_name, "Second")
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_unhashable_input_nonfinite_and_large_proposal_leave_state_unchanged(self):
        for value in ([], float("inf"), "X" * native_session.MAX_PROJECT_BYTES):
            raw = self.session.snapshot()
            if value == []:
                raw["actions"][0]["sdk_type"] = value
            elif isinstance(value, float):
                raw["actions"][2]["adjustment"]["maximum"] = value
            else:
                raw["actions"][0]["display_name"] = value
            before = self.state()
            with self.assertRaises(NativeSessionError):
                self.session.replace(raw, base_revision=self.session.revision)
            self.assertEqual(self.state(), before)

    def test_stale_foreign_and_undo_revisions_fail_closed_even_for_noop(self):
        stale = self.session.revision
        self.change()
        before = self.state()
        for revision in (stale, NativeProjectSession.from_raw(sample()).revision, "", None):
            with self.subTest(revision=revision):
                with self.assertRaises(NativeRevisionConflict):
                    self.session.replace(self.session.snapshot(), base_revision=revision)
                self.assertEqual(self.state(), before)
        self.session.undo()
        with self.assertRaises(NativeRevisionConflict):
            self.session.replace(sample(), base_revision=stale)

    def test_external_same_size_same_mtime_and_format_only_changes_are_conflicts(self):
        self.change()
        stamp = self.path.stat()
        external = self.original.replace(b"sample.native", b"extern.native")
        self.assertEqual(len(external), len(self.original))
        self.path.write_bytes(external)
        os.utime(self.path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        self.assertEqual(self.path.stat().st_mtime_ns, stamp.st_mtime_ns)
        before = self.state()
        with self.assertRaises(NativeDiskConflict):
            self.session.save()
        self.assertEqual(self.path.read_bytes(), external)
        self.assertEqual(self.state(), before)
        self.assert_no_temporary()
        external = self.original + b" "  # Same parsed content is still foreign bytes.
        self.path.write_bytes(external)
        with self.assertRaises(NativeDiskConflict):
            self.session.save()
        self.assertEqual(self.path.read_bytes(), external)

    def test_deleted_unreadable_and_oversized_target_fail_closed(self):
        self.change()
        self.path.unlink()
        before = self.state()
        with self.assertRaises(NativeDiskConflict):
            self.session.save()
        self.assertFalse(self.path.exists())
        self.assertEqual(self.state(), before)
        self.path.write_bytes(self.original)
        with patch.object(native_session, "_read_limited", side_effect=PermissionError("denied")):
            with self.assertRaises(NativeDiskConflict):
                self.session.save()
        with self.path.open("wb") as stream:
            stream.truncate(native_session.MAX_PROJECT_BYTES + 1)
        with self.assertRaises(NativeDiskConflict):
            self.session.save()
        self.assertEqual(self.path.stat().st_size, native_session.MAX_PROJECT_BYTES + 1)
        self.assertEqual(self.state(), before)
        self.assert_no_temporary()

    def test_second_disk_check_detects_change_during_fsync_and_cleans_staging(self):
        self.change()
        before = self.state()
        external = self.original + b"\n"
        real_fsync = os.fsync

        def concurrent_change(fd):
            real_fsync(fd)
            self.path.write_bytes(external)

        with patch.object(native_session.os, "fsync", side_effect=concurrent_change), \
                patch.object(native_session.os, "replace") as replace:
            with self.assertRaises(NativeDiskConflict):
                self.session.save()
            replace.assert_not_called()
        self.assertEqual(self.state(), before)
        self.assertEqual(self.path.read_bytes(), external)
        self.assert_no_temporary()

    def test_second_disk_check_detects_deleted_target(self):
        self.change()
        with patch.object(native_session.os, "fsync", side_effect=lambda fd: self.path.unlink()):
            with self.assertRaises(NativeDiskConflict):
                self.session.save()
        self.assertFalse(self.path.exists())
        self.assertTrue(self.session.dirty)
        self.assert_no_temporary()

    def test_atomic_replace_receives_complete_closed_fsynced_staging_file(self):
        self.change()
        expected = self.session.snapshot()
        real_replace, real_fsync = os.replace, os.fsync
        seen = []

        def fsync(fd):
            real_fsync(fd)
            seen.append("fsync")

        def replace(source, target):
            self.assertEqual(seen, ["fsync"])
            self.assertEqual(Path(source).parent, self.path.parent)
            self.assertEqual(Path(target), self.path.resolve())
            self.assertEqual(self.path.read_bytes(), self.original)
            self.assertEqual(json.loads(Path(source).read_bytes()), expected)
            real_replace(source, target)
            seen.append("replace")

        with patch.object(native_session.os, "fsync", side_effect=fsync), \
                patch.object(native_session.os, "replace", side_effect=replace):
            self.session.save()
        self.assertEqual(seen, ["fsync", "replace"])
        self.assertEqual(NativeProjectSession.load(self.path).snapshot(), expected)
        self.assertFalse(self.session.dirty)
        self.assert_no_temporary()

    def test_creation_fsync_and_replace_failures_preserve_target_and_session(self):
        self.change()
        before = self.state()
        for owner, name in ((native_session.tempfile, "NamedTemporaryFile"),
                            (native_session.os, "fsync"), (native_session.os, "replace")):
            with self.subTest(stage=name):
                with patch.object(owner, name, side_effect=OSError("simulated " + name)):
                    with self.assertRaisesRegex(NativeSessionError, "simulated"):
                        self.session.save()
                self.assertEqual(self.path.read_bytes(), self.original)
                self.assertEqual(self.state(), before)
                self.assert_no_temporary()
        self.session.save()  # Failed writes did not advance either baseline.
        self.assertFalse(self.session.dirty)

    def test_partial_write_and_flush_failure_cleanup(self):
        self.change()
        before = self.state()
        factory = native_session.tempfile.NamedTemporaryFile
        for failure in ("write", "flush"):
            class BrokenStream:
                def __enter__(inner):
                    inner.stream = factory(dir=self.directory, prefix=".native-session-", delete=False)
                    inner.name = inner.stream.name
                    return inner

                def write(inner, content):
                    if failure == "write":
                        inner.stream.write(content[:20])
                        raise OSError("partial write")
                    return inner.stream.write(content)

                def flush(inner):
                    raise OSError("flush failed")

                def __exit__(inner, *args):
                    inner.stream.close()

            with self.subTest(failure=failure):
                with patch.object(native_session.tempfile, "NamedTemporaryFile", return_value=BrokenStream()):
                    with self.assertRaises(NativeSessionError):
                        self.session.save()
                self.assertEqual(self.path.read_bytes(), self.original)
                self.assertEqual(self.state(), before)
                self.assert_no_temporary()

    def test_cleanup_failure_retains_original_error_and_reports_orphan_path(self):
        self.change()
        with patch.object(native_session.os, "replace", side_effect=OSError("replace failed")), \
                patch.object(native_session.Path, "unlink", side_effect=PermissionError("cleanup denied")):
            with self.assertRaisesRegex(NativeSessionError, "replace failed") as error:
                self.session.save()
        self.assertIn("cleanup denied", " ".join(error.exception.__notes__))
        orphans = list(self.directory.glob(".native-session-*"))
        self.assertEqual(len(orphans), 1)
        self.assertIn(str(orphans[0]), " ".join(error.exception.__notes__))
        orphans[0].unlink()
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertTrue(self.session.dirty)
        self.assert_no_temporary()

    def test_full_optional_json_roundtrip_preserves_raw_values_and_assets(self):
        raw = rich_sample()
        self.path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        assets = {}
        for name in ("default.ict", "command.ict", "command.svg", "command.png", "first.svg", "off.svg"):
            target = self.directory / "assets" / name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(b"fixture bytes, never parsed or repaired: " + name.encode())
            assets[name] = hashlib.sha256(target.read_bytes()).hexdigest()
        s = NativeProjectSession.load(self.path)
        initial_revision = s.revision
        s.save()
        self.assertEqual(s.revision, initial_revision)
        self.assertEqual(json.loads(self.path.read_bytes()), raw)
        self.change("Öffnen geändert", session=s)
        changed = s.snapshot()
        s.undo()
        self.assertEqual(s.snapshot(), raw)
        s.redo()
        s.save()
        reloaded = NativeProjectSession.load(self.path)
        self.assertNotEqual(reloaded.revision, s.revision)
        self.assertEqual(reloaded.snapshot(), changed)
        self.assertEqual(reloaded.native_project(), parse_native_project(changed))
        for name, digest in assets.items():
            self.assertEqual(hashlib.sha256((self.directory / "assets" / name).read_bytes()).hexdigest(), digest)
        self.assertFalse((self.directory / "licenses").exists())
        self.assert_no_temporary()

    def test_reads_commit_undo_redo_never_write(self):
        before = self.state()
        for _ in range(3):
            self.session.snapshot()
            self.session.native_project()
            _ = self.session.revision, self.session.path, self.session.dirty
        self.assertEqual(self.state(), before)
        with patch.object(native_session.os, "replace") as replace, \
                patch.object(native_session.tempfile, "NamedTemporaryFile") as temporary:
            self.change()
            self.session.undo()
            self.session.redo()
            replace.assert_not_called()
            temporary.assert_not_called()
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_stdlib_only_import_and_workflow_with_site_packages_disabled(self):
        script = (
            "import json, sys; from pathlib import Path; "
            "sys.path.insert(0, str(Path(sys.argv[1]) / 'src')); "
            "from studio.native_session import NativeProjectSession; "
            "s = NativeProjectSession.load(sys.argv[2]); "
            "r = s.snapshot(); r['actions'][0]['display_name'] = 'No Qt'; "
            "s.replace(r, base_revision=s.revision); s.undo(); s.redo(); s.save(); "
            "assert not any(m.startswith('PySide6') for m in sys.modules); "
            "assert not s.dirty; print('stdlib-only OK')"
        )
        result = subprocess.run([sys.executable, "-B", "-S", "-c", script, str(ROOT), str(self.path)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("stdlib-only OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
