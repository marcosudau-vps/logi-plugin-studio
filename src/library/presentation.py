"""Shared optional presentation contract; omitted fields retain MVP behavior."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedVisual:
    """Transient selection result; never persisted and never a state owner."""

    variant_key: str | None
    text: str
    background: str
    foreground: str
    image_asset_id: str | None
    image_fit: str
    font_size: int | None


def resolve_visual(raw: dict, placement: dict | None,
                   variant_key: str | None = None) -> ResolvedVisual:
    """Resolve exactly one legacy presentation variant for technical renderers.

    The function does not read live state, mutate the project, or create a
    second presentation model.  An explicit preview key wins; otherwise the
    declared StateDefinition fallback is used before the lexical first key.
    """
    component = next((c for c in raw.get("components", []) if isinstance(c, dict) and
                      placement and c.get("id") == placement.get("component")), {})
    config = component.get("config") if isinstance(component.get("config"), dict) else {}
    text = str(config.get("display_name", "Kein Inhalt"))
    presentation = next((p for p in raw.get("presentations", []) if isinstance(p, dict) and
                         placement and p.get("id") == placement.get("presentation")), {})
    variants = presentation.get("variants", {})
    selected: str | None = None
    variant: dict = {}
    if isinstance(variants, dict) and variants:
        selected = variant_key if variant_key in variants else sorted(variants)[0]
        if variant_key is None:
            selector = next((b for b in raw.get("bindings", []) if isinstance(b, dict) and
                             b.get("kind") == "state" and
                             isinstance(b.get("target"), dict) and
                             b["target"].get("owner_kind") == "presentation" and
                             b["target"].get("owner_id") == presentation.get("id")), None)
            if selector and isinstance(selector.get("source"), dict):
                state = next((s for s in raw.get("states", []) if isinstance(s, dict) and
                              s.get("id") == selector["source"].get("owner_id")), {})
                fallback = state.get("fallback")
                if isinstance(fallback, str) and fallback in variants:
                    selected = fallback
        candidate = variants.get(selected)
        variant = candidate if isinstance(candidate, dict) else {}
    fit, font = presentation_options(variant)
    return ResolvedVisual(
        selected,
        str(variant.get("text", text)),
        variant.get("background", "#243449"),
        variant.get("foreground", "#ffffff"),
        variant.get("image") if isinstance(variant.get("image"), str) else None,
        fit,
        font,
    )


def presentation_options(variant: dict) -> tuple[str, int | None]:
    fit = variant.get("image_fit", "stretch")
    if fit not in ("stretch", "contain"):
        raise ValueError("Presentation image_fit must be stretch or contain")
    font = variant.get("font_size")
    if "font_size" in variant and (type(font) is not int or not 6 <= font <= 48):
        raise ValueError("Presentation font_size must be an integer from 6 to 48 at 116px")
    return fit, font


def image_bounds(width: int, height: int, size: int, fit: str) -> tuple[int, int, int, int]:
    if fit == "stretch":
        return 0, 0, size, size
    scale = min(size / width, size / height)
    w, h = max(1, int(width * scale)), max(1, int(height * scale))
    return (size - w) // 2, (size - h) // 2, w, h
