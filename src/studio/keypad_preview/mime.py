"""Versioned drag references. Plain data only: no images, code or callbacks.

A decoded reference is a proposal. It proves neither that an action exists nor
that it may be placed; the host verifies both when it receives the EditRequest.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from studio.keypad_contract import ActionOffer, SlotAddress

ACTION_REF_MIME = "application/vnd.logi-plugin-studio.action-ref+json"
SLOT_REF_MIME = "application/vnd.logi-plugin-studio.keypad-slot-ref+json"
REF_VERSION = 1
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_ID_LENGTH = 1024


def _load_object(payload: bytes) -> dict | None:
    if len(payload) > MAX_PAYLOAD_BYTES:
        return None
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != REF_VERSION:
        return None
    return data


def _text(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= MAX_ID_LENGTH


def encode_action_ref(offer: ActionOffer) -> bytes:
    """Only the reference crosses the drag boundary, never tile_image."""
    return json.dumps({"version": REF_VERSION, "action_id": offer.action_id,
                       "action_parameter": offer.action_parameter}).encode("utf-8")


def decode_action_ref(payload: bytes) -> tuple[str, str | None] | None:
    """Return (action_id, action_parameter), or None if the reference is invalid."""
    data = _load_object(payload)
    if data is None or not _text(data.get("action_id")):
        return None
    parameter = data.get("action_parameter")
    if parameter is not None and (not isinstance(parameter, str) or len(parameter) > MAX_ID_LENGTH):
        return None
    return data["action_id"], parameter


@dataclass(frozen=True)
class SlotRef:
    """Drag origin of an internal move or copy."""

    instance: str
    context_id: str
    revision: str
    source: SlotAddress


def encode_slot_ref(ref: SlotRef) -> bytes:
    return json.dumps({
        "version": REF_VERSION, "instance": ref.instance, "context_id": ref.context_id,
        "revision": ref.revision, "view_id": ref.source.view_id, "page_index": ref.source.page_index,
        "physical_index": ref.source.physical_index, "placement_id": ref.source.placement_id,
    }).encode("utf-8")


def decode_slot_ref(payload: bytes) -> SlotRef | None:
    data = _load_object(payload)
    if data is None:
        return None
    if not all(_text(data.get(key)) for key in ("instance", "context_id", "revision", "view_id", "placement_id")):
        return None
    try:
        source = SlotAddress(data["view_id"], data["page_index"], data["physical_index"], data["placement_id"])
    except ValueError:
        return None
    return SlotRef(data["instance"], data["context_id"], data["revision"], source)
