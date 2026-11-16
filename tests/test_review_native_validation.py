"""Review R2: native editor validation must agree with runtime projection."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from adapters.logitech.native import NativeProjectError, parse_native_project, runtime_projection
from core.registry import load_manifests
from runtime.plan import compile_plan
from studio.native_session import NativeProjectSession, NativeSessionError
from studio.action_inspector.lifecycle import propose_create, starter_action

class ReviewNativeValidationTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads((ROOT/'examples/project_logitech_native_v1.json').read_text(encoding='utf-8'))
    def test_action_handler_collision_has_data_path(self):
        action = starter_action('PluginDynamicCommand', 'handler.main', 'Collision', 'handler.main')
        with self.assertRaisesRegex(ValueError, '/actions/4/id.*collides'):
            propose_create(self.raw, action)
    def test_session_rejects_collision_without_mutating_revision_or_history(self):
        session=NativeProjectSession.from_raw(self.raw); rev=session.revision
        proposed=copy.deepcopy(self.raw); proposed['actions'].append(starter_action('PluginDynamicCommand','handler.main','Collision','handler.main'))
        with self.assertRaisesRegex(NativeSessionError, '/actions/4/id'):
            session.replace(proposed,base_revision=rev)
        self.assertEqual(session.snapshot(),self.raw); self.assertEqual(session.revision,rev)
        self.assertFalse(session.dirty); self.assertFalse(session.can_undo)
    def test_duplicate_position_rejected_with_both_paths(self):
        self.raw['folders'][0]['entries'][1]['position']=0
        with self.assertRaisesRegex(NativeProjectError, '/folders/0/entries/1/position.*entries/0'):
            parse_native_project(self.raw)
        with self.assertRaises(NativeSessionError): NativeProjectSession.from_raw(self.raw)
    def test_position_scope_is_per_folder_and_valid_projection_remains_valid(self):
        folder=copy.deepcopy(self.raw['folders'][0]); folder['id']='folder.second'
        for entry in folder['entries']: entry['id'] += '.second'
        self.raw['folders'].append(folder)
        parse_native_project(self.raw)
        registry,issues=load_manifests(ROOT/'component_types')
        plan,issues=compile_plan(runtime_projection(self.raw),registry)
        self.assertIsNotNone(plan,issues)
    def test_load_rejects_bad_file_without_touching_bytes(self):
        self.raw['folders'][0]['entries'][1]['position']=0
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.json'; data=json.dumps(self.raw).encode(); p.write_bytes(data)
            with self.assertRaises(NativeSessionError): NativeProjectSession.load(p)
            self.assertEqual(p.read_bytes(),data)
