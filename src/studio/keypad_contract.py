"""Transient SDK-facing DTOs for a Keypad preview; no project persistence."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from PySide6.QtGui import QImage

DisplayMode = Literal["preview", "edit"]
SlotRole = Literal["empty", "placement", "sdk_navigation", "unavailable"]
NavigationArea = Literal["None", "ButtonArea", "EncoderArea"]
EditOperation = Literal["move", "copy", "place", "remove"]


@dataclass(frozen=True)
class NavigationCapability:
    """Device-specific result supplied by the SDK adapter, never guessed by UI."""

    device_type: str
    area: NavigationArea
    content_slots: tuple[int, ...]
    navigation_slots: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        all_slots = self.content_slots + self.navigation_slots
        if not self.device_type or self.area not in ("None", "ButtonArea", "EncoderArea"):
            raise ValueError("Invalid SDK navigation capability")
        if any(type(slot) is not int or slot < 0 for slot in all_slots) or len(set(all_slots)) != len(all_slots):
            raise ValueError("SDK slot indices must be unique non-negative integers")


@dataclass(frozen=True)
class SlotData:
    physical_index: int
    role: SlotRole
    placement_id: str | None = None
    action_id: str | None = None
    action_parameter: str | None = None
    label: str = ""
    tile_image: QImage | None = None
    editable: bool = True
    # Host-resolved display value; never derived from physical_index by the UI.
    logical_position: int | None = None
    tooltip: str = ""

    def __post_init__(self) -> None:
        if type(self.physical_index) is not int or self.physical_index < 0:
            raise ValueError("physical_index must be non-negative")
        if self.logical_position is not None:
            if type(self.logical_position) is not int or self.logical_position < 0:
                raise ValueError("logical_position must be a non-negative integer or None")
            if self.role != "placement":
                raise ValueError("Only placement slots can carry a logical_position")
        if self.role == "placement" and (not self.placement_id or not self.action_id):
            raise ValueError("Placement slots require placement_id and action_id")
        if self.role != "placement" and (self.placement_id is not None or self.action_id is not None):
            raise ValueError("Non-placement slots cannot claim project placement identity")
        if self.role in ("sdk_navigation", "unavailable") and self.editable:
            object.__setattr__(self, "editable", False)


@dataclass(frozen=True)
class KeypadFrame:
    context_id: str
    view_id: str
    revision: str
    capability: NavigationCapability
    slots: tuple[SlotData, ...]
    # Resolved outside the UI; the widget only displays them and requests pages.
    page_index: int = 0
    page_count: int = 1

    def __post_init__(self) -> None:
        if type(self.page_count) is not int or self.page_count < 1:
            raise ValueError("page_count must be an integer >= 1")
        if type(self.page_index) is not int or not 0 <= self.page_index < self.page_count:
            raise ValueError("page_index must be within 0..page_count-1")
        indices = [slot.physical_index for slot in self.slots]
        allowed = set(self.capability.content_slots + self.capability.navigation_slots)
        if len(set(indices)) != len(indices):
            raise ValueError("A physical slot occurs more than once")
        if any(index not in allowed for index in indices):
            raise ValueError("Frame contains a slot not reported by the SDK capability")


@dataclass(frozen=True)
class KeypadViewState:
    """View-only state. Preview is intentionally the safe default."""

    frame: KeypadFrame
    mode: DisplayMode = "preview"

    def with_mode(self, mode: DisplayMode) -> "KeypadViewState":
        if mode not in ("preview", "edit"):
            raise ValueError("mode must be preview or edit")
        return replace(self, mode=mode)

    @property
    def editing_enabled(self) -> bool:
        return self.mode == "edit"


@dataclass(frozen=True)
class SlotAddress:
    """Transient source/target of a UI intent; placement_id None means an empty slot."""

    view_id: str
    page_index: int
    physical_index: int
    placement_id: str | None = None

    def __post_init__(self) -> None:
        if not self.view_id or not isinstance(self.view_id, str):
            raise ValueError("SlotAddress requires a view_id")
        if type(self.page_index) is not int or self.page_index < 0:
            raise ValueError("SlotAddress.page_index must be non-negative")
        if type(self.physical_index) is not int or self.physical_index < 0:
            raise ValueError("SlotAddress.physical_index must be non-negative")


@dataclass(frozen=True)
class ActionOffer:
    """External offer to place an existing SDK action; never creates an action."""

    action_id: str
    display_name: str
    action_parameter: str | None = None
    tile_image: QImage | None = None

    def __post_init__(self) -> None:
        if not self.action_id or not isinstance(self.action_id, str):
            raise ValueError("ActionOffer requires an action_id")


@dataclass(frozen=True)
class EditRequest:
    """Change intent from the UI to the host, which alone validates and commits."""

    request_id: str
    base_revision: str
    operation: EditOperation
    source: SlotAddress | None = None
    target: SlotAddress | None = None
    action_id: str | None = None
    action_parameter: str | None = None

    def __post_init__(self) -> None:
        if not self.request_id or not self.base_revision:
            raise ValueError("EditRequest requires request_id and base_revision")
        if self.operation not in ("move", "copy", "place", "remove"):
            raise ValueError("operation must be move, copy, place or remove")
        if self.operation != "place" and (self.source is None or not self.source.placement_id):
            raise ValueError(self.operation + " requires a source placement")
        if self.operation == "place" and (self.source is not None or not self.action_id):
            raise ValueError("place requires an action_id and no source slot")
        if self.operation == "remove" and self.target is not None:
            raise ValueError("remove cannot have a target slot")
        if self.operation != "remove":
            if self.target is None:
                raise ValueError(self.operation + " requires a target slot")
            if self.target.placement_id is not None:
                raise ValueError("A target must be free: replace and swap are not operations")


__all__ = ["ActionOffer", "DisplayMode", "EditOperation", "EditRequest", "KeypadFrame", "KeypadViewState",
           "NavigationCapability", "SlotAddress", "SlotData", "SlotRole"]
