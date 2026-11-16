"""AP-WIDGET-004: ProblemsPanelWidget and the Problems Panel Lab.

Input runs through real Qt events where the behaviour depends on input. No network,
no hardware, no Logitech service. QTest.mouseMove is deliberately not used: it moves the
global cursor, which earlier let another widget's hover test depend on this module.
"""
from __future__ import annotations

import ast
import csv
import dataclasses
import importlib.util
import io
import json
import os
import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.errors import Diagnostic

try:
    from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
    from PySide6.QtGui import QColor, QContextMenuEvent, QGuiApplication, QKeyEvent, QKeySequence, QPalette, QShortcut
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QHeaderView, QWidget

    from studio.problems_panel import (DEFAULT_SOURCE, SEVERITY_ALL, SEVERITY_ERROR, SEVERITY_OTHER, SEVERITY_WARNING,
                                       ProblemsPanelWidget)
    from studio.problems_panel.model import COL_CODE, COL_MESSAGE, COL_PATH, COL_SEVERITY, COL_SOURCE, COLUMN_TITLES
    from studio.problems_panel.widget import severity_color
    HAS_QT = True
except ModuleNotFoundError as exc:
    if exc.name != "PySide6":
        raise
    HAS_QT = False

WIDGET_SOURCES = [ROOT / "src" / "studio" / "problems_panel" / name for name in ("__init__.py", "widget.py", "model.py")]
LAB = ROOT / "tools" / "run_problems_panel_lab.py"
_app = None
_restore: dict = {}


def setUpModule():
    global _app
    if not HAS_QT:
        return
    _app = QApplication.instance() or QApplication([])
    _restore.update(clipboard=QGuiApplication.clipboard().text(), palette=QPalette(_app.palette()), style=_app.style().objectName())


def tearDownModule():
    if not HAS_QT:
        return
    QGuiApplication.clipboard().setText(_restore["clipboard"])
    _app.setStyle(_restore["style"])
    _app.setPalette(_restore["palette"])
    _app.processEvents()


def lab_module():
    if "problems_panel_lab" in sys.modules:
        return sys.modules["problems_panel_lab"]
    spec = importlib.util.spec_from_file_location("problems_panel_lab", LAB)
    module = importlib.util.module_from_spec(spec)
    sys.modules["problems_panel_lab"] = module
    spec.loader.exec_module(module)
    return module


def luminance(color: "QColor") -> float:
    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(color.redF()) + 0.7152 * channel(color.greenF()) + 0.0722 * channel(color.blueF())


def contrast(a: "QColor", b: "QColor") -> float:
    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


ERR = Diagnostic("ID_DUPLICATE", "/components/3/id", "Duplicate 'a' in components")
ERR2 = Diagnostic("TYPE_MISSING", "/components/10/type", "Unknown component type 'x'")
WARN = Diagnostic("SCHEMA_NOT_PROVEN", "/bindings/4", "Payload compatibility not provable", "WARNING")
INFO = Diagnostic("NOTE", "", "Keine Pfadangabe", "INFO")
HINT = Diagnostic("TIP", "/", "Nur ein Hinweis", "HINT")


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class PanelCase(unittest.TestCase):
    def setUp(self):
        self.panel = ProblemsPanelWidget()
        self.panel.resize(1000, 460)
        self.activated = []
        self.selected = []
        self.panel.diagnosticActivated.connect(self.activated.append)
        self.panel.diagnosticSelected.connect(self.selected.append)
        self.addCleanup(self._dispose)

    def _dispose(self):
        self.panel.close()
        self.panel.deleteLater()
        _app.processEvents()

    @property
    def table(self):
        return self.panel.problems_table

    @property
    def model(self):
        return self.panel.problems_table.model()

    def show(self):
        self.panel.show()
        _app.processEvents()

    def fill(self):
        self.panel.set_source_diagnostics("project", [ERR, ERR2, WARN], revision="r1")
        self.panel.set_source_diagnostics("build", [INFO, ERR], revision="b7")
        self.panel.set_source_diagnostics("host", [HINT])

    def visible(self):
        return [diagnostic for _, diagnostic in self.panel.visible_entries()]

    def cell_point(self, row, column=1):
        index = self.model.index(row, column)
        self.table.scrollTo(index)
        _app.processEvents()
        return self.table.visualRect(index).center()

    def click_row(self, row, button=None):
        QTest.mouseClick(self.table.viewport(), button or Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self.cell_point(row))
        _app.processEvents()

    def double_click_row(self, row):
        QTest.mouseDClick(self.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self.cell_point(row))
        _app.processEvents()

    def row_of(self, diagnostic, source=None):
        for position, (entry_source, entry) in enumerate(self.panel.visible_entries()):
            if entry is diagnostic and (source is None or entry_source == source):
                return position
        self.fail(f"{diagnostic} not visible")

    def menu_action(self, menu, text):
        for action in menu.actions():
            if action.text().startswith(text):
                return action
        self.fail(f"no action {text!r}")


# 1. ------------------------------------------------------------------ Diagnostic contract


class DiagnosticContractTests(PanelCase):
    def test_core_diagnostic_contract_is_the_expected_one(self):
        fields = dataclasses.fields(Diagnostic)
        self.assertEqual([field.name for field in fields], ["code", "path", "message", "severity"])
        self.assertEqual(fields[3].default, "ERROR")
        self.assertTrue(Diagnostic.__dataclass_params__.frozen)
        sample = Diagnostic("C", "/p", "m", "INFO")
        self.assertEqual(sample.as_dict(), {"code": "C", "path": "/p", "message": "m", "severity": "INFO"})
        self.assertEqual(sample.sort_key(), ("/p", "C", "m", "INFO"))

    def test_instances_are_kept_by_reference_and_unchanged(self):
        items = [Diagnostic(" Code ", "  /Odd//Path ", " Text\n mit  Rand ", "error"), Diagnostic("", "", "", "")]
        before = [item.as_dict() for item in items]
        self.panel.set_diagnostics(items)
        kept = self.panel.diagnostics(DEFAULT_SOURCE)
        self.assertIs(kept[0], items[0])
        self.assertIs(kept[1], items[1])
        self.assertEqual([item.as_dict() for item in kept], before)

    def test_source_of_the_snapshot_can_change_later_without_touching_the_view(self):
        items = [ERR]
        self.panel.set_diagnostics(items)
        items.append(WARN)
        items[0] = HINT
        self.assertEqual(self.panel.diagnostics(DEFAULT_SOURCE), [ERR])
        self.assertEqual(self.panel.counts()["WARNING"], 0)

    def test_only_diagnostics_are_accepted_and_a_refused_call_changes_nothing(self):
        self.panel.set_source_diagnostics("project", [ERR], revision="r1")
        for bad in ([{"code": "X", "path": "/", "message": "m"}], [ERR, "text"], "abc", [None]):
            with self.assertRaises(TypeError):
                self.panel.set_source_diagnostics("project", bad, revision="r2")
        with self.assertRaises(TypeError):
            self.panel.set_source_diagnostics("project", ERR)
        with self.assertRaises(TypeError):
            self.panel.set_source_diagnostics(7, [])
        with self.assertRaises(TypeError):
            self.panel.set_source_diagnostics("project", [], revision=3)
        for empty in ("", "   "):
            with self.assertRaises(ValueError):
                self.panel.set_source_diagnostics(empty, [])
        self.assertEqual(self.panel.diagnostics("project"), [ERR])
        self.assertEqual(self.panel.source_revision("project"), "r1")
        self.assertEqual(self.panel.sources(), ["project"])

    def test_non_string_fields_do_not_break_the_view(self):
        odd = Diagnostic(404, None, ["liste"], 2)
        self.panel.set_diagnostics([odd, ERR])
        self.assertIs(self.panel.diagnostics(DEFAULT_SOURCE)[0], odd)
        self.panel.set_filter("404")
        self.assertEqual(self.visible(), [odd])

    def test_widget_sources_keep_their_boundaries(self):
        allowed = {"PySide6", "core", "studio", "__future__", "collections", "csv", "html", "io", "json", "re", "unicodedata", "typing"}
        forbidden_calls = {"open", "exec", "eval", "__import__"}
        for path in WIDGET_SOURCES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for name in node.names:
                        self.assertIn(name.name.split(".")[0], allowed, path.name)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    self.assertIn(module.split(".")[0], allowed, path.name)
                    if module.startswith("core"):
                        self.assertEqual(module, "core.errors")
                    if module.startswith("studio"):
                        self.assertTrue(module.startswith("studio.problems_panel"), module)
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, forbidden_calls, path.name)
            source = path.read_text(encoding="utf-8")
            for word in ("StudioWindow", "validate_project", "parse_native_project", "QProcess", "QNetwork", "write_text", "setStyleSheet"):
                self.assertNotIn(word, source, path.name)

    def test_import_needs_neither_the_studio_window_nor_adapters(self):
        script = textwrap.dedent("""
            import sys
            sys.path.insert(0, sys.argv[1])
            import studio.problems_panel
            loaded = sorted(n for n in sys.modules if n.split('.')[0] in ('adapters', 'runtime', 'library', 'symbol_designer')
                            or n in ('studio.app', 'studio.keypad_preview', 'studio.action_catalog'))
            print(loaded)
        """)
        result = subprocess.run([sys.executable, "-c", script, str(ROOT / "src")], capture_output=True, text=True, timeout=60,
                                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "[]")


# 2. ------------------------------------------------------------------ sources


class SourceTests(PanelCase):
    def test_sources_coexist_and_an_update_replaces_only_its_own(self):
        self.fill()
        self.assertEqual(self.panel.sources(), ["build", "host", "project"])
        build, host = self.panel.diagnostics("build"), self.panel.diagnostics("host")
        self.panel.set_source_diagnostics("project", [WARN], revision="r2")
        self.assertEqual(self.panel.diagnostics("project"), [WARN])
        self.assertEqual(self.panel.diagnostics("build"), build)
        self.assertEqual(self.panel.diagnostics("host"), host)
        self.assertEqual(self.panel.source_revision("build"), "b7")

    def test_removing_a_source_leaves_the_others(self):
        self.fill()
        self.panel.remove_source("build")
        self.assertEqual(self.panel.sources(), ["host", "project"])
        self.assertEqual(self.panel.diagnostics("project"), [ERR, ERR2, WARN])
        self.assertEqual(self.panel.diagnostics("build"), [])
        self.panel.remove_source("gibt-es-nicht")
        self.assertEqual(self.panel.sources(), ["host", "project"])

    def test_set_diagnostics_replaces_only_the_default_channel(self):
        self.fill()
        self.panel.set_diagnostics([HINT])
        self.assertEqual(self.panel.diagnostics(DEFAULT_SOURCE), [HINT])
        self.assertEqual(self.panel.diagnostics("build"), [INFO, ERR])
        self.assertEqual(self.panel.diagnostics("host"), [HINT])
        self.assertIsNone(self.panel.source_revision(DEFAULT_SOURCE))

    def test_an_empty_source_stays_listed_until_it_is_removed(self):
        self.panel.set_source_diagnostics("build", [], revision="b1")
        self.assertEqual(self.panel.sources(), ["build"])
        self.assertIn("build 0 (Stand: b1)", self.panel.summary_label.full_text())
        self.panel.remove_source("build")
        self.assertEqual(self.panel.sources(), [])

    def test_revision_is_opaque_and_never_compared(self):
        self.panel.set_source_diagnostics("build", [ERR], revision="zzz-new")
        self.panel.set_source_diagnostics("build", [WARN], revision="aaa-older-looking")
        self.assertEqual(self.panel.diagnostics("build"), [WARN])
        self.assertEqual(self.panel.source_revision("build"), "aaa-older-looking")
        summary = self.panel.summary_label.full_text()
        self.assertIn("Stand: aaa-older-looking", summary)
        for claim in ("aktuell", "gültig", "geprüft", "erfolgreich"):
            self.assertNotIn(claim, summary.casefold())

    def test_no_revision_means_no_stand_text(self):
        self.panel.set_source_diagnostics("host", [ERR])
        self.assertNotIn("Stand", self.panel.summary_label.full_text())
        self.assertIsNone(self.panel.source_revision("host"))
        self.assertIsNone(self.panel.source_revision("unbekannt"))

    def test_same_instance_in_two_sources_stays_two_entries(self):
        self.panel.set_source_diagnostics("a", [ERR])
        self.panel.set_source_diagnostics("b", [ERR])
        self.assertEqual(self.panel.visible_entries(), [("a", ERR), ("b", ERR)])
        self.panel.remove_source("a")
        self.assertEqual(self.panel.visible_entries(), [("b", ERR)])


# 3. ------------------------------------------------------------------ counting and filters


class CountAndFilterTests(PanelCase):
    def test_counts_keep_the_source_severity(self):
        self.panel.set_diagnostics([ERR, ERR2, WARN, INFO, HINT, Diagnostic("X", "/", "m", "error"), Diagnostic("Y", "/", "m", "")])
        self.assertEqual(self.panel.counts(), {"ERROR": 2, "WARNING": 1, "OTHER": 4})
        self.assertEqual(self.panel.severity_buttons[SEVERITY_ERROR].full_text(), "2 Fehler")
        self.assertEqual(self.panel.severity_buttons[SEVERITY_WARNING].full_text(), "1 Warnung")
        self.assertEqual(self.panel.severity_buttons[SEVERITY_OTHER].full_text(), "4 Weitere")
        self.assertEqual(self.panel.severity_buttons[SEVERITY_ALL].full_text(), "Alle 7")

    def test_zero_errors_are_stated(self):
        self.panel.set_diagnostics([WARN])
        self.assertEqual(self.panel.severity_buttons[SEVERITY_ERROR].full_text(), "0 Fehler")
        self.assertEqual(self.panel.severity_buttons[SEVERITY_ERROR].accessibleName(), "0 Fehler")

    def test_filters_do_not_change_the_counts(self):
        self.fill()
        before = self.panel.counts()
        self.panel.set_filter("kein-treffer")
        self.panel.set_severity_filter("Warnungen")
        self.assertEqual(self.panel.counts(), before)
        self.assertEqual(self.panel.severity_buttons[SEVERITY_ERROR].full_text(), "3 Fehler")

    def test_severity_filter_and_its_names(self):
        self.fill()
        for names, expected in ((("ERROR", "Fehler", "error"), [ERR, ERR, ERR2]), (("WARNING", "Warnungen"), [WARN]),
                                (("OTHER", "Weitere"), [HINT, INFO]), (("ALL", "Alle"), [ERR, ERR, ERR2, WARN, HINT, INFO])):
            for name in names:
                self.panel.set_severity_filter(name)
                self.assertEqual(self.visible(), expected, name)
        self.assertEqual(self.panel.severity_filter(), SEVERITY_ALL)

    def test_unknown_severity_filter_is_refused(self):
        self.fill()
        self.panel.set_severity_filter("Fehler")
        for bad in ("INFO", "", None):
            with self.assertRaises(ValueError):
                self.panel.set_severity_filter(bad)
        self.assertEqual(self.panel.severity_filter(), SEVERITY_ERROR)

    def test_severity_button_click_filters(self):
        self.fill()
        self.show()
        QTest.mouseClick(self.panel.severity_buttons[SEVERITY_WARNING], Qt.MouseButton.LeftButton)
        self.assertEqual(self.visible(), [WARN])
        self.assertEqual(self.panel.severity_filter(), SEVERITY_WARNING)
        QTest.mouseClick(self.panel.severity_buttons[SEVERITY_WARNING], Qt.MouseButton.LeftButton)
        self.assertEqual(self.panel.severity_filter(), SEVERITY_WARNING, "exclusive: a second click keeps the choice")

    def test_search_covers_code_path_message_and_source_ignoring_case(self):
        self.fill()
        for text, expected in (("type_missing", [ERR2]), ("/BINDINGS/4", [WARN]), ("pAyLoAd", [WARN]), ("BUILD", [ERR, INFO])):
            self.panel.set_filter(text)
            self.assertEqual(self.visible(), expected, text)

    def test_search_does_not_look_at_severity_or_revision(self):
        self.fill()
        self.panel.set_filter("warning")
        self.assertEqual(self.visible(), [])
        self.panel.set_filter("b7")
        self.assertEqual(self.visible(), [])

    def test_all_words_must_match_across_fields(self):
        self.fill()
        self.panel.set_filter("  duplicate   build ")
        self.assertEqual(self.panel.visible_entries(), [("build", ERR)])

    def test_text_and_severity_combine(self):
        self.panel.set_diagnostics([ERR, Diagnostic("ID_DUPLICATE", "/x", "Duplicate", "WARNING")])
        self.panel.set_filter("id_duplicate")
        self.panel.set_severity_filter(SEVERITY_WARNING)
        self.assertEqual([d.severity for d in self.visible()], ["WARNING"])

    def test_typing_filters_live(self):
        self.fill()
        self.show()
        QTest.keyClicks(self.panel.search_field, "payl")
        self.assertEqual(self.visible(), [WARN])
        self.assertEqual(self.panel.filter_text(), "payl")

    def test_find_shortcut_is_local_to_the_panel_and_focuses_the_search(self):
        self.show()
        shortcuts = [item for item in self.panel.findChildren(QShortcut) if item.key() == QKeySequence(QKeySequence.StandardKey.Find)]
        self.assertEqual(len(shortcuts), 1)
        self.assertEqual(shortcuts[0].context(), Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.panel.set_filter("abc")
        shortcuts[0].activated.emit()
        self.assertEqual(self.panel.search_field.selectedText(), "abc")

    def test_escape_clears_the_search(self):
        self.fill()
        self.show()
        self.panel.set_filter("payl")
        self.panel.search_field.setFocus()
        QTest.keyClick(self.panel.search_field, Qt.Key.Key_Escape)
        self.assertEqual(self.panel.filter_text(), "")
        self.assertEqual(len(self.visible()), 6)

    def test_down_key_moves_from_search_to_results(self):
        self.fill()
        self.panel.activateWindow()
        self.show()
        self.panel.search_field.setFocus()
        QTest.keyClick(self.panel.search_field, Qt.Key.Key_Down)
        self.assertEqual(self.panel.selected_diagnostic(), self.visible()[0])
        self.assertEqual(self.activated, [])

    def test_set_filter_refuses_non_text(self):
        with self.assertRaises(TypeError):
            self.panel.set_filter(None)

    def test_summary_shows_filtered_and_total(self):
        self.fill()
        self.assertTrue(self.panel.summary_label.full_text().startswith("6 Meldungen"))
        self.panel.set_filter("payload")
        self.assertTrue(self.panel.summary_label.full_text().startswith("1 von 6 Meldungen"))


# 4. ------------------------------------------------------------------ clear, empty states, long text, Unicode


class EmptyAndTextTests(PanelCase):
    def test_no_source_and_empty_source_read_as_no_problems_without_claiming_a_check(self):
        self.assertEqual(self.panel.empty_state(), "none")
        self.assertEqual(self.panel.empty_title.text(), "Keine Probleme")
        self.assertIn("noch keine Prüfergebnisse", self.panel.empty_detail.text())
        self.panel.set_diagnostics([])
        self.assertEqual(self.panel.empty_title.text(), "Keine Probleme")
        self.assertIn("keine Meldungen geliefert", self.panel.empty_detail.text())
        self.assertIs(self.panel.result_stack.currentWidget(), self.panel.empty_page)

    def test_filter_without_match_has_its_own_state_and_a_working_reset(self):
        self.fill()
        self.show()
        self.panel.set_filter("kein-treffer")
        self.assertEqual(self.panel.empty_state(), "no_match")
        self.assertEqual(self.panel.empty_title.text(), "Kein Treffer für Filter")
        self.assertTrue(self.panel.empty_reset.isVisible())
        QTest.mouseClick(self.panel.empty_reset, Qt.MouseButton.LeftButton)
        self.assertEqual(self.panel.filter_text(), "")
        self.assertEqual(self.panel.empty_state(), "")
        self.assertIs(self.panel.result_stack.currentWidget(), self.table)

    def test_severity_filter_without_match_is_also_a_filter_state(self):
        self.panel.set_diagnostics([WARN])
        self.panel.set_severity_filter(SEVERITY_ERROR)
        self.assertEqual(self.panel.empty_state(), "no_match")
        self.panel.empty_reset.click()
        self.assertEqual(self.panel.severity_filter(), SEVERITY_ALL)

    def test_clear_removes_all_sources_and_keeps_view_settings(self):
        self.fill()
        self.panel.set_filter("payload")
        self.panel.set_severity_filter(SEVERITY_WARNING)
        self.panel.clear()
        self.assertEqual(self.panel.sources(), [])
        self.assertEqual(self.panel.diagnostics(), [])
        self.assertEqual(self.panel.counts(), {"ERROR": 0, "WARNING": 0, "OTHER": 0})
        self.assertEqual(self.panel.empty_state(), "none", "without data a filter hides nothing")
        self.assertEqual(self.panel.filter_text(), "payload")
        self.panel.set_diagnostics([WARN])
        self.assertEqual(self.visible(), [WARN])

    def test_reset_filters_does_not_touch_data(self):
        self.fill()
        self.panel.set_filter("payload")
        self.panel.set_severity_filter(SEVERITY_WARNING)
        self.panel.reset_filters()
        self.assertEqual(len(self.visible()), 6)
        self.assertEqual(self.panel.sources(), ["build", "host", "project"])

    def test_empty_state_produces_no_rows_or_artificial_results(self):
        self.panel.set_diagnostics([])
        self.assertEqual(self.model.rowCount(), 0)
        self.assertEqual(self.panel.diagnostics(), [])
        self.assertEqual(self.panel.detail_text(), "")

    def test_long_text_stays_complete_outside_the_table_cell(self):
        long_message = "Wort " * 2000 + "ENDE"
        diagnostic = Diagnostic("LONG", "/a/" + "b/" * 200, long_message)
        self.panel.set_diagnostics([diagnostic])
        self.table.selectRow(0)
        shown = self.model.index(0, COL_MESSAGE).data()
        self.assertLess(len(shown), 500)
        self.assertTrue(shown.endswith("…"))
        self.assertIn(long_message, self.panel.detail_text())
        self.assertIn(diagnostic.path, self.panel.detail_text())
        self.assertLess(len(self.model.index(0, COL_MESSAGE).data(Qt.ItemDataRole.ToolTipRole)), 2300)
        self.assertEqual(self.panel.selected_diagnostic().message, long_message)

    def test_line_breaks_show_on_one_row_and_stay_in_the_original(self):
        diagnostic = Diagnostic("LINES", "/", "eins\nzwei\r\ndrei\tvier")
        self.panel.set_diagnostics([diagnostic])
        self.table.selectRow(0)
        shown = self.model.index(0, COL_MESSAGE).data()
        self.assertNotIn("\n", shown)
        self.assertNotIn("\t", shown)
        self.assertIn("eins", self.panel.detail_text())
        self.assertEqual(self.panel.selected_diagnostic().message, "eins\nzwei\r\ndrei\tvier")

    def test_unicode_search_and_display(self):
        diagnostic = Diagnostic("ÄÖÜ_CODE", "/größe/日本語", "Straße 🎛️ שלום")
        self.panel.set_diagnostics([diagnostic, ERR])
        for text in ("äöü_code", "STRASSE", "日本語", "🎛️", "שלום", "GRÖSSE"):
            self.panel.set_filter(text)
            self.assertEqual(self.visible(), [diagnostic], text)
        self.panel.set_filter("")
        self.table.selectRow(self.row_of(diagnostic))
        self.assertIn("Straße 🎛️ שלום", self.panel.detail_text())

    def test_decomposed_unicode_matches_composed_search(self):
        diagnostic = Diagnostic("X", "/", "Gro\u0308ße")
        self.panel.set_diagnostics([diagnostic])
        self.panel.set_filter("gr\u00f6ße")
        self.assertEqual(self.visible(), [diagnostic])

    def test_foreign_text_is_never_markup(self):
        diagnostic = Diagnostic("<b>CODE</b>", "/<i>p</i>", "<img src=x> & <b>fett</b>")
        self.panel.set_diagnostics([diagnostic])
        self.table.selectRow(0)
        self.assertIn("<img src=x> & <b>fett</b>", self.panel.detail_text())
        tooltip = self.model.index(0, COL_MESSAGE).data(Qt.ItemDataRole.ToolTipRole)
        self.assertIn("&lt;img src=x&gt; &amp; &lt;b&gt;fett&lt;/b&gt;", tooltip)
        self.assertNotIn("<img", tooltip)
        self.panel.set_source_diagnostics("<b>quelle</b>", [], revision="<i>r</i>")
        self.assertNotIn("<b>quelle", self.panel.summary_label.toolTip())
        self.assertEqual(self.panel.summary_label.textFormat(), Qt.TextFormat.PlainText)


# 5. ------------------------------------------------------------------ sorting and identity


class SortAndIdentityTests(PanelCase):
    def test_default_order_is_severity_then_source_then_path_naturally(self):
        c2 = Diagnostic("A", "/components/2", "m")
        c10 = Diagnostic("A", "/components/10", "m")
        self.panel.set_source_diagnostics("z", [c10, c2])
        self.panel.set_source_diagnostics("a", [WARN, HINT, ERR])
        self.assertEqual(self.panel.visible_entries(), [("a", ERR), ("z", c2), ("z", c10), ("a", WARN), ("a", HINT)])

    def test_order_does_not_depend_on_delivery_order(self):
        items = [ERR, ERR2, WARN, INFO, HINT, Diagnostic("A", "/a", "b"), Diagnostic("A", "/a", "a")]
        self.panel.set_source_diagnostics("a", items)
        self.panel.set_source_diagnostics("b", items[:3])
        first = [(source, d.as_dict()) for source, d in self.panel.visible_entries()]
        other = ProblemsPanelWidget()
        self.addCleanup(other.deleteLater)
        other.set_source_diagnostics("b", list(reversed(items[:3])))
        other.set_source_diagnostics("a", list(reversed(items)))
        self.assertEqual([(source, d.as_dict()) for source, d in other.visible_entries()], first)

    def test_equal_diagnostics_keep_delivery_order(self):
        one, two, three = (Diagnostic("A", "/", "m") for _ in range(3))
        self.panel.set_diagnostics([one, two, three])
        rows = [d for _, d in self.panel.visible_entries()]
        self.assertTrue(rows[0] is one and rows[1] is two and rows[2] is three)

    def test_header_sort_each_column_both_directions_with_stable_ties(self):
        self.fill()
        self.show()
        base = self.panel.visible_entries()
        for column in range(len(COLUMN_TITLES)):
            self.table.sortByColumn(column, Qt.SortOrder.AscendingOrder)
            ascending = self.panel.visible_entries()
            self.table.sortByColumn(column, Qt.SortOrder.DescendingOrder)
            descending = self.panel.visible_entries()
            self.assertEqual(sorted(map(repr, ascending)), sorted(map(repr, base)))
            self.assertEqual(sorted(map(repr, descending)), sorted(map(repr, base)))
            self.table.sortByColumn(column, Qt.SortOrder.AscendingOrder)
            self.assertEqual(self.panel.visible_entries(), ascending, "repeatable")
        self.table.sortByColumn(COL_SOURCE, Qt.SortOrder.DescendingOrder)
        self.assertEqual([source for source, _ in self.panel.visible_entries()], ["project"] * 3 + ["host"] + ["build"] * 2)
        self.assertEqual([d for s, d in self.panel.visible_entries() if s == "project"], [ERR, ERR2, WARN], "ties keep base order")

    def test_clicking_the_header_sorts(self):
        self.fill()
        self.show()
        header = self.table.horizontalHeader()
        point = QPoint(header.sectionViewportPosition(COL_CODE) + 8, header.height() // 2)
        QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        codes = [d.code for d in self.visible()]
        self.assertEqual(codes, sorted(codes, key=str.casefold))
        self.assertEqual(self.activated, [])

    def test_sorting_survives_updates_and_filters(self):
        self.fill()
        self.table.sortByColumn(COL_CODE, Qt.SortOrder.DescendingOrder)
        self.panel.set_source_diagnostics("host", [WARN])
        codes = [d.code for d in self.visible()]
        self.assertEqual(codes, sorted(codes, key=str.casefold, reverse=True))
        self.panel.set_filter("a")
        codes = [d.code for d in self.visible()]
        self.assertEqual(codes, sorted(codes, key=str.casefold, reverse=True))

    def test_selection_follows_its_row_through_a_header_sort(self):
        self.fill()
        self.show()
        self.click_row(self.row_of(WARN))
        self.table.sortByColumn(COL_CODE, Qt.SortOrder.DescendingOrder)
        self.assertIs(self.panel.selected_diagnostic(), WARN)
        self.assertEqual(self.selected, [WARN], "sorting is no new selection")

    def test_same_text_from_two_sources_is_not_confused(self):
        self.panel.set_source_diagnostics("project", [ERR])
        same_text = Diagnostic(*ERR.as_dict().values())
        self.panel.set_source_diagnostics("build", [same_text])
        self.assertEqual(ERR, same_text)
        self.show()
        row = self.row_of(same_text, "build")
        self.click_row(row)
        self.assertIs(self.panel.selected_diagnostic(), same_text)
        self.assertEqual(self.panel.selected_source(), "build")
        self.panel.remove_source("project")
        self.assertIs(self.panel.selected_diagnostic(), same_text)
        self.assertEqual(self.panel.selected_source(), "build")
        self.panel.set_source_diagnostics("project", [ERR])
        self.panel.remove_source("build")
        self.assertIsNone(self.panel.selected_diagnostic(), "the other source's equal message is another entry")

    def test_activation_identifies_the_row_of_the_other_source(self):
        one, two = Diagnostic("A", "/", "m"), Diagnostic("A", "/", "m")
        self.panel.set_source_diagnostics("a", [one])
        self.panel.set_source_diagnostics("b", [two])
        self.show()
        self.double_click_row(self.row_of(two, "b"))
        self.assertEqual(len(self.activated), 1)
        self.assertIs(self.activated[0], two)


# 6. ------------------------------------------------------------------ activation signal


class ActivationTests(PanelCase):
    def setUp(self):
        super().setUp()
        self.fill()
        self.show()

    def test_double_click_sends_exactly_one_signal_with_the_original(self):
        row = self.row_of(WARN)
        self.double_click_row(row)
        self.assertEqual(len(self.activated), 1)
        self.assertIs(self.activated[0], WARN)

    def test_single_click_selects_and_does_not_navigate(self):
        self.click_row(self.row_of(WARN))
        self.assertEqual(self.activated, [])
        self.assertIs(self.panel.selected_diagnostic(), WARN)
        self.assertEqual(self.selected, [WARN])

    def test_qt_activated_signal_is_not_the_path(self):
        """Some styles fire QAbstractItemView.activated on a single click; that must not be a navigation wish."""
        self.table.activated.emit(self.model.index(0, 0))
        self.assertEqual(self.activated, [])

    def test_enter_and_return_send_exactly_one_signal(self):
        self.click_row(self.row_of(WARN))
        self.table.setFocus()
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.activated.clear()
            QTest.keyClick(self.table, key)
            self.assertEqual(len(self.activated), 1, key)
            self.assertIs(self.activated[0], WARN)

    def test_key_auto_repeat_does_not_send_a_series(self):
        self.click_row(self.row_of(WARN))
        repeat = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier, "", True)
        self.table.keyPressEvent(repeat)
        self.assertEqual(self.activated, [])

    def test_enter_without_a_current_row_sends_nothing(self):
        QTest.keyClick(self.table, Qt.Key.Key_Return)
        self.assertEqual(self.activated, [])

    def test_keyboard_moves_the_selection_without_navigating(self):
        self.click_row(0)
        self.table.setFocus()
        QTest.keyClick(self.table, Qt.Key.Key_Down)
        self.assertIs(self.panel.selected_diagnostic(), self.visible()[1])
        self.assertEqual(self.activated, [])
        self.assertEqual(len(self.selected), 2)

    def test_double_click_on_the_empty_area_or_other_button_sends_nothing(self):
        bottom = QPoint(10, self.table.viewport().height() - 2)
        self.assertFalse(self.table.indexAt(bottom).isValid())
        QTest.mouseDClick(self.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, bottom)
        QTest.mouseDClick(self.table.viewport(), Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, self.cell_point(0))
        self.assertEqual(self.activated, [])

    def test_empty_and_root_paths_are_delivered_unchanged(self):
        for diagnostic in (INFO, HINT):
            self.activated.clear()
            self.double_click_row(self.row_of(diagnostic))
            self.assertEqual(len(self.activated), 1)
            self.assertIs(self.activated[0], diagnostic)
            self.assertEqual(self.activated[0].path, diagnostic.path)

    def test_programmatic_updates_send_no_signal(self):
        self.activated.clear()
        self.selected.clear()
        self.click_row(0)
        self.selected.clear()
        self.panel.set_source_diagnostics("project", [WARN], revision="r2")
        self.panel.set_source_diagnostics("build", [])
        self.panel.remove_source("host")
        self.panel.set_filter("x")
        self.panel.set_severity_filter(SEVERITY_ERROR)
        self.panel.reset_filters()
        self.panel.set_diagnostics([ERR])
        self.table.sortByColumn(COL_MESSAGE, Qt.SortOrder.DescendingOrder)
        self.panel.clear()
        self.assertEqual(self.activated, [])
        self.assertEqual(self.selected, [])

    def test_context_menu_request_sends_one_signal_for_its_row(self):
        menu = self.panel.build_context_menu(self.row_of(WARN))
        self.addCleanup(menu.deleteLater)
        self.menu_action(menu, "Navigation anfordern").trigger()
        self.assertEqual(len(self.activated), 1)
        self.assertIs(self.activated[0], WARN)
        self.assertIs(self.panel.selected_diagnostic(), WARN)

    def test_host_slot_may_update_during_activation(self):
        self.panel.diagnosticActivated.connect(lambda _: self.panel.set_diagnostics([HINT]))
        self.double_click_row(self.row_of(WARN))
        self.assertEqual(len(self.activated), 1)
        self.assertEqual(self.panel.diagnostics(DEFAULT_SOURCE), [HINT])
        self.assertIsNone(self.panel.selected_diagnostic())

    def test_activation_does_not_switch_or_touch_anything_else(self):
        before = (self.panel.sources(), self.panel.counts(), self.panel.visible_entries())
        self.double_click_row(self.row_of(WARN))
        self.assertEqual((self.panel.sources(), self.panel.counts(), self.panel.visible_entries()), before)


# 7. ------------------------------------------------------------------ paths and stale entries


class PathAndStaleTests(PanelCase):
    PATHS = ("/", "", "/unbekannt/bereich", "kein-pointer", "/a~1b/~0c", "//doppelt//", " /mit rand ", "/components/3/id")

    def test_paths_are_neither_changed_nor_invented(self):
        items = [Diagnostic("P", path, f"Pfad {index}") for index, path in enumerate(self.PATHS)]
        self.panel.set_diagnostics(items)
        self.assertEqual({d.path for d in self.panel.diagnostics(DEFAULT_SOURCE)}, set(self.PATHS))
        for position in range(self.model.rowCount()):
            row_diagnostic = self.visible()[position]
            self.assertEqual(self.model.index(position, COL_PATH).data(), row_diagnostic.path)
            self.table.selectRow(position)
            self.assertIs(self.panel.selected_diagnostic(), row_diagnostic)

    def test_message_text_is_not_turned_into_a_pointer(self):
        diagnostic = Diagnostic("ADAPTER_CAPABILITY", "/", "Fehler bei /components/3/id und /views/0")
        self.panel.set_diagnostics([diagnostic])
        self.assertEqual(self.model.index(0, COL_PATH).data(), "/")
        self.table.selectRow(0)
        self.assertIn("Pfad: /\n", self.panel.detail_text())

    def test_removed_source_cannot_stay_selected_or_be_activated(self):
        self.fill()
        self.show()
        self.click_row(self.row_of(HINT))
        self.selected.clear()
        self.panel.remove_source("host")
        self.assertIsNone(self.panel.selected_diagnostic())
        self.assertEqual(self.panel.detail_text(), "")
        self.table.setFocus()
        QTest.keyClick(self.table, Qt.Key.Key_Return)
        self.assertEqual(self.activated, [])
        self.assertEqual(self.selected, [])

    def test_a_menu_opened_on_an_old_snapshot_cannot_activate_or_copy_it(self):
        self.fill()
        menu = self.panel.build_context_menu(0)
        self.addCleanup(menu.deleteLater)
        clipboard = QGuiApplication.clipboard()
        clipboard.setText("unberührt")
        self.panel.clear()
        self.panel.set_diagnostics([WARN])
        for text in ("Navigation anfordern", "Eintrag kopieren", "Fehlercode kopieren", "Pfad kopieren"):
            self.menu_action(menu, text).trigger()
        self.assertEqual(self.activated, [])
        self.assertEqual(clipboard.text(), "unberührt")

    def test_selection_follows_the_same_message_into_a_new_snapshot_as_the_new_instance(self):
        self.fill()
        self.show()
        self.click_row(self.row_of(WARN))
        self.selected.clear()
        replacement = Diagnostic(*WARN.as_dict().values())
        self.panel.set_source_diagnostics("project", [ERR2, replacement, ERR])
        self.assertIs(self.panel.selected_diagnostic(), replacement)
        self.assertIsNot(self.panel.selected_diagnostic(), WARN)
        self.assertEqual(self.selected, [])
        self.table.setFocus()
        QTest.keyClick(self.table, Qt.Key.Key_Return)
        self.assertIs(self.activated[-1], replacement)

    def test_selection_never_jumps_to_another_message(self):
        self.fill()
        self.show()
        self.click_row(self.row_of(WARN))
        self.panel.set_source_diagnostics("project", [ERR, ERR2, Diagnostic(WARN.code, WARN.path, "geänderter Text", WARN.severity)])
        self.assertIsNone(self.panel.selected_diagnostic())
        self.assertFalse(self.table.currentIndex().isValid())
        self.assertEqual(self.panel.detail_text(), "")

    def test_selection_of_a_repeated_message_keeps_its_occurrence(self):
        first, second = Diagnostic("A", "/", "m"), Diagnostic("A", "/", "m")
        self.panel.set_diagnostics([first, second])
        self.table.selectRow(1)
        self.assertIs(self.panel.selected_diagnostic(), second)
        new_first, new_second = Diagnostic("A", "/", "m"), Diagnostic("A", "/", "m")
        self.panel.set_diagnostics([new_first, new_second])
        self.assertIs(self.panel.selected_diagnostic(), new_second)
        only = Diagnostic("A", "/", "m")
        self.panel.set_diagnostics([only])
        self.assertIsNone(self.panel.selected_diagnostic(), "the second occurrence is gone")

    def test_update_of_another_source_keeps_selection_instance_and_focus(self):
        self.fill()
        self.panel.activateWindow()
        self.show()
        self.click_row(self.row_of(WARN))
        self.table.setFocus()
        self.panel.set_source_diagnostics("build", [])
        self.assertIs(self.panel.selected_diagnostic(), WARN)
        if self.panel.isActiveWindow():
            self.assertTrue(self.table.hasFocus())

    def test_filter_hides_a_selection_and_brings_it_back(self):
        self.fill()
        self.show()
        self.click_row(self.row_of(WARN))
        self.selected.clear()
        self.panel.set_filter("duplicate")
        self.assertIsNone(self.panel.selected_diagnostic())
        self.assertEqual(self.panel.detail_text(), "")
        self.panel.set_filter("")
        self.assertIs(self.panel.selected_diagnostic(), WARN)
        self.assertIn(WARN.message, self.panel.detail_text())
        self.assertEqual(self.selected, [])

    def test_selection_hidden_by_a_filter_is_dropped_when_its_source_goes(self):
        self.fill()
        self.show()
        self.click_row(self.row_of(HINT))
        self.panel.set_filter("duplicate")
        self.panel.remove_source("host")
        self.panel.set_filter("")
        self.assertIsNone(self.panel.selected_diagnostic())

    def test_scroll_position_survives_an_update_of_another_source(self):
        lab = lab_module()
        self.panel.set_diagnostics(lab.stress_diagnostics(1200))
        self.show()
        bar = self.table.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        before = bar.value()
        self.assertGreater(before, 0)
        self.panel.set_source_diagnostics("host", [HINT])
        _app.processEvents()
        self.assertEqual(bar.value(), before)

    def test_selected_row_stays_on_screen_through_a_filter(self):
        lab = lab_module()
        items = lab.stress_diagnostics(1200)
        self.panel.set_diagnostics(items)
        self.show()
        position = self.row_of(items[700])
        self.table.selectRow(position)
        self.table.scrollTo(self.model.index(position, 0))
        self.panel.set_filter("bereich")
        _app.processEvents()
        new_position = self.row_of(items[700])
        rect = self.table.visualRect(self.model.index(new_position, 0))
        self.assertTrue(self.table.viewport().rect().intersects(rect))

    def test_detail_view_is_read_only_and_empty_without_selection(self):
        self.fill()
        self.assertTrue(self.panel.detail_view.isReadOnly())
        self.assertEqual(self.panel.detail_text(), "")
        self.table.selectRow(self.row_of(ERR2))
        detail = self.panel.detail_text()
        for part in (ERR2.code, ERR2.path, ERR2.message, ERR2.severity, "project", "Stand: r1"):
            self.assertIn(part, detail)

    def test_table_cells_are_not_editable(self):
        self.fill()
        index = self.model.index(0, COL_MESSAGE)
        self.assertFalse(self.model.flags(index) & Qt.ItemFlag.ItemIsEditable)
        self.assertFalse(self.model.setData(index, "x"))


# 8. ------------------------------------------------------------------ clipboard


class ClipboardTests(PanelCase):
    def setUp(self):
        super().setUp()
        self.clipboard = QGuiApplication.clipboard()
        self.clipboard.setText("vorher")
        self.fill()
        self.show()

    def test_no_copy_without_user_action(self):
        self.table.selectRow(0)
        self.panel.set_filter("a")
        self.panel.reset_filters()
        self.panel.set_source_diagnostics("host", [])
        menu = self.panel.build_context_menu(0)
        self.addCleanup(menu.deleteLater)
        self.double_click_row(0)
        self.panel.clear()
        self.assertEqual(self.clipboard.text(), "vorher")

    def test_ctrl_c_copies_the_selected_entry_completely(self):
        self.click_row(self.row_of(ERR2))
        self.table.setFocus()
        QTest.keyClick(self.table, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.clipboard.text(),
                         f"ERROR TYPE_MISSING\nQuelle: project · Stand: r1\nPfad: {ERR2.path}\nMeldung: {ERR2.message}")

    def test_ctrl_c_without_selection_changes_nothing(self):
        QTest.keyClick(self.table, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.clipboard.text(), "vorher")

    def test_menu_copies_code_and_path_of_its_row(self):
        row = self.row_of(ERR2)
        for text, expected in (("Fehlercode kopieren", ERR2.code), ("Pfad kopieren", ERR2.path)):
            menu = self.panel.build_context_menu(row)
            self.addCleanup(menu.deleteLater)
            self.menu_action(menu, text).trigger()
            self.assertEqual(self.clipboard.text(), expected)

    def test_empty_path_cannot_clear_the_clipboard(self):
        menu = self.panel.build_context_menu(self.row_of(INFO))
        self.addCleanup(menu.deleteLater)
        action = self.menu_action(menu, "Pfad kopieren")
        self.assertFalse(action.isEnabled())
        action.trigger()
        self.assertEqual(self.clipboard.text(), "vorher")

    def test_root_path_is_copied_as_it_is(self):
        menu = self.panel.build_context_menu(self.row_of(HINT))
        self.addCleanup(menu.deleteLater)
        self.menu_action(menu, "Pfad kopieren").trigger()
        self.assertEqual(self.clipboard.text(), "/")

    def test_copying_all_filtered_contains_exactly_the_visible_rows(self):
        self.panel.set_filter("duplicate")
        menu = self.panel.build_context_menu(None)
        self.addCleanup(menu.deleteLater)
        self.menu_action(menu, "Alle gefilterten Einträge kopieren (2)").trigger()
        rows = list(csv.reader(io.StringIO(self.clipboard.text()), dialect="excel-tab"))
        self.assertEqual(rows[0], list(COLUMN_TITLES))
        self.assertEqual(rows[1:], [[s, ERR.code, source, ERR.path, ERR.message] for s, source in (("ERROR", "build"), ("ERROR", "project"))])
        self.assertNotIn(WARN.message, self.clipboard.text())
        self.assertNotIn(ERR2.message, self.clipboard.text())

    def test_tabular_copy_keeps_line_breaks_readable(self):
        tricky = Diagnostic("T", "/a\tb", "eins\nzwei \"drei\"")
        self.panel.clear()
        self.panel.set_diagnostics([tricky])
        menu = self.panel.build_context_menu(None)
        self.addCleanup(menu.deleteLater)
        self.menu_action(menu, "Alle gefilterten").trigger()
        rows = list(csv.reader(io.StringIO(self.clipboard.text()), dialect="excel-tab"))
        self.assertEqual(rows[1], ["ERROR", "T", "project", "/a\tb", "eins\nzwei \"drei\""])

    def test_json_copy_holds_only_diagnostic_fields_source_and_revision(self):
        self.panel.set_filter("payload")
        menu = self.panel.build_context_menu(None)
        self.addCleanup(menu.deleteLater)
        self.menu_action(menu, "Gefilterte Einträge als JSON").trigger()
        self.assertEqual(json.loads(self.clipboard.text()), [{"source": "project", "revision": "r1", **WARN.as_dict()}])

    def test_copy_actions_are_disabled_without_data(self):
        self.panel.clear()
        menu = self.panel.build_context_menu(None)
        self.addCleanup(menu.deleteLater)
        for action in menu.actions():
            if not action.isSeparator():
                self.assertFalse(action.isEnabled(), action.text())
        self.assertEqual(self.clipboard.text(), "vorher")

    def choose_in_open_menu(self, text):
        """Runs inside the real QMenu.exec loop; the second timer ends the loop if the menu did not open as expected."""
        def choose():
            popup = QApplication.activePopupWidget()
            if popup is not None:
                self.opened.append([action.text() for action in popup.actions()])
                self.menu_action(popup, text).trigger()
                popup.close()

        def give_up():
            popup = QApplication.activePopupWidget()
            if popup is not None:
                popup.close()

        self.opened = []
        QTimer.singleShot(0, choose)
        QTimer.singleShot(5000, give_up)

    def test_right_click_opens_the_menu_of_the_clicked_row(self):
        point = self.cell_point(self.row_of(WARN))
        self.choose_in_open_menu("Fehlercode kopieren")
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, self.table.viewport().mapToGlobal(point))
        self.table.contextMenuEvent(event)
        self.assertEqual(len(self.opened), 1)
        self.assertEqual(self.clipboard.text(), WARN.code)

    def test_right_click_outside_the_rows_offers_no_entry_action(self):
        point = QPoint(10, self.table.viewport().height() - 2)
        self.assertFalse(self.table.indexAt(point).isValid())
        self.choose_in_open_menu("Alle gefilterten")
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, self.table.viewport().mapToGlobal(point))
        self.table.contextMenuEvent(event)
        self.assertEqual(len(self.opened), 1)
        self.assertTrue(self.clipboard.text().startswith("Schwere\tCode"))

    def test_keyboard_menu_uses_the_current_row(self):
        self.click_row(self.row_of(WARN))
        self.choose_in_open_menu("Pfad kopieren")
        event = QContextMenuEvent(QContextMenuEvent.Reason.Keyboard, QPoint(0, 0), QPoint(0, 0))
        self.table.contextMenuEvent(event)
        self.assertEqual(len(self.opened), 1)
        self.assertEqual(self.clipboard.text(), WARN.path)


# 9. ------------------------------------------------------------------ load


class LoadTests(PanelCase):
    def timed(self, action):
        started = time.perf_counter()
        action()
        _app.processEvents()
        return time.perf_counter() - started

    def test_thousand_and_more_messages_stay_responsive(self):
        items = lab_module().stress_diagnostics(5000)
        self.show()
        self.assertLess(self.timed(lambda: self.panel.set_diagnostics(items)), 3.0)
        self.assertEqual(self.model.rowCount(), 5000)
        self.assertLess(self.timed(lambda: self.panel.set_filter("bereich 7")), 1.0)
        self.assertGreater(self.model.rowCount(), 0)
        self.assertLess(self.timed(lambda: self.panel.set_filter("")), 1.0)
        self.assertLess(self.timed(lambda: self.panel.set_severity_filter(SEVERITY_WARNING)), 1.0)
        self.assertLess(self.timed(lambda: self.table.sortByColumn(COL_MESSAGE, Qt.SortOrder.DescendingOrder)), 1.0)
        self.assertLess(self.timed(lambda: self.panel.set_source_diagnostics("host", [HINT])), 1.0)

    def test_view_creates_no_widget_per_row(self):
        items = lab_module().stress_diagnostics(1500)
        self.panel.set_diagnostics(items)
        self.show()
        self.assertLess(len(self.panel.findChildren(QWidget)), 100)
        self.assertIsNone(self.table.indexWidget(self.model.index(0, 0)))
        self.assertEqual(self.table.verticalHeader().sectionResizeMode(0), QHeaderView.ResizeMode.Fixed)

    def test_identity_of_each_row_survives_load(self):
        items = lab_module().stress_diagnostics(1200)
        self.panel.set_diagnostics(items)
        self.assertEqual({id(d) for d in self.panel.diagnostics(DEFAULT_SOURCE)}, {id(d) for d in items})
        self.assertEqual(sum(self.panel.counts().values()), 1200)

    def test_very_long_digit_runs_do_not_break_sorting(self):
        diagnostic = Diagnostic("A", "/" + "9" * 6000, "m")
        self.panel.set_diagnostics([diagnostic, ERR])
        self.assertEqual(len(self.visible()), 2)


# 10. ----------------------------------------------------------------- layout, theme, accessibility


class LayoutAndThemeTests(PanelCase):
    def test_columns_are_exactly_the_agreed_ones(self):
        self.assertEqual([self.model.headerData(i, Qt.Orientation.Horizontal) for i in range(5)],
                         ["Schwere", "Code", "Quelle", "Pfad", "Meldung"])
        self.fill()
        row = self.row_of(WARN)
        self.assertEqual([self.model.index(row, c).data() for c in range(5)], ["WARNING", WARN.code, "project", WARN.path, WARN.message])

    def test_narrow_widths_keep_all_controls_inside_the_panel(self):
        self.fill()
        self.show()
        for width, height in ((1400, 240), (900, 480), (560, 560), (380, 560), (300, 420)):
            self.panel.resize(width, height)
            _app.processEvents()
            self.assertEqual(self.panel.width(), width)
            controls = [self.panel.search_field, self.panel.summary_label, self.table, *self.panel.severity_buttons.values()]
            for control in controls:
                self.assertTrue(control.isVisible(), f"{width}: {control.objectName()}")
                right = control.mapTo(self.panel, QPoint(control.width(), control.height()))
                self.assertLessEqual(right.x(), width, f"{width}: {control.objectName()}")
                self.assertLessEqual(right.y(), height, f"{width}: {control.objectName()}")
            for column in range(5):
                self.assertGreater(self.table.columnWidth(column), 20, f"{width}: column {column}")

    def test_detail_moves_beside_the_table_when_wide(self):
        self.fill()
        self.show()
        self.panel.resize(1300, 300)
        _app.processEvents()
        self.assertEqual(self.panel.body_splitter.orientation(), Qt.Orientation.Horizontal)
        self.panel.resize(700, 500)
        _app.processEvents()
        self.assertEqual(self.panel.body_splitter.orientation(), Qt.Orientation.Vertical)

    def test_common_codes_are_not_cut_at_normal_width(self):
        self.panel.set_diagnostics([Diagnostic("PLACEMENT_COMPONENT", "/views/0/placements/2/component", "m", "WARNING")])
        self.show()
        self.panel.resize(1240, 420)
        _app.processEvents()
        metrics = self.table.fontMetrics()
        self.assertGreaterEqual(self.table.columnWidth(COL_CODE), metrics.horizontalAdvance("PLACEMENT_COMPONENT"))
        self.assertGreaterEqual(self.table.columnWidth(COL_SEVERITY), metrics.horizontalAdvance("WARNING"))
        self.assertGreaterEqual(self.table.columnWidth(COL_PATH), metrics.horizontalAdvance("/views/0/placements/2/component"))

    def test_user_column_width_is_kept(self):
        self.fill()
        self.show()
        self.table.horizontalHeader().resizeSection(COL_CODE, 321)
        self.panel.resize(700, 400)
        _app.processEvents()
        self.assertEqual(self.table.columnWidth(COL_CODE), 321)

    def test_compact_buttons_keep_the_full_text_for_assistive_technology(self):
        self.panel.set_diagnostics([ERR])
        self.show()
        self.panel.resize(380, 420)
        _app.processEvents()
        button = self.panel.severity_buttons[SEVERITY_WARNING]
        self.assertEqual(button.accessibleName(), "0 Warnungen")
        self.assertIn("0 Warnungen", button.toolTip())
        self.panel.resize(1000, 420)
        _app.processEvents()
        self.assertGreater(button.sizeHint().width(), button.fontMetrics().horizontalAdvance("0 Warnungen"))

    def test_marks_follow_the_palette_with_enough_contrast(self):
        for background, text in (("#2b3037", "#e8ebef"), ("#ffffff", "#1c1f24")):
            palette = QPalette()
            palette.setColor(QPalette.ColorRole.Base, QColor(background))
            palette.setColor(QPalette.ColorRole.Text, QColor(text))
            for category in (SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_OTHER):
                self.assertGreaterEqual(contrast(severity_color(category, palette), QColor(background)), 3.0, (background, category))

    def test_palette_change_keeps_data_and_selection(self):
        self.fill()
        self.show()
        self.click_row(self.row_of(WARN))
        dark = QPalette()
        dark.setColor(QPalette.ColorRole.Base, QColor("#111111"))
        dark.setColor(QPalette.ColorRole.Text, QColor("#eeeeee"))
        self.panel.setPalette(dark)
        _app.processEvents()
        self.assertIs(self.panel.selected_diagnostic(), WARN)
        self.assertIn(WARN.message, self.panel.detail_text())
        self.assertFalse(self.model.index(self.row_of(WARN), COL_SEVERITY).data(Qt.ItemDataRole.DecorationRole).isNull())

    def test_severity_is_shown_as_text_and_symbol(self):
        self.panel.set_diagnostics([ERR, WARN, HINT])
        for position, text in enumerate(("ERROR", "WARNING", "HINT")):
            index = self.model.index(position, COL_SEVERITY)
            self.assertEqual(index.data(), text)
            self.assertFalse(index.data(Qt.ItemDataRole.DecorationRole).isNull())

    def test_accessible_names_and_keyboard_reach(self):
        self.assertEqual(self.table.accessibleName(), "Problemliste")
        self.assertTrue(self.panel.search_field.accessibleName())
        self.assertTrue(self.panel.detail_view.accessibleName())
        for button in self.panel.severity_buttons.values():
            self.assertEqual(button.focusPolicy(), Qt.FocusPolicy.StrongFocus)
        self.panel.set_diagnostics([ERR])
        self.assertEqual(self.model.index(0, COL_CODE).data(Qt.ItemDataRole.AccessibleTextRole), ERR.code)

    def test_widget_has_no_fixed_size_and_a_small_minimum(self):
        hint = self.panel.minimumSizeHint()
        self.assertLessEqual(hint.width(), 320)
        self.assertLessEqual(hint.height(), 240)
        self.assertGreater(self.panel.sizeHint().width(), hint.width())

    def test_only_documented_signals_are_added(self):
        own = ProblemsPanelWidget.__dict__
        self.assertEqual({name for name, value in own.items() if isinstance(value, Signal)}, {"diagnosticActivated", "diagnosticSelected"})


# 11. ----------------------------------------------------------------- lab


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class LabTests(unittest.TestCase):
    def setUp(self):
        self.lab = lab_module()

    def test_lab_does_not_import_the_studio_window(self):
        source = LAB.read_text(encoding="utf-8")
        self.assertNotIn("studio.app", source)
        self.assertNotIn("StudioWindow", source)
        tree = ast.parse(source)
        imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertIn("studio.problems_panel", imported)

    def test_lab_uses_the_real_widget_and_its_scenarios_run(self):
        window = self.lab.ProblemsPanelLabWindow()
        self.addCleanup(window.deleteLater)
        self.assertIsInstance(window.panel, ProblemsPanelWidget)
        panel = window.panel
        for index in range(len(window.SCENARIOS)):
            window.load_scenario(index)
        window.load_scenario(1)
        self.assertEqual(panel.counts(), {"ERROR": 0, "WARNING": 3, "OTHER": 0})
        window.load_scenario(2)
        self.assertEqual(panel.empty_state(), "none")
        window.load_scenario(3)
        self.assertEqual(panel.sources(), [])
        window.load_scenario(4)
        self.assertEqual(len(panel.visible_entries()), 1200)
        window.load_scenario(7)
        self.assertEqual(panel.empty_state(), "no_match")

    def test_lab_exchanges_sources_and_shows_revision(self):
        window = self.lab.ProblemsPanelLabWindow()
        self.addCleanup(window.deleteLater)
        panel = window.panel
        project = panel.diagnostics("project")
        window.source_combo.setCurrentText("build")
        window.snapshot_combo.setCurrentIndex(2)
        window.revision_edit.setText("opak-1")
        window.replace_button.click()
        self.assertEqual(panel.diagnostics("build"), [])
        self.assertEqual(panel.diagnostics("project"), project)
        self.assertIn("build 0 (Stand: opak-1)", panel.summary_label.full_text())
        window.remove_button.click()
        self.assertNotIn("build", panel.sources())
        window.clear_button.click()
        self.assertEqual(panel.sources(), [])

    def test_lab_logs_selection_and_navigation_wish(self):
        window = self.lab.ProblemsPanelLabWindow()
        self.addCleanup(window.close)
        self.addCleanup(window.deleteLater)
        window.show()
        _app.processEvents()
        table = window.panel.problems_table
        index = table.model().index(0, 1)
        point = table.visualRect(index).center()
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        QTest.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        kinds = [event["kind"] for event in window.events]
        self.assertIn("diagnosticSelected", kinds)
        self.assertEqual(kinds.count("diagnosticActivated"), 1)
        self.assertIn("diagnosticActivated", window.log_view.toPlainText())

    def test_real_validator_diagnostics_are_shown_unchanged(self):
        real = self.lab.validate_in_memory()
        self.assertTrue(real)
        for item in real:
            self.assertIsInstance(item, Diagnostic)
        codes = {item.code for item in real}
        self.assertTrue({"FIELD_UNKNOWN", "SCOPE_INVALID", "PLACEMENT_COMPONENT"} <= codes, codes)
        panel = ProblemsPanelWidget()
        self.addCleanup(panel.deleteLater)
        panel.set_diagnostics(real)
        self.assertEqual({id(d) for d in panel.diagnostics(DEFAULT_SOURCE)}, {id(d) for d in real})
        self.assertEqual(sum(panel.counts().values()), len(real))

    def test_native_error_is_one_wrapper_without_position(self):
        items = self.lab.native_error_diagnostics()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].code, "NATIVE_PROJECT")
        self.assertEqual(items[0].path, "/")
        self.assertEqual(items[0].severity, "ERROR")
        window = self.lab.ProblemsPanelLabWindow()
        self.addCleanup(window.deleteLater)
        window.load_scenario(9)
        self.assertIn("ohne präzise Objektposition", window.banner.text())

    def test_adapter_issues_keep_their_values_in_a_separate_source(self):
        items = self.lab.adapter_diagnostics()
        self.assertEqual(items[-1].code, "BUILD_FAILED")
        self.assertEqual(items[-1].path, "/")
        self.assertTrue(all(item.path.startswith("/") for item in items))

    def test_lab_changes_no_project_file(self):
        before = {path: path.read_bytes() for path in (self.lab.DRAFT_EXAMPLE, self.lab.NATIVE_EXAMPLE)}
        window = self.lab.ProblemsPanelLabWindow()
        self.addCleanup(window.deleteLater)
        for index in range(len(window.SCENARIOS)):
            window.load_scenario(index)
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_smoke_mode_exits_zero_without_any_service(self):
        environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run([sys.executable, str(LAB), "--smoke"], capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=120, env=environment, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Smoke: 9/9", result.stdout)
        self.assertNotIn("FAIL", result.stdout)


if __name__ == "__main__":
    unittest.main()
