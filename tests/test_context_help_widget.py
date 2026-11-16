"""AP-WIDGET-005 public API, JSON, state transitions and real Qt input events."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea, QTextBrowser, QTextEdit, QToolButton

from studio.context_help import (
    ContextHelpWidget, HelpContext, HelpCoordinator, HelpDisplayState, HelpEntry, HelpRegistry, load_help_entries,
)
from studio.context_help.registry import MAX_HELP_JSON_BYTES

SOURCES = ROOT / "src/studio/context_help"
DEFAULT_TOPICS = SOURCES / "resources/default_topics.de.json"
BASE = HelpEntry("keypad", "Tastenvorschau", "Seite mit Tasten")
SLOT = HelpEntry("keypad.slot", "Taste", "Vorschau einer Taste", technical_details="Interne Kennung: physical_index",
                 related_topics=("keypad", "later.topic", "keypad.slot", "keypad"))
OTHER = HelpEntry("catalog", "Katalog", "Aktionen anzeigen")
LITERAL = '<script>alert("Grüße 東京")</script>\n<img src="file:///secret"> & **`Text`** https://example.invalid'
APP = None


def setUpModule():
    global APP
    APP = QApplication.instance() or QApplication([])


class EntryTests(unittest.TestCase):
    def test_types_are_frozen_and_defaults_are_immutable(self):
        for value, field in ((BASE, "title"), (HelpContext("keypad"), "facts"), (HelpDisplayState(), "pinned")):
            with self.subTest(value=value), self.assertRaises(FrozenInstanceError):
                setattr(value, field, None)
        self.assertEqual(BASE.related_topics, ())
        self.assertEqual(HelpContext("keypad").facts, ())

    def test_canonical_ids_and_required_text(self):
        self.assertEqual(HelpEntry("keypad_1.slot2", "Titel", "Hilfe").topic_id, "keypad_1.slot2")
        for bad in ("", "Keypad", " a", "a.", ".a", "a..b", "a-b", "a/b", "ä", "a\n"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                HelpEntry(bad, "Titel", "Hilfe")
        for fields in ({"title": ""}, {"summary": "\n "}, {"related_topics": ("https://example.invalid",)}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                replace(BASE, **fields)

    def test_entry_types_are_validated(self):
        for fields in ({"topic_id": 1}, {"title": False}, {"summary": None}, {"description": []},
                       {"example": {}}, {"technical_details": b"bytes"}, {"related_topics": ["a"]},
                       {"related_topics": (1,)}):
            with self.subTest(fields=fields), self.assertRaises(TypeError):
                replace(BASE, **fields)

    def test_context_facts_are_immutable_pairs_of_text(self):
        facts = (("Taste", "5"), ("Aktion", LITERAL), ("Taste", "6"))
        self.assertEqual(HelpContext("keypad.slot", facts).facts, facts)
        for invalid in ([("Taste", "5")], (["Taste", "5"],), (("Taste",),), (("Taste", 5),), ("ab",)):
            with self.subTest(invalid=invalid), self.assertRaises(TypeError):
                HelpContext("keypad.slot", invalid)
        with self.assertRaises(ValueError):
            HelpContext("")


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = HelpRegistry()
        self.registry.register(BASE, source="keypad")

    def test_exact_and_hierarchical_lookup_are_read_only(self):
        self.registry.register(SLOT, source="keypad")
        before = self.registry.topics()
        self.assertIs(self.registry.get(SLOT.topic_id), SLOT)
        self.assertIsNone(self.registry.get("keypad.slot.empty"))
        self.assertEqual(self.registry.resolve("keypad.slot"), (SLOT.topic_id, SLOT))
        self.assertEqual(self.registry.resolve("keypad.slot.empty"), (SLOT.topic_id, SLOT))
        self.assertEqual(self.registry.resolve("keypad.page.next"), (BASE.topic_id, BASE))
        self.assertIsNone(self.registry.resolve("other.keypad"))
        self.assertEqual(self.registry.topics(), before)

    def test_batch_collisions_and_invalid_values_leave_earlier_sources_intact(self):
        for batch, exception in (((OTHER, BASE), ValueError), ((OTHER, OTHER), ValueError),
                                 ((OTHER, object()), TypeError)):
            with self.subTest(batch=batch), self.assertRaises(exception):
                self.registry.register_many(batch, source="catalog")
            self.assertEqual(self.registry.topics(), ("keypad",))
        with self.assertRaises(ValueError):
            self.registry.register(BASE, source="keypad")

    def test_source_removal_isolated_and_id_reusable(self):
        self.registry.register_many((SLOT,), source="keypad")
        self.registry.register_many((OTHER, HelpEntry("z", "Z", "Z")), source="catalog")
        self.assertEqual(self.registry.topics(), ("catalog", "keypad", "keypad.slot", "z"))
        self.registry.unregister_source("missing")
        self.registry.unregister_source("keypad")
        self.registry.unregister_source("keypad")
        self.assertEqual(self.registry.topics(), ("catalog", "z"))
        self.registry.register(BASE, source="other")
        self.assertIs(self.registry.get("keypad"), BASE)

    def test_sources_and_lookup_arguments_reject_bad_values(self):
        for source in ("", " ", " name", "name "):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.registry.register(OTHER, source=source)
            with self.assertRaises(ValueError):
                self.registry.unregister_source(source)
        with self.assertRaises(TypeError):
            self.registry.register(OTHER, source=None)
        with self.assertRaises(TypeError):
            self.registry.unregister_source(2)
        with self.assertRaises(ValueError):
            self.registry.resolve("keypad.")
        with self.assertRaises(TypeError):
            self.registry.get(None)

    def test_concurrent_collision_commits_only_one_complete_batch(self):
        def register(index):
            source = f"module_{index}"
            try:
                self.registry.register_many((SLOT, HelpEntry(source, source, "Hilfe")), source=source)
            except ValueError:
                return None
            return source

        with ThreadPoolExecutor(4) as pool:
            winners = [source for source in pool.map(register, range(16)) if source is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(self.registry.topics(), ("keypad", "keypad.slot", winners[0]))
        self.registry.unregister_source(winners[0])
        self.assertEqual(self.registry.topics(), ("keypad",))


class JsonTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "help.json"
        self.valid = {"topic_id": "test.data", "title": "Grüße", "summary": LITERAL}

    def load(self, payload):
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        return load_help_entries(self.path)

    def test_valid_file_and_builtin_topics(self):
        entry, = self.load([{**self.valid, "related_topics": ["later.data"]}])
        self.assertEqual(entry, HelpEntry("test.data", "Grüße", LITERAL, related_topics=("later.data",)))
        self.assertEqual(self.load([]), ())
        builtins = {entry.topic_id for entry in load_help_entries(DEFAULT_TOPICS)}
        self.assertTrue({
            "studio.help", "keypad", "keypad.overview", "keypad.slot.empty", "keypad.slot.occupied",
            "keypad.dragdrop", "keypad.pagination", "catalog", "catalog.search", "catalog.parameter",
            "problems", "problems.diagnostic", "problems.filters", "symbol.ict", "action.definition",
        } <= builtins)

    def test_bad_shapes_unknown_fields_types_and_ids(self):
        for invalid in ({}, None, "file.json", [False], [{}], [{**self.valid, "include": "../project.json"}],
                        [{**self.valid, "topic_id": "a/b"}], [{**self.valid, "title": " "}],
                        [{**self.valid, "summary": 42}], [{**self.valid, "related_topics": "keypad"}],
                        [{**self.valid, "related_topics": ["https://example.invalid"]}],
                        [{**self.valid, "related_topics": [None]}], [{**self.valid, "description": "\ud800"}]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.load(invalid)

    def test_duplicate_ids_and_json_fields(self):
        with self.assertRaisesRegex(ValueError, "duplicate help topic"):
            self.load([self.valid, self.valid])
        self.path.write_text('[{"topic_id":"a","title":"T","title":"U","summary":"S"}]', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate JSON field"):
            load_help_entries(self.path)

    def test_byte_limit_encoding_syntax_and_deep_json(self):
        for data in (b" " * (MAX_HELP_JSON_BYTES + 1), b'["\xff"]', b"[", b"[" * 1500 + b"]" * 1500):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                self.path.write_bytes(data)
                load_help_entries(self.path)

    def test_field_limits(self):
        for fields in ({"topic_id": "x" * 161}, {"title": "x" * 161}, {"example": "x" * 16_385},
                       {"related_topics": ["keypad"] * 33}, {"related_topics": ["x" * 161]}):
            with self.subTest(field=tuple(fields)), self.assertRaises(ValueError):
                self.load([{**self.valid, **fields}])

    def test_no_file_resolution_or_code_execution_from_json_values(self):
        marker = self.path.with_name("executed.txt")
        code = f"__import__('pathlib').Path({str(marker)!r}).touch()"
        entry, = self.load([{**self.valid, "description": code, "example": str(marker)}])
        self.assertEqual(entry.description, code)
        self.assertEqual(entry.example, str(marker))
        self.assertFalse(marker.exists())
        with self.assertRaises(FileNotFoundError):
            load_help_entries(marker)


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.registry = HelpRegistry()
        self.registry.register_many((BASE, SLOT), source="keypad")
        self.registry.register(OTHER, source="catalog")
        self.coordinator = HelpCoordinator(self.registry)
        self.spy = QSignalSpy(self.coordinator.helpChanged)
        self.current = self.coordinator.current

    def test_initial_state_unknown_and_clear(self):
        self.assertEqual(self.current(), HelpDisplayState())
        self.coordinator.set_context(HelpContext("unknown.deep", (("Name", "Intern"),)))
        self.assertEqual(self.current(), HelpDisplayState(requested_topic_id="unknown.deep"))
        self.coordinator.set_context(None)
        self.assertEqual(self.current(), HelpDisplayState())
        self.assertEqual(self.spy.count(), 2)

    def test_pin_freezes_automatic_changes_and_explicit_request_bypasses_it(self):
        self.coordinator.set_context(HelpContext("keypad", (("Taste", "5"),)))
        self.coordinator.set_pinned(True)
        pinned = self.current()
        self.coordinator.set_context(HelpContext("keypad", (("Taste", "8"),)))
        self.coordinator.set_context(None)
        self.assertIs(self.current(), pinned)
        self.assertEqual(self.spy.count(), 2)
        self.coordinator.request_help(HelpContext("catalog"))
        self.assertTrue(self.current().pinned)
        self.assertIs(self.current().entry, OTHER)
        self.coordinator.set_pinned(False)
        self.assertEqual(self.current().resolved_topic_id, "catalog")
        self.coordinator.set_context(HelpContext("keypad.slot"))
        self.assertIs(self.current().entry, SLOT)
        self.assertEqual(self.spy.count(), 5)

    def test_unknown_explicit_request_can_replace_pinned_content(self):
        self.coordinator.set_context(HelpContext("keypad"))
        self.coordinator.set_pinned(True)
        self.coordinator.request_help(HelpContext("missing", (("Name", "Intern"),)))
        self.assertEqual(self.current(), HelpDisplayState(requested_topic_id="missing", pinned=True))

    def test_refresh_tracks_fallback_exact_match_and_removal_even_while_pinned(self):
        self.coordinator.request_help(HelpContext("keypad.slot.empty", (("Taste", "3"),)))
        self.coordinator.set_pinned(True)
        self.assertTrue(self.current().is_fallback)
        self.assertEqual(self.current().resolved_topic_id, SLOT.topic_id)
        specific = HelpEntry("keypad.slot.empty", "Freie Taste", "Freier Platz")
        self.registry.register(specific, source="extension")
        self.assertIs(self.current().entry, SLOT)
        self.coordinator.refresh()
        self.assertIs(self.current().entry, specific)
        self.assertFalse(self.current().is_fallback)
        self.assertTrue(self.current().pinned)
        self.assertEqual(self.current().facts, (("Taste", "3"),))
        self.registry.unregister_source("extension")
        self.coordinator.refresh()
        self.assertIs(self.current().entry, SLOT)
        self.registry.unregister_source("keypad")
        self.coordinator.refresh()
        self.assertIsNone(self.current().entry)
        self.assertEqual(self.current().facts, ())
        self.assertIs(self.registry.get("catalog"), OTHER)

    def test_related_requires_exact_target_and_is_recomputed_on_refresh(self):
        self.coordinator.set_context(HelpContext("keypad.slot"))
        self.assertEqual(self.current().related_topics, (("keypad", BASE.title),))
        self.registry.register(HelpEntry("later", "Oberthema", "Text"), source="other")
        self.coordinator.refresh()
        self.assertEqual(self.spy.count(), 1)
        topic = HelpEntry("later.topic", "Späteres Thema", "Text")
        self.registry.register(topic, source="extension")
        self.coordinator.refresh()
        self.assertEqual(self.current().related_topics, (("keypad", BASE.title), ("later.topic", topic.title)))
        self.registry.unregister_source("extension")
        self.coordinator.refresh()
        self.assertEqual(self.current().related_topics, (("keypad", BASE.title),))
        self.assertEqual(self.spy.count(), 3)

    def test_same_updates_emit_once_and_fact_changes_do_not_store_topics(self):
        before = self.registry.topics()
        context = HelpContext("keypad.slot", (("Taste", "5"),))
        self.coordinator.set_context(context)
        self.coordinator.set_context(replace(context))
        self.coordinator.request_help(context)
        self.coordinator.set_pinned(False)
        self.coordinator.refresh()
        self.assertEqual(self.spy.count(), 1)
        self.assertEqual(self.spy.at(0)[0], self.current())
        self.coordinator.set_context(replace(context, facts=(("Taste", "8"),)))
        self.assertEqual(self.spy.count(), 2)
        self.assertEqual(self.current().facts, (("Taste", "8"),))
        self.assertIs(self.current().entry, SLOT)
        self.assertEqual(self.registry.topics(), before)

    def test_invalid_arguments_leave_the_state_recoverable(self):
        self.coordinator.set_context(HelpContext("keypad"))
        before = self.current()
        for method, argument in ((self.coordinator.set_context, "keypad"),
                                 (self.coordinator.request_help, None), (self.coordinator.set_pinned, "false")):
            with self.subTest(method=method), self.assertRaises(TypeError):
                method(argument)
        self.coordinator.refresh()
        self.assertIs(self.current(), before)
        self.assertEqual(self.spy.count(), 1)


class WidgetTests(unittest.TestCase):
    def setUp(self):
        self.registry = HelpRegistry()
        self.registry.register_many((BASE, SLOT, OTHER), source="tests")
        self.coordinator = HelpCoordinator(self.registry)
        self.widget = ContextHelpWidget()
        self.addCleanup(self._close)
        self.widget.resize(380, 650)
        self.widget.show()
        APP.processEvents()
        self.pin = self.widget.findChild(QPushButton, "helpPin")
        self.pins = QSignalSpy(self.widget.pinRequested)
        self.links = QSignalSpy(self.widget.relatedTopicRequested)
        self.coordinator.helpChanged.connect(self.widget.set_help)

    def _close(self):
        self.widget.close()
        self.widget.deleteLater()
        APP.processEvents()

    def text(self, name):
        return self.widget.findChild(QTextEdit, name)

    def test_set_help_is_passive_even_when_pin_changes(self):
        self.coordinator.set_context(HelpContext(SLOT.topic_id))
        self.coordinator.set_pinned(True)
        self.assertTrue(self.pin.isChecked())
        self.assertEqual(self.text("helpTitle").toPlainText(), SLOT.title)
        self.widget.set_help(None)
        self.assertFalse(self.pin.isChecked())
        self.assertEqual(self.text("helpTitle").toPlainText(), "Keine passende Hilfe")
        self.assertEqual((self.pins.count(), self.links.count()), (0, 0))
        self.assertTrue(self.coordinator.current().pinned)

    def test_mouse_and_space_emit_only_pin_intent_without_host_update(self):
        QTest.mouseClick(self.pin, Qt.MouseButton.LeftButton)
        self.assertEqual(self.pins.count(), 1)
        self.assertEqual(self.pins.at(0), [True])
        self.assertFalse(self.pin.isChecked())
        self.coordinator.set_pinned(True)
        self.pin.setFocus()
        QTest.keyClick(self.pin, Qt.Key.Key_Space)
        self.assertEqual(self.pins.count(), 2)
        self.assertEqual(self.pins.at(1), [False])
        self.assertTrue(self.pin.isChecked())
        self.assertEqual(self.registry.topics(), ("catalog", "keypad", "keypad.slot"))

    def test_related_mouse_and_keyboard_emit_once_then_host_handles_navigation(self):
        self.coordinator.set_context(HelpContext(SLOT.topic_id))
        button = self.widget.findChild(QPushButton, "helpRelated.keypad")
        APP.processEvents()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.links.count(), 1)
        self.assertEqual(self.links.at(0), ["keypad"])
        self.assertIs(self.coordinator.current().entry, SLOT)
        self.assertIsNone(self.widget.findChild(QPushButton, "helpRelated.later.topic"))
        self.registry.register(HelpEntry("later.topic", "Grüße & Hilfe", "Text"), source="later")
        self.coordinator.refresh()
        APP.processEvents()
        added = self.widget.findChild(QPushButton, "helpRelated.later.topic")
        self.assertTrue(added.isVisible())
        self.assertEqual(added.accessibleName(), "Grüße & Hilfe")
        self.assertIn("&&", added.text())
        self.widget.relatedTopicRequested.connect(lambda topic: self.coordinator.request_help(HelpContext(topic)))
        added.setFocus()
        QTest.keyClick(added, Qt.Key.Key_Space)
        self.assertEqual(self.links.count(), 2)
        self.assertEqual(self.links.at(1), ["later.topic"])
        self.assertEqual(self.coordinator.current().resolved_topic_id, "later.topic")
        self.assertEqual(self.registry.topics(), ("catalog", "keypad", "keypad.slot", "later.topic"))

    def test_related_is_hidden_immediately_when_source_is_removed(self):
        self.registry.register(HelpEntry("later.topic", "Später", "Text"), source="later")
        self.coordinator.set_context(HelpContext(SLOT.topic_id))
        related = self.widget.findChild(QPushButton, "helpRelated.later.topic")
        self.assertTrue(related.isVisible())
        self.registry.unregister_source("later")
        self.coordinator.refresh()
        self.assertTrue(related.isHidden())
        self.assertEqual(self.links.count(), 0)

    def test_optional_details_are_collapsed_and_expand_with_keyboard(self):
        self.coordinator.set_context(HelpContext(SLOT.topic_id))
        toggle = self.widget.findChild(QToolButton, "helpDetailsToggle")
        details = self.text("helpDetails")
        self.assertTrue(toggle.isVisible())
        self.assertFalse(details.isVisible())
        toggle.setFocus()
        QTest.keyClick(toggle, Qt.Key.Key_Space)
        self.assertTrue(details.isVisible())
        self.assertEqual(details.toPlainText(), SLOT.technical_details)
        self.coordinator.set_pinned(True)
        self.assertTrue(details.isVisible())
        self.coordinator.request_help(HelpContext(BASE.topic_id))
        self.assertFalse(toggle.isVisible())
        self.assertFalse(details.isVisible())
        self.assertEqual(self.pins.count(), 0)

    def test_plaintext_long_lines_and_palette_at_300_380_500(self):
        clipboard = APP.clipboard()
        previous = clipboard.text()
        self.addCleanup(clipboard.setText, previous)
        clipboard.setText("vorher")
        long_text = LITERAL + "\n" + "LangeKennung" * 90
        entry = HelpEntry("safe", LITERAL, "Kurz", long_text, LITERAL, LITERAL)
        self.registry.register(entry, source="test")
        self.coordinator.set_context(HelpContext("safe", (("Wert", LITERAL),)))
        scroll = self.widget.findChild(QScrollArea, "helpScroll")
        for width, color in ((300, "#202631"), (380, "#ffffff"), (500, "#202631")):
            with self.subTest(width=width):
                palette = QPalette(self.widget.palette())
                palette.setColor(QPalette.ColorRole.Base, QColor(color))
                palette.setColor(QPalette.ColorRole.Text, QColor("#ffffff" if color != "#ffffff" else "#202631"))
                self.widget.setPalette(palette)
                self.widget.resize(width, 450)
                APP.processEvents()
                self.assertEqual(self.widget.width(), width)
                self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
                self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
                description = self.text("helpDescription")
                self.assertEqual(description.toPlainText(), long_text)
                self.assertEqual(description.palette().color(QPalette.ColorRole.Base), QColor(color))
                self.assertEqual(description.horizontalScrollBar().maximum(), 0)
                self.assertEqual(description.verticalScrollBar().maximum(), 0)
                self.assertGreater(description.height(), description.fontMetrics().lineSpacing() * 12)
                self.assertLessEqual(description.width(), width)
                self.assertFalse(description.acceptRichText())
                self.assertTrue(description.isReadOnly())
                self.assertIn("&lt;script&gt;", description.document().toHtml())
                self.assertNotIn("<img", description.document().toHtml())
                self.assertIn(LITERAL, self.text("helpFacts").toPlainText())
                self.assertTrue(self.pin.isVisible())
        self.assertFalse(self.widget.findChildren(QTextBrowser))
        self.assertEqual(clipboard.text(), "vorher")
        self.assertEqual((self.links.count(), self.pins.count()), (0, 0))

    def test_fallback_indicator_and_neutral_empty_hide_host_facts(self):
        self.coordinator.set_context(HelpContext("keypad.slot.more", (("Taste", "5"),)))
        self.assertIn("keypad.slot.more → keypad.slot", self.text("helpFallback").toPlainText())
        self.assertTrue(self.text("helpFacts").isVisible())
        self.coordinator.set_context(HelpContext("unknown.slot", (("Taste", "5"),)))
        self.assertEqual(self.text("helpTitle").toPlainText(), "Keine passende Hilfe")
        self.assertTrue(self.text("helpFallback").isHidden())
        self.assertTrue(self.text("helpFacts").isHidden())


class BoundaryTests(unittest.TestCase):
    def test_registry_import_and_operation_do_not_import_qt(self):
        result = subprocess.run(
            [sys.executable, "-S", "-c",
             "import sys; sys.path.insert(0, 'src'); from studio.context_help import HelpEntry, HelpRegistry; "
             "r = HelpRegistry(); r.register(HelpEntry('test', 'T', 'S'), source='x'); "
             "assert r.resolve('test.more')[0] == 'test'; assert 'PySide6' not in sys.modules"],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_production_modules_have_no_studio_runtime_sdk_or_widget_dependencies(self):
        allowed = {"math", "re", "dataclasses", "importlib", "json", "collections.abc",
                   "pathlib", "threading", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"}
        for path in SOURCES.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                imports = set()
                for node in ast.walk(ast.parse(source)):
                    if isinstance(node, ast.Import):
                        imports.update(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.level == 0:
                        imports.add(node.module)
                self.assertLessEqual(imports, allowed)
                for forbidden in ("studio.app", "LogiPluginService", "ProfileInfo.json", "openUrl"):
                    self.assertNotIn(forbidden, source)
        self.assertNotIn("registry", (SOURCES / "widget.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
