"""KeypadPreviewWidget: shows one resolved SDK page and emits typed intents.

The host owns every commit. A slot keeps its old content until the host delivers
a new KeypadFrame. A click never runs an SDK command, handler or runtime change.
Only Hover, press, selection, focus and the clipboard marking live here.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QEvent, QMimeData, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import (QColor, QContextMenuEvent, QCursor, QDrag, QFont, QFontMetricsF, QImage, QKeyEvent,
                           QIcon, QKeySequence, QPainter, QPen, QPixmap)
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMenu, QSizePolicy, QToolButton, QToolTip, QWidget
from shiboken6 import getCppPointer, wrapInstance

from studio.keypad_contract import EditRequest, KeypadFrame, KeypadViewState, SlotAddress, SlotData
from studio.keypad_preview.mime import (ACTION_REF_MIME, SLOT_REF_MIME, SlotRef, decode_action_ref, decode_slot_ref,
                                        encode_slot_ref)
from studio.keypad_preview.pager import PageBar
from studio.keypad_preview.skin import (FONT_FAMILY, TINT_DRAG_SOURCE, TINT_DROP_CANDIDATE, TINT_DROP_TARGET, TINT_HOVER,
                                        KeypadSkin, drag_label_pixmap, neutral_skin, neutral_skin_for)

PRESS_SCALE = 0.97
PRESS_OFFSET_NATIVE = 1.5
PRESS_MS = 80
RELEASE_MS = 120
SPRING_PAGE_MS = 650
_PAGER_AREA_NATIVE = 105.0    # Room below the canvas, as in Pagination.png.
_PAGER_TOP_NATIVE = 45.0
_PAGER_AREA_MIN = 46.0
_MENU_BUTTON_NATIVE = 38.0
_MENU_BUTTON_OVERHANG = (13.0, 12.0)   # Beyond the key's right and top edge.
_ACTIVATION_KEYS = (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter)


@dataclass(frozen=True)
class _Press:
    index: int
    source: str  # "mouse" | "key"
    start: QPointF


@dataclass(frozen=True)
class _Clipboard:
    kind: str  # "cut" | "copy"
    source: SlotAddress
    context_id: str
    base_revision: str
    action_id: str
    action_parameter: str | None


class KeypadPreviewWidget(QWidget):
    slotSelected = Signal(object)          # SlotAddress
    pageRequested = Signal(int)            # 0-based page; the host delivers the frame
    pageCreateRequested = Signal()         # Non-binding: asks the host for a new page, edit mode only
    symbolEditRequested = Signal(object)   # SlotAddress; the host opens the SymbolDesigner
    editRequested = Signal(object)         # EditRequest, never a direct commit
    undoRequested = Signal()
    redoRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("keypadPreviewWidget")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAcceptDrops(False)
        self.setAccessibleName("Keypad-Vorschau")
        self._instance = uuid.uuid4().hex
        self._frame: KeypadFrame | None = None
        self._slots: dict[int, SlotData] = {}
        self._images: dict[int, QImage] = {}
        self._mode = "preview"
        self._edit_allowed = False
        self._placement_edit_allowed = True
        self._page_creation_allowed = True
        self._motion = True
        self._skin = neutral_skin()
        self._active_skin = self._skin
        self._selection: SlotAddress | None = None
        self._focus_index: int | None = None
        self._focus_visible = False
        self._hover_index: int | None = None
        self._press: _Press | None = None
        self._progress: dict[int, float] = {}
        self._anims: dict[int, QVariantAnimation] = {}
        self._release_after_press: set[int] = set()
        self._clipboard: _Clipboard | None = None
        self._drag_source: SlotAddress | None = None
        self._drag_slot: SlotData | None = None
        self._drop_index: int | None = None
        self._drop_ok = False
        self._menu: QMenu | None = None
        self._menu_index: int | None = None
        self._can_undo = True
        self._can_redo = True
        self._body_cache: QPixmap | None = None
        self._body_key: tuple | None = None
        self._cover_cache: QPixmap | None = None
        self._cover_key: tuple | None = None
        self._drag_active = False
        self._pointer_on_menu_button = False
        self._arrow_hover: int | None = None
        self._arrow_press: int | None = None
        self._spring_page: int | None = None
        self._spring_timer = QTimer(self)
        self._spring_timer.setSingleShot(True)
        self._spring_timer.setInterval(SPRING_PAGE_MS)
        self._spring_timer.timeout.connect(self._fire_spring_page)
        self._pager = QWidget(self)
        self._pager.setObjectName("keypadPager")
        self._pager_layout = QHBoxLayout(self._pager)
        self._pager_layout.setContentsMargins(0, 0, 0, 0)
        self._pager_layout.setSpacing(4)
        self.prev_page_button = self._pager_button("keypadPrevPage", "‹", "Vorherige Seite anfordern (Bild auf)")
        self.page_label = QLabel(self._pager)
        self.page_label.setObjectName("keypadPageLabel")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setMinimumWidth(84)
        self.page_bar = PageBar(self._pager)
        self.next_page_button = self._pager_button("keypadNextPage", "›", "Nächste Seite anfordern (Bild ab)")
        self._pager_layout.addStretch(1)
        for item in (self.prev_page_button, self.page_bar, self.page_label, self.next_page_button):
            self._pager_layout.addWidget(item)
        self._pager_layout.addStretch(1)
        self.prev_page_button.clicked.connect(lambda: self._request_page(-1))
        self.next_page_button.clicked.connect(lambda: self._request_page(+1))
        self.page_bar.pageClicked.connect(self._on_page_cell)
        self.page_bar.createClicked.connect(self._on_create_page)
        self._pager.hide()
        self._arrow_tip = QLabel(self)
        self._arrow_tip.setObjectName("keypadArrowTip")
        self._arrow_tip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._arrow_tip.hide()
        self._update_description()

    def _pager_button(self, name: str, text: str, tip: str) -> QToolButton:
        button = QToolButton(self._pager)
        button.setObjectName(name)
        button.setText(text)
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        button.setAutoRaise(True)
        button.setFixedSize(32, 30)
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        font = button.font()
        font.setPixelSize(20)
        button.setFont(font)
        return button

    # ------------------------------------------------------------------ inputs

    def set_frame(self, frame: KeypadFrame) -> None:
        """Show an authoritative frame. Emits no signal and aborts pending interaction."""
        if not isinstance(frame, KeypadFrame):
            raise TypeError("set_frame expects a KeypadFrame")
        self._abort_transient()
        self._frame = frame
        self._slots = {slot.physical_index: slot for slot in frame.slots}
        # Deep copies, so a host cannot change the display behind this frame.
        self._images = {slot.physical_index: slot.tile_image.copy().convertToFormat(
                            QImage.Format.Format_ARGB32_Premultiplied)
                        for slot in frame.slots if slot.tile_image is not None and not slot.tile_image.isNull()}
        clip = self._clipboard
        if clip is not None and (clip.context_id != frame.context_id or clip.source.view_id != frame.view_id
                                 or clip.base_revision != frame.revision):
            self._clipboard = None
        self._reconcile_selection()
        if self._focus_index is not None and not self._interactive(self._focus_index):
            self._focus_index = None
        self._refresh_skin()
        self._sync_pager()
        pointer = self.mapFromGlobal(QCursor.pos()).toPointF() if self.underMouse() else None
        self._hover_index = self.slot_at(pointer) if pointer is not None else None
        self._set_arrow_hover(self._usable_arrow_at(pointer) if pointer is not None else None)
        self._update_description()
        self.update()

    def set_mode(self, mode: str) -> None:
        if mode not in ("preview", "edit"):
            raise ValueError("mode must be preview or edit")
        if mode != self._mode:
            self._mode = mode
            self._editing_changed()

    def set_edit_allowed(self, allowed: bool) -> None:
        allowed = bool(allowed)
        if allowed != self._edit_allowed:
            self._edit_allowed = allowed
            self._editing_changed()

    def set_placement_edit_allowed(self, allowed: bool) -> None:
        """A host may allow symbol edits without allowing placement mutations."""
        if allowed != self._placement_edit_allowed:
            self._placement_edit_allowed = allowed
            self._editing_changed()

    def set_page_creation_allowed(self, allowed: bool) -> None:
        """A host may show editable slots on pages it cannot create."""
        if allowed != self._page_creation_allowed:
            self._page_creation_allowed = allowed
            self._sync_pager()

    def set_selection(self, address: SlotAddress | None) -> None:
        """Set the selection from outside. Never emits slotSelected, so no feedback loop."""
        if address is not None and not isinstance(address, SlotAddress):
            raise TypeError("set_selection expects a SlotAddress or None")
        self._selection = address
        self._reconcile_selection()
        self.update()

    def set_skin(self, skin: KeypadSkin | None) -> None:
        if skin is not None and not isinstance(skin, KeypadSkin):
            raise TypeError("set_skin expects a KeypadSkin or None")
        self._skin = skin if skin is not None else neutral_skin()
        self._refresh_skin()
        self.update()

    def set_motion_enabled(self, enabled: bool) -> None:
        self._motion = bool(enabled)
        if not self._motion:
            self._stop_animations()
            self._progress = {self._press.index: 1.0} if self._press is not None else {}
        self.update()

    def set_history_available(self, can_undo: bool, can_redo: bool) -> None:
        """Enable the Undo/Redo menu entries. The history itself stays with the host."""
        self._can_undo, self._can_redo = bool(can_undo), bool(can_redo)

    # ------------------------------------------------------------------ read-only view state

    def frame(self) -> KeypadFrame | None:
        return self._frame

    def mode(self) -> str:
        return self._mode

    def edit_allowed(self) -> bool:
        return self._edit_allowed

    def editing_active(self) -> bool:
        return self._mode == "edit" and self._edit_allowed

    def view_state(self) -> KeypadViewState | None:
        """DTO for hosts, e.g. NativeSymbolDesignerDialog.select_slot(state, physical_index)."""
        if self._frame is None:
            return None
        return KeypadViewState(self._frame, "edit" if self.editing_active() else "preview")

    def selection(self) -> SlotAddress | None:
        return self._selection

    def hovered_slot(self) -> int | None:
        return self._hover_index

    def pressed_slot(self) -> int | None:
        return self._press.index if self._press is not None else None

    def focused_slot(self) -> int | None:
        return self._focus_index

    def press_progress(self, index: int) -> float:
        return self._progress.get(index, 0.0)

    def key_motion(self, index: int) -> tuple[float, float]:
        """Current (scale, native y offset). Identity for reduced motion and resting keys."""
        progress = self._progress.get(index, 0.0)
        if not self._motion or progress <= 0.0:
            return 1.0, 0.0
        return 1.0 - (1.0 - PRESS_SCALE) * progress, PRESS_OFFSET_NATIVE * progress

    def clipboard_state(self) -> tuple[str, SlotAddress] | None:
        return (self._clipboard.kind, self._clipboard.source) if self._clipboard is not None else None

    def effective_skin(self) -> KeypadSkin:
        return self._active_skin

    def skin_notice(self) -> str:
        if self._active_skin is self._skin:
            return self._skin.notice
        return f"Skin „{self._skin.name}“ deckt die gemeldeten Slots nicht ab; neutraler Fallback aktiv."

    def physical_arrows_available(self) -> bool:
        return bool(self._active_skin.arrow_rects)

    def arrow_rect(self, step: int) -> QRectF:
        """Hardware arrow in widget coordinates; step is -1 (previous) or +1 (next)."""
        return self._to_widget(self._active_skin.arrow_rect(step))

    def hovered_arrow(self) -> int | None:
        return self._arrow_hover

    def pressed_arrow(self) -> int | None:
        return self._arrow_press

    def size_for_scale(self, scale: float) -> QSize:
        """Widget size that shows the skin at this scale of its native size, pager included."""
        width, height = self._active_skin.native_size
        return QSize(round(width * scale), round(height * scale + max(_PAGER_AREA_NATIVE * scale, _PAGER_AREA_MIN)))

    def slot_rect(self, index: int) -> QRectF:
        """Resting key rectangle in widget coordinates; input never follows the animation."""
        return self._to_widget(self._active_skin.key_rect(index))

    def slot_at(self, position: QPointF) -> int | None:
        """Interactive slot under a widget position, or None for gaps and the housing."""
        native = self._to_native(position)
        hit = self._active_skin.hit_key(native, self._reported())
        return hit if hit is not None and self._interactive(hit) else None

    def has_menu_button(self, index: int) -> bool:
        """Whether this slot offers the three-dot menu at all. It shows while hovered or focused."""
        return self._can_edit_symbol(index) or self._is_free_target(index)

    def menu_button_visible(self, index: int) -> bool:
        if not self.has_menu_button(index):
            return False
        return index == self._hover_index or (index == self._focus_index and self._focus_visible) or (
            self._menu is not None and index == self._menu_index)

    def menu_button_rect(self, index: int) -> QRectF:
        return self._to_widget(self._menu_button_native(index))

    # ------------------------------------------------------------------ slot rules

    def _reported(self) -> tuple[int, ...]:
        if self._frame is None:
            return ()
        capability = self._frame.capability
        return capability.content_slots + capability.navigation_slots

    def _interactive(self, index: int) -> bool:
        slot = self._slots.get(index)
        return slot is not None and slot.role != "unavailable"

    def _is_content(self, index: int) -> bool:
        return self._frame is not None and index in self._frame.capability.content_slots

    def _can_edit_symbol(self, index: int) -> bool:
        slot = self._slots.get(index)
        return (self.editing_active() and slot is not None and slot.role == "placement"
                and slot.editable and self._is_content(index))

    def _is_source(self, index: int) -> bool:
        return self._placement_edit_allowed and self._can_edit_symbol(index)

    def _is_free_target(self, index: int) -> bool:
        slot = self._slots.get(index)
        return (self._placement_edit_allowed and self.editing_active() and slot is not None and slot.role == "empty"
                and slot.editable and self._is_content(index))

    def _address(self, index: int) -> SlotAddress:
        slot = self._slots[index]
        return SlotAddress(self._frame.view_id, self._frame.page_index, index, slot.placement_id)

    def _selected_index(self) -> int | None:
        address, frame = self._selection, self._frame
        if address is None or frame is None or address.page_index != frame.page_index:
            return None
        return address.physical_index

    def _reconcile_selection(self) -> None:
        """Keep a selection only while it still points at what it selected."""
        address, frame = self._selection, self._frame
        if address is None or frame is None:
            return
        if address.view_id != frame.view_id:
            self._selection = None
        elif address.page_index == frame.page_index:
            slot = self._slots.get(address.physical_index)
            if address.placement_id is not None and (slot is None or slot.placement_id != address.placement_id):
                moved = next((s for s in frame.slots if s.placement_id == address.placement_id), None)
                self._selection = self._address(moved.physical_index) if moved is not None else None
            elif slot is None or not self._interactive(address.physical_index):
                self._selection = None
            else:
                self._selection = self._address(address.physical_index)

    def _editing_changed(self) -> None:
        self._abort_transient()
        self._clipboard = None
        self.setAcceptDrops(self.editing_active())
        self._sync_pager()
        self._update_description()
        self.update()

    def _abort_transient(self) -> None:
        """End everything that must not survive a new frame or mode."""
        self._press = None
        self._stop_animations()
        self._progress.clear()
        if self._menu is not None:
            self._menu.close()
        self._spring_timer.stop()
        self._spring_page = None
        self._drop_index = None
        self._arrow_press = None
        self._set_arrow_hover(None)

    def _refresh_skin(self) -> None:
        reported = self._reported()
        if self._skin.covers(reported):
            active = self._skin
        else:
            active = neutral_skin_for(reported)
        if active is not self._active_skin:
            self._active_skin = active
            self._body_cache = self._cover_cache = None
            self.updateGeometry()
        self._sync_pager()

    def _sync_pager(self) -> None:
        frame = self._frame
        if frame is None:
            self._pager.hide()
            return
        multiple = frame.page_count > 1
        creatable = self.editing_active() and self._page_creation_allowed
        physical = self.physical_arrows_available()
        scale, _, _ = self._canvas()
        arrow_room = 0 if physical else 2 * (self.prev_page_button.width() + 8)
        self.page_bar.set_state(frame.page_index, frame.page_count, creatable, scale, max(0, self.width() - arrow_room - 8))
        compact = not self.page_bar.fits()
        self.page_label.setText(f"Seite {frame.page_index + 1} / {frame.page_count}")
        self.prev_page_button.setEnabled(frame.page_index > 0)
        self.next_page_button.setEnabled(frame.page_index < frame.page_count - 1)
        self.page_bar.setVisible((multiple or creatable) and not compact)
        self.page_label.setVisible(multiple and compact)
        arrows = multiple and (compact or not physical)
        self.prev_page_button.setVisible(arrows)
        self.next_page_button.setVisible(arrows)
        self._pager.setVisible(multiple or (creatable and not compact))
        self._layout_pager()

    def _request_page(self, step: int) -> None:
        frame = self._frame
        if frame is not None and 0 <= frame.page_index + step < frame.page_count:
            self.pageRequested.emit(frame.page_index + step)

    def _on_page_cell(self, page: int) -> None:
        frame = self._frame
        if frame is not None and 0 <= page < frame.page_count and page != frame.page_index:
            self.pageRequested.emit(page)

    def _on_create_page(self) -> None:
        if self.editing_active() and self._page_creation_allowed:
            self.pageCreateRequested.emit()

    def _update_description(self) -> None:
        frame = self._frame
        if frame is None:
            self.setAccessibleDescription("Kein Frame geladen.")
            return
        parts = [f"Seite {frame.page_index + 1} von {frame.page_count}",
                 "Bearbeitung aktiv" if self.editing_active() else "Vorschau"]
        slot = self._slots.get(self._focus_index) if self._focus_index is not None else None
        if slot is not None:
            names = {"placement": slot.label or slot.action_id, "empty": "frei",
                     "sdk_navigation": slot.label or "SDK-Navigation"}
            parts.append(f"Taste {slot.physical_index + 1}: {names.get(slot.role, slot.role)}")
        self.setAccessibleDescription(", ".join(parts))

    # ------------------------------------------------------------------ geometry

    def _layout_metrics(self) -> tuple[float, float, float, float]:
        """Scale, canvas x and y, and the height of the area below the canvas."""
        width, height = self._active_skin.native_size
        scale = max(0.01, min(self.width() / width, self.height() / (height + _PAGER_AREA_NATIVE)))
        area = _PAGER_AREA_NATIVE * scale
        if area < _PAGER_AREA_MIN:
            area = _PAGER_AREA_MIN
            scale = max(0.01, min(self.width() / width, max(1.0, self.height() - area) / height))
        ratio = self.devicePixelRatioF() or 1.0
        # Whole device pixels keep the layers sharp and at 100 % identical to the source files.
        x = round((self.width() - width * scale) / 2 * ratio) / ratio
        y = round((self.height() - height * scale - area) / 2 * ratio) / ratio
        return scale, x, y, area

    def _canvas(self) -> tuple[float, float, float]:
        scale, x, y, _ = self._layout_metrics()
        return scale, x, y

    def _to_native(self, point: QPointF) -> QPointF:
        scale, x, y = self._canvas()
        return QPointF((point.x() - x) / scale, (point.y() - y) / scale)

    def _to_widget(self, rect: QRectF) -> QRectF:
        scale, x, y = self._canvas()
        return QRectF(x + rect.x() * scale, y + rect.y() * scale, rect.width() * scale, rect.height() * scale)

    def _menu_button_native(self, index: int) -> QRectF:
        """Square at the key's top right corner, partly outside it, as in the reference."""
        scale, _, _ = self._canvas()
        rect = self._active_skin.key_rect(index)
        side = min(max(_MENU_BUTTON_NATIVE, 22.0 / scale), rect.width() * 0.5)
        over_x, over_y = _MENU_BUTTON_OVERHANG
        return QRectF(rect.right() + over_x - side, rect.top() - over_y, side, side)

    def _menu_button_at(self, position: QPointF) -> int | None:
        """The overhanging part only counts while the button shows; a hidden one has no hit area in the gap."""
        native = self._to_native(position)
        under_pointer = self.slot_at(position)
        for index in (self._hover_index, under_pointer):
            if index is not None and self.has_menu_button(index) and self._menu_button_native(index).contains(native):
                return index
        return None

    def _layout_pager(self) -> None:
        scale, x, y, area = self._layout_metrics()
        width, height = self._active_skin.native_size
        top = y + height * scale
        gap = min(_PAGER_TOP_NATIVE * scale, max(0.0, area - self.page_bar.height()))
        strip = max(self.page_bar.height(), self.prev_page_button.height())
        self._pager.setGeometry(0, round(top + gap), self.width(), strip)
        center = self._active_skin.center_x
        shift = round(2 * (center - width / 2) * scale) if center is not None else 0
        self._pager_layout.setContentsMargins(max(0, shift), 0, 0, 0)
        self._pager_layout.activate()  # Drag hit tests must not see a stale button layout.

    def sizeHint(self) -> QSize:
        return self.size_for_scale(0.62)

    def minimumSizeHint(self) -> QSize:
        return QSize(150, 150)

    def resizeEvent(self, event) -> None:
        self._sync_pager()
        super().resizeEvent(event)

    # ------------------------------------------------------------------ press state

    def _begin_press(self, index: int, source: str, start: QPointF) -> None:
        if self._press is not None:
            self._cancel_press()
        self._press = _Press(index, source, start)
        self._animate_to(index, True)

    def _cancel_press(self) -> None:
        """Abort the click candidate; it never produces a selection."""
        press, self._press = self._press, None
        if press is not None:
            self._animate_to(press.index, False)

    def _commit_press(self) -> None:
        press, self._press = self._press, None
        if press is None:
            return
        self._animate_to(press.index, False)
        if self._frame is None or not self._interactive(press.index):
            return
        address = self._address(press.index)
        # Change-only, so the second half of a double click emits nothing.
        if address != self._selection:
            self._selection = address
            self.update()
            self.slotSelected.emit(address)

    def _animate_to(self, index: int, pressed: bool) -> None:
        if not self._motion:
            if pressed:
                self._progress[index] = 1.0
            else:
                self._progress.pop(index, None)
            self._update_key(index)
            return
        running = self._anims.get(index)
        if not pressed and running is not None and running.endValue() == 1.0:
            # A very short click still shows its press phase before springing back.
            self._release_after_press.add(index)
            return
        self._release_after_press.discard(index)
        self._stop_animation(index)
        start = self._progress.get(index, 0.0)
        target = 1.0 if pressed else 0.0
        if start == target:
            return
        animation = QVariantAnimation(self)
        animation.setStartValue(start)
        animation.setEndValue(target)
        animation.setDuration(PRESS_MS if pressed else RELEASE_MS)
        animation.valueChanged.connect(lambda value, i=index: self._set_progress(i, float(value)))
        animation.finished.connect(lambda i=index, a=animation: self._animation_finished(i, a))
        self._anims[index] = animation
        animation.start()

    def _animation_finished(self, index: int, animation: QVariantAnimation) -> None:
        if self._anims.get(index) is animation:
            del self._anims[index]
        animation.deleteLater()
        if index in self._release_after_press:
            self._release_after_press.discard(index)
            self._animate_to(index, False)

    def _set_progress(self, index: int, value: float) -> None:
        if value <= 0.0:
            self._progress.pop(index, None)
        else:
            self._progress[index] = value
        self._update_key(index)

    def _stop_animation(self, index: int) -> None:
        animation = self._anims.pop(index, None)
        if animation is not None:
            animation.stop()
            animation.deleteLater()

    def _stop_animations(self) -> None:
        for index in list(self._anims):
            self._stop_animation(index)
        self._release_after_press.clear()

    def _update_key(self, index: int) -> None:
        if index in self._active_skin.key_rects:
            self.update(self.menu_button_rect(index).united(self.slot_rect(index)).adjusted(-8, -8, 8, 8).toAlignedRect())

    # ------------------------------------------------------------------ mouse

    def mousePressEvent(self, event) -> None:
        position = event.position()
        if event.button() != Qt.MouseButton.LeftButton:
            self._cancel_press()  # Another button during a press ends the candidate.
            event.ignore()
            return
        menu_index = self._menu_button_at(position)
        if menu_index is not None:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._set_focus_index(menu_index, visible=False)
            self._show_menu(menu_index, self.mapToGlobal(self._menu_anchor(menu_index)))
            event.accept()
            return
        arrow = self._usable_arrow_at(position)
        if arrow is not None:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._arrow_press = arrow
            self._update_arrow(arrow)
            event.accept()
            return
        index = self.slot_at(position)
        if index is None:
            event.ignore()
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self._set_focus_index(index, visible=False)
        self._begin_press(index, "mouse", position)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        # The second click of a double click is an ordinary press, with no extra intent.
        self.mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        position = event.position()
        self._set_arrow_hover(self._usable_arrow_at(position))
        on_button = self._menu_button_at(position) is not None
        if on_button != self._pointer_on_menu_button:
            self._pointer_on_menu_button = on_button
            if self._hover_index is not None:
                self._update_key(self._hover_index)
        hover = self.slot_at(position)
        if hover is None and self._hover_index is not None and self.has_menu_button(self._hover_index):
            # The three-dot button overhangs its key; reaching for it must not hide it.
            if self._menu_button_native(self._hover_index).contains(self._to_native(position)):
                hover = self._hover_index
        if hover != self._hover_index:
            previous, self._hover_index = self._hover_index, hover
            for index in (previous, hover):
                if index is not None:
                    self._update_key(index)
        press = self._press
        if press is None or press.source != "mouse":
            return
        if not event.buttons() & Qt.MouseButton.LeftButton:
            self._cancel_press()
        elif (self._is_source(press.index)
              and (position - press.start).manhattanLength() >= QApplication.startDragDistance()):
            self._start_drag(press.index, position)
        elif hover != press.index:
            self._cancel_press()

    def mouseReleaseEvent(self, event) -> None:
        arrow, self._arrow_press = self._arrow_press, None
        if arrow is not None:
            self._update_arrow(arrow)
            if event.button() == Qt.MouseButton.LeftButton and self._usable_arrow_at(event.position()) == arrow:
                self._request_page(arrow)
            return
        press = self._press
        if event.button() != Qt.MouseButton.LeftButton or press is None or press.source != "mouse":
            return
        if self.slot_at(event.position()) == press.index:
            self._commit_press()
        else:
            self._cancel_press()

    def leaveEvent(self, event) -> None:
        self._set_arrow_hover(None)
        if self._hover_index is not None:
            index, self._hover_index = self._hover_index, None
            self._update_key(index)
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:
        if event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason):
            self._focus_visible = True
            if self._focus_index is None:
                selected = self._selected_index()
                self._set_focus_index(selected if selected is not None else self._first_interactive(), visible=True)
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self._cancel_press()
        self._arrow_press = None
        self.update()
        super().focusOutEvent(event)

    def hideEvent(self, event) -> None:
        self._cancel_press()
        super().hideEvent(event)

    # ------------------------------------------------------------------ hardware arrows

    def _usable_arrow_at(self, position: QPointF) -> int | None:
        """Arrow under the pointer, only if the host's frame has a page in that direction."""
        skin, frame = self._active_skin, self._frame
        if not skin.arrow_rects or frame is None:
            return None
        step = skin.hit_arrow(self._to_native(position))
        return step if step is not None and 0 <= frame.page_index + step < frame.page_count else None

    def _set_arrow_hover(self, step: int | None) -> None:
        if step == self._arrow_hover:
            return
        previous, self._arrow_hover = self._arrow_hover, step
        for item in (previous, step):
            if item is not None:
                self._update_arrow(item)
        self._show_arrow_tip(step)

    def _update_arrow(self, step: int) -> None:
        if step in self._active_skin.arrow_rects:
            self.update(self.arrow_rect(step).adjusted(-2, -2, 2, 2).toAlignedRect())

    def _show_arrow_tip(self, step: int | None) -> None:
        tip = self._arrow_tip
        if step is None:
            tip.hide()
            return
        scale, _, _ = self._canvas()
        font_px = max(12, round(21 * scale))
        tip.setStyleSheet(f"#keypadArrowTip {{ background:#000000; color:#ffffff; font-family:'{FONT_FAMILY}'; "
                          f"font-weight:700; font-size:{font_px}px; padding:{round(9 * scale) + 2}px {round(14 * scale) + 3}px; }}")
        tip.setText("Nächste Seite" if step > 0 else "Vorherige Seite")
        tip.adjustSize()
        rect = self.arrow_rect(step)
        gap = round(28 * scale)
        x = rect.right() + gap if step > 0 else rect.left() - gap - tip.width()
        y = rect.center().y() - tip.height() / 2
        if x < 2 or x + tip.width() > self.width() - 2:
            # No room beside the arrow, as in a tightly sized widget: never cover the arrow itself.
            x = min(max(2, rect.left()), self.width() - tip.width() - 2)
            y = rect.top() - tip.height() - round(6 * scale)
        tip.move(round(x), round(y))
        tip.raise_()
        tip.show()

    # ------------------------------------------------------------------ keyboard

    def _first_interactive(self) -> int | None:
        return next((index for index in sorted(self._reported()) if self._interactive(index)), None)

    def _set_focus_index(self, index: int | None, *, visible: bool) -> None:
        previous, self._focus_index = self._focus_index, index
        self._focus_visible = visible
        for key in (previous, index):
            if key is not None:
                self._update_key(key)
        self._update_description()

    def _move_focus(self, dx: int, dy: int) -> None:
        indices = [index for index in self._reported() if self._interactive(index)]
        if not indices:
            return
        current = self._focus_index
        if current is None:
            self._set_focus_index(self._first_interactive(), visible=True)
            return
        origin = self._active_skin.key_rect(current).center()
        best, best_score = None, 0.0
        for index in indices:
            delta = self._active_skin.key_rect(index).center() - origin
            along, across = delta.x() * dx + delta.y() * dy, abs(delta.x() * dy) + abs(delta.y() * dx)
            if index != current and along > 0:
                score = along + 3 * across
                if best is None or score < best_score:
                    best, best_score = index, score
        self._set_focus_index(best if best is not None else current, visible=True)

    @staticmethod
    def _edit_command(event: QKeyEvent) -> str | None:
        key, modifiers = event.key(), event.modifiers()
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if key == Qt.Key.Key_F2 and not ctrl and not shift:
            return "symbol"
        if ctrl and key == Qt.Key.Key_Z:
            return "redo" if shift else "undo"
        if ctrl and not shift and key == Qt.Key.Key_Y:
            return "redo"
        for standard, name in ((QKeySequence.StandardKey.Cut, "cut"), (QKeySequence.StandardKey.Copy, "copy"),
                               (QKeySequence.StandardKey.Paste, "paste"), (QKeySequence.StandardKey.Delete, "remove")):
            if event.matches(standard):
                return name
        return None

    def _run_edit_command(self, command: str, index: int | None) -> None:
        if not self.editing_active():
            return
        if command == "undo":
            self.undoRequested.emit()
        elif command == "redo":
            self.redoRequested.emit()
        elif index is not None:
            handler = {"cut": self._cut, "copy": self._copy, "paste": self._paste,
                       "remove": self._remove, "symbol": self._request_symbol}[command]
            handler(index)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            if self._press is not None:
                self._cancel_press()
            elif self._clipboard is not None:
                self._clipboard = None
                self.update()
            else:
                event.ignore()
            return
        if key in _ACTIVATION_KEYS:
            index = self._focus_index
            if index is None or not self._interactive(index):
                event.ignore()  # Nothing to activate, e.g. the default button of a host dialog.
            elif not event.isAutoRepeat() and self._press is None:
                self._begin_press(index, "key", QPointF())
            return
        moves = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if key in moves:
            self._cancel_press()
            self._move_focus(*moves[key])
        elif key == Qt.Key.Key_PageUp:
            self._request_page(-1)
        elif key == Qt.Key.Key_PageDown:
            self._request_page(+1)
        else:
            command = self._edit_command(event) if self.editing_active() else None
            if command is None:
                event.ignore()
            else:
                self._run_edit_command(command, self._focus_index)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        press = self._press
        if event.key() in _ACTIVATION_KEYS and not event.isAutoRepeat() and press is not None and press.source == "key":
            self._commit_press()
        else:
            event.ignore()

    def event(self, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.ShortcutOverride and self.editing_active():
            # Claim edit keys over window-level QActions, but only while editing.
            # PySide6 hands this event over as plain QEvent, so view it as QKeyEvent.
            key_event = wrapInstance(getCppPointer(event)[0], QKeyEvent)
            if self._edit_command(key_event) is not None:
                event.accept()
                return True
        elif kind == QEvent.Type.ToolTip:
            # Unavailable tiles are inert for input but can explain why.
            index = self._active_skin.hit_key(self._to_native(QPointF(event.pos())), self._reported())
            slot = self._slots.get(index) if index is not None else None
            text = (slot.tooltip or slot.label) if slot is not None else ""
            if text:
                QToolTip.showText(event.globalPos(), text, self, self.slot_rect(index).toAlignedRect())
            else:
                QToolTip.hideText()
            return True
        return super().event(event)

    # ------------------------------------------------------------------ context menu

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        if not self.editing_active():
            event.ignore()
            return
        if event.reason() == QContextMenuEvent.Reason.Keyboard:
            index = self._focus_index
            position = self.slot_rect(index).center().toPoint() if index is not None else None
        else:
            index = self.slot_at(QPointF(event.pos()))
            position = event.pos()
        if index is None:
            event.ignore()
            return
        self._set_focus_index(index, visible=self._focus_visible)
        self._show_menu(index, self.mapToGlobal(position))
        event.accept()

    def _add_action(self, menu: QMenu, name: str, text: str, enabled: bool, command: str, index: int,
                    icon: str, hint: str) -> None:
        action = menu.addAction(_menu_icon(icon), text)
        action.setObjectName(name)
        action.setEnabled(enabled)
        action.setToolTip(hint)
        frame = self._frame
        action.triggered.connect(
            lambda _checked=False: self._run_edit_command(command, index) if self._frame is frame else None)

    def _menu_style(self) -> str:
        scale, _, _ = self._canvas()
        size = round(min(22.0, max(13.0, 22.0 * scale)))
        vertical = round(size * 0.62)
        return (f"QMenu {{ background:#000000; color:#ffffff; border:1px solid #333333; padding:6px 0; "
                f"font-family:'{FONT_FAMILY}'; font-size:{size}px; font-weight:600; icon-size:{round(size * 1.3)}px; }}"
                f"QMenu::item {{ padding:{vertical}px {round(size * 0.9)}px {vertical}px {round(size * 1.05)}px; "
                f"background:transparent; }}"
                "QMenu::item:selected { background:#1e1e1e; }"
                "QMenu::item:disabled { color:#7c7c7c; }"
                f"QMenu::icon {{ padding-left:{round(size * 0.9)}px; }}"
                "QMenu::separator { height:1px; background:#333333; margin:6px 12px; }")

    def _build_menu(self, index: int) -> QMenu | None:
        if not self.editing_active() or self._frame is None:
            return None
        menu = QMenu(self)
        menu.setObjectName("keypadSlotMenu")
        menu.setToolTipsVisible(True)
        menu.setStyleSheet(self._menu_style())
        source = self._is_source(index)
        if source or self._is_free_target(index):
            self._add_action(menu, "keypadCut", "Aktion schneiden", source, "cut", index, "cut", "Strg+X")
            self._add_action(menu, "keypadCopy", "Aktion kopieren", source, "copy", index, "copy", "Strg+C")
            self._add_action(menu, "keypadPaste", "Aktion einfügen", self._can_paste(index), "paste", index, "paste", "Strg+V")
            self._add_action(menu, "keypadRemove", "Aktion löschen", source, "remove", index, "remove", "Entf")
            menu.addSeparator()
        if self._can_edit_symbol(index):
            self._add_action(menu, "keypadSymbol", "Symbol bearbeiten", True, "symbol", index, "symbol", "F2")
            menu.addSeparator()
        self._add_action(menu, "keypadUndo", "Rückgängig", self._can_undo, "undo", index, "undo", "Strg+Z")
        self._add_action(menu, "keypadRedo", "Wiederholen", self._can_redo, "redo", index, "redo", "Strg+Y")
        return menu

    def _menu_anchor(self, index: int):
        """Menu corner relative to the three-dot button, as in DreiPunkteMenu.png."""
        button = self.menu_button_rect(index)
        scale, _, _ = self._canvas()
        return QPointF(button.center().x(), button.bottom() - 14 * scale).toPoint()

    def _show_menu(self, index: int, global_position) -> None:
        menu = self._build_menu(index)
        if menu is None:
            return
        self._cancel_press()
        self._menu, self._menu_index = menu, index
        self._update_key(index)
        try:
            self._exec_menu(menu, global_position)
        finally:
            self._menu = self._menu_index = None
            menu.deleteLater()
            self._update_key(index)

    def _exec_menu(self, menu: QMenu, global_position) -> None:
        menu.exec(global_position)

    # ------------------------------------------------------------------ edit intents

    def _emit_edit(self, operation: str, base_revision: str, *, source: SlotAddress | None = None,
                   target: SlotAddress | None = None, action_id: str | None = None,
                   action_parameter: str | None = None) -> None:
        self.editRequested.emit(EditRequest(uuid.uuid4().hex, base_revision, operation, source, target,
                                            action_id, action_parameter))

    def _mark_clipboard(self, kind: str, index: int) -> None:
        if not self._is_source(index):
            return
        slot = self._slots[index]
        self._clipboard = _Clipboard(kind, self._address(index), self._frame.context_id, self._frame.revision,
                                     slot.action_id, slot.action_parameter)
        self.update()

    def _cut(self, index: int) -> None:
        """Only remember the source. Nothing leaves the slot before a committed paste."""
        self._mark_clipboard("cut", index)

    def _copy(self, index: int) -> None:
        self._mark_clipboard("copy", index)

    def _can_paste(self, index: int) -> bool:
        clip, frame = self._clipboard, self._frame
        return (clip is not None and frame is not None and clip.base_revision == frame.revision
                and self._is_free_target(index))

    def _paste(self, index: int) -> None:
        if not self._can_paste(index):
            return
        clip = self._clipboard
        self._emit_edit("move" if clip.kind == "cut" else "copy", clip.base_revision, source=clip.source,
                        target=self._address(index), action_id=clip.action_id,
                        action_parameter=clip.action_parameter)

    def _remove(self, index: int) -> None:
        if self._is_source(index):
            self._emit_edit("remove", self._frame.revision, source=self._address(index))

    def _request_symbol(self, index: int) -> None:
        if self._can_edit_symbol(index):
            self.symbolEditRequested.emit(self._address(index))

    # ------------------------------------------------------------------ drag and drop

    def _start_drag(self, index: int, position: QPointF) -> None:
        source = self._address(index)
        frame = self._frame
        self._drag_slot = self._slots[index]
        pixmap, hotspot = drag_label_pixmap(self._drag_slot.label or self._drag_slot.action_id, self.devicePixelRatioF())
        hotspot = hotspot.toPoint()
        self._cancel_press()
        mime = QMimeData()
        mime.setData(SLOT_REF_MIME, QByteArray(encode_slot_ref(
            SlotRef(self._instance, frame.context_id, frame.revision, source))))
        self._drag_source = source
        self.update()
        try:
            self._exec_drag(mime, pixmap, hotspot)
        finally:
            self._drag_source = None
            self._drag_slot = None
            self._drag_active = False
            self._clear_drop()

    def _exec_drag(self, mime: QMimeData, pixmap: QPixmap, hotspot) -> None:
        # QDrag takes ownership of the mime data and deletes itself afterwards.
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(pixmap)
        drag.setHotSpot(hotspot)
        drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction, Qt.DropAction.MoveAction)

    def _internal_ref(self, mime: QMimeData) -> SlotRef | None:
        if not mime.hasFormat(SLOT_REF_MIME):
            return None
        ref = decode_slot_ref(bytes(mime.data(SLOT_REF_MIME)))
        frame = self._frame
        if (ref is None or frame is None or ref.instance != self._instance or ref.source != self._drag_source
                or ref.context_id != frame.context_id or ref.source.view_id != frame.view_id
                or ref.revision != frame.revision):
            return None
        return ref

    def _external_ref(self, mime: QMimeData) -> tuple[str, str | None] | None:
        return decode_action_ref(bytes(mime.data(ACTION_REF_MIME))) if mime.hasFormat(ACTION_REF_MIME) else None

    def _acceptable_payload(self, mime: QMimeData) -> bool:
        return (self._placement_edit_allowed and self.editing_active() and self._frame is not None
                and (self._internal_ref(mime) is not None or self._external_ref(mime) is not None))

    def _drop_action(self, event) -> Qt.DropAction:
        if self._internal_ref(event.mimeData()) is None:
            return Qt.DropAction.CopyAction
        copying = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        return Qt.DropAction.CopyAction if copying else Qt.DropAction.MoveAction

    def _clear_drop(self) -> None:
        self._spring_timer.stop()
        self._spring_page = None
        self._drop_index = None
        self.update()

    def _pager_page_at(self, position: QPointF) -> int | None:
        """Page reachable under the pointer during a drag: hardware arrow, page cell or page button."""
        frame = self._frame
        step = self._usable_arrow_at(position)
        if step is not None:
            return frame.page_index + step
        if not self._pager.isVisible():
            return None
        point = position.toPoint() - self._pager.pos()
        if self.page_bar.isVisible() and self.page_bar.geometry().contains(point):
            page = self.page_bar.page_at(QPointF(point - self.page_bar.pos()))
            return page if page != frame.page_index else None
        for button, offset in ((self.prev_page_button, -1), (self.next_page_button, +1)):
            if button.isVisible() and button.isEnabled() and button.geometry().contains(point):
                return frame.page_index + offset
        return None

    def _update_spring(self, position: QPointF) -> None:
        """Hovering a page control during a drag requests that page from the host."""
        page = self._pager_page_at(position)
        if page != self._spring_page:
            self._spring_page = page
            self._spring_timer.stop()
            if page is not None:
                self._spring_timer.start()

    def _fire_spring_page(self) -> None:
        page, self._spring_page = self._spring_page, None
        if page is not None and self._frame is not None and 0 <= page < self._frame.page_count:
            self.pageRequested.emit(page)

    def dragEnterEvent(self, event) -> None:
        if self._acceptable_payload(event.mimeData()):
            self._drag_active = True
            self.update()
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if not self._acceptable_payload(event.mimeData()):
            self._clear_drop()
            event.ignore()
            return
        position = event.position()
        self._update_spring(position)
        native = self._to_native(position)
        index = self._active_skin.hit_key(native, self._reported())
        accepted = index is not None and self._is_free_target(index)
        if index != self._drop_index or accepted != self._drop_ok:
            self._drop_index, self._drop_ok = index, accepted
            self.update()
        if accepted:
            event.setDropAction(self._drop_action(event))
            event.accept()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        if self._drag_source is None:
            self._drag_active = False
        self._clear_drop()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._drag_active = False
        self._clear_drop()
        mime = event.mimeData()
        if not self._acceptable_payload(mime):
            event.ignore()
            return
        index = self._active_skin.hit_key(self._to_native(event.position()), self._reported())
        if index is None or not self._is_free_target(index):
            event.ignore()
            return
        target = self._address(index)
        internal = self._internal_ref(mime)
        action = self._drop_action(event)
        revision = self._frame.revision
        event.setDropAction(action)
        event.accept()
        if internal is None:
            action_id, parameter = self._external_ref(mime)
            self._emit_edit("place", revision, target=target, action_id=action_id, action_parameter=parameter)
            return
        operation = "copy" if action == Qt.DropAction.CopyAction else "move"
        self._emit_edit(operation, revision, source=internal.source, target=target,
                        action_id=self._drag_slot.action_id, action_parameter=self._drag_slot.action_parameter)

    # ------------------------------------------------------------------ painting

    def _paint_body(self, painter: QPainter, scale: float, x: float, y: float) -> None:
        skin = self._active_skin
        ratio = self.devicePixelRatioF()
        width, height = skin.native_size
        key = (id(skin), round(scale, 5), ratio)
        if self._body_cache is None or self._body_key != key:
            pixmap = QPixmap(max(1, round(width * scale * ratio)), max(1, round(height * scale * ratio)))
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(Qt.GlobalColor.transparent)
            cached = QPainter(pixmap)
            cached.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                                  | QPainter.RenderHint.SmoothPixmapTransform)
            cached.scale(scale, scale)
            skin.paint_body(cached)
            cached.end()
            self._body_cache, self._body_key = pixmap, key
        painter.drawPixmap(QPointF(x, y), self._body_cache)

    def _paint_cover(self, painter: QPainter, scale: float, x: float, y: float) -> None:
        """Case image, smoothly resampled once per size so that its edges and logo stay clean."""
        skin = self._active_skin
        if skin.case_image is None:
            return
        ratio = self.devicePixelRatioF()
        width, height = skin.native_size
        key = (id(skin), round(scale, 5), ratio)
        if self._cover_cache is None or self._cover_key != key:
            target = QSize(max(1, round(width * scale * ratio)), max(1, round(height * scale * ratio)))
            scaled = skin.case_image if target == skin.case_image.size() else skin.case_image.scaled(
                target, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            pixmap = QPixmap.fromImage(scaled)
            pixmap.setDevicePixelRatio(ratio)
            self._cover_cache, self._cover_key = pixmap, key
        painter.drawPixmap(QPointF(x, y), self._cover_cache)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                               | QPainter.RenderHint.SmoothPixmapTransform)
        skin = self._active_skin
        if skin.backdrop:
            painter.fillRect(self.rect(), QColor(skin.backdrop))
        scale, x, y = self._canvas()
        self._paint_body(painter, scale, x, y)
        painter.save()
        painter.translate(x, y)
        painter.scale(scale, scale)
        on_top = [index for index in skin.key_rects if skin.is_device_art and self._is_lit(index)]
        for index in skin.key_rects:
            if index not in on_top:
                self._paint_key(painter, index, self.key_motion(index))
        painter.restore()
        self._paint_cover(painter, scale, x, y)
        painter.translate(x, y)
        painter.scale(scale, scale)
        for index in on_top:
            self._paint_key(painter, index, self.key_motion(index))
        for step in skin.arrow_rects:
            self._paint_arrow_state(painter, step)
        for index in self._reported():
            self._paint_state_rings(painter, index)
        for index in self._reported():
            self._paint_top_markers(painter, index)

    def _is_lit(self, index: int) -> bool:
        """An occupied LCD is black. An empty one stays grey; that is never overwritten by a state."""
        slot = self._slots.get(index)
        return self._frame is not None and index in self._reported() and slot is not None and slot.role in (
            "placement", "sdk_navigation")

    def _paint_key(self, painter: QPainter, index: int, motion: tuple[float, float]) -> None:
        skin = self._active_skin
        slot = self._slots.get(index)
        reported = self._frame is not None and index in self._reported()
        factor, offset = motion
        painter.save()
        if factor != 1.0 or offset != 0.0:
            center = skin.key_rect(index).center()
            painter.translate(center.x(), center.y() + offset)
            painter.scale(factor, factor)
            painter.translate(-center.x(), -center.y())
        inert = not reported or slot is None or slot.role == "unavailable"
        lit = self._is_lit(index)
        skin.paint_key_cap(painter, index, inert=inert, lit=lit)
        if slot is not None and reported:
            self._paint_slot_content(painter, index, slot)
            if lit:
                skin.paint_gloss(painter, index)
            self._paint_state_tints(painter, index, slot)
        painter.restore()

    def _paint_slot_content(self, painter: QPainter, index: int, slot: SlotData) -> None:
        skin = self._active_skin
        rect = skin.display_rect(index)
        image = self._images.get(index)
        painter.save()
        painter.setClipPath(skin.lcd_path(index))
        if image is not None:
            # A finished tile already contains its caption; label stays out of it.
            fitted = QSize(image.width(), image.height()).scaled(rect.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF(0, 0, fitted.width(), fitted.height())
            target.moveCenter(rect.center())
            painter.drawImage(target, image)
        elif slot.role == "placement":
            self._paint_caption(painter, rect, slot.label or slot.action_id, skin.palette.text)
        elif slot.role == "sdk_navigation":
            self._paint_caption(painter, rect, slot.label or "SDK-Navigation", skin.palette.navigation, small=True)
        elif slot.role == "unavailable":
            self._paint_caption(painter, rect, slot.label or "Nicht verfügbar", skin.palette.muted, small=True)
        elif slot.role == "empty" and self._is_free_target(index) and not skin.is_device_art:
            self._paint_caption(painter, rect, slot.label or "Frei", skin.palette.muted, small=True)
        elif slot.role == "empty" and slot.label:
            self._paint_caption(painter, rect, slot.label, skin.palette.muted, small=True)
        if slot.role == "sdk_navigation":
            # A reported role, not a claim about what the hardware key does.
            pen = QPen(QColor(skin.palette.navigation), 1.4, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(5, 5, -5, -5), 8, 8)
        painter.restore()

    def _fill_tint(self, painter: QPainter, index: int, color: str, opacity: float) -> None:
        tint = QColor(color)
        tint.setAlphaF(opacity)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tint)
        painter.drawPath(self._active_skin.lcd_path(index))

    def _paint_state_tints(self, painter: QPainter, index: int, slot: SlotData) -> None:
        """Dynamic colour layers below the case. They never replace the occupied or empty base."""
        skin = self._active_skin
        tone = skin.palette
        if self._drag_active:
            if index == self._drop_index and self._drop_ok:
                self._fill_tint(painter, index, tone.tint, TINT_DROP_TARGET)
            elif self._is_free_target(index):
                self._fill_tint(painter, index, tone.tint, TINT_DROP_CANDIDATE)
        elif index == self._hover_index and self._interactive(index) and not self._pointer_on_menu_button and self._menu is None:
            self._fill_tint(painter, index, tone.tint, TINT_HOVER)
        address = self._address(index)
        clip = self._clipboard
        if address == self._drag_source:
            self._fill_tint(painter, index, tone.tint, TINT_DRAG_SOURCE)
        elif clip is not None and clip.kind == "cut" and clip.source == address:
            self._fill_tint(painter, index, "#000000", 0.5)
        progress = self._progress.get(index, 0.0)
        if progress > 0.0:
            self._fill_tint(painter, index, tone.pressed_tint, 0.14 * progress)

    def _paint_arrow_state(self, painter: QPainter, step: int) -> None:
        skin = self._active_skin
        if step != self._arrow_hover and step != self._arrow_press:
            return
        tint = QColor(skin.palette.tint)
        tint.setAlphaF(0.32 if step == self._arrow_press else TINT_HOVER)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tint)
        painter.drawPath(skin.arrow_path(step))

    def _paint_caption(self, painter: QPainter, rect: QRectF, text: str, color: str, *, small: bool = False) -> None:
        """Text of a slot without a finished tile: small, on one line if possible, wrapped otherwise."""
        box = rect.adjusted(2, 4, -2, -4) if self._active_skin.is_device_art else rect.adjusted(8, 6, -8, -6)
        font = QFont(FONT_FAMILY)
        font.setWeight(QFont.Weight.DemiBold)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        font.setStyleStrategy(QFont.StyleStrategy.NoSubpixelAntialias)
        flags = int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap)
        sizes = (14, 12, 11) if small else (17, 16, 15, 13)
        for size in sizes:
            font.setPixelSize(size)
            if QFontMetricsF(font).horizontalAdvance(text) <= box.width():
                break
        else:
            for size in sizes:
                font.setPixelSize(size)
                needed = QFontMetricsF(font).boundingRect(box, flags, text)
                if needed.height() <= box.height() and needed.width() <= box.width():
                    break
            else:
                metrics = QFontMetricsF(font)
                lines = max(1, int(box.height() // metrics.lineSpacing()))
                text = metrics.elidedText(text, Qt.TextElideMode.ElideRight, box.width() * lines * 0.9)
        painter.setFont(font)
        painter.setPen(QColor(color))
        painter.drawText(box, flags, text)

    def _paint_top_markers(self, painter: QPainter, index: int) -> None:
        """Markers above the case. The three-dot button overhangs the key on purpose."""
        slot = self._slots.get(index)
        if slot is None:
            return
        skin = self._active_skin
        clip = self._clipboard
        if clip is not None and clip.source == self._address(index):
            pen = QPen(QColor(skin.palette.text), 1.6, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(skin.lcd_path(index))
        if self.menu_button_visible(index):
            self._paint_menu_button(painter, index)
        elif self.editing_active() and slot.role in ("placement", "empty") and not self.has_menu_button(index):
            self._paint_lock(painter, index)

    def _paint_menu_button(self, painter: QPainter, index: int) -> None:
        button = self._menu_button_native(index)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#000000"))
        painter.drawRoundedRect(button, button.width() * 0.08, button.width() * 0.08)
        painter.setBrush(QColor("#ffffff"))
        dot = button.width() * 0.058
        center = button.center()
        for step in (-1, 0, 1):
            painter.drawEllipse(QPointF(center.x(), center.y() + step * button.width() * 0.24), dot, dot)

    def _paint_lock(self, painter: QPainter, index: int) -> None:
        """Shows in edit mode why this key offers no menu."""
        key = self._active_skin.key_rect(index)
        badge = QRectF(key.right() - 34, key.top() + 6, 28, 24)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 150))
        painter.drawRoundedRect(badge, badge.height() / 3, badge.height() / 3)
        tone = QColor(255, 255, 255, 215)
        unit = badge.height() / 24
        center = badge.center()
        body = QRectF(center.x() - 6 * unit, center.y() - 1 * unit, 12 * unit, 8 * unit)
        painter.setPen(QPen(tone, 1.8 * unit))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(QRectF(center.x() - 4 * unit, center.y() - 7 * unit, 8 * unit, 12 * unit), 0, 180 * 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tone)
        painter.drawRoundedRect(body, 1.5 * unit, 1.5 * unit)

    def _ring(self, painter: QPainter, index: int, color: str, width: float, outset: float,
              style: Qt.PenStyle = Qt.PenStyle.SolidLine) -> None:
        pen = QPen(QColor(color), width, style)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._active_skin.key_path(index, outset))

    def _paint_state_rings(self, painter: QPainter, index: int) -> None:
        """Selection, focus and drop stay independent and may show together."""
        tone = self._active_skin.palette
        if index == self._selected_index():
            self._ring(painter, index, tone.selected, 2.5, 3.0)
        if index == self._focus_index and self._focus_visible and self.hasFocus():
            self._ring(painter, index, tone.focus, 1.5, -5.0, Qt.PenStyle.DashLine)
        if not self._drag_active:
            return
        if index == self._drop_index and not self._drop_ok:
            self._ring(painter, index, tone.drop_refused, 2.5, 3.0)
        elif self._is_free_target(index):
            self._ring(painter, index, tone.drop_border, 2.0, 4.0, Qt.PenStyle.DashLine)


def _menu_icon(kind: str) -> QIcon:
    """Self-drawn line icons in the style of the reference menu."""
    icon = QIcon()
    for mode, color in ((QIcon.Mode.Normal, "#ffffff"), (QIcon.Mode.Active, "#ffffff"), (QIcon.Mode.Disabled, "#7c7c7c")):
        pixmap = QPixmap(48, 48)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(color), 3.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        _ICON_PAINTERS[kind](painter)
        painter.end()
        icon.addPixmap(pixmap, mode)
    return icon


def _icon_cut(p: QPainter) -> None:
    p.drawEllipse(QPointF(11, 13), 6, 6)
    p.drawEllipse(QPointF(11, 35), 6, 6)
    p.drawLine(QPointF(16, 16), QPointF(42, 34))
    p.drawLine(QPointF(16, 32), QPointF(42, 14))


def _icon_copy(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(16, 15, 24, 27), 3, 3)
    p.drawPolyline([QPointF(10, 33), QPointF(8, 33), QPointF(8, 6), QPointF(32, 6), QPointF(32, 9)])


def _icon_paste(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(8, 9, 24, 33), 3, 3)
    p.drawRoundedRect(QRectF(14, 5, 12, 8), 2, 2)
    p.drawRoundedRect(QRectF(23, 22, 19, 21), 2, 2)
    p.drawLine(QPointF(28, 29), QPointF(37, 29))
    p.drawLine(QPointF(28, 36), QPointF(37, 36))


def _icon_remove(p: QPainter) -> None:
    p.drawLine(QPointF(8, 12), QPointF(40, 12))
    p.drawPolyline([QPointF(18, 12), QPointF(18, 6), QPointF(30, 6), QPointF(30, 12)])
    p.drawPolyline([QPointF(12, 12), QPointF(14, 42), QPointF(34, 42), QPointF(36, 12)])
    p.drawLine(QPointF(20, 20), QPointF(20, 34))
    p.drawLine(QPointF(28, 20), QPointF(28, 34))


def _icon_symbol(p: QPainter) -> None:
    p.drawPolygon([QPointF(8, 40), QPointF(11, 29), QPointF(32, 8), QPointF(40, 16), QPointF(19, 37)])
    p.drawLine(QPointF(27, 13), QPointF(35, 21))


def _icon_undo(p: QPainter) -> None:
    p.drawArc(QRectF(10, 12, 28, 26), 120 * 16, -210 * 16)
    p.drawPolyline([QPointF(8, 8), QPointF(10, 20), QPointF(22, 18)])


def _icon_redo(p: QPainter) -> None:
    p.translate(48, 0)
    p.scale(-1, 1)
    _icon_undo(p)


_ICON_PAINTERS = {"cut": _icon_cut, "copy": _icon_copy, "paste": _icon_paste, "remove": _icon_remove,
                  "symbol": _icon_symbol, "undo": _icon_undo, "redo": _icon_redo}
