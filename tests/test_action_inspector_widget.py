"""Actual structured controls, signals and explicit destructive decisions."""
import json,os,sys,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from PySide6.QtWidgets import QApplication,QMessageBox,QLineEdit
from PySide6.QtTest import QTest,QSignalSpy
from PySide6.QtCore import Qt
from studio.action_inspector.widget import ActionInspectorWidget

class WidgetTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  self.raw=json.loads((ROOT/'examples/project_logitech_native_v1.json').read_text(encoding='utf-8'))
  self.w=ActionInspectorWidget();self.w.resize(420,750);self.w.show();self.load()
  self.addCleanup(self.dispose)
 def dispose(self):self.w.hide();self.w.deleteLater();self.app.processEvents()
 def load(self,i=0):
  if self.w.dirty:self.w.discard()
  self.w.set_action(self.raw,self.raw['actions'][i]['id'],self.raw['actions'][i],'r')
  self.app.processEvents()
 def test_all_type_sections_and_readonly(self):
  for i,special in enumerate((None,'states','adjustment','editor_controls')):
   self.load(i);self.assertFalse(self.w.dirty)
   if special:self.assertIn(special,self.w.sections)
   for key in ('id','sdk_type'):self.assertTrue(self.w.sections['identity'].fields[key].input.isReadOnly())
   self.assertEqual(self.w.draft.snapshot(),self.raw['actions'][i])
 def test_two_real_inputs_one_apply_intent(self):
  spy=QSignalSpy(self.w.applyRequested)
  field=self.w.sections['common'].fields['display_name'].input
  field.selectAll();QTest.keyClicks(field,'Changed')
  desc=self.w.sections['common'].fields['description'].input
  desc.selectAll();QTest.keyClicks(desc,'Description')
  self.assertTrue(self.w.dirty);QTest.mouseClick(self.w.apply_button,Qt.MouseButton.LeftButton)
  self.assertEqual(spy.count(),1);self.assertEqual(spy.at(0)[2]['display_name'],'Changed')
  self.assertTrue(self.w.dirty) # No speculative success before host acknowledgement.
 def test_inline_invalid_and_discard(self):
  self.w.sections['common'].fields['display_name'].input.clear()
  self.assertFalse(self.w.apply_button.isEnabled());self.assertIn('prüfen',self.w.errors.text())
  self.assertTrue(self.w.sections['common'].fields['display_name'].error.isVisible())
  self.w.discard_button.click();self.assertFalse(self.w.dirty)
 def test_parameter_add_edit_move_remove(self):
  rows=self.w.sections['parameters'];rows.add_button.click()
  rows.forms[2].fields['name'].input.setText('third');rows.move_or_remove(2,-1)
  self.assertEqual(self.w.draft.snapshot()['parameters'][1]['name'],'third')
  rows.move_or_remove(1,0);self.assertEqual(self.w.draft.snapshot(),self.raw['actions'][0])
 def test_symbol_conflict_remains_until_user_edits_mapping(self):
  self.raw['actions'][0]['parameter_symbols']={'first':'assets/first.svg'};self.load()
  self.w.sections['parameters'].forms[0].fields['name'].input.setText('changed')
  self.assertFalse(self.w.apply_button.isEnabled());self.assertIn('first',self.w.draft.snapshot()['parameter_symbols'])
  self.w.sections['parameter_symbols'].forms[0].fields['name'].input.setText('changed')
  self.assertTrue(self.w.apply_button.isEnabled())
 def test_symbol_duplicates_block_and_discard(self):
  rows=self.w.sections['parameter_symbols'];rows.add_row();rows.add_row()
  self.assertTrue(self.w.dirty);self.assertFalse(self.w.apply_button.isEnabled())
  self.w.discard();self.assertFalse(self.w.dirty)
 def test_states_and_change_mode(self):
  self.load(1);rows=self.w.sections['states'];rows.add_row()
  self.assertFalse(self.w.apply_button.isEnabled())
  field=self.w.sections['state_change'].fields['state_change'];field.input.setCurrentText('increment')
  self.assertTrue(self.w.apply_button.isEnabled());rows.move_or_remove(2,-1)
  self.assertEqual([r['index'] for r in self.w.draft.proposed_action()['states']],[0,1,2])
 def test_adjustment_fields(self):
  self.load(2);f=self.w.sections['adjustment'].fields
  f['minimum'].input.setText('200');self.assertFalse(self.w.apply_button.isEnabled())
  f['minimum'].input.setText('0');f['has_reset'].input.setCurrentText('false')
  self.assertTrue(self.w.apply_button.isEnabled());self.assertFalse(self.w.draft.snapshot()['adjustment']['has_reset'])
 def test_assets_remove_null_and_bad_relative(self):
  f=self.w.sections['assets'].fields['icon'];f.mode.setCurrentIndex(2);f.input.setText('../bad.png')
  self.assertFalse(self.w.apply_button.isEnabled());f.input.setText('assets/icon.png');self.assertTrue(self.w.apply_button.isEnabled())
  f.mode.setCurrentIndex(1);self.assertIsNone(self.w.draft.snapshot()['icon'])
  f.mode.setCurrentIndex(0);self.assertNotIn('icon',self.w.draft.snapshot())
 def test_control_type_switch_warning_cancel_and_accept(self):
  self.load(3);rows=self.w.sections['editor_controls']
  with patch.object(QMessageBox,'warning',return_value=QMessageBox.StandardButton.Cancel):
   rows.forms[1].fields['type'].input.setCurrentText('slider')
  self.assertEqual(rows.rows[1]['type'],'checkbox');self.assertFalse(self.w.dirty)
  with patch.object(QMessageBox,'warning',return_value=QMessageBox.StandardButton.Yes):
   rows.forms[1].fields['type'].input.setCurrentText('slider')
  self.assertEqual(rows.rows[1]['default'],0);self.assertTrue(self.w.apply_button.isEnabled())
 def test_all_control_types_and_nested_filters(self):
  self.load(3);rows=self.w.sections['editor_controls']
  for typ in ('textarea','file_selector','directory_selector','numeric_up_down','textbox','checkbox','slider'):
   with patch.object(QMessageBox,'warning',return_value=QMessageBox.StandardButton.Yes):
    rows.forms[0].fields['type'].input.setCurrentText(typ)
   if typ=='file_selector':
    rows.forms[0].filters_editor.add_row()
    self.assertEqual(rows.rows[0]['filters'][0]['pattern'],'*.png')
   self.assertFalse(self.w.draft.diagnostics(),typ)
 def test_dirty_setter_refuses_overwrite(self):
  self.w.sections['common'].fields['display_name'].input.setText('Keep')
  with self.assertRaises(ValueError):self.w.set_action(self.raw,'action.editor',self.raw['actions'][3],'r2')
  self.assertEqual(self.w.draft.snapshot()['display_name'],'Keep')

if __name__=='__main__':unittest.main()
