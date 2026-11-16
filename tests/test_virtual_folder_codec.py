"""Extension roundtrip, adversarial JSON and atomic file/history ownership."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from studio.virtual_folders import Document, FolderError, PagingCapability, Reference
from studio.virtual_folders.codec import ExtensionStore, MAX_BYTES, decode, encode


class CodecTests(unittest.TestCase):
    def setUp(self):
        self.d = Document.create('project.test', 'plugin.test')
        self.d, self.remote = self.d.add_action(self.d.root_id, Reference('peer', 'action.offline'))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'test.vfolders.json'

    def decode(self, value):
        return decode(value, project_id=self.d.project_id, plugin_id=self.d.plugin_id)

    def test_roundtrip_preserves_all_identities_modes_and_offline_references(self):
        d = self.d.set_mode(self.d.root_id, 'auto', PagingCapability(1, 'Explicit test'))
        self.assertEqual(self.decode(encode(d)), d)
        self.assertEqual(self.decode(encode(d)).placement(self.remote).target.plugin_id, 'peer')

    def test_invalid_json_version_duplicate_keys_nonfinite_size_identity(self):
        data = json.loads(encode(self.d))
        for mutation in ({'version': 'future'}, {'project_id': 'other'}, {'plugin_id': 'other'},
                         {'extra': True}, {'folders': None}, {'root_id': False}):
            with self.subTest(mutation=mutation), self.assertRaises(FolderError):
                self.decode(json.dumps(dict(data, **mutation)))
        for invalid in ('{', '[]', 'null', '{"a":1,"a":2}', '{"a":NaN}', b'\xff', b' '*(MAX_BYTES+1)):
            with self.assertRaises(FolderError):
                self.decode(invalid)

    def test_invalid_nested_fields_missing_targets_owner_and_positions(self):
        data = json.loads(encode(self.d))
        for category, fields in (
            ('folders', {'owner': 'peer'}), ('folders', {'parent_id': 'missing'}),
            ('folders', {'mode': 'auto'}), ('folders', {'pages': []}),
            ('placements', {'page_id': 'missing'}), ('placements', {'position': True}),
            ('placements', {'target': {'plugin_id': 'UPPER', 'resource_id': 'id'}}),
            ('placements', {'unexpected': 'field'}),
        ):
            bad = json.loads(json.dumps(data))
            bad[category][0].update(fields)
            with self.subTest(category=category, fields=fields), self.assertRaises(FolderError):
                self.decode(json.dumps(bad))

    def test_invalid_unicode_and_malformed_dataclass_snapshots_fail_closed(self):
        data = json.loads(encode(self.d))
        data['folders'][0]['name'] = '\ud800'
        with self.assertRaises(FolderError):
            self.decode(json.dumps(data))
        for changes in ({'folders': (None,)}, {'placements': (None,)}):
            with self.assertRaises(FolderError):
                replace(self.d, **changes).validate()

    def test_decode_never_normalizes_duplicate_positions_or_ids(self):
        data = json.loads(encode(self.d))
        p = dict(data['placements'][0], id='placement.other')
        data['placements'].append(p)
        with self.assertRaises(FolderError):
            self.decode(json.dumps(data))
        data['placements'][-1]['id'] = data['placements'][0]['id']
        with self.assertRaises(FolderError):
            self.decode(json.dumps(data))

    def test_export_new_atomic_save_history_reload_and_native_file_untouched(self):
        source = ROOT / 'examples/project_logitech_native_v1.json'
        original = source.read_bytes()
        store = ExtensionStore(self.d)
        store.export(self.path)
        first = self.path.read_bytes()
        store.commit(self.d.rename_folder(self.d.root_id, 'Renamed'))
        self.assertTrue(store.dirty)
        self.assertEqual(self.path.read_bytes(), first)
        store.undo()
        self.assertEqual(store.document, self.d)
        self.assertFalse(store.dirty)
        store.redo()
        store.save()
        fresh = ExtensionStore.load(self.path, project_id='project.test', plugin_id='plugin.test')
        self.assertEqual(fresh.document, store.document)
        self.assertFalse(fresh.dirty)
        self.assertEqual(source.read_bytes(), original)
        self.assertFalse(list(self.path.parent.glob('.vfolders-*')))

    def test_export_existing_file_never_overwrites_and_preserves_store_target(self):
        self.path.write_bytes(b'foreign')
        store = ExtensionStore(self.d)
        with self.assertRaises(FolderError):
            store.export(self.path)
        self.assertEqual(self.path.read_bytes(), b'foreign')
        self.assertIsNone(store.path)
        self.assertFalse(list(self.path.parent.glob('.vfolders-*')))

    def test_atomic_export_race_existing_target_preserved(self):
        store = ExtensionStore(self.d)
        import os
        link = os.link
        def competing(source, target):
            Path(target).write_bytes(b'racer')
            link(source, target)
        with patch('studio.virtual_folders.codec.os.link', side_effect=competing):
            with self.assertRaises(FolderError):
                store.export(self.path)
        self.assertEqual(self.path.read_bytes(), b'racer')
        self.assertIsNone(store.path)

    def test_disk_conflict_deleted_changed_and_staging_race(self):
        for change in ('changed', 'deleted', 'staging'):
            with self.subTest(change=change):
                self.path.unlink(missing_ok=True)
                store = ExtensionStore(self.d)
                store.export(self.path)
                store.commit(self.d.rename_folder(self.d.root_id, 'Changed'))
                if change == 'changed':
                    self.path.write_bytes(b'external')
                elif change == 'deleted':
                    self.path.unlink()
                original_check = store._check_disk
                calls = []
                def check():
                    calls.append(1)
                    if change == 'staging' and len(calls) == 2:
                        self.path.write_bytes(b'external')
                    original_check()
                with patch.object(store, '_check_disk', side_effect=check), self.assertRaises(FolderError):
                    store.save()
                self.assertTrue(store.dirty)
                if self.path.exists():
                    self.assertEqual(self.path.read_bytes(), b'external')
                self.assertFalse(list(self.path.parent.glob('.vfolders-*')))

    def test_write_failure_retains_original_file_and_dirty_draft(self):
        store = ExtensionStore(self.d)
        store.export(self.path)
        original = self.path.read_bytes()
        store.commit(self.d.rename_folder(self.d.root_id, 'Changed'))
        with patch('studio.virtual_folders.codec.os.replace', side_effect=OSError('simulated')), self.assertRaises(FolderError):
            store.save()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertTrue(store.dirty)

    def test_extension_suffix_and_identity_guards_no_native_writer(self):
        store = ExtensionStore(self.d)
        with self.assertRaises(FolderError):
            store.export(self.path.parent / 'native.json')
        with self.assertRaises(FolderError):
            store.save()
        with self.assertRaises(FolderError):
            store.commit(replace(self.d, project_id='project.other'))
        self.assertFalse(store.can_undo)

    def test_bounded_history_noop_and_branch_clear_redo(self):
        store = ExtensionStore(self.d)
        store.commit(self.d)
        self.assertFalse(store.can_undo)
        for i in range(60):
            store.commit(store.document.rename_folder(store.document.root_id, str(i)))
        self.assertEqual(len(store._undo), 50)
        store.undo()
        self.assertTrue(store.can_redo)
        store.commit(store.document.rename_folder(store.document.root_id, 'Branch'))
        self.assertFalse(store.can_redo)


if __name__ == '__main__':
    unittest.main()
