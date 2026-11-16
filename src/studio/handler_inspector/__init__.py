"""HandlerInspector: Handler eines nativen Projekts anlegen, umbenennen und löschen."""
from .lifecycle import (HandlerDeleteCheck, HandlerError, check_handler_delete, handler_usage,
                        propose_handler_create, propose_handler_delete, propose_handler_rename,
                        suggest_handler_id)
from .widget import HandlerInspectorWidget

__all__ = ["HandlerDeleteCheck", "HandlerError", "HandlerInspectorWidget", "check_handler_delete",
           "handler_usage", "propose_handler_create", "propose_handler_delete", "propose_handler_rename",
           "suggest_handler_id"]
