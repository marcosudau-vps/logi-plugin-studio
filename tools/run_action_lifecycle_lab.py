"""AP-INSP-002: temporäre native Projekte, Qt-Klicks und echte Windows-Evidenz."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QPalette,QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QMessageBox,QPushButton
from studio.native_shell import NativeStudioShell
from studio.native_session import NativeProjectSession

TYPES=('PluginDynamicCommand','PluginMultistateDynamicCommand','PluginDynamicAdjustment','ActionEditorCommand')


def click(widget):
    QTest.mouseClick(widget,Qt.MouseButton.LeftButton)
    QApplication.processEvents()


def text(w,section,key,value):
    form=w.inspector.sections[section];form.set_expanded(True)
    target=form.fields[key].input
    w.inspector.scroll.ensureWidgetVisible(target);target.setFocus()
    target.selectAll();QTest.keyClick(target,Qt.Key.Key_Backspace);QTest.keyClicks(target,value)


def new_action(w,typ,identity):
    click(w.catalog.new_action_button)
    selector=w.inspector.sections['identity'].fields['sdk_type'].input
    index=selector.findText(typ);QTest.keyClick(selector,Qt.Key.Key_Home)
    for _ in range(index):
        QTest.keyClick(w.inspector.sections['identity'].fields['sdk_type'].input,Qt.Key.Key_Down)
    text(w,'identity','id',identity);text(w,'common','display_name','Neue SDK-Aktion '+typ)
    inspector=w.inspector
    if typ==TYPES[0]:
        rows=inspector.sections['parameters'];click(rows.add_button)
        rows.forms[0].fields['display_name'].input.setText('Neue Variante')
    elif typ==TYPES[1]:
        rows=inspector.sections['states'];rows.set_expanded(True);rows.forms[0].set_expanded(True)
        rows.forms[0].fields['description'].input.setPlainText('Neu angelegter Zustand')
    elif typ==TYPES[2]:
        form=inspector.sections['adjustment'];form.set_expanded(True)
        field=form.fields['format'];field.mode.setCurrentIndex(2);field.input.setText('{0}%')
    else:
        rows=inspector.sections['editor_controls'];rows.set_expanded(True);rows.forms[0].set_expanded(True)
        rows.forms[0].fields['label'].input.setText('Neues Textfeld')
    assert inspector.creating and inspector.apply_button.isEnabled()


def respond(label,capture=None):
    observations=[]
    def answer():
        dialog=QApplication.activeModalWidget()
        if not isinstance(dialog,QMessageBox):
            observations.append('FEHLENDER DIALOG');return
        observations.append(dict(default=dialog.defaultButton().text(),text=dialog.text()))
        if capture:capture(dialog)
        button=next((b for b in dialog.buttons() if b.text()==label),None)
        if button:click(button)
        else:dialog.reject()
    QTimer.singleShot(150,answer)
    return observations


def palette(app,dark=False):
    app.setStyle('Fusion');p=QPalette()
    colors=('#20242a','#171b20','#292f37','#303741','#eeeeee') if dark else ('#f4f5f7','#ffffff','#ebedf0','#eceef1','#18212b')
    for role,color in ((QPalette.ColorRole.Window,colors[0]),(QPalette.ColorRole.Base,colors[1]),
                       (QPalette.ColorRole.AlternateBase,colors[2]),(QPalette.ColorRole.Button,colors[3]),
                       (QPalette.ColorRole.WindowText,colors[4]),(QPalette.ColorRole.Text,colors[4]),
                       (QPalette.ColorRole.ButtonText,colors[4]),(QPalette.ColorRole.Highlight,'#247e97'),
                       (QPalette.ColorRole.HighlightedText,'#ffffff')):
        p.setColor(role,QColor(color))
    for role in (QPalette.ColorRole.Text,QPalette.ColorRole.WindowText,QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled,role,QColor('#858b93'))
    app.setPalette(p)


def workflow(app,w,destination=None):
    c=w.coordinator;session=c.session;original=session.snapshot();disk=session.path.read_bytes()
    shots=[];checkpoints={};commits=[]
    if destination:
        assert sys.platform=='win32' and app.platformName()=='windows','Echte Windows-Qt-Plattform erforderlich'
        assert abs(w.devicePixelRatioF()-1.5)<0.05,'Windows muss auf 150 % DPI stehen'
        destination.mkdir(parents=True,exist_ok=True)
        palette(app);w.resize(1380,860);w.splitter.setSizes([245,270,865])

    def capture(name,widget=None):
        if not destination:return
        target=widget or w
        if not widget:
            w.show();w.raise_();w.activateWindow();QTest.qWait(150)
        pix=target.grab();assert not pix.isNull()
        path=destination/(name+'.png');assert pix.save(str(path))
        shots.append(dict(file=path.name,platform=app.platformName(),dpr=target.devicePixelRatioF(),
                          pixels=[pix.width(),pix.height()],capture='QWidget.grab; sichtbares echtes Windows-Qt-Fenster',
                          sha256=hashlib.sha256(path.read_bytes()).hexdigest()))

    with patch.object(session,'replace',wraps=session.replace) as replace, patch.object(session,'save',wraps=session.save) as save:
        for i,typ in enumerate(TYPES):
            before=session.snapshot();count=replace.call_count
            identity=f'action.lab-{i}'
            new_action(w,typ,identity)
            assert len(session.snapshot()['actions'])==4+i
            assert w.catalog.item_for(identity) is None
            assert session.path.read_bytes()==disk
            if i==0:capture('01-create-editable-id')
            click(w.inspector.apply_button)
            assert replace.call_count==count+1
            assert not w.inspector.creating and not w.inspector.dirty
            assert c.selection==('action',identity) and w.catalog.item_for(identity) is not None
            assert w.inspector.sections['identity'].fields['id'].input.isReadOnly()
            after=session.snapshot();assert after['folders']==original['folders'];assert after['handlers']==original['handlers']
            checkpoints[identity]=after
            commits.append(dict(intent='create',id=identity,replace_calls=replace.call_count-count,history=len(session._undo)))
            section=('parameters','states','adjustment','editor_controls')[i]
            w.inspector.sections['identity'].set_expanded(False)
            w.inspector.sections['common'].set_expanded(False)
            w.inspector.sections[section].set_expanded(True)
            if hasattr(w.inspector.sections[section],'forms'):
                w.inspector.sections[section].forms[0].set_expanded(True)
            app.processEvents();w.inspector.scroll.ensureWidgetVisible(w.inspector.sections[section]);capture(f'0{i+2}-new-{typ}')
            w.undo_action.trigger();assert session.snapshot()==before
            w.redo_action.trigger();assert session.snapshot()==after
            click(w.inspector.apply_button);assert replace.call_count==count+1
            assert w.save_project();disk=session.path.read_bytes()
            assert NativeProjectSession.load(session.path).snapshot()==after

        # Dieselbe bestätigte Action direkt weiter bearbeiten, separat übernehmen/speichern.
        c.select_node('action','action.lab-3');w.open_inspector()
        text(w,'common','display_name','Bearbeitete neue Action')
        click(w.inspector.apply_button);edited=session.snapshot()
        assert w.save_project();disk=session.path.read_bytes()
        count=replace.call_count
        seen=respond('Aktion löschen',lambda dialog:capture('08-delete-confirmation',dialog))
        click(w.inspector.delete_button)
        assert seen and seen[0]['default']=='Abbrechen'
        assert replace.call_count==count+1 and w.catalog.offer_for('action.lab-3') is None
        assert w.inspector.draft is None
        deleted=session.snapshot();capture('09-delete-success')
        commits.append(dict(intent='delete',id='action.lab-3',replace_calls=replace.call_count-count,history=len(session._undo)))
        assert session.path.read_bytes()==disk
        w.undo_action.trigger();assert session.snapshot()==edited
        w.redo_action.trigger();assert session.snapshot()==deleted
        assert w.save_project();disk=session.path.read_bytes()
        assert NativeProjectSession.load(session.path).snapshot()==deleted
        checkpoints.update(edited=edited,deleted=deleted)
        assert save.call_count==6

        c.select_node('action','action.command');w.open_inspector()
        assert not w.inspector.delete_button.isEnabled()
        assert 'placement.command' in w.inspector.delete_info.text()
        count=replace.call_count;assert not w.delete_selected();assert replace.call_count==count
        capture('10-folder-reference-protection')
        w.inspector.sections['identity'].set_expanded(False);w.inspector.sections['common'].set_expanded(False)
        rows=w.inspector.sections['parameters'];rows.set_expanded(True)
        rows.forms[0].set_expanded(True);w.inspector.scroll.ensureWidgetVisible(rows)
        capture('06-compact-row-expanded')
        values=w.inspector.draft.snapshot();rows.forms[0].set_expanded(False)
        capture('07-compact-row-collapsed');assert w.inspector.draft.snapshot()==values

        text(w,'common','display_name','Noch nicht uebernommen')
        values=w.inspector.draft.snapshot();base=w.inspector.draft.base_revision
        c.rename_action('action.editor','Parallel geaendert',base_revision=session.revision)
        assert w.inspector.stale and not w.inspector.apply_button.isEnabled()
        assert w.inspector.draft.snapshot()==values and w.inspector.draft.base_revision==base
        w.inspector.scroll.verticalScrollBar().setValue(0);capture('11-stale-warning')
        click(w.inspector.refresh_button)

        new_action(w,TYPES[1],'action.loss-protection')
        values=w.inspector.draft.snapshot();selection=c.selection;revision=session.revision
        seen=respond('Abbrechen',lambda dialog:capture('12-draft-loss-cancel',dialog))
        click(w.catalog.new_action_button)
        assert seen and w.inspector.draft.snapshot()==values and session.revision==revision and c.selection==selection
        if destination:
            palette(app,True);w.resize(1050,800);w.splitter.setSizes([240,240,570])
            w.inspector.scroll.verticalScrollBar().setValue(0);capture('13-dark-narrow-create')
            text(w,'identity','id','Invalid ID')
            capture('14-dark-narrow-invalid');assert not w.inspector.apply_button.isEnabled()
            click(w.inspector.discard_button)
            c.select_node('action','action.lab-1');w.open_inspector()
            w.inspector.sections['identity'].set_expanded(False);w.inspector.sections['common'].set_expanded(False)
            rows=w.inspector.sections['states'];rows.set_expanded(True)
            capture('15-dark-compact-states')
            w.inspector.scroll.ensureWidgetVisible(rows.toggle);rows.toggle.setFocus();app.processEvents()
            QTest.keyClick(rows.toggle,Qt.Key.Key_F1)
            assert c.help.current().resolved_topic_id=='inspector.fold_sections'
            click(w.help_widget.findChild(QPushButton,'helpPin'));capture('16-help-pinned')
        else:
            click(w.inspector.discard_button)
    assert c.session is session and session.path is not None
    report=dict(platform=app.platformName(),dpr=w.devicePixelRatioF(),temporary_project_only=True,
                checks=['vier SDK-Typen über Create-Button','Common- und Spezialfelder','ID vor/nach Commit',
                        'ein replace je Lifecycleintent','unplatziert','Edit/Apply/Save','Delete-Bestätigung Standard Cancel',
                        'Undo/Redo gleiche Session','Fresh Load','referenziertes Delete abgelehnt',
                        'Accordion ohne Datenänderung','Stale vor Apply','Dirty-Cancel erhält Werte'],
                lifecycle_commits=commits,screenshots=shots,checkpoint_snapshots=checkpoints)
    if destination:
        (destination/'visual-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'PASS: nativer Create → Edit → Apply → Save → Delete → Undo/Redo; {len(shots)} Windows-Aufnahmen; Originalprojekt unverändert.',flush=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke',action='store_true');parser.add_argument('--evidence',type=Path)
    args=parser.parse_args();app=QApplication.instance() or QApplication([])
    source=ROOT/'examples/project_logitech_native_v1.json';original=source.read_bytes()
    with tempfile.TemporaryDirectory(prefix='action-lifecycle-lab-') as tmp:
        path=Path(tmp)/'native.json';path.write_bytes(original)
        w=NativeStudioShell(path);w.show();app.processEvents()
        try:
            if args.smoke or args.evidence:workflow(app,w,args.evidence)
            else:return app.exec()
            assert source.read_bytes()==original
        finally:
            w.hide();w.deleteLater();app.processEvents()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
