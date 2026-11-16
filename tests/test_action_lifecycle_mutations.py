"""Echte SDK-Parserinvarianten; Lifecycle ohne Qt, IO oder Sessionmutation."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from adapters.logitech.native import ACTION_TYPES, parse_native_project
from core.ids import is_valid_id
from studio.action_inspector.lifecycle import (
    CreateDraft, check_delete, propose_create, propose_delete, starter_action, suggest_id)
from studio.action_inspector.draft import DraftError
from studio.native_session import NativeProjectSession


class MutationTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads((ROOT / 'examples/project_logitech_native_v1.json').read_text(encoding='utf-8'))

    def action(self, typ='PluginDynamicCommand'):
        return starter_action(typ, 'action.neu', 'Neue Aktion', 'handler.main')

    def test_four_starters_parse_unplaced_defensive_and_preserve_siblings(self):
        before = copy.deepcopy(self.raw)
        for typ in ACTION_TYPES:
            with self.subTest(typ=typ):
                action = self.action(typ)
                result = propose_create(self.raw, action)
                self.assertEqual(len(parse_native_project(result).actions), 5)
                self.assertTrue(is_valid_id(action['id']))
                self.assertEqual(result['actions'][:-1], before['actions'])
                for key in set(before) - {'actions'}:
                    self.assertEqual(result[key], before[key])
                action['display_name'] = 'Extern'
                self.assertEqual(result['actions'][-1]['display_name'], 'Neue Aktion')
                self.assertEqual(self.raw, before)

    def test_explicit_defaults_states_controls_adjustment(self):
        self.assertEqual(set(self.action()), {'id', 'sdk_type', 'display_name', 'handler'})
        multi = self.action('PluginMultistateDynamicCommand')
        self.assertEqual([s['index'] for s in multi['states']], [0, 1])
        self.assertEqual(len({s['name'] for s in multi['states']}), 2)
        self.assertEqual(multi['state_change'], 'toggle')
        self.assertEqual(self.action('PluginDynamicAdjustment')['adjustment'], {})
        self.assertEqual(self.action('ActionEditorCommand')['editor_controls'][0]['type'], 'textbox')

    def test_id_collision_and_rule_reject_without_input_change(self):
        for identity in ('action.command', '', 'Action.New', 'action..new', '9new', 'action new'):
            action = dict(self.action(), id=identity)
            before = copy.deepcopy(self.raw)
            with self.assertRaisesRegex(ValueError, '/id'):
                propose_create(self.raw, action)
            self.assertEqual(self.raw, before)

    def test_handler_name_type_and_unknown_fields_rejected(self):
        for patch in ({'handler':'handler.missing'}, {'handler':''}, {'display_name':''},
                      {'display_name':'  '}, {'sdk_type':'PluginDynamicFolder'}, {'invented':True}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                propose_create(self.raw, dict(self.action(), **patch))
        with self.assertRaises(ValueError):
            self.action('Unsupported')

    def test_state_toggle_and_control_schema_rejected(self):
        multi = self.action('PluginMultistateDynamicCommand')
        mutations = [dict(multi, states=[]), dict(multi, states=multi['states']*2),
                     dict(multi, state_change='invalid')]
        three = copy.deepcopy(multi)
        three['states'].append(dict(index=2, name='third', display_name='Dritter', description=''))
        mutations.append(three)
        editor = self.action('ActionEditorCommand')
        mutations += [dict(editor, editor_controls=[]), dict(editor, editor_controls=[dict(type='slider',name='x',label='X')])]
        for action in mutations:
            with self.subTest(action=action), self.assertRaises(ValueError):
                propose_create(self.raw, action)

    def test_nan_and_asset_paths_rejected(self):
        for action in (dict(self.action('PluginDynamicAdjustment'), adjustment={'minimum':float('nan')}),
                       dict(self.action(), icon='C:/private.png'), dict(self.action(), icon='../x.png')):
            with self.assertRaises(ValueError):
                propose_create(self.raw, action)

    def test_create_draft_is_separate_and_reports_id_field(self):
        draft = CreateDraft(self.raw, 'revision', 'project')
        self.assertTrue(draft.dirty)
        self.assertEqual(draft.project_token, 'project')
        self.assertEqual(len(self.raw['actions']), 4)
        draft.set_field('id', 'action.command')
        self.assertEqual(draft.diagnostics()[0].path, '/id')
        draft.set_field('id', 'action.unique')
        draft.set_field('description', 'Erhalten')
        for typ in ACTION_TYPES:
            draft.change_type(typ)
            self.assertEqual(draft.proposed_action()['description'], 'Erhalten')
        draft.snapshot()['display_name'] = 'Extern'
        self.assertEqual(draft.snapshot()['display_name'], 'Neue Aktion')
        self.assertEqual(len(self.raw['actions']), 4)

    def test_suggestion_is_valid_unique_and_never_silently_committed(self):
        first = suggest_id(self.raw, 'ÄÖ Hallo Welt')
        self.assertTrue(is_valid_id(first))
        self.raw = propose_create(self.raw, dict(self.action(), id=first))
        self.assertNotEqual(suggest_id(self.raw, 'ÄÖ Hallo Welt'), first)
        with self.assertRaises(ValueError):
            propose_create(self.raw, dict(self.action(), id=first))

    def test_every_original_action_reference_protected_with_placement_ids(self):
        for action in self.raw['actions']:
            check = check_delete(self.raw, action['id'])
            self.assertFalse(check.allowed)
            self.assertEqual(len(check.references), 1)
            self.assertEqual(check.references[0][0], 'folder.main')
            self.assertIn(check.references[0][1], check.reason)
            with self.assertRaisesRegex(ValueError, 'Folder-Referenz'):
                propose_delete(self.raw, action['id'])

    def test_delete_unplaced_restores_exact_project_handler_retained(self):
        created = propose_create(self.raw, self.action())
        self.assertTrue(check_delete(created, 'action.neu').allowed)
        self.assertEqual(propose_delete(created, 'action.neu'), self.raw)
        self.assertEqual(len(created['actions']), 5)

    def test_last_action_guard_and_normative_parser_minimum(self):
        single = copy.deepcopy(self.raw)
        single['actions'] = [self.action()]
        single['folders'] = []
        parse_native_project(single)
        with self.assertRaisesRegex(ValueError, 'letzte Action'):
            propose_delete(single, 'action.neu')
        single['actions'] = []
        with self.assertRaisesRegex(ValueError, 'non-empty'):
            parse_native_project(single)

    def test_missing_identity_and_invalid_source_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'nicht mehr vorhanden'):
            propose_delete(self.raw, 'action.missing')
        invalid = copy.deepcopy(self.raw)
        invalid['folders'][0]['entries'][0]['action'] = 'action.missing'
        for operation in (lambda: propose_create(invalid, self.action()),
                          lambda: propose_delete(invalid, 'action.editor')):
            with self.assertRaisesRegex(ValueError, 'unknown action'):
                operation()

    def test_rejections_do_not_change_session_history_or_snapshot(self):
        session = NativeProjectSession.from_raw(self.raw)
        revision = session.revision
        with self.assertRaises(ValueError):
            propose_delete(session.snapshot(), 'action.command')
        with self.assertRaises(ValueError):
            propose_create(session.snapshot(), dict(self.action(), id='action.command'))
        self.assertEqual(session.snapshot(), self.raw)
        self.assertEqual(session.revision, revision)
        self.assertFalse(session.can_undo or session.can_redo or session.dirty)


if __name__ == '__main__':
    unittest.main()
