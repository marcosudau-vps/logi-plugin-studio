"""Offline source probes, not a claim of live dynamic membership support."""
import copy
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from adapters.logitech.native import parse_native_project, runtime_projection
from adapters.logitech.product import _folder
from studio.virtual_folders import Document, FolderError, Reference
from studio.virtual_folders.sample import demo_document


class ProjectionProbeTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads((ROOT / 'examples/project_logitech_native_v1.json').read_text(encoding='utf-8'))
        self.plan = SimpleNamespace(namespace='Probe', plugin_display_name='Folder probe')

    def test_current_virtual_page_local_command_ids_in_existing_create_run_dispatch_chain(self):
        d = demo_document(self.raw, 'project.probe')
        b = next(f for f in d.folders if f.name == 'B')
        command = next(p for p in d.entries(b.id, b.pages[0].id) if p.kind == 'action')
        # Feed ONLY a local command placement to the existing source generator.
        # A production integration would also need Visuals registration, dynamic
        # membership notifications and type/parameter-specific SDK contracts.
        view = {'id': b.id, 'placements': [{'id': command.id, 'component': command.target.resource_id, 'position': 0}]}
        source = _folder(self.plan, view, navigation='None', device_navigation={'Loupedeck70': 'ButtonArea'})
        self.assertIn(command.id, source)
        self.assertIn('this.CreateCommandName(p)', source)
        self.assertIn('public override void RunCommand(String parameter)', source)
        self.assertIn('if (!Placements.Contains(parameter))', source)
        self.assertIn('Bridge.Dispatch(Visuals.Placement(parameter).GetProperty("component").GetString(), parameter)', source)
        self.assertIn('PluginDynamicFolderNavigation.None', source)
        self.assertIn('DeviceType.Loupedeck70 => PluginDynamicFolderNavigation.ButtonArea', source)
        self.assertIn('private static readonly String[] Placements', source)
        self.assertIn('CommandImageChanged', source)
        self.assertNotIn('ButtonActionNamesChanged', source)
        self.assertNotIn('OpenFolder', source)

    def test_native_multiple_real_folders_remain_valid_and_projected_separately(self):
        raw = copy.deepcopy(self.raw)
        second = copy.deepcopy(raw['folders'][0])
        second['id'] = 'folder.second'
        for p in second['entries']:
            p['id'] += '.second'
        raw['folders'].append(second)
        native = parse_native_project(raw)
        self.assertEqual(len(native.folders), 2)
        projected = runtime_projection(raw)
        self.assertEqual(len(projected['views']), 2)
        for view, folder in zip(projected['views'], native.folders):
            source = _folder(self.plan, view, navigation=folder.navigation)
            for placement, entry in zip(view['placements'], folder.entries):
                self.assertEqual(placement['component'], entry.action)
                self.assertIn(entry.id, source)

    def test_native_target_validation_rejects_missing_local_accepts_offline_foreign(self):
        d = Document.create('project.test', self.raw['plugin']['id'])
        d, _ = d.add_action(d.root_id, Reference('peer', 'action.missing'))
        d.validate_native(self.raw)
        bad, _ = d.add_action(d.root_id, Reference(d.plugin_id, 'action.missing'))
        with self.assertRaises(FolderError):
            bad.validate_native(self.raw)

    def test_core_import_and_codec_have_no_qt_dependency(self):
        code = 'import sys; sys.path.insert(0, "src"); import studio.virtual_folders; import studio.virtual_folders.codec; import studio.virtual_folders.providers; assert not any(n.startswith("PySide6") for n in sys.modules)'
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
