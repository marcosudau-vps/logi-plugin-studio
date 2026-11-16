"""Problems Panel Lab: the real ProblemsPanelWidget in a small simulated host.

Start: python tools\\run_problems_panel_lab.py [--output ORDNER] [--smoke] [--evidence ORDNER]

Needs no Logitech service, login, device or installation. Everything here is a lab
host: diagnostics come from static samples or from the existing validators on
in-memory project copies; no project file is written and no editor is opened. The
studio main window is not imported.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                                   QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget)
except ModuleNotFoundError as exc:
    if exc.name == "PySide6":
        print("PySide6 fehlt. Die dokumentierte lokale Python-Umgebung verwenden.", file=sys.stderr)
        raise SystemExit(2) from exc
    raise

from adapters.logitech.errors import BuildError, LogitechAdapterError, ValidationGateError
from adapters.logitech.native import NativeProjectError, parse_native_project
from core.errors import Diagnostic
from core.registry import load_manifests
from core.validate import validate_project
from studio.problems_panel import ProblemsPanelWidget

DRAFT_EXAMPLE = ROOT / "examples" / "project_v0_1_draft.json"
NATIVE_EXAMPLE = ROOT / "examples" / "project_logitech_native_v1.json"
DEFAULT_OUTPUT = ROOT / "work" / "widget-lab" / "problems-panel-v1" / "lab-output"
SOURCES = ("project", "build", "host")
LONG_MESSAGE = ("Der Generator konnte das Symbol nicht übernehmen, weil die referenzierte Vorlage in mehreren Varianten "
                "vorliegt und keine davon eindeutig dem Parameter zugeordnet ist. " * 8).strip()

# Static samples. Codes from core.validate and the adapter errors where such a code exists; the rest is marked as lab data.
SNAPSHOTS: dict[str, dict[str, tuple[Diagnostic, ...]]] = {
    "project": {
        "A": (Diagnostic("ID_DUPLICATE", "/components/3/id", "Duplicate 'action.mute' in components"),
              Diagnostic("TYPE_MISSING", "/components/7/type", "Unknown component type 'core.unknown'"),
              Diagnostic("PLACEMENT_COMPONENT", "/views/0/placements/2/component", "Missing component"),
              Diagnostic("POSITION_COLLISION", "/views/1/placements/10/position", "Position already occupied in this view"),
              Diagnostic("SCHEMA_NOT_PROVEN", "/bindings/4", "Payload compatibility not conservatively provable; explicit converter required", "WARNING"),
              Diagnostic("CAPABILITY_DEFERRED", "/components/1", "Capabilities ['net'] require a separate adapter-stage check", "WARNING")),
        "B": (Diagnostic("ID_DUPLICATE", "/components/3/id", "Duplicate 'action.mute' in components"),
              Diagnostic("SCHEMA_NOT_PROVEN", "/bindings/4", "Payload compatibility not conservatively provable; explicit converter required", "WARNING")),
    },
    "build": {
        "A": (Diagnostic("BUILD_FAILED", "/", "dotnet build exited with code 1 (Lab-Beispiel, kein echter Build)"),
              Diagnostic("LAB_BUILD_NOTE", "", "Keine Pfadangabe vom Build; das Widget erfindet keine.", "INFO"),
              Diagnostic("ID_DUPLICATE", "/components/3/id", "Duplicate 'action.mute' in components")),
        "B": (Diagnostic("LAB_BUILD_NOTE", "", "Keine Pfadangabe vom Build; das Widget erfindet keine.", "INFO"),),
    },
    "host": {
        "A": (Diagnostic("LAB_HOST_NOTE", "/", "Verbindung zum lokalen Host nicht geprüft (Lab-Beispiel).", "INFO"),
              Diagnostic("LAB_HINT", "/states/0", "Eigene Schwere der Quelle bleibt erhalten.", "HINT")),
        "B": (Diagnostic("LAB_HOST_NOTE", "/", "Verbindung zum lokalen Host nicht geprüft (Lab-Beispiel).", "INFO"),),
    },
}
ONLY_WARNINGS = (Diagnostic("SCHEMA_NOT_PROVEN", "/bindings/0", "Payload compatibility not conservatively provable; explicit converter required", "WARNING"),
                 Diagnostic("CAPABILITY_DEFERRED", "/components/1", "Capabilities ['net'] require a separate adapter-stage check", "WARNING"),
                 Diagnostic("CAPABILITY_DEFERRED", "/components/2", "Capabilities ['usb'] require a separate adapter-stage check", "WARNING"))
UNICODE_LONG = (Diagnostic("LAB_UNICODE", "/components/0/config/größe", "Größenangabe „Straße 42“ ist ungültig – Ünïcödé, 日本語, emoji 🎛️ und RTL שלום bleiben erhalten."),
                Diagnostic("LAB_MARKUP", "/presentations/0/variants/<b>fett</b>", "<b>Kein Markup:</b> <img src=x> & \"Anführungszeichen\" bleiben Text.", "WARNING"),
                Diagnostic("LAB_LONG_TEXT_WITH_A_VERY_LONG_DIAGNOSTIC_CODE_NAME", "/views/0/placements/12/presentation/variants/active/image/source/path/segment", LONG_MESSAGE),
                Diagnostic("LAB_MULTILINE", "/", "Erste Zeile\nZweite Zeile\n\tEingerückte dritte Zeile", "INFO"),
                Diagnostic("LAB_EMPTY_PATH", "", "Leerer Pfad bleibt leer.", "NOTICE"))
_STRESS_CODES = ("FIELD_UNKNOWN", "ID_INVALID", "PORT_MISSING", "SCHEMA_NOT_PROVEN", "CAPABILITY_DEFERRED", "LAB_NOTE")
_STRESS_SEVERITIES = ("ERROR", "WARNING", "WARNING", "INFO", "ERROR", "HINT", "WARNING")


def stress_diagnostics(count: int) -> tuple[Diagnostic, ...]:
    return tuple(Diagnostic(_STRESS_CODES[index % len(_STRESS_CODES)], f"/components/{index}/config/field_{index % 17}",
                            f"Lasttest-Meldung {index:05d} für Bereich {index % 23}", _STRESS_SEVERITIES[index % len(_STRESS_SEVERITIES)])
                 for index in range(count))


# ---------------------------------------------------------------------- lab host: real validators, in memory only


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def broken_draft_project() -> dict:
    """An in-memory copy of the draft example with real structural mistakes. No file is touched."""
    raw = copy.deepcopy(_read_json(DRAFT_EXAMPLE))
    raw["lab_extra"] = True
    raw["components"].append(copy.deepcopy(raw["components"][0]))
    raw["states"][0]["scope"] = "planet"
    raw["views"][0]["placements"][0]["component"] = "component.missing"
    raw["bindings"][0]["kind"] = "smoke_signal"
    return raw


def validate_in_memory() -> list[Diagnostic]:
    """The real ``core.validate.validate_project`` on the broken copy, plus the registry's own issues."""
    registry, registry_issues = load_manifests(ROOT / "component_types")
    return [*registry_issues, *validate_project(broken_draft_project(), registry)]


def native_error_diagnostics() -> list[Diagnostic]:
    """The display wrapper the assignment allows: one native error without a precise position."""
    raw = copy.deepcopy(_read_json(NATIVE_EXAMPLE))
    raw["actions"][0]["sdk_type"] = "NoSuchSdkType"
    try:
        parse_native_project(raw)
    except NativeProjectError as exc:
        return [Diagnostic("NATIVE_PROJECT", "/", str(exc))]
    return []


def adapter_diagnostics() -> list[Diagnostic]:
    """Separate source: ``ValidationGateError.issues`` keep their own values; other adapter errors have no pointer."""
    registry, _ = load_manifests(ROOT / "component_types")
    errors = [issue for issue in validate_project(broken_draft_project(), registry) if issue.severity == "ERROR"]
    gate = ValidationGateError(errors[:3])
    built = [Diagnostic(issue["code"], issue["path"], issue["message"], issue.get("severity", "ERROR")) for issue in gate.issues]
    failure: LogitechAdapterError = BuildError("dotnet build wurde im Lab nicht gestartet (Beispieltext).")
    return [*built, Diagnostic(failure.code, "/", failure.message)]


def describe(diagnostic: Diagnostic) -> str:
    return f"{diagnostic.severity} {diagnostic.code} path={diagnostic.path!r}"


# ---------------------------------------------------------------------- window


class ProblemsPanelLabWindow(QMainWindow):
    SCENARIOS = ("Gemischt: project, build, host", "Nur Warnungen", "Leere Listen (Quellen ohne Meldungen)",
                 "Keine Quelle (clear)", "1.200 Meldungen", "5.000 Meldungen", "Unicode, lange Texte, Markup",
                 "Filter ohne Treffer", "Echte Prüfung im Speicher (validate_project)",
                 "Nativer Fehler (NATIVE_PROJECT)", "Adapter-Fehler (ValidationGateError)")
    WIDTHS = (("Frei", None), ("720 px", 720), ("520 px", 520), ("380 px", 380))

    def __init__(self, output: Path = DEFAULT_OUTPUT) -> None:
        super().__init__()
        self.setObjectName("problemsPanelLabWindow")
        self.setWindowTitle("Problems Panel Lab – simulierter Host, keine Hardware")
        self.resize(1360, 860)
        self.output = Path(output)
        self.events: list[dict] = []
        self.panel = ProblemsPanelWidget()
        self._revision_counter = 0
        self._build_ui()
        self.panel.diagnosticSelected.connect(self._on_selected)
        self.panel.diagnosticActivated.connect(self._on_activated)
        self.load_scenario(0)

    def _build_ui(self) -> None:
        self.panel_frame = QFrame()
        self.panel_frame.setObjectName("labPanelFrame")
        self.panel_frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame_layout = QHBoxLayout(self.panel_frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.addWidget(self.panel)

        self.panel_area = QWidget()
        area_layout = QHBoxLayout(self.panel_area)
        area_layout.setContentsMargins(0, 0, 0, 0)
        area_layout.addWidget(self.panel_frame, 1)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("labEventLog")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        log_font = QFont("Consolas")
        log_font.setStyleHint(QFont.StyleHint.Monospace)
        self.log_view.setFont(log_font)
        self.log_view.setPlaceholderText("Auswahl, Navigationswünsche und Host-Aufrufe erscheinen hier.")

        left = QSplitter(Qt.Orientation.Vertical)
        left.addWidget(self.panel_area)
        left.addWidget(self.log_view)
        left.setStretchFactor(0, 4)
        left.setStretchFactor(1, 1)
        left.setSizes([640, 200])

        self.banner = QLabel()
        self.banner.setObjectName("labBanner")
        self.banner.setTextFormat(Qt.TextFormat.PlainText)
        self.banner.setWordWrap(True)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        row = 0

        def heading(text: str) -> None:
            nonlocal row
            label = QLabel(text)
            font = label.font()
            font.setBold(True)
            label.setFont(font)
            grid.addWidget(label, row, 0, 1, 2)
            row += 1

        def field(text: str, widget: QWidget) -> None:
            nonlocal row
            grid.addWidget(QLabel(text), row, 0)
            grid.addWidget(widget, row, 1)
            row += 1

        def full(widget: QWidget) -> None:
            nonlocal row
            grid.addWidget(widget, row, 0, 1, 2)
            row += 1

        heading("Szenario")
        self.scenario_combo = QComboBox()
        self.scenario_combo.addItems(self.SCENARIOS)
        self.scenario_combo.activated.connect(self.load_scenario)
        full(self.scenario_combo)

        heading("Eine Quelle austauschen")
        self.source_combo = QComboBox()
        self.source_combo.setEditable(True)
        self.source_combo.addItems(SOURCES)
        field("Quelle", self.source_combo)
        self.snapshot_combo = QComboBox()
        self.snapshot_combo.addItems(["Stand A", "Stand B", "Leer"])
        field("Inhalt", self.snapshot_combo)
        self.revision_edit = QLineEdit()
        self.revision_edit.setPlaceholderText("leer = keine Revision")
        field("Revision (opak)", self.revision_edit)
        self.replace_button = QPushButton("set_source_diagnostics")
        self.replace_button.clicked.connect(self.replace_selected_source)
        full(self.replace_button)
        self.remove_button = QPushButton("remove_source")
        self.remove_button.clicked.connect(lambda: self.remove_source(self.source_combo.currentText()))
        self.clear_button = QPushButton("clear")
        self.clear_button.clicked.connect(self.clear_all)
        buttons = QHBoxLayout()
        buttons.addWidget(self.remove_button)
        buttons.addWidget(self.clear_button)
        grid.addLayout(buttons, row, 0, 1, 2)
        row += 1

        heading("Programmatischer Filter")
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Text für set_filter")
        self.filter_edit.returnPressed.connect(self._program_filter)
        field("Text", self.filter_edit)
        self.filter_button = QPushButton("set_filter")
        self.filter_button.clicked.connect(self._program_filter)
        full(self.filter_button)
        self.severity_combo = QComboBox()
        self.severity_combo.addItems(["Alle", "Fehler", "Warnungen", "Weitere"])
        self.severity_combo.activated.connect(lambda _: self._program_severity())
        field("Schwere", self.severity_combo)

        heading("Darstellung")
        self.width_combo = QComboBox()
        self.width_combo.addItems([name for name, _ in self.WIDTHS])
        self.width_combo.currentIndexChanged.connect(lambda index: self.set_panel_width(self.WIDTHS[index][1]))
        field("Panelbreite", self.width_combo)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dunkel", "Hell"])
        self.theme_combo.currentIndexChanged.connect(lambda index: apply_lab_theme(QApplication.instance(), dark=index == 0))
        field("Thema", self.theme_combo)

        heading("Ausgabe")
        self.shot_widget_button = QPushButton("Screenshot Widget")
        self.shot_widget_button.clicked.connect(lambda: self.save_screenshot(self.panel, "panel"))
        self.shot_lab_button = QPushButton("Screenshot Lab")
        self.shot_lab_button.clicked.connect(lambda: self.save_screenshot(self, "lab"))
        shots = QHBoxLayout()
        shots.addWidget(self.shot_widget_button)
        shots.addWidget(self.shot_lab_button)
        grid.addLayout(shots, row, 0, 1, 2)
        row += 1
        self.clear_log_button = QPushButton("Protokoll leeren")
        self.clear_log_button.clicked.connect(self.log_view.clear)
        full(self.clear_log_button)
        grid.setColumnStretch(1, 1)

        controls = QWidget()
        controls.setObjectName("labControls")
        controls.setFixedWidth(320)
        side = QVBoxLayout(controls)
        side.addWidget(self.banner)
        side.addLayout(grid)
        side.addStretch(1)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(left, 1)
        layout.addWidget(controls)
        self.setCentralWidget(root)

    # ------------------------------------------------------------------ host actions

    def log(self, kind: str, text: str, data: dict | None = None) -> None:
        self.events.append({"kind": kind, "text": text, "data": data or {}})
        self.log_view.appendPlainText(f"{datetime.now():%H:%M:%S}  {kind}: {text}")

    def _next_revision(self) -> str:
        self._revision_counter += 1
        return f"rev-{self._revision_counter}"

    def _deliver(self, source: str, diagnostics, revision: str | None) -> None:
        started = time.perf_counter()
        self.panel.set_source_diagnostics(source, diagnostics, revision=revision)
        elapsed = (time.perf_counter() - started) * 1000
        self.log("set_source_diagnostics", f"source={source!r}, Meldungen: {len(diagnostics)}, revision={revision!r}, {elapsed:.1f} ms")

    def load_scenario(self, index: int) -> None:
        self.scenario_combo.setCurrentIndex(index)
        self.panel.reset_filters()
        self.panel.clear()
        self.log("Szenario", self.SCENARIOS[index])
        banner = "Simulierter Host. Beispieldaten sind keine Prüfaussage über ein echtes Projekt."
        if index == 0:
            for source in SOURCES:
                self._deliver(source, SNAPSHOTS[source]["A"], self._next_revision())
        elif index == 1:
            self._deliver("project", ONLY_WARNINGS, self._next_revision())
        elif index == 2:
            for source in SOURCES:
                self._deliver(source, (), self._next_revision())
        elif index == 4:
            self._deliver("project", stress_diagnostics(1200), self._next_revision())
        elif index == 5:
            self._deliver("project", stress_diagnostics(5000), self._next_revision())
        elif index == 6:
            self._deliver("project", UNICODE_LONG, self._next_revision())
        elif index == 7:
            for source in SOURCES:
                self._deliver(source, SNAPSHOTS[source]["A"], self._next_revision())
            self.panel.set_filter("kein-solcher-text")
            self.log("set_filter", "'kein-solcher-text'")
        elif index == 8:
            self._deliver("project", validate_in_memory(), self._next_revision())
            banner = ("Echte validate_project-Meldungen zu einer defekten Kopie des Draft-Beispiels im Speicher. "
                      "Keine Datei wurde geändert.")
        elif index == 9:
            self._deliver("native", native_error_diagnostics(), self._next_revision())
            banner = ("Lab-Hülle um NativeProjectError: ein einzelner nativer Fehler ohne präzise Objektposition. "
                      "Der Pfad „/“ ist keine Fundstelle.")
        elif index == 10:
            self._deliver("project", validate_in_memory(), self._next_revision())
            self._deliver("adapter", adapter_diagnostics(), self._next_revision())
            banner = ("Eigene Quelle „adapter“: ValidationGateError.issues behalten ihre Werte. Der BuildError hat keinen "
                      "JSON-Pointer; der Lab-Host setzt deshalb „/“. Es lief kein Build.")
        self.banner.setText(banner)

    def replace_selected_source(self) -> None:
        source = self.source_combo.currentText().strip()
        if not source:
            self.log("abgelehnt", "Quellenname ist leer")
            return
        choice = self.snapshot_combo.currentIndex()
        samples = SNAPSHOTS.get(source, SNAPSHOTS["project"])
        diagnostics = samples["A"] if choice == 0 else samples["B"] if choice == 1 else ()
        self._deliver(source, diagnostics, self.revision_edit.text() or None)

    def remove_source(self, source: str) -> None:
        self.panel.remove_source(source)
        self.log("remove_source", repr(source))

    def clear_all(self) -> None:
        self.panel.clear()
        self.log("clear", "alle Quellen entfernt")

    def _program_filter(self) -> None:
        self.panel.set_filter(self.filter_edit.text())
        self.log("set_filter", repr(self.filter_edit.text()))

    def _program_severity(self) -> None:
        self.panel.set_severity_filter(self.severity_combo.currentText())
        self.log("set_severity_filter", self.severity_combo.currentText())

    def set_panel_width(self, width: int | None) -> None:
        if width is None:
            self.panel_frame.setMinimumWidth(0)
            self.panel_frame.setMaximumWidth(16777215)
        else:
            self.panel_frame.setFixedWidth(width)

    def _on_selected(self, diagnostic: Diagnostic | None) -> None:
        if diagnostic is None:
            self.log("diagnosticSelected", "keine Markierung")
        else:
            self.log("diagnosticSelected", f"{describe(diagnostic)}, Quelle {self.panel.selected_source()!r}", diagnostic.as_dict())

    def _on_activated(self, diagnostic: Diagnostic) -> None:
        self.log("diagnosticActivated", f"Navigationswunsch: {describe(diagnostic)} (Lab öffnet keinen Editor)", diagnostic.as_dict())

    def save_screenshot(self, widget: QWidget, name: str) -> Path:
        self.output.mkdir(parents=True, exist_ok=True)
        path = self.output / f"{name}_{datetime.now():%Y%m%d_%H%M%S}.png"
        widget.grab().save(str(path), "PNG")
        self.log("Screenshot", str(path))
        return path


def apply_lab_theme(app: QApplication, *, dark: bool = True) -> None:
    """The lab decides the theme; the widget just follows the palette it gets."""
    app.setStyle("Fusion")
    window, text, base, alternate, button, accent, placeholder, disabled = (
        ("#1f2227", "#e8ebef", "#2b3037", "#262a30", "#2f343b", "#3f74c0", "#98a0aa", "#737a84") if dark else
        ("#f2f3f5", "#1c1f24", "#ffffff", "#f5f6f8", "#e6e8eb", "#2f6fc4", "#6a7078", "#979ca3"))
    palette = QPalette()
    for role, color in ((QPalette.ColorRole.Window, window), (QPalette.ColorRole.WindowText, text),
                        (QPalette.ColorRole.Base, base), (QPalette.ColorRole.AlternateBase, alternate),
                        (QPalette.ColorRole.Text, text), (QPalette.ColorRole.Button, button),
                        (QPalette.ColorRole.ButtonText, text), (QPalette.ColorRole.ToolTipBase, button),
                        (QPalette.ColorRole.ToolTipText, text), (QPalette.ColorRole.Highlight, accent),
                        (QPalette.ColorRole.HighlightedText, "#ffffff"), (QPalette.ColorRole.PlaceholderText, placeholder)):
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText, QPalette.ColorRole.Text):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(disabled))
    app.setPalette(palette)


# ---------------------------------------------------------------------- scripted runs


def run_smoke(window: ProblemsPanelLabWindow) -> int:
    """Instantiation, search filter and source exchange, without any service or clipboard change."""
    app = QApplication.instance()
    panel = window.panel
    sentinel = "problems-panel-smoke-sentinel"
    clipboard = QGuiApplication.clipboard()
    original = clipboard.text()
    clipboard.setText(sentinel)
    activated: list[Diagnostic] = []
    panel.diagnosticActivated.connect(activated.append)
    checks: list[tuple[str, bool]] = []

    window.show()
    app.processEvents()
    all_sources = sum(len(SNAPSHOTS[source]["A"]) for source in SOURCES)
    checks.append(("Instanziierung mit drei Quellen", panel.sources() == sorted(SOURCES) and len(panel.visible_entries()) == all_sources))

    panel.set_filter("id_duplicate")
    checks.append(("Suchfilter findet beide Quellen", {source for source, _ in panel.visible_entries()} == {"project", "build"}))
    panel.set_filter("kein-solcher-text")
    checks.append(("Leerzustand bei Filter ohne Treffer", panel.empty_state() == "no_match"))
    panel.reset_filters()

    build_before = panel.diagnostics("build")
    panel.set_source_diagnostics("project", SNAPSHOTS["project"]["B"], revision="smoke-2")
    checks.append(("Quellwechsel ersetzt nur eine Quelle", panel.diagnostics("build") == build_before
                   and len(panel.diagnostics("project")) == len(SNAPSHOTS["project"]["B"])
                   and panel.source_revision("project") == "smoke-2"))
    panel.remove_source("host")
    checks.append(("Entfernen betrifft nur eine Quelle", panel.sources() == ["build", "project"]))
    panel.clear()
    checks.append(("clear führt zum leeren Zustand", panel.empty_state() == "none"))
    checks.append(("Kein Signal und kein Clipboard ohne Nutzeraktion", not activated and clipboard.text() == sentinel))

    window.load_scenario(8)
    checks.append(("Echte Prüfung im Speicher liefert Meldungen", bool(panel.diagnostics("project"))))
    window.load_scenario(9)
    checks.append(("Nativer Fehler als einzelne Hülle", [d.code for d in panel.diagnostics("native")] == ["NATIVE_PROJECT"]
                   and panel.diagnostics("native")[0].path == "/"))
    clipboard.setText(original)

    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
    passed_count = sum(passed for _, passed in checks)
    print(f"Smoke: {passed_count}/{len(checks)}")
    return 0 if passed_count == len(checks) else 1


def _row_point(panel: ProblemsPanelWidget, row: int) -> QPoint:
    table = panel.problems_table
    table.scrollTo(table.model().index(row, 0))
    return table.visualRect(table.model().index(row, 1)).center()


def measure_latency(counts: tuple[int, ...] = (1000, 1200, 5000, 20000)) -> list[dict]:
    """Milliseconds with event processing, on a fresh visible widget. ``grab`` is not included."""
    app = QApplication.instance()
    results = []
    for count in counts:
        panel = ProblemsPanelWidget()
        panel.resize(1200, 420)
        panel.show()
        app.processEvents()
        diagnostics = stress_diagnostics(count)

        def timed(action) -> float:
            started = time.perf_counter()
            action()
            app.processEvents()
            return round((time.perf_counter() - started) * 1000, 1)

        results.append({"messages": count,
                        "deliver_ms": timed(lambda: panel.set_diagnostics(diagnostics)),
                        "search_ms": timed(lambda: panel.set_filter("bereich 7")),
                        "search_clear_ms": timed(lambda: panel.set_filter("")),
                        "severity_ms": timed(lambda: panel.set_severity_filter("Warnungen")),
                        "severity_clear_ms": timed(lambda: panel.set_severity_filter("Alle")),
                        "sort_message_ms": timed(lambda: panel.problems_table.sortByColumn(4, Qt.SortOrder.DescendingOrder)),
                        "replace_other_source_ms": timed(lambda: panel.set_source_diagnostics("host", SNAPSHOTS["host"]["A"]))})
        panel.close()
        panel.deleteLater()
        app.processEvents()
    return results


def run_evidence(window: ProblemsPanelLabWindow, directory: Path) -> dict:
    """Walks through the lab with real Qt input events and writes screenshots, event log and report."""
    app = QApplication.instance()
    directory = Path(directory)
    shots = directory / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    panel = window.panel
    results: list[dict] = []
    clipboard = QGuiApplication.clipboard()
    original_clipboard = clipboard.text()

    def settle() -> None:
        for _ in range(3):
            app.processEvents()
            QTest.qWait(15)

    def shot(name: str, widget: QWidget | None = None) -> None:
        settle()
        (widget or panel).grab().save(str(shots / f"{name}.png"), "PNG")

    def check(name: str, passed: bool, detail: object = None) -> None:
        results.append({"name": name, "passed": bool(passed), "detail": detail})

    def alone(width: int, height: int, name: str, setup) -> ProblemsPanelWidget:
        """The isolated widget in its own window, without any lab around it."""
        single = ProblemsPanelWidget()
        single.setWindowTitle(f"ProblemsPanelWidget {width}x{height}")
        single.resize(width, height)
        single.show()
        setup(single)
        shot(name, single)
        return single

    def fill_mixed(target: ProblemsPanelWidget) -> None:
        for number, source in enumerate(SOURCES, start=1):
            target.set_source_diagnostics(source, SNAPSHOTS[source]["A"], revision=f"rev-{number}")

    def fill_selected(target: ProblemsPanelWidget) -> None:
        fill_mixed(target)
        target.problems_table.selectRow(0)
        target.problems_table.setFocus()

    apply_lab_theme(app, dark=True)
    window.resize(1360, 860)
    window.show()
    settle()

    singles = [alone(1240, 420, "01_widget_wide_detail_beside", fill_selected),
               alone(900, 480, "02_widget_medium_detail_below", fill_selected),
               alone(560, 560, "03_widget_narrow_560", fill_selected),
               alone(380, 560, "04_widget_narrow_380", fill_selected),
               alone(1400, 240, "05_widget_low_bottom_area", fill_selected),
               alone(900, 380, "06_widget_no_problems", lambda t: t.set_diagnostics(())),
               alone(900, 380, "07_widget_no_source", lambda t: None),
               alone(900, 380, "08_widget_no_match", lambda t: (fill_mixed(t), t.set_filter("kein-solcher-text"))),
               alone(900, 380, "09_widget_only_warnings", lambda t: t.set_diagnostics(ONLY_WARNINGS)),
               alone(1100, 480, "10_widget_unicode_markup_long", lambda t: (t.set_diagnostics(UNICODE_LONG), t.problems_table.selectRow(2))),
               alone(1100, 480, "11_widget_stress_1200", lambda t: t.set_diagnostics(stress_diagnostics(1200))),
               alone(900, 420, "12_widget_search_and_severity", lambda t: (fill_mixed(t), t.set_filter("duplicate"), t.set_severity_filter("Fehler")))]

    menu = singles[0].build_context_menu(0)
    menu.ensurePolished()
    menu.adjustSize()
    shot("13_context_menu", menu)
    menu.deleteLater()

    apply_lab_theme(app, dark=False)
    settle()
    shot("14_widget_light", singles[1])
    shot("15_widget_light_narrow", singles[3])
    apply_lab_theme(app, dark=True)
    settle()
    for single in singles:
        single.close()
        single.deleteLater()
    settle()

    # Lab walkthrough with real input events on the visible lab.
    window.load_scenario(0)
    settle()
    shot("16_lab_start", window)
    expected = sum(len(SNAPSHOTS[source]["A"]) for source in SOURCES)
    check("Mehrere Quellen koexistieren", len(panel.visible_entries()) == expected, panel.sources())

    table = panel.problems_table
    seen: list[Diagnostic] = []
    panel.diagnosticActivated.connect(seen.append)
    point = _row_point(panel, 1)
    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    settle()
    check("Klick markiert ohne Navigationswunsch", panel.selected_diagnostic() is not None and not seen)
    selected = panel.selected_diagnostic()
    QTest.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    settle()
    check("Doppelklick: genau ein Signal mit der Originalinstanz", len(seen) == 1 and seen[0] is selected,
          None if not seen else seen[0].as_dict())
    seen.clear()
    table.setFocus()
    QTest.keyClick(table, Qt.Key.Key_Return)
    settle()
    check("Enter: genau ein Signal", len(seen) == 1 and seen[0] is selected)
    seen.clear()

    window.source_combo.setCurrentText("build")
    window.snapshot_combo.setCurrentIndex(1)
    window.revision_edit.setText("2026-11-05T10:15")
    project_before = panel.diagnostics("project")
    window.replace_button.click()
    settle()
    check("Quelle build ersetzt, project unberührt, kein Signal",
          panel.diagnostics("build") == list(SNAPSHOTS["build"]["B"]) and panel.diagnostics("project") == project_before and not seen)
    check("Revision sichtbar", "Stand: 2026-11-05T10:15" in panel.summary_label.full_text(), panel.summary_label.full_text())
    shot("17_lab_after_source_exchange", window)
    window.remove_source("host")
    settle()
    check("Quelle host entfernt", panel.sources() == ["build", "project"])

    panel.search_field.setFocus()
    QTest.keyClicks(panel.search_field, "DUPLICATE")
    settle()
    check("Live-Suche ohne Rücksicht auf Großschreibung", bool(panel.visible_entries())
          and all("Duplicate" in diagnostic.message for _, diagnostic in panel.visible_entries()))
    panel.search_field.clear()
    settle()

    window.load_scenario(1)
    settle()
    check("Nur Warnungen", panel.counts() == {"ERROR": 0, "WARNING": 3, "OTHER": 0}, panel.counts())
    window.load_scenario(2)
    settle()
    check("Leere Listen", panel.empty_state() == "none" and len(panel.sources()) == 3)
    shot("18_lab_empty", window)
    window.load_scenario(4)
    settle()
    check("1.200 Meldungen", len(panel.visible_entries()) == 1200)
    shot("19_lab_stress_1200", window)
    window.load_scenario(7)
    settle()
    check("Leerzustand abhängig vom Textfilter", panel.empty_state() == "no_match")
    shot("20_lab_no_match", window)
    window.load_scenario(8)
    settle()
    real = panel.diagnostics("project")
    check("Echte validate_project-Meldungen", bool(real) and any(diagnostic.severity == "ERROR" for diagnostic in real),
          sorted({diagnostic.code for diagnostic in real}))
    table.selectRow(0)
    shot("21_lab_real_validation", window)
    window.load_scenario(9)
    settle()
    native = panel.diagnostics("native")
    check("Nativer Fehler als eine Hülle mit Pfad /", len(native) == 1 and native[0].code == "NATIVE_PROJECT" and native[0].path == "/",
          native[0].as_dict() if native else None)
    table.selectRow(0)
    shot("22_lab_native_error", window)
    window.load_scenario(10)
    settle()
    check("Adapterquelle getrennt", "adapter" in panel.sources() and "project" in panel.sources())
    shot("23_lab_adapter_source", window)

    window.load_scenario(0)
    window.width_combo.setCurrentIndex(3)
    settle()
    table.selectRow(0)
    shot("24_lab_panel_380", window)
    window.width_combo.setCurrentIndex(0)
    window.theme_combo.setCurrentIndex(1)
    settle()
    table.selectRow(2)
    shot("25_lab_light", window)
    window.theme_combo.setCurrentIndex(0)
    settle()
    check("Clipboard unverändert ohne Nutzeraktion", clipboard.text() == original_clipboard)

    latency = measure_latency()
    report = {"platform": QGuiApplication.platformName(), "style": app.style().objectName(), "font": app.font().family(),
              "device_pixel_ratio": window.devicePixelRatio(), "checks": results,
              "passed": sum(item["passed"] for item in results), "total": len(results), "latency_ms": latency}
    (directory / "lab_walkthrough_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "lab_event_log.json").write_text(json.dumps(window.events, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Problems Panel Lab: echtes Widget, simulierter Host")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Ziel der Screenshot-Knöpfe")
    parser.add_argument("--smoke", action="store_true", help="Instanziierung, Suche, Quellwechsel; Exitcode 0 bei Erfolg")
    parser.add_argument("--evidence", type=Path, help="Durchlauf mit Screenshots, Ereignislog und Bericht in diesen Ordner")
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 10))
    apply_lab_theme(app, dark=True)
    window = ProblemsPanelLabWindow(args.output)
    try:
        if args.smoke:
            return run_smoke(window)
        if args.evidence:
            report = run_evidence(window, args.evidence)
            for item in report["checks"]:
                print(f"{'PASS' if item['passed'] else 'FAIL'}  {item['name']}")
            print(f"Nachweislauf: {report['passed']}/{report['total']} ({report['platform']}, DPR {report['device_pixel_ratio']})")
            return 0 if report["passed"] == report["total"] else 1
        window.show()
        return app.exec()
    finally:
        # Destroy the window while the application still exists. Otherwise interpreter shutdown decides the
        # order, which aborted about one of twenty smoke runs after all checks had passed.
        window.close()
        window.deleteLater()
        del window
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


if __name__ == "__main__":
    raise SystemExit(main())
