"""Standalone, scripted and interactive lab for AP-WIDGET-005."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QKeySequence, QPalette, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from studio.context_help import (
    ContextHelpWidget, HelpContext, HelpCoordinator, HelpEntry, HelpRegistry, load_help_entries,
)

DEFAULT_TOPICS = ROOT / "src/studio/context_help/resources/default_topics.de.json"
MODULE_SOURCE = "lab_extension"
LITERAL = '<script>alert("Grüße 東京")</script> & `Code` https://example.invalid'
SCENARIOS = (
    ("Start · Kontexthilfe", HelpContext("studio.help")),
    ("KeypadPreview · Taste 5 auf Seite 2", HelpContext(
        "keypad.slot.occupied", (("Taste", "5"), ("Seite", "2"), ("Aktion", "Mikrofon ein/aus")))),
    ("KeypadPreview · Taste 8 auf Seite 3", HelpContext(
        "keypad.slot.occupied", (("Taste", "8"), ("Seite", "3"), ("Aktion", "Mikrofon ein/aus")))),
    ("KeypadPreview · Freie Taste", HelpContext("keypad.slot.empty", (("Taste", "3"),))),
    ("ActionCatalog · Aktionsdefinition", HelpContext(
        "action.definition", (("Aktion", "Mikrofon ein/aus"),))),
    ("ProblemsPanel · Meldung", HelpContext(
        "problems.diagnostic", (("Code", "BEISPIEL_REFERENZ"), ("Quelle", "Lab")))),
    ("SymbolDesigner · Symbolvorlage", HelpContext("symbol.ict", (("Vorlage", "mikrofon.ict"),))),
    ("Fallback · Unbekannter Tastenkontext", HelpContext("keypad.slot.some_unknown_child")),
    ("Leerzustand · Unbekannter Bereich", HelpContext("unbekannt.bereich", (("Demo", "Nur bei Treffer"),))),
    ("Zusatzquelle · Text und Sonderzeichen", HelpContext("lab.literal", (("Host-Text", LITERAL),))),
)
MODULE_TOPICS = (
    HelpEntry(
        "lab.literal", "Sonderzeichen und lange Texte",
        "Dieses Thema wurde zur Laufzeit vom Beispiel-Host registriert.",
        "Die nächste Zeile enthält verschiedene Zeichen und eine URL als Anzeigetext.\n" + LITERAL,
        "Eine lange Kennung wird auch in einer schmalen Seitenleiste umgebrochen.\n" + "BeispielKennung_" * 15,
        "Der Host liefert Fakten zusammen mit der Hilfe-ID. Die Inhalte der Registry bleiben dabei gleich.",
        ("studio.help", "lab.source"),
    ),
    HelpEntry("lab.source", "Registrierung zur Laufzeit",
              "Der Beispiel-Host kann diese Hilfequelle hinzufügen und gezielt entfernen.",
              related_topics=("lab.literal",)),
)


def lab_palette(dark: bool) -> QPalette:
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: ("#edf1f6", "#1e242e"),
        QPalette.ColorRole.Base: ("#ffffff", "#252d39"),
        QPalette.ColorRole.AlternateBase: ("#e3ebf7", "#303e52"),
        QPalette.ColorRole.WindowText: ("#17253a", "#eaf0fa"),
        QPalette.ColorRole.Text: ("#17253a", "#eaf0fa"),
        QPalette.ColorRole.Button: ("#f6f8fc", "#344156"),
        QPalette.ColorRole.ButtonText: ("#17253a", "#eaf0fa"),
        QPalette.ColorRole.Highlight: ("#2760ae", "#83b6ff"),
        QPalette.ColorRole.HighlightedText: ("#ffffff", "#10213b"),
        QPalette.ColorRole.ToolTipBase: ("#ffffff", "#344156"),
        QPalette.ColorRole.ToolTipText: ("#17253a", "#eaf0fa"),
        QPalette.ColorRole.PlaceholderText: ("#495972", "#aabbd2"),
    }
    for role, pair in colors.items():
        palette.setColor(role, QColor(pair[dark]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText,
                     QColor("#9cabc0" if dark else "#62728a"))
    return palette


class ContextHelpLab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Plugin Studio · Kontexthilfe-Lab")
        self.resize(1000, 790)
        self.registry = HelpRegistry()
        self.registry.register_many(load_help_entries(DEFAULT_TOPICS), source="studio_builtin")
        self.coordinator = HelpCoordinator(self.registry, self)
        self.help_widget = ContextHelpWidget()
        self.help_widget.setFixedWidth(380)
        self.events: list[dict] = []
        self._host_context = SCENARIOS[0][1]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)
        title = QLabel("Kontexthilfe im Plugin Studio")
        font = title.font()
        font.setPointSize(19)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        layout.addWidget(QLabel("Widget-Lab  ·  Simulierter Host  ·  AP-WIDGET-005"))
        body = QHBoxLayout()
        body.setSpacing(18)
        layout.addLayout(body, 1)

        host = QVBoxLayout()
        host.setSpacing(8)
        body.addLayout(host, 1)
        body.addWidget(self.help_widget)
        self.scenarios = QListWidget()
        self.scenarios.setAccessibleName("Kontext auswählen")
        self.scenarios.addItems([title for title, _ in SCENARIOS])
        self.scenarios.currentRowChanged.connect(self._select)
        self.scenarios.itemClicked.connect(lambda item: self._select(self.scenarios.row(item)))
        host.addWidget(QLabel("Beispielkontext auswählen"))
        host.addWidget(self.scenarios, 1)

        form = QFormLayout()
        self.fields = {}
        for label, topic, text in (
            ("Katalogsuche", "catalog.search", "Mikrofon"),
            ("Aktionsparameter", "catalog.parameter", "USB-Audio"),
        ):
            field = QLineEdit(text)
            field.setAccessibleName(label)
            self.fields[field] = (topic, label)
            field.installEventFilter(self)
            field.textEdited.connect(lambda _text, field=field: self._field_context(field))
            form.addRow(label, field)
        host.addLayout(form)

        self.help_button = QPushButton("Hilfe öffnen (F1)")
        self.help_button.clicked.connect(self._explicit)
        self.f1 = QShortcut(QKeySequence(Qt.Key.Key_F1), self)
        self.f1.setContext(Qt.ShortcutContext.WindowShortcut)
        self.f1.activated.connect(self._explicit)
        self.source_button = QPushButton("Zusatzquelle registrieren")
        self.source_button.clicked.connect(self._toggle_source)
        actions = QHBoxLayout()
        actions.addWidget(self.help_button)
        actions.addWidget(self.source_button)
        host.addLayout(actions)

        appearance = QFormLayout()
        self.theme = QComboBox()
        self.theme.addItems(("Hell", "Dunkel"))
        self.theme.setAccessibleName("Palette")
        self.theme.currentIndexChanged.connect(self._theme_changed)
        self.sidebar_width = QComboBox()
        self.sidebar_width.addItems(("300", "380", "500"))
        self.sidebar_width.setCurrentText("380")
        self.sidebar_width.setAccessibleName("Seitenleistenbreite in Pixeln")
        self.sidebar_width.currentTextChanged.connect(self._width_changed)
        appearance.addRow("Palette", self.theme)
        appearance.addRow("Seitenleiste (px)", self.sidebar_width)
        host.addLayout(appearance)

        self.capture_button = QPushButton("Lab und Hilfe als PNG speichern…")
        self.capture_button.clicked.connect(self._save_dialog)
        host.addWidget(self.capture_button)
        layout.addWidget(QLabel("Ereignisprotokoll"))
        self.log = QPlainTextEdit()
        self.log.setAccessibleName("Ereignisprotokoll")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(250)
        self.log.setFixedHeight(95)
        layout.addWidget(self.log)

        self.coordinator.helpChanged.connect(self.help_widget.set_help)
        self.coordinator.helpChanged.connect(self._display_changed)
        self.help_widget.pinRequested.connect(self._pin_requested)
        self.help_widget.relatedTopicRequested.connect(self._related_requested)
        self.setPalette(lab_palette(False))
        self.scenarios.setCurrentRow(0)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.FocusIn and watched in self.fields:
            self._field_context(watched)
        return super().eventFilter(watched, event)

    def _log(self, event: str, **data) -> None:
        self.events.append({"sequence": len(self.events) + 1, "event": event, **data})
        self.log.appendPlainText(f"{event}  ·  " + "  /  ".join(
            f"{key}={value}" for key, value in data.items()
        ))

    def _display_changed(self, state) -> None:
        self._log("Anzeige", angefragt=state.requested_topic_id, aufgelöst=state.resolved_topic_id,
                  angeheftet=state.pinned, fallback=state.is_fallback, fakten=state.facts)

    def _select(self, index: int) -> None:
        if index >= 0:
            self._automatic(SCENARIOS[index][1])

    def _automatic(self, context: HelpContext) -> None:
        if context != self._host_context:
            self._log("Auswahl", topic=context.topic_id)
        self._host_context = context
        self.coordinator.set_context(context)

    def _field_context(self, field: QLineEdit) -> None:
        topic, label = self.fields[field]
        self._automatic(HelpContext(topic, ((label, field.text()),)))

    def _explicit(self) -> None:
        self._log("Explizite Hilfe", topic=self._host_context.topic_id)
        self.coordinator.request_help(self._host_context)

    def _pin_requested(self, pinned: bool) -> None:
        self._log("Pin", aktiv=pinned)
        self.coordinator.set_pinned(pinned)

    def _related_requested(self, topic_id: str) -> None:
        self._log("Verwandtes Thema", topic=topic_id)
        self.coordinator.request_help(HelpContext(topic_id))

    def _toggle_source(self) -> None:
        if self.registry.get("lab.literal") is None:
            self.registry.register_many(MODULE_TOPICS, source=MODULE_SOURCE)
            self.source_button.setText("Zusatzquelle entfernen")
            self._log("Registriert", source=MODULE_SOURCE)
        else:
            self.registry.unregister_source(MODULE_SOURCE)
            self.source_button.setText("Zusatzquelle registrieren")
            self._log("Entfernt", source=MODULE_SOURCE)
        self.coordinator.refresh()

    def _theme_changed(self, index: int) -> None:
        self.setPalette(lab_palette(bool(index)))
        self._log("Palette", name=self.theme.currentText())

    def _width_changed(self, width: str) -> None:
        self.help_widget.setFixedWidth(int(width))
        self._log("Seitenleiste", pixel=int(width))

    def _save_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Ordner für Lab-Screenshots wählen")
        if folder:
            try:
                self.capture(Path(folder), "context_help")
            except OSError as exc:
                self._log("Screenshot fehlgeschlagen", meldung=str(exc))

    def capture(self, output: Path, stem: str) -> dict:
        QApplication.processEvents()
        files = {}
        for label, widget in (("lab", self), ("widget", self.help_widget)):
            filename = f"{stem}_{label}.png"
            pixmap = widget.grab()
            if pixmap.isNull() or not pixmap.save(str(output / filename)):
                raise OSError(f"PNG konnte nicht gespeichert werden: {filename}")
            files[label] = {"file": filename, "pixel_size": [pixmap.width(), pixmap.height()],
                            "dpr": pixmap.devicePixelRatio()}
        return {"scenario": stem, "sidebar_px": self.help_widget.width(),
                "palette": self.theme.currentText(), "images": files}


def walkthrough(lab: ContextHelpLab, output: Path | None) -> dict:
    app = QApplication.instance()
    checks = []
    captures = []
    report = {"qt_platform": app.platformName(), "style": app.style().objectName(),
              "checks": checks, "captures": captures, "success": False}

    def check(name: str, condition: bool) -> None:
        checks.append({"name": name, "passed": bool(condition)})
        if not condition:
            raise RuntimeError(name)

    def click(button: QPushButton) -> None:
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        app.processEvents()

    def select(index: int) -> None:
        item = lab.scenarios.item(index)
        lab.scenarios.scrollToItem(item)
        point = lab.scenarios.visualItemRect(item).center()
        QTest.mouseClick(lab.scenarios.viewport(), Qt.MouseButton.LeftButton, pos=point)
        app.processEvents()

    def capture(name: str) -> None:
        if output is not None:
            captures.append(lab.capture(output, name))

    current = lab.coordinator.current
    try:
        lab.activateWindow()
        QTest.qWaitForWindowActive(lab)
        pin = lab.help_widget.findChild(QPushButton, "helpPin")
        original = lab.registry.topics()

        check("Start mit deutscher JSON-Hilfe", current().resolved_topic_id == "studio.help" and len(original) >= 15)
        select(1)
        first = current()
        select(2)
        check("Taste gewählt, gleiche Hilfe mit neuen Fakten", first.resolved_topic_id == "keypad.slot.occupied"
              and current().entry is first.entry and current().facts != first.facts
              and lab.registry.topics() == original)
        select(1)
        capture("01_belegte_taste_hell_380")
        click(pin)
        select(4)
        check("Pin blockiert automatischen Wechsel", current().pinned and current().facts == first.facts)
        QTest.keyClick(lab.scenarios, Qt.Key.Key_F1)
        app.processEvents()
        check("Fenster-F1 wechselt bei aktivem Pin", current().pinned and current().resolved_topic_id == "action.definition")
        lab.theme.setCurrentIndex(1)
        details = lab.help_widget.findChild(QWidget, "helpDetailsToggle")
        QTest.mouseClick(details, Qt.MouseButton.LeftButton)
        app.processEvents()
        capture("02_f1_pin_details_dunkel_380")

        related = lab.help_widget.findChild(QPushButton, "helpRelated.catalog.parameter")
        click(related)
        check("Verwandtes Thema ist explizit und behält Pin", current().resolved_topic_id == "catalog.parameter"
              and current().pinned and not current().facts)
        click(pin)
        check("Lösen des Pins behält das angezeigte Thema", not current().pinned
              and current().resolved_topic_id == "catalog.parameter")

        select(7)
        check("Angefragte ID fällt auf nächsten Vorfahren zurück", current().is_fallback
              and current().resolved_topic_id == "keypad.slot")
        lab.sidebar_width.setCurrentText("300")
        capture("03_fallback_dunkel_300")
        select(8)
        empty_title = lab.help_widget.findChild(QWidget, "helpTitle")
        check("Unbekannte Hierarchie zeigt neutralen Zustand", current().entry is None and not current().facts
              and empty_title.toPlainText() == "Keine passende Hilfe")
        capture("04_leerzustand_dunkel_300")
        select(9)
        click(lab.source_button)
        description = lab.help_widget.findChild(QWidget, "helpDescription")
        check("Quellenregistrierung aktualisiert Anzeige mit Literaltext", current().resolved_topic_id == "lab.literal"
              and LITERAL in description.toPlainText() and description.isVisible())
        lab.sidebar_width.setCurrentText("500")
        lab.theme.setCurrentIndex(0)
        capture("05_zusatzquelle_literal_hell_500")
        click(lab.source_button)
        check("Quellenentfernung erhält mitgelieferte Themen", current().entry is None and lab.registry.topics() == original)

        if output is not None:
            field = next(iter(lab.fields))
            click(field)
            QTest.keyClick(field, Qt.Key.Key_End)
            QTest.keyClicks(field, " Demo")
            app.processEvents()
            check("Feldeingabe aktualisiert Host-Kontext", current().resolved_topic_id == "catalog.search"
                  and current().facts == (("Katalogsuche", "Mikrofon Demo"),))
            capture("06_feldhilfe_hell_500")
            select(9)
            check("Bereits markierte Zeile kann nach Feldfokus erneut gewählt werden",
                  current().requested_topic_id == "lab.literal")
            select(3)
            check("Freie Taste hat eigene Hilfe", current().resolved_topic_id == "keypad.slot.empty")
            select(5)
            check("ProblemsPanel liefert Meldungsfakten", current().resolved_topic_id == "problems.diagnostic"
                  and ("Code", "BEISPIEL_REFERENZ") in current().facts)
            click(pin)
            select(6)
            click(lab.help_button)
            check("Hilfeknopf öffnet Symbolhilfe bei aktivem Pin", current().pinned
                  and current().resolved_topic_id == "symbol.ict")
        report["success"] = True
    except Exception as exc:
        report["error"] = str(exc)
    if output is not None:
        for filename, payload in (("lab_walkthrough_report.json", report), ("lab_event_log.json", lab.events)):
            (output / filename).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--smoke", action="store_true", help="Run Qt checks offscreen")
    modes.add_argument("--evidence", type=Path, metavar="ORDNER", help="Run a visible walkthrough and save evidence")
    options = parser.parse_args()
    if options.smoke:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        if sys.platform == "win32":
            os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
    app = QApplication([])
    app.setStyle("Fusion")
    if options.evidence and app.platformName() in {"offscreen", "minimal"}:
        parser.error("--evidence requires a windowed Qt platform")
    lab = ContextHelpLab()
    lab.show()
    if not options.smoke and options.evidence is None:
        return app.exec()
    if options.evidence is not None:
        options.evidence.mkdir(parents=True, exist_ok=True)
    report = walkthrough(lab, options.evidence)
    passed = sum(check["passed"] for check in report["checks"])
    print(f"{'Smoke' if options.smoke else 'Evidence'}: {passed}/{len(report['checks'])} PASS")
    if not report["success"]:
        print("FAIL:", report["error"], file=sys.stderr)
    lab.close()
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
