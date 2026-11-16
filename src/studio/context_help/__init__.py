"""Optional Studio context help. Data and registry imports work without Qt."""

from importlib import import_module

from .entries import HelpContext, HelpDisplayState, HelpEntry
from .registry import HelpRegistry, load_help_entries

__all__ = [
    "ContextHelpWidget", "HelpContext", "HelpCoordinator", "HelpDisplayState",
    "HelpEntry", "HelpRegistry", "load_help_entries",
]


def __getattr__(name: str):
    # Import Qt only for the two UI types.
    modules = {"ContextHelpWidget": ".widget", "HelpCoordinator": ".coordinator"}
    if name not in modules:
        raise AttributeError(name)
    value = getattr(import_module(modules[name], __name__), name)
    globals()[name] = value
    return value
