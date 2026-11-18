"""Qt-freie, nur lesende Hilfsprüfungen für die Fakten des geführten Ablaufs.

Nichts hier schreibt, importiert Benutzer-Code oder führt ihn aus: die
Handlerdatei wird ausschließlich statisch (AST) gelesen.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

HANDLER_LIMIT = 262_144
ASSET_KEYS = ("icon", "icon_template", "symbol")


def registered_handlers(file: Path) -> set[str] | None:
    """Handler-IDs aus ``host.register_handler("<id>", …)``; None, wenn nicht lesbar."""
    try:
        if file.stat().st_size > HANDLER_LIMIT:
            return None
        tree = ast.parse(file.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return None
    found = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "register_handler" and node.args
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            found.add(node.args[0].value)
    return found


def asset_references(raw: dict) -> dict[str, list[str]]:
    """Projektrelative Bild-/Vorlagenpfade je Aktions-ID (``""`` = Plugin-Standardvorlage)."""
    result: dict[str, list[str]] = {}
    default = raw.get("plugin", {}).get("default_icon_template")
    if isinstance(default, str):
        result[""] = [default]
    for action in raw.get("actions", ()):
        refs = [action[k] for k in ASSET_KEYS if isinstance(action.get(k), str)]
        refs += [v for v in (action.get("parameter_symbols") or {}).values() if isinstance(v, str)]
        refs += [s["image"] for s in action.get("states", ()) if isinstance(s.get("image"), str)]
        if refs:
            result[action["id"]] = refs
    return result


def missing_assets(raw: dict, project_dir: Path | None) -> tuple[str, ...]:
    if project_dir is None:
        return ()
    missing = []
    for refs in asset_references(raw).values():
        for ref in refs:
            if ref not in missing and not (project_dir / ref).is_file():
                missing.append(ref)
    return tuple(missing)


def fingerprint(files, *extra: str) -> str:
    """SHA-256 über den gespeicherten Stand der genannten Dateien (fehlende zählen als leer)."""
    digest = hashlib.sha256()
    for file in files:
        digest.update(str(file).encode("utf-8") + b"\0")
        try:
            digest.update(hashlib.sha256(Path(file).read_bytes()).digest() if file else b"-")
        except OSError:
            digest.update(b"-")
    for value in extra:
        digest.update(b"\0" + str(value).encode("utf-8"))
    return digest.hexdigest()


HANDLER_TEMPLATE = '''"""Python-Handler für das Plugin „{name}“.

Diese Datei wird vom Host des Plugins geladen, nicht vom Studio.
Jeder Handler wird aufgerufen, wenn eine zugeordnete Aktion ausgelöst wird.
"""


def register(host):
{body}
'''
HANDLER_BLOCK = '''    def {function}(payload, context):
        # context.component_id    -> ID der ausgelösten Aktion
        # context.action_parameter -> gewählte Variante der Aktion oder None
        # context.operation        -> Art des Aufrufs (Tastendruck, Drehung, …)
        # Hier deinen Code ergänzen.
        return {{"ok": True}}

    host.register_handler("{handler}", "invoke", {function})
'''


def handler_snippet(handlers) -> str:
    """Registrierungsblöcke zum Einfügen in eine bestehende Handlerdatei."""
    return "\n".join(_blocks(handlers)).rstrip("\n")


def handler_template(display_name: str, handlers) -> str:
    """Sofort lauffähige Handlerdatei, die jeden genannten Handler registriert.

    Der Host akzeptiert nur Handler, die mindestens eine Aktion verwendet; der
    Aufrufer übergibt deshalb nur verwendete Handler.
    """
    blocks = _blocks(handlers)
    body = "\n".join(blocks) if blocks else "    pass\n"
    return HANDLER_TEMPLATE.format(name=display_name.replace('"', "'"), body=body.rstrip("\n"))


def _blocks(handlers) -> list[str]:
    blocks, used = [], set()
    for handler in handlers:
        name = "".join(c if c.isalnum() else "_" for c in handler).strip("_").lower() or "handler"
        if name[0].isdigit():
            name = "h_" + name
        base, suffix = name, 2
        while name in used:
            name, suffix = f"{base}_{suffix}", suffix + 1
        used.add(name)
        blocks.append(HANDLER_BLOCK.format(function=name, handler=handler.replace('"', "")))
    return blocks
