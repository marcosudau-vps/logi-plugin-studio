"""Host-/Sessionverträge und temporäre native Projektdateien, echte Qt-Intents."""
import ast
import copy
import json
from pathlib import Path
from unittest.mock import patch
import unittest
from test_action_lifecycle_widget import ShellCase, ROOT, QTest, Qt, QMessageBox, QCloseEvent
from studio.native_session import NativeProjectSession, NativeSessionError, NativeRevisionConflict, NativeDiskConflict
from studio.action_inspector.lifecycle import starter_action


class LifecycleIntegrationTests(ShellCase):
    def test_v63_catalog_create_intent_to_guarded_create_draft(self):
        self.c.select_node('action','action.command')
        before=self.c.session.snapshot();revision=self.c.session.revision
        self.fill('common','display_name','Zu schützen')
        seen=self.decision('Abbrechen');self.click(self.w.catalog.new_action_button)
        self.assertEqual(seen,['Abbrechen'])
        self.assertEqual(self.c.selection,('action','action.command'))
        self.assertEqual(self.w.inspector.draft.snapshot()['display_name'],'Zu schützen')
        self.decision('Verwerfen');self.click(self.w.catalog.new_action_button)
        self.assertTrue(self.w.inspector.creating)
        self.assertEqual(self.c.session.snapshot(),before);self.assertEqual(self.c.session.revision,revision)

    def test_v64_create_apply_exactly_one_replace_and_selected_edit_mode(self):
        self.create('ActionEditorCommand')
        before=self.c.session.snapshot();session=self.c.session
        with patch.object(session,'replace',wraps=session.replace) as replace:
            self.click(self.w.inspector.apply_button);replace.assert_called_once()
        self.assertIs(self.c.session,session)
        self.assertEqual(self.c.selection,('action','action.created'))
        self.assertEqual(self.w.catalog.selected_key(),('action.created',None))
        self.assertEqual(self.w.inspector.draft.action_id,'action.created')
        self.assertFalse(self.w.inspector.creating or self.w.inspector.dirty)
        self.assertEqual(session.snapshot()['folders'],before['folders'])
        self.assertEqual(session.snapshot()['handlers'],before['handlers'])
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_v65_delete_intent_current_reference_check_before_dialog(self):
        self.c.select_node('action','action.editor')
        before=self.c.session.snapshot();revision=self.c.session.revision
        with patch.object(QMessageBox,'exec') as dialog, patch.object(self.c.session,'replace',wraps=self.c.session.replace) as replace:
            self.assertFalse(self.w.delete_selected());dialog.assert_not_called();replace.assert_not_called()
        self.assertEqual(self.c.session.snapshot(),before);self.assertEqual(self.c.session.revision,revision)
        self.assertIn('placement.editor',self.w.inspector.delete_info.text())

    def test_v66_confirmed_delete_one_replace_history_save_reload(self):
        before=self.commit_create();session=self.c.session
        self.decision('Aktion löschen')
        with patch.object(session,'replace',wraps=session.replace) as replace:
            self.click(self.w.inspector.delete_button);replace.assert_called_once()
        after=session.snapshot()
        self.assertEqual(after,json.loads(self.original))
        self.assertIsNone(self.c.selection);self.assertIsNone(self.w.inspector.draft)
        self.assertIsNone(self.w.catalog.item_for('action.created'))
        self.assertIsNone(self.w.catalog.offer_for('action.created'))
        self.assertEqual(self.path.read_bytes(),self.original)
        self.w.undo_action.trigger();self.assertEqual(session.snapshot(),before)
        self.w.redo_action.trigger();self.assertEqual(session.snapshot(),after)
        self.assertTrue(self.w.save_project());self.assertIs(self.c.session,session)
        self.assertEqual(session.path,self.path.resolve())
        self.assertEqual(NativeProjectSession.load(self.path).snapshot(),after)

    def test_v67_changed_signal_proactively_marks_edit_and_create_stale(self):
        for creating in (False,True):
            if creating:self.create()
            else:
                self.c.select_node('action','action.command');self.fill('common','display_name','Entwurf')
            draft=self.w.inspector.draft;before=draft.snapshot();base=draft.base_revision
            self.c.rename_action('action.editor','Fremder Commit '+str(creating),base_revision=self.c.session.revision)
            self.assertTrue(self.w.inspector.stale)
            self.assertTrue(self.w.inspector.stale_band.isVisible())
            self.assertFalse(self.w.inspector.apply_button.isEnabled())
            self.assertEqual(draft.snapshot(),before);self.assertEqual(draft.base_revision,base)
            self.assertIn('noch nicht übernommen',self.w.inspector.status.text())
            self.click(self.w.inspector.stay_button);self.assertEqual(draft.snapshot(),before)
            self.click(self.w.inspector.refresh_button)

    def test_v68_refresh_exact_id_current_revision_or_deleted_empty(self):
        self.c.select_node('action','action.command');self.fill('common','display_name','Alt')
        self.c.rename_action('action.command','Aktuell',base_revision=self.c.session.revision)
        self.click(self.w.inspector.refresh_button)
        self.assertFalse(self.w.inspector.stale)
        self.assertEqual(self.w.inspector.draft.snapshot()['display_name'],'Aktuell')
        self.assertEqual(self.w.inspector.draft.base_revision,self.c.session.revision)
        self.commit_create();self.fill('common','display_name','Entfernt')
        self.c.delete_action('action.created',base_revision=self.c.session.revision,project_token=self.c.project_token)
        self.assertTrue(self.w.inspector.stale)
        self.click(self.w.inspector.refresh_button)
        self.assertIsNone(self.w.inspector.draft)
        self.assertIn('existiert nicht mehr',self.w.inspector.status.text())

    def test_four_types_common_special_apply_history_save_fresh_load(self):
        for index,typ in enumerate(('PluginDynamicCommand','PluginMultistateDynamicCommand','PluginDynamicAdjustment','ActionEditorCommand')):
            with self.subTest(typ=typ):
                identity=f'action.created-{index}'
                before=self.c.session.snapshot();self.create(typ,identity)
                inspector=self.w.inspector
                if index==0:
                    self.click(inspector.sections['parameters'].add_button)
                    inspector.sections['parameters'].forms[0].fields['display_name'].input.setText('Variante')
                elif index==1:
                    inspector.sections['states'].forms[0].fields['description'].input.setPlainText('Neuer Zustand')
                elif index==2:
                    field=inspector.sections['adjustment'].fields['format']
                    field.mode.setCurrentIndex(2);field.input.setText('{0}%')
                else:
                    inspector.sections['editor_controls'].forms[0].fields['label'].input.setText('Neues Feld')
                self.assertTrue(inspector.apply_button.isEnabled())
                self.click(inspector.apply_button);after=self.c.session.snapshot()
                self.assertEqual(after['folders'],before['folders'])
                self.assertEqual(after['handlers'],before['handlers'])
                self.assertIsNotNone(self.w.catalog.item_for(identity))
                self.w.undo_action.trigger();self.assertEqual(self.c.session.snapshot(),before)
                self.w.redo_action.trigger();self.assertEqual(self.c.session.snapshot(),after)
                self.assertTrue(self.w.save_project())
                self.assertEqual(NativeProjectSession.load(self.path).snapshot(),after)

    def test_end_to_end_create_edit_apply_save_delete_undo_redo_exact_history(self):
        original=self.c.session.snapshot();session=self.c.session
        with patch.object(session,'replace',wraps=session.replace) as replace:
            created=self.commit_create()
            self.fill('common','display_name','Nach Erstellung bearbeitet')
            self.click(self.w.inspector.apply_button);edited=session.snapshot()
            self.assertTrue(self.w.save_project())
            self.decision('Aktion löschen');self.click(self.w.inspector.delete_button)
            self.assertEqual(replace.call_count,3) # Create, Edit und Delete je ein Intent.
        deleted=session.snapshot();self.assertEqual(deleted,original)
        self.w.undo_action.trigger();self.assertEqual(session.snapshot(),edited)
        self.w.undo_action.trigger();self.assertEqual(session.snapshot(),created)
        self.w.undo_action.trigger();self.assertEqual(session.snapshot(),original);self.assertFalse(session.can_undo)
        self.w.redo_action.trigger();self.w.redo_action.trigger();self.assertEqual(session.snapshot(),edited)
        self.w.redo_action.trigger();self.assertEqual(session.snapshot(),deleted)
        self.assertIs(self.c.session,session);self.assertTrue(self.w.save_project())
        self.assertEqual(NativeProjectSession.load(self.path).snapshot(),deleted)
        self.assertEqual((ROOT/'examples/project_logitech_native_v1.json').read_bytes(),self.original)

    def test_create_delete_only_two_transitions_no_autosave(self):
        session=self.c.session;before=session.snapshot()
        with patch.object(session,'replace',wraps=session.replace) as replace, patch.object(session,'save',wraps=session.save) as save:
            self.commit_create();self.decision('Aktion löschen');self.click(self.w.inspector.delete_button)
            self.assertEqual(replace.call_count,2);save.assert_not_called()
        self.assertEqual(len(session._undo),2);self.assertEqual(session.snapshot(),before)
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_host_stale_project_revision_missing_id_no_snapshot_history_disk_diff(self):
        action=starter_action('PluginDynamicCommand','action.unique','Neu','handler.main')
        session=self.c.session;before=session.snapshot();revision=session.revision
        for operation in (lambda:self.c.apply_action_create(action,base_revision='stale',project_token=self.c.project_token),
                          lambda:self.c.apply_action_create(action,base_revision=revision,project_token='other'),
                          lambda:self.c.delete_action('action.command',base_revision=revision,project_token='other'),
                          lambda:self.c.delete_action('missing',base_revision=revision,project_token=self.c.project_token)):
            with self.assertRaises(NativeSessionError):operation()
            self.assertEqual(session.snapshot(),before);self.assertEqual(session.revision,revision)
            self.assertFalse(session.can_undo or session.can_redo);self.assertEqual(self.path.read_bytes(),self.original)

    def test_host_invalid_create_and_parser_failure_no_replace(self):
        session=self.c.session;revision=session.revision;before=session.snapshot()
        action=starter_action('PluginDynamicCommand','action.unique','Neu','handler.main')
        for mutation in ({'id':'action.command'},{'id':'Invalid'},{'handler':'missing'},
                         {'sdk_type':'Folder'},{'display_name':''}):
            with patch.object(session,'replace',wraps=session.replace) as replace:
                with self.assertRaises(NativeSessionError):
                    self.c.apply_action_create(dict(action,**mutation),base_revision=revision,project_token=self.c.project_token)
                replace.assert_not_called()
        invalid=copy.deepcopy(before);invalid['folders'][0]['entries'][0]['action']='missing'
        with patch.object(session,'snapshot',return_value=invalid):
            with self.assertRaises(NativeSessionError):
                self.c.apply_action_create(action,base_revision=revision,project_token=self.c.project_token)
        self.assertEqual(session.snapshot(),before);self.assertEqual(session.revision,revision)
        self.assertFalse(session.can_undo);self.assertEqual(self.path.read_bytes(),self.original)

    def test_disk_conflict_blocks_both_lifecycle_commits(self):
        self.commit_create();session=self.c.session;before=session.snapshot();revision=session.revision
        external=self.path.read_bytes()+b'\n';self.path.write_bytes(external)
        action=starter_action('PluginDynamicCommand','action.other','Neu','handler.main')
        for operation in (lambda:self.c.apply_action_create(action,base_revision=revision,project_token=self.c.project_token),
                          lambda:self.c.delete_action('action.created',base_revision=revision,project_token=self.c.project_token)):
            with patch.object(session,'replace',wraps=session.replace) as replace:
                with self.assertRaises(NativeDiskConflict):operation()
                replace.assert_not_called()
            self.assertEqual(session.snapshot(),before);self.assertEqual(session.revision,revision)
            self.assertEqual(self.path.read_bytes(),external)

    def test_delete_modal_concurrent_rename_or_project_change_fail_closed(self):
        self.commit_create();before=self.c.session.snapshot()
        def concurrent(dialog):
            self.c.rename_action('action.created','Neuer Name',base_revision=self.c.session.revision)
        self.decision('Aktion löschen',concurrent);self.click(self.w.inspector.delete_button)
        self.assertTrue(self.c._exists('action','action.created'))
        self.assertEqual(len(self.c.session._undo),2) # Create + fremdes Rename, kein Delete.
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_same_display_name_never_changes_delete_identity(self):
        self.commit_create();self.c.rename_action('action.command','Erstellte Aktion',base_revision=self.c.session.revision)
        self.click(self.w.inspector.refresh_button)
        self.assertEqual(self.c.selection,('action','action.created'))
        self.decision('Aktion löschen');self.click(self.w.inspector.delete_button)
        self.assertTrue(self.c._exists('action','action.command'))
        self.assertFalse(self.c._exists('action','action.created'))

    def test_create_edit_guards_all_decisions_for_selection_open_reload_close_save_history_create_delete(self):
        operations=('selection','open','reload','close','save','undo','redo','create','delete')
        for creating in (False,True):
            for operation in operations:
                for decision in ('Abbrechen','Verwerfen','Übernehmen'):
                    with self.subTest(creating=creating,operation=operation,decision=decision):
                        self.w.inspector.accept_applied();self.path.write_bytes(self.original)
                        self.c.open_project(self.path,discard=True)
                        self.c.select_node('action','action.command')
                        if creating:self.create()
                        else:self.fill('common','display_name','Geschützt')
                        draft=self.w.inspector.draft;values=draft.snapshot();revision=self.c.session.revision
                        token=self.c.project_token;selection=self.c.selection
                        self.decision(decision)
                        # Nach Draftentscheidung nur projektspezifischen Save/Discard-Dialog beantworten.
                        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Save):
                            if operation=='selection':self.c.select_node('action','action.editor')
                            elif operation=='open':self.w.open_project(self.path)
                            elif operation=='reload':self.w.reload_project()
                            elif operation=='close':self.w.closeEvent(QCloseEvent())
                            elif operation=='save':self.w.save_project()
                            elif operation=='undo':self.w.undo_project()
                            elif operation=='redo':self.w.redo_project()
                            elif operation=='create':self.click(self.w.catalog.new_action_button)
                            else:self.w.delete_selected() # Referenziertes Ziel: kein zweiter Bestätigungsdialog.
                        if decision=='Abbrechen':
                            self.assertEqual(self.c.session.revision,revision)
                            self.assertEqual(self.c.project_token,token);self.assertEqual(self.c.selection,selection)
                            self.assertIs(self.w.inspector.draft,draft);self.assertEqual(draft.snapshot(),values)
                            self.assertEqual(self.path.read_bytes(),self.original)

    def test_failed_open_retains_create_and_edit_draft_even_after_discard_choice(self):
        for creating in (False,True):
            if creating:self.create()
            else:
                self.c.select_node('action','action.command');self.fill('common','display_name','Bewahren')
            draft=self.w.inspector.draft;values=draft.snapshot();token=self.c.project_token
            self.decision('Verwerfen')
            self.assertFalse(self.w.open_project(self.path.parent/'missing.json'))
            self.assertIs(self.w.inspector.draft,draft);self.assertEqual(draft.snapshot(),values)
            self.assertEqual(self.c.project_token,token);self.assertFalse(self.c.session.dirty)
            self.click(self.w.inspector.discard_button)

    def test_project_switch_during_delete_confirmation_does_not_delete_same_id(self):
        self.commit_create();other=self.path.parent/'other.json'
        other.write_text(json.dumps(self.c.session.snapshot()),encoding='utf-8')
        def switch(dialog):
            self.c.open_project(other,discard=True)
        self.decision('Aktion löschen',switch)
        self.click(self.w.inspector.delete_button)
        self.assertTrue(self.c._exists('action','action.created'))
        self.assertFalse(self.c.session.can_undo)
        self.assertEqual(self.c.session.path,other.resolve())
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_lost_id_during_confirmation_and_old_offer_fail_closed(self):
        self.commit_create();offer=self.w.catalog.offer_for('action.created')
        def remove(dialog):
            self.c.delete_action('action.created',base_revision=self.c.session.revision,project_token=self.c.project_token)
        self.decision('Aktion löschen',remove);self.click(self.w.inspector.delete_button)
        self.assertEqual(len(self.c.session._undo),2) # Create und paralleles Delete.
        self.assertFalse(self.c._exists('action','action.created'))
        before=self.c.selection;self.c.select_offer(offer)
        self.assertEqual(self.c.selection,before)
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_invalid_state_toggle_editor_create_and_handler_keep_draft(self):
        for typ in ('PluginMultistateDynamicCommand','ActionEditorCommand'):
            self.create(typ)
            rows=self.w.inspector.sections['states' if typ.startswith('Plugin') else 'editor_controls']
            if typ.startswith('Plugin'):
                rows.add_row() # toggle mit drei Zuständen ist parserungültig.
            else:
                rows.forms[0].fields['name'].input.clear()
            self.assertFalse(self.w.inspector.apply_button.isEnabled())
            before=self.c.session.snapshot();revision=self.c.session.revision
            values=self.w.inspector.draft.snapshot()
            self.click(self.w.inspector.apply_button)
            self.assertEqual(self.c.session.snapshot(),before);self.assertEqual(self.c.session.revision,revision)
            self.assertEqual(self.w.inspector.draft.snapshot(),values)
            self.click(self.w.inspector.discard_button)
        self.create();self.w.inspector.draft.set_field('handler','handler.missing');self.w.inspector._validate()
        self.assertFalse(self.w.inspector.apply_button.isEnabled())
        self.assertIn('/handler',self.w.inspector.errors.text())
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_delete_dirty_target_apply_discard_cancel_before_confirmation(self):
        for decision in ('Abbrechen','Verwerfen','Übernehmen'):
            self.w.inspector.accept_applied();self.path.write_bytes(self.original)
            self.c.open_project(self.path,discard=True);self.commit_create()
            self.fill('common','display_name','Geändert')
            values=self.w.inspector.draft.snapshot();revision=self.c.session.revision
            if decision=='Abbrechen':
                self.decision(decision);self.assertFalse(self.w.delete_selected())
                self.assertEqual(self.w.inspector.draft.snapshot(),values);self.assertEqual(self.c.session.revision,revision)
            else:
                # Folgeantwort erst nach dem ersten Draftdialog einplanen.
                from PySide6.QtCore import QTimer
                self.decision(decision,lambda dialog:QTimer.singleShot(60,lambda:self.decision('Aktion löschen')))
                self.assertTrue(self.w.delete_selected())
                self.assertFalse(self.c._exists('action','action.created'))
                self.w.undo_action.trigger()
                expected='Geändert' if decision=='Übernehmen' else 'Erstellte Aktion'
                self.assertEqual(self.c.selected_action(),None)
                record=next(a for a in self.c.session.snapshot()['actions'] if a['id']=='action.created')
                self.assertEqual(record['display_name'],expected)


if __name__ == '__main__':
    unittest.main()
