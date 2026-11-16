"""ActionInspector lab: temporary projects only; genuine Windows screen evidence."""
import argparse,json,os,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from PySide6.QtWidgets import QApplication,QMessageBox,QToolButton
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QPalette,QColor
from PySide6.QtTest import QTest
from studio.native_shell import NativeStudioShell
from studio.native_session import NativeProjectSession

def smoke(w):
 c=w.coordinator;checks=[]
 for i,identity in enumerate(('action.command','action.multistate','action.adjustment','action.editor')):
  c.select_node('action',identity);w.open_inspector();f=w.inspector.sections['common'].fields['display_name'].input
  f.selectAll();QTest.keyClicks(f,'Lab '+str(i))
  if i==0:w.inspector.sections['parameters'].forms[0].fields['display_name'].input.setText('Lab variant')
  if i==1:w.inspector.sections['states'].forms[0].fields['description'].input.setPlainText('Lab state')
  if i==2:w.inspector.sections['adjustment'].fields['default'].input.setText('75')
  if i==3:w.inspector.sections['editor_controls'].forms[0].fields['label'].input.setText('Lab editor')
  assert not c.session.dirty if i==0 else c.session.dirty
  assert w.inspector.apply_button.isEnabled();w.inspector.apply_button.click();assert not w.inspector.dirty
  checks.append(identity)
 after=c.session.snapshot();c.undo();assert c.session.snapshot()!=after;c.redo();assert c.session.snapshot()==after
 assert w.save_project();assert NativeProjectSession.load(c.session.path).snapshot()==after
 assert w.reload_project();c.select_node('action','action.adjustment');w.open_inspector()
 target=w.inspector.sections['adjustment'].fields['default'].input;target.setFocus();QApplication.processEvents();QTest.keyClick(target,Qt.Key.Key_F1)
 assert c.help.current().resolved_topic_id=='inspector.adjustment'
 assert w.catalog.new_action_button.isEnabled();assert not w.ict_action.isEnabled()
 print('PASS: four types, common/special edits, Apply, history, save, fresh load, F1, capability boundaries',flush=True)
 return checks

def evidence(app,w,destination):
 assert sys.platform=='win32' and app.platformName()=='windows','Real Windows Qt required'
 destination.mkdir(parents=True,exist_ok=True);shots=[]
 def capture(name):
  w.show();w.raise_();w.activateWindow();QTest.qWait(200)
  image=w.grab();assert not image.isNull();assert image.save(str(destination/(name+'.png')))
  shots.append(dict(name=name,capture_method='QWidget.grab on genuine Windows Qt',dpr=w.devicePixelRatioF(),pixels=[image.width(),image.height()]))
 app.setStyle('Fusion')
 light=QPalette()
 for role,color in ((QPalette.ColorRole.Window,'#f4f5f7'),(QPalette.ColorRole.Base,'#ffffff'),(QPalette.ColorRole.AlternateBase,'#ebedf0'),(QPalette.ColorRole.Button,'#eceef1'),(QPalette.ColorRole.WindowText,'#18212b'),(QPalette.ColorRole.Text,'#18212b'),(QPalette.ColorRole.ButtonText,'#18212b'),(QPalette.ColorRole.Highlight,'#247e97'),(QPalette.ColorRole.HighlightedText,'#ffffff')):light.setColor(role,QColor(color))
 for role in (QPalette.ColorRole.Text,QPalette.ColorRole.WindowText,QPalette.ColorRole.ButtonText):light.setColor(QPalette.ColorGroup.Disabled,role,QColor('#858b93'))
 app.setPalette(light);w.resize(1320,840);w.splitter.setSizes([260,280,780])
 for i,(identity,section) in enumerate((('action.command','parameters'),('action.multistate','states'),('action.adjustment','adjustment'),('action.editor','editor_controls'))):
  w.coordinator.select_node('action',identity);w.open_inspector();app.processEvents()
  w.inspector.scroll.ensureWidgetVisible(w.inspector.sections[section]);capture(f'0{i+1}-light-{identity}')
 w.coordinator.select_node('action','action.command');w.open_inspector()
 w.inspector.scroll.verticalScrollBar().setValue(0);w.inspector.sections['common'].fields['display_name'].input.clear();capture('05-invalid-dirty')
 w.inspector.discard();w.coordinator.select_node('action','action.editor');w.open_inspector()
 w.inspector.sections['editor_controls'].add_row();app.processEvents();target=w.inspector.sections['editor_controls'].forms[-1].fields['name'].input
 w.inspector.scroll.ensureWidgetVisible(target);target.setFocus();app.processEvents();QTest.keyClick(target,Qt.Key.Key_F1)
 assert w.coordinator.help.current().resolved_topic_id=='inspector.editor_controls';w.coordinator.help.set_pinned(True)
 w.help_widget.findChild(QToolButton,'helpDetailsToggle').setChecked(True)
 capture('06-help-pin-sdk-reference')
 dark=QPalette()
 for role,color in ((QPalette.ColorRole.Window,'#20242a'),(QPalette.ColorRole.Base,'#171b20'),(QPalette.ColorRole.AlternateBase,'#292f37'),(QPalette.ColorRole.Button,'#303741'),(QPalette.ColorRole.WindowText,'#eeeeee'),(QPalette.ColorRole.Text,'#eeeeee'),(QPalette.ColorRole.ButtonText,'#eeeeee'),(QPalette.ColorRole.Highlight,'#247e97'),(QPalette.ColorRole.HighlightedText,'#ffffff')):dark.setColor(role,QColor(color))
 for role in (QPalette.ColorRole.Text,QPalette.ColorRole.WindowText,QPalette.ColorRole.ButtonText):dark.setColor(QPalette.ColorGroup.Disabled,role,QColor('#858b93'))
 app.setPalette(dark);w.resize(1020,790);w.splitter.setSizes([245,245,530]);capture('07-dark-narrow-help')
 w.tabs.setCurrentWidget(w.inspector);w.inspector.scroll.ensureWidgetVisible(target);capture('08-dark-narrow-editor-dirty')
 w.inspector.discard();w.coordinator.select_node('action','action.adjustment');w.open_inspector();app.processEvents();w.inspector.scroll.ensureWidgetVisible(w.inspector.sections['adjustment'].fields['default']);capture('09-dark-narrow-adjustment')
 w.inspector.sections['adjustment'].fields['default'].input.setText('999');app.processEvents();w.inspector.scroll.ensureWidgetVisible(w.inspector.sections['adjustment'].fields['default']);capture('10-dark-narrow-invalid')
 def cancel():
  d=QApplication.activeModalWidget();assert isinstance(d,QMessageBox)
  pix=d.grab();assert pix.save(str(destination/'11-draft-loss-dialog.png'))
  next(b for b in d.buttons() if b.text()=='Abbrechen').click()
 QTimer.singleShot(200,cancel);assert not w.confirm_draft();assert w.inspector.dirty
 w.inspector.discard()
 (destination/'visual-report.json').write_text(json.dumps(dict(platform=app.platformName(),screenshots=shots,loss_dialog_cancel=True,temporary_project_only=True),indent=2),encoding='utf-8')
 print('PASS: Windows screenshots and draft dialog; '+str(len(shots)+1)+' captures',flush=True)

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--smoke',action='store_true');parser.add_argument('--evidence',type=Path);args=parser.parse_args()
 app=QApplication.instance() or QApplication([])
 source=ROOT/'examples/project_logitech_native_v1.json';original=source.read_bytes()
 with tempfile.TemporaryDirectory(prefix='action-inspector-lab-') as tmp:
  path=Path(tmp)/'native.json';path.write_bytes(original);w=NativeStudioShell(path);w.show();app.processEvents()
  try:
   if args.smoke:smoke(w)
   elif args.evidence:evidence(app,w,args.evidence)
   else:return app.exec()
   assert source.read_bytes()==original
  finally:w.hide();w.deleteLater();app.processEvents()
 return 0
if __name__=='__main__':raise SystemExit(main())
