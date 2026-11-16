"""Minimal in-memory host for the Keypad Lab and tests. Simulation only.

It demonstrates that the host stays the only writer: it validates each
EditRequest and sends a new frame on success. Slot layouts, pagination and
logical positions are invented lab data, not SDK or hardware evidence.

The tiles come in two kinds of test data. Colourful function-test tiles make
individual slots easy to tell apart. Black-ground reference tiles reproduce the
look of the device references so that the skin can be judged at all. Both are
plain QImage test data; neither changes what the widget does.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import math

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF

from studio.keypad_contract import ActionOffer, EditRequest, KeypadFrame, NavigationCapability, SlotAddress, SlotData
from studio.keypad_preview.skin import FONT_FAMILY

VIEW_ID = "lab.folder.main"
CONTEXT_ID = "lab.context"
TILE_SIZE = 116
REFERENCE_TILE_UNITS = 132      # Size of the black LCD area of the device skin.
REFERENCE_TILE_PIXELS = 264
VISUAL_FUNCTION = "function"
VISUAL_REFERENCE = "reference"


@dataclass(frozen=True)
class LabAction:
    action_id: str
    display_name: str
    color: str = ""        # An empty color means the action has no image, only a label.
    glyph: str = "dot"
    parameters: tuple[str, ...] = ()
    reference_icon: str = ""     # Symbol of the black-ground reference tile.


@dataclass(frozen=True)
class LabPlacement:
    placement_id: str
    action_id: str
    action_parameter: str | None
    page: int
    physical_index: int


@dataclass(frozen=True)
class LabScenario:
    key: str
    title: str
    device_type: str
    area: str
    content_slots: tuple[int, ...]
    navigation_slots: tuple[int, ...] = ()
    unavailable_slots: tuple[int, ...] = ()
    locked_slots: tuple[int, ...] = ()
    page_count: int = 1
    seed: tuple[tuple[str, str | None, int, int], ...] = ()  # action, parameter, page, slot
    start_page: int = 0


@dataclass(frozen=True)
class HostDecision:
    request_id: str
    operation: str
    accepted: bool
    code: str
    message: str
    revision: str


LAB_ACTIONS = (
    LabAction("lab.action.mute", "Mikro stumm", "#d9534f", "ring"),
    LabAction("lab.action.camera", "Kamera", "#3f7fd9", "square"),
    LabAction("lab.action.scene", "Szene", "#3aa76d", "triangle", ("Studio", "Pause")),
    LabAction("lab.action.note", "Notiz", "#b07cd8", "dot"),
    LabAction("lab.action.timer", "Timer starten"),
)
# Same captions as the reference screenshots, so that both can be compared directly.
REFERENCE_ACTIONS = (
    LabAction("lab.ref.mode", "Mode", "#c98a6d", "dot", reference_icon="toggle"),
    LabAction("lab.ref.actions_ring", "Actions Ring anzeigen", "#6d7ac9", "ring", reference_icon="dot_ring"),
    LabAction("lab.ref.access_ring", "Access Ring", "#2aa7c9", "ring", reference_icon="folder_ring"),
    LabAction("lab.ref.brightness_down", "Helligkeit -10 %"),
    LabAction("lab.ref.brightness_up", "Helligkeit +10 %"),
    LabAction("lab.ref.star", "Stern", "#8a8a8a", "dot", reference_icon="star"),
    LabAction("lab.ref.shortcuts", "Shortcut Guide", "#7a8aa0", "square", reference_icon="keyboard"),
    LabAction("lab.ref.display", "Power Display", "#8a8f96", "square", reference_icon="monitor"),
    LabAction("lab.ref.on_top", "Always On Top", "#4aa8e0", "square", reference_icon="layers"),
    LabAction("lab.ref.zones", "FancyZones", "#3f8fd0", "square", reference_icon="zones"),
    LabAction("lab.ref.workspaces", "Workspaces", "#3a9ad9", "square", reference_icon="stack"),
)
ALL_ACTIONS = LAB_ACTIONS + REFERENCE_ACTIONS
FOREIGN_OFFER = ActionOffer("lab.action.not_in_catalog", "Fremde Referenz (nicht im Katalog)")

_NINE = tuple(range(9))
_STANDARD_SEED = (
    ("lab.action.mute", None, 0, 0), ("lab.action.camera", None, 0, 1), ("lab.action.scene", "Studio", 0, 2),
    ("lab.action.note", None, 0, 3), ("lab.action.mute", None, 0, 5), ("lab.action.timer", None, 0, 7),
    ("lab.action.scene", "Pause", 1, 0), ("lab.action.camera", None, 1, 4), ("lab.action.note", None, 2, 8),
)
LAB_SCENARIOS = (
    LabScenario("nine", "9 Inhalts-Slots, 3 Seiten (simuliert)", "LabDevice", "None", _NINE, page_count=3,
                seed=_STANDARD_SEED),
    LabScenario("navigation", "8 Inhalte + SDK-Navigation (simuliertes Beispiel)", "LabDevice", "ButtonArea",
                tuple(range(8)), (8,), page_count=2,
                seed=tuple(entry for entry in _STANDARD_SEED if entry[3] != 8)),
    LabScenario("locked", "Gesperrte und nicht verfügbare Slots (simuliert)", "LabDevice", "None", _NINE,
                unavailable_slots=(6,), locked_slots=(1, 4), seed=_STANDARD_SEED[:5]),
    LabScenario("four", "Nur 4 gemeldete Slots (simuliert)", "LabDevice", "None", (0, 1, 2, 3),
                seed=_STANDARD_SEED[:3]),
    LabScenario("sparse", "Lückenhafte Slots 2, 7, 12 (simuliert)", "LabDevice", "None", (2, 7, 12),
                seed=(("lab.action.camera", None, 0, 7),)),
    LabScenario("reference", "Referenzbelegung, 7 Seiten (simuliert)", "LabDevice", "None", _NINE, page_count=7, start_page=1,
                seed=(("lab.ref.mode", None, 1, 0), ("lab.ref.actions_ring", None, 1, 1), ("lab.ref.access_ring", None, 1, 2),
                      ("lab.ref.access_ring", None, 1, 5), ("lab.ref.brightness_down", None, 1, 7),
                      ("lab.ref.brightness_up", None, 1, 8),
                      ("lab.ref.star", None, 2, 0), ("lab.ref.shortcuts", None, 2, 2), ("lab.ref.display", None, 2, 5),
                      ("lab.ref.on_top", None, 2, 6), ("lab.ref.zones", None, 2, 7), ("lab.ref.workspaces", None, 2, 8))),
)


def render_lab_tile(action: LabAction, parameter: str | None, variant: int = 0) -> QImage | None:
    """Self-drawn sample tile. Abstract shapes only, no third-party artwork."""
    if not action.color:
        return None
    image = QImage(TILE_SIZE, TILE_SIZE, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    base = QColor(action.color)
    if variant % 2:
        base = QColor.fromHsv((base.hue() + 150) % 360, base.saturation(), base.value())
    gradient = QLinearGradient(0, 0, 0, TILE_SIZE)
    gradient.setColorAt(0.0, base.lighter(120))
    gradient.setColorAt(1.0, base.darker(170))
    painter.fillRect(0, 0, TILE_SIZE, TILE_SIZE, gradient)
    painter.setPen(QPen(QColor(255, 255, 255, 235), 6))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    shape = QRectF(36, 14, 44, 44)
    if action.glyph == "ring":
        painter.drawEllipse(shape)
    elif action.glyph == "square":
        painter.drawRoundedRect(shape, 7, 7)
    elif action.glyph == "triangle":
        path = QPainterPath(QPointF(58, 14))
        path.lineTo(82, 58)
        path.lineTo(34, 58)
        path.closeSubpath()
        painter.drawPath(path)
    else:
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawEllipse(QRectF(46, 24, 24, 24))
    font = QFont()
    font.setPixelSize(15)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))
    caption = action.display_name if parameter is None else f"{action.display_name}\n{parameter}"
    painter.drawText(QRectF(4, 62, TILE_SIZE - 8, 50), int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), caption)
    painter.end()
    return image


def _paint_reference_icon(painter: QPainter, icon: str) -> None:
    """Simple high-contrast symbols in tile units, centred above the caption."""
    white = QColor("#ffffff")
    painter.setPen(Qt.PenStyle.NoPen)
    if icon == "toggle":
        painter.setBrush(QColor("#c98a6d"))
        painter.drawRoundedRect(QRectF(46, 17, 34, 20), 10, 10)
        painter.drawRoundedRect(QRectF(46, 40, 34, 20), 10, 10)
        painter.setBrush(QColor("#1b1b1b"))
        painter.drawEllipse(QRectF(50, 21, 12, 12))
        painter.drawEllipse(QRectF(50, 44, 12, 12))
    elif icon in ("dot_ring", "folder_ring"):
        colored = icon == "folder_ring"
        center = QPointF(63, 40 if colored else 38)
        radius = 32 if colored else 27
        painter.setBrush(QColor("#17b3d6") if colored else white)
        for step in range(8):
            angle = math.radians(90 + 45 * step)
            painter.drawEllipse(QPointF(center.x() + radius * math.cos(angle), center.y() + radius * math.sin(angle)),
                                6.5 if colored else 5.5, 6.5 if colored else 5.5)
        if colored:
            painter.setBrush(QColor("#7b5cf0"))
            painter.drawPolygon(QPolygonF([QPointF(52, 24), QPointF(78, 46), QPointF(66, 47), QPointF(72, 60),
                                           QPointF(66, 63), QPointF(60, 50), QPointF(52, 58)]))
            # The white notch at the top marks a folder in the reference.
            painter.setBrush(white)
            painter.drawRoundedRect(QRectF(39, -6, 48, 15), 5, 5)
    elif icon == "star":
        painter.fillRect(QRectF(-3, -3, REFERENCE_TILE_UNITS, REFERENCE_TILE_UNITS), QColor("#3c3c3c"))
        painter.setBrush(white)
        path = QPainterPath(QPointF(63, 2))
        path.quadTo(QPointF(66, 42), QPointF(106, 48))
        path.quadTo(QPointF(66, 54), QPointF(63, 96))
        path.quadTo(QPointF(60, 54), QPointF(20, 48))
        path.quadTo(QPointF(60, 42), QPointF(63, 2))
        painter.drawPath(path)
    elif icon == "keyboard":
        painter.setBrush(QColor("#a9b4c2"))
        painter.drawRoundedRect(QRectF(36, 26, 52, 32), 4, 4)
        painter.setBrush(QColor("#2b2f36"))
        for row in range(3):
            for column in range(6):
                painter.drawRect(QRectF(40 + column * 7.6, 30 + row * 8, 5.4, 5.4))
        painter.setPen(QPen(QColor("#31a8e0"), 3.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(QRectF(76, 46, 18, 18), 30 * 16, 280 * 16)
    elif icon == "monitor":
        painter.setBrush(QColor("#5a5f66"))
        painter.drawRoundedRect(QRectF(36, 18, 54, 40), 5, 5)
        painter.fillRect(QRectF(58, 58, 10, 8), QColor("#5a5f66"))
        painter.fillRect(QRectF(48, 66, 30, 4), QColor("#5a5f66"))
        painter.setBrush(QColor("#d9dde0"))
        painter.drawRect(QRectF(41, 23, 44, 30))
    elif icon == "layers":
        painter.setBrush(QColor("#8a9099"))
        painter.drawRoundedRect(QRectF(40, 32, 34, 34), 3, 3)
        painter.setBrush(QColor("#46b4ea"))
        painter.drawRoundedRect(QRectF(58, 16, 32, 32), 3, 3)
    elif icon == "zones":
        painter.fillRect(QRectF(41, 18, 22, 48), QColor("#57c8f0"))
        painter.fillRect(QRectF(65, 18, 22, 22), QColor("#3f8fd0"))
        painter.fillRect(QRectF(65, 42, 22, 24), QColor("#2c6fb0"))
    elif icon == "stack":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#2a7ac0"), 3))
        painter.drawRoundedRect(QRectF(36, 16, 30, 34), 5, 5)
        painter.setPen(QPen(QColor("#2f8fd5"), 3))
        painter.drawRoundedRect(QRectF(44, 22, 30, 34), 5, 5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#55bdf0"))
        painter.drawRoundedRect(QRectF(54, 30, 34, 36), 6, 6)
    else:
        painter.setBrush(white)
        painter.drawEllipse(QRectF(47, 22, 32, 32))


def render_reference_tile(action: LabAction, parameter: str | None) -> QImage | None:
    """Black LCD tile with a free-standing symbol and a small white caption near the lower edge."""
    if not action.color:
        return None
    image = QImage(REFERENCE_TILE_PIXELS, REFERENCE_TILE_PIXELS, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#000000"))
    painter = QPainter(image)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    painter.scale(REFERENCE_TILE_PIXELS / REFERENCE_TILE_UNITS, REFERENCE_TILE_PIXELS / REFERENCE_TILE_UNITS)
    painter.save()
    painter.translate(3, 3)
    _paint_reference_icon(painter, action.reference_icon or action.glyph)
    painter.restore()
    font = QFont(FONT_FAMILY)
    font.setPixelSize(18)
    font.setWeight(QFont.Weight.DemiBold)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))
    caption = action.display_name if parameter is None else f"{action.display_name} {parameter}"
    metrics = QFontMetricsF(font)
    lines: list[str] = []
    for word in caption.split():
        if lines and metrics.horizontalAdvance(f"{lines[-1]} {word}") <= REFERENCE_TILE_UNITS - 4:
            lines[-1] += f" {word}"
        else:
            lines.append(word)
    # Tight fixed line pitch and common centre, measured from the reference captions.
    pitch = 18.0
    baseline = 114.0 - (len(lines) - 1) * pitch / 2
    for line in lines:
        painter.drawText(QPointF((REFERENCE_TILE_UNITS - metrics.horizontalAdvance(line)) / 2, baseline), line)
        baseline += pitch
    painter.end()
    return image


class LabHost(QObject):
    """The only writer of lab placements. No project file is involved."""

    frameChanged = Signal(object)    # KeypadFrame
    decisionMade = Signal(object)    # HostDecision
    historyChanged = Signal(bool, bool)

    def __init__(self, scenario_key: str = "nine", parent: QObject | None = None, *, visual_mode: str = VISUAL_FUNCTION) -> None:
        super().__init__(parent)
        self.actions = {action.action_id: action for action in ALL_ACTIONS}
        self.visual_mode = visual_mode
        self.load_scenario(scenario_key, emit=False)

    def set_visual_mode(self, mode: str) -> None:
        """Choose which test tiles the frames carry. Placements and revision stay as they are."""
        self.visual_mode = mode
        self.resend_frame()

    def _tile(self, action: LabAction, parameter: str | None) -> QImage | None:
        if self.visual_mode == VISUAL_REFERENCE:
            return render_reference_tile(action, parameter)
        return render_lab_tile(action, parameter, self.variant)

    def load_scenario(self, key: str, *, emit: bool = True) -> None:
        self.scenario = next(item for item in LAB_SCENARIOS if item.key == key)
        self.placements: dict[str, LabPlacement] = {}
        self._next_placement = 1
        for action_id, parameter, page, slot in self.scenario.seed:
            self._add_placement(action_id, parameter, page, slot)
        self.page = self.scenario.start_page
        self.page_count = self.scenario.page_count
        self._revision_number = 1
        self.variant = 0
        self.undo_stack: list[dict[str, LabPlacement]] = []
        self.redo_stack: list[dict[str, LabPlacement]] = []
        if emit:
            self.resend_frame()
            self._emit_history()

    def _add_placement(self, action_id: str, parameter: str | None, page: int, slot: int) -> LabPlacement:
        placement = LabPlacement(f"lab.placement.{self._next_placement}", action_id, parameter, page, slot)
        self._next_placement += 1
        self.placements[placement.placement_id] = placement
        return placement

    @property
    def revision(self) -> str:
        return f"lab-rev-{self._revision_number}"

    def offers(self) -> list[ActionOffer]:
        offers = []
        for action in ALL_ACTIONS:
            for parameter in action.parameters or (None,):
                name = action.display_name if parameter is None else f"{action.display_name} · {parameter}"
                offers.append(ActionOffer(action.action_id, name, parameter, self._tile(action, parameter)))
        offers.append(FOREIGN_OFFER)
        return offers

    def _logical_position(self, placement: LabPlacement) -> int:
        """Simulated host mapping, deliberately owned here and not in the widget."""
        usable = [i for i in self.scenario.content_slots if i not in self.scenario.unavailable_slots]
        return placement.page * len(usable) + usable.index(placement.physical_index)

    def placement_at(self, page: int, slot: int) -> LabPlacement | None:
        return next((p for p in self.placements.values() if p.page == page and p.physical_index == slot), None)

    def frame(self) -> KeypadFrame:
        scenario = self.scenario
        capability = NavigationCapability(scenario.device_type, scenario.area, scenario.content_slots,
                                          scenario.navigation_slots)
        slots = [SlotData(index, "sdk_navigation", label="SDK-Navigation (simuliert)",
                          tooltip="Simulierter SDK-Navigationsslot; kein Hardwarebeleg")
                 for index in scenario.navigation_slots]
        for index in scenario.content_slots:
            locked = index in scenario.locked_slots
            placement = self.placement_at(self.page, index)
            if index in scenario.unavailable_slots:
                slots.append(SlotData(index, "unavailable"))
            elif placement is None:
                slots.append(SlotData(index, "empty", editable=not locked))
            else:
                action = self.actions[placement.action_id]
                suffix = f" · {placement.action_parameter}" if placement.action_parameter else ""
                variant = " (Variante)" if self.variant % 2 else ""
                label = action.display_name + suffix + variant
                slots.append(SlotData(
                    index, "placement", placement.placement_id, placement.action_id, placement.action_parameter,
                    label, self._tile(action, placement.action_parameter), not locked,
                    self._logical_position(placement),
                    f"{label}\n{placement.placement_id} | {placement.action_id}"))
        return KeypadFrame(CONTEXT_ID, VIEW_ID, self.revision, capability, tuple(slots), self.page, self.page_count)

    def resend_frame(self) -> None:
        self.frameChanged.emit(self.frame())

    def show_page(self, page: int) -> None:
        if 0 <= page < self.page_count:
            self.page = page
            self.resend_frame()

    def add_page(self) -> None:
        """Answer a page request by simulation: a new empty page, shown at once."""
        self.page_count += 1
        self.page = self.page_count - 1
        self._revision_number += 1
        self.resend_frame()

    def external_change(self) -> None:
        """Simulate a change from elsewhere: new revision, no new frame yet."""
        self._revision_number += 1

    def cycle_visuals(self) -> None:
        self.variant += 1
        self._revision_number += 1
        self.resend_frame()

    # ------------------------------------------------------------------ validation and commit

    def _check_source(self, request: EditRequest) -> tuple[LabPlacement | None, str, str]:
        source = request.source
        placement = self.placements.get(source.placement_id)
        if source.view_id != VIEW_ID:
            return None, "unknown_view", "Quelle liegt in einer anderen Ansicht."
        if placement is None or placement.page != source.page_index or placement.physical_index != source.physical_index:
            return None, "source_mismatch", "Die Quelladresse passt nicht zur Platzierung."
        if source.physical_index in self.scenario.locked_slots:
            return None, "source_locked", "Die Quelltaste ist gesperrt."
        return placement, "", ""

    def _check_target(self, target: SlotAddress) -> tuple[str, str]:
        scenario = self.scenario
        if target.view_id != VIEW_ID:
            return "unknown_view", "Ziel liegt in einer anderen Ansicht."
        if not 0 <= target.page_index < self.page_count:
            return "target_missing", "Die Zielseite existiert nicht."
        if target.physical_index in scenario.navigation_slots:
            return "target_navigation", "SDK-Navigationsslots sind nicht belegbar."
        if target.physical_index not in scenario.content_slots:
            return "target_missing", "Dieser Slot wurde nicht als Inhalts-Slot gemeldet."
        if target.physical_index in scenario.unavailable_slots:
            return "target_unavailable", "Der Slot ist nicht verfügbar."
        if target.physical_index in scenario.locked_slots:
            return "target_locked", "Die Zieltaste ist gesperrt."
        if self.placement_at(target.page_index, target.physical_index) is not None:
            return "target_occupied", "Das Ziel ist belegt. Es gibt kein stilles Ersetzen oder Tauschen."
        return "", ""

    def submit(self, request: EditRequest) -> HostDecision:
        code, message = self._validate(request)
        if code:
            return self._decide(request, False, code, message)
        self.undo_stack.append(dict(self.placements))
        self.redo_stack.clear()
        if request.operation == "move":
            placement = self.placements[request.source.placement_id]
            self.placements[placement.placement_id] = replace(
                placement, page=request.target.page_index, physical_index=request.target.physical_index)
            message = "Platzierung verschoben; placement_id unverändert."
        elif request.operation == "copy":
            origin = self.placements[request.source.placement_id]
            created = self._add_placement(origin.action_id, origin.action_parameter,
                                          request.target.page_index, request.target.physical_index)
            message = f"Neue Platzierung {created.placement_id} derselben Aktion {origin.action_id}."
        elif request.operation == "place":
            created = self._add_placement(request.action_id, request.action_parameter,
                                          request.target.page_index, request.target.physical_index)
            message = f"Neue Platzierung {created.placement_id} der Aktion {request.action_id}."
        else:
            del self.placements[request.source.placement_id]
            message = "Nur die Platzierung entfernt; die Aktion bleibt im Katalog."
        self._revision_number += 1
        decision = self._decide(request, True, "committed", message)
        self.resend_frame()
        self._emit_history()
        return decision

    def _validate(self, request: EditRequest) -> tuple[str, str]:
        if request.base_revision != self.revision:
            return "revision_conflict", f"Anfrage auf {request.base_revision}, aktuell {self.revision}."
        if request.operation != "place":
            placement, code, message = self._check_source(request)
            if code:
                return code, message
            if request.operation != "remove" and request.action_id not in (None, placement.action_id):
                return "source_mismatch", "Die Aktion passt nicht zur Quellplatzierung."
        if request.target is not None:
            code, message = self._check_target(request.target)
            if code:
                return code, message
        if request.operation == "place":
            action = self.actions.get(request.action_id)
            if action is None:
                return "unknown_action", f"Aktion {request.action_id} ist dem Host nicht bekannt."
            if request.action_parameter is not None and request.action_parameter not in action.parameters:
                return "unknown_parameter", f"Parameter {request.action_parameter!r} ist nicht zulässig."
        return "", ""

    def _decide(self, request: EditRequest, accepted: bool, code: str, message: str) -> HostDecision:
        decision = HostDecision(request.request_id, request.operation, accepted, code, message, self.revision)
        self.decisionMade.emit(decision)
        return decision

    def _emit_history(self) -> None:
        self.historyChanged.emit(bool(self.undo_stack), bool(self.redo_stack))

    def _swap_history(self, source: list, target: list) -> bool:
        if not source:
            return False
        target.append(dict(self.placements))
        self.placements = source.pop()
        self._revision_number += 1
        self.resend_frame()
        self._emit_history()
        return True

    def undo(self) -> bool:
        return self._swap_history(self.undo_stack, self.redo_stack)

    def redo(self) -> bool:
        return self._swap_history(self.redo_stack, self.undo_stack)
