"""Qt-freie Handler-Lebenszyklen: defensive Vorschläge, keine Session-/Dateiwrites.

Gleiches Muster wie ``action_inspector/lifecycle.py``: Der Host korreliert
Projekttoken und Revision und committet genau einmal über die native Session.
Der native Parser bleibt der normative Validator.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from adapters.logitech.native import parse_native_project
from core.ids import is_valid_id


class HandlerError(ValueError):
    pass


def suggest_handler_id(project, name="neu"):
    used = {h["id"] for h in project["handlers"]} | {a["id"] for a in project["actions"]}
    base = "handler." + name
    result, suffix = base, 2
    while result in used:
        result = f"{base}-{suffix}"
        suffix += 1
    return result


def handler_usage(project, handler_id):
    """IDs der Aktionen, die diesen Handler verwenden."""
    return tuple(a["id"] for a in project["actions"] if a.get("handler") == handler_id)


def _validated(proposed):
    try:
        parse_native_project(proposed)
    except ValueError as exc:
        raise HandlerError(str(exc)) from exc
    return proposed


def _check_new_id(project, handler_id):
    if not is_valid_id(handler_id):
        raise HandlerError("Ungültige Handler-ID. Beispiel: handler.licht (klein, ohne Leerzeichen).")
    if any(h["id"] == handler_id for h in project["handlers"]):
        raise HandlerError("Diese Handler-ID existiert bereits; bitte eine eindeutige ID eingeben.")
    if any(a["id"] == handler_id for a in project["actions"]):
        raise HandlerError("Diese ID gehört bereits einer Aktion; Handler und Aktionen teilen sich einen Namensraum.")


def propose_handler_create(project, handler_id):
    proposed = _validated(deepcopy(project))
    _check_new_id(proposed, handler_id)
    proposed["handlers"].append({"id": handler_id, "callback_id": handler_id})
    return _validated(proposed)


def propose_handler_rename(project, old_id, new_id):
    """Benennt den Handler und alle Verweise der Aktionen in einem Vorschlag um."""
    proposed = _validated(deepcopy(project))
    handler = next((h for h in proposed["handlers"] if h["id"] == old_id), None)
    if handler is None:
        raise HandlerError("Handler-ID nicht mehr vorhanden; nichts geändert.")
    if new_id == old_id:
        raise HandlerError("Die neue Handler-ID entspricht der bisherigen.")
    _check_new_id(proposed, new_id)
    if handler.get("callback_id") == old_id:
        handler["callback_id"] = new_id
    handler["id"] = new_id
    for action in proposed["actions"]:
        if action.get("handler") == old_id:
            action["handler"] = new_id
    return _validated(proposed)


@dataclass(frozen=True)
class HandlerDeleteCheck:
    handler_id: str
    references: tuple[str, ...]
    reason: str

    @property
    def allowed(self):
        return not self.reason


def check_handler_delete(project, handler_id):
    if not any(h["id"] == handler_id for h in project["handlers"]):
        raise HandlerError("Handler-ID nicht mehr vorhanden; nichts geändert.")
    references = handler_usage(project, handler_id)
    reason = ""
    if references:
        reason = (f"{len(references)} Aktion(en) verwenden diesen Handler: " + ", ".join(references) +
                  ". Zuerst im Aktionsinspektor einen anderen Handler zuordnen.")
    elif len(project["handlers"]) == 1:
        reason = "Der letzte Handler darf nicht gelöscht werden; das Projekt benötigt mindestens einen Handler."
    return HandlerDeleteCheck(handler_id, references, reason)


def propose_handler_delete(project, handler_id):
    proposed = _validated(deepcopy(project))
    check = check_handler_delete(proposed, handler_id)
    if not check.allowed:
        raise HandlerError(check.reason)
    proposed["handlers"] = [h for h in proposed["handlers"] if h["id"] != handler_id]
    return _validated(proposed)
