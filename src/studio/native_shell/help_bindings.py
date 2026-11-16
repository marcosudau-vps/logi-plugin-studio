"""Declarative, window-local help contributions and current UI context projection.

Only the host translates controls to HelpContext. Accepted widgets and the help
framework remain passive. No application-wide event/focus hook is installed.
"""
from __future__ import annotations

from pathlib import Path
import re

from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QInputDialog,
                               QMessageBox, QWidget)
from shiboken6 import isValid

from studio.context_help import HelpContext, load_help_entries

RESOURCES = Path(__file__).parents[1] / 'context_help/resources'
CONTRIBUTIONS = {
    'folders': 'folder_topics.de.json',
    'inspector': 'inspector_topics.de.json',
    'explorer': 'explorer_topics.de.json',
    'catalog': 'catalog_topics.de.json',
    'problems': 'problems_topics.de.json',
    'native_shell': 'native_shell_topics.de.json',
}


def register_topics(registry):
    """Keep every default ID, assigning each entry exactly one module owner."""
    groups = {source: [] for source in (*CONTRIBUTIONS, 'prepared')}
    for entry in load_help_entries(RESOURCES / 'default_topics.de.json'):
        source = ('catalog' if entry.topic_id.startswith(('catalog', 'action.')) else
                  'problems' if entry.topic_id.startswith('problems') else
                  'native_shell' if entry.topic_id == 'studio.help' else 'prepared')
        groups[source].append(entry)
    for source, filename in CONTRIBUTIONS.items():
        groups[source].extend(load_help_entries(RESOURCES / filename))
    for source, entries in groups.items():
        registry.register_many(entries, source=source)  # V-43


def safe_fact(value):
    """Bound native identity text; never project dialog input, paths or log bodies."""
    return ''.join(c for c in str(value) if c.isprintable())[:160]


def selection_context(host):
    if host.selection is None or not host._exists(*host.selection):
        return HelpContext('studio.help')
    kind, identity = host.selection
    topic = {'plugin': 'explorer.plugin', 'action': 'action.definition',
             'handler': 'explorer.handler', 'folder': 'explorer.folder',
             'folder_entry': 'explorer.folder_entry'}[kind]
    facts = (('Entität', safe_fact(f'{kind}: {identity}')),)
    action = host.selected_action()
    if kind == 'folder_entry' and action:
        facts += (('Action-ID', safe_fact(action.id)),)
    if action and host.action_parameter is not None and any(
            p.name == host.action_parameter for p in action.parameters):
        topic = 'catalog.parameter'
        facts += (('actionParameter', safe_fact(host.action_parameter)),)
    return HelpContext(topic, facts)


# Explicit Qt objects are resolved from these stable host/widget attributes.
# Dynamic resolver names below also document the possible facts in coverage-after.
CONTROL_BINDINGS = (
    ('explorer.search_edit', 'explorer.search', 'explorer_search'),
    ('explorer.reset_button', 'explorer.search', 'explorer_search'),
    ('explorer.tree', 'explorer', 'explorer_selection'),
    ('explorer.empty_page', 'explorer', None),
    ('catalog.search_edit', 'catalog.search', 'catalog_filter'),
    ('catalog.reset_filter_button', 'catalog.search', 'catalog_filter'),
    ('catalog.type_combo', 'catalog.type_filter', 'catalog_filter'),
    ('catalog.sort_button', 'catalog.sort', 'catalog_sort'),
    ('catalog.catalog_tree', 'catalog', 'catalog_selection'),
    ('catalog.empty_page', 'catalog', 'catalog_filter'),
    ('catalog.edit_button', 'catalog.edit', 'edit'),
    ('catalog.new_action_button', 'inspector.create', None),
    ('problems.search_field', 'problems.filters', 'problem_filter'),
    ('problems.empty_reset', 'problems.filters', 'problem_filter'),
    ('problems.problems_table', 'problems', 'diagnostic'),
    ('problems.detail_view', 'problems.diagnostic', 'diagnostic'),
    ('problems.empty_page', 'problems.empty', 'problem_filter'),
    ('details', 'native_shell.details', 'selection'),
    ('keypad.panel', 'keypad.overview', None),
)
TOOLBAR_BINDINGS = (
    ('folder_save', 'folders.studio'),
    ('open', 'native_shell.open'), ('save', 'native_shell.save'),
    ('undo', 'native_shell.undo'), ('redo', 'native_shell.redo'),
    ('rename', 'native_shell.rename'), ('reload', 'native_shell.reload'),
    ('ict', 'symbol.ict'), ('help', 'studio.help'),
)


class NativeHelpBindings(QObject):
    def __init__(self, window, toolbar):
        super().__init__(window)
        self.window = window
        self.host = window.coordinator
        self.bindings = {}
        self.actions = {}
        for path, topic, facts in CONTROL_BINDINGS:
            obj = window
            for attr in path.split('.'):
                obj = getattr(obj, attr)
            self.bindings[obj] = (topic, facts)
        for category, button in window.problems.severity_buttons.items():
            self.bindings[button] = ('problems.filters', 'problem_filter')
        self.bindings[window.problems.problems_table.horizontalHeader()] = ('problems.sort', None)
        self.bindings[window.tabs.tabBar()] = ('native_shell.tabs', 'tabs')
        for key, topic in TOOLBAR_BINDINGS:
            action = getattr(window, key + '_action')
            button = toolbar.widgetForAction(action)
            button.setObjectName('nativeHelpToolbar.' + key)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.bindings[button] = (topic, 'toolbar')
            self.actions[button] = action
            action.setToolTip(self.host.registry.get(topic).summary)
        window.catalog.new_action_button.setToolTip(
            self.host.registry.get('inspector.create').summary)
        self._install(window)
        for obj, signal in ((window.explorer.search_edit, 'textChanged'),
                            (window.catalog.search_edit, 'textChanged'),
                            (window.catalog.type_combo, 'currentIndexChanged'),
                            (window.catalog.sort_button, 'toggled'),
                            (window.problems.search_field, 'textChanged')):
            getattr(obj, signal).connect(lambda *_, control=obj: self.update(control))  # V-45
        for button in window.problems.severity_buttons.values():
            button.toggled.connect(lambda checked, control=button: checked and self.update(control))
        for tree in (window.explorer.tree, window.catalog.catalog_tree):
            tree.itemSelectionChanged.connect(lambda control=tree: self.update(control))
        window.tabs.currentChanged.connect(self._tab_changed)
        window.problems.problems_table.horizontalHeader().sortIndicatorChanged.connect(
            lambda *_: self.update(window.problems.problems_table.horizontalHeader()))

    def _install(self, obj):
        # A ChildAdded object can still be exposed as QObject during its C++
        # constructor (notably QDialog). Install now; inspect QWidget only on input.
        obj.installEventFilter(self)
        for child in obj.children():
            if child is not self:
                self._install(child)

    def _owned(self, widget):
        # QWidget.isAncestorOf stops at child window boundaries. Owned dialogs
        # have a parentWidget chain too, and must retain their own F1 context.
        while widget is not None:
            if widget is self.window:
                return True
            widget = widget.parentWidget()
        return False

    def context_for(self, widget):
        if not isinstance(widget, QWidget) or not self._owned(widget):
            return HelpContext('studio.help')
        while widget is not None and widget is not self.window:
            topic = widget.property('inspectorTopic')
            if topic and self._registered(topic):
                return HelpContext(topic)
            if isinstance(widget, QDialog):
                composer = getattr(self.window, 'composer', None)
                ancestor = widget.parentWidget()
                while ancestor is not None and ancestor is not self.window:
                    if ancestor is composer:
                        return HelpContext('folders.studio')
                    ancestor = ancestor.parentWidget()
                topic = ('native_shell.rename' if isinstance(widget, QInputDialog) else
                         'native_shell.open' if isinstance(widget, QFileDialog) else
                         'native_shell.unsaved' if isinstance(widget, QMessageBox) else 'studio.help')
                return HelpContext(topic)  # No dialog input or file path facts. V-48
            topic = widget.property('inspectorTopic')
            if topic and self._registered(topic):
                return HelpContext(topic)  # No unvalidated draft data in facts.
            name = widget.objectName()
            if name == 'helpPin':
                return HelpContext('help.pin', (('Angeheftet', str(self.host.help.current().pinned)),))
            if name == 'helpDetailsToggle':
                return HelpContext('help.details')
            if name.startswith('helpRelated.'):
                topic = name.removeprefix('helpRelated.')
                return HelpContext('help.related', (('Zielthema', topic),)) if self._registered(topic) else HelpContext('studio.help')
            if name == 'problemsContextMenu':
                return HelpContext('problems.diagnostic')
            if widget in self.bindings:
                topic, resolver = self.bindings[widget]
                return self._resolve(widget, topic, resolver)
            if widget is self.window.help_widget:
                return HelpContext('studio.help')
            widget = widget.parentWidget()
        return HelpContext('studio.help')

    def _registered(self, topic):
        try:
            return self.host.registry.get(topic) is not None
        except (TypeError, ValueError):
            return False

    def _resolve(self, widget, topic, resolver):
        w, c = self.window, self.host
        facts = ()
        if resolver == 'explorer_selection':
            context = selection_context(c)
            return HelpContext('explorer') if c.selection is None else context
        if resolver == 'selection':
            facts = selection_context(c).facts
        if resolver == 'explorer_search':
            facts = (('Suchlänge', str(len(w.explorer.search_edit.text()))),)
        if resolver == 'catalog_selection':
            key = w.catalog.selected_key()
            if key and c._exists('action', key[0]):
                topic = 'catalog.parameter' if key[1] is not None else 'action.definition'
                facts = (('Entität', safe_fact('action: ' + key[0])),)
                if key[1] is not None and w.catalog.offer_for(*key):
                    facts += (('actionParameter', safe_fact(key[1])),)
            else:
                facts = (('Sichtbare Angebote', str(len(w.catalog.visible_keys()))),)
        if resolver == 'catalog_filter':
            facts = (('Suchlänge', str(len(w.catalog.search_edit.text()))),
                     ('SDK-Typ', w.catalog.type_combo.currentText()),
                     ('Sichtbare Angebote', str(len(w.catalog.visible_keys()))))
        if resolver == 'catalog_sort':
            facts = (('Reihenfolge', 'Name' if w.catalog.sort_button.isChecked() else 'Projekt'),)
        if resolver == 'edit':
            action = c.selected_action()
            facts = (('Verfügbar', str(widget.isEnabled())),)
            if action:
                facts += (('Action-ID', safe_fact(action.id)),)
        if resolver in ('problem_filter', 'diagnostic'):
            facts = (('Schweregrad', w.problems.severity_filter()),
                     ('Suchlänge', str(len(w.problems.filter_text()))),
                     ('Sichtbare Meldungen', str(len(w.problems.visible_entries()))))
            if resolver == 'diagnostic':
                indexes = w.problems.problems_table.selectionModel().selectedRows()
                entries = w.problems.visible_entries()
                if indexes and 0 <= indexes[0].row() < len(entries):
                    diagnostic = entries[indexes[0].row()][1]
                    # Do not echo arbitrary diagnostic.path/message/source in help.
                    if re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', diagnostic.code):
                        facts += (('Code', diagnostic.code),)
                    topic = 'problems.diagnostic'
                else:
                    topic = 'problems.empty' if w.problems.empty_state() else 'problems'
            if w.problems.empty_state():
                facts += (('Leerzustand', w.problems.empty_state()),)
        if resolver == 'toolbar':
            facts = (('Verfügbar', str(self.actions[widget].isEnabled())),)
            if topic == 'native_shell.save':
                facts += (('Ungespeichert', str(bool(c.session and c.session.dirty))),)
        if resolver == 'tabs':
            facts = (('Tabindex', str(w.tabs.currentIndex())),)
        return HelpContext(topic, facts)

    def update(self, widget):
        if self.host._syncing:
            return
        if self.window.help_widget is widget or self.window.help_widget.isAncestorOf(widget):
            return  # Keep the article and its focused controls operable. V-47
        self.host.help.set_context(self.context_for(widget))

    def _tab_changed(self, index):
        widget = self.window.tabs.widget(index)
        if widget is getattr(self.window, 'composer', None):
            self.update(widget)
            return
        if widget is self.window.keypad.panel:
            self.update(widget)
        elif widget is self.window.problems:
            self.update(self.window.problems.problems_table)

    def request_help(self, focused=None):
        modal = QApplication.activeModalWidget()
        if modal is not None and self._owned(modal):
            focused = modal.focusWidget() or modal
        context = self.context_for(focused or self.window.focusWidget())
        self.window.tabs.setCurrentWidget(self.window.help_widget)
        # Hiding a focused detail/table can move focus to a toolbar control.
        # Publish the explicit request after that synchronous focus transition.
        self.host.help.request_help(context)  # V-46

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind in (QEvent.Type.ChildAdded, QEvent.Type.ChildPolished):
            self._install(event.child())
        if (kind in (QEvent.Type.FocusIn, QEvent.Type.ToolTip, QEvent.Type.KeyPress)
                and isValid(self.window) and isinstance(watched, QWidget) and self._owned(watched)):
            if kind == QEvent.Type.FocusIn:
                self.update(watched)  # V-44
            elif kind == QEvent.Type.ToolTip and (watched in self.bindings or watched.property('inspectorTopic')):
                self.update(watched)  # Disabled buttons still explain their boundary.
            elif kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_F1:
                self.request_help(watched)
                return True
        return super().eventFilter(watched, event)
