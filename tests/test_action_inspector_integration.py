"""Vertical native-shell routes and loss protection through actual Qt events."""
import ast,copy,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from PySide6.QtCore import Qt,QTimer,QEvent
from PySide6.QtGui import QCloseEvent,QFocusEvent
from PySide6.QtWidgets import QApplication,QMessageBox,QWidget,QPushButton
from PySide6.QtTest import QTest,QSignalSpy
from studio.native_shell import NativeStudioShell
from studio.native_session import NativeProjectSession,NativeSessionError,NativeRevisionConflict,NativeDiskConflict
from studio.context_help import HelpContext,HelpRegistry,load_help_entries
from studio.native_shell.help_bindings import RESOURCES,register_topics

class IntegrationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.path=Path(self.tmp.name)/'project.json';self.original=(ROOT/'examples/project_logitech_native_v1.json').read_bytes();self.path.write_bytes(self.original)
  self.w=NativeStudioShell(self.path);self.c=self.w.coordinator;self.w.show();self.w.activateWindow();self.app.processEvents()
  self.c.select_node('action','action.command');self.w.open_inspector();self.addCleanup(self.dispose)
 def dispose(self):self.w.hide();self.w.deleteLater();self.app.processEvents()
 def edit(self,text='Changed'):
  field=self.w.inspector.sections['common'].fields['display_name'].input
  field.selectAll();QTest.keyClick(field,Qt.Key.Key_Backspace);QTest.keyClicks(field,text)
 def choose(self,label):
  seen=[]
  def click():
   d=QApplication.activeModalWidget()
   if isinstance(d,QMessageBox):
    for b in d.buttons():
     if b.text()==label:seen.append(label);b.click();return
   seen.append('Missing dialog')
  QTimer.singleShot(10,click)
  return seen
 def test_v53_selection_and_folder_entry(self):
  before=self.c.session.snapshot();revision=self.c.session.revision
  for kind,identity,action in [('action','action.editor','action.editor'),('folder_entry','placement.multistate','action.multistate')]:
   self.c.select_node(kind,identity);self.assertEqual(self.w.inspector.draft.action_id,action)
  self.assertEqual(self.c.session.snapshot(),before);self.assertEqual(self.c.session.revision,revision);self.assertFalse(self.c.session.dirty)
 def test_v54_catalog_edit_navigation(self):
  self.c.select_node('action','action.editor')
  with patch('studio.native_shell.window.QInputDialog.getText') as dialog:
   QTest.mouseClick(self.w.catalog.edit_button,Qt.MouseButton.LeftButton)
  self.assertIs(self.w.tabs.currentWidget(),self.w.inspector);dialog.assert_not_called();self.assertFalse(self.c.session.dirty)
 def test_v55_apply_one_commit_history_save_fresh_load(self):
  before=self.c.session.snapshot();revision=self.c.session.revision;self.edit()
  f=self.w.inspector.sections['common'].fields['description'].input;f.selectAll();QTest.keyClicks(f,'Second change')
  self.assertEqual(self.c.session.revision,revision);self.assertFalse(self.c.session.dirty)
  with patch.object(self.c.session,'replace',wraps=self.c.session.replace) as commit:
   QTest.mouseClick(self.w.inspector.apply_button,Qt.MouseButton.LeftButton)
   commit.assert_called_once()
  after=self.c.session.snapshot();self.assertEqual(after['actions'][0]['description'],'Second change')
  self.assertEqual(after['actions'][1:],before['actions'][1:]);self.assertEqual(after['folders'],before['folders']);self.assertEqual(after['handlers'],before['handlers'])
  self.assertEqual(self.path.read_bytes(),self.original);self.assertFalse(self.w.inspector.dirty)
  self.w.undo_action.trigger();self.assertEqual(self.c.session.snapshot(),before);self.assertFalse(self.c.session.can_undo)
  self.w.redo_action.trigger();self.assertEqual(self.c.session.snapshot(),after)
  self.w.save_action.trigger();self.assertEqual(NativeProjectSession.load(self.path).snapshot(),after)
  self.assertTrue(self.w.reload_project());self.c.select_node('action','action.command')
  self.assertEqual(self.w.inspector.draft.snapshot(),after['actions'][0])
 def test_v56_dirty_selection_cancel_discard_apply(self):
  before=self.c.session.snapshot();self.edit('Keep');seen=self.choose('Abbrechen')
  self.c.select_node('action','action.editor');self.assertEqual(seen,['Abbrechen'])
  self.assertEqual(self.c.selection,('action','action.command'));self.assertEqual(self.w.inspector.draft.snapshot()['display_name'],'Keep')
  self.assertEqual(self.c.session.snapshot(),before)
  self.choose('Verwerfen');self.c.select_node('action','action.editor');self.assertFalse(self.w.inspector.dirty);self.assertEqual(self.c.session.snapshot(),before)
  self.edit('Editor changed');self.choose('Übernehmen');self.c.select_node('action','action.command')
  self.assertEqual(self.c.session.snapshot()['actions'][3]['display_name'],'Editor changed')
 def test_v57_reload_open_close_protect_draft(self):
  self.edit('Keep');session=self.c.session
  self.choose('Abbrechen');self.assertFalse(self.w.reload_project());self.assertIs(self.c.session,session)
  with patch.object(self.w,'confirm_unsaved') as confirm:
   self.assertFalse(self.w.open_project(self.path.parent/'missing.json'));confirm.assert_not_called()
  self.assertTrue(self.w.inspector.dirty);self.assertEqual(self.w.inspector.draft.snapshot()['display_name'],'Keep')
  self.choose('Abbrechen');event=QCloseEvent();self.w.closeEvent(event);self.assertFalse(event.isAccepted())
  self.choose('Verwerfen');self.assertTrue(self.w.reload_project());self.assertFalse(self.w.inspector.dirty)
  self.c.select_node('action','action.command');self.edit('Apply close')
  self.choose('Übernehmen')
  with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Save):
   event=QCloseEvent();self.w.closeEvent(event)
  self.assertTrue(event.isAccepted());self.assertEqual(NativeProjectSession.load(self.path).snapshot()['actions'][0]['display_name'],'Apply close')
 def test_v58_stale_refresh_and_disk_conflict(self):
  self.edit('Old draft');base=self.w.inspector.draft.base_revision
  self.c.rename_action('action.editor','Newer',base_revision=self.c.session.revision)
  self.assertEqual(self.w.inspector.draft.base_revision,base);before=self.c.session.snapshot()
  self.w.inspector.apply_button.click();self.assertTrue(self.w.inspector.dirty);self.assertEqual(self.c.session.snapshot(),before)
  self.assertIn('Veraltete',self.w.inspector.errors.text());self.w.inspector.discard()
  self.edit('Disk draft');external=self.path.read_bytes()+b'\n';self.path.write_bytes(external)
  before=self.c.session.snapshot();self.w.inspector.apply_button.click()
  self.assertEqual(self.c.session.snapshot(),before);self.assertEqual(self.path.read_bytes(),external);self.assertTrue(self.w.inspector.dirty)
 def test_v59_correlated_inline_problems(self):
  self.edit('');self.assertFalse(self.w.inspector.apply_button.isEnabled())
  self.assertEqual(len(self.w.problems.diagnostics('inspector')),1)
  self.assertEqual(self.w.problems.source_revision('inspector'),self.c.session.revision)
  self.assertIsNone(self.c.registry.get('inspector.private'))
  d=self.w.problems.diagnostics('inspector')[0];before=self.c.selection;self.c.diagnostic_activated(d);self.assertEqual(self.c.selection,before)
 def test_v60_inspector_topics_owner(self):
  entries=load_help_entries(RESOURCES/'inspector_topics.de.json');self.assertEqual(len(entries),23)
  registry=HelpRegistry();register_topics(registry);self.assertEqual(len(registry.topics()),66)
  for e in entries:
   self.assertTrue(e.description and e.example)
   for topic in e.related_topics:self.assertIsNotNone(registry.get(topic))
  registry.unregister_source('inspector')
  for e in entries:self.assertIsNone(registry.get(e.topic_id))
  self.assertEqual(len(registry.topics()),43)
 def test_v61_dynamic_focus_f1_pin_related_privacy(self):
  for i,action in enumerate(('action.command','action.multistate','action.adjustment','action.editor')):
   self.c.select_node('action',action);self.w.open_inspector()
   for widget in self.w.inspector.findChildren(QWidget):
    if widget.property('inspectorTopic'):
     context=self.w.help_bindings.context_for(widget)
     self.assertIsNotNone(self.c.registry.get(context.topic_id));self.assertEqual(context.facts,())
   key=('parameters','states','adjustment','editor_controls')[i]
   section=self.w.inspector.sections[key]
   if hasattr(section,'add_row'):
    section.add_row();self.app.processEvents();target=section.forms[-1].fields['name'].input
   else:target=section.fields['format'].input
   self.w.inspector.scroll.ensureWidgetVisible(target);target.setFocus();self.app.processEvents();self.assertEqual(self.c.help.current().resolved_topic_id,'inspector.'+key)
   self.c.help.set_pinned(True);self.w.help_bindings.update(self.w.catalog.search_edit)
   self.assertEqual(self.c.help.current().resolved_topic_id,'inspector.'+key)
   QTest.keyClick(target,Qt.Key.Key_F1);self.assertIs(self.w.tabs.currentWidget(),self.w.help_widget)
   self.assertEqual(self.c.help.current().resolved_topic_id,'inspector.'+key)
   button=self.w.help_widget.findChild(QPushButton,'helpRelated.inspector.apply');button.click()
   self.assertEqual(self.c.help.current().resolved_topic_id,'inspector.apply');self.assertTrue(self.c.help.current().pinned)
   self.c.help.set_pinned(False);self.w.inspector.discard()
  self.assertFalse(self.c.session.dirty);self.assertEqual(self.path.read_bytes(),self.original)
 def test_all_active_controls_have_owned_help_including_seven_types(self):
  from studio.action_inspector.widget import CONTROL_TYPES
  for identity in ('action.command','action.multistate','action.adjustment','action.editor'):
   self.c.select_node('action',identity);self.w.open_inspector()
   rows=self.w.inspector.sections.get('editor_controls')
   for typ in CONTROL_TYPES if rows else (None,):
    if rows:
     with patch.object(QMessageBox,'warning',return_value=QMessageBox.StandardButton.Yes):
      rows.forms[0].fields['type'].input.setCurrentText(typ)
     if typ=='file_selector':rows.forms[0].filters_editor.add_row()
    self.app.processEvents()
    for widget in self.w.inspector.findChildren(QWidget):
     if widget.focusPolicy()!=Qt.FocusPolicy.NoFocus or widget.property('inspectorTopic'):
      context=self.w.help_bindings.context_for(widget)
      self.assertTrue(context.topic_id.startswith('inspector.'),widget.objectName())
      self.assertIsNotNone(self.c.registry.get(context.topic_id));self.assertEqual(context.facts,())
   self.w.inspector.discard()
 def test_machine_coverage_and_connections(self):
  data=json.loads((ROOT/'tests/fixtures/contracts/inspector-coverage.json').read_text(encoding='utf-8'))
  self.assertFalse(data['unresolved_gaps']);self.assertEqual(data['owner'],'inspector')
  names={node.name for node in ast.walk(ast.parse(Path(__file__).read_text(encoding='utf-8-sig'))) if isinstance(node,ast.FunctionDef)}
  ids=[]
  for row in data['surfaces']:
   self.assertIsNotNone(self.c.registry.get(row['topic_id']));self.assertEqual(row['owner'],'inspector')
   self.assertIn(row['test'].split('::')[1],names);ids.append(row['id'])
  self.assertEqual(len(ids),len(set(ids)))
  self.assertEqual({r['sdk_type'] for r in data['surfaces']},{a.sdk_type for a in self.c.session.native_project().actions})
  for edge in data['connections']:
   self.assertIn(edge['test'].split('::')[1],names)
   self.assertIn(edge['id'],(ROOT/'docs/architecture/studio/04-Verbindungsregister.md').read_text(encoding='utf-8'))
 def test_v62_history_guard_preserves_cancelled_draft(self):
  self.c.rename_action('action.editor','History',base_revision=self.c.session.revision);self.edit('Keep')
  revision=self.c.session.revision;self.choose('Abbrechen');self.w.undo_action.trigger()
  self.assertEqual(self.c.session.revision,revision);self.assertTrue(self.w.inspector.dirty)
  self.choose('Verwerfen');self.w.undo_action.trigger();self.assertEqual(self.c.session.snapshot(),json.loads(self.original))
 def test_host_negative_identity_type_missing_and_noop(self):
  s=self.c.session;raw=s.snapshot();r=s.revision;a=raw['actions'][0]
  self.assertEqual(self.c.apply_action_edit(a['id'],a,base_revision=r),r);self.assertFalse(s.can_undo)
  for proposed in (dict(a,id='other'),dict(a,sdk_type='ActionEditorCommand'),dict(a,handler='missing')):
   with self.assertRaises(NativeSessionError):self.c.apply_action_edit(a['id'],proposed,base_revision=r)
  with self.assertRaises(NativeSessionError):self.c.apply_action_edit('missing',a,base_revision=r)
  self.assertEqual(s.snapshot(),raw);self.assertFalse(s.dirty)
 def test_all_types_special_fields_apply_roundtrip(self):
  for i,action in enumerate(('action.command','action.multistate','action.adjustment','action.editor')):
   self.c.select_node('action',action);self.edit('Type '+str(i))
   w=self.w.inspector
   if i==0:w.sections['parameters'].forms[0].fields['display_name'].input.setText('Variant')
   elif i==1:w.sections['states'].forms[0].fields['description'].input.setPlainText('State changed')
   elif i==2:w.sections['adjustment'].fields['default'].input.setText('75')
   else:w.sections['editor_controls'].forms[0].fields['label'].input.setText('Editor label')
   self.assertTrue(w.apply_button.isEnabled());w.apply_button.click();self.assertFalse(w.dirty)
  after=self.c.session.snapshot();self.assertTrue(self.w.save_project());self.assertEqual(NativeProjectSession.load(self.path).snapshot(),after)
 def test_reload_project_and_close_all_three_draft_decisions(self):
  other=self.path.parent/'other.json';other.write_bytes(self.original)
  for operation in ('reload','project','close'):
   for decision in ('Abbrechen','Verwerfen','Übernehmen'):
    with self.subTest(operation=operation,decision=decision):
     self.w.inspector.accept_applied();self.path.write_bytes(self.original)
     self.c.open_project(self.path,discard=True);self.c.select_node('action','action.command');self.edit('Lifecycle')
     revision=self.c.session.revision;self.choose(decision)
     with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Save):
      if operation=='close':
       event=QCloseEvent();self.w.closeEvent(event);accepted=event.isAccepted()
      else:accepted=self.w.reload_project() if operation=='reload' else self.w.open_project(other)
     self.assertEqual(accepted,decision!='Abbrechen')
     if decision=='Abbrechen':
      self.assertEqual(self.c.session.revision,revision);self.assertTrue(self.w.inspector.dirty)
      self.assertEqual(self.w.inspector.draft.snapshot()['display_name'],'Lifecycle')
     if decision=='Übernehmen':self.assertEqual(NativeProjectSession.load(self.path).snapshot()['actions'][0]['display_name'],'Lifecycle')
     else:self.assertEqual(self.path.read_bytes(),self.original)
 def test_invalid_draft_blocks_apply_on_selection_and_save(self):
  self.edit('');revision=self.c.session.revision
  for operation in ('selection','save'):
   self.choose('Übernehmen')
   if operation=='selection':self.c.select_node('action','action.editor')
   else:self.assertFalse(self.w.save_project())
   self.assertEqual(self.c.session.revision,revision);self.assertTrue(self.w.inspector.dirty)
   self.assertEqual(self.c.selection,('action','action.command'))
 def test_direct_coordinator_project_switch_refuses_dirty_draft(self):
  self.edit()
  with self.assertRaises(NativeSessionError):self.c.open_project(self.path)
  self.assertTrue(self.w.inspector.dirty)

if __name__=='__main__':unittest.main()
