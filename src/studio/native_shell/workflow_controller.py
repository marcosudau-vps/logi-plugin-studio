"""Host des geführten Ablaufs in der nativen Shell.

Liest Fakten aus den bestehenden Eigentümern, berechnet den Schrittstatus,
blendet Registerkarten/Seitenbereiche/Werkzeuge je Schritt ein und versorgt
die bestehende Hilfe und Problemliste. Schreibt weder Projekt noch Extension;
jede Änderung läuft über vorhandene Shell-/Coordinator-Operationen.
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QDockWidget, QMessageBox, QStyle, QWidget

from core.errors import Diagnostic
from studio.context_help import HelpContext, load_help_entries
from studio.workflow import (ERROR, STEP_KEYS, STEPS, Facts, complete, evaluate, first_incomplete, step)
from studio.native_session import NativeSessionError
from studio.workflow.facts import (asset_references, fingerprint, handler_snippet, handler_template,
                                   missing_assets, registered_handlers)
from studio.workflow.model import BLOCKING
from studio.workflow.start_page import StartPage
from studio.workflow.store import WorkflowStore
from studio.workflow.widget import WorkflowRail
from .build_integration import NativeBuildPreflightError, validate_handler
from .help_bindings import RESOURCES

#: Quellen der Problemliste, die den Projektzustand beschreiben (nicht einzelne Bedienfehler).
PROJECT_SOURCES = ("native.validation", "folders.references")
ALWAYS_TOOLS = ("new", "open", "save_all", "undo", "redo", "help")
EXPERT_TOOLS = ("save", "folder_save", "reload")
ICONS = {"new": "SP_FileIcon", "open": "SP_DialogOpenButton", "save_all": "SP_DialogSaveButton",
         "undo": "SP_ArrowBack", "redo": "SP_ArrowForward", "reload": "SP_BrowserReload",
         "help": "SP_DialogHelpButton"}
TOOL_NAMES = {"new": "Neues Projekt", "open": "Projekt öffnen", "save_all": "Alles speichern",
              "undo": "Rückgängig", "redo": "Wiederholen", "reload": "Neu laden", "help": "Hilfe (F1)"}


class WorkflowController(QObject):
    changed = Signal()

    def __init__(self, shell, toolbar, store=None):
        super().__init__(shell)
        self.shell, self.toolbar = shell, toolbar
        self.store = store if store is not None else WorkflowStore()
        self.expert = not self.store.guided()
        self.active = STEP_KEYS[0]
        self.states = evaluate(Facts())
        self._project_seen = None
        self._built = None          # Fingerabdruck des letzten erfolgreichen Builds
        self._pending = None        # Fingerabdruck beim Buildstart
        self._hardware = ""         # Fingerabdruck des bestätigten Gerätetests
        self._published = None
        self._shown = None
        self._prereq = (0.0, ())
        self._handler_cache = (None, None)
        shell.coordinator.registry.register_many(
            load_help_entries(RESOURCES / "guide_topics.de.json"), source="guide")  # V-96
        self.start_page = StartPage()
        shell.tabs.insertTab(0, self.start_page, "Start")
        self.start_page.newRequested.connect(shell.create_project)  # V-90
        self.start_page.openRequested.connect(shell.choose_project)
        from studio.handler_inspector import HandlerInspectorWidget
        self.handlers = shell.handler_panel = HandlerInspectorWidget()
        shell.tabs.insertTab(1, self.handlers, "Handler")
        self.handlers.createRequested.connect(self.create_handler)  # V-100
        self.handlers.renameRequested.connect(self.rename_handler)
        self.handlers.deleteRequested.connect(self.delete_handler)
        self.handlers.templateRequested.connect(self.create_handler_file)  # V-101
        self.handlers.chooseFileRequested.connect(shell.build_controller.choose_handler)
        self.handlers.handlerSelected.connect(lambda key: shell.coordinator.select_node("handler", key))  # V-102
        shell.coordinator.selectionChanged.connect(self._mirror_selection)
        self._handlers_shown = None
        self.rail = WorkflowRail()
        dock = QDockWidget(shell)
        dock.setObjectName("workflowDock")
        dock.setTitleBarWidget(QWidget(dock))
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        dock.setWidget(self.rail)
        shell.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, dock)
        self.dock = dock
        self.rail.stepRequested.connect(self.enter)  # V-91
        self.rail.backRequested.connect(self.back)
        self.rail.nextRequested.connect(self.next)
        self.rail.helpRequested.connect(self.show_guide)  # V-97
        self.rail.criterionActivated.connect(self.activate_criterion)  # V-95
        self.rail.expertToggled.connect(self.set_expert)  # V-94
        self.save_all_action = QAction("Alles speichern", shell)
        self.save_all_action.setObjectName("workflowSaveAllAction")
        self.save_all_action.setToolTip("Alles speichern: Projekt sowie Ordner und Belegung in ihre Dateien schreiben.")
        self.save_all_action.triggered.connect(shell.save_all)
        toolbar.insertAction(shell.save_action, self.save_all_action)
        shell.save_all_action = self.save_all_action
        self._decorate_toolbar()
        self._build_menus()
        build = shell.build_controller
        build.guards.append(self._build_guard)  # V-98
        build.listeners.append(self._build_finished)
        build.handler.textChanged.connect(self._handler_edited)
        build.mode.currentIndexChanged.connect(lambda *_: self.refresh())
        shell.coordinator.changed.connect(self.refresh)  # V-92
        shell.inspector.diagnosticsChanged.connect(lambda *_: self.refresh())
        shell.tabs.currentChanged.connect(lambda *_: self._sync_tools())
        self.timer = QTimer(self)
        self.timer.setInterval(700)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    # -- Werkzeugleiste und Menü -------------------------------------------
    def _tools(self):
        s = self.shell
        return {"new": s.new_action, "open": s.open_action, "save_all": self.save_all_action,
                "save": s.save_action, "folder_save": s.folder_save_action, "undo": s.undo_action,
                "redo": s.redo_action, "rename": s.rename_action, "reload": s.reload_action,
                "ict": s.ict_action, "build": s.build_controller.action, "help": s.help_action}

    def _decorate_toolbar(self):
        """Symbole für die Standardbefehle; Befehle ohne Symbol behalten ihren Text."""
        style = self.shell.style()
        tools = self._tools()
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for key, name in ICONS.items():
            action = tools[key]
            action.setIcon(style.standardIcon(getattr(QStyle.StandardPixmap, name)))
            summary = action.toolTip()
            action.setToolTip(TOOL_NAMES[key] + (" – " + summary if summary and summary != action.text() else ""))
            button = self.toolbar.widgetForAction(action)
            if button is not None:
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                button.setAccessibleName(TOOL_NAMES[key])

    def _build_menus(self):
        s, tools = self.shell, self._tools()
        bar = s.menuBar()
        bar.setObjectName("workflowMenuBar")
        file_menu = bar.addMenu("&Datei")
        for key in ("new", "open", None, "save_all", "save", "folder_save", None, "reload"):
            file_menu.addSeparator() if key is None else file_menu.addAction(tools[key])
        file_menu.addSeparator()
        quit_action = file_menu.addAction("Beenden")
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(s.close)
        edit_menu = bar.addMenu("&Bearbeiten")
        for key in ("undo", "redo", None, "rename"):
            edit_menu.addSeparator() if key is None else edit_menu.addAction(tools[key])
        flow = bar.addMenu("&Ablauf")
        self.step_actions = {}
        for definition in STEPS:
            action = flow.addAction(f"{definition.number}  {definition.title}")
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, key=definition.key: self.enter(key))
            self.step_actions[definition.key] = action
        flow.addSeparator()
        self.expert_action = flow.addAction("Expertenmodus")
        self.expert_action.setCheckable(True)
        self.expert_action.triggered.connect(self.set_expert)
        self.tools_menu = bar.addMenu("&Werkzeuge")
        self.tools_menu.addAction(tools["ict"])
        self.tools_menu.addAction(tools["build"])
        help_menu = bar.addMenu("&Hilfe")
        help_menu.addAction(tools["help"])
        guide = help_menu.addAction("Anleitung zu diesem Schritt")
        guide.triggered.connect(self.show_guide)

    # -- Fakten -------------------------------------------------------------
    def _project_key(self):
        return self.shell.build_controller._project_key()

    def _files(self):
        from studio.virtual_folders.binding import extension_path
        session = self.shell.coordinator.session
        if session is None or session.path is None:
            return ()
        base = Path(session.path)
        handler = self.shell.build_controller.handler.text().strip()
        return (base, extension_path(base), (base.parent / handler) if handler else "")

    def current_fingerprint(self) -> str:
        return fingerprint(self._files(), self.shell.build_controller.folder_mode)

    def _prerequisites(self):
        stamp, value = self._prereq
        if time.monotonic() - stamp > 5.0:
            value = tuple(self.shell.build_controller.quick_prerequisites())
            self._prereq = (time.monotonic(), value)
        return value

    def _handler_facts(self, session, raw):
        """(Datei, Fehler, fehlende, unbekannte, registrierte) – nur statisch gelesen."""
        relative = self.shell.build_controller.handler.text().strip()
        if not relative:
            return "", "", (), (), None
        if session.path is None:
            return relative, "Projekt zuerst speichern.", (), (), None
        file = Path(session.path).resolve().parent / relative
        try:
            stamp = (str(file), file.stat().st_mtime_ns, file.stat().st_size)
        except OSError:
            stamp = (str(file), None, None)
        if self._handler_cache[0] != stamp:
            try:
                validate_handler(session.path, relative)
                result = ("", registered_handlers(file))
            except NativeBuildPreflightError as exc:
                result = (str(exc), None)
            self._handler_cache = (stamp, result)
        error, found = self._handler_cache[1]
        if error or found is None:
            return relative, error, (), (), None
        used = [h["id"] for h in raw.get("handlers", ()) if any(
            a.get("handler") == h["id"] for a in raw.get("actions", ()))]
        return (relative, "", tuple(h for h in used if h not in found),
                tuple(sorted(found - set(used))), found)

    def facts(self) -> Facts:
        s = self.shell
        c = s.coordinator
        session = c.session
        if session is None:
            return Facts()
        raw = session.snapshot()
        handlers = tuple(h["id"] for h in raw.get("handlers", ()))
        actions = raw.get("actions", ())
        handler_file, handler_error, unregistered, unknown, _found = self._handler_facts(session, raw)
        project_dir = Path(session.path).resolve().parent if session.path else None
        references = asset_references(raw)
        store = c.extension_store
        orphans, placements, extension_saved = (), 0, True
        if store is not None:
            orphans = tuple(p.id for p in store.document.missing_actions(raw))
            placements = sum(1 for p in store.document.placements if p.kind == "action")
            extension_saved = not store.dirty
        placements += sum(len(f.get("entries", ())) for f in raw.get("folders", ()))
        errors = 0
        if s.problems is not None:
            for source in PROJECT_SOURCES:
                if source in s.problems.sources():
                    errors += sum(1 for d in s.problems.diagnostics(source) if d.severity.upper() == "ERROR")
        build, deploy = s.build_controller, s.deployment_controller
        built = build.last_result is not None
        current = built and self._built is not None and self._built == self.current_fingerprint()
        status = deploy.state.status if deploy.state is not None and deploy.result is build.last_result else {}
        installed = status.get("installed") in ("INSTALLED", "UPDATED")
        return Facts(
            has_project=True, project_saved=not session.dirty, plugin_id=raw["plugin"].get("id", ""),
            display_name=raw["plugin"].get("display_name", ""), handlers=handlers, handler_file=handler_file,
            handler_file_error=handler_error, handlers_unregistered=unregistered, handlers_unknown=unknown,
            actions=len(actions),
            actions_without_handler=tuple(a["id"] for a in actions if a.get("handler") not in handlers),
            draft_open=bool(s.inspector.dirty), missing_assets=missing_assets(raw, project_dir),
            actions_with_symbol=sum(1 for key in references if key), orphan_placements=orphans,
            placements=placements, extension_saved=extension_saved, problem_errors=errors,
            prerequisites=self._prerequisites(), build_done=built, build_current=bool(current),
            build_error="" if built else (build.last_error or ""),
            package_valid=bool(built and deploy.result is build.last_result
                               and deploy.status_codes.get("package") == "VALID"),
            installed=installed, loaded=status.get("loaded") == "LOADED",
            connected=status.get("connection") == "ACTIVE", install_current=installed,
            hardware_confirmed=bool(installed and current and self._hardware == self._built))

    # -- Anzeige ------------------------------------------------------------
    def state(self, key):
        return next(s for s in self.states if s.step.key == key)

    def refresh(self):
        c = self.shell.coordinator
        if c.project_token != self._project_seen:
            self._project_changed()
        self.states = evaluate(self.facts())
        if not self.expert and not self.state(self.active).reachable:
            self.active = first_incomplete(self.states)
        shown = (self.states, self.active, self.expert)
        if shown != self._shown:
            self._shown = shown
            self.rail.set_states(self.states, self.active, expert=self.expert)
            for key, action in self.step_actions.items():
                action.setChecked(key == self.active)
                action.setEnabled(self.expert or self.state(key).reachable)
            self.expert_action.setChecked(self.expert)
        session = c.session
        self.start_page.set_project(None if session is None else (
            session.native_project().display_name, session.snapshot()["plugin"]["id"], session.path,
            len(session.snapshot().get("actions", ())), len(session.snapshot().get("handlers", ()))))
        self._show_handlers()
        self._apply_visibility()
        self._publish()
        self.changed.emit()

    def _project_changed(self):
        self._project_seen = self.shell.coordinator.project_token
        self._built = self._pending = None
        self._hardware, self._published = "", None
        self._handler_cache = (None, None)
        key = self._project_key()
        remembered = self.store.project(*key) if key else {}
        build = self.shell.build_controller
        build.handler.blockSignals(True)
        build.handler.setText(remembered.get("handler_file", ""))  # V-93
        build.handler.blockSignals(False)
        self._hardware = remembered.get("hardware", "")
        self.states = evaluate(self.facts())
        wanted = remembered.get("step")
        self.active = (wanted if wanted in STEP_KEYS and self.state(wanted).reachable
                       else first_incomplete(self.states))
        if self.shell.coordinator.session is None:
            self.active = STEP_KEYS[0]
        self._show_home()

    def _tabs(self):
        s = self.shell
        return {"start": self.start_page, "details": s.details, "keypad": s.keypad.panel,
                "inspector": s.inspector, "folders": s.composer or s.folder_notice, "problems": s.problems,
                "help": s.help_widget, "build": s.build_controller.panel,
                "install": s.deployment_controller.panel, "peers": s.pairing_controller.panel,
                "handlers": getattr(s, "handler_panel", None), "symbols": getattr(s, "symbol_panel", None),
                "states": getattr(s, "state_panel", None)}

    def _visible_tabs(self):
        views = set(step(self.active).views)
        if self.shell.build_controller.folder_mode != "shared":
            views.discard("peers")
        return views

    def _apply_visibility(self):
        s = self.shell
        definition = step(self.active)
        views = self._visible_tabs()
        keys = {widget: key for key, widget in self._tabs().items() if widget is not None}
        tabs = s.tabs
        for index in range(tabs.count()):
            key = keys.get(tabs.widget(index))
            visible = self.expert or key is None or key in views
            if tabs.isTabVisible(index) != visible:
                tabs.setTabVisible(index, visible)
        if not tabs.isTabVisible(tabs.currentIndex()):
            self._show_home()
        s.explorer.setVisible(self.expert or "explorer" in definition.panes)
        s.catalog.setVisible(self.expert or "catalog" in definition.panes)
        self._sync_tools()

    def _sync_tools(self):
        definition = step(self.active)
        has_project = self.shell.coordinator.session is not None
        for key, action in self._tools().items():
            if key in EXPERT_TOOLS:
                visible = self.expert
            elif key in ALWAYS_TOOLS:
                visible = key in ("new", "open", "help") or has_project
            else:
                visible = self.expert or key in definition.tools
            if action.isVisible() != visible:
                action.setVisible(visible)
        s = self.shell
        session = s.coordinator.session
        dirty = bool(session and (session.dirty or (s.composer and s.composer.store.dirty) or s.inspector.dirty))
        self.save_all_action.setEnabled(dirty)

    def _show_home(self):
        tabs = self._tabs()
        widget = tabs.get(step(self.active).home)
        index = self.shell.tabs.indexOf(widget) if widget is not None else -1
        if index < 0 or not (self.expert or self.shell.tabs.isTabVisible(index)
                             or step(self.active).home in self._visible_tabs()):
            return
        self.shell.tabs.setTabVisible(index, True)
        self.shell.tabs.setCurrentIndex(index)

    def _publish(self):
        """Offene Punkte des aktiven Schritts als eigene Quelle der bestehenden Problemliste."""
        c = self.shell.coordinator
        problems = self.shell.problems
        if problems is None or c.session is None:
            return
        state = self.state(self.active)
        items = tuple((cr.key, cr.status, cr.text, cr.detail) for cr in state.criteria if cr.status in BLOCKING)
        signature = (c.project_token, c.session.revision, self.active, items)
        present = "workflow" in problems.sources()
        if signature == self._published and present == bool(items):
            return
        self._published = signature
        if not items:
            if present:
                problems.remove_source("workflow")
            return
        diagnostics = [Diagnostic("WORKFLOW_" + key.upper().replace(".", "_"), "/",
                                  f"Schritt {state.step.number} „{state.step.title}“: {text}." +
                                  (" " + detail if detail else ""),
                                  "ERROR" if status == ERROR else "WARNING")
                       for key, status, text, detail in items]
        c.publish_diagnostics("workflow", diagnostics, project_token=c.project_token,
                              base_revision=c.session.revision)  # V-99

    # -- Bedienung ----------------------------------------------------------
    def enter(self, key) -> bool:
        if key not in STEP_KEYS:
            return False
        self.states = evaluate(self.facts())
        target = self.state(key)
        if not self.expert and not target.reachable:
            blocker = next(s for s in self.states if not complete(s))
            self.shell.statusBar().showMessage(
                f"Schritt {target.step.number} „{target.step.title}“ ist noch gesperrt: zuerst Schritt "
                f"{blocker.step.number} „{blocker.step.title}“ abschließen.")
            self._shown = None
            self.refresh()
            return False
        self.active = key
        project = self._project_key()
        if project:
            self.store.remember(*project, step=key)
        self.refresh()
        self._show_home()
        self.shell.coordinator.help.set_context(HelpContext(target.step.topic))
        return True

    def back(self):
        index = STEP_KEYS.index(self.active)
        return index > 0 and self.enter(STEP_KEYS[index - 1])

    def next(self):
        index = STEP_KEYS.index(self.active)
        return index < len(STEP_KEYS) - 1 and self.enter(STEP_KEYS[index + 1])

    def set_expert(self, expert) -> None:
        self.expert = bool(expert)
        self.store.set_guided(not self.expert)
        self.refresh()
        if not self.expert:
            self._show_home()
        self.shell.statusBar().showMessage(
            "Expertenmodus: alle Bereiche sind frei erreichbar." if self.expert
            else "Geführter Ablauf: es werden nur die Bereiche des aktuellen Schritts gezeigt.")

    def show_guide(self):
        s = self.shell
        s.coordinator.related_help(step(self.active).topic)
        index = s.tabs.indexOf(s.help_widget)
        s.tabs.setTabVisible(index, True)
        s.tabs.setCurrentIndex(index)

    def activate_criterion(self, key) -> bool:
        criterion = next((c for s in self.states for c in s.criteria if c.key == key), None)
        if criterion is None:
            return False
        target = criterion.target
        if target == "do:save_all":
            return bool(self.shell.save_all())
        if target == "do:build":
            return bool(self.shell.build_controller.start())
        if target == "do:confirm_hardware":
            return self.confirm_hardware()
        widget = self._tabs().get(target)
        index = self.shell.tabs.indexOf(widget) if widget is not None else -1
        if index < 0 or not (self.expert or target in self._visible_tabs()):
            return False
        self.shell.tabs.setCurrentIndex(index)
        return True

    def confirm_hardware(self, *, confirmed=None) -> bool:
        """Der Gerätetest ist eine ausdrückliche Aussage des Anwenders, nie ein automatischer Nachweis."""
        facts = self.facts()
        if not (facts.installed and facts.build_current):
            self.shell.statusBar().showMessage("Gerätetest erst nach Installation des aktuellen Builds bestätigen.")
            return False
        if confirmed is None:
            answer = QMessageBox.question(
                self.shell, "Gerätetest bestätigen",
                "Hast du eine Aktion dieses Plugins in Logi Options+ auf eine Taste gelegt, sie am Gerät "
                "gedrückt und hat sie wie erwartet reagiert?")
            confirmed = answer == QMessageBox.StandardButton.Yes
        if not confirmed:
            return False
        self._hardware = self._built
        key = self._project_key()
        if key:
            self.store.remember(*key, hardware=self._hardware)
        self.shell.deployment_controller.set_status("hardware", "HARDWARE_PASS")
        self.refresh()
        return True

    # -- Handler -------------------------------------------------------------
    def _show_handlers(self):
        session = self.shell.coordinator.session
        if session is None:
            if self._handlers_shown is not None:
                self._handlers_shown = None
                self.handlers.set_project(None)
            return
        raw = session.snapshot()
        file, error, unregistered, unknown, found = self._handler_facts(session, raw)
        shown = (session.revision, self.shell.coordinator.project_token, file, error, unregistered, unknown,
                 None if found is None else tuple(sorted(found)))
        if shown == self._handlers_shown:
            return
        self._handlers_shown = shown
        self.handlers.set_project(raw, file=file, file_error=error, registered=found, unknown=unknown,
                                  snippet=handler_snippet(unregistered) if unregistered else "")

    def _mirror_selection(self):
        selection = self.shell.coordinator.selection
        if selection and selection[0] == "handler":
            self.handlers.select(selection[1])

    def _handler_change(self, operation) -> bool:
        s = self.shell
        c = s.coordinator
        if c.session is None or not s.confirm_draft():
            return False
        try:
            operation(c.session.revision, c.project_token)
        except NativeSessionError as exc:
            c.report_error("handlers", exc)
            s.statusBar().showMessage(str(exc))
            QMessageBox.warning(s, "Handler", str(exc))
            return False
        s.inspector.accept_applied()
        s._sync_inspector()
        self.refresh()
        return True

    def create_handler(self, handler_id) -> bool:
        c = self.shell.coordinator
        return self._handler_change(lambda revision, token: c.apply_handler_create(
            handler_id, base_revision=revision, project_token=token))

    def rename_handler(self, old_id, new_id) -> bool:
        c = self.shell.coordinator
        return self._handler_change(lambda revision, token: c.rename_handler(
            old_id, new_id, base_revision=revision, project_token=token))

    def delete_handler(self, handler_id) -> bool:
        c = self.shell.coordinator
        return self._handler_change(lambda revision, token: c.delete_handler(
            handler_id, base_revision=revision, project_token=token))

    def create_handler_file(self) -> bool:
        """Legt die Handlerdatei einmalig aus der Vorlage an; überschreibt nie eine vorhandene Datei."""
        s = self.shell
        session = s.coordinator.session
        if session is None or session.path is None:
            return False
        raw = session.snapshot()
        project = Path(session.path)
        target = project.with_name(project.stem + "_handlers.py")
        if not target.exists():
            used = [h["id"] for h in raw["handlers"] if any(a.get("handler") == h["id"] for a in raw["actions"])]
            try:
                with target.open("x", encoding="utf-8", newline="\n") as output:
                    output.write(handler_template(raw["plugin"].get("display_name", ""), used))
            except OSError as exc:
                s.coordinator.report_error("handlers", exc)
                s.statusBar().showMessage(f"Handlerdatei konnte nicht angelegt werden: {exc}")
                return False
            s.statusBar().showMessage(f"Handlerdatei angelegt: {target}")
        else:
            s.statusBar().showMessage(f"Vorhandene Datei {target.name} zugeordnet (nicht überschrieben).")
        s.build_controller.handler.setText(target.name)
        return True

    # -- Build --------------------------------------------------------------
    def _build_guard(self):
        if self.shell.problems is not None:
            self.shell.problems.remove_source("native-build")
        if not self.expert:
            self.states = evaluate(self.facts())
            state = self.state("build")
            if not state.reachable:
                blocker = next(s for s in self.states if not complete(s))
                return (f"Im geführten Ablauf zuerst Schritt {blocker.step.number} "
                        f"„{blocker.step.title}“ abschließen.")
            for criterion in state.criteria:
                if criterion.key in ("build.saved", "build.errors") and criterion.status in BLOCKING:
                    return f"{criterion.text}: {criterion.detail}"
        self._pending = self.current_fingerprint()
        return None

    def _build_finished(self):
        build = self.shell.build_controller
        self._built = self._pending if build.last_result is not None else None
        self._pending = None
        self.refresh()

    def _handler_edited(self, text):
        self._handler_cache = (None, None)
        key = self._project_key()
        if key:
            self.store.remember(*key, handler_file=text.strip())
        self.refresh()
