"""HandlerInspector: Handler eines nativen Projekts anlegen, umbenennen und löschen."""
from .lifecycle import (HandlerDeleteCheck, HandlerError, check_handler_delete, handler_usage,
                        propose_handler_create, propose_handler_delete, propose_handler_rename,
                        suggest_handler_id)


def __getattr__(name):
    """Das Qt-Widget erst bei Bedarf laden; der Lebenszyklus bleibt Qt-frei importierbar."""
    if name == "HandlerInspectorWidget":
        from .widget import HandlerInspectorWidget
        return HandlerInspectorWidget
    raise AttributeError(name)

__all__ = ["HandlerDeleteCheck", "HandlerError", "HandlerInspectorWidget", "check_handler_delete",
           "handler_usage", "propose_handler_create", "propose_handler_delete", "propose_handler_rename",
           "suggest_handler_id"]
