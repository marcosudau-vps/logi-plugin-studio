"""Qt-free draft contracts, including raw absences and reference failures."""
import copy
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from studio.action_inspector.draft import ActionDraft, DraftError

class DraftTests(unittest.TestCase):
 def setUp(self): self.raw=json.loads((ROOT/'examples/project_logitech_native_v1.json').read_text(encoding='utf-8'))
 def draft(self,i=0): return ActionDraft(self.raw,self.raw['actions'][i]['id'],self.raw['actions'][i],'revision')
 def test_all_types_noop_absence_and_defensive_copies(self):
  for i in range(4):
   d=self.draft(i); before=copy.deepcopy(self.raw)
   self.assertFalse(d.dirty); self.assertEqual(d.proposed_action(),before['actions'][i])
   snap=d.snapshot();snap['display_name']='Outside';self.assertFalse(d.dirty)
   d.set_field('display_name','Inside'); self.assertTrue(d.dirty)
   self.assertEqual(self.raw,before); d.discard();self.assertFalse(d.dirty)
 def test_input_defensive_and_revision_identity(self):
  d=self.draft();self.raw['actions'][0]['display_name']='Outside'
  self.assertNotEqual(d.snapshot()['display_name'],'Outside');self.assertEqual(d.base_revision,'revision')
  for key,value in [('id','other'),('sdk_type','ActionEditorCommand'),('states',[])]:
   with self.assertRaises(DraftError): d.set_field(key,value)
  with self.assertRaises(DraftError): d.remove_field('handler')
  with self.assertRaises(DraftError): ActionDraft(self.raw,'missing',{},'revision')
 def test_parameter_duplicate_handler_and_paths(self):
  for key,value in [('handler','handler.missing'),('parameters',[self.raw['actions'][0]['parameters'][0]]*2),('symbol','../private.svg'),('icon','C:/private.png'),('icon_template','image.png'),('display_name','')]:
   with self.subTest(key=key):
    d=self.draft();d.set_field(key,value)
    self.assertTrue(d.diagnostics())
    with self.assertRaises(DraftError):d.proposed_action()
 def test_parameter_reference_requires_explicit_decision(self):
  self.raw['actions'][0]['parameter_symbols']={'first':'assets/first.svg'}
  d=self.draft();rows=d.snapshot()['parameters'];rows[0]['name']='renamed';d.set_rows('parameters',rows)
  self.assertEqual(d.symbol_conflicts(),('first',));self.assertTrue(d.diagnostics())
  d.resolve_symbol('first','renamed');self.assertFalse(d.diagnostics())
  self.assertEqual(d.snapshot()['parameter_symbols'],{'renamed':'assets/first.svg'})
  d.resolve_symbol('renamed'); self.assertEqual(d.snapshot()['parameter_symbols'],{})
 def test_states_reorder_contiguous_toggle_and_gaps(self):
  d=self.draft(1);d.set_rows('states',list(reversed(d.snapshot()['states'])))
  self.assertEqual([r['index'] for r in d.proposed_action()['states']],[0,1])
  rows=d.snapshot()['states'];rows.append(dict(index=2,name='third',display_name='Third',description=''))
  d.set_rows('states',rows);self.assertTrue(d.diagnostics());d.set_field('state_change','increment');self.assertFalse(d.diagnostics())
  rows[0]['index']=7;d.set_field('states',rows);self.assertTrue(d.diagnostics())
 def test_adjustment_finite_boolean_and_bounds(self):
  for adjustment in ({'minimum':True},{'minimum':float('nan')},{'maximum':float('inf')},{'minimum':5,'maximum':1},{'minimum':0,'maximum':1,'default':2},{'has_reset':1}):
   d=self.draft(2);d.set_field('adjustment',adjustment);self.assertTrue(d.diagnostics(),adjustment)
 def test_control_types_and_options(self):
  for typ in ('textbox','checkbox','textarea','file_selector','directory_selector','slider','numeric_up_down'):
   row=dict(type=typ,name='field',label='Feld')
   if typ in ('slider','numeric_up_down'):row.update(minimum=0,maximum=100,step=1,default=50)
   if typ=='checkbox':row['default']=True
   if typ=='file_selector':row['filters']=[dict(pattern='*.png',label='Bilder')]
   d=self.draft(3);d.set_rows('editor_controls',[row]);self.assertFalse(d.diagnostics(),typ)
   row['filters']=[] if typ!='file_selector' else 'wrong'
   d.set_rows('editor_controls',[row]);self.assertTrue(d.diagnostics(),typ)
 def test_numeric_invalid_and_checkbox_defaults(self):
  rows=[dict(type='checkbox',name='x',label='X',default=1),dict(type='slider',name='x',label='X',minimum=0,maximum=10,step=0,default=1),dict(type='textbox',name='x',label='X',default='text')]
  for row in rows:
   d=self.draft(3);d.set_rows('editor_controls',[row]);self.assertTrue(d.diagnostics())
 def test_optional_null_and_raw_path_preservation(self):
  self.raw['actions'][0].update(icon=None,symbol='assets\\symbol.svg')
  d=self.draft();d.set_field('display_name','Changed')
  self.assertEqual(d.proposed_action()['symbol'],'assets\\symbol.svg');self.assertIsNone(d.snapshot()['icon'])
  self.assertNotIn('description',self.draft(1).snapshot())
  d.remove_field('icon');self.assertNotIn('icon',d.proposed_action())

if __name__=='__main__': unittest.main()
