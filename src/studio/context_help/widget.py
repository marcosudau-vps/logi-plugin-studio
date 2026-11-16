"""Palette-aware presentation of already resolved help snapshots."""

from math import ceil

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPalette, QTextOption
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from .entries import HelpDisplayState


class _HelpText(QTextEdit):
    """Noninteractive text block that wraps even long identifiers."""

    def __init__(self, name: str, *, bold: bool = False, scale: float = 1.0) -> None:
        super().__init__()
        self.setObjectName(name)
        self.setReadOnly(True)
        self.setAcceptRichText(False)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.viewport().setAutoFillBackground(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        font = self.font()
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() * scale)
        elif font.pixelSize() > 0:
            font.setPixelSize(round(font.pixelSize() * scale))
        font.setBold(bold)
        self.setFont(font)
        self.document().setDocumentMargin(0)
        self.document().documentLayout().documentSizeChanged.connect(self._fit_height)

    def _fit_height(self, size) -> None:
        self.setFixedHeight(ceil(size.height()))

    def show_text(self, text: str) -> None:
        self.setPlainText(text)
        self.setVisible(bool(text))


class _PinButton(QPushButton):
    def nextCheckState(self) -> None:
        # Only a returned snapshot may change the checked state.
        pass


class _RelatedButton(QPushButton):
    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title
        self.setAccessibleName(title)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(28)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # The title is data. Escape ampersands so Qt never turns them into shortcuts.
        text = self.fontMetrics().elidedText(self._title, Qt.TextElideMode.ElideRight, max(0, self.width() - 24))
        self.setText(text.replace("&", "&&"))


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


class ContextHelpWidget(QWidget):
    relatedTopicRequested = Signal(str)
    pinRequested = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Kontexthilfe")
        self.setMinimumWidth(240)
        self._state: HelpDisplayState | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setBackgroundRole(QPalette.ColorRole.AlternateBase)
        header.setAutoFillBackground(True)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 9, 14, 9)
        header_layout.addWidget(_section_label("Kontexthilfe"), 1)
        self._pin = _PinButton()
        self._pin.setObjectName("helpPin")
        self._pin.setCheckable(True)
        self._pin.setMinimumSize(96, 28)
        self._pin.clicked.connect(self._request_pin)
        header_layout.addWidget(self._pin)
        layout.addWidget(header)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("helpScroll")
        self._scroll.setAccessibleName("Hilfetext")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        article = QWidget()
        article.setBackgroundRole(QPalette.ColorRole.Base)
        article.setAutoFillBackground(True)
        self._scroll.setWidget(article)
        layout.addWidget(self._scroll, 1)
        content = QVBoxLayout(article)
        content.setContentsMargins(16, 15, 16, 18)
        content.setSpacing(10)

        self._title = _HelpText("helpTitle", bold=True, scale=1.55)
        self._summary = _HelpText("helpSummary", bold=True)
        self._fallback = _HelpText("helpFallback")
        self._description = _HelpText("helpDescription")
        for block in (self._title, self._summary, self._fallback, self._description):
            content.addWidget(block)
        self._example_section, example_layout = self._section(content, "Beispiel")
        self._example = _HelpText("helpExample")
        example_layout.addWidget(self._example)
        self._facts_section, facts_layout = self._section(content, "Aktueller Kontext")
        self._facts = _HelpText("helpFacts")
        facts_layout.addWidget(self._facts)

        self._details_toggle = QToolButton()
        self._details_toggle.setObjectName("helpDetailsToggle")
        self._details_toggle.setText("Technische Details")
        self._details_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._details_toggle.setCheckable(True)
        self._details_toggle.toggled.connect(self._show_details)
        content.addWidget(self._details_toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        self._details = _HelpText("helpDetails")
        content.addWidget(self._details)

        self._related_section, self._related_layout = self._section(content, "Verwandte Themen")
        content.addStretch()
        self.set_help(None)

    @staticmethod
    def _section(parent: QVBoxLayout, title: str) -> tuple[QWidget, QVBoxLayout]:
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 5, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(_section_label(title))
        parent.addWidget(section)
        return section, layout

    def _request_pin(self) -> None:
        self.pinRequested.emit(not self._pin.isChecked())

    def _show_details(self, expanded: bool) -> None:
        self._details_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self._details.setVisible(expanded and bool(self._details.toPlainText()))
        self._details_toggle.setAccessibleDescription("Ausgeklappt" if expanded else "Eingeklappt")

    def _set_related(self, related: tuple[tuple[str, str], ...]) -> None:
        while self._related_layout.count() > 1:
            button = self._related_layout.takeAt(1).widget()
            if button.hasFocus():
                self._pin.setFocus()
            button.hide()
            button.deleteLater()
        for topic_id, title in related:
            button = _RelatedButton(title)
            button.setObjectName(f"helpRelated.{topic_id}")
            button.clicked.connect(lambda checked=False, topic=topic_id: self.relatedTopicRequested.emit(topic))
            self._related_layout.addWidget(button)
        self._related_section.setVisible(bool(related))

    def set_help(self, state: HelpDisplayState | None) -> None:
        previous = self._state
        self._state = state
        pinned = state.pinned if state else False
        self._pin.setChecked(pinned)
        self._pin.setText("Angeheftet" if pinned else "Anheften")
        self._pin.setAccessibleName("Hilfe lösen" if pinned else "Hilfe anheften")
        self._pin.setToolTip("Automatische Kontextwechsel wieder zulassen." if pinned
                             else "Thema bei automatischen Kontextwechseln behalten.")

        entry = state.entry if state else None
        old_entry = previous.entry if previous else None
        if entry != old_entry or previous is None:
            if entry is None or old_entry is None or entry.topic_id != old_entry.topic_id:
                self._details_toggle.setChecked(False)
                self._scroll.verticalScrollBar().setValue(0)
            self._title.show_text(entry.title if entry else "Keine passende Hilfe")
            self._summary.show_text(entry.summary if entry else
                                    "Wähle einen Bereich aus oder öffne die Hilfe für das aktuelle Feld.")
            self._description.show_text(entry.description if entry else "")
            self._example.show_text(entry.example if entry else "")
            self._example_section.setVisible(bool(entry and entry.example))
            self._details.setPlainText(entry.technical_details if entry else "")
            self._details_toggle.setVisible(bool(entry and entry.technical_details))
            self._show_details(self._details_toggle.isChecked())

        self._fallback.show_text(
            f"Übergeordnetes Thema\n{state.requested_topic_id} → {state.resolved_topic_id}"
            if state and state.is_fallback else ""
        )
        facts = state.facts if state and entry else ()
        self._facts.show_text("\n".join(f"{label}  ·  {value}" for label, value in facts))
        self._facts_section.setVisible(bool(facts))
        related = state.related_topics if state and entry else ()
        if previous is None or related != previous.related_topics:
            self._set_related(related)
