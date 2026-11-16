"""OBS-INSP-001/002: Datenverlustfreiheit, zeitnahe Warnung und zentrale Hilfe."""
import ast
import json
import unittest
from unittest.mock import patch
from test_action_lifecycle_widget import ShellCase, ROOT, Qt, QTest, QMessageBox
from PySide6.QtWidgets import QWidget, QPushButton
from studio.action_inspector.widget import CONTROL_TYPES, RowsEditor
from studio.context_help import HelpRegistry
from studio.native_shell.help_bindings import register_topics


class InspectorUXTests(ShellCase):
    def test_all_groups_are_foldable_and_rows_have_compact_summaries(self):
        for identity,expected in (('action.command','parameters'),('action.multistate','states'),
                                  ('action.adjustment','adjustment'),('action.editor','editor_controls')):
            self.c.select_node('action',identity);self.w.open_inspector()
            self.assertIn(expected,self.w.inspector.sections)
            for key,section in self.w.inspector.sections.items():
                self.assertTrue(section.toggle.isCheckable(),key)
                self.assertTrue(section.toggle.accessibleName())
                self.assertEqual(section.toggle.property('inspectorTopic'),'inspector.fold_sections')
                if isinstance(section,RowsEditor):
                    for index,form in enumerate(section.forms):
                        self.assertIn(str(index+1),form.toggle.text())
                        self.assertIn(section.rows[index]['name'],form.toggle.text())
                        self.assertFalse(form.toggle.isChecked())
                        if key=='states':self.assertIn('State '+str(index),form.toggle.text())
                        if key=='editor_controls':self.assertIn(section.rows[index]['type'],form.toggle.text())

    def test_collapse_resize_scroll_focus_preserve_invalid_values_and_formatting(self):
        self.c.select_node('action','action.adjustment');self.w.open_inspector()
        section=self.w.inspector.sections['adjustment']
        field=section.fields['default'].input
        for value in ('050.000','not a number'):
            field.setText(value);snapshot=self.w.inspector.draft.snapshot();base=self.w.inspector.draft.base_revision
            revision=self.c.session.revision
            with patch.object(self.c.session,'replace',wraps=self.c.session.replace) as replace:
                for width in (980,1400,1050):
                    self.click(section.toggle);self.w.resize(width,790)
                    self.w.inspector.scroll.verticalScrollBar().setValue(0)
                    self.w.catalog.search_edit.setFocus();self.app.processEvents()
                    self.click(section.toggle)
                    self.assertEqual(field.text(),value)
                    self.assertEqual(self.w.inspector.draft.snapshot(),snapshot)
                replace.assert_not_called()
            self.assertEqual(self.w.inspector.draft.base_revision,base)
            self.assertEqual(self.c.session.revision,revision)

    def test_invalid_rows_collapse_reopen_preserve_every_input_and_identity(self):
        self.create('ActionEditorCommand')
        rows=self.w.inspector.sections['editor_controls'];form=rows.forms[0]
        form.fields['name'].input.clear()
        self.assertFalse(self.w.inspector.apply_button.isEnabled())
        self.assertTrue(rows.toggle.isChecked());self.assertTrue(form.toggle.isChecked())
        before=self.w.inspector.draft.snapshot();revision=self.c.session.revision
        for _ in range(3):
            self.click(form.toggle);self.click(rows.toggle);self.click(rows.toggle);self.click(form.toggle)
            self.assertIs(rows.forms[0],form)
            self.assertEqual(form.fields['name'].input.text(),'')
            self.assertEqual(self.w.inspector.draft.snapshot(),before)
        self.assertEqual(self.c.session.revision,revision)

    def test_duplicate_symbol_rows_not_lost_by_collapsing(self):
        self.c.select_node('action','action.command');self.w.open_inspector()
        rows=self.w.inspector.sections['parameter_symbols'];rows.add_row();rows.add_row()
        rows.forms[0].fields['symbol'].input.setText('assets/a.svg')
        before=[dict(form.raw) for form in rows.forms]
        for form in rows.forms:
            self.click(form.toggle);self.click(form.toggle)
        self.click(rows.toggle);self.click(rows.toggle)
        self.assertEqual([form.raw for form in rows.forms],before)
        self.assertFalse(self.w.inspector.apply_button.isEnabled())
        self.assertTrue(self.w.inspector.dirty)

    def test_all_seven_controls_filter_add_remove_reorder_and_optional_modes(self):
        self.create('ActionEditorCommand');rows=self.w.inspector.sections['editor_controls']
        for typ in CONTROL_TYPES:
            with patch.object(QMessageBox,'warning',return_value=QMessageBox.StandardButton.Yes):
                rows.forms[0].fields['type'].input.setCurrentText(typ)
            rows.set_expanded(True);rows.forms[0].set_expanded(True)
            self.assertIn(typ,rows.forms[0].toggle.text())
            if typ=='file_selector':
                filters=rows.forms[0].filters_editor
                self.click(filters.add_button)
                filters.forms[0].fields['pattern'].input.setText('*.svg')
                self.click(filters.toggle);self.click(filters.toggle)
                self.assertEqual(rows.rows[0]['filters'][0]['pattern'],'*.svg')
            self.assertFalse(self.w.inspector.draft.diagnostics(),typ)
        self.click(rows.add_button);rows.move_or_remove(1,-1);rows.move_or_remove(0,0)
        self.assertEqual(len(rows.rows),1)
        field=self.w.inspector.sections['assets'].fields['icon'];field.mode.setCurrentIndex(1)
        self.assertIsNone(self.w.inspector.draft.snapshot()['icon'])
        field.mode.setCurrentIndex(0);self.assertNotIn('icon',self.w.inspector.draft.snapshot())

    def test_direct_session_commit_timer_warns_before_apply_and_save_no_rebase(self):
        self.create();before=self.w.inspector.draft.snapshot();base=self.w.inspector.draft.base_revision
        proposed=self.c.session.snapshot();proposed['actions'][1]['display_name']='Parallel'
        self.c.session.replace(proposed,base_revision=self.c.session.revision)
        for _ in range(30):
            if self.w.inspector.stale:
                break
            QTest.qWait(50)
        self.assertTrue(self.w.inspector.stale)
        self.assertFalse(self.w.inspector.apply_button.isEnabled())
        self.assertEqual(self.w.inspector.draft.snapshot(),before)
        self.decision('Übernehmen');self.assertFalse(self.w.save_project())
        self.assertEqual(self.w.inspector.draft.base_revision,base)
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_save_without_revision_change_does_not_mark_stale_or_rebuild(self):
        self.c.select_node('action','action.command');self.w.open_inspector()
        draft=self.w.inspector.draft;section=self.w.inspector.sections['parameters']
        section.set_expanded(True)
        self.c.save();QTest.qWait(400)
        self.assertFalse(self.w.inspector.stale)
        self.assertIs(self.w.inspector.draft,draft)
        self.assertIs(self.w.inspector.sections['parameters'],section)
        self.assertTrue(section.toggle.isChecked())

    def test_external_disk_conflict_proactive_and_cancelled_switch_retains_warning(self):
        self.create();draft=self.w.inspector.draft;values=draft.snapshot();base=draft.base_revision
        self.path.write_bytes(self.original+b'\n');QTest.qWait(450)
        self.assertTrue(self.w.inspector.stale)
        self.assertIn('extern verändert',self.w.inspector.stale_label.text())
        self.decision('Abbrechen');self.assertFalse(self.w.open_project(self.path))
        self.assertIs(self.w.inspector.draft,draft);self.assertEqual(draft.snapshot(),values)
        self.assertEqual(draft.base_revision,base);self.assertTrue(self.w.inspector.stale)

    def test_undo_redo_external_host_warns_and_project_token_mismatch_preserves_input(self):
        self.c.rename_action('action.editor','History',base_revision=self.c.session.revision)
        self.create();draft=self.w.inspector.draft;values=draft.snapshot()
        self.c.undo();self.assertTrue(self.w.inspector.stale)
        self.assertEqual(draft.snapshot(),values)
        self.c.redo();self.assertTrue(self.w.inspector.stale)
        self.w.inspector.observe_context(draft.base_revision,'other-project')
        self.assertTrue(self.w.inspector.stale);self.assertEqual(draft.snapshot(),values)

    def test_v69_new_controls_f1_focus_pin_related_and_registry_owner(self):
        self.create()
        targets=[(self.w.catalog.new_action_button,'inspector.create'),
                 (self.w.inspector.sections['identity'].fields['id'].input,'inspector.create_id'),
                 (self.w.inspector.sections['identity'].fields['sdk_type'].input,'inspector.create_type'),
                 (self.w.inspector.sections['handler'].fields['handler'].input,'inspector.handler'),
                 (self.w.inspector.sections['common'].toggle,'inspector.fold_sections')]
        for target,topic in targets:
            self.w.tabs.setCurrentWidget(self.w.inspector)
            self.w.inspector.sections['handler'].set_expanded(True)
            self.w.inspector.scroll.ensureWidgetVisible(target)
            target.setFocus();self.app.processEvents()
            self.assertEqual(self.w.help_bindings.context_for(target).topic_id,topic)
            self.c.help.set_pinned(True);QTest.keyClick(target,Qt.Key.Key_F1)
            self.assertEqual(self.c.help.current().resolved_topic_id,topic)
            self.assertEqual(self.c.help.current().facts,())
            self.c.help.set_pinned(False)
        self.c.rename_action('action.editor','Parallel',base_revision=self.c.session.revision)
        for target,topic in ((self.w.inspector.stay_button,'inspector.stale'),(self.w.inspector.refresh_button,'inspector.refresh')):
            self.w.tabs.setCurrentWidget(self.w.inspector);target.setFocus();self.app.processEvents()
            QTest.keyClick(target,Qt.Key.Key_F1)
            self.assertEqual(self.c.help.current().resolved_topic_id,topic)
        self.c.related_help('inspector.delete')
        self.w.help_widget.findChild(QPushButton,'helpRelated.inspector.delete_references').click()
        self.assertEqual(self.c.help.current().resolved_topic_id,'inspector.delete_references')
        registry=HelpRegistry();register_topics(registry)
        self.assertEqual(len(registry.topics()),66)
        registry.unregister_source('inspector')
        self.assertIsNone(registry.get('inspector.create'))
        self.assertEqual(len(registry.topics()),43)

    def test_v70_delete_dialog_f1_is_owned_and_contains_no_private_facts(self):
        self.commit_create();observed=[]
        def inspect(dialog):
            QTest.keyClick(dialog.defaultButton(),Qt.Key.Key_F1)
            observed.append(self.c.help.current())
        self.decision('Abbrechen',inspect);self.click(self.w.inspector.delete_button)
        self.assertEqual(observed[0].resolved_topic_id,'inspector.delete')
        self.assertEqual(observed[0].facts,())
        self.assertTrue(self.c._exists('action','action.created'))

    def test_all_create_dynamic_controls_resolve_owned_help_and_reference_tooltip(self):
        from PySide6.QtCore import QEvent, QPoint
        from PySide6.QtGui import QHelpEvent
        from PySide6.QtWidgets import QApplication
        for typ in ('PluginDynamicCommand','PluginMultistateDynamicCommand','PluginDynamicAdjustment','ActionEditorCommand'):
            self.create(typ)
            rows=self.w.inspector.sections.get('editor_controls')
            for control_type in CONTROL_TYPES if rows else (None,):
                if rows:
                    with patch.object(QMessageBox,'warning',return_value=QMessageBox.StandardButton.Yes):
                        rows.forms[0].fields['type'].input.setCurrentText(control_type)
                    if control_type=='file_selector':rows.forms[0].filters_editor.add_row()
                for widget in self.w.inspector.findChildren(QWidget):
                    if widget.focusPolicy()!=Qt.FocusPolicy.NoFocus or widget.property('inspectorTopic'):
                        context=self.w.help_bindings.context_for(widget)
                        self.assertTrue(context.topic_id.startswith('inspector.'))
                        self.assertIsNotNone(self.c.registry.get(context.topic_id))
                        self.assertEqual(context.facts,())
            self.assertEqual(self.w.help_bindings.context_for(self.w.inspector.status).topic_id,'inspector.unplaced')
            self.click(self.w.inspector.discard_button)
        self.c.select_node('action','action.command');self.w.open_inspector()
        button=self.w.inspector.delete_button
        event=QHelpEvent(QEvent.Type.ToolTip,QPoint(2,2),button.mapToGlobal(QPoint(2,2)))
        QApplication.sendEvent(button,event)
        self.assertEqual(self.c.help.current().resolved_topic_id,'inspector.delete_references')
        self.assertFalse(self.c.session.dirty)

    def test_coverage_register_concrete_controls_topics_functions_and_edges(self):
        data=json.loads((ROOT/'tests/fixtures/contracts/lifecycle-coverage.json').read_text(encoding='utf-8'))
        self.assertFalse(data['unresolved_gaps'])
        self.assertEqual(len({r['id'] for r in data['surfaces']}),len(data['surfaces']))
        for row in data['surfaces']+data['connections']:
            filename,function=row['test'].split('::')
            tree=ast.parse((ROOT/filename).read_text(encoding='utf-8-sig'))
            self.assertTrue(any(isinstance(n,ast.FunctionDef) and n.name==function for n in ast.walk(tree)))
            if 'topic_id' in row:self.assertIsNotNone(self.c.registry.get(row['topic_id']))
        self.assertEqual([r['id'] for r in data['connections']],[f'V-{i}' for i in range(63,71)])


if __name__ == '__main__':
    unittest.main()
