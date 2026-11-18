"""Structured Qt forms. Emits intentions, never touches sessions or files."""
from __future__ import annotations
from copy import deepcopy
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLineEdit, QPlainTextEdit, QComboBox, QPushButton, QLabel, QScrollArea, QMessageBox, QToolButton, QSizePolicy)
from .draft import ActionDraft, DraftError, DraftDiagnostic
from .lifecycle import CreateDraft
from adapters.logitech.native import ACTION_TYPES

CONTROL_TYPES = ('textbox', 'checkbox', 'textarea', 'file_selector', 'directory_selector', 'slider', 'numeric_up_down')
MISSING = object()
LABELS = {'id':'Aktions-ID', 'sdk_type':'SDK-Typ', 'display_name':'Anzeigename', 'description':'Beschreibung', 'group_name':'Gruppe',
 'super_group_name':'Übergeordnete Gruppe', 'handler':'Handler', 'name':'Name', 'label':'Beschriftung',
 'image':'Bildreferenz (.png/.svg)', 'minimum':'Minimum', 'maximum':'Maximum', 'default':'Standardwert',
 'step':'Schrittweite', 'format':'Format', 'format_string':'Zahlenformat', 'has_reset':'Reset verfügbar',
 'dialog_title':'Dialogtitel', 'initial_directory':'Startverzeichnis', 'pattern':'Dateimuster',
 'icon':'Icon (.png/.svg)', 'icon_template':'Iconvorlage (.ict)', 'symbol':'Symbol (.svg)',
 'type':'Control-Typ', 'state_change':'Zustandswechsel'}


def help_topic(widget, topic):
    widget.setProperty('inspectorTopic', 'inspector.' + topic)
    widget.setToolTip('F1 öffnet die Hilfe für diesen Bereich. Änderungen werden erst mit Übernehmen geprüft übernommen.')
    return widget


class ValueField(QWidget):
    changed = Signal()
    def __init__(self, key, value=MISSING, *, kind='text', choices=(), optional=False, topic='overview'):
        super().__init__()
        self.key, self.kind, self._original = key, kind, value
        self.setObjectName('inspector.' + key)
        help_topic(self, topic)
        layout = QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        self.mode = None
        if optional:
            self.mode = QComboBox()
            self.mode.addItems(['Nicht gesetzt / entfernen', 'Null', 'Wert'])
            self.mode.setCurrentIndex(0 if value is MISSING else 1 if value is None else 2)
            layout.addWidget(self.mode)
        if choices or kind == 'bool':
            self.input = QComboBox()
            self.input.addItems(list(choices) if choices else ['false', 'true'])
            self.input.setCurrentText(str(value).lower() if kind == 'bool' else str(value if value is not MISSING else ''))
            signal = self.input.currentTextChanged
        elif kind == 'multiline':
            self.input = QPlainTextEdit('' if value is MISSING or value is None else str(value))
            self.input.setMaximumHeight(85)
            signal = self.input.textChanged
        else:
            self.input = QLineEdit('' if value is MISSING or value is None else str(value))
            if kind == 'number': self.input.setPlaceholderText('Endliche Zahl, z. B. 0.5')
            signal = self.input.textChanged
        self.input.setAccessibleName(LABELS.get(key,key))
        layout.addWidget(self.input)
        self.error = QLabel(); self.error.setWordWrap(True); self.error.setTextFormat(Qt.TextFormat.PlainText)
        help_topic(self.error, 'invalid'); layout.addWidget(self.error); self.error.hide()
        signal.connect(self.changed)
        if self.mode:
            self.mode.currentIndexChanged.connect(self._mode_changed)
            self.input.setEnabled(self.mode.currentIndex() == 2)
    def _mode_changed(self):
        self.input.setEnabled(self.mode.currentIndex() == 2); self.changed.emit()
    def value(self):
        if self.mode and self.mode.currentIndex() != 2:
            return MISSING if self.mode.currentIndex() == 0 else None
        text = self.input.toPlainText() if isinstance(self.input,QPlainTextEdit) else self.input.currentText() if isinstance(self.input,QComboBox) else self.input.text()
        if self.kind == 'bool': return text == 'true'
        if self.kind == 'number':
            try: return float(text)
            except ValueError: return text  # Invalid drafts stay visible; parser diagnoses them.
        return text


class FoldSection(QWidget):
    """Sichtbarkeit ohne Neubau, Serialisierung oder Fachsignal ändern."""
    def __init__(self, title, topic, expanded=False):
        super().__init__()
        self._title = title
        self.section_layout = QVBoxLayout(self)
        self.section_layout.setContentsMargins(0, 2, 0, 2)
        self.toggle = help_topic(QToolButton(), 'fold_sections')
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.toggle.setMinimumHeight(28)
        self.toggle.setAccessibleName(title + ' ein- oder ausklappen')
        self.section_layout.addWidget(self.toggle)
        self.details_body = QWidget()
        self.section_layout.addWidget(self.details_body)
        self.toggle.toggled.connect(self._toggle)
        help_topic(self, topic)
        self.set_summary(title)
        self.set_expanded(expanded)
    def set_summary(self, text):
        self._title = text
        self.toggle.setText(text.replace('&', '&&'))
        self.toggle.setToolTip(text + '\nF1: Abschnittsbedienung')
        self.toggle.setAccessibleName(text + ' ein- oder ausklappen')
    def set_expanded(self, expanded):
        self.toggle.setChecked(expanded)
        self._toggle(expanded)
    def _toggle(self, expanded):
        self.details_body.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.toggle.setAccessibleDescription('Ausgeklappt' if expanded else 'Eingeklappt')


class ObjectForm(FoldSection):
    changed = Signal()
    def __init__(self, title, raw, specs, topic):
        super().__init__(title, topic)
        self.raw = deepcopy(raw); self.fields = {}; self.topic = topic
        self.section_title = title
        help_topic(self,topic)
        self.form = QFormLayout(self.details_body)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for key, kind, optional, choices in specs:
            field = ValueField(key, self.raw.get(key,MISSING), kind=kind, optional=optional, choices=choices, topic=topic)
            self.fields[key] = field
            self.form.addRow(LABELS.get(key,key), field)
            field.changed.connect(lambda k=key: self._edit(k))
    def _edit(self,key):
        value = self.fields[key].value()
        if value is MISSING: self.raw.pop(key,None)
        else: self.raw[key] = value
        self.changed.emit()


def spec(key, kind='text', optional=False, choices=()): return (key,kind,optional,choices)


class RowsEditor(FoldSection):
    changed = Signal()
    def __init__(self, title, rows, category, handlers=()):
        super().__init__(title, 'editor_controls' if category=='filters' else category)
        self.title = title
        self.category = category; self.rows = deepcopy(rows or []); self.forms = []
        help_topic(self, 'editor_controls' if category=='filters' else category)
        self.layout_ = QVBoxLayout(self.details_body)
        self.add_button = QPushButton('Zeile hinzufügen')
        self.add_button.setObjectName('inspector.add.'+category)
        self.layout_.addWidget(self.add_button)
        self.add_button.setAccessibleName(title + ': Zeile hinzufügen')
        self.add_button.clicked.connect(self.add_row)
        self.body = QWidget(); self.body_layout = QVBoxLayout(self.body); self.body_layout.setContentsMargins(0,0,0,0)
        self.layout_.addWidget(self.body)
        self.rebuild()
    def specs(self,row):
        if self.category == 'parameters':
            return [spec(k,optional=k=='super_group_name') for k in ('name','display_name','group_name','super_group_name')]
        if self.category == 'states':
            return [spec('name'),spec('display_name'),spec('description','multiline'),spec('image',optional=True)]
        if self.category == 'parameter_symbols': return [spec('name'),spec('symbol')]
        if self.category == 'filters': return [spec('pattern'),spec('label')]
        fields = [spec('type',choices=CONTROL_TYPES),spec('name'),spec('label'),spec('description','multiline',True)]
        typ = row['type']
        if typ == 'checkbox': fields += [spec('default','bool',True)]
        if typ in ('slider','numeric_up_down'):
            fields += [spec(k,'number') for k in ('minimum','maximum','step','default')] + [spec('format_string',optional=True)]
        if typ in ('file_selector','directory_selector'):
            fields += [spec('dialog_title',optional=True),spec('initial_directory',optional=True)]
        return fields
    def rebuild(self):
        while self.body_layout.count():
            w = self.body_layout.takeAt(0).widget(); w.hide(); w.deleteLater()
        self.forms = []
        self.set_summary(f'{self.title} · {len(self.rows)} Einträge')
        for i,row in enumerate(self.rows):
            form = ObjectForm(f'Zeile {i+1}' + (f' · SDK-Index {i}' if self.category=='states' else ''),row,self.specs(row),self.category)
            form.setObjectName(f'inspector.row.{self.category}.{i}')
            form.set_summary(self.summary(i, row))
            self.forms.append(form); self.body_layout.addWidget(form)
            form.changed.connect(lambda index=i: self._row_changed(index))
            if self.category == 'editor_controls' and row['type']=='file_selector':
                filters = RowsEditor('Dateifilter',row.get('filters',[]),'filters')
                help_topic(filters,'editor_controls')
                filters.changed.connect(lambda index=i,f=filters: self._filters_changed(index,f))
                form.form.addRow(filters); form.filters_editor = filters
            buttons = QWidget(); line = QHBoxLayout(buttons); line.setContentsMargins(0,0,0,0)
            for title,delta in (('↑',-1),('↓',1),('Entfernen',0)):
                b = QPushButton(title); line.addWidget(b)
                b.setAccessibleName(self.category + ': ' + title + ' Zeile ' + str(i+1))
                b.setObjectName(f'inspector.row.{self.category}.{i}.{delta}')
                b.setEnabled(delta==0 or 0<=i+delta<len(self.rows))
                b.clicked.connect(lambda checked=False,index=i,d=delta:self.move_or_remove(index,d))
            form.form.addRow(buttons)
    def summary(self, index, row):
        name = str(row.get('name') or row.get('pattern') or 'Ohne Name')
        detail = ('State ' + str(index) if self.category == 'states' else
                  str(row.get('type') or row.get('display_name') or row.get('label') or row.get('symbol') or ''))
        return f'{index+1}. {name} · {detail}'
    def _filters_changed(self,i,filters):
        self.rows[i]['filters'] = deepcopy(filters.rows)
        self.forms[i].raw['filters'] = deepcopy(filters.rows)
        self.changed.emit()
    def _row_changed(self,i):
        new = deepcopy(self.forms[i].raw)
        if self.category=='editor_controls' and new['type'] != self.rows[i]['type']:
            old = self.rows[i]
            allowed = {s[0] for s in self.specs(new)} | ({'filters'} if new['type']=='file_selector' else set())
            lost = set(new)-allowed
            # A default may exist in both types but have incompatible semantics.
            if old['type'] != new['type'] and 'default' in new: lost.add('default')
            if lost:
                answer = QMessageBox.warning(self,'Control-Typ wechseln',
                    'Beim Typwechsel werden diese Optionen entfernt: '+', '.join(sorted(lost))+'. Fortfahren?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
                if answer != QMessageBox.StandardButton.Yes:
                    self.rebuild(); return
                for k in lost: new.pop(k,None)
            if new['type'] in ('slider','numeric_up_down'):
                for k,v in {'minimum':0,'maximum':100,'step':1,'default':0}.items(): new.setdefault(k,v)
            self.rows[i]=new; self.rebuild()
        else: self.rows[i]=new
        self.forms[i].set_summary(self.summary(i, self.rows[i]))
        self.changed.emit()
    def add_row(self):
        n=len(self.rows)+1
        defaults = {'parameters':{'name':f'parameter{n}','display_name':f'Parameter {n}','group_name':'Parameter'},
          'states':{'index':n-1,'name':f'state{n}','display_name':f'Zustand {n}','description':''},
          'editor_controls':{'type':'textbox','name':f'control{n}','label':f'Feld {n}'},
          'parameter_symbols':{'name':'','symbol':''}, 'filters':{'pattern':'*.png','label':'Bilder'}}
        self.rows.append(defaults[self.category]); self.rebuild()
        self.set_expanded(True); self.forms[-1].set_expanded(True); self.changed.emit()
    def move_or_remove(self,i,delta):
        if delta: self.rows[i],self.rows[i+delta] = self.rows[i+delta],self.rows[i]
        else: self.rows.pop(i)
        self.rebuild(); self.changed.emit()


class ActionInspectorWidget(QWidget):
    applyRequested = Signal(str,str,object)
    draftDirtyChanged = Signal(bool)
    discardRequested = Signal()
    diagnosticsChanged = Signal(object)
    createRequested = Signal(str,str,object)
    deleteRequested = Signal()
    refreshRequested = Signal()
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setObjectName('actionInspector'); help_topic(self,'overview')
        self.draft = None; self.sections = {}; self._last_dirty=False
        self.stale = False; self._context = None; self._conflict = False
        self.empty_message = 'Vorhandene Aktion auswählen.'
        layout=QVBoxLayout(self)
        self.status = QLabel('Vorhandene Aktion auswählen.'); self.status.setTextFormat(Qt.TextFormat.PlainText); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.stale_band = help_topic(QWidget(), 'stale')
        band = QVBoxLayout(self.stale_band); band.setContentsMargins(6, 6, 6, 6)
        self.stale_label = QLabel(); self.stale_label.setWordWrap(True)
        self.stale_label.setTextFormat(Qt.TextFormat.PlainText)
        band.addWidget(self.stale_label)
        self.refresh_button = help_topic(QPushButton('Entwurf verwerfen / aktuelle Daten neu laden'), 'refresh')
        self.stay_button = help_topic(QPushButton('Im Entwurf bleiben'), 'stale')
        band.addWidget(self.refresh_button); band.addWidget(self.stay_button)
        self.refresh_button.clicked.connect(self.refreshRequested)
        self.stay_button.clicked.connect(lambda: self.scroll.setFocus())
        layout.addWidget(self.stale_band); self.stale_band.hide()
        self.delete_info = help_topic(QLabel(), 'delete'); self.delete_info.setWordWrap(True)
        self.delete_info.setTextFormat(Qt.TextFormat.PlainText); self.delete_info.setFocusPolicy(Qt.FocusPolicy.StrongFocus); layout.addWidget(self.delete_info)
        self.scroll=QScrollArea(); self.scroll.setWidgetResizable(True); layout.addWidget(self.scroll,1)
        self.body=QWidget(); self.content=QVBoxLayout(self.body); self.scroll.setWidget(self.body)
        self.errors=QLabel(); self.errors.setWordWrap(True); self.errors.setTextFormat(Qt.TextFormat.PlainText)
        help_topic(self.errors,'invalid'); layout.addWidget(self.errors)
        buttons=QHBoxLayout(); layout.addLayout(buttons)
        self.apply_button=help_topic(QPushButton('Übernehmen'),'apply')
        self.discard_button=help_topic(QPushButton('Verwerfen'),'discard')
        self.delete_button=help_topic(QPushButton('Aktion löschen …'),'delete')
        self.delete_button.clicked.connect(self.deleteRequested)
        buttons.addWidget(self.apply_button); buttons.addWidget(self.discard_button); buttons.addWidget(self.delete_button)
        self.delete_button.setEnabled(False)
        self.apply_button.clicked.connect(self.request_apply); self.discard_button.clicked.connect(self.discard)
        self._validate()
    @property
    def dirty(self): return bool(self.draft and (self.draft.dirty or getattr(self,'_invalid_symbols',False)))
    def set_action(self,project,action_id,raw_action,revision,project_token=None):
        if self.dirty: raise DraftError('Offenen Formularentwurf zuerst übernehmen oder verwerfen.')
        draft = ActionDraft(project,action_id,raw_action,revision,project_token) if action_id else None
        self.empty_message = 'Vorhandene Aktion auswählen.'
        self.draft=draft; self._invalid_symbols=False; self.stale=False; self._conflict=False; self._context=None; self._build()
    @property
    def creating(self):
        return isinstance(self.draft, CreateDraft)
    def start_create(self, project, revision, project_token):
        if self.dirty: raise DraftError('Offenen Formularentwurf zuerst behandeln.')
        self.draft = CreateDraft(project, revision, project_token)
        self._invalid_symbols=False; self.stale=False; self._conflict=False; self._context=None
        self.set_delete_state(None)
        self._build()
    def observe_context(self, revision, project_token, conflict=False):
        context = (revision, project_token, conflict)
        if context == self._context: return
        self._context = context
        self._conflict = conflict
        self.stale = bool(self.draft and (self.draft.base_revision != revision or
                          self.draft.project_token != project_token or conflict))
        self._validate()
    def set_delete_state(self, check):
        self.delete_button.setEnabled(bool(check and check.allowed and not self.creating))
        self.delete_info.setText(('Löschen: ' + check.action_id + '\n' + check.reason) if check and check.reason else '')
        topic = 'delete_references' if check and check.references else 'delete_last' if check and check.reason else 'delete'
        help_topic(self.delete_info, topic); help_topic(self.delete_button, topic)
        self.delete_button.setToolTip(check.reason if check and check.reason else 'Ausgewählte Aktions-ID nach ausdrücklicher Bestätigung löschen.')
    def _change_type(self):
        value = self.sections['identity'].fields['sdk_type'].value()
        if value == self.draft.snapshot()['sdk_type']: return
        raw = self.draft.snapshot()
        special = {k:raw[k] for k in ('states','state_change','adjustment','editor_controls') if k in raw}
        original = {k:self.draft._original[k] for k in special if k in self.draft._original}
        if special != original:
            answer = QMessageBox.warning(self, 'SDK-Typ wählen', 'Die typspezifischen Eingaben werden durch gültige Startwerte ersetzt. Fortfahren?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Yes:
                field=self.sections['identity'].fields['sdk_type'].input
                field.blockSignals(True); field.setCurrentText(raw['sdk_type']); field.blockSignals(False)
                return
        self.draft.change_type(value); self._build()
    def _build(self):
        while self.content.count():
            w=self.content.takeAt(0).widget()
            if w: w.hide(); w.deleteLater()
        self.sections={}
        if not self.draft: self._validate(); return
        raw=self.draft.snapshot()
        identity=ObjectForm('Neue Aktion · SDK-Identität' if self.creating else 'SDK-Identität',raw,[spec('id'),spec('sdk_type',choices=tuple(sorted(ACTION_TYPES)) if self.creating else ())],'create' if self.creating else 'identity')
        identity.set_expanded(True)
        if self.creating:
            help_topic(identity.fields['id'], 'create_id'); help_topic(identity.fields['sdk_type'], 'create_type')
            identity.fields['id'].changed.connect(lambda: self._create_id_changed(identity))
            identity.fields['sdk_type'].changed.connect(self._change_type)
        else:
            for f in identity.fields.values(): f.input.setReadOnly(True)
        self.content.addWidget(identity); self.sections['identity']=identity
        self._object('common','Allgemein',raw,[spec('display_name'),spec('description','multiline',True),spec('group_name',optional=True)],'overview')
        self._object('handler','Handler',raw,[spec('handler',choices=self.draft.handler_ids)],'handler')
        self._rows('parameters','Parameter',raw.get('parameters'))
        self._rows('parameter_symbols','Parameter → SVG-Referenz',[{'name':k,'symbol':v} for k,v in raw.get('parameter_symbols',{}).items()])

        self._object('assets','Asset-Referenzen',raw,[spec(k,optional=True) for k in ('icon','icon_template','symbol')],'assets')
        if raw['sdk_type']=='PluginMultistateDynamicCommand':
            self._rows('states','SDK-Zustände',raw['states'])
            self._object('state_change','Zustandswechsel',raw,[spec('state_change',optional=True,choices=('none','increment','decrement','toggle'))],'state_change')
        if raw['sdk_type']=='PluginDynamicAdjustment':
            self._object('adjustment','Einstellung',raw.get('adjustment') or {},[spec('has_reset','bool',True)]+[spec(k,'number',True) for k in ('minimum','maximum','default')]+[spec('format',optional=True)],'adjustment')
        if raw['sdk_type']=='ActionEditorCommand': self._rows('editor_controls','SDK-Editorfelder',raw.get('editor_controls'))
        self.content.addStretch(); self._validate()
    def _object(self,key,title,raw,specs,topic):
        form=ObjectForm(title,raw,specs,topic); form.setObjectName('inspector.section.'+key); self.sections[key]=form; self.content.addWidget(form)
        form.set_expanded(key == 'common')
        form.changed.connect(lambda:self._object_changed(key,form))
    def _create_id_changed(self, form):
        self.draft.set_field('id', form.fields['id'].value()); self._validate()
    def _object_changed(self,key,form):
        if key=='adjustment': self.draft.set_field(key,form.raw)
        else:
            for name,field in form.fields.items():
                value=field.value()
                # Touch only actual edits, preserving every absent/null/raw sibling.
                old=form.raw.get(name,MISSING)
                original=self.draft.snapshot().get(name,MISSING)
                if old is MISSING:
                    if original is not MISSING: self.draft.remove_field(name)
                elif original is MISSING or old!=original: self.draft.set_field(name,old)
        self._validate()
    def _rows(self,key,title,rows):
        editor=RowsEditor(title,rows,key); editor.setObjectName('inspector.section.'+key); self.sections[key]=editor; self.content.addWidget(editor)
        editor.changed.connect(lambda:self._rows_changed(key,editor))
    def _rows_changed(self,key,editor):
        if key=='parameter_symbols':
            names=[r['name'] for r in editor.rows]
            if len(names)!=len(set(names)):
                self._invalid_symbols=True
                self._validate(); return
            self._invalid_symbols=False
            self.draft.set_field(key,{r['name']:r['symbol'] for r in editor.rows})
        else: self.draft.set_rows(key,editor.rows)
        self._validate()
    def _validate(self):
        errors=self.draft.diagnostics() if self.draft else ()
        if getattr(self,'_invalid_symbols',False):
            errors += (DraftDiagnostic('/parameter_symbols','Symbolzuordnung: Parameternamen müssen eindeutig sein.'),)
        self.errors.setText('\n'.join(e.path+': '+e.message for e in errors))
        mode = 'Neue Aktion · unplatziert. Übernehmen erstellt die Definition ohne Folder-Belegung. ' if self.creating else 'Bearbeiten · ' if self.draft else ''
        help_topic(self.status, 'unplaced' if self.creating else 'overview')
        self.status.setText(mode + ('Formular geändert, aber noch nicht übernommen' if self.dirty else 'Formular unverändert' if self.draft else self.empty_message))
        self.stale_band.setVisible(self.stale)
        self.stale_label.setText('⚠ Veraltete Sessionrevision: Formular basiert auf einem älteren Projektstand. Eingaben bleiben erhalten; Übernehmen ist gesperrt.' if not self._conflict else '⚠ Projektdatei extern verändert. Eingaben bleiben erhalten; Übernehmen ist gesperrt. Vor weiteren Änderungen Projekt bewusst neu laden.')
        self.errors.setVisible(bool(errors))
        if self.stale: self.errors.setText(self.stale_label.text() + ('\n' + self.errors.text() if errors else ''))
        for key,section in self.sections.items():
            if any(e.path.startswith('/'+key) for e in errors): section.set_expanded(True)
            forms=section.forms if isinstance(section,RowsEditor) else [section]
            for index,form in enumerate(forms):
                if isinstance(section,RowsEditor):
                    row_error=any(e.path.startswith('/'+section.category) for e in errors)
                    form.set_summary(('⚠ ' if row_error else '') + section.summary(index,section.rows[index]))
                for name,field in form.fields.items():
                    relevant=[e.message for e in errors if '/'+name in e.path or (isinstance(section,RowsEditor) and '/'+section.category in e.path) or ('/'+getattr(section,'topic','') == e.path)]
                    field.error.setText('\n'.join(relevant)); field.error.setVisible(bool(relevant))
                    if relevant:
                        section.set_expanded(True); form.set_expanded(True)
        self.apply_button.setEnabled(bool(self.dirty and not self.stale and not errors and not getattr(self,'_invalid_symbols',False)))
        self.discard_button.setEnabled(self.dirty or self.stale)
        self.diagnosticsChanged.emit(errors)
        if self.dirty!=self._last_dirty:
            self._last_dirty=self.dirty; self.draftDirtyChanged.emit(self.dirty)
    def request_apply(self):
        if self.draft and self.apply_button.isEnabled():
            if self.creating:
                self.createRequested.emit(self.draft.project_token,self.draft.base_revision,self.draft.proposed_action())
            else:
                self.applyRequested.emit(self.draft.action_id,self.draft.base_revision,self.draft.proposed_action())
    def discard(self):
        if self.creating or self.stale:
            self.accept_applied(); self._build(); self.discardRequested.emit(); return
        if self.draft: self.draft.discard()
        self._invalid_symbols=False; self._build(); self.discardRequested.emit()
    def accept_applied(self):
        # Host immediately supplies the committed session snapshot.
        self.draft=None; self.stale=False; self._conflict=False; self._context=None; self._invalid_symbols=False; self._last_dirty=False; self.draftDirtyChanged.emit(False)
    def show_host_error(self,message):
        self.errors.setText('Übernehmen nicht möglich: '+str(message)); self.errors.show()
